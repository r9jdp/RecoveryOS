"""Loopback-only liveness and readiness endpoints for the Temporal worker.

The worker has no public HTTP API, but container orchestrators still need to
distinguish a live Python process from a worker that can poll Temporal.  This
small asyncio server avoids adding another application server to the worker
image and deliberately binds only to loopback.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from typing import Any

from temporalio.client import Client
from temporalio.worker import Worker

HEALTH_HOST = "127.0.0.1"
HEALTH_PORT = 8001
TEMPORAL_HEALTH_TIMEOUT_SECONDS = 3.0


class WorkerHealthServer:
    """Serve sanitized health state for one Temporal worker process."""

    def __init__(
        self,
        client: Client,
        worker: Worker,
        *,
        host: str = HEALTH_HOST,
        port: int = HEALTH_PORT,
        temporal_timeout_seconds: float = TEMPORAL_HEALTH_TIMEOUT_SECONDS,
    ) -> None:
        self._client = client
        self._worker = worker
        self._host = host
        self._port = port
        self._temporal_timeout_seconds = temporal_timeout_seconds
        self._server: asyncio.Server | None = None

    @property
    def port(self) -> int:
        """Return the bound port, including the OS-selected port used by tests."""

        if self._server is None or not self._server.sockets:
            return self._port
        return int(self._server.sockets[0].getsockname()[1])

    async def start(self) -> None:
        """Bind the health socket before the worker enters its long-running loop."""

        if self._server is not None:
            raise RuntimeError("worker health server is already running")
        self._server = await asyncio.start_server(self._handle_connection, self._host, self._port)

    async def close(self) -> None:
        """Stop accepting probes and wait for the socket to close."""

        if self._server is None:
            return
        self._server.close()
        await self._server.wait_closed()
        self._server = None

    async def _readiness(self) -> tuple[int, dict[str, Any]]:
        worker_ready = self._worker.is_running and not self._worker.is_shutdown
        temporal_ready = False
        if worker_ready:
            try:
                async with asyncio.timeout(self._temporal_timeout_seconds):
                    temporal_ready = await self._client.service_client.check_health()
            except Exception:
                temporal_ready = False

        is_ready = worker_ready and temporal_ready
        return (
            200 if is_ready else 503,
            self._payload(
                "ready" if is_ready else "not_ready",
                components=[
                    {
                        "name": "worker",
                        "status": "ok" if worker_ready else "unavailable",
                        **({} if worker_ready else {"reason": "not_polling"}),
                    },
                    {
                        "name": "temporal",
                        "status": "ok" if temporal_ready else "unavailable",
                        **({} if temporal_ready else {"reason": "probe_failed"}),
                    },
                ],
            ),
        )

    @staticmethod
    def _payload(status: str, **extra: Any) -> dict[str, Any]:
        return {
            "status": status,
            "service": os.getenv("SERVICE_NAME", "recoveryos-worker"),
            "version": os.getenv("APP_VERSION", "unknown"),
            "timestamp": datetime.now(UTC).isoformat(),
            **extra,
        }

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            request_line = await asyncio.wait_for(reader.readline(), timeout=2)
            parts = request_line.decode("ascii", errors="replace").strip().split()
            method = parts[0] if len(parts) == 3 else ""
            target = parts[1] if len(parts) == 3 else ""
            path = target.partition("?")[0]

            if method != "GET":
                status_code = 405
                payload = self._payload("method_not_allowed")
            elif path in {"/health", "/health/live"}:
                status_code = 200
                payload = self._payload("ok")
            elif path == "/health/ready":
                status_code, payload = await self._readiness()
            else:
                status_code = 404
                payload = self._payload("not_found")
            await self._write_response(writer, status_code, payload)
        except (TimeoutError, UnicodeError):
            await self._write_response(writer, 400, self._payload("bad_request"))
        finally:
            writer.close()
            await writer.wait_closed()

    @staticmethod
    async def _write_response(
        writer: asyncio.StreamWriter,
        status_code: int,
        payload: dict[str, Any],
    ) -> None:
        reason = {
            200: "OK",
            400: "Bad Request",
            404: "Not Found",
            405: "Method Not Allowed",
            503: "Service Unavailable",
        }[status_code]
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers = (
            f"HTTP/1.1 {status_code} {reason}\r\n"
            "Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Cache-Control: no-store\r\n"
            "Connection: close\r\n"
            "\r\n"
        ).encode("ascii")
        writer.write(headers + body)
        await writer.drain()
