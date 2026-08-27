from datetime import UTC, datetime

import httpx
import pytest

from services.api.app.integrations.voice.twilio import (
    TwilioConfig,
    TwilioVoiceProvider,
    render_elevenlabs_twiml,
)
from services.api.app.providers.contracts import VoiceContactRequest


def request() -> VoiceContactRequest:
    return VoiceContactRequest(
        idempotency_key="attempt-123",
        case_id="case-1",
        customer_id="customer-1",
        destination_token="+919999999999",
        preferred_language="hi-IN",
        consent_verified_at=datetime(2026, 8, 1, tzinfo=UTC),
        max_duration_seconds=180,
        disclosure_text="I am an AI",
    )


@pytest.mark.asyncio
async def test_twilio_submission_is_idempotent_and_recording_is_off() -> None:
    submissions: list[httpx.Request] = []

    def handler(incoming: httpx.Request) -> httpx.Response:
        submissions.append(incoming)
        return httpx.Response(201, json={"sid": "CA123", "status": "queued"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = TwilioVoiceProvider(
            TwilioConfig("AC123", "secret", "+12025550100", "https://voice.example"), client
        )
        first = await provider.start_contact(request())
        second = await provider.start_contact(request())

    assert first.provider_call_id == second.provider_call_id == "CA123"
    assert len(submissions) == 1
    assert b"Record=false" in submissions[0].content
    assert b"attempt_id%3Dattempt-123" in submissions[0].content


@pytest.mark.asyncio
async def test_twilio_timeout_is_uncertain_and_never_retried_inside_adapter() -> None:
    calls = 0

    def handler(incoming: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("unknown submit outcome", request=incoming)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = TwilioVoiceProvider(
            TwilioConfig("AC123", "secret", "+12025550100", "https://voice.example"), client
        )
        result = await provider.start_contact(request())

    assert result.status == "UNCERTAIN"
    assert result.reason_code == "TWILIO_SUBMISSION_UNCERTAIN_RECONCILE_REQUIRED"
    assert calls == 1


def test_twiml_escapes_attempt_and_requires_secure_stream() -> None:
    xml = render_elevenlabs_twiml(
        stream_url="wss://eleven.example/stream?a=1&b=2", attempt_id='a"b'
    )
    assert "wss://eleven.example/stream?a=1&amp;b=2" in xml
    assert "a&quot;b" in xml
    with pytest.raises(ValueError):
        render_elevenlabs_twiml(stream_url="ws://insecure", attempt_id="a")
