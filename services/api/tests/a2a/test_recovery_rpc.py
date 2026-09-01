from datetime import UTC, datetime

import httpx
import pytest
from fastapi import FastAPI

from services.api.app.a2a.router import get_customer_agent_client, router
from services.api.app.providers.contracts import CustomerAgentRecoveryRequest, CustomerAgentTask


class FakeCustomerAgentClient:
    async def send_recovery_request(
        self, request: CustomerAgentRecoveryRequest
    ) -> CustomerAgentTask:
        assert request.exact_amount_paise == 149_900
        assert request.context.plan_name == "FitBox Annual"
        assert request.recovery_action_id == "action-1"
        assert request.failed_invoice_id == "invoice-local-1"
        return CustomerAgentTask(
            remote_task_id="task-1",
            state="AUTH_REQUIRED",
            updated_at=datetime(2026, 8, 28, tzinfo=UTC),
        )

    async def get_task(self, *, remote_task_id: str) -> CustomerAgentTask:
        raise NotImplementedError

    async def cancel_task(self, *, remote_task_id: str, reason: str) -> CustomerAgentTask:
        raise NotImplementedError


@pytest.mark.asyncio
async def test_recovery_rpc_is_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("A2A_ENABLED", raising=False)
    monkeypatch.delenv("RECOVERY_AGENT_A2A_INBOUND_BEARER_TOKEN", raising=False)
    app = FastAPI()
    app.include_router(router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/a2a/rpc",
            headers={
                "A2A-Version": "1.0",
                "A2A-Extensions": "https://recoveryos.dev/a2a/recovery-mandate/v2",
            },
            json={"jsonrpc": "2.0", "id": "1", "method": "GetTask", "params": {"id": "x"}},
        )
    assert response.json()["error"]["code"] == -32004


@pytest.mark.asyncio
async def test_recovery_rpc_delegates_exact_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("A2A_ENABLED", "true")
    monkeypatch.delenv("RECOVERY_AGENT_A2A_INBOUND_BEARER_TOKEN", raising=False)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_customer_agent_client] = FakeCustomerAgentClient
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/a2a/rpc",
            headers={
                "A2A-Version": "1.0",
                "A2A-Extensions": "https://recoveryos.dev/a2a/recovery-mandate/v2",
            },
            json={
                "jsonrpc": "2.0",
                "id": "1",
                "method": "SendMessage",
                "params": {
                    "message": {
                        "parts": [
                            {
                                "data": {
                                    "protocol_version": "recovery.request.v2",
                                    "idempotency_key": "case-1:a2a:1",
                                    "case_id": "case-1",
                                    "merchant_id": "merchant-1",
                                    "customer_id": "customer-1",
                                    "recovery_action_id": "action-1",
                                    "failed_invoice_id": "invoice-local-1",
                                    "exact_amount_paise": 149900,
                                    "currency": "INR",
                                    "payment_surface_type": "SUBSCRIPTION_INVOICE_LINK",
                                    "payment_surface_reference": "inv-1",
                                    "expires_at": "2026-08-28T12:00:00Z",
                                    "context": {
                                        "merchant_display_name": "FitBox",
                                        "plan_name": "FitBox Annual",
                                        "failure_explanation": (
                                            "Authentication was not completed."
                                        ),
                                        "invoice_state": "issued",
                                        "payment_state": "FAILED",
                                        "subscription_state": "PENDING",
                                        "provider_subscription_state": "pending",
                                        "preferred_language": "en-IN",
                                        "invoice_due_at": "2026-08-27T12:00:00Z",
                                        "recovery_deadline": "2026-08-28T12:00:00Z",
                                    },
                                }
                            }
                        ]
                    }
                },
            },
        )
    assert response.status_code == 200
    assert response.json()["result"]["task"]["status"]["state"] == "TASK_STATE_AUTH_REQUIRED"


@pytest.mark.asyncio
async def test_recovery_rpc_enforces_configured_inbound_bearer_before_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("A2A_ENABLED", "true")
    monkeypatch.setenv("RECOVERY_AGENT_A2A_INBOUND_BEARER_TOKEN", "recovery-inbound-secret")
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_customer_agent_client] = FakeCustomerAgentClient
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        missing = await client.post("/a2a/rpc", content=b"not-json")
        wrong = await client.post(
            "/a2a/rpc",
            content=b"not-json",
            headers={"Authorization": "Bearer wrong"},
        )
        authenticated = await client.post(
            "/a2a/rpc",
            content=b"not-json",
            headers={"Authorization": "Bearer recovery-inbound-secret"},
        )

    assert missing.status_code == wrong.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"
    assert authenticated.status_code == 200
    assert authenticated.json()["error"]["code"] == -32700
