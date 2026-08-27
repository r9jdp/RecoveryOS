"""Environment-gated voice service composition for API and Temporal activities."""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from services.api.app.integrations.voice.twilio import TwilioConfig, TwilioVoiceProvider
from services.api.app.providers.interfaces import VoiceProvider

from .repository import SqlVoiceRepository
from .service import DisabledVoiceProvider, VoiceContactService


def _truthy(value: str | None) -> bool:
    return value is not None and value.casefold() in {"1", "true", "yes", "on"}


def voice_provider_ready() -> bool:
    required = (
        "TWILIO_ACCOUNT_SID",
        "TWILIO_AUTH_TOKEN",
        "TWILIO_FROM_NUMBER",
        "VOICE_PUBLIC_ORIGIN",
    )
    return (
        os.getenv("VOICE_PROVIDER", "mock").strip().casefold() == "twilio"
        and _truthy(os.getenv("VOICE_REAL_CALLS_ENABLED"))
        and all(os.getenv(name, "").strip() for name in required)
    )


@dataclass
class VoiceServiceResources:
    """A composed service and the optional HTTP resource it owns."""

    service: VoiceContactService
    client: httpx.AsyncClient | None = None

    async def aclose(self) -> None:
        if self.client is not None:
            await self.client.aclose()


def create_voice_service_from_env(session: AsyncSession) -> VoiceServiceResources:
    """Compose the safely disabled default or explicitly enabled Twilio adapter."""

    repository = SqlVoiceRepository(session)
    client: httpx.AsyncClient | None = None
    provider: VoiceProvider = DisabledVoiceProvider()
    real_calls_enabled = voice_provider_ready()
    if real_calls_enabled:
        client = httpx.AsyncClient(timeout=10.0)

        async def resolve_call_sid(contact_attempt_id: str) -> str | None:
            attempt = await repository.get_attempt(contact_attempt_id)
            return attempt.provider_call_id if attempt else None

        try:
            provider = TwilioVoiceProvider(
                TwilioConfig(
                    account_sid=os.environ["TWILIO_ACCOUNT_SID"],
                    auth_token=os.environ["TWILIO_AUTH_TOKEN"],
                    from_number=os.environ["TWILIO_FROM_NUMBER"],
                    public_voice_origin=os.environ["VOICE_PUBLIC_ORIGIN"].rstrip("/"),
                ),
                client,
                call_sid_resolver=resolve_call_sid,
            )
        except ValueError:
            # Configuration remains fail-closed even if all variables are present.
            provider = DisabledVoiceProvider("VOICE_PROVIDER_CONFIGURATION_INVALID")
            real_calls_enabled = False

    return VoiceServiceResources(
        service=VoiceContactService(
            repository=repository,
            provider=provider,
            real_calls_enabled=real_calls_enabled,
            operator_token=os.getenv("VOICE_OPERATOR_TOKEN", ""),
            allowlisted_destinations=frozenset(
                item.strip()
                for item in os.getenv("VOICE_ALLOWLIST_DESTINATIONS", "").split(",")
                if item.strip()
            ),
        ),
        client=client,
    )
