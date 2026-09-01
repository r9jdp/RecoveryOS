"""Task storage with durable idempotency and optimistic concurrency."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
    select,
    update,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .models import TaskRecord


class TaskVersionConflictError(RuntimeError):
    """Raised when a concurrent writer changed a task after it was read."""


class TaskIdempotencyConflictError(RuntimeError):
    """Raised when one idempotency key is reused for a different request scope."""


class TaskStore(Protocol):
    kind: str

    async def create_once(self, *, idempotency_key: str, task: TaskRecord) -> TaskRecord: ...

    async def get(self, task_id: str) -> TaskRecord | None: ...

    async def save(self, task: TaskRecord, *, expected_revision: int) -> None: ...

    async def is_ready(self) -> bool: ...

    async def close(self) -> None: ...


class InMemoryTaskStore:
    """Process-local mock store. It remains the safe default for local/demo mode."""

    kind = "memory"

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._tasks: dict[str, TaskRecord] = {}
        self._idempotency: dict[str, str] = {}

    async def create_once(self, *, idempotency_key: str, task: TaskRecord) -> TaskRecord:
        async with self._lock:
            existing_id = self._idempotency.get(idempotency_key)
            if existing_id:
                existing = self._tasks[existing_id]
                _require_matching_request(existing=existing, incoming=task)
                return existing.model_copy(deep=True)
            stored = task.model_copy(deep=True, update={"revision": 1})
            self._tasks[task.id] = stored
            self._idempotency[idempotency_key] = task.id
            return stored.model_copy(deep=True)

    async def get(self, task_id: str) -> TaskRecord | None:
        async with self._lock:
            task = self._tasks.get(task_id)
            return task.model_copy(deep=True) if task is not None else None

    async def save(self, task: TaskRecord, *, expected_revision: int) -> None:
        async with self._lock:
            current = self._tasks.get(task.id)
            if current is None or current.revision != expected_revision:
                raise TaskVersionConflictError(task.id)
            next_revision = expected_revision + 1
            self._tasks[task.id] = task.model_copy(
                deep=True,
                update={"revision": next_revision},
            )
            task.revision = next_revision

    async def is_ready(self) -> bool:
        return True

    async def close(self) -> None:
        return None


class _Base(DeclarativeBase):
    pass


class CustomerAgentTaskRow(_Base):
    """SQL projection; signed artifacts and receipt history live in ``payload``."""

    __tablename__ = "customer_agent_tasks"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_customer_agent_tasks_idempotency_key"),
        CheckConstraint("version >= 1", name="ck_customer_agent_tasks_version_positive"),
        Index("ix_customer_agent_tasks_state_updated", "state", "updated_at"),
    )

    task_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    state: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SqlAlchemyTaskStore:
    """Cross-process task store backed by a coordinator-migrated SQL table."""

    kind = "sql"

    def __init__(
        self,
        *,
        engine: AsyncEngine,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._engine = engine
        self._session_factory = session_factory or async_sessionmaker(
            engine,
            expire_on_commit=False,
        )

    @classmethod
    def from_database_url(cls, database_url: str) -> SqlAlchemyTaskStore:
        engine = create_async_engine(
            _async_database_url(database_url),
            pool_pre_ping=True,
        )
        return cls(engine=engine)

    async def create_once(self, *, idempotency_key: str, task: TaskRecord) -> TaskRecord:
        row = CustomerAgentTaskRow(
            task_id=task.id,
            idempotency_key=idempotency_key,
            state=task.state,
            payload=_task_payload(task),
            version=1,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )
        try:
            async with self._session_factory() as session, session.begin():
                session.add(row)
                await session.flush()
            return _task_from_row(row)
        except IntegrityError:
            # The uniqueness constraint, not a read-before-write, serializes
            # duplicated SendMessage deliveries across hosted instances.
            async with self._session_factory() as session:
                result = await session.execute(
                    select(CustomerAgentTaskRow).where(
                        CustomerAgentTaskRow.idempotency_key == idempotency_key
                    )
                )
                existing = result.scalar_one_or_none()
            if existing is None:
                raise
            existing_task = _task_from_row(existing)
            _require_matching_request(existing=existing_task, incoming=task)
            return existing_task

    async def get(self, task_id: str) -> TaskRecord | None:
        async with self._session_factory() as session:
            row = await session.get(CustomerAgentTaskRow, task_id)
            return _task_from_row(row) if row is not None else None

    async def save(self, task: TaskRecord, *, expected_revision: int) -> None:
        statement = (
            update(CustomerAgentTaskRow)
            .where(
                CustomerAgentTaskRow.task_id == task.id,
                CustomerAgentTaskRow.version == expected_revision,
            )
            .values(
                state=task.state,
                payload=_task_payload(task),
                version=expected_revision + 1,
                updated_at=task.updated_at,
            )
        )
        async with self._session_factory() as session, session.begin():
            result = await session.execute(statement)
            if result.rowcount != 1:  # type: ignore[attr-defined]
                raise TaskVersionConflictError(task.id)
        task.revision = expected_revision + 1

    async def is_ready(self) -> bool:
        try:
            async with self._session_factory() as session:
                # Verify both connectivity and that the coordinator-owned
                # migration is present; a bare SELECT 1 is not service-ready.
                await session.execute(select(CustomerAgentTaskRow.task_id).limit(1))
            return True
        except SQLAlchemyError:
            return False

    async def close(self) -> None:
        await self._engine.dispose()


def create_task_store(*, mode: str, database_url: str | None = None) -> TaskStore:
    if mode == "memory":
        return InMemoryTaskStore()
    if mode == "sql":
        if not database_url:
            raise ValueError("database_url is required for the sql customer-agent task store")
        return SqlAlchemyTaskStore.from_database_url(database_url)
    raise ValueError(f"unsupported customer-agent task store mode: {mode}")


async def create_schema_for_tests(database_url: str) -> None:
    """Create an isolated test schema; hosted environments must use Alembic."""

    engine = create_async_engine(_async_database_url(database_url))
    try:
        async with engine.begin() as connection:
            await connection.run_sync(_Base.metadata.create_all)
    finally:
        await engine.dispose()


def _task_payload(task: TaskRecord) -> dict[str, Any]:
    return dict(task.model_dump(mode="json", exclude={"revision"}))


def _task_from_row(row: CustomerAgentTaskRow) -> TaskRecord:
    payload: Mapping[str, Any] = row.payload
    return TaskRecord.model_validate({**payload, "revision": row.version})


def _require_matching_request(*, existing: TaskRecord, incoming: TaskRecord) -> None:
    if _canonical_request(existing) != _canonical_request(incoming):
        raise TaskIdempotencyConflictError(
            "idempotency key was reused with a different recovery request"
        )


def _canonical_request(task: TaskRecord) -> bytes:
    return json.dumps(
        task.request.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _async_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql+psycopg://"):
        return database_url.replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+asyncpg://", 1)
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return database_url
