from datetime import UTC, datetime

import pytest

from services.api.app.providers.contracts import (
    VoiceContactRequest,
    VoiceContactResult,
    VoiceContactSnapshot,
)
from services.api.app.voice.service import (
    InMemoryVoiceRepository,
    VoiceAttempt,
    VoiceContactService,
    VoiceSubject,
)


class FakeProvider:
    def __init__(self, status: str = "SUBMITTED") -> None:
        self.status = status
        self.started = 0
        self.cancelled: list[str] = []

    async def start_contact(self, request: VoiceContactRequest) -> VoiceContactResult:
        self.started += 1
        return VoiceContactResult(
            provider="twilio",
            contact_attempt_id=request.idempotency_key,
            provider_call_id=None if self.status == "UNCERTAIN" else "CA123",
            status=self.status,
            reason_code="UNCERTAIN" if self.status == "UNCERTAIN" else None,
        )

    async def cancel_contact(self, *, contact_attempt_id: str, reason: str) -> None:
        self.cancelled.append(f"{contact_attempt_id}:{reason}")

    async def fetch_contact(self, *, contact_attempt_id: str) -> VoiceContactSnapshot:
        raise NotImplementedError


class ExplodingProvider(FakeProvider):
    async def start_contact(self, request: VoiceContactRequest) -> VoiceContactResult:
        self.started += 1
        raise RuntimeError("connection reset after submission")


def make_service(
    *, provider: FakeProvider | None = None
) -> tuple[VoiceContactService, InMemoryVoiceRepository, FakeProvider]:
    selected = provider or FakeProvider()
    repository = InMemoryVoiceRepository(
        [
            VoiceSubject(
                merchant_id="merchant-1",
                case_id="case-1",
                customer_id="customer-1",
                destination_token="+919999999999",
                preferred_language="hi-IN",
                consent_verified_at=datetime(2026, 8, 1, tzinfo=UTC),
                opted_out_at=None,
            )
        ]
    )
    return (
        VoiceContactService(
            repository=repository,
            provider=selected,
            real_calls_enabled=True,
            operator_token="operator-secret",
            allowlisted_destinations=frozenset({"+919999999999"}),
        ),
        repository,
        selected,
    )


@pytest.mark.asyncio
async def test_start_is_operator_guarded_and_idempotent() -> None:
    service, _, provider = make_service()
    now = datetime(2026, 8, 28, 14, tzinfo=UTC)
    blocked = await service.start(
        case_id="case-1",
        idempotency_key="attempt-123",
        supplied_operator_token="wrong",
        max_duration_seconds=180,
        now=now,
    )
    assert blocked.reason_code == "OPERATOR_AUTH_REQUIRED"
    first = await service.start(
        case_id="case-1",
        idempotency_key="attempt-123",
        supplied_operator_token="operator-secret",
        max_duration_seconds=180,
        now=now,
    )
    replay = await service.start(
        case_id="case-1",
        idempotency_key="attempt-123",
        supplied_operator_token="operator-secret",
        max_duration_seconds=180,
        now=now,
    )
    assert first.status == replay.status == "SUBMITTED"
    assert replay.reason_code == "IDEMPOTENT_REPLAY"
    assert provider.started == 1


@pytest.mark.asyncio
async def test_uncertain_submission_stays_uncertain_on_replay() -> None:
    service, _, provider = make_service(provider=FakeProvider("UNCERTAIN"))
    now = datetime(2026, 8, 28, 14, tzinfo=UTC)
    for _ in range(2):
        result = await service.start(
            case_id="case-1",
            idempotency_key="attempt-uncertain",
            supplied_operator_token="operator-secret",
            max_duration_seconds=180,
            now=now,
        )
        assert result.status == "UNCERTAIN"
    assert provider.started == 1


@pytest.mark.asyncio
async def test_reserved_replay_is_uncertain_and_never_resubmits() -> None:
    service, repository, provider = make_service()
    await repository.save_attempt(
        VoiceAttempt(
            id="attempt-reserved",
            merchant_id="merchant-1",
            case_id="case-1",
            customer_id="customer-1",
            idempotency_key="attempt-reserved",
            provider="twilio",
            status="RESERVED",
            created_at=datetime(2026, 8, 28, 14, tzinfo=UTC),
        )
    )

    replay = await service.start(
        case_id="case-1",
        idempotency_key="attempt-reserved",
        supplied_operator_token="operator-secret",
        max_duration_seconds=180,
        now=datetime(2026, 8, 28, 14, tzinfo=UTC),
    )

    assert replay.status == "UNCERTAIN"
    assert replay.reason_code == "RESERVATION_RECONCILIATION_REQUIRED"
    assert provider.started == 0


@pytest.mark.asyncio
async def test_unknown_provider_exception_leaves_durable_uncertain_attempt() -> None:
    provider = ExplodingProvider()
    service, repository, _ = make_service(provider=provider)

    result = await service.start(
        case_id="case-1",
        idempotency_key="attempt-exploded",
        supplied_operator_token="operator-secret",
        max_duration_seconds=180,
        now=datetime(2026, 8, 28, 14, tzinfo=UTC),
    )

    persisted = await repository.get_attempt("attempt-exploded")
    assert result.status == "UNCERTAIN"
    assert persisted is not None and persisted.uncertain_submission
    assert provider.started == 1


@pytest.mark.asyncio
async def test_opt_out_is_immediate_idempotent_and_ends_call() -> None:
    service, repository, provider = make_service()
    attempt = VoiceAttempt(
        id="attempt-1",
        merchant_id="merchant-1",
        case_id="case-1",
        customer_id="customer-1",
        idempotency_key="attempt-1",
        provider="twilio",
        status="IN_PROGRESS",
        created_at=datetime(2026, 8, 28, 14, tzinfo=UTC),
    )
    await repository.save_attempt(attempt)
    first = await service.apply_transcript(
        attempt_id="attempt-1",
        transcript="Stop calling, but I can pay tomorrow",
        confidence_basis_points=9700,
        event_id="evt-1",
    )
    replay = await service.apply_transcript(
        attempt_id="attempt-1",
        transcript="Stop calling, but I can pay tomorrow",
        confidence_basis_points=9700,
        event_id="evt-1",
    )
    assert first == (first[0], True, True)
    assert first[0].value == "OPT_OUT"
    assert replay[2] is False
    assert provider.cancelled == ["attempt-1:VOICE_OPT_OUT"]


@pytest.mark.asyncio
async def test_callback_receipts_are_idempotent_and_duration_is_capped() -> None:
    service, repository, _ = make_service()
    await repository.save_attempt(
        VoiceAttempt(
            id="attempt-1",
            merchant_id="merchant-1",
            case_id="case-1",
            customer_id="customer-1",
            idempotency_key="attempt-1",
            provider="twilio",
            status="SUBMITTED",
            created_at=datetime(2026, 8, 28, 14, tzinfo=UTC),
        )
    )
    assert not await service.apply_twilio_status(
        event_id="evt-1",
        attempt_id="attempt-1",
        status="completed",
        duration_seconds=999,
        provider_call_id="CA-CALLBACK-1",
    )
    assert await service.apply_twilio_status(
        event_id="evt-1", attempt_id="attempt-1", status="completed", duration_seconds=999
    )
    attempt = await repository.get_attempt("attempt-1")
    assert attempt is not None and attempt.duration_seconds == 180
    assert attempt.provider_call_id == "CA-CALLBACK-1"


@pytest.mark.asyncio
async def test_twilio_statuses_are_normalized_and_terminal_state_never_regresses() -> None:
    service, repository, _ = make_service()
    await repository.save_attempt(
        VoiceAttempt(
            id="attempt-status",
            merchant_id="merchant-1",
            case_id="case-1",
            customer_id="customer-1",
            idempotency_key="attempt-status",
            provider="twilio",
            status="SUBMITTED",
            created_at=datetime(2026, 8, 28, 14, tzinfo=UTC),
        )
    )
    await service.apply_twilio_status(
        event_id="status:completed",
        attempt_id="attempt-status",
        status="completed",
        duration_seconds=12,
    )
    await service.apply_twilio_status(
        event_id="status:ringing-late",
        attempt_id="attempt-status",
        status="ringing",
        duration_seconds=None,
    )

    attempt = await repository.get_attempt("attempt-status")
    assert attempt is not None
    assert attempt.status == "COMPLETED"
    assert attempt.disposition == "COMPLETED"
    assert attempt.duration_seconds == 12


@pytest.mark.asyncio
async def test_live_elevenlabs_opt_out_is_idempotent_and_ends_contact() -> None:
    service, repository, provider = make_service()
    await repository.save_attempt(
        VoiceAttempt(
            id="attempt-live-tool",
            merchant_id="merchant-1",
            case_id="case-1",
            customer_id="customer-1",
            idempotency_key="attempt-live-tool",
            provider="twilio",
            status="IN_PROGRESS",
            created_at=datetime(2026, 8, 28, 14, tzinfo=UTC),
        )
    )

    first = await service.apply_live_intent(
        event_id="tool-event-1",
        attempt_id="attempt-live-tool",
        intent="OPT_OUT",
        confidence_basis_points=9900,
    )
    replay = await service.apply_live_intent(
        event_id="tool-event-1",
        attempt_id="attempt-live-tool",
        intent="OPT_OUT",
        confidence_basis_points=9900,
    )

    assert first[0].value == "OPT_OUT"
    assert first[1:] == (True, True, False)
    assert replay[1:] == (True, False, True)
    assert provider.cancelled == ["attempt-live-tool:VOICE_OPT_OUT"]


@pytest.mark.asyncio
async def test_post_call_prefers_structured_intent_and_persists_analysis() -> None:
    service, repository, _ = make_service()
    occurred_at = datetime(2026, 8, 28, 14, 3, tzinfo=UTC)
    await repository.save_attempt(
        VoiceAttempt(
            id="attempt-ai",
            merchant_id="merchant-1",
            case_id="case-1",
            customer_id="customer-1",
            idempotency_key="attempt-ai",
            provider="twilio",
            status="IN_PROGRESS",
            created_at=datetime(2026, 8, 28, 14, tzinfo=UTC),
        )
    )

    duplicate = await service.apply_elevenlabs_post_call(
        event_id="post_call_transcription:conv-ai",
        attempt_id="attempt-ai",
        transcript="agent: When can you pay?\nuser: I will pay tomorrow.",
        intent_transcript="I will pay tomorrow.",
        provider_intent="CALLBACK",
        confidence_basis_points=8700,
        duration_seconds=42,
        disclosure_delivered=True,
        occurred_at=occurred_at,
    )

    attempt = await repository.get_attempt("attempt-ai")
    assert duplicate is False
    assert attempt is not None
    # Ordinary phrase matching is not treated as the real-call AI classifier.
    assert attempt.detected_intent == "CALLBACK"
    assert attempt.disposition == "CALLBACK"
    assert attempt.confidence_basis_points == 8700
    assert attempt.duration_seconds == 42
    assert attempt.disclosure_delivered_at == occurred_at
    assert attempt.transcript == "agent: When can you pay?\nuser: I will pay tomorrow."


@pytest.mark.asyncio
async def test_post_call_high_risk_phrase_overrides_provider_intent_and_suppresses() -> None:
    service, repository, _ = make_service()
    await repository.save_attempt(
        VoiceAttempt(
            id="attempt-stop",
            merchant_id="merchant-1",
            case_id="case-1",
            customer_id="customer-1",
            idempotency_key="attempt-stop",
            provider="twilio",
            status="IN_PROGRESS",
            created_at=datetime(2026, 8, 28, 14, tzinfo=UTC),
        )
    )

    await service.apply_elevenlabs_post_call(
        event_id="post_call_transcription:conv-stop",
        attempt_id="attempt-stop",
        transcript="agent: Can you pay?\nuser: Stop calling me.",
        intent_transcript="Stop calling me.",
        provider_intent="PROMISE_TO_PAY",
        confidence_basis_points=9900,
        duration_seconds=12,
        disclosure_delivered=False,
        occurred_at=datetime(2026, 8, 28, 14, 1, tzinfo=UTC),
    )

    attempt = await repository.get_attempt("attempt-stop")
    assert attempt is not None
    assert attempt.detected_intent == "OPT_OUT"
    assert attempt.confidence_basis_points is None
    assert ("merchant-1", "customer-1") in repository.suppressions


@pytest.mark.asyncio
async def test_post_call_rejects_unknown_structured_intent() -> None:
    service, repository, _ = make_service()
    await repository.save_attempt(
        VoiceAttempt(
            id="attempt-invalid-intent",
            merchant_id="merchant-1",
            case_id="case-1",
            customer_id="customer-1",
            idempotency_key="attempt-invalid-intent",
            provider="twilio",
            status="IN_PROGRESS",
            created_at=datetime(2026, 8, 28, 14, tzinfo=UTC),
        )
    )

    with pytest.raises(ValueError, match="unsupported ElevenLabs structured recovery intent"):
        await service.apply_elevenlabs_post_call(
            event_id="post_call_transcription:conv-invalid",
            attempt_id="attempt-invalid-intent",
            transcript="user: okay",
            intent_transcript="okay",
            provider_intent="SOMETHING_ELSE",
            confidence_basis_points=7000,
            duration_seconds=4,
            disclosure_delivered=False,
            occurred_at=datetime(2026, 8, 28, 14, 1, tzinfo=UTC),
        )

    attempt = await repository.get_attempt("attempt-invalid-intent")
    assert attempt is not None and attempt.status == "IN_PROGRESS"
