import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from services.api.app.domain.enums import (
    ActionStatus,
    CaseOutcome,
    Diagnosis,
    PaymentState,
    RevenueAttribution,
    SubscriptionState,
)
from services.api.app.integrations.razorpay.signature import webhook_signature
from services.api.app.models import (
    Customer,
    Invoice,
    Merchant,
    OutboxMessage,
    PaymentAttempt,
    RecoveryActionRecord,
    RecoveryCase,
    RecoveryEventRecord,
    RevenueRecognitionRecord,
    Subscription,
    WebhookInboxEntry,
)
from services.api.app.providers.contracts import (
    OpenPaymentSurfaceRequest,
    PaymentSnapshot,
    PaymentSurfaceResult,
)
from services.api.app.seed import FITBOX_CASE_ID, seed_fitbox
from services.api.app.webhooks.processor import (
    RazorpayDownstreamSignal,
    RazorpayOutboxProcessor,
)
from services.api.app.webhooks.razorpay import RazorpayWebhookIngestionService
from services.api.app.webhooks.repository import InboxOutboxStore

FIXTURES = Path("services/api/tests/fixtures/razorpay")
SECRET = "processor_test_secret"
NOW = datetime(2030, 1, 1, tzinfo=UTC)


class FakePaymentProvider:
    def __init__(self, *snapshots: PaymentSnapshot) -> None:
        self.snapshots = list(snapshots)
        self.fetch_calls: list[tuple[str, str | None, str]] = []

    async def open_customer_payment_surface(
        self, request: OpenPaymentSurfaceRequest
    ) -> PaymentSurfaceResult:
        del request
        raise AssertionError("outbox processing must not open payment surfaces")

    async def fetch_payment_snapshot(
        self, *, merchant_id: str, payment_id: str | None, invoice_id: str
    ) -> PaymentSnapshot:
        self.fetch_calls.append((merchant_id, payment_id, invoice_id))
        if not self.snapshots:
            raise AssertionError("unexpected authoritative fetch")
        return self.snapshots.pop(0)


def _snapshot(
    *,
    payment_state: PaymentState = PaymentState.CAPTURED,
    subscription_state: SubscriptionState = SubscriptionState.HALTED,
) -> PaymentSnapshot:
    return PaymentSnapshot(
        provider="razorpay",
        payment_id="pay_fitbox_recovered_001",
        invoice_id="inv_fitbox_aug_2026",
        subscription_id="sub_fitbox_annual_001",
        payment_state=payment_state,
        subscription_state=subscription_state,
        amount_paise=149_900,
        currency="INR",
        observed_at=NOW,
        authoritative=True,
    )


def _raw_fixture(name: str, *, changes: dict[str, Any] | None = None) -> bytes:
    payload = cast(
        dict[str, Any],
        json.loads((FIXTURES / name).read_text(encoding="utf-8")),
    )
    if changes:
        payment = cast(dict[str, Any], payload["payload"])["payment"]
        entity = cast(dict[str, Any], cast(dict[str, Any], payment)["entity"])
        entity.update(changes)
    return json.dumps(payload, separators=(",", ":")).encode()


async def _ingest(
    session: AsyncSession,
    *,
    fixture: str,
    provider_event_id: str,
    merchant_id: str = "merchant_fitbox",
    raw_body: bytes | None = None,
) -> OutboxMessage:
    raw = raw_body or _raw_fixture(fixture)
    await RazorpayWebhookIngestionService(InboxOutboxStore(session)).ingest(
        merchant_id=merchant_id,
        raw_body=raw,
        signature=webhook_signature(raw, SECRET),
        provider_event_id=provider_event_id,
        webhook_secret=SECRET,
    )
    outbox = await session.scalar(
        select(OutboxMessage)
        .where(OutboxMessage.published_at.is_(None))
        .order_by(OutboxMessage.created_at.desc())
        .limit(1)
    )
    assert outbox is not None
    assert outbox.payload["merchant_id"] == merchant_id
    assert outbox.payload["event"]["provider_event_id"] == provider_event_id
    return outbox


async def test_captured_events_recognize_one_payment_once_and_signal_before_publish(
    processor_session: AsyncSession,
) -> None:
    session = processor_session
    await seed_fitbox(session)
    first_outbox = await _ingest(
        session,
        fixture="payment.captured.json",
        provider_event_id="evt_capture_primary",
    )
    await _ingest(
        session,
        fixture="subscription.charged.json",
        provider_event_id="evt_charge_duplicate_payment",
    )
    signals: list[RazorpayDownstreamSignal] = []

    async def signal_callback(signal: RazorpayDownstreamSignal) -> None:
        outbox = await session.scalar(
            select(OutboxMessage).where(OutboxMessage.deduplication_key == signal.idempotency_key)
        )
        inbox = await session.scalar(
            select(WebhookInboxEntry).where(
                WebhookInboxEntry.provider_event_id == signal.provider_event_id
            )
        )
        assert outbox is not None and outbox.published_at is None
        assert inbox is not None and inbox.processed_at is None
        signals.append(signal)

    provider = FakePaymentProvider(
        _snapshot(subscription_state=SubscriptionState.HALTED),
        _snapshot(subscription_state=SubscriptionState.ACTIVE),
    )
    processor = RazorpayOutboxProcessor(session, provider, signal_callback, clock=lambda: NOW)

    first = await processor.process_next()
    second = await processor.process_next()

    assert first is not None and first.status == "PUBLISHED"
    assert second is not None and second.status == "PUBLISHED"
    assert first.outbox_id == first_outbox.id
    recovery_case = await session.get(RecoveryCase, FITBOX_CASE_ID)
    invoice_count = await session.scalar(select(func.count(RevenueRecognitionRecord.id)))
    recognition = await session.scalar(select(RevenueRecognitionRecord))
    invoice = await session.get(Invoice, "inv_fitbox_aug_2026")
    action = await session.get(RecoveryActionRecord, "action_fitbox_card_update_001")
    assert recovery_case is not None
    assert recognition is not None
    assert invoice is not None
    assert invoice_count == 1
    assert recognition.amount_paise == 149_900
    assert recognition.provider_event_id == "evt_capture_primary"
    assert recognition.subscription_reactivated is False
    assert recovery_case.arrears_collected_paise == 149_900
    assert recovery_case.payment_state == PaymentState.CAPTURED
    assert recovery_case.case_outcome == CaseOutcome.RECOVERED
    assert recovery_case.revenue_attribution == RevenueAttribution.RAZORPAY_TEST_VERIFIED
    assert recovery_case.subscription_reactivated is True
    assert invoice.amount_paid_paise == 149_900
    assert action is not None and action.status == ActionStatus.CANCELLED
    assert len(signals) == 2
    assert signals[0].effects["newly_recognized"] is True
    assert signals[1].effects["newly_recognized"] is False
    assert len(provider.fetch_calls) == 2
    assert await processor.process_next() is None


async def test_failed_callback_rolls_back_domain_and_retry_uses_same_idempotency_key(
    processor_session: AsyncSession,
) -> None:
    session = processor_session
    await seed_fitbox(session)
    outbox = await _ingest(
        session,
        fixture="subscription.halted.json",
        provider_event_id="evt_halted_retry",
    )
    callback_keys: list[str] = []
    fail = True

    async def callback(signal: RazorpayDownstreamSignal) -> None:
        nonlocal fail
        callback_keys.append(signal.idempotency_key)
        if fail:
            fail = False
            raise RuntimeError("simulated Temporal outage")

    processor = RazorpayOutboxProcessor(
        session,
        FakePaymentProvider(),
        callback,
        clock=lambda: NOW,
        retry_base_delay=timedelta(0),
    )
    failed = await processor.process_next()

    subscription = await session.get(Subscription, "sub_fitbox_annual_001")
    recovery_case = await session.get(RecoveryCase, FITBOX_CASE_ID)
    failed_outbox = await session.get(OutboxMessage, outbox.id)
    inbox = await session.scalar(
        select(WebhookInboxEntry).where(WebhookInboxEntry.provider_event_id == "evt_halted_retry")
    )
    assert failed is not None and failed.status == "FAILED"
    assert failed.error_code == "RAZORPAY_DOWNSTREAM_SIGNAL_FAILED"
    assert failed_outbox is not None and failed_outbox.published_at is None
    assert failed_outbox.attempt_count == 1
    assert inbox is not None and inbox.processed_at is None
    assert inbox.processing_error_code == "RAZORPAY_DOWNSTREAM_SIGNAL_FAILED"
    assert subscription is not None and subscription.subscription_state == SubscriptionState.PENDING
    assert recovery_case is not None
    assert recovery_case.subscription_state == SubscriptionState.PENDING

    succeeded = await processor.process_next()
    await session.refresh(failed_outbox)
    await session.refresh(inbox)
    await session.refresh(subscription)
    assert succeeded is not None and succeeded.status == "PUBLISHED"
    assert succeeded.attempt_count == 2
    assert failed_outbox.published_at == NOW
    assert failed_outbox.last_error_code is None
    assert inbox.processed_at == NOW
    assert inbox.processing_error_code is None
    assert subscription.subscription_state == SubscriptionState.HALTED
    assert callback_keys == [outbox.deduplication_key, outbox.deduplication_key]


async def test_subscription_only_updates_known_subscription_without_creating_case(
    processor_session: AsyncSession,
) -> None:
    session = processor_session
    merchant = Merchant(
        id="merchant_nocase", external_id="acc_nocase", display_name="No Case Merchant"
    )
    customer = Customer(
        id="customer_nocase",
        merchant_id=merchant.id,
        external_id="cust_nocase",
        display_name="Customer",
    )
    subscription = Subscription(
        id="subscription_nocase",
        merchant_id=merchant.id,
        customer_id=customer.id,
        provider_subscription_id="sub_fitbox_annual_001",
        plan_name="Plan",
        amount_paise=149_900,
        subscription_state=SubscriptionState.ACTIVE,
    )
    for record in (merchant, customer, subscription):
        session.add(record)
        await session.flush()
    await session.commit()
    await _ingest(
        session,
        fixture="subscription.pending.json",
        provider_event_id="evt_pending_no_case",
        merchant_id=merchant.id,
    )
    signals: list[RazorpayDownstreamSignal] = []

    async def callback(signal: RazorpayDownstreamSignal) -> None:
        signals.append(signal)

    provider = FakePaymentProvider()
    result = await RazorpayOutboxProcessor(
        session, provider, callback, clock=lambda: NOW
    ).process_next()
    await session.refresh(subscription)
    assert result is not None and result.status == "PUBLISHED"
    assert subscription.subscription_state == SubscriptionState.PENDING
    assert await session.scalar(select(func.count(RecoveryCase.id))) == 0
    assert signals[0].case_id is None
    assert provider.fetch_calls == []


async def test_older_subscription_event_is_published_without_regressing_newer_state(
    processor_session: AsyncSession,
) -> None:
    session = processor_session
    await seed_fitbox(session)

    async def callback(signal: RazorpayDownstreamSignal) -> None:
        del signal

    processor = RazorpayOutboxProcessor(session, FakePaymentProvider(), callback, clock=lambda: NOW)
    await _ingest(
        session,
        fixture="subscription.halted.json",
        provider_event_id="evt_newer_halted",
    )
    newer = await processor.process_next()
    await _ingest(
        session,
        fixture="subscription.pending.json",
        provider_event_id="evt_older_pending",
    )
    older = await processor.process_next()
    subscription = await session.get(Subscription, "sub_fitbox_annual_001")
    assert newer is not None and newer.status == "PUBLISHED"
    assert older is not None and older.status == "PUBLISHED"
    assert subscription is not None
    assert subscription.subscription_state == SubscriptionState.HALTED


async def test_payment_failure_is_idempotent_and_never_regresses_capture(
    processor_session: AsyncSession,
) -> None:
    session = processor_session
    await seed_fitbox(session)
    raw = _raw_fixture(
        "payment.failed.json",
        changes={"id": "pay_new_failure", "created_at": 1787827000},
    )
    await _ingest(
        session,
        fixture="payment.failed.json",
        provider_event_id="evt_new_failure",
        raw_body=raw,
    )
    signals: list[RazorpayDownstreamSignal] = []

    async def callback(signal: RazorpayDownstreamSignal) -> None:
        signals.append(signal)

    processor = RazorpayOutboxProcessor(session, FakePaymentProvider(), callback, clock=lambda: NOW)
    first = await processor.process_next()
    payment = await session.scalar(
        select(PaymentAttempt).where(PaymentAttempt.provider_payment_id == "pay_new_failure")
    )
    recovery_case = await session.get(RecoveryCase, FITBOX_CASE_ID)
    assert first is not None and first.status == "PUBLISHED"
    assert payment is not None and payment.payment_state == PaymentState.FAILED
    assert recovery_case is not None and recovery_case.failed_payment_id == payment.id

    payment.payment_state = PaymentState.CAPTURED
    recovery_case.payment_state = PaymentState.CAPTURED
    await session.commit()
    later_raw = _raw_fixture(
        "payment.failed.json",
        changes={"id": "pay_new_failure", "created_at": 1787828000},
    )
    await _ingest(
        session,
        fixture="payment.failed.json",
        provider_event_id="evt_failure_after_capture",
        raw_body=later_raw,
    )
    second = await processor.process_next()
    await session.refresh(payment)
    await session.refresh(recovery_case)
    audit_count = await session.scalar(
        select(func.count(RecoveryEventRecord.id)).where(
            RecoveryEventRecord.source_event_id.in_(
                {"evt_new_failure", "evt_failure_after_capture"}
            )
        )
    )
    assert second is not None and second.status == "PUBLISHED"
    assert payment.payment_state == PaymentState.CAPTURED
    assert recovery_case.payment_state == PaymentState.CAPTURED
    assert audit_count == 2
    assert len(signals) == 2


async def test_payment_failure_creates_one_deterministic_invoice_scoped_case(
    processor_session: AsyncSession,
) -> None:
    session = processor_session
    merchant = Merchant(id="merchant_fresh", external_id="acc_fresh", display_name="Fresh Merchant")
    customer = Customer(
        id="customer_fresh",
        merchant_id=merchant.id,
        external_id="cust_fitbox_001",
        display_name="Customer",
    )
    subscription = Subscription(
        id="subscription_fresh",
        merchant_id=merchant.id,
        customer_id=customer.id,
        provider_subscription_id="sub_fitbox_annual_001",
        plan_name="Annual",
        amount_paise=149_900,
        subscription_state=SubscriptionState.PENDING,
        current_billing_cycle_key="2026-08",
    )
    invoice = Invoice(
        id="invoice_fresh",
        merchant_id=merchant.id,
        subscription_id=subscription.id,
        provider_invoice_id="inv_fitbox_aug_2026",
        billing_cycle_key="2026-08",
        amount_paise=149_900,
        amount_paid_paise=0,
        currency="INR",
        invoice_state="issued",
    )
    for record in (merchant, customer, subscription, invoice):
        session.add(record)
        await session.flush()
    await session.commit()
    merchant_id = merchant.id
    raw = _raw_fixture("payment.failed.json")
    first_outbox = await _ingest(
        session,
        fixture="payment.failed.json",
        provider_event_id="evt_create_case",
        merchant_id=merchant_id,
        raw_body=raw,
    )
    duplicate_outbox = await _ingest(
        session,
        fixture="payment.failed.json",
        provider_event_id="evt_create_case",
        merchant_id=merchant_id,
        raw_body=raw,
    )
    signals: list[RazorpayDownstreamSignal] = []

    async def callback(signal: RazorpayDownstreamSignal) -> None:
        signals.append(signal)

    processor = RazorpayOutboxProcessor(session, FakePaymentProvider(), callback, clock=lambda: NOW)
    result = await processor.process_next()
    created_case = await session.scalar(
        select(RecoveryCase).where(RecoveryCase.merchant_id == merchant.id)
    )
    payment = await session.scalar(
        select(PaymentAttempt).where(PaymentAttempt.merchant_id == merchant.id)
    )
    audit = await session.scalar(
        select(RecoveryEventRecord).where(RecoveryEventRecord.source_event_id == "evt_create_case")
    )
    assert first_outbox.id == duplicate_outbox.id
    assert result is not None and result.status == "PUBLISHED"
    assert created_case is not None
    assert payment is not None
    assert created_case.id.startswith("case_rzp_")
    assert created_case.customer_id == customer.id
    assert created_case.subscription_id == subscription.id
    assert created_case.failed_invoice_id == invoice.id
    assert created_case.failed_payment_id == payment.id
    assert created_case.payment_state == PaymentState.FAILED
    assert created_case.subscription_state == SubscriptionState.PENDING
    assert created_case.case_outcome == CaseOutcome.OPEN
    assert created_case.diagnosis == Diagnosis.AUTHENTICATION_REQUIRED
    assert created_case.amount_at_risk_paise == 149_900
    assert created_case.recovery_deadline > created_case.opened_at
    assert await session.scalar(select(func.count(RecoveryCase.id))) == 1
    assert await session.scalar(select(func.count(PaymentAttempt.id))) == 1
    assert await session.scalar(select(func.count(OutboxMessage.id))) == 1
    assert audit is not None and audit.payload["case_created"] is True
    assert len(signals) == 1
    assert signals[0].case_id == created_case.id
    assert signals[0].effects["case_created"] is True
    assert await processor.process_next() is None


async def test_capture_delivered_before_failure_retries_after_case_creation(
    processor_session: AsyncSession,
) -> None:
    session = processor_session
    merchant = Merchant(
        id="merchant_out_of_order",
        external_id="acc_out_of_order",
        display_name="Out Of Order Merchant",
    )
    customer = Customer(
        id="customer_out_of_order",
        merchant_id=merchant.id,
        external_id="cust_fitbox_001",
        display_name="Customer",
    )
    subscription = Subscription(
        id="subscription_out_of_order",
        merchant_id=merchant.id,
        customer_id=customer.id,
        provider_subscription_id="sub_fitbox_annual_001",
        plan_name="Annual",
        amount_paise=149_900,
        subscription_state=SubscriptionState.PENDING,
        current_billing_cycle_key="2026-08",
    )
    invoice = Invoice(
        id="invoice_out_of_order",
        merchant_id=merchant.id,
        subscription_id=subscription.id,
        provider_invoice_id="inv_fitbox_aug_2026",
        billing_cycle_key="2026-08",
        amount_paise=149_900,
        amount_paid_paise=0,
        currency="INR",
        invoice_state="issued",
    )
    for record in (merchant, customer, subscription, invoice):
        session.add(record)
        await session.flush()
    await session.commit()
    out_of_order_merchant_id = merchant.id
    captured_raw = _raw_fixture(
        "payment.captured.json",
        changes={"notes": {"subscription_id": "sub_fitbox_annual_001"}},
    )
    captured_outbox = await _ingest(
        session,
        fixture="payment.captured.json",
        provider_event_id="evt_capture_arrived_first",
        merchant_id=out_of_order_merchant_id,
        raw_body=captured_raw,
    )
    await _ingest(
        session,
        fixture="payment.failed.json",
        provider_event_id="evt_failure_arrived_second",
        merchant_id=out_of_order_merchant_id,
    )
    current_time = NOW
    signals: list[RazorpayDownstreamSignal] = []

    def clock() -> datetime:
        return current_time

    async def callback(signal: RazorpayDownstreamSignal) -> None:
        signals.append(signal)

    provider = FakePaymentProvider(_snapshot(subscription_state=SubscriptionState.ACTIVE))
    processor = RazorpayOutboxProcessor(session, provider, callback, clock=clock)
    first_attempt = await processor.process_next()
    failure = await processor.process_next()
    current_time = NOW + timedelta(seconds=6)
    capture_retry = await processor.process_next()

    recovery_case = await session.scalar(
        select(RecoveryCase).where(RecoveryCase.merchant_id == out_of_order_merchant_id)
    )
    await session.refresh(captured_outbox)
    assert first_attempt is not None and first_attempt.status == "FAILED"
    assert first_attempt.error_code == "RAZORPAY_CAPTURE_NOT_CORRELATED"
    assert failure is not None and failure.status == "PUBLISHED"
    assert capture_retry is not None and capture_retry.status == "PUBLISHED"
    assert captured_outbox.attempt_count == 2
    assert captured_outbox.published_at == current_time
    assert recovery_case is not None
    assert recovery_case.payment_state == PaymentState.CAPTURED
    assert recovery_case.case_outcome == CaseOutcome.RECOVERED
    assert recovery_case.arrears_collected_paise == 149_900
    assert await session.scalar(select(func.count(RecoveryCase.id))) == 1
    assert await session.scalar(select(func.count(RevenueRecognitionRecord.id))) == 1
    assert [signal.event_type for signal in signals] == [
        "payment.failed",
        "payment.captured",
    ]


async def test_unconfirmed_capture_records_failure_and_leaves_domain_unmodified(
    processor_session: AsyncSession,
) -> None:
    session = processor_session
    await seed_fitbox(session)
    outbox = await _ingest(
        session,
        fixture="payment.captured.json",
        provider_event_id="evt_unconfirmed_capture",
    )

    async def callback(signal: RazorpayDownstreamSignal) -> None:
        raise AssertionError(f"signal must not run: {signal.provider_event_id}")

    result = await RazorpayOutboxProcessor(
        session,
        FakePaymentProvider(_snapshot(payment_state=PaymentState.PENDING)),
        callback,
        clock=lambda: NOW,
    ).process_next()
    stored_outbox = await session.get(OutboxMessage, outbox.id)
    recovery_case = await session.get(RecoveryCase, FITBOX_CASE_ID)
    assert result is not None and result.status == "FAILED"
    assert result.error_code == "RAZORPAY_CAPTURE_NOT_CONFIRMED"
    assert stored_outbox is not None and stored_outbox.published_at is None
    assert stored_outbox.attempt_count == 1
    assert recovery_case is not None
    assert recovery_case.payment_state == PaymentState.FAILED
    assert await session.scalar(select(func.count(RevenueRecognitionRecord.id))) == 0
