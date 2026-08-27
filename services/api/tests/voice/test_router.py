import httpx
import pytest
from fastapi import FastAPI

from services.api.app.voice.router import get_voice_service, router
from services.api.app.voice.service import (
    DisabledVoiceProvider,
    InMemoryVoiceRepository,
    VoiceContactService,
)


@pytest.mark.asyncio
async def test_browser_rehearsal_detects_safety_intent_without_external_attempt() -> None:
    app = FastAPI()
    app.include_router(router)
    service = VoiceContactService(
        repository=InMemoryVoiceRepository(),
        provider=DisabledVoiceProvider(),
        real_calls_enabled=False,
        operator_token="",
        allowlisted_destinations=frozenset(),
    )
    app.dependency_overrides[get_voice_service] = lambda: service

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/v1/voice/contacts/browser-rehearsal-fitbox/browser-transcript",
            headers={"X-Voice-Event-Id": "evt-rehearsal-1"},
            json={
                "transcript": "Stop calling me, although I can pay tomorrow.",
                "confidence_basis_points": 9800,
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "detected_intent": "OPT_OUT",
        "disposition": "OPT_OUT",
        "contact_must_end": True,
        "suppression_persisted": False,
    }
