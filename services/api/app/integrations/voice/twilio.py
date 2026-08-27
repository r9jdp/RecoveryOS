"""Twilio outbound adapter with uncertain-submission reconciliation semantics."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape
from typing import Any

import httpx

from services.api.app.providers.contracts import (
    VoiceContactRequest,
    VoiceContactResult,
    VoiceContactSnapshot,
)
from services.api.app.reliability.circuit_breaker import FailureKind
from services.api.app.reliability.registry import (
    CircuitBreakerRegistry,
    provider_breaker_registry,
)


@dataclass(frozen=True)
class TwilioConfig:
    account_sid: str
    auth_token: str
    from_number: str
    public_voice_origin: str

    def __post_init__(self) -> None:
        if self.from_number.startswith("+91"):
            raise ValueError("Twilio India outreach must use an international caller ID")
        if not self.public_voice_origin.startswith("https://"):
            raise ValueError("public voice origin must use HTTPS")


def render_elevenlabs_twiml(*, stream_url: str, attempt_id: str) -> str:
    if not stream_url.startswith("wss://"):
        raise ValueError("voice stream must use wss")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Response><Connect><Stream url="'
        f'{escape(stream_url, quote=True)}"'
        '><Parameter name="attempt_id" value="'
        f'{escape(attempt_id, quote=True)}" />'
        "</Stream></Connect></Response>"
    )


CallSidResolver = Callable[[str], Awaitable[str | None]]


class TwilioVoiceProvider:
    """Submit at most once and return UNCERTAIN on transport ambiguity.

    RecoveryOS must reconcile `fetch_contact` using the deterministic attempt
    identifier before an operator decides whether any further submission is safe.
    """

    def __init__(
        self,
        config: TwilioConfig,
        client: httpx.AsyncClient,
        *,
        call_sid_resolver: CallSidResolver | None = None,
        breaker_registry: CircuitBreakerRegistry | None = None,
    ) -> None:
        self._config = config
        self._client = client
        self._call_sid_resolver = call_sid_resolver
        self._attempt_calls: dict[str, str] = {}
        registry = breaker_registry or provider_breaker_registry()
        self._start_breaker = registry.get(
            provider="twilio",
            operation="start_contact",
            scope=config.account_sid,
        )

    async def _resolve_call_sid(self, contact_attempt_id: str) -> str | None:
        known_sid = self._attempt_calls.get(contact_attempt_id)
        if known_sid or self._call_sid_resolver is None:
            return known_sid
        resolved = await self._call_sid_resolver(contact_attempt_id)
        if resolved:
            self._attempt_calls[contact_attempt_id] = resolved
        return resolved

    @property
    def _calls_url(self) -> str:
        return f"https://api.twilio.com/2010-04-01/Accounts/{self._config.account_sid}/Calls.json"

    async def start_contact(self, request: VoiceContactRequest) -> VoiceContactResult:
        known_sid = self._attempt_calls.get(request.idempotency_key)
        if known_sid:
            return VoiceContactResult(
                provider="twilio",
                contact_attempt_id=request.idempotency_key,
                provider_call_id=known_sid,
                status="SUBMITTED",
            )
        decision = self._start_breaker.before_call()
        if not decision.allowed:
            reason = decision.reason
            if reason is None:  # pragma: no cover - defensive invariant
                raise RuntimeError("blocked circuit decision omitted its fallback reason")
            return VoiceContactResult(
                provider="twilio",
                contact_attempt_id=request.idempotency_key,
                status="UNCERTAIN" if reason.requires_reconciliation else "REJECTED",
                reason_code=reason.code,
            )
        try:
            response = await self._client.post(
                self._calls_url,
                auth=(self._config.account_sid, self._config.auth_token),
                data={
                    "To": request.destination_token,
                    "From": self._config.from_number,
                    "Url": (
                        f"{self._config.public_voice_origin}/v1/voice/twiml/"
                        f"{request.idempotency_key}"
                    ),
                    "StatusCallback": (
                        f"{self._config.public_voice_origin}/v1/voice/webhooks/twilio/status"
                        f"?attempt_id={request.idempotency_key}"
                    ),
                    "StatusCallbackEvent": "initiated ringing answered completed",
                    "Timeout": "25",
                    "Record": "false",
                },
            )
        except (httpx.TimeoutException, httpx.NetworkError):
            self._start_breaker.record_failure(FailureKind.UNCERTAIN_SUBMISSION)
            return VoiceContactResult(
                provider="twilio",
                contact_attempt_id=request.idempotency_key,
                status="UNCERTAIN",
                reason_code="TWILIO_SUBMISSION_UNCERTAIN_RECONCILE_REQUIRED",
            )
        if response.status_code >= 500:
            self._start_breaker.record_failure(FailureKind.UNCERTAIN_SUBMISSION)
            return VoiceContactResult(
                provider="twilio",
                contact_attempt_id=request.idempotency_key,
                status="UNCERTAIN",
                reason_code="TWILIO_SUBMISSION_UNCERTAIN_RECONCILE_REQUIRED",
            )
        if response.status_code >= 400:
            self._start_breaker.record_failure(FailureKind.PERMANENT)
            return VoiceContactResult(
                provider="twilio",
                contact_attempt_id=request.idempotency_key,
                status="REJECTED",
                reason_code=f"TWILIO_REJECTED_{response.status_code}",
            )
        payload: dict[str, Any] = response.json()
        sid = str(payload["sid"])
        self._attempt_calls[request.idempotency_key] = sid
        self._start_breaker.record_success()
        return VoiceContactResult(
            provider="twilio",
            contact_attempt_id=request.idempotency_key,
            provider_call_id=sid,
            status="SUBMITTED",
        )

    async def cancel_contact(self, *, contact_attempt_id: str, reason: str) -> None:
        del reason
        sid = await self._resolve_call_sid(contact_attempt_id)
        if not sid:
            return
        await self._client.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{self._config.account_sid}/Calls/{sid}.json",
            auth=(self._config.account_sid, self._config.auth_token),
            data={"Status": "completed"},
        )

    async def fetch_contact(self, *, contact_attempt_id: str) -> VoiceContactSnapshot:
        sid = await self._resolve_call_sid(contact_attempt_id)
        if not sid:
            return VoiceContactSnapshot(
                contact_attempt_id=contact_attempt_id,
                status="UNKNOWN_RECONCILIATION_REQUIRED",
                observed_at=datetime.now(UTC),
            )
        response = await self._client.get(
            f"https://api.twilio.com/2010-04-01/Accounts/{self._config.account_sid}/Calls/{sid}.json",
            auth=(self._config.account_sid, self._config.auth_token),
        )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        if self._start_breaker.uncertain_submission:
            self._start_breaker.record_success()
        duration = payload.get("duration")
        return VoiceContactSnapshot(
            contact_attempt_id=contact_attempt_id,
            status=str(payload.get("status", "unknown")).upper(),
            duration_seconds=int(duration) if duration else None,
            observed_at=datetime.now(UTC),
        )
