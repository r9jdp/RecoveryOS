from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool

from services.api.app.db import Base
from services.api.app.domain.enums import SubscriptionState
from services.api.app.integrations.razorpay.signature import webhook_signature
from services.api.app.models import (
    Customer,
    Invoice,
    Merchant,
    MerchantPolicySetting,
    OutboxMessage,
    PaymentAttempt,
    PolicyDecisionRecord,
    RecoveryActionRecord,
    RecoveryCase,
    Subscription,
    WebhookInboxEntry,
)
from services.api.app.providers.contracts import (
    OpenPaymentSurfaceRequest,
    PaymentSnapshot,
    PaymentSurfaceResult,
)
from services.api.app.webhooks.processor import (
    RazorpayDownstreamSignal,
    RazorpayOutboxProcessor,
)
from services.api.app.webhooks.razorpay import RazorpayWebhookIngestionService
from services.api.app.webhooks.repository import InboxOutboxStore

FIXTURE = Path("services/api/tests/fixtures/razorpay/payment.failed.json")
SECRET = "foreign_key_test_secret"
NOW = datetime(2030, 1, 1, tzinfo=UTC)


class NoExternalCallsProvider:
    async def open_customer_payment_surface(
        self, request: OpenPaymentSurfaceRequest
    ) -> PaymentSurfaceResult:
        del request
        raise AssertionError("outbox processing must not open payment surfaces")

    async def fetch_payment_snapshot(
        self, *, merchant_id: str, payment_id: str | None, invoice_id: str
    ) -> PaymentSnapshot:
        del merchant_id, payment_id, invoice_id
        raise AssertionError("payment.failed processing must not fetch payment state")


def _enable_foreign_keys(dbapi_connection: Any, connection_record: Any) -> None:
    del connection_record
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.close()


async def test_outbox_persists_actions_before_policy_foreign_keys() -> None:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    event.listen(engine.sync_engine, "connect", _enable_foreign_keys)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with AsyncSession(engine, expire_on_commit=False) as session:
            assert await session.scalar(text("PRAGMA foreign_keys")) == 1

            merchant = Merchant(
                id="merchant_fk_order",
                external_id="acc_fk_order",
                display_name="Foreign Key Merchant",
            )
            policy_settings = MerchantPolicySetting(merchant_id=merchant.id)
            customer = Customer(
                id="customer_fk_order",
                merchant_id=merchant.id,
                external_id="cust_fitbox_001",
                display_name="Customer",
            )
            subscription = Subscription(
                id="subscription_fk_order",
                merchant_id=merchant.id,
                customer_id=customer.id,
                provider_subscription_id="sub_fitbox_annual_001",
                plan_name="Annual",
                amount_paise=149_900,
                subscription_state=SubscriptionState.PENDING,
                current_billing_cycle_key="2026-08",
            )
            invoice = Invoice(
                id="invoice_fk_order",
                merchant_id=merchant.id,
                subscription_id=subscription.id,
                provider_invoice_id="inv_fitbox_aug_2026",
                billing_cycle_key="2026-08",
                amount_paise=149_900,
                amount_paid_paise=0,
                currency="INR",
                invoice_state="issued",
            )
            for record in (merchant, policy_settings, customer, subscription, invoice):
                session.add(record)
                await session.flush()
            await session.commit()

            raw_body = FIXTURE.read_bytes()
            receipt = await RazorpayWebhookIngestionService(InboxOutboxStore(session)).ingest(
                merchant_id=merchant.id,
                raw_body=raw_body,
                signature=webhook_signature(raw_body, SECRET),
                provider_event_id="evt_fk_order",
                webhook_secret=SECRET,
            )
            signals: list[RazorpayDownstreamSignal] = []

            async def callback(signal: RazorpayDownstreamSignal) -> None:
                signals.append(signal)

            processor = RazorpayOutboxProcessor(
                session,
                NoExternalCallsProvider(),
                callback,
                clock=lambda: NOW,
            )
            result = await processor.process_next()

            recovery_case = await session.scalar(select(RecoveryCase))
            payment = await session.scalar(select(PaymentAttempt))
            action = await session.scalar(select(RecoveryActionRecord))
            policy = await session.scalar(select(PolicyDecisionRecord))
            inbox = await session.get(WebhookInboxEntry, receipt.inbox_id)
            outbox = await session.get(OutboxMessage, receipt.outbox_id)

            assert result is not None and result.status == "PUBLISHED"
            assert result.error_code is None
            assert recovery_case is not None
            assert payment is not None
            assert action is not None
            assert policy is not None
            assert policy.action_id == action.id
            assert policy.case_id == action.case_id == recovery_case.id
            assert inbox is not None and inbox.processed_at is not None
            assert inbox.processing_error_code is None
            assert outbox is not None and outbox.published_at is not None
            assert outbox.last_error_code is None
            assert [signal.case_id for signal in signals] == [recovery_case.id]

            reconciliation_action = await processor._ensure_reconciliation_authorization(
                recovery_case=recovery_case
            )
            await session.commit()
            reconciliation_policy = await session.scalar(
                select(PolicyDecisionRecord).where(
                    PolicyDecisionRecord.action_id == reconciliation_action.id
                )
            )
            assert reconciliation_policy is not None
            assert reconciliation_policy.case_id == recovery_case.id
            assert (await session.execute(text("PRAGMA foreign_key_check"))).all() == []
    finally:
        await engine.dispose()
