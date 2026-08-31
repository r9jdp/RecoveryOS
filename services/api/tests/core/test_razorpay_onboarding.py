"""Real-provider onboarding persists correlation state without demo fixtures."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from services.api.app.api import install_core_api
from services.api.app.api.operator_auth import require_operator_for_non_mock_payment
from services.api.app.db import get_async_session
from services.api.app.integrations.razorpay.client import (
    RazorpaySubscriptionOnboardingBundle,
)
from services.api.app.models import Customer, Invoice, Merchant, Subscription
from services.api.app.razorpay_onboarding.router import (
    get_razorpay_onboarding_client,
    merchant_identity_from_env,
    router,
)
from services.api.app.razorpay_onboarding.service import MerchantIdentity


class FakeRazorpayOnboardingProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.subscription_short_url = "https://rzp.io/i/subscription-auth-real"
        self.invoice_short_url = "https://rzp.io/i/invoice-real"

    async def fetch_test_subscription_onboarding_bundle(
        self, *, subscription_id: str
    ) -> RazorpaySubscriptionOnboardingBundle:
        self.calls.append(subscription_id)
        return RazorpaySubscriptionOnboardingBundle(
            subscription={
                "id": subscription_id,
                "plan_id": "plan_real_test_001",
                "quantity": 2,
                "status": "pending",
                "short_url": self.subscription_short_url,
            },
            plan={
                "id": "plan_real_test_001",
                "item": {
                    "name": "Merchant Gold Monthly",
                    "amount": 75_000,
                    "currency": "INR",
                },
            },
            invoices=(
                {
                    "id": "inv_real_test_001",
                    "subscription_id": subscription_id,
                    "amount": 150_000,
                    "amount_paid": 0,
                    "currency": "INR",
                    "status": "issued",
                    "short_url": self.invoice_short_url,
                    "billing_start": 1_788_070_400,
                    "billing_end": 1_790_662_400,
                },
            ),
        )


def _merchant() -> MerchantIdentity:
    return MerchantIdentity(
        id="merchant_pitch_account",
        external_id="merchant-pitch-account",
        display_name="Pitch Merchant",
        timezone="Asia/Kolkata",
        currency="INR",
    )


def _app(
    session_factory: async_sessionmaker[AsyncSession],
    provider: FakeRazorpayOnboardingProvider,
) -> FastAPI:
    app = FastAPI()
    install_core_api(app)
    app.include_router(router)

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as active_session:
            yield active_session

    app.dependency_overrides[get_async_session] = override_session
    app.dependency_overrides[get_razorpay_onboarding_client] = lambda: provider
    app.dependency_overrides[merchant_identity_from_env] = _merchant
    app.dependency_overrides[require_operator_for_non_mock_payment] = lambda: None
    return app


async def test_sync_is_idempotent_and_persists_real_provider_correlation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    provider = FakeRazorpayOnboardingProvider()
    app = _app(session_factory, provider)
    payload = {
        "customer_external_id": "customer-acme-42",
        "customer_display_name": "Aarav Sharma",
        "preferred_language": "hi-IN",
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.post(
            "/v1/razorpay/test-onboarding/subscriptions/sub_real_test_001/sync",
            json=payload,
        )
        second = await client.post(
            "/v1/razorpay/test-onboarding/subscriptions/sub_real_test_001/sync",
            json=payload,
        )

    assert first.status_code == 200, first.text
    assert first.json()["mode"] == "razorpay_test"
    assert first.json()["merchant_id"] == "merchant_pitch_account"
    assert first.json()["customer"]["created"] is True
    assert first.json()["subscription"] == {
        "id": first.json()["subscription"]["id"],
        "provider_subscription_id": "sub_real_test_001",
        "provider_plan_id": "plan_real_test_001",
        "plan_name": "Merchant Gold Monthly",
        "amount_paise": 150_000,
        "currency": "INR",
        "subscription_state": "PENDING",
        "authorization_url": "https://rzp.io/i/subscription-auth-real",
        "created": True,
    }
    assert first.json()["invoices"][0]["provider_invoice_id"] == "inv_real_test_001"
    assert first.json()["invoices"][0]["payment_url"] == "https://rzp.io/i/invoice-real"
    assert second.status_code == 200, second.text
    assert second.json()["customer"]["created"] is False
    assert second.json()["subscription"]["created"] is False
    assert second.json()["invoices"][0]["created"] is False
    assert provider.calls == ["sub_real_test_001", "sub_real_test_001"]

    async with session_factory() as session:
        assert await session.scalar(select(func.count(Merchant.id))) == 1
        assert await session.scalar(select(func.count(Customer.id))) == 1
        assert await session.scalar(select(func.count(Subscription.id))) == 1
        assert await session.scalar(select(func.count(Invoice.id))) == 1
        subscription = await session.scalar(select(Subscription))
        invoice = await session.scalar(select(Invoice))
        assert subscription is not None
        assert invoice is not None
        assert subscription.provider_subscription_id == "sub_real_test_001"
        assert subscription.amount_paise == 150_000
        assert subscription.current_billing_cycle_key == "razorpay:inv_real_test_001"
        assert invoice.subscription_id == subscription.id
        assert invoice.amount_paise == 150_000


async def test_existing_subscription_cannot_be_rebound_to_another_customer(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    provider = FakeRazorpayOnboardingProvider()
    app = _app(session_factory, provider)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.post(
            "/v1/razorpay/test-onboarding/subscriptions/sub_real_test_001/sync",
            json={
                "customer_external_id": "customer-one",
                "customer_display_name": "Customer One",
            },
        )
        conflict = await client.post(
            "/v1/razorpay/test-onboarding/subscriptions/sub_real_test_001/sync",
            json={
                "customer_external_id": "customer-two",
                "customer_display_name": "Customer Two",
            },
        )

    assert first.status_code == 200
    assert conflict.status_code == 422
    assert conflict.json()["error"]["code"] == "RAZORPAY_SUBSCRIPTION_CUSTOMER_CONFLICT"


async def test_provider_guard_fails_closed_when_razorpay_is_disabled(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    app = FastAPI()
    install_core_api(app)
    app.include_router(router)

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as active_session:
            yield active_session

    monkeypatch.setenv("PAYMENT_PROVIDER", "mock")
    app.dependency_overrides[get_async_session] = override_session
    app.dependency_overrides[merchant_identity_from_env] = _merchant
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/v1/razorpay/test-onboarding/subscriptions/sub_real_test_001/sync",
            json={
                "customer_external_id": "customer-one",
                "customer_display_name": "Customer One",
            },
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "RAZORPAY_ONBOARDING_PROVIDER_DISABLED"


async def test_sync_rejects_non_https_provider_urls(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    provider = FakeRazorpayOnboardingProvider()
    provider.subscription_short_url = "http://unsafe.example/subscription"
    app = _app(session_factory, provider)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/v1/razorpay/test-onboarding/subscriptions/sub_real_test_001/sync",
            json={
                "customer_external_id": "customer-one",
                "customer_display_name": "Customer One",
            },
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "RAZORPAY_SUBSCRIPTION_URL_INVALID"
