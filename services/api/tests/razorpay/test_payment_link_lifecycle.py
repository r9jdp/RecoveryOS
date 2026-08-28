from __future__ import annotations

from typing import Any

import httpx
import pytest

from services.api.app.integrations.razorpay.client import RazorpayClient, RazorpayConfig
from services.api.app.integrations.razorpay.errors import RazorpayContractError


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
