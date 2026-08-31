from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from services.api.app.domain.enums import PaymentSurfaceType
from services.api.app.integrations.razorpay.client import RazorpayClient, RazorpayConfig
from services.api.app.integrations.razorpay.errors import (
    RazorpayContractError,
    RazorpayRequestError,
    RazorpayUncertainSubmissionError,
)
from services.api.app.providers.contracts import OpenPaymentSurfaceRequest
from services.api.app.reliability.registry import CircuitBreakerRegistry


def _client(handler: Any) -> RazorpayClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport, base_url="https://api.razorpay.test")
    return RazorpayClient(
        RazorpayConfig(
            key_id="rzp_test_key",
            key_secret="test_secret",
            checkout_origin="https://recovery.test",
            base_url="https://api.razorpay.test",
        ),
        client=http_client,
        breaker_registry=CircuitBreakerRegistry(),
    )


async def test_reference_lookup_distinguishes_found_absent_and_malformed() -> None:
    responses = [
        {
            "payment_links": [
                {
                    "id": "plink_existing",
                    "reference_id": "rec_stable",
                    "short_url": "https://rzp.test/i/existing",
                    "expire_by": 1_788_082_800,
                }
            ]
        },
        {"payment_links": []},
        {"count": 0},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.params["reference_id"] == "rec_stable"
        return httpx.Response(200, json=responses.pop(0))

    client = _client(handler)
    found = await client.reconcile_payment_link_by_reference(reference_id="rec_stable")
    absent = await client.reconcile_payment_link_by_reference(reference_id="rec_stable")
    with pytest.raises(RazorpayContractError) as caught:
        await client.reconcile_payment_link_by_reference(reference_id="rec_stable")

    assert found is not None
    assert found.provider_reference == "plink_existing"
    assert found.customer_url == "https://rzp.test/i/existing"
    assert absent is None
    assert caught.value.code == "RAZORPAY_PAYMENT_LINK_COLLECTION_INVALID"
    await client._client.aclose()  # noqa: SLF001 - injected test client


@pytest.mark.parametrize(
    ("provider_status", "expected"),
    [
        ("cancelled", "ALREADY_INACTIVE"),
        ("expired", "ALREADY_INACTIVE"),
        ("paid", "PAYMENT_PRESENT"),
        ("partially_paid", "PAYMENT_PRESENT"),
    ],
)
async def test_revoke_converges_terminal_provider_states(
    provider_status: str, expected: str
) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        return httpx.Response(200, json={"id": "plink_existing", "status": provider_status})

    client = _client(handler)
    result = await client.revoke_standard_payment_link(provider_reference="plink_existing")

    assert result == expected
    assert calls == ["GET /v1/payment_links/plink_existing"]
    await client._client.aclose()  # noqa: SLF001


async def test_revoke_cancels_only_a_created_link() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        if request.method == "GET":
            return httpx.Response(200, json={"id": "plink_existing", "status": "created"})
        return httpx.Response(200, json={"id": "plink_existing", "status": "cancelled"})

    client = _client(handler)
    result = await client.revoke_standard_payment_link(provider_reference="plink_existing")

    assert result == "CANCELLED"
    assert calls == [
        "GET /v1/payment_links/plink_existing",
        "POST /v1/payment_links/plink_existing/cancel",
    ]
    await client._client.aclose()  # noqa: SLF001


async def test_revoke_refetches_a_payment_race_instead_of_masking_it() -> None:
    responses = [
        httpx.Response(200, json={"id": "plink_existing", "status": "created"}),
        httpx.Response(400, json={"error": {"code": "BAD_REQUEST_ERROR"}}),
        httpx.Response(200, json={"id": "plink_existing", "status": "paid"}),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return responses.pop(0)

    client = _client(handler)
    result = await client.revoke_standard_payment_link(provider_reference="plink_existing")

    assert result == "PAYMENT_PRESENT"
    assert responses == []
    await client._client.aclose()  # noqa: SLF001


async def test_uncertain_create_requires_reference_lookup_before_retry() -> None:
    create_attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal create_attempts
        if request.url.path == "/v1/subscriptions/sub_test":
            return httpx.Response(200, json={"status": "halted"})
        if request.method == "GET" and request.url.path == "/v1/payment_links":
            assert request.url.params["reference_id"] == "rec_initial_uncertain"
            return httpx.Response(200, json={"payment_links": []})
        create_attempts += 1
        if create_attempts == 1:
            raise httpx.ReadTimeout("unknown create outcome", request=request)
        return httpx.Response(
            200,
            json={"id": "plink_after_lookup", "short_url": "https://rzp.test/i/retried"},
        )

    request = OpenPaymentSurfaceRequest(
        idempotency_key="case:initial-uncertain:surface:v1",
        case_id="case_initial_uncertain",
        merchant_id="merchant_test",
        customer_id="customer_test",
        subscription_id="sub_test",
        failed_invoice_id="inv_test",
        surface_type=PaymentSurfaceType.STANDARD_PAYMENT_LINK,
        exact_amount_paise=10_000,
        currency="INR",
        recovery_deadline=datetime(2026, 8, 30, tzinfo=UTC),
        expires_at=datetime(2026, 8, 30, tzinfo=UTC),
        reference_id="rec_initial_uncertain",
        notes={"case_id": "case_initial_uncertain", "invoice_id": "inv_test"},
    )
    client = _client(handler)

    with pytest.raises(RazorpayUncertainSubmissionError):
        await client.open_customer_payment_surface(request)
    assert create_attempts == 1
    assert (
        await client.reconcile_payment_link_by_reference(reference_id="rec_initial_uncertain")
        is None
    )
    result = await client.open_customer_payment_surface(request)

    assert result.provider_reference == "plink_after_lookup"
    assert create_attempts == 2
    await client._client.aclose()  # noqa: SLF001


@pytest.mark.parametrize(
    "ambiguous_response",
    [
        httpx.Response(503, json={"error": {"code": "SERVER_ERROR"}}),
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json=[{"id": "plink_unusable"}]),
        httpx.Response(200, json={"id": "plink_missing_url"}),
        httpx.Response(
            200,
            json={"id": "plink_insecure", "short_url": "http://unsafe.example/link"},
        ),
    ],
    ids=[
        "server-5xx",
        "invalid-json-2xx",
        "non-object-2xx",
        "incomplete-object-2xx",
        "insecure-url-2xx",
    ],
)
async def test_ambiguous_create_responses_require_reference_reconciliation(
    ambiguous_response: httpx.Response,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"status": "halted"})
        return ambiguous_response

    client = _client(handler)
    with pytest.raises(RazorpayUncertainSubmissionError) as caught:
        await client.open_customer_payment_surface(
            OpenPaymentSurfaceRequest(
                idempotency_key="case:ambiguous:surface:v1",
                case_id="case_ambiguous",
                merchant_id="merchant_test",
                customer_id="customer_test",
                subscription_id="sub_test",
                failed_invoice_id="inv_test",
                surface_type=PaymentSurfaceType.STANDARD_PAYMENT_LINK,
                exact_amount_paise=10_000,
                currency="INR",
                recovery_deadline=datetime(2026, 8, 30, tzinfo=UTC),
                expires_at=datetime(2026, 8, 30, tzinfo=UTC),
                reference_id="rec_ambiguous",
                notes={"case_id": "case_ambiguous", "invoice_id": "inv_test"},
            )
        )

    assert caught.value.metadata == {"reference_id": "rec_ambiguous"}
    assert client._payment_link_breaker.uncertain_submission is True  # noqa: SLF001
    await client._client.aclose()  # noqa: SLF001


async def test_definite_create_4xx_remains_a_provider_rejection() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"status": "halted"})
        return httpx.Response(400, json={"error": {"code": "BAD_REQUEST_ERROR"}})

    client = _client(handler)
    with pytest.raises(RazorpayRequestError) as caught:
        await client.open_customer_payment_surface(
            OpenPaymentSurfaceRequest(
                idempotency_key="case:definite-rejection:surface:v1",
                case_id="case_definite_rejection",
                merchant_id="merchant_test",
                customer_id="customer_test",
                subscription_id="sub_test",
                failed_invoice_id="inv_test",
                surface_type=PaymentSurfaceType.STANDARD_PAYMENT_LINK,
                exact_amount_paise=10_000,
                currency="INR",
                recovery_deadline=datetime(2026, 8, 30, tzinfo=UTC),
                expires_at=datetime(2026, 8, 30, tzinfo=UTC),
                reference_id="rec_definite_rejection",
                notes={
                    "case_id": "case_definite_rejection",
                    "invoice_id": "inv_test",
                },
            )
        )

    assert caught.value.status_code == 400
    assert client._payment_link_breaker.uncertain_submission is False  # noqa: SLF001
    await client._client.aclose()  # noqa: SLF001
