from __future__ import annotations

import asyncio
from typing import cast

import pytest
from temporalio.client import Client

from services.worker.app import outbox as outbox_module


async def test_outer_cancellation_stops_worker_and_provider_poller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PAYMENT_PROVIDER", "razorpay")
    worker_started = asyncio.Event()
    poller_started = asyncio.Event()
    worker_stopped = asyncio.Event()
    poller_stopped = asyncio.Event()

    async def worker_run() -> None:
        worker_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            worker_stopped.set()

    async def poller(client: Client, *, task_queue: str) -> None:
        del client, task_queue
        poller_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            poller_stopped.set()

    monkeypatch.setattr(outbox_module, "run_razorpay_outbox_poller", poller)
    service_task = asyncio.create_task(
        outbox_module.run_worker_services(
            worker_run(),
            cast(Client, object()),
            task_queue="test-recovery",
        )
    )
    await asyncio.wait_for(worker_started.wait(), timeout=1)
    await asyncio.wait_for(poller_started.wait(), timeout=1)

    service_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await service_task

    assert worker_stopped.is_set()
    assert poller_stopped.is_set()
