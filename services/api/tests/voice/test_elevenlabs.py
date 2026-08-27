import httpx
import pytest

from services.api.app.integrations.voice.elevenlabs import (
    ElevenLabsAgentConfig,
    ElevenLabsCallRegistrar,
)


def test_hindi_hinglish_config_disables_recording_and_caps_duration() -> None:
    config = ElevenLabsAgentConfig(agent_id="agent-1", api_key="secret")
    overrides = config.agent_overrides()
    assert overrides["agent"]["language"] == "hi"
    assert "AI" in overrides["agent"]["first_message"]
    assert overrides["conversation"] == {
        "max_duration_seconds": 180,
        "recording_enabled": False,
    }


@pytest.mark.asyncio
async def test_call_registration_binds_idempotency_key_and_requires_wss() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"stream_url": "wss://eleven.example/conversation"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        registrar = ElevenLabsCallRegistrar(
            ElevenLabsAgentConfig(agent_id="agent-1", api_key="secret"), client
        )
        stream_url = await registrar.register(twilio_call_sid="CA123", attempt_id="attempt-1")

    assert stream_url.startswith("wss://")
    assert requests[0].headers["Idempotency-Key"] == "attempt-1"
    assert b'"recording_enabled":false' in requests[0].content


def test_twilio_india_caller_id_is_rejected() -> None:
    from services.api.app.integrations.voice.twilio import TwilioConfig

    with pytest.raises(ValueError, match="international caller ID"):
        TwilioConfig("AC1", "secret", "+919999999999", "https://voice.example")
