from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from services.api.app.api import install_core_api
from services.api.app.api.router import (
    _dashboard_evidence_kind,
    get_merchant_scope,
    get_payment_provider,
)
from services.api.app.db import get_async_session
from services.api.app.domain.enums import EvidenceKind
from services.api.app.integrations.razorpay.errors import RazorpayIntegrationError
from services.api.app.models import Merchant
from services.api.app.runtime_mode import ensure_demo_seed_allowed
from services.api.app.seed import seed_fitbox


def test_live_provider_requires_a_real_configured_merchant(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("PAYMENT_PROVIDER", "razorpay")
    monkeypatch.delenv("RECOVERY_MERCHANT_ID", raising=False)

    with pytest.raises(HTTPException) as exc_info:
        get_merchant_scope()

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["code"] == "MERCHANT_SCOPE_NOT_CONFIGURED"


def test_live_provider_rejects_the_bundled_fitbox_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("PAYMENT_PROVIDER", "razorpay")
    monkeypatch.setenv("RECOVERY_MERCHANT_ID", "merchant_fitbox")

    with pytest.raises(HTTPException) as exc_info:
        get_merchant_scope()

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["code"] == "DEMO_MERCHANT_NOT_ALLOWED"


def test_live_provider_uses_the_configured_database_merchant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("PAYMENT_PROVIDER", "razorpay")
    monkeypatch.setenv("RECOVERY_MERCHANT_ID", "merchant_acme")

    assert get_merchant_scope() == "merchant_acme"


def test_local_mock_mode_keeps_the_explicit_demo_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("PAYMENT_PROVIDER", "mock")
    monkeypatch.delenv("RECOVERY_MERCHANT_ID", raising=False)

    assert get_merchant_scope() == "merchant_fitbox"
    ensure_demo_seed_allowed()


def test_local_demo_can_be_disabled_explicitly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("PAYMENT_PROVIDER", "mock")
    monkeypatch.delenv("RECOVERY_MERCHANT_ID", raising=False)

    with pytest.raises(HTTPException) as exc_info:
        get_merchant_scope()

    assert exc_info.value.detail["code"] == "MERCHANT_SCOPE_NOT_CONFIGURED"


def test_fitbox_seed_is_blocked_in_live_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("PAYMENT_PROVIDER", "razorpay")

    with pytest.raises(RuntimeError, match="FitBox seed is restricted"):
        ensure_demo_seed_allowed()


@pytest.mark.asyncio
async def test_hosted_mock_provider_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("PAYMENT_PROVIDER", "mock")
    provider = get_payment_provider()

    with pytest.raises(RazorpayIntegrationError) as exc_info:
        await anext(provider)

    assert exc_info.value.code == "MOCK_PAYMENT_DISABLED"


@pytest.mark.parametrize(
    ("observed", "expected"),
    [
        ([], EvidenceKind.SYSTEM_DERIVED),
        ([EvidenceKind.SIMULATED], EvidenceKind.SIMULATED),
        (
            [EvidenceKind.SIMULATED, EvidenceKind.SYSTEM_DERIVED],
            EvidenceKind.SYSTEM_DERIVED,
        ),
        (
            [EvidenceKind.SYSTEM_DERIVED, EvidenceKind.RAZORPAY_TEST_VERIFIED],
            EvidenceKind.RAZORPAY_TEST_VERIFIED,
        ),
    ],
)
def test_dashboard_evidence_is_never_invented(
    observed: list[EvidenceKind],
    expected: EvidenceKind,
) -> None:
    assert _dashboard_evidence_kind(observed) == expected


@pytest.mark.asyncio
async def test_dashboard_currency_comes_from_the_configured_merchant_row(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("PAYMENT_PROVIDER", "mock")
    monkeypatch.setenv("RECOVERY_MERCHANT_ID", "merchant_fitbox")
    async with session_factory() as session:
        await seed_fitbox(session)
        merchant = await session.get(Merchant, "merchant_fitbox")
        assert merchant is not None
        merchant.currency = "USD"
        await session.commit()

    app = FastAPI()
    install_core_api(app)

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_async_session] = override_session
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/v1/dashboard/metrics")

    assert response.status_code == 200, response.text
    assert response.json()["currency"] == "USD"
