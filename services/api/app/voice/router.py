"""Isolated FastAPI router for guarded voice contact and signed callbacks."""

from __future__ import annotations

import hmac
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated

import httpx
from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from services.api.app.db.session import get_async_session
from services.api.app.integrations.voice.elevenlabs import (
    ElevenLabsAgentConfig,
    ElevenLabsCallRegistrar,
    ElevenLabsRecoveryContext,
    parse_elevenlabs_post_call,
)
from services.api.app.integrations.voice.safety import VoiceIntent, detect_voice_intent
from services.api.app.integrations.voice.signatures import (
    verify_elevenlabs_signature,
    verify_twilio_signature,
)

from .factory import create_voice_service_from_env, voice_provider_ready
from .schemas import (
    BrowserTranscriptRequest,
    BrowserTranscriptResponse,
    LiveVoiceIntentRequest,
    LiveVoiceIntentResponse,
    StartVoiceContactRequest,
    StartVoiceContactResponse,
    VoiceAttemptResponse,
    VoiceContactSetupRequest,
    VoiceEligibilityResponse,
    VoiceTimelineResponse,
    WebhookAcceptedResponse,
)
from .service import VoiceContactService

router = APIRouter(prefix="/v1/voice", tags=["voice"])


async def get_voice_service(
    session: Annotated[AsyncSession, Depends(get_async_session)],
) -> AsyncIterator[VoiceContactService]:
    """Create a transactional SQL service while keeping real calls opt-in."""

    resources = create_voice_service_from_env(session)
    try:
        yield resources.service
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await resources.aclose()


async def get_call_registrar() -> AsyncIterator[ElevenLabsCallRegistrar]:
    if not voice_provider_ready():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "ELEVENLABS_NOT_CONFIGURED",
                "message": "Call registration unavailable",
            },
        )
    client = httpx.AsyncClient(timeout=10.0)
    try:
        yield ElevenLabsCallRegistrar(
            ElevenLabsAgentConfig(
                agent_id=os.environ["ELEVENLABS_AGENT_ID"],
                api_key=os.environ["ELEVENLABS_API_KEY"],
            ),
            client,
        )
    finally:
        await client.aclose()


VoiceServiceDependency = Annotated[VoiceContactService, Depends(get_voice_service)]
RegistrarDependency = Annotated[ElevenLabsCallRegistrar, Depends(get_call_registrar)]


def _real_voice_requested() -> bool:
    return os.getenv("VOICE_REAL_CALLS_ENABLED", "false").strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _authorize_voice_start(
    *,
    service: VoiceContactService,
    supplied_voice_operator_token: str | None,
    supplied_recoveryos_operator_token: str | None,
    supplied_csrf_token: str | None,
    operator_session: str | None,
) -> bool:
    """Authorize a real call without exposing the server-side voice token.

    Existing server integrations may continue using the dedicated voice token.
    Browser clients instead present the API-owned HttpOnly session cookie and
    matching CSRF header. Real voice mode must never inherit the payment guard's
    safe mock-mode no-op behavior.
    """

    # Import lazily because the shared model registry imports the voice package
    # while the core API package is still initializing.
    from services.api.app.api.operator_auth import (
        OperatorAuthorizationNotConfiguredError,
        _authorization_required,
        require_operator_for_non_mock_payment,
    )

    voice_token = service.operator_token
    if (
        service.real_calls_enabled
        and voice_token
        and supplied_voice_operator_token is not None
        and hmac.compare_digest(supplied_voice_operator_token, voice_token)
    ):
        return False
    if _authorization_required():
        require_operator_for_non_mock_payment(
            x_recoveryos_operator_token=supplied_recoveryos_operator_token,
            x_recoveryos_csrf_token=supplied_csrf_token,
            operator_session=operator_session,
        )
        return service.real_calls_enabled
    if service.real_calls_enabled:
        raise OperatorAuthorizationNotConfiguredError(
            "Real voice calls require OPERATOR_AUTH_REQUIRED=true or another active "
            "RecoveryOS operator-auth gate."
        )
    return False


def _require_voice_operator(
    *,
    service: VoiceContactService,
    supplied_voice_operator_token: str | None,
    supplied_recoveryos_operator_token: str | None,
    supplied_csrf_token: str | None,
    operator_session: str | None,
) -> None:
    """Authenticate configuration and sensitive reads even in degraded mode."""

    from services.api.app.api.operator_auth import (
        OperatorAuthorizationNotConfiguredError,
        _authorization_required,
        require_operator_for_non_mock_payment,
    )

    if (
        service.operator_token
        and supplied_voice_operator_token is not None
        and hmac.compare_digest(supplied_voice_operator_token, service.operator_token)
    ):
        return
    if _authorization_required():
        require_operator_for_non_mock_payment(
            x_recoveryos_operator_token=supplied_recoveryos_operator_token,
            x_recoveryos_csrf_token=supplied_csrf_token,
            operator_session=operator_session,
        )
        return
    raise OperatorAuthorizationNotConfiguredError(
        "Voice operator endpoints require VOICE_OPERATOR_TOKEN or the RecoveryOS "
        "operator-auth gate."
    )


def _protect_real_voice_data(
    *,
    service: VoiceContactService,
    supplied_voice_operator_token: str | None,
    supplied_recoveryos_operator_token: str | None,
    supplied_csrf_token: str | None,
    operator_session: str | None,
) -> None:
    if service.real_calls_enabled or _real_voice_requested():
        _require_voice_operator(
            service=service,
            supplied_voice_operator_token=supplied_voice_operator_token,
            supplied_recoveryos_operator_token=supplied_recoveryos_operator_token,
            supplied_csrf_token=supplied_csrf_token,
            operator_session=operator_session,
        )


@router.post("/contacts", response_model=StartVoiceContactResponse)
async def start_voice_contact(
    payload: StartVoiceContactRequest,
    service: VoiceServiceDependency,
    x_recovery_operator_token: Annotated[
        str | None, Header(alias="X-Recovery-Operator-Token")
    ] = None,
    x_recoveryos_operator_token: Annotated[
        str | None, Header(alias="X-RecoveryOS-Operator-Token")
    ] = None,
    x_recoveryos_csrf_token: Annotated[str | None, Header(alias="X-RecoveryOS-CSRF-Token")] = None,
    operator_session: Annotated[str | None, Cookie(alias="recoveryos_operator_session")] = None,
) -> StartVoiceContactResponse:
    operator_session_authorized = _authorize_voice_start(
        service=service,
        supplied_voice_operator_token=x_recovery_operator_token,
        supplied_recoveryos_operator_token=x_recoveryos_operator_token,
        supplied_csrf_token=x_recoveryos_csrf_token,
        operator_session=operator_session,
    )
    result = await service.start(
        case_id=payload.case_id,
        idempotency_key=payload.idempotency_key,
        supplied_operator_token=x_recovery_operator_token,
        operator_session_authorized=operator_session_authorized,
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


def _eligibility_response(value: object) -> VoiceEligibilityResponse:
    from .service import VoiceEligibility

    if not isinstance(value, VoiceEligibility):  # pragma: no cover - internal invariant
        raise TypeError("voice eligibility service returned an invalid result")
    return VoiceEligibilityResponse(
        case_id=value.case_id,
        customer_id=value.customer_id,
        eligible=value.eligible,
        reason_code=value.reason_code,
        destination_configured=value.destination_configured,
        destination_allowlisted=value.destination_allowlisted,
        consent_verified_at=value.consent_verified_at,
        opted_out_at=value.opted_out_at,
        preferred_language=value.preferred_language,
    )


@router.put("/cases/{case_id}/contact-setup", response_model=VoiceEligibilityResponse)
async def configure_voice_contact(
    case_id: str,
    payload: VoiceContactSetupRequest,
    service: VoiceServiceDependency,
    x_recovery_operator_token: Annotated[
        str | None, Header(alias="X-Recovery-Operator-Token")
    ] = None,
    x_recoveryos_operator_token: Annotated[
        str | None, Header(alias="X-RecoveryOS-Operator-Token")
    ] = None,
    x_recoveryos_csrf_token: Annotated[str | None, Header(alias="X-RecoveryOS-CSRF-Token")] = None,
    operator_session: Annotated[str | None, Cookie(alias="recoveryos_operator_session")] = None,
) -> VoiceEligibilityResponse:
    _require_voice_operator(
        service=service,
        supplied_voice_operator_token=x_recovery_operator_token,
        supplied_recoveryos_operator_token=x_recoveryos_operator_token,
        supplied_csrf_token=x_recoveryos_csrf_token,
        operator_session=operator_session,
    )
    now = datetime.now(UTC)
    subject = await service.configure_subject(
        case_id=case_id,
        destination_token=payload.destination_token,
        preferred_language=payload.preferred_language,
        consent_granted=payload.consent_granted,
        now=now,
    )
    if subject is None:
        raise HTTPException(status_code=404, detail={"code": "VOICE_SUBJECT_NOT_FOUND"})
    return _eligibility_response(await service.eligibility(case_id=case_id, now=now))


@router.get("/cases/{case_id}/eligibility", response_model=VoiceEligibilityResponse)
async def voice_eligibility(
    case_id: str,
    service: VoiceServiceDependency,
    x_recovery_operator_token: Annotated[
        str | None, Header(alias="X-Recovery-Operator-Token")
    ] = None,
    x_recoveryos_operator_token: Annotated[
        str | None, Header(alias="X-RecoveryOS-Operator-Token")
    ] = None,
    x_recoveryos_csrf_token: Annotated[str | None, Header(alias="X-RecoveryOS-CSRF-Token")] = None,
    operator_session: Annotated[str | None, Cookie(alias="recoveryos_operator_session")] = None,
) -> VoiceEligibilityResponse:
    _require_voice_operator(
        service=service,
        supplied_voice_operator_token=x_recovery_operator_token,
        supplied_recoveryos_operator_token=x_recoveryos_operator_token,
        supplied_csrf_token=x_recoveryos_csrf_token,
        operator_session=operator_session,
    )
    return _eligibility_response(await service.eligibility(case_id=case_id, now=datetime.now(UTC)))


@router.get("/cases/{case_id}/timeline", response_model=VoiceTimelineResponse)
async def voice_timeline(
    case_id: str,
    service: VoiceServiceDependency,
    x_recovery_operator_token: Annotated[
        str | None, Header(alias="X-Recovery-Operator-Token")
    ] = None,
    x_recoveryos_operator_token: Annotated[
        str | None, Header(alias="X-RecoveryOS-Operator-Token")
    ] = None,
    x_recoveryos_csrf_token: Annotated[str | None, Header(alias="X-RecoveryOS-CSRF-Token")] = None,
    operator_session: Annotated[str | None, Cookie(alias="recoveryos_operator_session")] = None,
) -> VoiceTimelineResponse:
    _protect_real_voice_data(
        service=service,
        supplied_voice_operator_token=x_recovery_operator_token,
        supplied_recoveryos_operator_token=x_recoveryos_operator_token,
        supplied_csrf_token=x_recoveryos_csrf_token,
        operator_session=operator_session,
    )
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
    x_recovery_operator_token: Annotated[
        str | None, Header(alias="X-Recovery-Operator-Token")
    ] = None,
    x_recoveryos_operator_token: Annotated[
        str | None, Header(alias="X-RecoveryOS-Operator-Token")
    ] = None,
    x_recoveryos_csrf_token: Annotated[str | None, Header(alias="X-RecoveryOS-CSRF-Token")] = None,
    operator_session: Annotated[str | None, Cookie(alias="recoveryos_operator_session")] = None,
) -> BrowserTranscriptResponse:
    _protect_real_voice_data(
        service=service,
        supplied_voice_operator_token=x_recovery_operator_token,
        supplied_recoveryos_operator_token=x_recoveryos_operator_token,
        supplied_csrf_token=x_recoveryos_csrf_token,
        operator_session=operator_session,
    )
    if await service.repository.get_attempt(attempt_id) is None:
        if attempt_id.startswith("browser-rehearsal-"):
            intent = detect_voice_intent(payload.transcript)
            return BrowserTranscriptResponse(
                detected_intent=intent.value,
                disposition=intent.value,
                contact_must_end=intent
                in {
                    VoiceIntent.OPT_OUT,
                    VoiceIntent.DISPUTE,
                    VoiceIntent.WRONG_PERSON,
                    VoiceIntent.ALREADY_PAID,
                },
                suppression_persisted=False,
            )
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
    if attempt.provider_call_id and not hmac.compare_digest(attempt.provider_call_id, call_sid):
        raise HTTPException(status_code=403, detail={"code": "TWILIO_CALL_SCOPE_MISMATCH"})
    from_number = form.get("From")
    to_number = form.get("To")
    if not from_number or not to_number:
        raise HTTPException(
            status_code=422,
            detail={"code": "TWILIO_CALL_PARTICIPANTS_REQUIRED"},
        )
    subject = await service.repository.load_subject(attempt.case_id)
    if subject is None:
        raise HTTPException(status_code=409, detail={"code": "VOICE_CONTEXT_NOT_FOUND"})
    twiml = await registrar.register(
        twilio_call_sid=call_sid,
        attempt_id=attempt_id,
        from_number=from_number,
        to_number=to_number,
        direction="outbound",
        context=ElevenLabsRecoveryContext(
            merchant_id=subject.merchant_id,
            merchant_display_name=subject.merchant_display_name,
            case_id=subject.case_id,
            customer_id=subject.customer_id,
            customer_display_name=subject.customer_display_name,
            preferred_language=subject.preferred_language,
            amount_at_risk_paise=subject.amount_at_risk_paise,
            currency=subject.currency,
            diagnosis=subject.diagnosis,
            plan_name=subject.plan_name,
        ),
    )
    # ElevenLabs owns the complete TwiML document. Do not rebuild or escape it.
    return Response(twiml, media_type="application/xml")


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
    attempt = await service.repository.get_attempt(attempt_id)
    if attempt is None:
        raise HTTPException(status_code=404, detail={"code": "VOICE_ATTEMPT_NOT_FOUND"})
    call_sid = form.get("CallSid")
    if not call_sid:
        raise HTTPException(status_code=422, detail={"code": "TWILIO_CALL_SID_REQUIRED"})
    if attempt.provider_call_id and not hmac.compare_digest(attempt.provider_call_id, call_sid):
        raise HTTPException(status_code=403, detail={"code": "TWILIO_CALL_SCOPE_MISMATCH"})
    callback_status = form.get("CallStatus", "unknown")
    event_id = f"{call_sid}:{form.get('SequenceNumber') or callback_status}"
    try:
        duration_seconds = int(form["CallDuration"]) if form.get("CallDuration") else None
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "TWILIO_CALL_DURATION_INVALID"},
        ) from exc
    try:
        duplicate = await service.apply_twilio_status(
            event_id=event_id,
            attempt_id=attempt_id,
            status=callback_status,
            duration_seconds=duration_seconds,
            provider_call_id=call_sid,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "TWILIO_CALL_STATUS_INVALID", "message": str(exc)},
        ) from exc
    return WebhookAcceptedResponse(duplicate=duplicate)


@router.post("/webhooks/elevenlabs/post-call", response_model=WebhookAcceptedResponse)
async def elevenlabs_post_call_webhook(
    request: Request,
    service: VoiceServiceDependency,
    elevenlabs_signature: Annotated[str | None, Header(alias="ElevenLabs-Signature")] = None,
) -> WebhookAcceptedResponse:
    raw = await request.body()
    if not verify_elevenlabs_signature(
        secret=os.getenv("ELEVENLABS_WEBHOOK_SECRET", ""),
        body=raw,
        supplied=elevenlabs_signature,
    ):
        raise HTTPException(status_code=401, detail={"code": "INVALID_ELEVENLABS_SIGNATURE"})
    try:
        event = parse_elevenlabs_post_call(
            raw,
            expected_agent_id=os.getenv("ELEVENLABS_AGENT_ID", "").strip() or None,
        )
        if await service.repository.get_attempt(event.attempt_id) is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "VOICE_ATTEMPT_NOT_FOUND"},
            )
        occurred_at = datetime.fromtimestamp(event.event_timestamp, UTC)
        duplicate = await service.apply_elevenlabs_post_call(
            event_id=f"{event.event_type}:{event.conversation_id}",
            attempt_id=event.attempt_id,
            transcript=event.transcript,
            intent_transcript=event.user_transcript,
            provider_intent=event.provider_intent,
            confidence_basis_points=event.confidence_basis_points,
            duration_seconds=event.duration_seconds,
            disclosure_delivered=event.disclosure_delivered,
            occurred_at=occurred_at,
        )
    except HTTPException:
        raise
    except (ValueError, OSError, OverflowError) as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_ELEVENLABS_POST_CALL",
                "message": str(exc),
            },
        ) from exc
    return WebhookAcceptedResponse(duplicate=duplicate)


@router.post("/tools/elevenlabs/intent", response_model=LiveVoiceIntentResponse)
async def elevenlabs_live_intent_tool(
    payload: LiveVoiceIntentRequest,
    service: VoiceServiceDependency,
    x_elevenlabs_tool_secret: Annotated[
        str | None, Header(alias="X-ElevenLabs-Tool-Secret")
    ] = None,
) -> LiveVoiceIntentResponse:
    """Receive authenticated live intent tools; opt-out persists before hang-up."""

    expected_secret = os.getenv("ELEVENLABS_WEBHOOK_SECRET", "").strip()
    if (
        not voice_provider_ready()
        or not expected_secret
        or x_elevenlabs_tool_secret is None
        or not hmac.compare_digest(x_elevenlabs_tool_secret, expected_secret)
    ):
        raise HTTPException(status_code=401, detail={"code": "INVALID_ELEVENLABS_TOOL_AUTH"})
    attempt = await service.repository.get_attempt(payload.attempt_id)
    if attempt is None:
        raise HTTPException(status_code=404, detail={"code": "VOICE_ATTEMPT_NOT_FOUND"})
    try:
        intent, must_end, suppression_persisted, duplicate = await service.apply_live_intent(
            event_id=payload.event_id
            or f"live:{payload.attempt_id}:{payload.intent.strip().upper()}",
            attempt_id=payload.attempt_id,
            intent=payload.intent.strip().upper(),
            confidence_basis_points=payload.confidence_basis_points,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_ELEVENLABS_INTENT", "message": str(exc)},
        ) from exc
    return LiveVoiceIntentResponse(
        duplicate=duplicate,
        detected_intent=intent.value,
        contact_must_end=must_end,
        suppression_persisted=suppression_persisted,
    )


@router.get("/intents", response_model=list[str])
async def supported_voice_intents() -> list[str]:
    return [item.value for item in VoiceIntent]
