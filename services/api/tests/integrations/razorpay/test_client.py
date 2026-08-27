import json
from datetime import UTC, datetime
from typing import Any, cast

import httpx
import pytest

from services.api.app.domain.enums import PaymentState, PaymentSurfaceType, SubscriptionState
from services.api.app.integrations.razorpay.client import (
    RazorpayClient,
    RazorpayConfig,
    build_reference_id,
)
from services.api.app.integrations.razorpay.errors import (
    RazorpayContractError,
    RazorpayUncertainSubmissionError,
)
from services.api.app.integrations.razorpay.normalizer import normalize_webhook
from services.api.app.integrations.razorpay.reconciliation import reconcile_payment_success
from services.api.app.providers.contracts import OpenPaymentSurfaceRequest

DEADLINE = datetime(2026, 8, 30, 10, 0, tzinfo=UTC)


def _request(surface: PaymentSurfaceType, **updates: Any) -> OpenPaymentSurfaceRequest:
    values: dict[str, Any] = {
        "idempotency_key": "case:case_fitbox_aug_2026:surface:v1",
        "case_id": "case_fitbox_aug_2026",
        "merchant_id": "merchant_fitbox",
        "customer_id": "cust_fitbox_001",
        "subscription_id": "sub_fitbox_annual_001",
        "failed_invoice_id": "inv_fitbox_aug_2026",
        "surface_type": surface,
        "exact_amount_paise": 149_900,
        "currency": "INR",
        "recovery_deadline": DEADLINE,
    }
    values.update(updates)
    return OpenPaymentSurfaceRequest.model_validate(values)


def _config() -> RazorpayConfig:
    return RazorpayConfig(
        key_id="rzp_test_key",
        key_secret="test_secret",
        checkout_origin="https://staging.recovery.test",
        base_url="https://api.razorpay.test",
    )


def _client(handler: Any) -> RazorpayClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport, base_url="https://api.razorpay.test")
    return RazorpayClient(_config(), client=http_client)


async def test_card_update_checkout_contains_no_secret_and_opens_local_surface() -> None:
    client = _client(lambda request: pytest.fail(f"unexpected HTTP call: {request.url}"))
    request = _request(PaymentSurfaceType.SUBSCRIPTION_CARD_UPDATE)
    checkout = client.build_subscription_card_update_checkout(request)
    result = await client.open_customer_payment_surface(request)
    assert checkout == {
        "key": "rzp_test_key",
        "subscription_id": "sub_fitbox_annual_001",
        "subscription_card_change": True,
        "name": "RecoveryOS merchant checkout",
        "description": "Update the card used for this subscription",
    }
    assert "test_secret" not in str(checkout)
    assert result.customer_url.startswith("https://staging.recovery.test/")
    assert "key_id=rzp_test_key" in result.customer_url
    assert "subscription_id=sub_fitbox_annual_001" in result.customer_url
    assert "test_secret" not in result.customer_url
    await client._client.aclose()  # noqa: SLF001 - injected test client


async def test_exact_unpaid_invoice_short_url_is_selected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["subscription_id"] == "sub_fitbox_annual_001"
        return httpx.Response(
            200,
            json={
                "items": [
                    {"id": "inv_old", "status": "paid", "short_url": "https://wrong"},
                    {
                        "id": "inv_fitbox_aug_2026",
                        "status": "issued",
                        "short_url": "https://rzp.test/i/right",
                    },
                ]
            },
        )

    client = _client(handler)
    result = await client.open_customer_payment_surface(
        _request(PaymentSurfaceType.SUBSCRIPTION_INVOICE_LINK)
    )
    assert result.customer_url == "https://rzp.test/i/right"
    assert result.authoritative is True
    await client._client.aclose()  # noqa: SLF001


async def test_pending_subscription_blocks_standalone_payment_link() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json={"id": "sub_fitbox_annual_001", "status": "pending"})

    client = _client(handler)
    reference_id = build_reference_id(case_id="case_fitbox_aug_2026", idempotency_key="one")
    with pytest.raises(RazorpayContractError) as caught:
        await client.open_customer_payment_surface(
            _request(
                PaymentSurfaceType.STANDARD_PAYMENT_LINK,
                expires_at=DEADLINE,
                reference_id=reference_id,
                notes={
                    "case_id": "case_fitbox_aug_2026",
                    "invoice_id": "inv_fitbox_aug_2026",
                },
            )
        )
    assert caught.value.code == "RAZORPAY_STANDARD_LINK_REQUIRES_HALTED_SUBSCRIPTION"
    assert calls == ["/v1/subscriptions/sub_fitbox_annual_001"]
    await client._client.aclose()  # noqa: SLF001


async def test_payment_link_payload_has_all_safeguards() -> None:
    captured_body: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"status": "halted"})
        decoded = json.loads(request.content)
        captured_body.update(cast(dict[str, Any], decoded))
        return httpx.Response(
            200,
            json={"id": "plink_safe", "short_url": "https://rzp.test/i/safe"},
        )

    reference_id = build_reference_id(
        case_id="case_fitbox_aug_2026", idempotency_key="stable-idempotency-key"
    )
    assert len(reference_id) <= 40
    client = _client(handler)
    result = await client.open_customer_payment_surface(
        _request(
            PaymentSurfaceType.STANDARD_PAYMENT_LINK,
            expires_at=DEADLINE,
            reference_id=reference_id,
            notes={
                "case_id": "case_fitbox_aug_2026",
                "invoice_id": "inv_fitbox_aug_2026",
                "subscription_id": "sub_fitbox_annual_001",
            },
        )
    )
    assert result.customer_url == "https://rzp.test/i/safe"
    assert captured_body["amount"] == 149_900
    assert captured_body["accept_partial"] is False
    assert captured_body["notify"] == {"sms": False, "email": False}
    assert captured_body["reminder_enable"] is False
    assert captured_body["expire_by"] <= int(DEADLINE.timestamp())
    assert captured_body["reference_id"] == reference_id
    await client._client.aclose()  # noqa: SLF001


async def test_uncertain_create_is_not_blindly_retried() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"status": "halted"})
        raise httpx.ReadTimeout("unknown provider outcome", request=request)

    client = _client(handler)
    reference_id = build_reference_id(case_id="case", idempotency_key="uncertain")
    with pytest.raises(RazorpayUncertainSubmissionError) as caught:
        await client.open_customer_payment_surface(
            _request(
                PaymentSurfaceType.STANDARD_PAYMENT_LINK,
                expires_at=DEADLINE,
                reference_id=reference_id,
                notes={
                    "case_id": "case_fitbox_aug_2026",
                    "invoice_id": "inv_fitbox_aug_2026",
                },
            )
        )
    assert caught.value.metadata == {"reference_id": reference_id}
    await client._client.aclose()  # noqa: SLF001


async def test_authoritative_fetch_and_late_success_keep_lifecycle_axes_separate() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/invoices/inv_fitbox_aug_2026":
            return httpx.Response(
                200,
                json={
                    "id": "inv_fitbox_aug_2026",
                    "payment_id": "pay_success",
                    "subscription_id": "sub_fitbox_annual_001",
                    "amount": 149_900,
                    "currency": "INR",
                },
            )
        if request.url.path == "/v1/payments/pay_success":
            return httpx.Response(
                200,
                json={"id": "pay_success", "status": "captured", "amount": 149_900},
            )
        return httpx.Response(200, json={"status": "halted"})

    client = _client(handler)
    snapshot = await client.fetch_payment_snapshot(
        merchant_id="merchant_fitbox", payment_id=None, invoice_id="inv_fitbox_aug_2026"
    )
    event = normalize_webhook(
        provider_event_id="evt_late",
        payload={
            "event": "payment.captured",
            "created_at": 1787826002,
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_success",
                        "invoice_id": "inv_fitbox_aug_2026",
                        "amount": 149900,
                        "currency": "INR",
                        "created_at": 1787826000,
                    }
                }
            },
        },
    )
    outcome = reconcile_payment_success(
        event=event, snapshot=snapshot, current_payment_state=PaymentState.FAILED
    )
    assert snapshot.payment_state == PaymentState.CAPTURED
    assert snapshot.subscription_state == SubscriptionState.HALTED
    assert outcome.arrears_collected is True
    assert outcome.subscription_reactivated is False
    assert outcome.late_success is True
    assert outcome.should_close_case is True
    await client._client.aclose()  # noqa: SLF001
