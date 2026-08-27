"""Task storage with idempotent message handling for the customer agent."""

from __future__ import annotations

import asyncio
from typing import Protocol

from .models import TaskRecord


class TaskStore(Protocol):
    async def create_once(self, *, idempotency_key: str, task: TaskRecord) -> TaskRecord: ...

    async def get(self, task_id: str) -> TaskRecord | None: ...

    async def save(self, task: TaskRecord) -> None: ...


class InMemoryTaskStore:
    """Process-local mock store; production integration should use durable task storage."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._tasks: dict[str, TaskRecord] = {}
        self._idempotency: dict[str, str] = {}

    async def create_once(self, *, idempotency_key: str, task: TaskRecord) -> TaskRecord:
        async with self._lock:
            existing_id = self._idempotency.get(idempotency_key)
            if existing_id:
                return self._tasks[existing_id]
            self._tasks[task.id] = task
            self._idempotency[idempotency_key] = task.id
            return task

    async def get(self, task_id: str) -> TaskRecord | None:
        async with self._lock:
            return self._tasks.get(task_id)

    async def save(self, task: TaskRecord) -> None:
        async with self._lock:
            self._tasks[task.id] = task
