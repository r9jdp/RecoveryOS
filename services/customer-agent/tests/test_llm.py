from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from app.config import CustomerAgentSettings
from app.llm import (
    LanguageInterpreterProviderError,
    OpenAIResponsesLanguageInterpreter,
)
from app.main import create_app
from app.models import ApprovalSummary, CustomerLanguageRequest
from pydantic import ValidationError

_A2A_HEADERS = {
    "A2A-Version": "1.0",
    "A2A-Extensions": (
        "https://recoveryos.dev/a2a/recovery-mandate/v1,"
        "https://recoveryos.dev/a2a/recovery-receipt/v1"
    ),
}


def _summary() -> ApprovalSummary:
    return ApprovalSummary(
        task_id="task-1",
        state="TASK_STATE_AUTH_REQUIRED",
        merchant_id="merchant-1",
        case_id="case-1",
        exact_amount_paise=149_900,
        currency="INR",
        payment_surface_type="SUBSCRIPTION_INVOICE_LINK",
        payment_surface_reference="inv_123",
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
        merchant_display_name="FitBox",
        plan_name="FitBox Annual",
        failure_explanation=("The payment needs customer authentication before it can continue."),
    )


def _recovery_request() -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": "rpc-create",
        "method": "SendMessage",
        "params": {
            "message": {
                "messageId": "message-create",
                "role": "ROLE_USER",
                "contextId": "recovery:case-1",
                "parts": [
                    {
                        "data": {
                            "protocol_version": "recovery.request.v1",
                            "idempotency_key": "case-1:llm-test",
                            "case_id": "case-1",
                            "merchant_id": "merchant-1",
                            "customer_id": "customer-1",
                            "exact_amount_paise": 149_900,
                            "currency": "INR",
                            "payment_surface_type": "SUBSCRIPTION_INVOICE_LINK",
                            "payment_surface_reference": "inv_123",
                            "expires_at": (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
                            "context": {
                                "merchant_display_name": "FitBox",
                                "plan_name": "FitBox Annual",
                                "failure_explanation": (
                                    "The payment needs customer authentication before it can "
                                    "continue."
                                ),
                            },
                        }
                    }
                ],
            }
        },
    }


def _completed_response(*, intent: str = "APPROVE") -> dict[str, Any]:
    output = json.dumps(
        {
            "intent": intent,
            "confidence_basis_points": 9_300,
            "explanation": "You appear to want to approve the exact request shown.",
        }
    )
    return {
        "id": "resp_test",
        "status": "completed",
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": output}],
            }
        ],
    }


@pytest.mark.asyncio
async def test_openai_request_is_stateless_strict_and_omits_exact_scope() -> None:
    captured: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["Authorization"]
        captured["timeout"] = request.extensions["timeout"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_completed_response())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        interpreter = OpenAIResponsesLanguageInterpreter(
            api_key="server-secret",
            model="test-structured-model",
            timeout_seconds=4,
            http_client=http_client,
        )
        result = await interpreter.interpret(
            request=CustomerLanguageRequest(text="Yes, I want to continue."),
            summary=_summary(),
        )

    assert result.intent == "APPROVE"
    assert result.confidence_basis_points == 9_300
    assert captured["url"] == "https://api.openai.com/v1/responses"
    assert captured["authorization"] == "Bearer server-secret"
    assert captured["timeout"] == {
        "connect": 4,
        "read": 4,
        "write": 4,
        "pool": 4,
    }
    body = captured["body"]
    assert body["model"] == "test-structured-model"
    assert body["store"] is False
    assert body["text"]["format"]["type"] == "json_schema"
    assert body["text"]["format"]["strict"] is True
    assert body["text"]["format"]["schema"]["additionalProperties"] is False
    serialized_input = body["input"][0]["content"][0]["text"]
    safe_input = json.loads(serialized_input)
    assert safe_input["case_context"] == {
        "merchant_display_name": "FitBox",
        "plan_name": "FitBox Annual",
        "failure_explanation": (
            "The payment needs customer authentication before it can continue."
        ),
    }
    assert "149900" not in serialized_input
    assert "inv_123" not in serialized_input
    assert "payment_surface" not in serialized_input
    assert "merchant-1" not in serialized_input
    assert "case-1" not in serialized_input


@pytest.mark.asyncio
async def test_approve_interpretation_cannot_sign_or_change_authoritative_scope() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_completed_response(intent="APPROVE"))

    settings = CustomerAgentSettings(
        llm_provider="openai",
        openai_api_key="server-secret",
        openai_model="test-structured-model",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as provider_client:
        interpreter = OpenAIResponsesLanguageInterpreter(
            api_key="server-secret",
            model="test-structured-model",
            timeout_seconds=4,
            http_client=provider_client,
        )
        app = create_app(settings, language_interpreter=interpreter)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="https://customer-agent.example",
            headers=_A2A_HEADERS,
        ) as client:
            task = (await client.post("/rpc", json=_recovery_request())).json()["result"]["task"]
            response = await client.post(
                f"/v1/tasks/{task['id']}/interpretation",
                json={"text": "Yes, please go ahead.", "channel": "VOICE_TRANSCRIPT"},
            )
            unchanged = await client.post(
                "/rpc",
                json={
                    "jsonrpc": "2.0",
                    "id": "rpc-get-after-interpretation",
                    "method": "GetTask",
                    "params": {"id": task["id"]},
                },
            )

    assert response.status_code == 200
    result = response.json()
    assert result["intent"] == "APPROVE"
    assert result["authorization_effect"] == "NONE"
    assert result["requires_explicit_approval"] is True
    assert result["authoritative_scope"]["exact_amount_paise"] == 149_900
    assert result["authoritative_scope"]["payment_surface_reference"] == "inv_123"
    task_after = unchanged.json()["result"]
    assert task_after["status"]["state"] == "TASK_STATE_AUTH_REQUIRED"
    assert task_after["artifacts"] == []


@pytest.mark.asyncio
async def test_configured_provider_failure_has_no_keyword_fallback() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": {"message": "unavailable"}})

    settings = CustomerAgentSettings(
        llm_provider="openai",
        openai_api_key="server-secret",
        openai_model="test-structured-model",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as provider_client:
        interpreter = OpenAIResponsesLanguageInterpreter(
            api_key="server-secret",
            model="test-structured-model",
            timeout_seconds=4,
            http_client=provider_client,
        )
        app = create_app(settings, language_interpreter=interpreter)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="https://customer-agent.example",
            headers=_A2A_HEADERS,
        ) as client:
            task = (await client.post("/rpc", json=_recovery_request())).json()["result"]["task"]
            failed = await client.post(
                f"/v1/tasks/{task['id']}/interpretation",
                json={"text": "yes"},
            )
            summary = await client.get(f"/v1/tasks/{task['id']}/approval")

    assert failed.status_code == 502
    assert failed.json()["detail"] == "language model provider returned HTTP 503"
    assert summary.json()["state"] == "TASK_STATE_AUTH_REQUIRED"


@pytest.mark.asyncio
async def test_invalid_structured_output_is_rejected() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output_text": json.dumps(
                    {
                        "intent": "APPROVE",
                        "confidence_basis_points": 12_000,
                        "explanation": "yes",
                    }
                ),
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        interpreter = OpenAIResponsesLanguageInterpreter(
            api_key="server-secret",
            model="test-structured-model",
            timeout_seconds=4,
            http_client=http_client,
        )
        with pytest.raises(
            LanguageInterpreterProviderError,
            match="invalid structured response",
        ):
            await interpreter.interpret(
                request=CustomerLanguageRequest(text="yes"),
                summary=_summary(),
            )


def test_openai_provider_requires_server_side_key_and_model() -> None:
    with pytest.raises(ValidationError, match="OPENAI_API_KEY"):
        CustomerAgentSettings(
            llm_provider="openai",
            openai_api_key=None,
            openai_model="test-structured-model",
        )
    with pytest.raises(ValidationError, match="OPENAI_MODEL"):
        CustomerAgentSettings(
            llm_provider="openai",
            openai_api_key="server-secret",
            openai_model=None,
        )


def test_settings_use_unprefixed_server_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "environment-secret")
    monkeypatch.setenv("OPENAI_MODEL", "environment-model")
    settings = CustomerAgentSettings()
    assert settings.llm_provider == "openai"
    assert settings.openai_api_key is not None
    assert settings.openai_api_key.get_secret_value() == "environment-secret"
    assert settings.openai_model == "environment-model"
