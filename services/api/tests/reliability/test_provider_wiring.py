from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from services.api.app.domain.enums import PaymentState, PaymentSurfaceType
from services.api.app.integrations.razorpay.client import RazorpayClient, RazorpayConfig
from services.api.app.integrations.razorpay.errors import (
    RazorpayRequestError,
    RazorpayUncertainSubmissionError,
)
from services.api.app.integrations.voice.twilio import TwilioConfig, TwilioVoiceProvider
from services.api.app.providers.contracts import OpenPaymentSurfaceRequest, VoiceContactRequest
from services.api.app.reliability.registry import CircuitBreakerRegistry
from services.api.app.voice.service import DisabledVoiceProvider

DEADLINE = datetime(2026, 8, 30, 12, tzinfo=UTC)


def _payment_request() -> OpenPaymentSurfaceRequest:
    return OpenPaymentSurfaceRequest(
        idempotency_key="case-1:surface:1",
        case_id="case-1",
        merchant_id="merchant-1",
        customer_id="customer-1",
        subscription_id="subscription-1",
        failed_invoice_id="invoice-1",
        surface_type=PaymentSurfaceType.STANDARD_PAYMENT_LINK,
        exact_amount_paise=149_900,
        currency="INR",
        recovery_deadline=DEADLINE,
        expires_at=DEADLINE,
        reference_id="case-1-payment-link",
        notes={"case_id": "case-1", "invoice_id": "invoice-1"},
    )


def _razorpay(
    handler: Any, registry: CircuitBreakerRegistry
) -> tuple[RazorpayClient, httpx.AsyncClient]:
    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.razorpay.test"
    )
    adapter = RazorpayClient(
        RazorpayConfig(
            key_id="rzp_test_shared_scope",
            key_secret="secret",
            checkout_origin="https://recovery.example",
            base_url="https://api.razorpay.test",
        ),
        client=http_client,
        breaker_registry=registry,
    )
    return adapter, http_client


@pytest.mark.asyncio
async def test_razorpay_create_breaker_survives_adapter_rebuild_and_allows_reads() -> None:
    registry = CircuitBreakerRegistry()

    def uncertain_handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"status": "halted"})
        raise httpx.ReadTimeout("unknown create outcome", request=request)

    first, first_http = _razorpay(uncertain_handler, registry)
    with pytest.raises(RazorpayUncertainSubmissionError):
        await first.open_customer_payment_surface(_payment_request())
    await first_http.aclose()

    calls: list[tuple[str, str]] = []

    def recovery_handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path == "/v1/subscriptions/subscription-1":
            return httpx.Response(200, json={"status": "halted"})
        if request.url.path == "/v1/invoices/invoice-1":
            return httpx.Response(
                200,
                json={"id": "invoice-1", "amount": 149_900, "currency": "INR"},
            )
        if request.url.path == "/v1/payment_links" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "payment_links": [
                        {
                            "id": "plink-existing",
                            "reference_id": "case-1-payment-link",
                            "short_url": "https://rzp.test/i/existing",
                        }
                    ]
                },
            )
        if request.url.path == "/v1/payment_links" and request.method == "POST":
            return httpx.Response(
                200,
                json={"id": "plink-new", "short_url": "https://rzp.test/i/new"},
            )
        raise AssertionError(f"unexpected Razorpay request: {request.method} {request.url}")

    rebuilt, rebuilt_http = _razorpay(recovery_handler, registry)
    with pytest.raises(RazorpayRequestError) as blocked:
        await rebuilt.open_customer_payment_surface(_payment_request())
    assert (
        blocked.value.code == "RAZORPAY_CREATE_PAYMENT_LINK_SUBMISSION_UNCERTAIN_RECONCILE_REQUIRED"
    )
    assert blocked.value.metadata["requires_reconciliation"] is True
    assert blocked.value.retriable is False

    snapshot = await rebuilt.fetch_payment_snapshot(
        merchant_id="merchant-1", payment_id=None, invoice_id="invoice-1"
    )
    assert snapshot.authoritative
    assert snapshot.payment_state == PaymentState.UNKNOWN

    reconciled = await rebuilt.reconcile_payment_link_by_reference(
        reference_id="case-1-payment-link"
    )
    assert reconciled is not None and reconciled["id"] == "plink-existing"
    created = await rebuilt.open_customer_payment_surface(_payment_request())
    assert created.provider_reference == "plink-new"
    assert calls.count(("POST", "/v1/payment_links")) == 1
    await rebuilt_http.aclose()


def _voice_request(attempt_id: str) -> VoiceContactRequest:
    return VoiceContactRequest(
        idempotency_key=attempt_id,
        case_id="case-1",
        customer_id="customer-1",
        destination_token="+919999999999",
        preferred_language="hi-IN",
        consent_verified_at=datetime(2026, 8, 1, tzinfo=UTC),
        max_duration_seconds=180,
        disclosure_text="I am an AI",
    )


@pytest.mark.asyncio
async def test_twilio_start_breaker_survives_adapter_rebuild_but_fetch_can_reconcile() -> None:
    registry = CircuitBreakerRegistry()

    def uncertain_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("unknown call submission", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(uncertain_handler)) as client:
        first = TwilioVoiceProvider(
            TwilioConfig("AC-shared", "secret", "+12025550100", "https://voice.example"),
            client,
            breaker_registry=registry,
        )
        uncertain = await first.start_contact(_voice_request("attempt-1"))
    assert uncertain.status == "UNCERTAIN"

    requests: list[httpx.Request] = []

    def recovered_handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"sid": "CA-known", "status": "completed"})
        return httpx.Response(201, json={"sid": "CA-new", "status": "queued"})

    async def persisted_call_sid(attempt_id: str) -> str | None:
        return "CA-known" if attempt_id == "attempt-1" else None

    async with httpx.AsyncClient(transport=httpx.MockTransport(recovered_handler)) as client:
        rebuilt = TwilioVoiceProvider(
            TwilioConfig("AC-shared", "secret", "+12025550100", "https://voice.example"),
            client,
            call_sid_resolver=persisted_call_sid,
            breaker_registry=registry,
        )
        blocked = await rebuilt.start_contact(_voice_request("attempt-2"))
        assert blocked.status == "UNCERTAIN"
        assert blocked.reason_code == "TWILIO_START_CONTACT_SUBMISSION_UNCERTAIN_RECONCILE_REQUIRED"
        assert requests == []

        snapshot = await rebuilt.fetch_contact(contact_attempt_id="attempt-1")
        assert snapshot.status == "COMPLETED"
        submitted = await rebuilt.start_contact(_voice_request("attempt-2"))
        assert submitted.status == "SUBMITTED"
        assert [request.method for request in requests] == ["GET", "POST"]


@pytest.mark.asyncio
async def test_mock_voice_provider_remains_fail_closed() -> None:
    result = await DisabledVoiceProvider().start_contact(_voice_request("attempt-mock"))
    assert result.status == "REJECTED"
    assert result.reason_code == "REAL_VOICE_PROVIDER_NOT_CONFIGURED"
