"""Voice orchestration with immutable safety limits and callback idempotency."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, time
from typing import Any, Literal, Protocol
from zoneinfo import ZoneInfo

from services.api.app.integrations.voice.safety import (
    VoiceIntent,
    VoiceSafetyContext,
    detect_voice_intent,
    evaluate_voice_safety,
)
from services.api.app.providers.contracts import (
    VoiceContactRequest,
    VoiceContactResult,
    VoiceContactSnapshot,
)
from services.api.app.providers.interfaces import VoiceProvider

AI_DISCLOSURE = (
    "Namaste. Main RecoveryOS ki AI assistant hoon. Yeh automated call hai. "
    "Main card details nahi maangungi."
)


class DisabledVoiceProvider:
    """Safe default: browser rehearsal works but no external call can leave the API."""

    def __init__(self, reason_code: str = "REAL_VOICE_PROVIDER_NOT_CONFIGURED") -> None:
        self.reason_code = reason_code

    async def start_contact(self, request: VoiceContactRequest) -> VoiceContactResult:
        return VoiceContactResult(
            provider="mock",
            contact_attempt_id=request.idempotency_key,
            status="REJECTED",
            reason_code=self.reason_code,
        )

    async def cancel_contact(self, *, contact_attempt_id: str, reason: str) -> None:
        del contact_attempt_id, reason

    async def fetch_contact(self, *, contact_attempt_id: str) -> VoiceContactSnapshot:
        return VoiceContactSnapshot(
            contact_attempt_id=contact_attempt_id,
            status="NOT_CONFIGURED",
            observed_at=datetime.now(UTC),
        )


@dataclass(frozen=True)
class VoiceSubject:
    merchant_id: str
    case_id: str
    customer_id: str
    destination_token: str
    preferred_language: str
    consent_verified_at: datetime | None
    opted_out_at: datetime | None
    timezone: str = "Asia/Kolkata"
    kill_switch: bool = False
    quiet_hours_start: time | None = time(20, 0)
    quiet_hours_end: time | None = time(9, 0)


@dataclass(frozen=True)
class VoiceAttempt:
    id: str
    merchant_id: str
    case_id: str
    customer_id: str
    idempotency_key: str
    provider: str
    status: str
    created_at: datetime
    provider_call_id: str | None = None
    disposition: str | None = None
    transcript: str | None = None
    detected_intent: str | None = None
    confidence_basis_points: int | None = None
    duration_seconds: int | None = None
    disclosure_delivered_at: datetime | None = None
    uncertain_submission: bool = False


@dataclass(frozen=True)
class VoiceCancellationClaim:
    """Durable ownership of a single provider cancellation submission."""

    attempt: VoiceAttempt | None
    claimed: bool
    cancellation_key: str


@dataclass(frozen=True)
class VoiceCancellationResult:
    """Outcome of cancellation or its read-only reconciliation."""

    status: Literal["NO_ACTIVE_CALL", "CANCELLED", "UNCERTAIN", "ALREADY_REQUESTED"]
    cancellation_key: str
    attempt_id: str | None = None
    provider_submission_performed: bool = False
    reason_code: str | None = None


class VoiceRepository(Protocol):
    async def load_subject(self, case_id: str) -> VoiceSubject | None: ...

    async def get_by_idempotency(self, idempotency_key: str) -> VoiceAttempt | None: ...

    async def active_count(self) -> int: ...

    async def calls_today(self, now: datetime) -> int: ...

    async def save_attempt(self, attempt: VoiceAttempt) -> VoiceAttempt: ...

    async def get_attempt(self, attempt_id: str) -> VoiceAttempt | None: ...

    async def list_attempts(self, case_id: str) -> list[VoiceAttempt]: ...

    async def apply_callback(
        self, *, provider: str, event_id: str, attempt_id: str, changes: dict[str, Any]
    ) -> tuple[VoiceAttempt | None, bool]: ...

    async def suppress(self, *, attempt: VoiceAttempt, reason_code: str) -> bool: ...

    async def claim_payment_cancellation(
        self, *, case_id: str, cancellation_key: str, now: datetime
    ) -> VoiceCancellationClaim: ...

    async def finalize_payment_cancellation(
        self,
        *,
        attempt_id: str,
        cancellation_key: str,
        confirmed: bool,
        now: datetime,
        error_code: str | None = None,
    ) -> VoiceAttempt: ...

    async def get_payment_cancellation(self, cancellation_key: str) -> VoiceAttempt | None: ...


class InMemoryVoiceRepository:
    """Deterministic adapter for mock mode and unit tests."""

    def __init__(self, subjects: list[VoiceSubject] | None = None) -> None:
        self.subjects = {item.case_id: item for item in subjects or []}
        self.attempts: dict[str, VoiceAttempt] = {}
        self.receipts: set[tuple[str, str]] = set()
        self.suppressions: set[tuple[str, str]] = set()
        self.payment_cancellations: dict[str, str] = {}

    async def load_subject(self, case_id: str) -> VoiceSubject | None:
        return self.subjects.get(case_id)

    async def get_by_idempotency(self, idempotency_key: str) -> VoiceAttempt | None:
        return next(
            (item for item in self.attempts.values() if item.idempotency_key == idempotency_key),
            None,
        )

    async def active_count(self) -> int:
        return sum(
            item.status in {"RESERVED", "SUBMITTED", "RINGING", "IN_PROGRESS"}
            for item in self.attempts.values()
        )

    async def calls_today(self, now: datetime) -> int:
        return sum(item.created_at.date() == now.date() for item in self.attempts.values())

    async def save_attempt(self, attempt: VoiceAttempt) -> VoiceAttempt:
        self.attempts[attempt.id] = attempt
        return attempt

    async def get_attempt(self, attempt_id: str) -> VoiceAttempt | None:
        return self.attempts.get(attempt_id)

    async def list_attempts(self, case_id: str) -> list[VoiceAttempt]:
        return sorted(
            (item for item in self.attempts.values() if item.case_id == case_id),
            key=lambda item: item.created_at,
            reverse=True,
        )

    async def apply_callback(
        self, *, provider: str, event_id: str, attempt_id: str, changes: dict[str, Any]
    ) -> tuple[VoiceAttempt | None, bool]:
        receipt = (provider, event_id)
        if receipt in self.receipts:
            return self.attempts.get(attempt_id), True
        self.receipts.add(receipt)
        current = self.attempts.get(attempt_id)
        if current is None:
            return None, False
        updated = replace(current, **changes)
        self.attempts[attempt_id] = updated
        return updated, False

    async def suppress(self, *, attempt: VoiceAttempt, reason_code: str) -> bool:
        del reason_code
        key = (attempt.merchant_id, attempt.customer_id)
        was_new = key not in self.suppressions
        self.suppressions.add(key)
        subject = self.subjects.get(attempt.case_id)
        if subject:
            self.subjects[attempt.case_id] = replace(subject, opted_out_at=datetime.now(UTC))
        return was_new

    async def claim_payment_cancellation(
        self, *, case_id: str, cancellation_key: str, now: datetime
    ) -> VoiceCancellationClaim:
        del now
        claimed_attempt_id = self.payment_cancellations.get(cancellation_key)
        if claimed_attempt_id is not None:
            return VoiceCancellationClaim(
                attempt=self.attempts.get(claimed_attempt_id),
                claimed=False,
                cancellation_key=cancellation_key,
            )
        attempt = next(
            (
                item
                for item in sorted(
                    self.attempts.values(), key=lambda value: value.created_at, reverse=True
                )
                if item.case_id == case_id
                and item.status in {"RESERVED", "SUBMITTED", "RINGING", "IN_PROGRESS"}
            ),
            None,
        )
        if attempt is None:
            return VoiceCancellationClaim(
                attempt=None, claimed=False, cancellation_key=cancellation_key
            )
        pending = replace(
            attempt,
            status="CANCEL_PENDING",
            disposition="PAYMENT_RECOVERED",
        )
        self.attempts[attempt.id] = pending
        self.payment_cancellations[cancellation_key] = attempt.id
        return VoiceCancellationClaim(
            attempt=pending,
            claimed=True,
            cancellation_key=cancellation_key,
        )

    async def finalize_payment_cancellation(
        self,
        *,
        attempt_id: str,
        cancellation_key: str,
        confirmed: bool,
        now: datetime,
        error_code: str | None = None,
    ) -> VoiceAttempt:
        del now, error_code
        if self.payment_cancellations.get(cancellation_key) != attempt_id:
            raise ValueError("voice cancellation claim does not match the attempt")
        attempt = self.attempts[attempt_id]
        updated = replace(
            attempt,
            status="CANCELED" if confirmed else "CANCEL_UNCERTAIN",
            disposition="PAYMENT_RECOVERED",
            uncertain_submission=not confirmed,
        )
        self.attempts[attempt_id] = updated
        return updated

    async def get_payment_cancellation(self, cancellation_key: str) -> VoiceAttempt | None:
        attempt_id = self.payment_cancellations.get(cancellation_key)
        return self.attempts.get(attempt_id) if attempt_id else None


class VoiceContactService:
    def __init__(
        self,
        *,
        repository: VoiceRepository,
        provider: VoiceProvider,
        real_calls_enabled: bool,
        operator_token: str,
        allowlisted_destinations: frozenset[str],
    ) -> None:
        self.repository = repository
        self.provider = provider
        self.real_calls_enabled = real_calls_enabled
        self.operator_token = operator_token
        self.allowlisted_destinations = allowlisted_destinations

    async def start(
        self,
        *,
        case_id: str,
        idempotency_key: str,
        supplied_operator_token: str | None,
        max_duration_seconds: int,
        now: datetime,
    ) -> VoiceContactResult:
        existing = await self.repository.get_by_idempotency(idempotency_key)
        if existing:
            return VoiceContactResult(
                provider=existing.provider,
                contact_attempt_id=existing.id,
                provider_call_id=existing.provider_call_id,
                status=(
                    "UNCERTAIN"
                    if existing.uncertain_submission
                    else "SUBMITTED"
                    if existing.status not in {"REJECTED"}
                    else "REJECTED"
                ),
                reason_code="IDEMPOTENT_REPLAY",
            )
        subject = await self.repository.load_subject(case_id)
        if not subject:
            return VoiceContactResult(
                provider="voice",
                contact_attempt_id=idempotency_key,
                status="REJECTED",
                reason_code="VOICE_SUBJECT_NOT_FOUND",
            )
        decision = evaluate_voice_safety(
            VoiceSafetyContext(
                now_local=now.astimezone(ZoneInfo(subject.timezone)),
                quiet_hours_start=subject.quiet_hours_start,
                quiet_hours_end=subject.quiet_hours_end,
                real_calls_enabled=self.real_calls_enabled,
                operator_authorized=bool(self.operator_token)
                and supplied_operator_token == self.operator_token,
                kill_switch=subject.kill_switch,
                destination_allowlisted=subject.destination_token in self.allowlisted_destinations,
                consent_verified_at=subject.consent_verified_at,
                opted_out_at=subject.opted_out_at,
                active_calls=await self.repository.active_count(),
                calls_today=await self.repository.calls_today(now),
                max_duration_seconds=max_duration_seconds,
            )
        )
        if not decision.allowed:
            return VoiceContactResult(
                provider="voice",
                contact_attempt_id=idempotency_key,
                status="REJECTED",
                reason_code=decision.reason_code,
            )

        reserved = VoiceAttempt(
            id=idempotency_key,
            merchant_id=subject.merchant_id,
            case_id=subject.case_id,
            customer_id=subject.customer_id,
            idempotency_key=idempotency_key,
            provider="twilio",
            status="RESERVED",
            created_at=now,
        )
        await self.repository.save_attempt(reserved)
        provider_result = await self.provider.start_contact(
            VoiceContactRequest(
                idempotency_key=idempotency_key,
                case_id=case_id,
                customer_id=subject.customer_id,
                destination_token=subject.destination_token,
                preferred_language=subject.preferred_language,
                consent_verified_at=subject.consent_verified_at,
                max_duration_seconds=max_duration_seconds,
                disclosure_text=AI_DISCLOSURE,
            )
        )
        await self.repository.save_attempt(
            replace(
                reserved,
                status=provider_result.status,
                provider_call_id=provider_result.provider_call_id,
                uncertain_submission=provider_result.status == "UNCERTAIN",
            )
        )
        return provider_result

    async def cancel_for_authoritative_payment(
        self,
        *,
        case_id: str,
        cancellation_key: str,
        now: datetime,
    ) -> VoiceCancellationResult:
        """Stop one active call after authoritative recovery, with no blind retry.

        The repository persists the claim before the provider boundary is crossed.
        Any exception is therefore an uncertain submission that can only be resolved
        with ``reconcile_payment_cancellation``; replay never submits another cancel.
        """

        claim = await self.repository.claim_payment_cancellation(
            case_id=case_id,
            cancellation_key=cancellation_key,
            now=now,
        )
        if claim.attempt is None:
            return VoiceCancellationResult(
                status="NO_ACTIVE_CALL",
                cancellation_key=cancellation_key,
                reason_code="VOICE_NO_ACTIVE_CALL",
            )
        if not claim.claimed:
            return VoiceCancellationResult(
                status="ALREADY_REQUESTED",
                cancellation_key=cancellation_key,
                attempt_id=claim.attempt.id,
                reason_code="VOICE_CANCELLATION_ALREADY_REQUESTED",
            )
        try:
            await self.provider.cancel_contact(
                contact_attempt_id=claim.attempt.id,
                reason="AUTHORITATIVE_PAYMENT_SUCCESS",
            )
        except Exception as error:
            await self.repository.finalize_payment_cancellation(
                attempt_id=claim.attempt.id,
                cancellation_key=cancellation_key,
                confirmed=False,
                now=now,
                error_code=type(error).__name__,
            )
            return VoiceCancellationResult(
                status="UNCERTAIN",
                cancellation_key=cancellation_key,
                attempt_id=claim.attempt.id,
                provider_submission_performed=True,
                reason_code="VOICE_CANCELLATION_UNCERTAIN_RECONCILE_REQUIRED",
            )
        await self.repository.finalize_payment_cancellation(
            attempt_id=claim.attempt.id,
            cancellation_key=cancellation_key,
            confirmed=True,
            now=now,
        )
        return VoiceCancellationResult(
            status="CANCELLED",
            cancellation_key=cancellation_key,
            attempt_id=claim.attempt.id,
            provider_submission_performed=True,
        )

    async def reconcile_payment_cancellation(
        self,
        *,
        cancellation_key: str,
        now: datetime,
    ) -> VoiceCancellationResult:
        """Resolve an uncertain cancellation by observation, never resubmission."""

        attempt = await self.repository.get_payment_cancellation(cancellation_key)
        if attempt is None:
            return VoiceCancellationResult(
                status="NO_ACTIVE_CALL",
                cancellation_key=cancellation_key,
                reason_code="VOICE_CANCELLATION_NOT_FOUND",
            )
        if attempt.status == "CANCELED":
            return VoiceCancellationResult(
                status="CANCELLED",
                cancellation_key=cancellation_key,
                attempt_id=attempt.id,
                reason_code="VOICE_CANCELLATION_ALREADY_CONFIRMED",
            )
        try:
            snapshot = await self.provider.fetch_contact(contact_attempt_id=attempt.id)
        except Exception:
            return VoiceCancellationResult(
                status="UNCERTAIN",
                cancellation_key=cancellation_key,
                attempt_id=attempt.id,
                reason_code="VOICE_CANCELLATION_RECONCILIATION_FAILED",
            )
        terminal = snapshot.status.upper() in {
            "BUSY",
            "CANCELED",
            "CANCELLED",
            "COMPLETED",
            "FAILED",
            "NO-ANSWER",
        }
        if not terminal:
            return VoiceCancellationResult(
                status="UNCERTAIN",
                cancellation_key=cancellation_key,
                attempt_id=attempt.id,
                reason_code="VOICE_CANCELLATION_NOT_YET_CONFIRMED",
            )
        await self.repository.finalize_payment_cancellation(
            attempt_id=attempt.id,
            cancellation_key=cancellation_key,
            confirmed=True,
            now=now,
        )
        return VoiceCancellationResult(
            status="CANCELLED",
            cancellation_key=cancellation_key,
            attempt_id=attempt.id,
            reason_code="VOICE_CANCELLATION_RECONCILED",
        )

    async def apply_transcript(
        self, *, attempt_id: str, transcript: str, confidence_basis_points: int, event_id: str
    ) -> tuple[VoiceIntent, bool, bool]:
        intent = detect_voice_intent(transcript)
        attempt, duplicate = await self.repository.apply_callback(
            provider="browser",
            event_id=event_id,
            attempt_id=attempt_id,
            changes={
                "transcript": transcript,
                "detected_intent": intent.value,
                "confidence_basis_points": confidence_basis_points,
                "disposition": intent.value,
            },
        )
        must_end = intent in {
            VoiceIntent.OPT_OUT,
            VoiceIntent.DISPUTE,
            VoiceIntent.WRONG_PERSON,
            VoiceIntent.ALREADY_PAID,
        }
        suppressed = False
        if attempt and intent == VoiceIntent.OPT_OUT and not duplicate:
            suppressed = await self.repository.suppress(
                attempt=attempt, reason_code="VOICE_OPT_OUT"
            )
            await self.provider.cancel_contact(
                contact_attempt_id=attempt.id, reason="VOICE_OPT_OUT"
            )
        return intent, must_end, suppressed and not duplicate

    async def apply_twilio_status(
        self, *, event_id: str, attempt_id: str, status: str, duration_seconds: int | None
    ) -> bool:
        terminal = status.upper() in {"COMPLETED", "BUSY", "NO-ANSWER", "FAILED", "CANCELED"}
        _, duplicate = await self.repository.apply_callback(
            provider="twilio",
            event_id=event_id,
            attempt_id=attempt_id,
            changes={
                "status": status.upper(),
                "duration_seconds": min(duration_seconds, 180)
                if duration_seconds is not None
                else None,
                "disposition": status.upper() if terminal else None,
            },
        )
        return duplicate

    async def apply_elevenlabs_post_call(
        self,
        *,
        event_id: str,
        attempt_id: str,
        transcript: str,
        confidence_basis_points: int,
        duration_seconds: int,
        disclosure_delivered: bool,
    ) -> bool:
        intent = detect_voice_intent(transcript)
        attempt, duplicate = await self.repository.apply_callback(
            provider="elevenlabs",
            event_id=event_id,
            attempt_id=attempt_id,
            changes={
                "status": "COMPLETED",
                "transcript": transcript,
                "detected_intent": intent.value,
                "confidence_basis_points": confidence_basis_points,
                "duration_seconds": min(duration_seconds, 180),
                "disposition": intent.value,
                "disclosure_delivered_at": datetime.now(UTC) if disclosure_delivered else None,
            },
        )
        if attempt and intent == VoiceIntent.OPT_OUT and not duplicate:
            await self.repository.suppress(attempt=attempt, reason_code="VOICE_OPT_OUT")
        return duplicate
