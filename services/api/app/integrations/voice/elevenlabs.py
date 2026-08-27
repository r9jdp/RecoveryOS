"""ElevenLabs Hindi/Hinglish configuration and call registration adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class ElevenLabsAgentConfig:
    agent_id: str
    api_key: str
    api_origin: str = "https://api.elevenlabs.io"
    language: str = "hi"
    first_message: str = (
        "Namaste. Main FitBox ki AI recovery assistant hoon. "
        "Yeh automated call hai. Kya main account ke baare mein baat kar sakti hoon?"
    )
    recording_enabled: bool = False
    max_duration_seconds: int = 180

    def agent_overrides(self) -> dict[str, Any]:
        return {
            "agent": {
                "language": self.language,
                "first_message": self.first_message,
                "prompt": {
                    "prompt": (
                        "Use simple Hindi/Hinglish. Disclose that you are an AI before any case "
                        "details. Never collect card data or execute payment. On opt-out, stop "
                        "immediately."
                    )
                },
            },
            "conversation": {
                "max_duration_seconds": min(self.max_duration_seconds, 180),
                "recording_enabled": False,
            },
        }


class ElevenLabsCallRegistrar:
    """Register a Twilio call with ElevenLabs exactly once per attempt."""

    def __init__(self, config: ElevenLabsAgentConfig, client: httpx.AsyncClient) -> None:
        self._config = config
        self._client = client

    async def register(self, *, twilio_call_sid: str, attempt_id: str) -> str:
        response = await self._client.post(
            f"{self._config.api_origin}/v1/convai/twilio/register-call",
            headers={"xi-api-key": self._config.api_key, "Idempotency-Key": attempt_id},
            json={
                "agent_id": self._config.agent_id,
                "twilio_call_sid": twilio_call_sid,
                "conversation_initiation_client_data": {
                    "conversation_config_override": self._config.agent_overrides(),
                    "custom_llm_extra_body": {"attempt_id": attempt_id},
                },
            },
        )
        response.raise_for_status()
        payload = response.json()
        stream_url = payload.get("stream_url") or payload.get("signed_url")
        if not isinstance(stream_url, str) or not stream_url.startswith("wss://"):
            raise ValueError("ElevenLabs call registration omitted a secure stream_url")
        return stream_url
