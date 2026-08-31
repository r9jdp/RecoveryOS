from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi import FastAPI

from services.api.app import embedded_worker as embedded_worker_module


class FakeWorker:
    def __init__(self, *, failure: Exception | None = None) -> None:
        self.is_running = False
        self.is_shutdown = False
        self.failure = failure
        self.started = asyncio.Event()
        self.stopped = asyncio.Event()
        self._stop_requested = asyncio.Event()

    async def run(self) -> None:
        self.started.set()
        if self.failure is not None:
            raise self.failure
        self.is_running = True
        try:
            await self._stop_requested.wait()
        finally:
            self.is_running = False
            self.stopped.set()

    async def shutdown(self) -> None:
        self.is_shutdown = True
        self._stop_requested.set()


class FakeRuntime:
    def __init__(self, worker: FakeWorker) -> None:
        self.worker = worker
        self.client = object()
        self.task_queue = "test-recovery"


@pytest.fixture(autouse=True)
def reset_embedded_worker_state(monkeypatch: pytest.MonkeyPatch) -> None:
    embedded_worker_module._active_state = None
    monkeypatch.delenv("RECOVERY_EMBEDDED_WORKER", raising=False)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("PAYMENT_PROVIDER", "mock")
    monkeypatch.setenv("RECOVERY_ACTIVITY_MODE", "mock")
    monkeypatch.setenv("RECOVERY_ALLOW_REAL_PAYMENT_ACTIONS", "false")


async def test_disabled_lifespan_does_not_create_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    async def create_runtime() -> Any:
        nonlocal called
        called = True
        raise AssertionError("disabled mode must not create a worker")

    monkeypatch.setattr(embedded_worker_module, "_create_runtime", create_runtime)

    async with embedded_worker_module.lifespan(FastAPI()):
        assert embedded_worker_module.embedded_worker_component() is None

    assert called is False


async def test_enabled_lifespan_starts_and_stops_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RECOVERY_EMBEDDED_WORKER", "true")
    worker = FakeWorker()
    runtime = FakeRuntime(worker)

    async def create_runtime() -> Any:
        return runtime

    monkeypatch.setattr(embedded_worker_module, "_create_runtime", create_runtime)

    async with embedded_worker_module.lifespan(FastAPI()):
        await asyncio.wait_for(worker.started.wait(), timeout=1)
        component = embedded_worker_module.embedded_worker_component()
        assert component is not None
        assert component.status == "ok"

    assert worker.is_shutdown is True
    assert worker.stopped.is_set()
    assert embedded_worker_module.embedded_worker_component() is None


async def test_worker_startup_failure_prevents_api_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RECOVERY_EMBEDDED_WORKER", "true")
    worker = FakeWorker(failure=RuntimeError("temporal unavailable"))
    runtime = FakeRuntime(worker)

    async def create_runtime() -> Any:
        return runtime

    monkeypatch.setattr(embedded_worker_module, "_create_runtime", create_runtime)

    with pytest.raises(RuntimeError, match="temporal unavailable"):
        async with embedded_worker_module.lifespan(FastAPI()):
            pass

    assert worker.is_shutdown is True
    assert embedded_worker_module.embedded_worker_component() is None


def test_hosted_real_action_mode_enables_worker_without_extra_render_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("PAYMENT_PROVIDER", "razorpay")
    monkeypatch.setenv("RECOVERY_ACTIVITY_MODE", "production")
    monkeypatch.setenv("RECOVERY_ALLOW_REAL_PAYMENT_ACTIONS", "true")

    assert embedded_worker_module.embedded_worker_enabled() is True

    monkeypatch.setenv("RECOVERY_EMBEDDED_WORKER", "false")
    assert embedded_worker_module.embedded_worker_enabled() is False
