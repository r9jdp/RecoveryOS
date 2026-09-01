from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from app.config import CustomerAgentSettings
from app.main import create_app
from app.store import create_schema_for_tests

from services.api.app.domain.enums import PaymentSurfaceType
from services.api.app.integrations.a2a.client import A2ACustomerAgentClient
from services.api.app.integrations.a2a.receipts import RecoveryReceiptSigner
from services.api.app.providers.contracts import CustomerAgentRecoveryRequest


def _recovery_request(
    *,
    idempotency_key: str = "merchant-1:case-1:a2a",
    case_id: str = "case-1",
    recovery_action_id: str = "action-1",
    failed_invoice_id: str = "invoice-local-1",
    payment_surface_reference: str = "inv_123",
) -> CustomerAgentRecoveryRequest:
    recovery_deadline = datetime.now(UTC) + timedelta(minutes=10)
    return CustomerAgentRecoveryRequest(
        idempotency_key=idempotency_key,
        case_id=case_id,
        merchant_id="merchant-1",
        customer_id="customer-1",
        recovery_action_id=recovery_action_id,
        failed_invoice_id=failed_invoice_id,
        exact_amount_paise=149_900,
        currency="INR",
        payment_surface_type=PaymentSurfaceType.SUBSCRIPTION_INVOICE_LINK,
        payment_surface_reference=payment_surface_reference,
        expires_at=recovery_deadline,
        context={
            "merchant_display_name": "FitBox",
            "plan_name": "FitBox Annual",
            "failure_explanation": "Authentication was not completed.",
            "invoice_state": "issued",
            "payment_state": "FAILED",
            "subscription_state": "PENDING",
            "provider_subscription_state": "pending",
            "preferred_language": "en-IN",
            "invoice_due_at": recovery_deadline - timedelta(days=1),
            "recovery_deadline": recovery_deadline,
        },
    )


@pytest.mark.asyncio
async def test_customer_agent_client_sends_configured_s2s_bearer() -> None:
    captured_authorization: list[str | None] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured_authorization.append(request.headers.get("Authorization"))
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": "response-1",
                "result": {
                    "task": {
                        "id": "task-authenticated",
                        "status": {
                            "state": "TASK_STATE_AUTH_REQUIRED",
                            "timestamp": datetime.now(UTC).isoformat(),
                            "message": {
                                "parts": [
                                    {
                                        "data": {
                                            "approval_path": (
                                                "/a2a/task-authenticated#token=capability-token"
                                            )
                                        }
                                    }
                                ]
                            },
                        },
                        "artifacts": [],
                    }
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = A2ACustomerAgentClient(
            origin="https://customer.example",
            client=http_client,
            bearer_token="outbound-s2s-secret",
        )
        task = await client.send_recovery_request(_recovery_request())

    assert task.state == "AUTH_REQUIRED"
    assert task.approval_path == "/a2a/task-authenticated#token=capability-token"
    assert captured_authorization == ["Bearer outbound-s2s-secret"]


@pytest.mark.asyncio
async def test_frozen_customer_agent_client_maps_auth_required_and_cancel() -> None:
    app = create_app(CustomerAgentSettings(origin="https://customer.example"))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://customer.example",
    ) as http_client:
        client = A2ACustomerAgentClient(
            origin="https://customer.example",
            client=http_client,
        )
        task = await client.send_recovery_request(_recovery_request())
        assert task.state == "AUTH_REQUIRED"
        fetched = await client.get_task(remote_task_id=task.remote_task_id)
        assert fetched == task
        canceled = await client.cancel_task(
            remote_task_id=task.remote_task_id,
            reason="Payment captured elsewhere",
        )
        assert canceled.state == "CANCELED"


@pytest.mark.asyncio
async def test_customer_agent_client_completes_task_with_exact_idempotent_receipt(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{(tmp_path / 'receipt.db').as_posix()}"
    await create_schema_for_tests(database_url)
    settings = CustomerAgentSettings(
        origin="https://customer.example",
        task_store="sql",
        database_url=database_url,
    )
    app = create_app(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://customer.example",
    ) as http_client:
        client = A2ACustomerAgentClient(
            origin="https://customer.example",
            client=http_client,
        )
        task = await client.send_recovery_request(
            _recovery_request(
                idempotency_key="merchant-1:case-receipt:a2a",
                case_id="case-receipt",
                recovery_action_id="action-receipt",
                failed_invoice_id="invoice-local-receipt",
                payment_surface_reference="inv_receipt",
            )
        )
        approved = await http_client.post(
            f"/v1/tasks/{task.remote_task_id}/approval",
            json={
                "decision": "APPROVE",
                "merchant_id": "merchant-1",
                "case_id": "case-receipt",
                "exact_amount_paise": 149_900,
                "payment_surface_reference": "inv_receipt",
            },
        )
        assert approved.status_code == 200
        mandate = approved.json()["artifacts"][0]["parts"][0]["data"]["data"]
        observed_at = datetime.now(UTC)
        receipt_args = {
            "remote_task_id": task.remote_task_id,
            "mandate_id": mandate["mandate_id"],
            "merchant_id": "merchant-1",
            "case_id": "case-receipt",
            "recovery_action_id": "action-receipt",
            "failed_invoice_id": "invoice-local-receipt",
            "exact_amount_paise": 149_900,
            "currency": "INR",
            "provider_reference": "pay_captured_receipt",
            "observed_at": observed_at,
            "idempotency_key": f"{task.remote_task_id}:{mandate['mandate_id']}:receipt",
        }
        completed = await client.send_payment_receipt(**receipt_args)
        duplicate = await client.send_payment_receipt(**receipt_args)

        assert completed.state == "COMPLETED"
        assert duplicate == completed
        fetched = await client.get_task(remote_task_id=task.remote_task_id)
        assert fetched.state == "COMPLETED"
    await app.state.customer_agent_store.close()

    restarted_app = create_app(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=restarted_app),
        base_url="https://customer.example",
    ) as restarted_http_client:
        restarted_client = A2ACustomerAgentClient(
            origin="https://customer.example",
            client=restarted_http_client,
        )
        durable = await restarted_client.get_task(remote_task_id=task.remote_task_id)
        assert durable.state == "COMPLETED"
    await restarted_app.state.customer_agent_store.close()


@pytest.mark.asyncio
async def test_configured_recovery_receipt_signer_must_match_customer_agent_pin() -> None:
    receipt_signer = RecoveryReceiptSigner.from_seed(
        signer_key_id="recovery-agent-hosted-1",
        seed=bytes(range(32)),
    )
    settings = CustomerAgentSettings(
        origin="https://customer.example",
        receipt_verification_mode="pinned",
        recovery_agent_public_keys_json=json.dumps(
            {receipt_signer.signer_key_id: receipt_signer.public_key_base64}
        ),
    )
    app = create_app(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://customer.example",
    ) as http_client:
        client = A2ACustomerAgentClient(
            origin="https://customer.example",
            client=http_client,
            receipt_signer=receipt_signer,
        )
        task = await client.send_recovery_request(
            _recovery_request(
                idempotency_key="merchant-1:case-hosted:a2a",
                case_id="case-hosted",
                recovery_action_id="action-hosted",
                failed_invoice_id="invoice-local-hosted",
                payment_surface_reference="inv_hosted",
            )
        )
        approved = await http_client.post(
            f"/v1/tasks/{task.remote_task_id}/approval",
            json={
                "decision": "APPROVE",
                "merchant_id": "merchant-1",
                "case_id": "case-hosted",
                "exact_amount_paise": 149_900,
                "payment_surface_reference": "inv_hosted",
            },
        )
        mandate_id = approved.json()["artifacts"][0]["parts"][0]["data"]["data"]["mandate_id"]
        completed = await client.send_payment_receipt(
            remote_task_id=task.remote_task_id,
            mandate_id=mandate_id,
            merchant_id="merchant-1",
            case_id="case-hosted",
            recovery_action_id="action-hosted",
            failed_invoice_id="invoice-local-hosted",
            exact_amount_paise=149_900,
            currency="INR",
            provider_reference="pay_hosted_captured",
            observed_at=datetime.now(UTC),
            idempotency_key=f"{task.remote_task_id}:{mandate_id}:receipt",
        )
        assert completed.state == "COMPLETED"


def test_pinned_receipt_mode_requires_explicit_server_side_keys() -> None:
    with pytest.raises(
        ValueError,
        match="CUSTOMER_AGENT_RECOVERY_AGENT_PUBLIC_KEYS_JSON is required",
    ):
        create_app(CustomerAgentSettings(receipt_verification_mode="pinned"))
