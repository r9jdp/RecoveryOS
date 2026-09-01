from __future__ import annotations

import asyncio
import base64
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from app.config import CustomerAgentSettings
from app.main import create_app
from app.models import LanguageModelInterpretation

from services.api.app.integrations.a2a.receipts import (
    RecoveryReceiptData,
    RecoveryReceiptSigner,
)

_A2A_EXTENSIONS = (
    "https://recoveryos.dev/a2a/recovery-mandate/v2,https://recoveryos.dev/a2a/recovery-receipt/v2"
)
_REQUEST_EXPIRES_AT = datetime.now(UTC) + timedelta(hours=1)


class StaticLanguageInterpreter:
    async def interpret(self, **_kwargs: object) -> LanguageModelInterpretation:
        return LanguageModelInterpretation(
            intent="ASK_QUESTION",
            confidence_basis_points=9_000,
            explanation="The customer is asking for more information.",
        )

    async def close(self) -> None:
        return None


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
            "A2A-Extensions": _A2A_EXTENSIONS,
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
                            "protocol_version": "recovery.request.v2",
                            "idempotency_key": idempotency_key,
                            "case_id": "case-1",
                            "merchant_id": "merchant-1",
                            "customer_id": "customer-1",
                            "recovery_action_id": "action-1",
                            "failed_invoice_id": "invoice-local-1",
                            "exact_amount_paise": 149900,
                            "currency": "INR",
                            "payment_surface_type": "SUBSCRIPTION_INVOICE_LINK",
                            "payment_surface_reference": "inv_123",
                            "expires_at": _REQUEST_EXPIRES_AT.isoformat(),
                            "context": {
                                "merchant_display_name": "FitBox",
                                "plan_name": "FitBox Annual",
                                "failure_explanation": (
                                    "The payment needs customer authentication before it can "
                                    "continue."
                                ),
                                "invoice_state": "issued",
                                "payment_state": "FAILED",
                                "subscription_state": "PENDING",
                                "provider_subscription_state": "pending",
                                "preferred_language": "en-IN",
                                "invoice_due_at": (
                                    _REQUEST_EXPIRES_AT - timedelta(days=1)
                                ).isoformat(),
                                "recovery_deadline": _REQUEST_EXPIRES_AT.isoformat(),
                            },
                        }
                    }
                ],
            }
        },
    }


def signed_receipt(
    *,
    task_id: str,
    mandate_id: str,
    message_id: str = "message-receipt",
    merchant_id: str = "merchant-1",
    case_id: str = "case-1",
    exact_amount_paise: int = 149_900,
    provider_reference: str = "pay_captured_1",
    signer: RecoveryReceiptSigner | None = None,
) -> dict[str, Any]:
    active_signer = signer or RecoveryReceiptSigner.mock()
    return active_signer.sign(
        RecoveryReceiptData(
            receipt_id=message_id,
            signer_key_id=active_signer.signer_key_id,
            task_id=task_id,
            mandate_id=mandate_id,
            merchant_id=merchant_id,
            case_id=case_id,
            recovery_action_id="action-1",
            failed_invoice_id="invoice-local-1",
            exact_amount_paise=exact_amount_paise,
            currency="INR",
            provider_reference=provider_reference,
            observed_at=datetime.now(UTC),
        )
    ).model_dump(mode="json")


def receipt_rpc(
    *,
    task_id: str,
    mandate_id: str,
    message_id: str = "message-receipt",
    envelope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": f"rpc-{message_id}",
        "method": "SendMessage",
        "params": {
            "message": {
                "messageId": message_id,
                "role": "ROLE_USER",
                "taskId": task_id,
                "parts": [
                    {
                        "data": envelope
                        or signed_receipt(
                            task_id=task_id,
                            mandate_id=mandate_id,
                            message_id=message_id,
                        )
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
    assert card["securitySchemes"] == {}
    assert card["security"] == []
    extension = card["capabilities"]["extensions"][0]
    assert extension["params"]["signingAlgorithm"] == "Ed25519"
    assert len(extension["params"]["publicKeyBase64Url"]) == 43
    receipt_extension = card["capabilities"]["extensions"][1]
    assert receipt_extension["uri"].endswith("/recovery-receipt/v2")
    assert receipt_extension["params"] == {
        "authentication": "Ed25519",
        "protocolVersion": "recovery.receipt.v2",
        "canonicalization": "RECOVERYOS_CANONICAL_JSON_V1",
        "acceptedSignerKeyIds": ["recoveryos-receipt-mock-2026-01"],
        "scope": [
            "receipt_id",
            "task_id",
            "mandate_id",
            "merchant_id",
            "case_id",
            "recovery_action_id",
            "failed_invoice_id",
            "exact_amount_paise",
            "currency",
            "provider_reference",
            "payment_state",
            "observed_at",
        ],
    }


@pytest.mark.asyncio
async def test_real_signing_requires_and_enforces_s2s_bearer_before_json_parsing() -> None:
    encoded_seed = base64.urlsafe_b64encode(bytes(range(32))).rstrip(b"=").decode("ascii")
    with pytest.raises(ValueError, match="CUSTOMER_AGENT_S2S_BEARER_TOKEN"):
        CustomerAgentSettings(
            real_signing_enabled=True,
            ed25519_private_key=encoded_seed,
        )

    app = create_app(
        CustomerAgentSettings(
            origin="https://customer-agent.example",
            real_signing_enabled=True,
            ed25519_private_key=encoded_seed,
            s2s_bearer_token="customer-agent-s2s-secret",
            approval_token_secret="customer-agent-approval-capability-secret",
        )
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://customer-agent.example",
    ) as protected_client:
        card = (await protected_client.get("/.well-known/agent-card.json")).json()
        missing = await protected_client.post("/rpc", content=b"not-json")
        wrong = await protected_client.post(
            "/rpc",
            content=b"not-json",
            headers={"Authorization": "Bearer incorrect"},
        )
        malformed_with_auth = await protected_client.post(
            "/rpc",
            content=b"not-json",
            headers={"Authorization": "Bearer customer-agent-s2s-secret"},
        )

    assert card["securitySchemes"]["recoveryOSS2SBearer"]["scheme"] == "bearer"
    assert card["security"] == [{"recoveryOSS2SBearer": []}]
    assert missing.status_code == wrong.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"
    assert malformed_with_auth.status_code == 200
    assert malformed_with_auth.json()["error"]["code"] == -32700


def test_real_signing_requires_customer_approval_capability_secret() -> None:
    encoded_seed = base64.urlsafe_b64encode(bytes(range(32))).rstrip(b"=").decode("ascii")
    with pytest.raises(ValueError, match="CUSTOMER_AGENT_APPROVAL_TOKEN_SECRET"):
        CustomerAgentSettings(
            real_signing_enabled=True,
            ed25519_private_key=encoded_seed,
            s2s_bearer_token="customer-agent-s2s-secret",
        )

    with pytest.raises(ValueError, match="must contain at least 32 bytes"):
        CustomerAgentSettings(approval_token_secret="too-short")


@pytest.mark.asyncio
async def test_approval_capability_is_stateless_idempotent_and_required_for_customer_routes() -> (
    None
):
    app = create_app(
        CustomerAgentSettings(
            origin="https://customer-agent.example",
            web_origin="https://app.example",
            approval_token_secret="customer-agent-approval-capability-secret",
        ),
        language_interpreter=StaticLanguageInterpreter(),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://customer-agent.example",
        headers={
            "A2A-Version": "1.0",
            "A2A-Extensions": _A2A_EXTENSIONS,
        },
    ) as protected_client:
        created = (
            await protected_client.post(
                "/rpc",
                json=recovery_request(request_id="capability-original"),
            )
        ).json()["result"]["task"]
        duplicate = (
            await protected_client.post(
                "/rpc",
                json=recovery_request(request_id="capability-duplicate"),
            )
        ).json()["result"]["task"]
        approval_path = created["status"]["message"]["parts"][0]["data"]["approval_path"]
        duplicate_path = duplicate["status"]["message"]["parts"][0]["data"]["approval_path"]
        token = parse_qs(urlsplit(approval_path).fragment)["token"][0]
        task_id = created["id"]

        missing = await protected_client.get(f"/v1/tasks/{task_id}/approval")
        query_only = await protected_client.get(
            f"/v1/tasks/{task_id}/approval",
            params={"token": token},
        )
        wrong = await protected_client.get(
            f"/v1/tasks/{task_id}/approval",
            headers={"Authorization": "Bearer wrong-token"},
        )
        authorized = {"Authorization": f"Bearer {token}"}
        summary = await protected_client.get(
            f"/v1/tasks/{task_id}/approval",
            headers=authorized,
        )
        missing_interpretation = await protected_client.post(
            f"/v1/tasks/{task_id}/interpretation",
            json={"text": "Why did this fail?"},
        )
        interpretation = await protected_client.post(
            f"/v1/tasks/{task_id}/interpretation",
            json={"text": "Why did this fail?"},
            headers=authorized,
        )
        missing_decision = await protected_client.post(
            f"/v1/tasks/{task_id}/approval",
            json={
                "decision": "APPROVE",
                "merchant_id": "merchant-1",
                "case_id": "case-1",
                "exact_amount_paise": 149900,
                "payment_surface_reference": "inv_123",
            },
        )
        approved = await protected_client.post(
            f"/v1/tasks/{task_id}/approval",
            json={
                "decision": "APPROVE",
                "merchant_id": "merchant-1",
                "case_id": "case-1",
                "exact_amount_paise": 149900,
                "payment_surface_reference": "inv_123",
            },
            headers=authorized,
        )
        decided_summary = await protected_client.get(
            f"/v1/tasks/{task_id}/approval",
            headers=authorized,
        )

    assert approval_path == duplicate_path
    assert approval_path.startswith(f"/a2a/{task_id}#token=")
    assert len(token) == 43
    assert missing.status_code == query_only.status_code == wrong.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"
    assert summary.status_code == 200
    assert missing_interpretation.status_code == 401
    assert interpretation.status_code == 200
    assert interpretation.json()["authorization_effect"] == "NONE"
    assert missing_decision.status_code == 401
    assert approved.status_code == 200
    assert decided_summary.status_code == 409
    serialized_mandate = json.dumps(approved.json(), sort_keys=True)
    assert token not in serialized_mandate
    stored = await app.state.customer_agent_store.get(task_id)
    assert stored is not None
    assert token not in json.dumps(stored.model_dump(mode="json"), sort_keys=True)


@pytest.mark.asyncio
async def test_approval_capability_cannot_read_task_after_request_expiry() -> None:
    app = create_app(
        CustomerAgentSettings(
            origin="https://customer-agent.example",
            approval_token_secret="customer-agent-approval-capability-secret",
        )
    )
    request = recovery_request(
        request_id="capability-expiry",
        idempotency_key="capability-expiry:a2a",
    )
    expires_at = datetime.now(UTC) + timedelta(milliseconds=500)
    request_data = request["params"]["message"]["parts"][0]["data"]
    request_data["expires_at"] = expires_at.isoformat()
    request_data["context"]["recovery_deadline"] = expires_at.isoformat()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://customer-agent.example",
        headers={"A2A-Version": "1.0", "A2A-Extensions": _A2A_EXTENSIONS},
    ) as protected_client:
        task = (await protected_client.post("/rpc", json=request)).json()["result"]["task"]
        approval_path = task["status"]["message"]["parts"][0]["data"]["approval_path"]
        token = parse_qs(urlsplit(approval_path).fragment)["token"][0]
        await asyncio.sleep(0.55)
        expired = await protected_client.get(
            f"/v1/tasks/{task['id']}/approval",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert expired.status_code == 401
    assert expired.headers["www-authenticate"] == "Bearer"


@pytest.mark.asyncio
async def test_duplicate_idempotency_key_with_changed_request_is_rejected(
    client: httpx.AsyncClient,
) -> None:
    initial = recovery_request(request_id="idempotency-original")
    changed = deepcopy(recovery_request(request_id="idempotency-changed"))
    changed["params"]["message"]["parts"][0]["data"]["exact_amount_paise"] = 149_901

    created = await client.post("/rpc", json=initial)
    conflict = await client.post("/rpc", json=changed)

    assert created.status_code == conflict.status_code == 200
    assert conflict.json()["error"] == {
        "code": -32002,
        "message": "Idempotency key was reused with a different recovery request",
    }


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
    assert summary.json()["plan_name"] == "FitBox Annual"
    assert summary.json()["failure_explanation"].startswith(
        "The payment needs customer authentication"
    )

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
    assert signed["data"]["protocol_version"] == "recovery.mandate.v2"
    assert signed["data"]["recovery_action_id"] == "action-1"
    assert signed["data"]["failed_invoice_id"] == "invoice-local-1"
    assert signed["data"]["authorized_action"] == "OPEN_EXACT_PAYMENT_SURFACE"
    assert "merchant_display_name" not in signed["data"]
    assert "plan_name" not in signed["data"]
    assert "failure_explanation" not in signed["data"]
    assert "invoice_state" not in signed["data"]
    assert "payment_state" not in signed["data"]
    assert "subscription_state" not in signed["data"]
    assert "provider_subscription_state" not in signed["data"]
    assert "preferred_language" not in signed["data"]
    assert "invoice_due_at" not in signed["data"]
    assert "recovery_deadline" not in signed["data"]

    receipt = receipt_rpc(task_id=task["id"], mandate_id=signed["data"]["mandate_id"])
    completed = await client.post("/rpc", json=receipt)
    result = completed.json()["result"]["task"]
    assert result["status"]["state"] == "TASK_STATE_COMPLETED"
    assert (
        result["artifacts"][1]["parts"][0]["data"]["data"]["provider_reference"] == "pay_captured_1"
    )


@pytest.mark.asyncio
async def test_recovery_request_without_database_display_context_fails_closed(
    client: httpx.AsyncClient,
) -> None:
    request = recovery_request(request_id="missing-display-context")
    del request["params"]["message"]["parts"][0]["data"]["context"]

    response = await client.post("/rpc", json=request)

    assert response.status_code == 200
    assert response.json()["error"]["code"] == -32602
    assert response.json()["error"]["message"] == "Invalid params"


@pytest.mark.asyncio
async def test_receipt_requires_valid_signature_exact_scope_and_stable_replay(
    client: httpx.AsyncClient,
) -> None:
    task = (
        await client.post(
            "/rpc",
            json=recovery_request(request_id="receipt-auth", idempotency_key="receipt-auth:a2a"),
        )
    ).json()["result"]["task"]
    approved = await client.post(
        f"/v1/tasks/{task['id']}/approval",
        json={
            "decision": "APPROVE",
            "merchant_id": "merchant-1",
            "case_id": "case-1",
            "exact_amount_paise": 149_900,
            "payment_surface_reference": "inv_123",
        },
    )
    mandate_id = approved.json()["artifacts"][0]["parts"][0]["data"]["data"]["mandate_id"]
    message_id = "receipt-auth-message"

    missing_auth = receipt_rpc(
        task_id=task["id"],
        mandate_id=mandate_id,
        message_id=message_id,
        envelope={
            "protocol_version": "recovery.receipt.v2",
            "task_id": task["id"],
            "mandate_id": mandate_id,
        },
    )
    missing_response = await client.post("/rpc", json=missing_auth)
    assert missing_response.json()["error"]["code"] == -32602

    exact_envelope = signed_receipt(
        task_id=task["id"],
        mandate_id=mandate_id,
        message_id=message_id,
    )
    bad_signature = {
        **exact_envelope,
        "signature": ("A" if exact_envelope["signature"][0] != "A" else "B")
        + exact_envelope["signature"][1:],
    }
    bad_response = await client.post(
        "/rpc",
        json=receipt_rpc(
            task_id=task["id"],
            mandate_id=mandate_id,
            message_id=message_id,
            envelope=bad_signature,
        ),
    )
    assert bad_response.json()["error"] == {
        "code": -32002,
        "message": "payment receipt signature is invalid",
    }

    changed_scope = {
        **exact_envelope,
        "data": {**exact_envelope["data"], "exact_amount_paise": 1},
    }
    changed_response = await client.post(
        "/rpc",
        json=receipt_rpc(
            task_id=task["id"],
            mandate_id=mandate_id,
            message_id=message_id,
            envelope=changed_scope,
        ),
    )
    assert changed_response.json()["error"]["message"] == "payment receipt signature is invalid"

    valid_wrong_scope = signed_receipt(
        task_id=task["id"],
        mandate_id=mandate_id,
        message_id=message_id,
        exact_amount_paise=1,
    )
    wrong_scope_response = await client.post(
        "/rpc",
        json=receipt_rpc(
            task_id=task["id"],
            mandate_id=mandate_id,
            message_id=message_id,
            envelope=valid_wrong_scope,
        ),
    )
    assert wrong_scope_response.json()["error"] == {
        "code": -32002,
        "message": "receipt scope does not match the signed mandate",
    }

    exact_request = receipt_rpc(
        task_id=task["id"],
        mandate_id=mandate_id,
        message_id=message_id,
        envelope=exact_envelope,
    )
    completed = await client.post("/rpc", json=exact_request)
    replay = await client.post("/rpc", json=exact_request)
    assert completed.json()["result"]["task"]["status"]["state"] == "TASK_STATE_COMPLETED"
    assert replay.json()["result"]["task"] == completed.json()["result"]["task"]

    different_envelope = signed_receipt(
        task_id=task["id"],
        mandate_id=mandate_id,
        message_id=message_id,
        provider_reference="pay_changed_but_validly_signed",
    )
    different_response = await client.post(
        "/rpc",
        json=receipt_rpc(
            task_id=task["id"],
            mandate_id=mandate_id,
            message_id=message_id,
            envelope=different_envelope,
        ),
    )
    assert different_response.json()["error"] == {
        "code": -32002,
        "message": "messageId was reused with different receipt data",
    }


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


@pytest.mark.asyncio
async def test_unknown_json_rpc_method_returns_protocol_error(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/rpc",
        json={"jsonrpc": "2.0", "id": "unknown", "method": "FutureMethod", "params": {}},
    )
    assert response.status_code == 200
    assert response.json() == {
        "jsonrpc": "2.0",
        "id": "unknown",
        "error": {"code": -32601, "message": "Method not found"},
    }


@pytest.mark.asyncio
async def test_malformed_json_rpc_requests_are_protocol_errors(client: httpx.AsyncClient) -> None:
    invalid_envelope = await client.post(
        "/rpc",
        json={"jsonrpc": "2.0", "id": "invalid-envelope", "method": "GetTask"},
    )
    assert invalid_envelope.status_code == 200
    assert invalid_envelope.json()["error"]["code"] == -32600
    assert invalid_envelope.json()["id"] == "invalid-envelope"

    invalid_params = await client.post(
        "/rpc",
        json={"jsonrpc": "2.0", "id": "invalid-params", "method": "GetTask", "params": {}},
    )
    assert invalid_params.status_code == 200
    assert invalid_params.json()["error"]["code"] == -32602

    parse_error = await client.post(
        "/rpc",
        content=b'{"jsonrpc":',
        headers={"Content-Type": "application/json"},
    )
    assert parse_error.status_code == 200
    assert parse_error.json() == {
        "jsonrpc": "2.0",
        "id": None,
        "error": {"code": -32700, "message": "Parse error"},
    }


@pytest.mark.asyncio
async def test_default_app_uses_ready_in_memory_mock_store() -> None:
    app = create_app(CustomerAgentSettings(task_store="memory", database_url=None))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://customer-agent.test",
    ) as default_client:
        response = await default_client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "mode": "mock", "store": "memory"}
