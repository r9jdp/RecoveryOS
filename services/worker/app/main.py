from __future__ import annotations

import asyncio
import os

from temporalio.client import Client
from temporalio.worker import Worker


async def run() -> None:
    address = os.getenv("TEMPORAL_ADDRESS", "localhost:7233")
    namespace = os.getenv("TEMPORAL_NAMESPACE", "default")
    task_queue = os.getenv("TEMPORAL_TASK_QUEUE", "recovery-os")
    client = await Client.connect(address, namespace=namespace)
    worker = Worker(client, task_queue=task_queue, workflows=[], activities=[])
    await worker.run()


if __name__ == "__main__":
    asyncio.run(run())
