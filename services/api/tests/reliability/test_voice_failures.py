from __future__ import annotations

from datetime import UTC, datetime

import pytest

from services.api.app.providers.contracts import (
    VoiceContactRequest,
    VoiceContactResult,
    VoiceContactSnapshot,
)
from services.api.app.reliability.voice_projection import VoiceCallbackProjection
from services.api.app.voice.service import (
    InMemoryVoiceRepository,
    VoiceAttempt,
    VoiceContactService,
    VoiceSubject,
)


class UncertainProvider:
    def __init__(self) -> None:
        self.submissions = 0

    async def start_contact(self, request: VoiceContactRequest) -> VoiceContactResult:
        self.submissions += 1
        return VoiceContactResult(
            provider="twilio",
            contact_attempt_id=request.idempotency_key,
            status="UNCERTAIN",
            reason_code="TWILIO_SUBMISSION_UNCERTAIN_RECONCILE_REQUIRED",
        )

    async def cancel_contact(self, *, contact_attempt_id: str, reason: str) -> None:
        del contact_attempt_id, reason

    async def fetch_contact(self, *, contact_attempt_id: str) -> VoiceContactSnapshot:
        return VoiceContactSnapshot(
            contact_attempt_id=contact_attempt_id,
            status="UNKNOWN_RECONCILIATION_REQUIRED",
            observed_at=datetime(2026, 8, 28, 12, tzinfo=UTC),
        )


def _voice_service() -> tuple[VoiceContactService, InMemoryVoiceRepository, UncertainProvider]:
    provider = UncertainProvider()
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
    service = VoiceContactService(
        repository=repository,
        provider=provider,
        real_calls_enabled=True,
        operator_token="operator-secret",
        allowlisted_destinations=frozenset({"+919999999999"}),
    )
    return service, repository, provider


@pytest.mark.asyncio
async def test_uncertain_twilio_submission_is_never_automatically_retried() -> None:
    service, _, provider = _voice_service()
    now = datetime(2026, 8, 28, 14, tzinfo=UTC)
    results = [
        await service.start(
            case_id="case-1",
            idempotency_key="attempt-uncertain",
            supplied_operator_token="operator-secret",
            max_duration_seconds=180,
            now=now,
        )
        for _ in range(3)
    ]
    assert {result.status for result in results} == {"UNCERTAIN"}
    assert provider.submissions == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal_status", ["busy", "no-answer"])
async def test_twilio_terminal_callbacks_are_idempotent(terminal_status: str) -> None:
    service, repository, _ = _voice_service()
    await repository.save_attempt(
        VoiceAttempt(
            id="attempt-1",
            merchant_id="merchant-1",
            case_id="case-1",
            customer_id="customer-1",
            idempotency_key="attempt-1",
            provider="twilio",
            status="RINGING",
            created_at=datetime(2026, 8, 28, 14, tzinfo=UTC),
        )
    )
    first = await service.apply_twilio_status(
        event_id="event-1",
        attempt_id="attempt-1",
        status=terminal_status,
        duration_seconds=0,
    )
    duplicate = await service.apply_twilio_status(
        event_id="event-1",
        attempt_id="attempt-1",
        status=terminal_status,
        duration_seconds=0,
    )
    attempt = await repository.get_attempt("attempt-1")
    assert not first and duplicate
    assert attempt is not None
    assert attempt.status == terminal_status.upper()
    assert attempt.disposition == terminal_status.upper()


def test_late_ringing_does_not_regress_terminal_and_elevenlabs_reconciles() -> None:
    projection = VoiceCallbackProjection(attempt_id="attempt-1")
    completed = projection.apply_twilio(event_id="tw-1", status="COMPLETED")
    late = projection.apply_twilio(event_id="tw-2", status="RINGING")
    failed = projection.apply_elevenlabs(
        event_id="el-1", transcript=None, delivery_error_code="WEBHOOK_TIMEOUT"
    )
    replay = projection.apply_elevenlabs(
        event_id="el-1", transcript="should not be accepted on duplicate"
    )
    reconciled = projection.reconcile_elevenlabs(transcript="AI disclosure. Customer will pay.")

    assert completed.status == "COMPLETED"
    assert late.ignored_regression and late.status == "COMPLETED"
    assert failed.reconciliation_required
    assert failed.reason_code == "ELEVENLABS_POST_CALL_RECONCILIATION_REQUIRED"
    assert replay.duplicate
    assert not reconciled.reconciliation_required
    assert projection.transcript == "AI disclosure. Customer will pay."
