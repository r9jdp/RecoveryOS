"""Shared schema projection for the separately hosted customer-agent task store."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from services.api.app.db.base import Base

from .entities import UTCDateTime


class CustomerAgentTaskRecord(Base):
    """Alembic-owned projection used by the customer-agent SQL adapter.

    RecoveryOS does not mutate this table directly. Keeping the projection in
    the coordinator-owned metadata prevents Alembic drift checks from treating
    the separately hosted service table as an unmanaged extra table.
    """

    __tablename__ = "customer_agent_tasks"

    task_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    state: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "idempotency_key",
            name="uq_customer_agent_tasks_idempotency_key",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        Index("ix_customer_agent_tasks_state_updated", "state", "updated_at"),
    )
