from datetime import UTC, datetime

import httpx
import pytest
from fastapi import FastAPI

from services.api.app.api.operator_auth import operator_router
from services.api.app.api.router import application_error_handler
from services.api.app.http_security import install_credentialed_cors
from services.api.app.providers.contracts import (
    VoiceContactRequest,
    VoiceContactResult,
    VoiceContactSnapshot,
)
from services.api.app.services.cases import ApplicationServiceError
from services.api.app.voice.router import get_voice_service, router
from services.api.app.voice.service import (
    DisabledVoiceProvider,
    InMemoryVoiceRepository,
    VoiceContactService,
    VoiceSubject,
)


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
