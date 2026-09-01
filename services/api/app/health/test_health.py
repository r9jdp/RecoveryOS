from __future__ import annotations

import json
from collections.abc import Awaitable, Callable

import pytest

from . import router as router_module
from .checks import (
    ComponentStatus,
    _psycopg_dsn,
    merchant_scope_check,
    run_readiness_checks,
)


def test_psycopg_dsn_normalizes_sqlalchemy_driver() -> None:
    assert (
        _psycopg_dsn("postgresql+psycopg://user:secret@db.example/recovery")
        == "postgresql://user:secret@db.example/recovery"
    )


@pytest.mark.asyncio
async def test_razorpay_readiness_requires_real_merchant_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("PAYMENT_PROVIDER", "razorpay")
    monkeypatch.delenv("RECOVERY_MERCHANT_ID", raising=False)
    monkeypatch.delenv("RECOVERY_MERCHANT_DISPLAY_NAME", raising=False)

    result = await merchant_scope_check()

    assert result.status == "unavailable"
    assert result.reason == "scope_not_configured"


@pytest.mark.asyncio
async def test_razorpay_readiness_accepts_configured_merchant_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("PAYMENT_PROVIDER", "razorpay")
    monkeypatch.setenv("RECOVERY_MERCHANT_ID", "merchant_recoveryos")
    monkeypatch.setenv("RECOVERY_MERCHANT_DISPLAY_NAME", "RecoveryOS Test Merchant")

    result = await merchant_scope_check()

    assert result.status == "ok"


@pytest.mark.asyncio
async def test_liveness_has_no_downstream_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SERVICE_NAME", raising=False)
    payload = await router_module.live()

    assert payload["status"] == "ok"
    assert payload["service"] == "recoveryos-api"
    assert "timestamp" in payload


@pytest.mark.asyncio
async def test_readiness_checks_run_independently() -> None:
    async def healthy() -> ComponentStatus:
        return ComponentStatus("database", "ok", 1)

    async def unavailable() -> ComponentStatus:
        return ComponentStatus("temporal", "unavailable", 2, "probe_failed")

    checks: tuple[Callable[[], Awaitable[ComponentStatus]], ...] = (healthy, unavailable)
    assert await run_readiness_checks(checks) == [
        ComponentStatus("database", "ok", 1),
        ComponentStatus("temporal", "unavailable", 2, "probe_failed"),
    ]


@pytest.mark.asyncio
async def test_ready_returns_sanitized_503(monkeypatch: pytest.MonkeyPatch) -> None:
    async def unavailable() -> list[ComponentStatus]:
        return [ComponentStatus("database", "unavailable", 3, "probe_failed")]

    monkeypatch.setattr(router_module, "run_readiness_checks", unavailable)
    response = await router_module.ready()
    payload = json.loads(bytes(response.body))

    assert response.status_code == 503
    assert payload["status"] == "not_ready"
    assert payload["components"] == [
        {
            "name": "database",
            "status": "unavailable",
            "latency_ms": 3,
            "reason": "probe_failed",
        }
    ]
    assert "exception" not in payload
