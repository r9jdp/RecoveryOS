"""Run the durable recovery worker inside the API process on constrained hosts."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from time import monotonic
from typing import TYPE_CHECKING

from fastapi import FastAPI

if TYPE_CHECKING:
    from services.api.app.health.checks import ComponentStatus
    from services.worker.app.main import WorkerRuntime

logger = logging.getLogger(__name__)

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


@dataclass(slots=True)
class EmbeddedWorkerState:
    runtime: WorkerRuntime
    task: asyncio.Task[None]


_active_state: EmbeddedWorkerState | None = None


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in _TRUE_VALUES


def embedded_worker_enabled() -> bool:
    """Use an explicit override, or infer the already-authorized hosted Razorpay mode."""

    configured = os.getenv("RECOVERY_EMBEDDED_WORKER")
    if configured is not None:
        normalized = configured.strip().lower()
        if normalized in _TRUE_VALUES:
            return True
        if normalized in _FALSE_VALUES:
            return False
        raise RuntimeError("RECOVERY_EMBEDDED_WORKER must be a boolean value")

    return (
        os.getenv("APP_ENV", "development").strip().lower() == "production"
        and os.getenv("PAYMENT_PROVIDER", "mock").strip().lower() == "razorpay"
        and os.getenv("RECOVERY_ACTIVITY_MODE", "mock").strip().lower() == "production"
        and _truthy(os.getenv("RECOVERY_ALLOW_REAL_PAYMENT_ACTIONS"))
    )


async def _create_runtime() -> WorkerRuntime:
    # Lazy import keeps normal API imports and local mock mode lightweight.
    from services.worker.app.main import create_worker_runtime

    return await create_worker_runtime()


async def _run_runtime(runtime: WorkerRuntime) -> None:
    from services.worker.app.outbox import run_worker_services

    await run_worker_services(
        runtime.worker.run(),
        runtime.client,
        task_queue=runtime.task_queue,
    )


async def _wait_until_polling(state: EmbeddedWorkerState) -> None:
    timeout_seconds = max(
        float(os.getenv("RECOVERY_EMBEDDED_WORKER_STARTUP_TIMEOUT_SECONDS", "10")),
        0.1,
    )
    deadline = monotonic() + timeout_seconds
    while not state.runtime.worker.is_running:
        if state.task.done():
            await state.task
            raise RuntimeError("embedded recovery worker stopped during startup")
        if monotonic() >= deadline:
            raise TimeoutError("embedded recovery worker did not start polling")
        await asyncio.sleep(0.05)


async def _stop_worker(state: EmbeddedWorkerState) -> None:
    try:
        if not state.runtime.worker.is_shutdown:
            await state.runtime.worker.shutdown()
    finally:
        if not state.task.done():
            state.task.cancel()
        await asyncio.gather(state.task, return_exceptions=True)


def embedded_worker_component() -> ComponentStatus | None:
    """Return sanitized readiness state when embedded mode is active."""

    from services.api.app.health.checks import ComponentStatus

    state = _active_state
    if state is None:
        return None
    worker_running = state.runtime.worker.is_running and not state.runtime.worker.is_shutdown
    task_running = not state.task.done()
    if worker_running and task_running:
        return ComponentStatus("recovery_worker", "ok", 0)
    return ComponentStatus("recovery_worker", "unavailable", 0, "not_polling")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Start one embedded worker for the lifetime of the single API process."""

    global _active_state

    if not embedded_worker_enabled():
        yield
        return

    runtime = await _create_runtime()
    state = EmbeddedWorkerState(
        runtime=runtime,
        task=asyncio.create_task(_run_runtime(runtime), name="embedded-recovery-worker"),
    )
    _active_state = state
    try:
        await _wait_until_polling(state)
        logger.info("Embedded recovery worker is polling")
        yield
    finally:
        _active_state = None
        await _stop_worker(state)
