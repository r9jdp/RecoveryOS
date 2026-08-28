from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from app.config import CustomerAgentSettings
from app.main import create_app
from app.store import create_schema_for_tests

from services.api.app.integrations.a2a.receipts import (
    RecoveryReceiptData,
    RecoveryReceiptSigner,
)

_A2A_HEADERS = {
    "A2A-Version": "1.0",
    "A2A-Extensions": (
        "https://recoveryos.dev/a2a/recovery-mandate/v1,"
        "https://recoveryos.dev/a2a/recovery-receipt/v1"
    ),
}


def _database_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.as_posix()}"


def _settings(database_url: str) -> CustomerAgentSettings:
    return CustomerAgentSettings(
        origin="https://customer-agent.example",
        web_origin="https://app.example",
        task_store="sql",
        database_url=database_url,
    )


def _request(*, request_id: str, idempotency_key: str = "case-durable:a2a") -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "SendMessage",
        "params": {
            "message": {
                "messageId": f"message-{request_id}",
                "role": "ROLE_USER",
                "contextId": "recovery:case-durable",
                "parts": [
                    {
                        "data": {
                            "protocol_version": "recovery.request.v1",
                            "idempotency_key": idempotency_key,
                            "case_id": "case-durable",
                            "merchant_id": "merchant-1",
                            "customer_id": "customer-1",
                            "exact_amount_paise": 149900,
                            "currency": "INR",
                            "payment_surface_type": "SUBSCRIPTION_INVOICE_LINK",
                            "payment_surface_reference": "inv_durable",
                            "expires_at": (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
                        }
                    }
                ],
            }
        },
    }


def _approval() -> dict[str, Any]:
    return {
        "decision": "APPROVE",
        "merchant_id": "merchant-1",
        "case_id": "case-durable",
        "exact_amount_paise": 149900,
        "payment_surface_reference": "inv_durable",
    }


def _signed_receipt(
    *,
    task_id: str,
    mandate_id: str,
    provider_reference: str = "pay_durable_1",
) -> dict[str, Any]:
    signer = RecoveryReceiptSigner.mock()
    return signer.sign(
        RecoveryReceiptData(
            receipt_id="message-receipt-durable",
            signer_key_id=signer.signer_key_id,
            task_id=task_id,
            mandate_id=mandate_id,
            merchant_id="merchant-1",
            case_id="case-durable",
            exact_amount_paise=149_900,
            currency="INR",
            provider_reference=provider_reference,
            observed_at=datetime.now(UTC),
        )
    ).model_dump(mode="json")


async def _client(app: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://customer-agent.example",
        headers=_A2A_HEADERS,
    )


@pytest.mark.asyncio
async def test_task_approval_artifact_and_receipt_survive_service_restarts(
    tmp_path: Path,
) -> None:
    database_url = _database_url(tmp_path / "customer-agent.db")
    await create_schema_for_tests(database_url)
    settings = _settings(database_url)

    first_app = create_app(settings)
    async with await _client(first_app) as client:
        created = await client.post("/rpc", json=_request(request_id="create"))
        task_id = created.json()["result"]["task"]["id"]
    await first_app.state.customer_agent_store.close()

    second_app = create_app(settings)
    async with await _client(second_app) as client:
        fetched = await client.post(
            "/rpc",
            json={
                "jsonrpc": "2.0",
                "id": "get-after-restart",
                "method": "GetTask",
                "params": {"id": task_id},
            },
        )
        assert fetched.json()["result"]["status"]["state"] == "TASK_STATE_AUTH_REQUIRED"
        approved = await client.post(f"/v1/tasks/{task_id}/approval", json=_approval())
        signed = approved.json()["artifacts"][0]["parts"][0]["data"]
    await second_app.state.customer_agent_store.close()

    third_app = create_app(settings)
    receipt_request: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": "receipt-after-restart",
        "method": "SendMessage",
        "params": {
            "message": {
                "messageId": "message-receipt-durable",
                "role": "ROLE_USER",
                "taskId": task_id,
                "parts": [
                    {
                        "data": _signed_receipt(
                            task_id=task_id,
                            mandate_id=signed["data"]["mandate_id"],
                        )
                    }
                ],
            }
        },
    }
    async with await _client(third_app) as client:
        before_receipt = await client.post(
            "/rpc",
            json={
                "jsonrpc": "2.0",
                "id": "get-mandate-after-restart",
                "method": "GetTask",
                "params": {"id": task_id},
            },
        )
        assert before_receipt.json()["result"]["artifacts"][0] == approved.json()["artifacts"][0]
        completed = await client.post("/rpc", json=receipt_request)
        duplicate = await client.post("/rpc", json=receipt_request)
        assert completed.json()["result"]["task"]["status"]["state"] == "TASK_STATE_COMPLETED"
        assert duplicate.json()["result"]["task"] == completed.json()["result"]["task"]
        changed_receipt = deepcopy(receipt_request)
        changed_receipt["params"]["message"]["parts"][0]["data"] = _signed_receipt(
            task_id=task_id,
            mandate_id=signed["data"]["mandate_id"],
            provider_reference="pay_changed",
        )
        conflict = await client.post("/rpc", json=changed_receipt)
        assert conflict.json()["error"] == {
            "code": -32002,
            "message": "messageId was reused with different receipt data",
        }
    await third_app.state.customer_agent_store.close()

    fourth_app = create_app(settings)
    async with await _client(fourth_app) as client:
        final = await client.post(
            "/rpc",
            json={
                "jsonrpc": "2.0",
                "id": "get-complete-after-restart",
                "method": "GetTask",
                "params": {"id": task_id},
            },
        )
        assert final.json()["result"]["status"]["state"] == "TASK_STATE_COMPLETED"
        assert (
            final.json()["result"]["artifacts"][1]["parts"][0]["data"]["data"]["provider_reference"]
            == "pay_durable_1"
        )
    await fourth_app.state.customer_agent_store.close()


@pytest.mark.asyncio
async def test_duplicate_send_is_serialized_by_durable_store(tmp_path: Path) -> None:
    database_url = _database_url(tmp_path / "duplicate.db")
    await create_schema_for_tests(database_url)
    app = create_app(_settings(database_url))
    async with await _client(app) as client:
        first, second = await asyncio.gather(
            client.post("/rpc", json=_request(request_id="one")),
            client.post("/rpc", json=_request(request_id="two")),
        )
        assert first.status_code == second.status_code == 200
        assert first.json()["result"]["task"]["id"] == second.json()["result"]["task"]["id"]
    await app.state.customer_agent_store.close()


@pytest.mark.asyncio
async def test_concurrent_approval_and_cancel_cannot_lose_cancellation(tmp_path: Path) -> None:
    database_url = _database_url(tmp_path / "concurrent.db")
    await create_schema_for_tests(database_url)
    app = create_app(_settings(database_url))
    async with await _client(app) as client:
        created = await client.post("/rpc", json=_request(request_id="concurrent"))
        task_id = created.json()["result"]["task"]["id"]
        approval_response, cancel_response = await asyncio.gather(
            client.post(f"/v1/tasks/{task_id}/approval", json=_approval()),
            client.post(
                "/rpc",
                json={
                    "jsonrpc": "2.0",
                    "id": "cancel-concurrently",
                    "method": "CancelTask",
                    "params": {"id": task_id, "reason": "Payment captured elsewhere"},
                },
            ),
        )
        assert approval_response.status_code in {200, 409}
        assert cancel_response.status_code == 200
        assert cancel_response.json()["result"]["status"]["state"] == "TASK_STATE_CANCELED"

        fetched = await client.post(
            "/rpc",
            json={
                "jsonrpc": "2.0",
                "id": "get-after-race",
                "method": "GetTask",
                "params": {"id": task_id},
            },
        )
        assert fetched.json()["result"]["status"]["state"] == "TASK_STATE_CANCELED"
    await app.state.customer_agent_store.close()


@pytest.mark.asyncio
async def test_sql_readiness_reports_store_without_leaking_database_url(tmp_path: Path) -> None:
    database_url = _database_url(tmp_path / "readiness.db")
    await create_schema_for_tests(database_url)
    app = create_app(_settings(database_url))
    async with await _client(app) as client:
        response = await client.get("/health/ready")
        assert response.status_code == 200
        assert response.json() == {"status": "ready", "mode": "mock", "store": "sql"}
        assert str(tmp_path) not in response.text
    await app.state.customer_agent_store.close()


@pytest.mark.asyncio
async def test_sql_readiness_fails_safely_when_migration_is_missing(tmp_path: Path) -> None:
    database_url = _database_url(tmp_path / "unmigrated.db")
    app = create_app(_settings(database_url))
    async with await _client(app) as client:
        response = await client.get("/health/ready")
        assert response.status_code == 503
        assert response.json() == {"status": "not_ready", "mode": "mock", "store": "sql"}
        assert database_url not in response.text
    await app.state.customer_agent_store.close()
