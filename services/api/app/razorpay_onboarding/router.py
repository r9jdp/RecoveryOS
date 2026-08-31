"""Authenticated Razorpay Test subscription onboarding route."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from services.api.app.api.operator_auth import require_operator_for_non_mock_payment
from services.api.app.db.session import get_async_session
from services.api.app.integrations.razorpay import (
    RazorpayClient,
    create_razorpay_client_from_env,
)
from services.api.app.integrations.razorpay.errors import RazorpayIntegrationError

from .models import (
    RazorpayTestSubscriptionSyncRequest,
    RazorpayTestSubscriptionSyncResponse,
)
from .service import (
    MerchantIdentity,
    RazorpaySubscriptionOnboardingService,
    merchant_identity_from_env,
)

router = APIRouter(prefix="/v1/razorpay/test-onboarding", tags=["razorpay"])


async def get_razorpay_onboarding_client() -> AsyncIterator[RazorpayClient]:
    provider = os.getenv("PAYMENT_PROVIDER", "mock").strip().lower()
    test_mode_required = os.getenv("RAZORPAY_TEST_MODE_REQUIRED", "true").strip().lower()
    if provider != "razorpay":
        raise RazorpayIntegrationError(
            "RAZORPAY_ONBOARDING_PROVIDER_DISABLED",
            "Razorpay test onboarding requires PAYMENT_PROVIDER=razorpay.",
            status_code=503,
        )
    if test_mode_required not in {"1", "true", "yes", "on"}:
        raise RazorpayIntegrationError(
            "RAZORPAY_TEST_MODE_REQUIRED",
            "Razorpay onboarding is disabled unless test-mode enforcement is enabled.",
            status_code=503,
        )
    client = create_razorpay_client_from_env()
    try:
        yield client
    finally:
        await client.aclose()


Session = Annotated[AsyncSession, Depends(get_async_session)]
Provider = Annotated[RazorpayClient, Depends(get_razorpay_onboarding_client)]
MerchantScope = Annotated[MerchantIdentity, Depends(merchant_identity_from_env)]


@router.post(
    "/subscriptions/{subscription_id}/sync",
    response_model=RazorpayTestSubscriptionSyncResponse,
    dependencies=[Depends(require_operator_for_non_mock_payment)],
)
async def sync_razorpay_test_subscription(
    subscription_id: str,
    request: RazorpayTestSubscriptionSyncRequest,
    session: Session,
    provider: Provider,
    merchant: MerchantScope,
) -> RazorpayTestSubscriptionSyncResponse:
    """Persist provider-owned IDs so signed webhooks can correlate safely."""

    return await RazorpaySubscriptionOnboardingService(session, provider).sync(
        merchant=merchant,
        subscription_id=subscription_id,
        request=request,
    )
