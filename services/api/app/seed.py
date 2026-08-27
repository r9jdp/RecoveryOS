"""Idempotent FitBox demo seed for the Phase 1 vertical slice."""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from services.api.app.db import get_session_factory
from services.api.app.domain.enums import (
    ActionStatus,
    CaseOutcome,
    ContactDisposition,
    Diagnosis,
    EvidenceKind,
    PaymentState,
    PaymentSurfaceType,
    PolicyDisposition,
    RecoveryActionType,
    RevenueAttribution,
    SubscriptionState,
)
from services.api.app.models import (
    Customer,
    Invoice,
    Merchant,
    OutboxMessage,
    PaymentAttempt,
    PolicyDecisionRecord,
    RecoveryActionRecord,
    RecoveryCase,
    RecoveryEventRecord,
    RevenueRecognitionRecord,
    Subscription,
    WebhookInboxEntry,
)

FITBOX_CASE_ID = "case_fitbox_aug_2026"


async def reset_demo_data(session: AsyncSession) -> None:
    """Remove demo data in dependency order; intended only for explicit reset."""

    merchant_id = "merchant_fitbox"
    case_ids = select(RecoveryCase.id).where(RecoveryCase.merchant_id == merchant_id)
    await session.execute(
        delete(RevenueRecognitionRecord).where(RevenueRecognitionRecord.merchant_id == merchant_id)
    )
    await session.execute(delete(OutboxMessage).where(OutboxMessage.aggregate_id.in_(case_ids)))
    await session.execute(
        delete(WebhookInboxEntry).where(WebhookInboxEntry.merchant_id == merchant_id)
    )
    await session.execute(
        delete(RecoveryEventRecord).where(RecoveryEventRecord.case_id.in_(case_ids))
    )
    await session.execute(
        delete(PolicyDecisionRecord).where(PolicyDecisionRecord.case_id.in_(case_ids))
    )
    await session.execute(
        delete(RecoveryActionRecord).where(RecoveryActionRecord.case_id.in_(case_ids))
    )
    await session.execute(delete(RecoveryCase).where(RecoveryCase.merchant_id == merchant_id))
    await session.execute(delete(PaymentAttempt).where(PaymentAttempt.merchant_id == merchant_id))
    await session.execute(delete(Invoice).where(Invoice.merchant_id == merchant_id))
    await session.execute(delete(Subscription).where(Subscription.merchant_id == merchant_id))
    await session.execute(delete(Customer).where(Customer.merchant_id == merchant_id))
    await session.execute(delete(Merchant).where(Merchant.id == merchant_id))
    await session.commit()


async def seed_fitbox(session: AsyncSession, *, reset: bool = False) -> bool:
    """Seed one correlated failed subscription case, returning whether rows were added."""

    if reset:
        await reset_demo_data(session)
    existing = await session.scalar(
        select(RecoveryCase.id).where(RecoveryCase.id == FITBOX_CASE_ID)
    )
    if existing:
        return False

    failed_at = datetime(2026, 8, 27, 10, 0, 0, tzinfo=UTC)
    opened_at = datetime(2026, 8, 27, 10, 0, 1, tzinfo=UTC)
    recommended_at = datetime(2026, 8, 27, 10, 0, 2, tzinfo=UTC)
    deadline = datetime(2026, 8, 30, 10, 0, 1, tzinfo=UTC)

    merchant = Merchant(
        id="merchant_fitbox",
        external_id="acct_fitbox_test",
        display_name="FitBox",
        timezone="Asia/Kolkata",
        currency="INR",
    )
    customer = Customer(
        id="customer_fitbox_001",
        merchant_id=merchant.id,
        external_id="cust_fitbox_001",
        display_name="Aarav Sharma",
        preferred_language="Hinglish",
        voice_consent_at=datetime(2026, 8, 1, 9, 0, tzinfo=UTC),
        customer_agent_available=True,
    )
    subscription = Subscription(
        id="sub_fitbox_annual_001",
        merchant_id=merchant.id,
        customer_id=customer.id,
        provider_subscription_id="sub_fitbox_annual_001",
        plan_name="FitBox Annual",
        amount_paise=149_900,
        currency="INR",
        subscription_state=SubscriptionState.PENDING,
        current_billing_cycle_key="2026-08",
    )
    invoice = Invoice(
        id="inv_fitbox_aug_2026",
        merchant_id=merchant.id,
        subscription_id=subscription.id,
        provider_invoice_id="inv_fitbox_aug_2026",
        billing_cycle_key="2026-08",
        amount_paise=149_900,
        amount_paid_paise=0,
        currency="INR",
        invoice_state="issued",
        due_at=failed_at,
    )
    payment = PaymentAttempt(
        id="pay_fitbox_failed_001",
        merchant_id=merchant.id,
        invoice_id=invoice.id,
        subscription_id=subscription.id,
        provider_payment_id="pay_fitbox_failed_001",
        amount_paise=149_900,
        currency="INR",
        payment_state=PaymentState.FAILED,
        method="card",
        error_code="BAD_REQUEST_PAYMENT_AUTHENTICATION_FAILED",
        error_source="customer",
        error_step="payment_authentication",
        error_reason="incorrect_otp",
        occurred_at=failed_at,
    )
    recovery_case = RecoveryCase(
        id=FITBOX_CASE_ID,
        merchant_id=merchant.id,
        customer_id=customer.id,
        subscription_id=subscription.id,
        failed_invoice_id=invoice.id,
        billing_cycle_key="2026-08",
        failed_payment_id=payment.id,
        case_outcome=CaseOutcome.OPEN,
        payment_state=PaymentState.FAILED,
        subscription_state=SubscriptionState.PENDING,
        contact_disposition=ContactDisposition.NOT_CONTACTED,
        revenue_attribution=RevenueAttribution.NONE,
        diagnosis=Diagnosis.AUTHENTICATION_REQUIRED,
        amount_at_risk_paise=149_900,
        arrears_collected_paise=0,
        case_recovered=False,
        subscription_reactivated=False,
        opened_at=opened_at,
        recovery_deadline=deadline,
        version=1,
    )
    action = RecoveryActionRecord(
        id="action_fitbox_card_update_001",
        case_id=recovery_case.id,
        action_type=RecoveryActionType.OPEN_CUSTOMER_PAYMENT_SURFACE,
        payment_surface_type=PaymentSurfaceType.SUBSCRIPTION_CARD_UPDATE,
        status=ActionStatus.PROPOSED,
        idempotency_key=(
            "case:case_fitbox_aug_2026:action:OPEN_CUSTOMER_PAYMENT_SURFACE:"
            "surface:SUBSCRIPTION_CARD_UPDATE"
        ),
        created_at=recommended_at,
        updated_at=recommended_at,
    )
    policy = PolicyDecisionRecord(
        id="policy_fitbox_001",
        case_id=recovery_case.id,
        action_id=action.id,
        disposition=PolicyDisposition.ALLOW,
        decision_code="POLICY_ALLOWED",
        reason_codes=["WITHIN_RECOVERY_WINDOW", "NO_SUPPRESSION"],
        reasons=["Case is within its recovery window.", "Customer has no suppression."],
        policy_version="fitbox-demo.v1",
        created_at=recommended_at,
    )
    events = [
        RecoveryEventRecord(
            id="event_fitbox_payment_failed",
            case_id=recovery_case.id,
            event_type="PAYMENT_FAILED",
            source="simulator",
            evidence_kind=EvidenceKind.SIMULATED,
            payload={"error_reason": "incorrect_otp"},
            occurred_at=failed_at,
            recorded_at=opened_at,
            correlation_id="corr_fitbox_001",
            source_event_id="sim_payment_failed_001",
        ),
        RecoveryEventRecord(
            id="event_fitbox_case_opened",
            case_id=recovery_case.id,
            event_type="CASE_OPENED",
            source="recovery-api",
            evidence_kind=EvidenceKind.SIMULATED,
            payload={"amount_at_risk_paise": 149_900},
            occurred_at=opened_at,
            recorded_at=opened_at,
            correlation_id="corr_fitbox_001",
            source_event_id="sim_case_opened_001",
        ),
        RecoveryEventRecord(
            id="event_fitbox_action_recommended",
            case_id=recovery_case.id,
            event_type="ACTION_RECOMMENDED",
            source="decision-engine",
            evidence_kind=EvidenceKind.SIMULATED,
            payload={
                "action_type": "OPEN_CUSTOMER_PAYMENT_SURFACE",
                "payment_surface_type": "SUBSCRIPTION_CARD_UPDATE",
            },
            occurred_at=recommended_at,
            recorded_at=recommended_at,
            correlation_id="corr_fitbox_001",
            source_event_id="sim_action_recommended_001",
        ),
    ]
    # Flush dependency tiers explicitly because the demo models intentionally omit
    # ORM relationships; foreign-key columns alone do not create unit-of-work edges.
    for record in (merchant, customer, subscription, invoice, payment, recovery_case, action):
        session.add(record)
        await session.flush()
    session.add_all([policy, *events])
    await session.commit()
    return True


async def _main(reset: bool) -> None:
    async with get_session_factory()() as session:
        created = await seed_fitbox(session, reset=reset)
    print("FitBox demo seeded." if created else "FitBox demo already present.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="delete and recreate demo rows")
    arguments = parser.parse_args()
    asyncio.run(_main(arguments.reset))
