from __future__ import annotations

import asyncio
import json
from typing import Any, cast

from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from services.worker.app.activities import MockRecoveryActivityServices, RecoveryActivities
from services.worker.app.health import WorkerHealthServer
from services.worker.app.workflow import RecoveryCaseWorkflow


class FakeTemporalServiceClient:
    def __init__(self, *, healthy: bool = True, error: Exception | None = None) -> None:
        self.healthy = healthy
        self.error = error
        self.calls = 0

    async def check_health(self) -> bool:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.healthy


class FakeClient:
    def __init__(self, service_client: FakeTemporalServiceClient) -> None:
        self.service_client = service_client


class FakeWorker:
    def __init__(self, *, is_running: bool, is_shutdown: bool = False) -> None:
        self.is_running = is_running
        self.is_shutdown = is_shutdown


async def request(server: WorkerHealthServer, path: str, *, method: str = "GET") -> tuple[int, Any]:
    reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
    writer.write(f"{method} {path} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode())
    await writer.drain()
    raw = await reader.read()
    writer.close()
    await writer.wait_closed()
    head, body = raw.split(b"\r\n\r\n", maxsplit=1)
    status_code = int(head.splitlines()[0].split()[1])
    return status_code, json.loads(body)


def health_server(
    *,
    worker_running: bool,
    temporal_healthy: bool = True,
    temporal_error: Exception | None = None,
) -> tuple[WorkerHealthServer, FakeTemporalServiceClient]:
    temporal = FakeTemporalServiceClient(healthy=temporal_healthy, error=temporal_error)
    server = WorkerHealthServer(
        cast(Client, FakeClient(temporal)),
        cast(Worker, FakeWorker(is_running=worker_running)),
        port=0,
        temporal_timeout_seconds=0.1,
    )
    return server, temporal


async def test_liveness_does_not_probe_temporal_or_require_polling() -> None:
    server, temporal = health_server(worker_running=False, temporal_error=RuntimeError("secret"))
    await server.start()
    try:
        status_code, payload = await request(server, "/health/live")
    finally:
        await server.close()

    assert status_code == 200
    assert payload["status"] == "ok"
    assert temporal.calls == 0


async def test_readiness_requires_running_worker_and_temporal_health() -> None:
    server, temporal = health_server(worker_running=True)
    await server.start()
    try:
        status_code, payload = await request(server, "/health/ready")
    finally:
        await server.close()

    assert status_code == 200
    assert payload["status"] == "ready"
    assert payload["components"] == [
        {"name": "worker", "status": "ok"},
        {"name": "temporal", "status": "ok"},
    ]
    assert temporal.calls == 1


async def test_readiness_is_503_before_worker_polling_without_temporal_probe() -> None:
    server, temporal = health_server(worker_running=False)
    await server.start()
    try:
        status_code, payload = await request(server, "/health/ready")
    finally:
        await server.close()

    assert status_code == 503
    assert payload["status"] == "not_ready"
    assert payload["components"] == [
        {"name": "worker", "status": "unavailable", "reason": "not_polling"},
        {"name": "temporal", "status": "unavailable", "reason": "probe_failed"},
    ]
    assert temporal.calls == 0


async def test_temporal_failure_is_sanitized_and_fails_readiness() -> None:
    server, temporal = health_server(
        worker_running=True,
        temporal_error=RuntimeError("temporal.internal:7233?api_key=do-not-leak"),
    )
    await server.start()
    try:
        status_code, payload = await request(server, "/health/ready")
    finally:
        await server.close()

    assert status_code == 503
    assert payload["components"][1] == {
        "name": "temporal",
        "status": "unavailable",
        "reason": "probe_failed",
    }
    assert "do-not-leak" not in json.dumps(payload)
    assert temporal.calls == 1


async def test_unknown_route_and_non_get_method_are_rejected() -> None:
    server, _ = health_server(worker_running=True)
    await server.start()
    try:
        missing_status, missing = await request(server, "/missing")
        method_status, method = await request(server, "/health/ready", method="POST")
    finally:
        await server.close()

    assert (missing_status, missing["status"]) == (404, "not_found")
    assert (method_status, method["status"]) == (405, "method_not_allowed")


async def test_real_temporal_worker_with_registered_activities_is_ready() -> None:
    """Cover the SDK worker state and Temporal service probe used in production."""

    async with await WorkflowEnvironment.start_time_skipping() as environment:
        activities = RecoveryActivities(MockRecoveryActivityServices())
        async with Worker(
            environment.client,
            task_queue="worker-health-test",
            workflows=[RecoveryCaseWorkflow],
            activities=activities.registrations(),
        ) as worker:
            server = WorkerHealthServer(environment.client, worker, port=0)
            await server.start()
            try:
                for _ in range(50):
                    status_code, payload = await request(server, "/health/ready")
                    if status_code == 200:
                        break
                    await asyncio.sleep(0.01)
            finally:
                await server.close()

    assert status_code == 200
    assert payload["status"] == "ready"
