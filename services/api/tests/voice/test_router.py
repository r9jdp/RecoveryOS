import json
from datetime import UTC, datetime

import httpx
import pytest
from fastapi import FastAPI

from services.api.app.api.operator_auth import operator_router
from services.api.app.api.router import application_error_handler
from services.api.app.http_security import install_credentialed_cors
from services.api.app.integrations.voice.elevenlabs import ElevenLabsRecoveryContext
from services.api.app.integrations.voice.signatures import (
    elevenlabs_signature,
    twilio_signature,
)
from services.api.app.providers.contracts import (
    VoiceContactRequest,
    VoiceContactResult,
    VoiceContactSnapshot,
)
from services.api.app.services.cases import ApplicationServiceError
from services.api.app.voice.router import get_call_registrar, get_voice_service, router
from services.api.app.voice.service import (
    DisabledVoiceProvider,
    InMemoryVoiceRepository,
    VoiceAttempt,
    VoiceContactService,
    VoiceSubject,
)


class StubCallRegistrar:
    def __init__(self, twiml: str) -> None:
        self.twiml = twiml
        self.calls: list[dict[str, object]] = []

    async def register(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        return self.twiml


class SubmittedVoiceProvider:
    def __init__(self) -> None:
        self.requests: list[VoiceContactRequest] = []

    async def start_contact(self, request: VoiceContactRequest) -> VoiceContactResult:
        self.requests.append(request)
        return VoiceContactResult(
            provider="twilio",
            contact_attempt_id=request.idempotency_key,
            provider_call_id="CA_HOSTED_1",
            status="SUBMITTED",
        )

    async def cancel_contact(self, *, contact_attempt_id: str, reason: str) -> None:
        del contact_attempt_id, reason

    async def fetch_contact(self, *, contact_attempt_id: str) -> VoiceContactSnapshot:
        raise AssertionError(contact_attempt_id)


def _real_voice_service() -> tuple[VoiceContactService, SubmittedVoiceProvider]:
    provider = SubmittedVoiceProvider()
    repository = InMemoryVoiceRepository(
        [
            VoiceSubject(
                merchant_id="merchant-1",
                case_id="case-1",
                customer_id="customer-1",
                destination_token="+919999999999",
                preferred_language="hi-IN",
                consent_verified_at=datetime(2026, 8, 1, tzinfo=UTC),
                opted_out_at=None,
                quiet_hours_start=None,
                quiet_hours_end=None,
            )
        ]
    )
    return (
        VoiceContactService(
            repository=repository,
            provider=provider,
            real_calls_enabled=True,
            operator_token="server-only-voice-token",
            allowlisted_destinations=frozenset({"+919999999999"}),
        ),
        provider,
    )


def _voice_app(service: VoiceContactService) -> FastAPI:
    app = FastAPI()
    install_credentialed_cors(app, "https://web.recovery.test")
    app.include_router(operator_router)
    app.include_router(router)
    app.add_exception_handler(ApplicationServiceError, application_error_handler)
    app.dependency_overrides[get_voice_service] = lambda: service
    return app


def _configure_hosted_operator(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("OPERATOR_AUTH_REQUIRED", "true")
    monkeypatch.setenv("OPERATOR_COOKIE_SECURE", "true")
    monkeypatch.setenv("OPERATOR_COOKIE_SAMESITE", "none")
    monkeypatch.setenv("OPERATOR_DEMO_EMAIL", "operator@recovery.test")
    monkeypatch.setenv("OPERATOR_DEMO_TOKEN", "hosted-operator-password")
    monkeypatch.setenv("OPERATOR_SESSION_SECRET", "hosted-session-signing-secret")
    monkeypatch.setenv("PAYMENT_PROVIDER", "mock")
    monkeypatch.setenv("RECOVERY_ALLOW_REAL_PAYMENT_ACTIONS", "false")


def _start_payload(idempotency_key: str) -> dict[str, object]:
    return {
        "case_id": "case-1",
        "idempotency_key": idempotency_key,
        "max_duration_seconds": 180,
    }


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


@pytest.mark.asyncio
async def test_hosted_cross_origin_session_authorizes_real_voice_without_raw_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_hosted_operator(monkeypatch)
    service, provider = _real_voice_service()
    origin = "https://web.recovery.test"

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_voice_app(service)),
        base_url="https://api.recovery.test",
    ) as client:
        login = await client.post(
            "/v1/operator/session",
            headers={"Origin": origin},
            json={
                "email": "operator@recovery.test",
                "password": "hosted-operator-password",
            },
        )
        csrf_token = login.json()["csrf_token"]
        started = await client.post(
            "/v1/voice/contacts",
            headers={
                "Origin": origin,
                "X-RecoveryOS-CSRF-Token": csrf_token,
            },
            json=_start_payload("voice:hosted-session:1"),
        )

    assert login.status_code == 200
    assert "samesite=none" in login.headers["set-cookie"].lower()
    assert started.status_code == 200
    assert started.headers["access-control-allow-origin"] == origin
    assert started.headers["access-control-allow-credentials"] == "true"
    assert started.json()["status"] == "SUBMITTED"
    assert len(provider.requests) == 1


@pytest.mark.asyncio
async def test_real_voice_rejects_anonymous_and_missing_or_wrong_csrf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_hosted_operator(monkeypatch)
    service, provider = _real_voice_service()
    origin = "https://web.recovery.test"

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_voice_app(service)),
        base_url="https://api.recovery.test",
    ) as client:
        anonymous = await client.post(
            "/v1/voice/contacts",
            headers={"Origin": origin},
            json=_start_payload("voice:anonymous:1"),
        )
        login = await client.post(
            "/v1/operator/session",
            headers={"Origin": origin},
            json={
                "email": "operator@recovery.test",
                "password": "hosted-operator-password",
            },
        )
        missing_csrf = await client.post(
            "/v1/voice/contacts",
            headers={"Origin": origin},
            json=_start_payload("voice:missing-csrf:1"),
        )
        wrong_csrf = await client.post(
            "/v1/voice/contacts",
            headers={
                "Origin": origin,
                "X-RecoveryOS-CSRF-Token": "not-the-session-token",
            },
            json=_start_payload("voice:wrong-csrf:1"),
        )

    assert login.status_code == 200
    for response in (anonymous, missing_csrf, wrong_csrf):
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "OPERATOR_AUTH_REQUIRED"
    assert provider.requests == []


@pytest.mark.asyncio
async def test_server_voice_token_remains_available_without_browser_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPERATOR_AUTH_REQUIRED", "false")
    monkeypatch.setenv("PAYMENT_PROVIDER", "mock")
    monkeypatch.setenv("RECOVERY_ALLOW_REAL_PAYMENT_ACTIONS", "false")
    service, provider = _real_voice_service()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_voice_app(service)),
        base_url="https://api.recovery.test",
    ) as client:
        started = await client.post(
            "/v1/voice/contacts",
            headers={"X-Recovery-Operator-Token": "server-only-voice-token"},
            json=_start_payload("voice:server-token:1"),
        )

    assert started.status_code == 200
    assert started.json()["status"] == "SUBMITTED"
    assert len(provider.requests) == 1


@pytest.mark.asyncio
async def test_real_voice_timeline_is_not_public(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VOICE_REAL_CALLS_ENABLED", "true")
    monkeypatch.setenv("OPERATOR_AUTH_REQUIRED", "false")
    service, _ = _real_voice_service()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_voice_app(service)),
        base_url="https://api.recovery.test",
    ) as client:
        anonymous = await client.get("/v1/voice/cases/case-1/timeline")
        authorized = await client.get(
            "/v1/voice/cases/case-1/timeline",
            headers={"X-Recovery-Operator-Token": "server-only-voice-token"},
        )

    assert anonymous.status_code == 503
    assert authorized.status_code == 200


@pytest.mark.asyncio
async def test_operator_can_configure_destination_and_consent_then_check_eligibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPERATOR_AUTH_REQUIRED", "false")
    service, _ = _real_voice_service()
    repository = service.repository
    assert isinstance(repository, InMemoryVoiceRepository)
    repository.subjects["case-1"] = VoiceSubject(
        merchant_id="merchant-1",
        case_id="case-1",
        customer_id="customer-1",
        destination_token="",
        preferred_language="en-IN",
        consent_verified_at=None,
        opted_out_at=None,
        quiet_hours_start=None,
        quiet_hours_end=None,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_voice_app(service)),
        base_url="https://api.recovery.test",
    ) as client:
        anonymous = await client.put(
            "/v1/voice/cases/case-1/contact-setup",
            json={
                "destination_token": "+919999999999",
                "preferred_language": "hi-IN",
                "consent_granted": True,
            },
        )
        configured = await client.put(
            "/v1/voice/cases/case-1/contact-setup",
            headers={"X-Recovery-Operator-Token": "server-only-voice-token"},
            json={
                "destination_token": "+919999999999",
                "preferred_language": "hi-IN",
                "consent_granted": True,
            },
        )
        eligibility = await client.get(
            "/v1/voice/cases/case-1/eligibility",
            headers={"X-Recovery-Operator-Token": "server-only-voice-token"},
        )

    assert anonymous.status_code == 503
    assert configured.status_code == 200
    assert configured.json()["eligible"] is True
    assert configured.json()["preferred_language"] == "hi-IN"
    assert eligibility.json()["destination_allowlisted"] is True
    assert "destination_token" not in eligibility.json()


@pytest.mark.asyncio
async def test_authenticated_elevenlabs_live_opt_out_tool_persists_suppression(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, provider = _real_voice_service()
    await service.repository.save_attempt(
        VoiceAttempt(
            id="attempt-live-tool",
            merchant_id="merchant-1",
            case_id="case-1",
            customer_id="customer-1",
            idempotency_key="attempt-live-tool",
            provider="twilio",
            provider_call_id="CA-LIVE-TOOL",
            status="IN_PROGRESS",
            created_at=datetime(2026, 8, 28, 14, tzinfo=UTC),
        )
    )
    for name, value in {
        "VOICE_PROVIDER": "twilio",
        "VOICE_REAL_CALLS_ENABLED": "true",
        "TWILIO_ACCOUNT_SID": "AC123",
        "TWILIO_AUTH_TOKEN": "twilio-secret",
        "TWILIO_FROM_NUMBER": "+12025550100",
        "VOICE_PUBLIC_ORIGIN": "https://voice.recovery.test",
        "ELEVENLABS_API_KEY": "eleven-api-key",
        "ELEVENLABS_AGENT_ID": "agent-recovery",
        "ELEVENLABS_WEBHOOK_SECRET": "live-tool-secret",
        "VOICE_OPERATOR_TOKEN": "server-only-voice-token",
        "VOICE_ALLOWLIST_DESTINATIONS": "+919999999999",
    }.items():
        monkeypatch.setenv(name, value)
    app = _voice_app(service)
    payload = {
        "attempt_id": "attempt-live-tool",
        "event_id": "tool-event-live-1",
        "intent": "OPT_OUT",
        "confidence_basis_points": 9900,
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://api.recovery.test"
    ) as client:
        rejected = await client.post("/v1/voice/tools/elevenlabs/intent", json=payload)
        accepted = await client.post(
            "/v1/voice/tools/elevenlabs/intent",
            headers={"X-ElevenLabs-Tool-Secret": "live-tool-secret"},
            json=payload,
        )

    assert rejected.status_code == 401
    assert accepted.status_code == 200
    assert accepted.json()["contact_must_end"] is True
    assert accepted.json()["suppression_persisted"] is True
    repository = service.repository
    assert isinstance(repository, InMemoryVoiceRepository)
    assert repository.subjects["case-1"].opted_out_at is not None
    # In-memory SubmittedVoiceProvider implements cancellation as a no-op; the
    # authoritative assertion is persisted suppression plus the tool stop flag.
    assert len(provider.requests) == 0


@pytest.mark.asyncio
async def test_real_voice_does_not_inherit_mock_payment_auth_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPERATOR_AUTH_REQUIRED", "false")
    monkeypatch.setenv("PAYMENT_PROVIDER", "mock")
    monkeypatch.setenv("RECOVERY_ALLOW_REAL_PAYMENT_ACTIONS", "false")
    service, provider = _real_voice_service()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_voice_app(service)),
        base_url="https://api.recovery.test",
    ) as client:
        rejected = await client.post(
            "/v1/voice/contacts",
            json=_start_payload("voice:unsafe-auth-noop:1"),
        )

    assert rejected.status_code == 503
    assert rejected.json()["error"]["code"] == "OPERATOR_AUTH_NOT_CONFIGURED"
    assert provider.requests == []


@pytest.mark.asyncio
async def test_twiml_callback_forwards_full_elevenlabs_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _ = _real_voice_service()
    await service.repository.save_attempt(
        VoiceAttempt(
            id="attempt-twiml",
            merchant_id="merchant-1",
            case_id="case-1",
            customer_id="customer-1",
            idempotency_key="attempt-twiml",
            provider="twilio",
            provider_call_id="CA-TWIML-1",
            status="SUBMITTED",
            created_at=datetime(2026, 8, 28, 14, tzinfo=UTC),
        )
    )
    provider_twiml = (
        '<?xml version="1.0"?><Response><Connect><Stream '
        'url="wss://eleven.example/stream?a=1&amp;b=2" /></Connect></Response>'
    )
    registrar = StubCallRegistrar(provider_twiml)
    app = _voice_app(service)
    app.dependency_overrides[get_call_registrar] = lambda: registrar
    public_origin = "https://voice.recovery.test"
    auth_token = "twilio-auth-secret"
    monkeypatch.setenv("VOICE_PUBLIC_ORIGIN", public_origin)
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", auth_token)
    form = {
        "CallSid": "CA-TWIML-1",
        "From": "+12025550100",
        "To": "+919999999999",
    }
    signature = twilio_signature(
        auth_token=auth_token,
        url=f"{public_origin}/v1/voice/twiml/attempt-twiml",
        parameters=form,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://api.recovery.test"
    ) as client:
        response = await client.post(
            "/v1/voice/twiml/attempt-twiml",
            data=form,
            headers={"X-Twilio-Signature": signature},
        )

    assert response.status_code == 200
    assert response.text == provider_twiml
    assert len(registrar.calls) == 1
    registration = registrar.calls[0]
    assert registration["twilio_call_sid"] == "CA-TWIML-1"
    assert registration["attempt_id"] == "attempt-twiml"
    assert registration["from_number"] == "+12025550100"
    assert registration["to_number"] == "+919999999999"
    assert registration["direction"] == "outbound"
    context = registration["context"]
    assert isinstance(context, ElevenLabsRecoveryContext)
    assert context.merchant_id == "merchant-1"
    assert context.case_id == "case-1"
    assert context.customer_id == "customer-1"


@pytest.mark.asyncio
async def test_current_elevenlabs_post_call_is_signed_idempotent_and_persisted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _ = _real_voice_service()
    await service.repository.save_attempt(
        VoiceAttempt(
            id="attempt-post-call",
            merchant_id="merchant-1",
            case_id="case-1",
            customer_id="customer-1",
            idempotency_key="attempt-post-call",
            provider="twilio",
            provider_call_id="CA-POST-CALL-1",
            status="IN_PROGRESS",
            created_at=datetime(2026, 8, 28, 14, tzinfo=UTC),
        )
    )
    webhook_secret = "elevenlabs-webhook-secret"
    monkeypatch.setenv("ELEVENLABS_WEBHOOK_SECRET", webhook_secret)
    monkeypatch.setenv("ELEVENLABS_AGENT_ID", "agent-recovery")
    event_timestamp = int(datetime.now(UTC).timestamp())
    raw = json.dumps(
        {
            "type": "post_call_transcription",
            "event_timestamp": event_timestamp,
            "data": {
                "agent_id": "agent-recovery",
                "conversation_id": "conversation-1",
                "conversation_initiation_client_data": {
                    "dynamic_variables": {"recoveryos_attempt_id": "attempt-post-call"}
                },
                "transcript": [
                    {"role": "agent", "message": "I am an AI.", "time_in_call_secs": 1},
                    {
                        "role": "user",
                        "message": "I will pay tomorrow.",
                        "time_in_call_secs": 43,
                    },
                ],
                "metadata": {"call_duration_secs": 47},
                "analysis": {
                    "data_collection_results": {
                        "recovery_intent": {"value": "CALLBACK"},
                        "intent_confidence": {"value": 0.93},
                        "ai_disclosure_delivered": {"value": True},
                    }
                },
            },
        },
        separators=(",", ":"),
    ).encode()
    signature = elevenlabs_signature(
        secret=webhook_secret,
        body=raw,
        timestamp=str(event_timestamp),
    )
    app = _voice_app(service)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://api.recovery.test"
    ) as client:
        first = await client.post(
            "/v1/voice/webhooks/elevenlabs/post-call",
            content=raw,
            headers={
                "Content-Type": "application/json",
                "ElevenLabs-Signature": signature,
            },
        )
        replay = await client.post(
            "/v1/voice/webhooks/elevenlabs/post-call",
            content=raw,
            headers={
                "Content-Type": "application/json",
                "ElevenLabs-Signature": signature,
            },
        )

    assert first.status_code == replay.status_code == 200
    assert first.json() == {"accepted": True, "duplicate": False}
    assert replay.json() == {"accepted": True, "duplicate": True}
    attempt = await service.repository.get_attempt("attempt-post-call")
    assert attempt is not None
    assert attempt.status == "COMPLETED"
    assert attempt.transcript == "agent: I am an AI.\nuser: I will pay tomorrow."
    assert attempt.detected_intent == "CALLBACK"
    assert attempt.confidence_basis_points == 9300
    assert attempt.duration_seconds == 47
    assert attempt.disclosure_delivered_at == datetime.fromtimestamp(event_timestamp, UTC)
