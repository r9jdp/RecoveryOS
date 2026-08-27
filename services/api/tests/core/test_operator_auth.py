from __future__ import annotations

import httpx
import pytest
from fastapi import Depends, FastAPI

from services.api.app.api.operator_auth import require_operator_for_non_mock_payment
from services.api.app.api.router import application_error_handler
from services.api.app.services.cases import ApplicationServiceError


def authorization_test_app() -> FastAPI:
    app = FastAPI()
    app.add_exception_handler(ApplicationServiceError, application_error_handler)

    @app.post("/consequential", dependencies=[Depends(require_operator_for_non_mock_payment)])
    async def consequential_action() -> dict[str, bool]:
        return {"accepted": True}

    return app


async def test_mock_provider_keeps_public_demo_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PAYMENT_PROVIDER", "mock")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=authorization_test_app()),
        base_url="http://test",
    ) as client:
        response = await client.post("/consequential")

    assert response.status_code == 200


async def test_non_mock_provider_fails_closed_without_configured_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PAYMENT_PROVIDER", "razorpay")
    monkeypatch.delenv("OPERATOR_DEMO_TOKEN", raising=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=authorization_test_app()),
        base_url="http://test",
    ) as client:
        response = await client.post("/consequential")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "OPERATOR_AUTH_NOT_CONFIGURED"


async def test_non_mock_provider_rejects_anonymous_and_accepts_operator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PAYMENT_PROVIDER", "razorpay")
    monkeypatch.setenv("OPERATOR_DEMO_TOKEN", "test-operator-secret")
    app = authorization_test_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        anonymous = await client.post("/consequential")
        wrong = await client.post(
            "/consequential",
            headers={"X-RecoveryOS-Operator-Token": "wrong"},
        )
        authorized = await client.post(
            "/consequential",
            headers={"X-RecoveryOS-Operator-Token": "test-operator-secret"},
        )

    assert anonymous.status_code == 401
    assert wrong.status_code == 401
    assert authorized.status_code == 200
