"""Minimal async Razorpay HTTP adapter built on the shared httpx dependency."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import urlencode

import httpx

from services.api.app.domain.enums import PaymentState, PaymentSurfaceType, SubscriptionState
from services.api.app.providers.contracts import (
    OpenPaymentSurfaceRequest,
    PaymentSnapshot,
    PaymentSurfaceResult,
)

from .errors import (
    RazorpayContractError,
    RazorpayRequestError,
    RazorpayUncertainSubmissionError,
)


@dataclass(frozen=True, slots=True)
class RazorpayConfig:
    key_id: str
    key_secret: str
    checkout_origin: str
    base_url: str = "https://api.razorpay.com"
    timeout_seconds: float = 4.0


def build_reference_id(*, case_id: str, idempotency_key: str) -> str:
    """Create a stable, unique provider reference within Razorpay's 40-char limit."""

    case_fragment = "".join(character for character in case_id if character.isalnum())[-18:]
    digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:16]
    return f"rc_{case_fragment}_{digest}"[:40]


def _as_object(value: Any, *, code: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RazorpayContractError(code, "Razorpay returned a non-object response.")
    return cast(dict[str, Any], value)


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _integer(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _payment_state(value: Any) -> PaymentState:
    mapping = {
        "failed": PaymentState.FAILED,
        "created": PaymentState.PENDING,
        "authorized": PaymentState.AUTHORIZED,
        "captured": PaymentState.CAPTURED,
        "refunded": PaymentState.REFUNDED,
    }
    return mapping.get(value, PaymentState.UNKNOWN)


def _subscription_state(value: Any) -> SubscriptionState:
    mapping = {state.value.lower(): state for state in SubscriptionState}
    return mapping.get(value, SubscriptionState.UNKNOWN)


class RazorpayClient:
    """Customer-surface and read-only reconciliation operations.

    There is deliberately no operation that charges or retries a failed payment
    identifier.  Razorpay owns automatic subscription retries.
    """

    def __init__(
        self,
        config: RazorpayConfig,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.config = config
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=config.base_url,
            timeout=config.timeout_seconds,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    @property
    def _auth(self) -> httpx.BasicAuth:
        return httpx.BasicAuth(self.config.key_id, self.config.key_secret)

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        uncertain_reference_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            response = await self._client.request(
                method,
                path,
                params=params,
                json=json,
                auth=self._auth,
                headers={"Accept": "application/json"},
            )
        except httpx.RequestError as error:
            if uncertain_reference_id is not None:
                raise RazorpayUncertainSubmissionError(
                    reference_id=uncertain_reference_id
                ) from error
            raise RazorpayRequestError(
                "RAZORPAY_TRANSPORT_ERROR",
                "Razorpay could not be reached.",
                retriable=True,
            ) from error
        if response.is_error:
            try:
                body = response.json()
            except ValueError:
                body = {}
            error_body = body.get("error", {}) if isinstance(body, dict) else {}
            provider_code = error_body.get("code") if isinstance(error_body, dict) else None
            raise RazorpayRequestError(
                "RAZORPAY_API_ERROR",
                "Razorpay rejected the request.",
                status_code=response.status_code,
                retriable=response.status_code >= 500,
                metadata={"provider_code": provider_code},
            )
        try:
            return _as_object(response.json(), code="RAZORPAY_RESPONSE_INVALID")
        except ValueError as error:
            raise RazorpayContractError(
                "RAZORPAY_RESPONSE_INVALID", "Razorpay returned invalid JSON."
            ) from error

    def build_subscription_card_update_checkout(
        self, request: OpenPaymentSurfaceRequest
    ) -> dict[str, str | bool]:
        if request.surface_type != PaymentSurfaceType.SUBSCRIPTION_CARD_UPDATE:
            raise RazorpayContractError(
                "RAZORPAY_SURFACE_MISMATCH",
                "Card-update Checkout options require SUBSCRIPTION_CARD_UPDATE.",
            )
        return {
            "key": self.config.key_id,
            "subscription_id": request.subscription_id,
            "subscription_card_change": True,
            "name": "RecoveryOS merchant checkout",
            "description": "Update the card used for this subscription",
        }

    async def _open_card_update(self, request: OpenPaymentSurfaceRequest) -> PaymentSurfaceResult:
        self.build_subscription_card_update_checkout(request)
        query = urlencode({"case_id": request.case_id, "subscription_id": request.subscription_id})
        customer_url = (
            f"{self.config.checkout_origin.rstrip('/')}/payments/razorpay/card-update?{query}"
        )
        return PaymentSurfaceResult(
            provider="razorpay",
            provider_reference=request.subscription_id,
            surface_type=request.surface_type,
            customer_url=customer_url,
            expires_at=request.recovery_deadline,
            authoritative=False,
        )

    async def _open_invoice_link(self, request: OpenPaymentSurfaceRequest) -> PaymentSurfaceResult:
        collection = await self._request_json(
            "GET", "/v1/invoices", params={"subscription_id": request.subscription_id}
        )
        items = collection.get("items")
        if not isinstance(items, list):
            raise RazorpayContractError(
                "RAZORPAY_INVOICE_COLLECTION_INVALID",
                "Razorpay invoice collection has no items array.",
            )
        matching = next(
            (
                item
                for item in items
                if isinstance(item, dict)
                and item.get("id") == request.failed_invoice_id
                and item.get("status") not in {"paid", "cancelled"}
            ),
            None,
        )
        if not isinstance(matching, dict) or not _text(matching.get("short_url")):
            raise RazorpayContractError(
                "RAZORPAY_UNPAID_INVOICE_LINK_NOT_FOUND",
                "The exact failed invoice has no payable short_url.",
                invoice_id=request.failed_invoice_id,
            )
        return PaymentSurfaceResult(
            provider="razorpay",
            provider_reference=request.failed_invoice_id,
            surface_type=request.surface_type,
            customer_url=cast(str, matching["short_url"]),
            expires_at=request.recovery_deadline,
            authoritative=True,
        )

    async def _open_standard_payment_link(
        self, request: OpenPaymentSurfaceRequest
    ) -> PaymentSurfaceResult:
        subscription = await self._request_json(
            "GET", f"/v1/subscriptions/{request.subscription_id}"
        )
        if subscription.get("status") != "halted":
            raise RazorpayContractError(
                "RAZORPAY_STANDARD_LINK_REQUIRES_HALTED_SUBSCRIPTION",
                "A standalone Payment Link is allowed only for a halted subscription.",
                subscription_id=request.subscription_id,
                subscription_status=subscription.get("status"),
            )
        if request.expires_at is None or request.reference_id is None:
            raise RazorpayContractError(
                "RAZORPAY_PAYMENT_LINK_CONTRACT_INVALID",
                "A standalone Payment Link requires expiry and reference_id.",
            )
        expires_at = min(request.expires_at, request.recovery_deadline)
        body: dict[str, Any] = {
            "amount": request.exact_amount_paise,
            "currency": request.currency,
            "accept_partial": False,
            "expire_by": int(expires_at.timestamp()),
            "reference_id": request.reference_id,
            "description": f"Recovery for invoice {request.failed_invoice_id}",
            "notify": {"sms": False, "email": False},
            "reminder_enable": False,
            "notes": request.notes,
        }
        if request.callback_url:
            body["callback_url"] = request.callback_url
            body["callback_method"] = "get"
        link = await self._request_json(
            "POST",
            "/v1/payment_links",
            json=body,
            uncertain_reference_id=request.reference_id,
        )
        link_id = _text(link.get("id"))
        short_url = _text(link.get("short_url"))
        if link_id is None or short_url is None:
            raise RazorpayContractError(
                "RAZORPAY_PAYMENT_LINK_RESPONSE_INVALID",
                "Created Payment Link has no id or short_url.",
            )
        return PaymentSurfaceResult(
            provider="razorpay",
            provider_reference=link_id,
            surface_type=request.surface_type,
            customer_url=short_url,
            expires_at=expires_at,
            authoritative=True,
        )

    async def open_customer_payment_surface(
        self, request: OpenPaymentSurfaceRequest
    ) -> PaymentSurfaceResult:
        if request.surface_type == PaymentSurfaceType.SUBSCRIPTION_CARD_UPDATE:
            return await self._open_card_update(request)
        if request.surface_type == PaymentSurfaceType.SUBSCRIPTION_INVOICE_LINK:
            return await self._open_invoice_link(request)
        if request.surface_type == PaymentSurfaceType.STANDARD_PAYMENT_LINK:
            return await self._open_standard_payment_link(request)
        raise RazorpayContractError(
            "RAZORPAY_SURFACE_UNSUPPORTED", "Unsupported payment surface type."
        )

    async def fetch_payment_snapshot(
        self, *, merchant_id: str, payment_id: str | None, invoice_id: str
    ) -> PaymentSnapshot:
        del merchant_id  # Credentials are selected by the coordinator's merchant-scoped factory.
        invoice = await self._request_json("GET", f"/v1/invoices/{invoice_id}")
        provider_payment_id = payment_id or _text(invoice.get("payment_id"))
        payment: dict[str, Any] = {}
        if provider_payment_id:
            payment = await self._request_json("GET", f"/v1/payments/{provider_payment_id}")
        subscription_id = _text(invoice.get("subscription_id"))
        subscription: dict[str, Any] = {}
        if subscription_id:
            subscription = await self._request_json("GET", f"/v1/subscriptions/{subscription_id}")
        amount = _integer(payment.get("amount"))
        if amount is None:
            amount = _integer(invoice.get("amount")) or 0
        currency = _text(payment.get("currency")) or _text(invoice.get("currency")) or "INR"
        return PaymentSnapshot(
            provider="razorpay",
            payment_id=provider_payment_id,
            invoice_id=invoice_id,
            subscription_id=subscription_id,
            payment_state=_payment_state(payment.get("status")),
            subscription_state=_subscription_state(subscription.get("status")),
            amount_paise=amount,
            currency=currency,
            observed_at=datetime.now(UTC),
            authoritative=True,
        )

    async def reconcile_payment_link_by_reference(
        self, *, reference_id: str
    ) -> dict[str, Any] | None:
        """Resolve an uncertain create before an activity decides whether to resubmit."""

        collection = await self._request_json(
            "GET", "/v1/payment_links", params={"reference_id": reference_id}
        )
        items = collection.get("payment_links", collection.get("items"))
        if not isinstance(items, list):
            return None
        return next(
            (
                cast(dict[str, Any], item)
                for item in items
                if isinstance(item, dict) and item.get("reference_id") == reference_id
            ),
            None,
        )
