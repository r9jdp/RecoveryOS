from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from services.api.app.db import Base
from services.api.app.domain.enums import (
    CaseOutcome,
    PaymentState,
    RevenueAttribution,
    SubscriptionState,
)
from services.api.app.models import (
    PaymentAttempt,
    RecoveryCase,
    RevenueRecognitionRecord,
    WebhookInboxEntry,
)
from services.api.app.providers.contracts import (
    OpenPaymentSurfaceRequest,
    PaymentSnapshot,
    PaymentSurfaceResult,
    RecoveryScoreRequest,
    RecoveryScoreResult,
)
from services.api.app.seed import FITBOX_CASE_ID, seed_fitbox
from services.worker.app.contracts import ReconciliationInput
from services.worker.app.runtime import ProductionRecoveryActivityServices

NOW = datetime(2026, 8, 28, 9, 0, tzinfo=UTC)
MERCHANT_ID = "merchant_fitbox"
INVOICE_ID = "inv_fitbox_aug_2026"
SUBSCRIPTION_ID = "sub_fitbox_annual_001"
FAILED_PAYMENT_ID = "pay_fitbox_failed_001"
REPLACEMENT_PAYMENT_ID = "pay_replacement_captured_001"
AMOUNT_PAISE = 149_900


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


class FixedScorer:
    async def score(self, request: RecoveryScoreRequest) -> RecoveryScoreResult:
        return RecoveryScoreResult(
            model_name="fixed",
            model_version="test",
            recovery_probability=0.5,
            expected_recovered_paise=request.amount_at_risk_paise // 2,
            expected_utility_paise=request.amount_at_risk_paise // 2,
        )


class SnapshotProvider:
    def __init__(self, snapshot: PaymentSnapshot, *, fail_if_called: bool = False) -> None:
        self.snapshot = snapshot
        self.fail_if_called = fail_if_called
        self.calls: list[tuple[str, str | None, str]] = []

    async def open_customer_payment_surface(
        self, request: OpenPaymentSurfaceRequest
    ) -> PaymentSurfaceResult:
        raise AssertionError(f"payment surface was not expected: {request.case_id}")

    async def fetch_payment_snapshot(
        self, *, merchant_id: str, payment_id: str | None, invoice_id: str
    ) -> PaymentSnapshot:
        if self.fail_if_called:
            raise AssertionError("persisted recognition must avoid a provider call")
        self.calls.append((merchant_id, payment_id, invoice_id))
        return self.snapshot


def snapshot(
    *,
    payment_id: str = REPLACEMENT_PAYMENT_ID,
    subscription_state: SubscriptionState = SubscriptionState.PENDING,
) -> PaymentSnapshot:
    return PaymentSnapshot(
        provider="razorpay",
        payment_id=payment_id,
        invoice_id=INVOICE_ID,
        subscription_id=SUBSCRIPTION_ID,
        payment_state=PaymentState.CAPTURED,
        subscription_state=subscription_state,
        amount_paise=AMOUNT_PAISE,
        currency="INR",
        observed_at=NOW,
        authoritative=True,
    )


def command(
    event_id: str,
    *,
    authoritative_hint: bool = True,
) -> ReconciliationInput:
    return ReconciliationInput(
        case_id=FITBOX_CASE_ID,
        merchant_id=MERCHANT_ID,
        failed_invoice_id=INVOICE_ID,
        failed_payment_id=FAILED_PAYMENT_ID,
        trigger_event_id=event_id,
        payment_state_hint="CAPTURED" if authoritative_hint else None,
        amount_paise_hint=AMOUNT_PAISE if authoritative_hint else None,
        authoritative_hint=authoritative_hint,
    )


def captured_payload(*, event_type: str = "payment.captured") -> dict[str, object]:
    return {
        "event": event_type,
        "created_at": int(NOW.timestamp()),
        "payload": {
            "payment": {
                "entity": {
                    "id": REPLACEMENT_PAYMENT_ID,
                    "invoice_id": INVOICE_ID if event_type != "payment_link.paid" else None,
                    "amount": AMOUNT_PAISE,
                    "currency": "INR",
                    "created_at": int(NOW.timestamp()),
                    "notes": {"subscription_id": SUBSCRIPTION_ID},
                }
            },
            "payment_link": {
                "entity": {
                    "id": "plink_recovery_001",
                    "amount_paid": AMOUNT_PAISE,
                    "currency": "INR",
                    "notes": {
                        "case_id": FITBOX_CASE_ID,
                        "invoice_id": INVOICE_ID,
                        "subscription_id": SUBSCRIPTION_ID,
                    },
                }
            },
        },
    }


async def add_inbox(
    factory: async_sessionmaker[AsyncSession],
    *,
    event_id: str,
    payload: dict[str, object],
) -> None:
    async with factory() as session:
        session.add(
            WebhookInboxEntry(
                id=f"inbox-{event_id}",
                merchant_id=MERCHANT_ID,
                provider="razorpay",
                provider_event_id=event_id,
                event_type=str(payload["event"]),
                payload=payload,
                received_at=NOW,
                occurred_at=NOW,
            )
        )
        await session.commit()


def services(provider: SnapshotProvider) -> ProductionRecoveryActivityServices:
    return ProductionRecoveryActivityServices(
        payment_provider=provider,
        scorer=FixedScorer(),
        clock=lambda: NOW,
    )


async def test_new_capture_wins_over_original_failed_payment_id(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    async with session_factory() as session:
        await seed_fitbox(session)
    await add_inbox(
        session_factory,
        event_id="evt-replacement-captured",
        payload=captured_payload(),
    )
    monkeypatch.setattr("services.worker.app.runtime.get_session_factory", lambda: session_factory)
    provider = SnapshotProvider(snapshot())

    result = await services(provider).reconcile_case(command("evt-replacement-captured"))

    assert provider.calls == [(MERCHANT_ID, REPLACEMENT_PAYMENT_ID, INVOICE_ID)]
    assert provider.calls[0][1] != FAILED_PAYMENT_ID
    assert result.authoritative is True
    assert result.case_recovered is True
    assert result.arrears_collected_paise == AMOUNT_PAISE


async def test_persisted_recognition_converges_duplicate_and_late_success_without_refetch(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    async with session_factory() as session:
        await seed_fitbox(session)
        replacement = PaymentAttempt(
            id="payment-attempt-replacement",
            merchant_id=MERCHANT_ID,
            invoice_id=INVOICE_ID,
            subscription_id=SUBSCRIPTION_ID,
            provider_payment_id=REPLACEMENT_PAYMENT_ID,
            amount_paise=AMOUNT_PAISE,
            currency="INR",
            payment_state=PaymentState.CAPTURED,
            occurred_at=NOW,
        )
        session.add(replacement)
        session.add(
            RevenueRecognitionRecord(
                id="recognition-replacement",
                case_id=FITBOX_CASE_ID,
                merchant_id=MERCHANT_ID,
                payment_attempt_id=replacement.id,
                provider="razorpay",
                provider_event_id="evt-original-late-success",
                amount_paise=AMOUNT_PAISE,
                attribution=RevenueAttribution.RAZORPAY_TEST_VERIFIED,
                arrears_collected=True,
                subscription_reactivated=False,
                recognized_at=NOW,
            )
        )
        recovery_case = await session.get(RecoveryCase, FITBOX_CASE_ID)
        assert recovery_case is not None
        recovery_case.payment_state = PaymentState.CAPTURED
        recovery_case.case_outcome = CaseOutcome.RECOVERED
        recovery_case.case_recovered = True
        recovery_case.arrears_collected_paise = AMOUNT_PAISE
        recovery_case.recovered_at = NOW
        await session.commit()
    monkeypatch.setattr("services.worker.app.runtime.get_session_factory", lambda: session_factory)
    provider = SnapshotProvider(snapshot(), fail_if_called=True)
    activity_services = services(provider)

    first = await activity_services.reconcile_case(command("evt-duplicate-success"))
    duplicate = await activity_services.reconcile_case(command("evt-duplicate-success"))

    assert first == duplicate
    assert first.authoritative is True
    assert first.case_recovered is True
    assert first.provider_reference == REPLACEMENT_PAYMENT_ID
    assert first.arrears_collected_paise == AMOUNT_PAISE


async def test_replacement_payment_link_collects_arrears_without_reactivating_subscription(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    async with session_factory() as session:
        await seed_fitbox(session)
    await add_inbox(
        session_factory,
        event_id="evt-payment-link-paid",
        payload=captured_payload(event_type="payment_link.paid"),
    )
    monkeypatch.setattr("services.worker.app.runtime.get_session_factory", lambda: session_factory)
    provider = SnapshotProvider(snapshot(subscription_state=SubscriptionState.HALTED))

    result = await services(provider).reconcile_case(command("evt-payment-link-paid"))

    assert result.case_recovered is True
    assert result.subscription_state == SubscriptionState.HALTED.value
    assert result.subscription_reactivated is False
    assert provider.calls == [(MERCHANT_ID, REPLACEMENT_PAYMENT_ID, INVOICE_ID)]


async def test_invoice_reconciliation_uses_current_invoice_payment_after_card_update(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    async with session_factory() as session:
        await seed_fitbox(session)
    monkeypatch.setattr("services.worker.app.runtime.get_session_factory", lambda: session_factory)
    provider = SnapshotProvider(snapshot(subscription_state=SubscriptionState.ACTIVE))

    result = await services(provider).reconcile_case(
        command("customer-already-paid", authoritative_hint=False)
    )

    assert provider.calls == [(MERCHANT_ID, None, INVOICE_ID)]
    assert result.case_recovered is True
    assert result.subscription_reactivated is True


async def test_asserted_success_without_durable_webhook_is_not_payment_truth(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    async with session_factory() as session:
        await seed_fitbox(session)
    monkeypatch.setattr("services.worker.app.runtime.get_session_factory", lambda: session_factory)
    provider = SnapshotProvider(snapshot(), fail_if_called=True)

    result = await services(provider).reconcile_case(command("browser-callback-success"))

    assert result.authoritative is False
    assert result.case_recovered is False
    assert result.arrears_collected_paise == 0
