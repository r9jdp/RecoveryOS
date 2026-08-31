"""Razorpay adapter reads bounded subscription onboarding state in Test mode."""

from __future__ import annotations

import httpx
import pytest

from services.api.app.integrations.razorpay.client import RazorpayClient, RazorpayConfig
from services.api.app.integrations.razorpay.errors import RazorpayContractError


async def test_fetch_test_subscription_onboarding_bundle_reads_exact_provider_scope() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        assert request.headers["Authorization"].startswith("Basic ")
        if request.url.path == "/v1/subscriptions/sub_test_real_001":
            return httpx.Response(
                200,
                json={
                    "id": "sub_test_real_001",
                    "plan_id": "plan_test_real_001",
                    "status": "created",
                },
            )
        if request.url.path == "/v1/plans/plan_test_real_001":
            return httpx.Response(
                200,
                json={
                    "id": "plan_test_real_001",
                    "item": {"name": "Gold", "amount": 99_900, "currency": "INR"},
                },
            )
        assert request.url.path == "/v1/invoices"
        assert request.url.params["subscription_id"] == "sub_test_real_001"
        assert request.url.params["count"] == "100"
        assert request.url.params["skip"] == "0"
        assert set(request.url.params) == {"subscription_id", "count", "skip"}
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "inv_test_real_001",
                        "subscription_id": "sub_test_real_001",
                    }
                ]
            },
        )

    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.razorpay.test"
    )
    client = RazorpayClient(
        RazorpayConfig(
            key_id="rzp_test_real",
            key_secret="server-secret",
            checkout_origin="https://recovery.test",
            base_url="https://api.razorpay.test",
        ),
        client=http_client,
    )
    bundle = await client.fetch_test_subscription_onboarding_bundle(
        subscription_id="sub_test_real_001"
    )

    assert bundle.subscription["id"] == "sub_test_real_001"
    assert bundle.plan["id"] == "plan_test_real_001"
    assert bundle.invoices[0]["id"] == "inv_test_real_001"
    assert paths == [
        "/v1/subscriptions/sub_test_real_001",
        "/v1/plans/plan_test_real_001",
        "/v1/invoices",
    ]
    await http_client.aclose()


async def test_onboarding_client_rejects_live_credentials_before_network() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail(f"unexpected provider request: {request.url}")

    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.razorpay.test"
    )
    client = RazorpayClient(
        RazorpayConfig(
            key_id="rzp_live_forbidden",
            key_secret="server-secret",
            checkout_origin="https://recovery.test",
            base_url="https://api.razorpay.test",
        ),
        client=http_client,
    )
    with pytest.raises(RazorpayContractError, match="test-mode credentials") as raised:
        await client.fetch_test_subscription_onboarding_bundle(subscription_id="sub_test_real_001")
    assert raised.value.code == "RAZORPAY_TEST_MODE_REQUIRED"
    await http_client.aclose()


async def test_onboarding_client_paginates_all_subscription_invoices() -> None:
    invoice_pages: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/subscriptions/sub_test_real_001":
            return httpx.Response(
                200,
                json={"id": "sub_test_real_001", "plan_id": "plan_test_real_001"},
            )
        if request.url.path == "/v1/plans/plan_test_real_001":
            return httpx.Response(200, json={"id": "plan_test_real_001"})
        skip = request.url.params["skip"]
        count = request.url.params["count"]
        invoice_pages.append((count, skip))
        start = int(skip)
        page_size = 100 if start == 0 else 1
        return httpx.Response(
            200,
            json={
                "items": [
                    {"id": f"inv_{index:04d}"}
                    for index in range(start, start + page_size)
                ]
            },
        )

    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.razorpay.test"
    )
    client = RazorpayClient(
        RazorpayConfig(
            key_id="rzp_test_real",
            key_secret="server-secret",
            checkout_origin="https://recovery.test",
            base_url="https://api.razorpay.test",
        ),
        client=http_client,
    )

    bundle = await client.fetch_test_subscription_onboarding_bundle(
        subscription_id="sub_test_real_001"
    )

    assert len(bundle.invoices) == 101
    assert invoice_pages == [("100", "0"), ("100", "100")]
    await http_client.aclose()
