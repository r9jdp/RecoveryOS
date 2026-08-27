"""Idempotent Twilio and ElevenLabs callback convergence."""

from __future__ import annotations

from dataclasses import dataclass, field

_TWILIO_TERMINAL = frozenset({"COMPLETED", "BUSY", "NO-ANSWER", "FAILED", "CANCELED"})


@dataclass(frozen=True, slots=True)
class CallbackEffect:
    duplicate: bool
    ignored_regression: bool
    status: str
    reconciliation_required: bool
    reason_code: str | None = None


@dataclass(slots=True)
class VoiceCallbackProjection:
    """Converge independently delivered provider callbacks for one attempt."""

    attempt_id: str
    status: str = "SUBMITTED"
    transcript: str | None = None
    disposition: str | None = None
    reconciliation_required: bool = False
    _receipts: set[tuple[str, str]] = field(default_factory=set)

    def apply_twilio(self, *, event_id: str, status: str) -> CallbackEffect:
        if self._duplicate("twilio", event_id):
            return self._effect(duplicate=True)
        normalized = status.upper()
        terminal = self.status in _TWILIO_TERMINAL
        if terminal and normalized not in _TWILIO_TERMINAL:
            return self._effect(ignored_regression=True)
        if terminal and normalized != self.status:
            return self._effect(ignored_regression=True)
        self.status = normalized
        if normalized in _TWILIO_TERMINAL:
            self.disposition = normalized
        return self._effect()

    def apply_elevenlabs(
        self,
        *,
        event_id: str,
        transcript: str | None,
        delivery_error_code: str | None = None,
    ) -> CallbackEffect:
        if self._duplicate("elevenlabs", event_id):
            return self._effect(duplicate=True)
        if delivery_error_code:
            self.reconciliation_required = True
            return self._effect(reason_code="ELEVENLABS_POST_CALL_RECONCILIATION_REQUIRED")
        if transcript is None:
            self.reconciliation_required = True
            return self._effect(reason_code="ELEVENLABS_TRANSCRIPT_MISSING")
        self.transcript = transcript
        self.reconciliation_required = False
        if self.status not in _TWILIO_TERMINAL:
            self.status = "COMPLETED"
        return self._effect()

    def reconcile_elevenlabs(self, *, transcript: str | None) -> CallbackEffect:
        if transcript is None:
            self.reconciliation_required = True
            return self._effect(reason_code="ELEVENLABS_TRANSCRIPT_STILL_UNAVAILABLE")
        self.transcript = transcript
        self.reconciliation_required = False
        return self._effect()

    def _duplicate(self, provider: str, event_id: str) -> bool:
        receipt = (provider, event_id)
        if receipt in self._receipts:
            return True
        self._receipts.add(receipt)
        return False

    def _effect(
        self,
        *,
        duplicate: bool = False,
        ignored_regression: bool = False,
        reason_code: str | None = None,
    ) -> CallbackEffect:
        return CallbackEffect(
            duplicate=duplicate,
            ignored_regression=ignored_regression,
            status=self.status,
            reconciliation_required=self.reconciliation_required,
            reason_code=reason_code,
        )
