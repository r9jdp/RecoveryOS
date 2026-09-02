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

        def probe() -> None:
            with (
                psycopg.connect(
                    database_url, connect_timeout=max(1, round(timeout_seconds))
                ) as connection,
                connection.cursor() as cursor,
            ):
                cursor.execute("SELECT 1")
                row = cursor.fetchone()
                if row != (1,):
                    raise RuntimeError("database probe returned an unexpected result")

        async with asyncio.timeout(timeout_seconds):
            await asyncio.to_thread(probe)
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


async def merchant_scope_check() -> ComponentStatus:
    """Reject a hosted Razorpay process that would have no real merchant scope."""

    started_at = monotonic()
    try:
        environment = os.getenv("APP_ENV", "development").strip().lower()
        provider = os.getenv("PAYMENT_PROVIDER", "mock").strip().lower()
        if environment == "production" or provider == "razorpay":
            merchant_id = _required("RECOVERY_MERCHANT_ID")
            _required("RECOVERY_MERCHANT_DISPLAY_NAME")
            if merchant_id == "merchant_fitbox":
                raise RuntimeError("demo merchant is not a live scope")
        return ComponentStatus("merchant_scope", "ok", _elapsed_ms(started_at))
    except Exception:
        return ComponentStatus(
            "merchant_scope",
            "unavailable",
            _elapsed_ms(started_at),
            "scope_not_configured",
        )


async def recovery_model_check() -> ComponentStatus:
    """Prove that production can load and execute the checksum-verified scorer."""

    started_at = monotonic()
    model_required = os.getenv(
        "RECOVERY_MODEL_REQUIRED",
        "true"
        if os.getenv("APP_ENV", "development").strip().lower() == "production"
        else "false",
    ).strip().lower() in {"1", "true", "yes", "on"}
    if not model_required:
        return ComponentStatus(
            "recovery_model",
            "ok",
            _elapsed_ms(started_at),
            "deterministic_fallback",
        )
    try:
        from services.api.app.domain.enums import Diagnosis, RecoveryActionType
        from services.api.app.providers.contracts import RecoveryScoreRequest
        from services.api.app.services.decision_engine import get_default_recovery_scorer

        score = await get_default_recovery_scorer().score(
            RecoveryScoreRequest(
                case_id="readiness-probe",
                amount_at_risk_paise=100_000,
                diagnosis=Diagnosis.UNKNOWN,
                candidate_action=RecoveryActionType.ESCALATE_TO_HUMAN,
                features={},
            )
        )
        trained = score.model_name == "recoverybench-catboost" and bool(
            score.artifact_checksum
        )
        if not trained:
            raise RuntimeError("trained model is required")
        return ComponentStatus(
            "recovery_model",
            "ok",
            _elapsed_ms(started_at),
            None if trained else "deterministic_fallback",
        )
    except Exception:
        return ComponentStatus(
            "recovery_model",
            "unavailable",
            _elapsed_ms(started_at),
            "artifact_probe_failed",
        )


DEFAULT_READINESS_CHECKS: tuple[ReadinessCheck, ...] = (
    merchant_scope_check,
    database_check,
    temporal_check,
    recovery_model_check,
)


async def run_readiness_checks(
    checks: tuple[ReadinessCheck, ...] = DEFAULT_READINESS_CHECKS,
) -> list[ComponentStatus]:
    """Run independent readiness checks concurrently.

    Keeping this function injectable makes the health contract easy to unit-test
    and lets the application replace probes with already-initialized clients.
    """

    return list(await asyncio.gather(*(check() for check in checks)))
