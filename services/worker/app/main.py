from __future__ import annotations

import asyncio
import os

from temporalio.client import Client
from temporalio.worker import Worker

from .activities import MockRecoveryActivityServices, RecoveryActivities
from .outbox import run_worker_services
from .workflow import RecoveryCaseWorkflow


async def run() -> None:
    address = os.getenv("TEMPORAL_ADDRESS", "localhost:7233")
    namespace = os.getenv("TEMPORAL_NAMESPACE", "default")
    task_queue = os.getenv("TEMPORAL_TASK_QUEUE", "recovery-os")
    client = await Client.connect(address, namespace=namespace)
    activity_services = MockRecoveryActivityServices()
    activities = RecoveryActivities(activity_services)
    worker = Worker(
        client,
        task_queue=task_queue,
        workflows=[RecoveryCaseWorkflow],
        activities=activities.registrations(),
    )
    await run_worker_services(worker.run(), client, task_queue=task_queue)


if __name__ == "__main__":
    asyncio.run(run())
