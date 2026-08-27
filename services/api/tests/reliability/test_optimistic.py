from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from services.api.app.domain.enums import CaseOutcome, PaymentState, SubscriptionState
from services.api.app.models import Customer, Invoice, Merchant, RecoveryCase, Subscription
from services.api.app.reliability.optimistic import (
    OptimisticVersionConflict,
    compare_and_swap_case,
)


@pytest.mark.asyncio
async def test_two_writers_cannot_commit_the_same_case_version(
    reliability_engine: AsyncEngine,
) -> None:
    now = datetime(2026, 8, 28, 12, tzinfo=UTC)
    async with AsyncSession(reliability_engine, expire_on_commit=False) as seed:
        seed.add(Merchant(id="merchant-1", external_id="merchant-1", display_name="FitBox"))
        seed.add(
            Customer(
                id="customer-1",
                merchant_id="merchant-1",
                external_id="customer-1",
                display_name="Asha",
            )
        )
        seed.add(
            Subscription(
                id="subscription-1",
                merchant_id="merchant-1",
                customer_id="customer-1",
                provider_subscription_id="sub-provider-1",
                plan_name="FitBox Annual",
                amount_paise=149_900,
                subscription_state=SubscriptionState.PENDING,
            )
        )
        seed.add(
            Invoice(
                id="invoice-1",
                merchant_id="merchant-1",
                subscription_id="subscription-1",
                provider_invoice_id="inv-provider-1",
                billing_cycle_key="2026-08",
                amount_paise=149_900,
            )
        )
        seed.add(
            RecoveryCase(
                id="case-1",
                merchant_id="merchant-1",
                customer_id="customer-1",
                subscription_id="subscription-1",
                failed_invoice_id="invoice-1",
                billing_cycle_key="2026-08",
                payment_state=PaymentState.FAILED,
                subscription_state=SubscriptionState.PENDING,
                amount_at_risk_paise=149_900,
                opened_at=now,
                recovery_deadline=now + timedelta(days=3),
                version=1,
            )
        )
        await seed.commit()

    async with (
        AsyncSession(reliability_engine, expire_on_commit=False) as winner,
        AsyncSession(reliability_engine, expire_on_commit=False) as stale,
    ):
        version = await compare_and_swap_case(
            winner,
            merchant_id="merchant-1",
            case_id="case-1",
            expected_version=1,
            changes={
                "case_outcome": CaseOutcome.RECOVERED,
                "payment_state": PaymentState.CAPTURED,
                "case_recovered": True,
                "arrears_collected_paise": 149_900,
                "recovered_at": now,
            },
        )
        await winner.commit()
        assert version == 2

        with pytest.raises(OptimisticVersionConflict) as conflict:
            await compare_and_swap_case(
                stale,
                merchant_id="merchant-1",
                case_id="case-1",
                expected_version=1,
                changes={"case_outcome": CaseOutcome.STOPPED},
            )
        assert conflict.value.code == "RECOVERY_CASE_VERSION_CONFLICT"
        await stale.rollback()

    async with AsyncSession(reliability_engine) as verify:
        recovery_case = await verify.get(RecoveryCase, "case-1")
        assert recovery_case is not None
        assert recovery_case.version == 2
        assert recovery_case.case_outcome == CaseOutcome.RECOVERED
        assert recovery_case.arrears_collected_paise == 149_900
