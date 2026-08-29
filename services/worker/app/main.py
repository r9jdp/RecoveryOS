from __future__ import annotations

import asyncio
import os

from temporalio.client import Client
from temporalio.worker import Worker

from .a2a_runtime import (
    MockA2AMandateActivityServices,
    create_live_a2a_services_from_env,
)
from .activities import RecoveryActivities
from .health import WorkerHealthServer
from .outbox import run_worker_services
from .runtime import create_activity_services_from_env
from .workflow import RecoveryCaseWorkflow


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


async def run() -> None:
    address = os.getenv("TEMPORAL_ADDRESS", "localhost:7233")
    namespace = os.getenv("TEMPORAL_NAMESPACE", "default")
    task_queue = os.getenv("TEMPORAL_TASK_QUEUE", "recovery-os")
    api_key = os.getenv("TEMPORAL_API_KEY", "").strip() or None
    use_tls = _truthy(os.getenv("TEMPORAL_TLS"))
    client = await Client.connect(
        address,
        namespace=namespace,
        api_key=api_key,
        tls=use_tls,
    )
    activity_services = create_activity_services_from_env()
    a2a_services = (
        create_live_a2a_services_from_env()
        if _truthy(os.getenv("A2A_ENABLED"))
        else MockA2AMandateActivityServices()
    )
    activities = RecoveryActivities(activity_services, a2a_services)
    worker = Worker(
        client,
        task_queue=task_queue,
        workflows=[RecoveryCaseWorkflow],
        activities=activities.registrations(),
    )
    health_server = WorkerHealthServer(client, worker)
    await health_server.start()
    try:
        await run_worker_services(worker.run(), client, task_queue=task_queue)
    finally:
        await health_server.close()


if __name__ == "__main__":
    asyncio.run(run())
