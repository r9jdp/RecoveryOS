"""Twilio outbound adapter with uncertain-submission reconciliation semantics."""

from __future__ import annotations

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


class TwilioVoiceProvider:
    """Submit at most once and return UNCERTAIN on transport ambiguity.

    RecoveryOS must reconcile `fetch_contact` using the deterministic attempt
    identifier before an operator decides whether any further submission is safe.
    """

    def __init__(self, config: TwilioConfig, client: httpx.AsyncClient) -> None:
        self._config = config
        self._client = client
        self._attempt_calls: dict[str, str] = {}

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
            return VoiceContactResult(
                provider="twilio",
                contact_attempt_id=request.idempotency_key,
                status="UNCERTAIN",
                reason_code="TWILIO_SUBMISSION_UNCERTAIN_RECONCILE_REQUIRED",
            )
        if response.status_code >= 500:
            return VoiceContactResult(
                provider="twilio",
                contact_attempt_id=request.idempotency_key,
                status="UNCERTAIN",
                reason_code="TWILIO_SUBMISSION_UNCERTAIN_RECONCILE_REQUIRED",
            )
        if response.status_code >= 400:
            return VoiceContactResult(
                provider="twilio",
                contact_attempt_id=request.idempotency_key,
                status="REJECTED",
                reason_code=f"TWILIO_REJECTED_{response.status_code}",
            )
        payload: dict[str, Any] = response.json()
        sid = str(payload["sid"])
        self._attempt_calls[request.idempotency_key] = sid
        return VoiceContactResult(
            provider="twilio",
            contact_attempt_id=request.idempotency_key,
            provider_call_id=sid,
            status="SUBMITTED",
        )

    async def cancel_contact(self, *, contact_attempt_id: str, reason: str) -> None:
        del reason
        sid = self._attempt_calls.get(contact_attempt_id)
        if not sid:
            return
        await self._client.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{self._config.account_sid}/Calls/{sid}.json",
            auth=(self._config.account_sid, self._config.auth_token),
            data={"Status": "completed"},
        )

    async def fetch_contact(self, *, contact_attempt_id: str) -> VoiceContactSnapshot:
        sid = self._attempt_calls.get(contact_attempt_id)
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
        duration = payload.get("duration")
        return VoiceContactSnapshot(
            contact_attempt_id=contact_attempt_id,
            status=str(payload.get("status", "unknown")).upper(),
            duration_seconds=int(duration) if duration else None,
            observed_at=datetime.now(UTC),
        )
