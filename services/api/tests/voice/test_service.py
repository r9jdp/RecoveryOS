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
            status=self.status,  # type: ignore[arg-type]
            reason_code="UNCERTAIN" if self.status == "UNCERTAIN" else None,
        )

    async def cancel_contact(self, *, contact_attempt_id: str, reason: str) -> None:
        self.cancelled.append(f"{contact_attempt_id}:{reason}")

    async def fetch_contact(self, *, contact_attempt_id: str) -> VoiceContactSnapshot:
        raise NotImplementedError


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
        event_id="evt-1", attempt_id="attempt-1", status="completed", duration_seconds=999
    )
    assert await service.apply_twilio_status(
        event_id="evt-1", attempt_id="attempt-1", status="completed", duration_seconds=999
    )
    attempt = await repository.get_attempt("attempt-1")
    assert attempt is not None and attempt.duration_seconds == 180
