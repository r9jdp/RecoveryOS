"""Dependency checks used by the RecoveryOS readiness endpoint.

Liveness intentionally has no external dependencies. Readiness proves that the
API can authenticate to PostgreSQL and connect to the configured Temporal
namespace. Error responses are deliberately sanitized so credentials and
provider details cannot leak through a public health endpoint.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from time import monotonic
from typing import Any

ReadinessCheck = Callable[[], Awaitable["ComponentStatus"]]


@dataclass(frozen=True, slots=True)
class ComponentStatus:
    name: str
    status: str
    latency_ms: int
    reason: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


def _elapsed_ms(started_at: float) -> int:
    return max(0, round((monotonic() - started_at) * 1000))


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is not configured")
    return value


def _psycopg_dsn(database_url: str) -> str:
    """Convert a SQLAlchemy psycopg URL into a libpq-compatible URL."""

    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


async def database_check() -> ComponentStatus:
    started_at = monotonic()
    try:
        import psycopg

        database_url = _psycopg_dsn(_required("DATABASE_URL"))
        timeout_seconds = float(os.getenv("HEALTHCHECK_TIMEOUT_SECONDS", "3"))
        async with asyncio.timeout(timeout_seconds):
            connection = await psycopg.AsyncConnection.connect(
                database_url,
                connect_timeout=max(1, round(timeout_seconds)),
            )
            async with connection, connection.cursor() as cursor:
                await cursor.execute("SELECT 1")
                row = await cursor.fetchone()
                if row != (1,):
                    raise RuntimeError("database probe returned an unexpected result")
        return ComponentStatus("database", "ok", _elapsed_ms(started_at))
    except Exception:
        return ComponentStatus("database", "unavailable", _elapsed_ms(started_at), "probe_failed")


async def temporal_check() -> ComponentStatus:
    started_at = monotonic()
    try:
        from temporalio.client import Client

        address = _required("TEMPORAL_ADDRESS")
        namespace = _required("TEMPORAL_NAMESPACE")
        api_key = os.getenv("TEMPORAL_API_KEY", "").strip() or None
        use_tls = os.getenv("TEMPORAL_TLS", "false").lower() in {"1", "true", "yes"}

        timeout_seconds = float(os.getenv("HEALTHCHECK_TIMEOUT_SECONDS", "3"))
        async with asyncio.timeout(timeout_seconds):
            client = await Client.connect(
                address,
                namespace=namespace,
                tls=use_tls,
                api_key=api_key,
            )
            await client.service_client.check_health()
        return ComponentStatus("temporal", "ok", _elapsed_ms(started_at))
    except Exception:
        return ComponentStatus("temporal", "unavailable", _elapsed_ms(started_at), "probe_failed")


DEFAULT_READINESS_CHECKS: tuple[ReadinessCheck, ...] = (database_check, temporal_check)


async def run_readiness_checks(
    checks: tuple[ReadinessCheck, ...] = DEFAULT_READINESS_CHECKS,
) -> list[ComponentStatus]:
    """Run independent readiness checks concurrently.

    Keeping this function injectable makes the health contract easy to unit-test
    and lets the application replace probes with already-initialized clients.
    """

    return list(await asyncio.gather(*(check() for check in checks)))
