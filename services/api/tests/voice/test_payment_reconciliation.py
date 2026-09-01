from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool

from services.api.app.db import Base
from services.api.app.models import Customer
from services.api.app.providers.contracts import (
    VoiceContactRequest,
    VoiceContactResult,
    VoiceContactSnapshot,
)
from services.api.app.seed import FITBOX_CASE_ID, seed_fitbox
from services.api.app.voice.factory import create_voice_service_from_env, voice_provider_ready
from services.api.app.voice.models import VoiceContactAttemptRecord, VoiceWebhookReceiptRecord
from services.api.app.voice.repository import SqlVoiceRepository
from services.api.app.voice.service import (
    DisabledVoiceProvider,
    InMemoryVoiceRepository,
    VoiceAttempt,
    VoiceContactService,
)

NOW = datetime(2026, 8, 28, 14, tzinfo=UTC)
CANCELLATION_KEY = "case_fitbox_aug_2026:cancel:authoritative-payment"


class CancellationProvider:
    def __init__(
        self,
        *,
        cancel_error: Exception | None = None,
        observed_status: str = "CANCELED",
    ) -> None:
        self.cancel_error = cancel_error
        self.observed_status = observed_status
        self.cancel_calls: list[tuple[str, str]] = []
        self.fetch_calls: list[str] = []

    async def start_contact(self, request: VoiceContactRequest) -> VoiceContactResult:
        raise AssertionError(f"payment reconciliation cannot start a call: {request.case_id}")

    async def cancel_contact(self, *, contact_attempt_id: str, reason: str) -> None:
        self.cancel_calls.append((contact_attempt_id, reason))
        if self.cancel_error:
            raise self.cancel_error

    async def fetch_contact(self, *, contact_attempt_id: str) -> VoiceContactSnapshot:
        self.fetch_calls.append(contact_attempt_id)
        return VoiceContactSnapshot(
            contact_attempt_id=contact_attempt_id,
            status=self.observed_status,
            observed_at=NOW,
        )


class ReservationObservingProvider(CancellationProvider):
    def __init__(self, engine: AsyncEngine) -> None:
        super().__init__()
        self.engine = engine
        self.reservation_visible = False

    async def start_contact(self, request: VoiceContactRequest) -> VoiceContactResult:
        async with AsyncSession(self.engine, expire_on_commit=False) as observer:
            self.reservation_visible = (
                await observer.get(VoiceContactAttemptRecord, request.idempotency_key) is not None
            )
        return VoiceContactResult(
            provider="twilio",
            contact_attempt_id=request.idempotency_key,
            provider_call_id="CA-RESERVATION-1",
            status="SUBMITTED",
        )


def _attempt(*, status: str = "IN_PROGRESS") -> VoiceAttempt:
    return VoiceAttempt(
        id="voice-attempt-1",
        merchant_id="merchant-1",
        case_id="case-1",
        customer_id="customer-1",
        idempotency_key="voice-attempt-1",
        provider="twilio",
        status=status,
        created_at=NOW,
        provider_call_id="CA123",
    )


def _service(
    *,
    attempt: VoiceAttempt | None = None,
    provider: CancellationProvider | None = None,
) -> tuple[VoiceContactService, InMemoryVoiceRepository, CancellationProvider]:
    repository = InMemoryVoiceRepository()
    if attempt:
        repository.attempts[attempt.id] = attempt
    selected_provider = provider or CancellationProvider()
    return (
        VoiceContactService(
            repository=repository,
            provider=selected_provider,
            real_calls_enabled=False,
            operator_token="",
            allowlisted_destinations=frozenset(),
        ),
        repository,
        selected_provider,
    )


@pytest.mark.asyncio
async def test_runtime_factory_preserves_mock_disabled_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "VOICE_PROVIDER",
        "VOICE_REAL_CALLS_ENABLED",
        "TWILIO_ACCOUNT_SID",
        "TWILIO_AUTH_TOKEN",
        "TWILIO_FROM_NUMBER",
        "VOICE_PUBLIC_ORIGIN",
    ):
        monkeypatch.delenv(name, raising=False)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with AsyncSession(engine) as session:
            resources = create_voice_service_from_env(session)
            assert isinstance(resources.service.provider, DisabledVoiceProvider)
            assert not resources.service.real_calls_enabled
            assert resources.client is None
            await resources.aclose()
    finally:
        await engine.dispose()


def test_voice_readiness_requires_complete_twilio_elevenlabs_and_operator_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    complete = {
        "VOICE_PROVIDER": "twilio",
        "VOICE_REAL_CALLS_ENABLED": "true",
        "TWILIO_ACCOUNT_SID": "AC123",
        "TWILIO_AUTH_TOKEN": "twilio-secret",
        "TWILIO_FROM_NUMBER": "+12025550100",
        "VOICE_PUBLIC_ORIGIN": "https://voice.recovery.test",
        "ELEVENLABS_API_KEY": "eleven-api-key",
        "ELEVENLABS_AGENT_ID": "agent-recovery",
        "ELEVENLABS_WEBHOOK_SECRET": "webhook-secret",
        "VOICE_OPERATOR_TOKEN": "operator-secret",
        "VOICE_ALLOWLIST_DESTINATIONS": "+919999999999",
    }
    for name, value in complete.items():
        monkeypatch.setenv(name, value)
    assert voice_provider_ready()

    for required in (
        "ELEVENLABS_API_KEY",
        "ELEVENLABS_AGENT_ID",
        "ELEVENLABS_WEBHOOK_SECRET",
        "VOICE_OPERATOR_TOKEN",
        "VOICE_ALLOWLIST_DESTINATIONS",
    ):
        monkeypatch.delenv(required)
        assert not voice_provider_ready(), required
        monkeypatch.setenv(required, complete[required])
    monkeypatch.setenv("VOICE_ALLOWLIST_DESTINATIONS", " , ")
    assert not voice_provider_ready()


@pytest.mark.asyncio
async def test_authoritative_payment_cancels_active_call_once() -> None:
    service, repository, provider = _service(attempt=_attempt())

    result = await service.cancel_for_authoritative_payment(
        case_id="case-1", cancellation_key=CANCELLATION_KEY, now=NOW
    )

    stored = await repository.get_attempt("voice-attempt-1")
    assert result.status == "CANCELLED"
    assert result.provider_submission_performed
    assert provider.cancel_calls == [("voice-attempt-1", "AUTHORITATIVE_PAYMENT_SUCCESS")]
    assert stored is not None
    assert stored.status == "CANCELED"
    assert stored.disposition == "PAYMENT_RECOVERED"
    assert not stored.uncertain_submission


@pytest.mark.asyncio
async def test_duplicate_and_out_of_order_success_never_duplicate_provider_cancel() -> None:
    service, _, provider = _service(attempt=_attempt(status="RINGING"))

    first = await service.cancel_for_authoritative_payment(
        case_id="case-1", cancellation_key=CANCELLATION_KEY, now=NOW
    )
    duplicate = await service.cancel_for_authoritative_payment(
        case_id="case-1", cancellation_key=CANCELLATION_KEY, now=NOW
    )
    later_provider_event = await service.cancel_for_authoritative_payment(
        case_id="case-1",
        cancellation_key="case_fitbox_aug_2026:another-success-event",
        now=NOW,
    )

    assert first.status == "CANCELLED"
    assert duplicate.status == "ALREADY_REQUESTED"
    assert later_provider_event.status == "NO_ACTIVE_CALL"
    assert len(provider.cancel_calls) == 1


@pytest.mark.asyncio
async def test_no_active_call_is_a_successful_noop() -> None:
    service, _, provider = _service()

    result = await service.cancel_for_authoritative_payment(
        case_id="case-1", cancellation_key=CANCELLATION_KEY, now=NOW
    )

    assert result.status == "NO_ACTIVE_CALL"
    assert not result.provider_submission_performed
    assert provider.cancel_calls == []


@pytest.mark.asyncio
async def test_existing_real_call_is_not_falsely_cancelled_when_provider_is_disabled() -> None:
    repository = InMemoryVoiceRepository()
    repository.attempts["voice-attempt-1"] = _attempt()
    service = VoiceContactService(
        repository=repository,
        provider=DisabledVoiceProvider(),
        real_calls_enabled=False,
        operator_token="",
        allowlisted_destinations=frozenset(),
    )

    result = await service.cancel_for_authoritative_payment(
        case_id="case-1", cancellation_key=CANCELLATION_KEY, now=NOW
    )

    stored = await repository.get_attempt("voice-attempt-1")
    assert result.status == "UNCERTAIN"
    assert not result.provider_submission_performed
    assert result.reason_code == "VOICE_CANCELLATION_PROVIDER_NOT_CONFIGURED"
    assert stored is not None
    assert stored.status == "CANCEL_UNCERTAIN"
    assert stored.uncertain_submission


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal_status", ["COMPLETED", "BUSY", "FAILED", "CANCELED"])
async def test_already_terminal_call_is_never_cancelled(terminal_status: str) -> None:
    service, repository, provider = _service(attempt=_attempt(status=terminal_status))

    result = await service.cancel_for_authoritative_payment(
        case_id="case-1", cancellation_key=CANCELLATION_KEY, now=NOW
    )

    stored = await repository.get_attempt("voice-attempt-1")
    assert result.status == "NO_ACTIVE_CALL"
    assert provider.cancel_calls == []
    assert stored is not None and stored.status == terminal_status


@pytest.mark.asyncio
async def test_uncertain_cancel_is_observed_without_blind_resubmission() -> None:
    provider = CancellationProvider(cancel_error=TimeoutError("provider response lost"))
    service, repository, _ = _service(attempt=_attempt(), provider=provider)

    uncertain = await service.cancel_for_authoritative_payment(
        case_id="case-1", cancellation_key=CANCELLATION_KEY, now=NOW
    )
    replay = await service.cancel_for_authoritative_payment(
        case_id="case-1", cancellation_key=CANCELLATION_KEY, now=NOW
    )
    reconciled = await service.reconcile_payment_cancellation(
        cancellation_key=CANCELLATION_KEY, now=NOW
    )

    stored = await repository.get_attempt("voice-attempt-1")
    assert uncertain.status == "UNCERTAIN"
    assert uncertain.reason_code == "VOICE_CANCELLATION_UNCERTAIN_RECONCILE_REQUIRED"
    assert replay.status == "ALREADY_REQUESTED"
    assert reconciled.status == "CANCELLED"
    assert provider.cancel_calls == [("voice-attempt-1", "AUTHORITATIVE_PAYMENT_SUCCESS")]
    assert provider.fetch_calls == ["voice-attempt-1"]
    assert stored is not None
    assert stored.status == "CANCELED"
    assert stored.disposition == "PAYMENT_RECOVERED"


@pytest.mark.asyncio
async def test_sql_repository_persists_claim_timeline_and_duplicate_guard() -> None:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    provider = CancellationProvider()
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await seed_fitbox(session)
            session.add(
                VoiceContactAttemptRecord(
                    id="voice-sql-1",
                    merchant_id="merchant_fitbox",
                    case_id=FITBOX_CASE_ID,
                    customer_id="customer_fitbox_001",
                    idempotency_key="voice-sql-1",
                    destination_token="phone-token",
                    provider="twilio",
                    provider_call_id="CA-SQL-1",
                    status="IN_PROGRESS",
                    provider_payload={},
                    disclosure_text="Automated AI call",
                    consent_verified_at=NOW,
                    recording_enabled=False,
                    max_duration_seconds=180,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            await session.commit()
            service = VoiceContactService(
                repository=SqlVoiceRepository(session),
                provider=provider,
                real_calls_enabled=False,
                operator_token="",
                allowlisted_destinations=frozenset(),
            )
            result = await service.cancel_for_authoritative_payment(
                case_id=FITBOX_CASE_ID,
                cancellation_key=CANCELLATION_KEY,
                now=NOW,
            )
            duplicate = await service.cancel_for_authoritative_payment(
                case_id=FITBOX_CASE_ID,
                cancellation_key=CANCELLATION_KEY,
                now=NOW,
            )
            await session.commit()
            assert result.status == "CANCELLED"
            assert duplicate.status == "ALREADY_REQUESTED"

        async with AsyncSession(engine, expire_on_commit=False) as verification_session:
            record = await verification_session.get(VoiceContactAttemptRecord, "voice-sql-1")
            receipt_count = await verification_session.scalar(
                select(func.count(VoiceWebhookReceiptRecord.id)).where(
                    VoiceWebhookReceiptRecord.provider == "recoveryos-payment"
                )
            )
            assert record is not None
            assert record.status == "CANCELED"
            assert record.disposition == "PAYMENT_RECOVERED"
            assert record.completed_at == NOW
            assert record.provider_payload["payment_cancellation"]["state"] == "CONFIRMED"
            assert receipt_count == 1
            assert provider.cancel_calls == [("voice-sql-1", "AUTHORITATIVE_PAYMENT_SUCCESS")]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_sql_reservation_commits_before_provider_and_loads_real_case_context() -> None:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    provider = ReservationObservingProvider(engine)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await seed_fitbox(session)
            customer = await session.get(Customer, "customer_fitbox_001")
            assert customer is not None
            customer.phone_token = "+919999999999"
            customer.voice_consent_at = NOW
            customer.preferred_language = "hi-IN"
            await session.commit()
            repository = SqlVoiceRepository(session)
            subject = await repository.load_subject(FITBOX_CASE_ID)
            assert subject is not None
            assert subject.merchant_display_name == "FitBox"
            assert subject.customer_display_name == "Aarav Sharma"
            assert subject.amount_at_risk_paise == 149_900
            assert subject.diagnosis == "AUTHENTICATION_REQUIRED"
            assert subject.plan_name == "FitBox Annual"

            service = VoiceContactService(
                repository=repository,
                provider=provider,
                real_calls_enabled=True,
                operator_token="operator-secret",
                allowlisted_destinations=frozenset({"+919999999999"}),
            )
            result = await service.start(
                case_id=FITBOX_CASE_ID,
                idempotency_key="voice-reservation-committed",
                supplied_operator_token="operator-secret",
                max_duration_seconds=180,
                now=NOW,
            )
            await session.commit()

        assert result.status == "SUBMITTED"
        assert provider.reservation_visible
    finally:
        await engine.dispose()
