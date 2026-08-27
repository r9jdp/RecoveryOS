"""Isolated FastAPI router for guarded voice contact and signed callbacks."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from functools import lru_cache
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status

from services.api.app.integrations.voice.elevenlabs import ElevenLabsCallRegistrar
from services.api.app.integrations.voice.safety import VoiceIntent
from services.api.app.integrations.voice.signatures import (
    verify_elevenlabs_signature,
    verify_twilio_signature,
)

from .schemas import (
    BrowserTranscriptRequest,
    BrowserTranscriptResponse,
    StartVoiceContactRequest,
    StartVoiceContactResponse,
    VoiceAttemptResponse,
    VoiceTimelineResponse,
    WebhookAcceptedResponse,
)
from .service import DisabledVoiceProvider, InMemoryVoiceRepository, VoiceContactService

router = APIRouter(prefix="/v1/voice", tags=["voice"])


def _truthy(value: str | None) -> bool:
    return value is not None and value.casefold() in {"1", "true", "yes", "on"}


@lru_cache(maxsize=1)
def get_voice_service() -> VoiceContactService:
    """Safe default dependency; coordinator replaces this with SQL + Twilio wiring."""

    return VoiceContactService(
        repository=InMemoryVoiceRepository(),
        provider=DisabledVoiceProvider(),
        real_calls_enabled=_truthy(os.getenv("VOICE_REAL_CALLS_ENABLED")),
        operator_token=os.getenv("VOICE_OPERATOR_TOKEN", ""),
        allowlisted_destinations=frozenset(
            item.strip()
            for item in os.getenv("VOICE_ALLOWLIST_DESTINATIONS", "").split(",")
            if item.strip()
        ),
    )


def get_call_registrar() -> ElevenLabsCallRegistrar:
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"code": "ELEVENLABS_NOT_CONFIGURED", "message": "Call registration unavailable"},
    )


VoiceServiceDependency = Annotated[VoiceContactService, Depends(get_voice_service)]
RegistrarDependency = Annotated[ElevenLabsCallRegistrar, Depends(get_call_registrar)]


@router.post("/contacts", response_model=StartVoiceContactResponse)
async def start_voice_contact(
    payload: StartVoiceContactRequest,
    service: VoiceServiceDependency,
    x_recovery_operator_token: Annotated[str | None, Header()] = None,
) -> StartVoiceContactResponse:
    result = await service.start(
        case_id=payload.case_id,
        idempotency_key=payload.idempotency_key,
        supplied_operator_token=x_recovery_operator_token,
        max_duration_seconds=payload.max_duration_seconds,
        now=datetime.now(UTC),
    )
    return StartVoiceContactResponse(
        attempt_id=result.contact_attempt_id,
        provider=result.provider,
        provider_call_id=result.provider_call_id,
        status=result.status,
        reason_code=result.reason_code or result.status,
        retry_permitted=False,
    )


@router.get("/cases/{case_id}/timeline", response_model=VoiceTimelineResponse)
async def voice_timeline(case_id: str, service: VoiceServiceDependency) -> VoiceTimelineResponse:
    attempts = await service.repository.list_attempts(case_id)
    return VoiceTimelineResponse(
        items=[
            VoiceAttemptResponse(
                id=item.id,
                case_id=item.case_id,
                status=item.status,
                disposition=item.disposition,
                transcript=item.transcript,
                detected_intent=item.detected_intent,
                confidence_basis_points=item.confidence_basis_points,
                duration_seconds=item.duration_seconds,
                disclosure_delivered_at=item.disclosure_delivered_at,
                created_at=item.created_at,
            )
            for item in attempts
        ]
    )


@router.post("/contacts/{attempt_id}/browser-transcript", response_model=BrowserTranscriptResponse)
async def browser_transcript(
    attempt_id: str,
    payload: BrowserTranscriptRequest,
    service: VoiceServiceDependency,
    x_voice_event_id: Annotated[str, Header(min_length=1)],
) -> BrowserTranscriptResponse:
    if await service.repository.get_attempt(attempt_id) is None:
        raise HTTPException(status_code=404, detail={"code": "VOICE_ATTEMPT_NOT_FOUND"})
    intent, must_end, suppression_persisted = await service.apply_transcript(
        attempt_id=attempt_id,
        transcript=payload.transcript,
        confidence_basis_points=payload.confidence_basis_points,
        event_id=x_voice_event_id,
    )
    return BrowserTranscriptResponse(
        detected_intent=intent.value,
        disposition=intent.value,
        contact_must_end=must_end,
        suppression_persisted=suppression_persisted,
    )


@router.post("/twiml/{attempt_id}", response_class=Response)
async def twiml_for_elevenlabs(
    attempt_id: str,
    request: Request,
    service: VoiceServiceDependency,
    registrar: RegistrarDependency,
    x_twilio_signature: Annotated[str | None, Header()] = None,
) -> Response:
    form = {key: str(value) for key, value in (await request.form()).items()}
    public_origin = os.getenv("VOICE_PUBLIC_ORIGIN", "").rstrip("/")
    public_url = f"{public_origin}/v1/voice/twiml/{attempt_id}"
    if not verify_twilio_signature(
        auth_token=os.getenv("TWILIO_AUTH_TOKEN", ""),
        url=public_url,
        parameters=form,
        supplied=x_twilio_signature,
    ):
        raise HTTPException(status_code=401, detail={"code": "INVALID_TWILIO_SIGNATURE"})
    attempt = await service.repository.get_attempt(attempt_id)
    if attempt is None:
        raise HTTPException(status_code=404, detail={"code": "VOICE_ATTEMPT_NOT_FOUND"})
    call_sid = form.get("CallSid")
    if not call_sid:
        raise HTTPException(status_code=422, detail={"code": "TWILIO_CALL_SID_REQUIRED"})
    stream_url = await registrar.register(twilio_call_sid=call_sid, attempt_id=attempt_id)
    # Import locally so router import remains free of provider configuration.
    from services.api.app.integrations.voice.twilio import render_elevenlabs_twiml

    return Response(
        render_elevenlabs_twiml(stream_url=stream_url, attempt_id=attempt_id),
        media_type="application/xml",
    )


@router.post("/webhooks/twilio/status", response_model=WebhookAcceptedResponse)
async def twilio_status_webhook(
    request: Request,
    service: VoiceServiceDependency,
    attempt_id: Annotated[str, Query(min_length=1)],
    x_twilio_signature: Annotated[str | None, Header()] = None,
) -> WebhookAcceptedResponse:
    form = {key: str(value) for key, value in (await request.form()).items()}
    public_origin = os.getenv("VOICE_PUBLIC_ORIGIN", "").rstrip("/")
    public_url = f"{public_origin}/v1/voice/webhooks/twilio/status?attempt_id={attempt_id}"
    if not verify_twilio_signature(
        auth_token=os.getenv("TWILIO_AUTH_TOKEN", ""),
        url=public_url,
        parameters=form,
        supplied=x_twilio_signature,
    ):
        raise HTTPException(status_code=401, detail={"code": "INVALID_TWILIO_SIGNATURE"})
    event_id = (
        form.get("SequenceNumber") or f"{form.get('CallSid', '')}:{form.get('CallStatus', '')}"
    )
    duplicate = await service.apply_twilio_status(
        event_id=event_id,
        attempt_id=attempt_id,
        status=form.get("CallStatus", "unknown"),
        duration_seconds=int(form["CallDuration"]) if form.get("CallDuration") else None,
    )
    return WebhookAcceptedResponse(duplicate=duplicate)


@router.post("/webhooks/elevenlabs/post-call", response_model=WebhookAcceptedResponse)
async def elevenlabs_post_call_webhook(
    request: Request,
    service: VoiceServiceDependency,
    elevenlabs_signature: Annotated[str | None, Header(alias="ElevenLabs-Signature")] = None,
    elevenlabs_timestamp: Annotated[str | None, Header(alias="ElevenLabs-Timestamp")] = None,
) -> WebhookAcceptedResponse:
    raw = await request.body()
    if not verify_elevenlabs_signature(
        secret=os.getenv("ELEVENLABS_WEBHOOK_SECRET", ""),
        body=raw,
        supplied=elevenlabs_signature,
        timestamp=elevenlabs_timestamp,
    ):
        raise HTTPException(status_code=401, detail={"code": "INVALID_ELEVENLABS_SIGNATURE"})
    payload: dict[str, Any] = await request.json()
    attempt_id = str(payload.get("attempt_id", ""))
    event_id = str(payload.get("event_id", ""))
    if not attempt_id or not event_id:
        raise HTTPException(status_code=422, detail={"code": "VOICE_WEBHOOK_IDS_REQUIRED"})
    raw_analysis = payload.get("analysis")
    analysis: dict[str, Any] = (
        {str(key): value for key, value in raw_analysis.items()}
        if isinstance(raw_analysis, dict)
        else {}
    )
    duplicate = await service.apply_elevenlabs_post_call(
        event_id=event_id,
        attempt_id=attempt_id,
        transcript=str(payload.get("transcript", "")),
        confidence_basis_points=max(
            0, min(10_000, int(analysis.get("confidence_basis_points", 0)))
        ),
        duration_seconds=max(0, min(180, int(payload.get("duration_seconds", 0)))),
        disclosure_delivered=bool(analysis.get("ai_disclosure_delivered", False)),
    )
    return WebhookAcceptedResponse(duplicate=duplicate)


@router.get("/intents", response_model=list[str])
async def supported_voice_intents() -> list[str]:
    return [item.value for item in VoiceIntent]
