from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from app.config import CustomerAgentSettings
from app.main import create_app


@pytest.fixture
def app():  # type: ignore[no-untyped-def]
    return create_app(
        CustomerAgentSettings(
            origin="https://customer-agent.example",
            web_origin="https://app.example",
        )
    )


@pytest.fixture
async def client(app):  # type: ignore[no-untyped-def]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://customer-agent.example",
        headers={
            "A2A-Version": "1.0",
            "A2A-Extensions": "https://recoveryos.dev/a2a/recovery-mandate/v1",
        },
    ) as active_client:
        yield active_client


def recovery_request(
    *, request_id: str = "rpc-1", idempotency_key: str = "case-1:a2a"
) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "SendMessage",
        "params": {
            "message": {
                "messageId": f"message-{request_id}",
                "role": "ROLE_USER",
                "contextId": "recovery:case-1",
                "parts": [
                    {
                        "data": {
                            "protocol_version": "recovery.request.v1",
                            "idempotency_key": idempotency_key,
                            "case_id": "case-1",
                            "merchant_id": "merchant-1",
                            "customer_id": "customer-1",
                            "exact_amount_paise": 149900,
                            "currency": "INR",
                            "payment_surface_type": "SUBSCRIPTION_INVOICE_LINK",
                            "payment_surface_reference": "inv_123",
                            "expires_at": (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
                            "context": {
                                "merchant_display_name": "FitBox",
                                "recovery_reason": "August membership renewal failed",
                            },
                        }
                    }
                ],
            }
        },
    }


@pytest.mark.asyncio
async def test_agent_card_declares_a2a_1_and_public_signing_key(client: httpx.AsyncClient) -> None:
    response = await client.get("/.well-known/agent-card.json")
    assert response.status_code == 200
    card = response.json()
    assert card["version"] == "0.1.0"
    assert card["supportedInterfaces"] == [
        {
            "url": "https://customer-agent.example/rpc",
            "protocolBinding": "JSONRPC",
            "protocolVersion": "1.0",
        }
    ]
    assert card["skills"][0]["id"] == "authorize-exact-recovery-surface"
    extension = card["capabilities"]["extensions"][0]
    assert extension["params"]["signingAlgorithm"] == "Ed25519"
    assert len(extension["params"]["publicKeyBase64Url"]) == 43


@pytest.mark.asyncio
async def test_version_and_required_extension_must_be_declared(app) -> None:  # type: ignore[no-untyped-def]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://customer-agent.example",
    ) as client_without_extension:
        missing_version = await client_without_extension.post("/rpc", json=recovery_request())
        missing_extension = await client_without_extension.post(
            "/rpc",
            json=recovery_request(request_id="missing-extension"),
            headers={"A2A-Version": "1.0"},
        )
    assert missing_version.status_code == 200
    assert missing_version.json()["error"]["code"] == -32008
    assert missing_extension.json()["error"]["code"] == -32009


@pytest.mark.asyncio
async def test_send_get_approval_and_receipt_lifecycle(client: httpx.AsyncClient) -> None:
    submitted = await client.post("/rpc", json=recovery_request())
    assert submitted.status_code == 200
    task = submitted.json()["result"]["task"]
    assert task["status"]["state"] == "TASK_STATE_AUTH_REQUIRED"
    assert task["status"]["message"]["parts"][0]["data"]["approval_path"].endswith(task["id"])

    duplicate = await client.post(
        "/rpc",
        json=recovery_request(request_id="rpc-duplicate", idempotency_key="case-1:a2a"),
    )
    assert duplicate.json()["result"]["task"]["id"] == task["id"]

    fetched = await client.post(
        "/rpc",
        json={
            "jsonrpc": "2.0",
            "id": "rpc-get",
            "method": "GetTask",
            "params": {"id": task["id"], "historyLength": 1},
        },
    )
    assert fetched.json()["result"]["status"]["state"] == "TASK_STATE_AUTH_REQUIRED"
    assert len(fetched.json()["result"]["history"]) == 1

    summary = await client.get(f"/v1/tasks/{task['id']}/approval")
    assert summary.json()["exact_amount_paise"] == 149900
    assert summary.json()["merchant_display_name"] == "FitBox"

    approved = await client.post(
        f"/v1/tasks/{task['id']}/approval",
        json={
            "decision": "APPROVE",
            "merchant_id": "merchant-1",
            "case_id": "case-1",
            "exact_amount_paise": 149900,
            "payment_surface_reference": "inv_123",
        },
    )
    assert approved.status_code == 200
    approved_task = approved.json()
    assert approved_task["status"]["state"] == "TASK_STATE_WORKING"
    signed = approved_task["artifacts"][0]["parts"][0]["data"]
    assert signed["algorithm"] == "Ed25519"
    assert signed["data"]["authorized_action"] == "OPEN_EXACT_PAYMENT_SURFACE"

    receipt = {
        "jsonrpc": "2.0",
        "id": "rpc-receipt",
        "method": "SendMessage",
        "params": {
            "message": {
                "messageId": "message-receipt",
                "role": "ROLE_USER",
                "taskId": task["id"],
                "parts": [
                    {
                        "data": {
                            "protocol_version": "recovery.receipt.v1",
                            "task_id": task["id"],
                            "mandate_id": signed["data"]["mandate_id"],
                            "merchant_id": "merchant-1",
                            "case_id": "case-1",
                            "exact_amount_paise": 149900,
                            "currency": "INR",
                            "provider_reference": "pay_captured_1",
                            "payment_state": "CAPTURED",
                            "observed_at": datetime.now(UTC).isoformat(),
                        }
                    }
                ],
            }
        },
    }
    completed = await client.post("/rpc", json=receipt)
    result = completed.json()["result"]["task"]
    assert result["status"]["state"] == "TASK_STATE_COMPLETED"
    assert result["artifacts"][1]["parts"][0]["data"]["provider_reference"] == "pay_captured_1"


@pytest.mark.asyncio
async def test_approval_rejects_changed_scope_and_second_decision(
    client: httpx.AsyncClient,
) -> None:
    task = (await client.post("/rpc", json=recovery_request())).json()["result"]["task"]
    changed = await client.post(
        f"/v1/tasks/{task['id']}/approval",
        json={
            "decision": "APPROVE",
            "merchant_id": "merchant-1",
            "case_id": "case-1",
            "exact_amount_paise": 1,
            "payment_surface_reference": "inv_123",
        },
    )
    assert changed.status_code == 409
    assert changed.json()["detail"] == "approval scope does not match the recovery request"

    exact = {
        "decision": "REJECT",
        "merchant_id": "merchant-1",
        "case_id": "case-1",
        "exact_amount_paise": 149900,
        "payment_surface_reference": "inv_123",
    }
    rejected = await client.post(f"/v1/tasks/{task['id']}/approval", json=exact)
    assert rejected.json()["status"]["state"] == "TASK_STATE_CANCELED"
    again = await client.post(f"/v1/tasks/{task['id']}/approval", json=exact)
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_cancel_task_is_idempotent(client: httpx.AsyncClient) -> None:
    task = (await client.post("/rpc", json=recovery_request())).json()["result"]["task"]
    payload = {
        "jsonrpc": "2.0",
        "id": "rpc-cancel",
        "method": "CancelTask",
        "params": {"id": task["id"], "reason": "Payment captured elsewhere"},
    }
    first = await client.post("/rpc", json=payload)
    second = await client.post("/rpc", json=payload)
    assert first.json()["result"]["status"]["state"] == "TASK_STATE_CANCELED"
    assert second.json()["result"]["status"]["state"] == "TASK_STATE_CANCELED"
