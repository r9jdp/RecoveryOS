from datetime import UTC, datetime, timedelta

import httpx
import pytest
from app.config import CustomerAgentSettings
from app.main import create_app

from services.api.app.integrations.a2a.client import A2ACustomerAgentClient
from services.api.app.integrations.a2a.mandates import MandateVerifier
from services.api.app.integrations.a2a.models import ExpectedMandateScope
from services.api.app.integrations.a2a.nonce_store import InMemoryNonceStore
from services.api.app.providers.contracts import CustomerAgentRecoveryRequest


@pytest.mark.asyncio
async def test_approval_creates_one_exact_mandate_with_idempotent_verification() -> None:
    app = create_app(
        CustomerAgentSettings(
            origin="http://customer-agent.test",
            web_origin="http://web.test",
        )
    )
    expires_at = datetime.now(UTC) + timedelta(minutes=10)
    request = CustomerAgentRecoveryRequest(
        idempotency_key="case-1:a2a:1",
        case_id="case-1",
        merchant_id="merchant-1",
        customer_id="customer-1",
        recovery_action_id="action-1",
        failed_invoice_id="invoice-local-1",
        exact_amount_paise=149_900,
        currency="INR",
        payment_surface_type="SUBSCRIPTION_INVOICE_LINK",
        payment_surface_reference="inv-1",
        expires_at=expires_at,
        context={
            "merchant_display_name": "FitBox",
            "plan_name": "FitBox Annual",
            "failure_explanation": "Authentication was not completed.",
            "invoice_state": "issued",
            "payment_state": "FAILED",
            "subscription_state": "PENDING",
            "provider_subscription_state": "pending",
            "preferred_language": "en-IN",
            "invoice_due_at": expires_at - timedelta(days=1),
            "recovery_deadline": expires_at,
        },
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://customer-agent.test"
    ) as transport_client:
        client = A2ACustomerAgentClient(
            origin="http://customer-agent.test", client=transport_client
        )
        task = await client.send_recovery_request(request)
        assert task.state == "AUTH_REQUIRED"

        approval = await transport_client.post(
            f"/v1/tasks/{task.remote_task_id}/approval",
            json={
                "decision": "APPROVE",
                "merchant_id": request.merchant_id,
                "case_id": request.case_id,
                "exact_amount_paise": request.exact_amount_paise,
                "payment_surface_reference": request.payment_surface_reference,
            },
        )
        assert approval.status_code == 200
        approved = await client.get_task(remote_task_id=task.remote_task_id)
        assert approved.state == "WORKING"
        assert approved.artifact is not None

        card = (await transport_client.get("/.well-known/agent-card.json")).json()
        extension = card["capabilities"]["extensions"][0]["params"]
        verifier = MandateVerifier(
            pinned_public_keys={extension["signerKeyId"]: extension["publicKeyBase64Url"]},
            nonce_store=InMemoryNonceStore(),
        )
        expected = ExpectedMandateScope(
            task_id=task.remote_task_id,
            merchant_id=request.merchant_id,
            case_id=request.case_id,
            customer_id=request.customer_id,
            recovery_action_id=request.recovery_action_id,
            failed_invoice_id=request.failed_invoice_id,
            exact_amount_paise=request.exact_amount_paise,
            currency=request.currency,
            payment_surface_type=request.payment_surface_type,
            payment_surface_reference=request.payment_surface_reference,
        )
        verified = await verifier.verify_and_consume(approved.artifact, expected=expected)
        assert verified.data.protocol_version == "recovery.mandate.v2"
        assert verified.data.authorized_action == "OPEN_EXACT_PAYMENT_SURFACE"
        retry = await verifier.verify_and_consume(approved.artifact, expected=expected)
        assert retry.claim_id == verified.claim_id
