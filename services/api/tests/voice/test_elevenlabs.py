import json

import httpx
import pytest

from services.api.app.integrations.voice.elevenlabs import (
    ElevenLabsAgentConfig,
    ElevenLabsCallRegistrar,
    ElevenLabsRecoveryContext,
    parse_elevenlabs_post_call,
)


def _context(*, language: str = "en-IN") -> ElevenLabsRecoveryContext:
    return ElevenLabsRecoveryContext(
        merchant_id="merchant-live",
        merchant_display_name="Acme Fitness",
        case_id="case-live",
        customer_id="customer-live",
        customer_display_name="Aarav Sharma",
        preferred_language=language,
        amount_at_risk_paise=149_900,
        currency="INR",
        diagnosis="AUTHENTICATION_REQUIRED",
        plan_name="Annual membership",
    )


def test_config_uses_customer_language_and_trusted_context_without_fitbox() -> None:
    config = ElevenLabsAgentConfig(agent_id="agent-1", api_key="secret")
    overrides = config.agent_overrides(_context(language="en-IN"))
    assert overrides["agent"]["language"] == "en"
    assert overrides["agent"]["first_message"] == "{{ai_disclosure_message}}"
    assert "FitBox" not in json.dumps(overrides)
    assert "preferred language (en-IN)" in overrides["agent"]["prompt"]["prompt"]
    assert "{{amount_display}}" in overrides["agent"]["prompt"]["prompt"]
    assert overrides["conversation"] == {
        "max_duration_seconds": 180,
        "recording_enabled": False,
    }


@pytest.mark.asyncio
async def test_call_registration_sends_current_fields_and_returns_provider_twiml() -> None:
    requests: list[httpx.Request] = []
    provider_twiml = (
        '<?xml version="1.0"?><Response><Connect><Stream url="wss://x" /></Connect></Response>'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=provider_twiml)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        registrar = ElevenLabsCallRegistrar(
            ElevenLabsAgentConfig(agent_id="agent-1", api_key="secret"), client
        )
        twiml = await registrar.register(
            twilio_call_sid="CA123",
            attempt_id="attempt-1",
            from_number="+12025550100",
            to_number="+919999999999",
            direction="outbound",
            context=_context(),
        )

    assert twiml == provider_twiml
    assert requests[0].headers["Idempotency-Key"] == "attempt-1"
    assert requests[0].headers["xi-api-key"] == "secret"
    body = json.loads(requests[0].content)
    assert body["agent_id"] == "agent-1"
    assert body["from_number"] == "+12025550100"
    assert body["to_number"] == "+919999999999"
    assert body["direction"] == "outbound"
    dynamic = body["conversation_initiation_client_data"]["dynamic_variables"]
    assert dynamic["recoveryos_attempt_id"] == "attempt-1"
    assert dynamic["recoveryos_twilio_call_sid"] == "CA123"
    assert dynamic["merchant_id"] == "merchant-live"
    assert dynamic["merchant_display_name"] == "Acme Fitness"
    assert dynamic["customer_display_name"] == "Aarav Sharma"
    assert dynamic["amount_at_risk_paise"] == 149_900
    assert dynamic["amount_display"] == "INR 1499.00"
    assert dynamic["diagnosis"] == "AUTHENTICATION_REQUIRED"
    assert dynamic["plan_name"] == "Annual membership"
    assert "Acme Fitness" in dynamic["ai_disclosure_message"]
    assert "AI" in dynamic["ai_disclosure_message"]
    assert (
        body["conversation_initiation_client_data"]["conversation_config_override"]["conversation"][
            "recording_enabled"
        ]
        is False
    )


def test_current_post_call_envelope_is_normalized_with_structured_analysis() -> None:
    raw = json.dumps(
        {
            "type": "post_call_transcription",
            "event_timestamp": 1_777_000_000,
            "data": {
                "agent_id": "agent-1",
                "conversation_id": "conv-1",
                "conversation_initiation_client_data": {
                    "dynamic_variables": {"recoveryos_attempt_id": "attempt-1"}
                },
                "transcript": [
                    {"role": "agent", "message": "I am an AI.", "time_in_call_secs": 1},
                    {"role": "user", "message": "Call me later.", "time_in_call_secs": 19},
                ],
                "metadata": {"call_duration_secs": 23},
                "analysis": {
                    "data_collection_results": {
                        "recovery_intent": {"value": "callback"},
                        "intent_confidence": {"value": 0.91},
                        "ai_disclosure_delivered": {"value": True},
                    }
                },
            },
        },
        separators=(",", ":"),
    ).encode()

    event = parse_elevenlabs_post_call(raw, expected_agent_id="agent-1")

    assert event.conversation_id == "conv-1"
    assert event.attempt_id == "attempt-1"
    assert event.transcript == "agent: I am an AI.\nuser: Call me later."
    assert event.user_transcript == "Call me later."
    assert event.provider_intent == "CALLBACK"
    assert event.confidence_basis_points == 9100
    assert event.duration_seconds == 23
    assert event.disclosure_delivered is True


def test_twilio_india_caller_id_is_rejected() -> None:
    from services.api.app.integrations.voice.twilio import TwilioConfig

    with pytest.raises(ValueError, match="international caller ID"):
        TwilioConfig("AC1", "secret", "+919999999999", "https://voice.example")
