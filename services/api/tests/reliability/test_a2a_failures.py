from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from services.api.app.integrations.a2a.client import A2ACustomerAgentClient
from services.api.app.integrations.a2a.mandates import (
    MandateVerificationError,
    MandateVerifier,
    canonical_json,
)
from services.api.app.integrations.a2a.models import (
    ExpectedMandateScope,
    RecoveryMandateData,
    SignedMandate,
)
from services.api.app.integrations.a2a.nonce_store import InMemoryNonceStore
from services.api.app.providers.contracts import CustomerAgentRecoveryRequest
from services.api.app.reliability.circuit_breaker import CircuitBreaker, FailureKind


def _encoded(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _signed_mandate() -> tuple[SignedMandate, ExpectedMandateScope, str, datetime]:
    now = datetime(2026, 8, 28, 12, tzinfo=UTC)
    data = RecoveryMandateData(
        protocol_version="recovery.mandate.v1",
        mandate_id="mandate-1",
        nonce="nonce-1",
        signer_key_id="customer-key-1",
        task_id="task-1",
        merchant_id="merchant-1",
        case_id="case-1",
        customer_id="customer-1",
        exact_amount_paise=149_900,
        currency="INR",
        payment_surface_type="SUBSCRIPTION_INVOICE_LINK",
        payment_surface_reference="inv-1",
        authorized_action="OPEN_EXACT_PAYMENT_SURFACE",
        issued_at=now,
        expires_at=now + timedelta(minutes=10),
    )
    private_key = Ed25519PrivateKey.generate()
    public_key = _encoded(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    )
    envelope = SignedMandate(
        algorithm="Ed25519",
        data=data,
        signature=_encoded(private_key.sign(canonical_json(data))),
    )
    expected = ExpectedMandateScope.model_validate(
        data.model_dump(
            include={
                "task_id",
                "merchant_id",
                "case_id",
                "customer_id",
                "exact_amount_paise",
                "currency",
                "payment_surface_type",
                "payment_surface_reference",
            }
        )
    )
    return envelope, expected, public_key, now


@pytest.mark.asyncio
async def test_customer_agent_timeout_opens_structured_fallback() -> None:
    async def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("customer agent did not answer", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as client:
        adapter = A2ACustomerAgentClient(
            origin="https://customer-agent.example",
            client=client,
            timeout_seconds=0.01,
        )
        request = CustomerAgentRecoveryRequest(
            idempotency_key="case-1:a2a:1",
            merchant_id="merchant-1",
            case_id="case-1",
            customer_id="customer-1",
            exact_amount_paise=149_900,
            currency="INR",
            payment_surface_type="SUBSCRIPTION_INVOICE_LINK",
            payment_surface_reference="inv-1",
            expires_at=datetime(2026, 8, 28, 12, 10, tzinfo=UTC),
            context={
                "merchant_display_name": "FitBox",
                "plan_name": "FitBox Annual",
                "failure_explanation": "Authentication was not completed.",
            },
        )
        with pytest.raises(httpx.ReadTimeout):
            await adapter.send_recovery_request(request)

    breaker = CircuitBreaker(
        provider="customer_agent", operation="send_recovery", failure_threshold=1
    )
    fallback = breaker.record_failure(FailureKind.RETRYABLE)
    assert fallback is not None
    assert fallback.code == "CUSTOMER_AGENT_SEND_RECOVERY_CIRCUIT_OPEN"
    assert not breaker.before_call().allowed


@pytest.mark.asyncio
async def test_invalid_and_expired_mandates_never_consume_nonce() -> None:
    envelope, expected, public_key, now = _signed_mandate()
    store = InMemoryNonceStore()
    verifier = MandateVerifier(pinned_public_keys={"customer-key-1": public_key}, nonce_store=store)
    wrong_scope = expected.model_copy(update={"exact_amount_paise": 149_901})
    with pytest.raises(MandateVerificationError) as mismatch:
        await verifier.verify_and_consume(envelope, expected=wrong_scope, now=now)
    assert mismatch.value.code == "SCOPE_MISMATCH"

    with pytest.raises(MandateVerificationError) as expired:
        await verifier.verify_and_consume(
            envelope, expected=expected, now=now + timedelta(minutes=11)
        )
    assert expired.value.code == "EXPIRED"

    verified = await verifier.verify_and_consume(envelope, expected=expected, now=now)
    assert verified.data.mandate_id == "mandate-1"
