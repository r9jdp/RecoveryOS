"""Minimal async Razorpay HTTP adapter built on the shared httpx dependency."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, cast
from urllib.parse import urlencode, urlsplit

import httpx

from services.api.app.domain.enums import PaymentState, PaymentSurfaceType, SubscriptionState
from services.api.app.providers.contracts import (
    InvoiceSnapshot,
    OpenPaymentSurfaceRequest,
    PaymentSnapshot,
    PaymentSurfaceResult,
)
from services.api.app.reliability.circuit_breaker import FailureKind, FallbackReason
from services.api.app.reliability.registry import (
    CircuitBreakerRegistry,
    provider_breaker_registry,
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


@dataclass(frozen=True, slots=True)
class RazorpaySubscriptionOnboardingBundle:
    """Read-only provider state used to establish local webhook correlation."""

    subscription: dict[str, Any]
    plan: dict[str, Any]
    invoices: tuple[dict[str, Any], ...]


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


def _provider_https_url(value: Any, *, code: str) -> str:
    if not isinstance(value, str) or len(value) > 2_048:
        raise RazorpayContractError(code, "Razorpay returned an invalid customer URL.")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise RazorpayContractError(code, "Razorpay customer URLs must use HTTPS.")
    return value


def _checkout_origin(value: str) -> str:
    parsed = urlsplit(value)
    is_local_http = parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}
    if (
        (parsed.scheme != "https" and not is_local_http)
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise RazorpayContractError(
            "RAZORPAY_CHECKOUT_ORIGIN_INVALID",
            "Checkout origin must be HTTPS (localhost HTTP is allowed for development).",
        )
    return value.rstrip("/")


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


def _fallback_metadata(reason: FallbackReason) -> dict[str, Any]:
    return {
        "fallback_reason_code": reason.code,
        "provider": reason.provider,
        "operation": reason.operation,
        "circuit_state": reason.state.value,
        "failure_count": reason.failure_count,
        "retry_after_seconds": reason.retry_after_seconds,
        "requires_reconciliation": reason.requires_reconciliation,
        "automatic_retry_permitted": reason.automatic_retry_permitted,
    }


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
        breaker_registry: CircuitBreakerRegistry | None = None,
    ) -> None:
        self.config = config
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=config.base_url,
            timeout=config.timeout_seconds,
        )
        registry = breaker_registry or provider_breaker_registry()
        self._payment_link_breaker = registry.get(
            provider="razorpay",
            operation="create_payment_link",
            scope=config.key_id,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def fetch_test_subscription_onboarding_bundle(
        self, *, subscription_id: str
    ) -> RazorpaySubscriptionOnboardingBundle:
        """Fetch one test subscription and all of its current invoices.

        This method is intentionally read-only at Razorpay. Local onboarding is
        therefore safe to repeat, and an uncertain provider write can never be
        introduced by the sync endpoint.
        """

        if not self.config.key_id.startswith("rzp_test_"):
            raise RazorpayContractError(
                "RAZORPAY_TEST_MODE_REQUIRED",
                "Subscription onboarding accepts only Razorpay test-mode credentials.",
            )
        subscription = await self._request_json("GET", f"/v1/subscriptions/{subscription_id}")
        if subscription.get("id") != subscription_id:
            raise RazorpayContractError(
                "RAZORPAY_SUBSCRIPTION_RESPONSE_MISMATCH",
                "Razorpay returned a different subscription than requested.",
                requested_subscription_id=subscription_id,
            )
        plan_id = _text(subscription.get("plan_id"))
        if plan_id is None:
            raise RazorpayContractError(
                "RAZORPAY_SUBSCRIPTION_PLAN_MISSING",
                "Razorpay subscription has no plan_id.",
                subscription_id=subscription_id,
            )
        plan = await self._request_json("GET", f"/v1/plans/{plan_id}")
        if plan.get("id") != plan_id:
            raise RazorpayContractError(
                "RAZORPAY_PLAN_RESPONSE_MISMATCH",
                "Razorpay returned a different plan than requested.",
                requested_plan_id=plan_id,
            )

        invoices = await self._list_objects(
            "/v1/invoices",
            params={"subscription_id": subscription_id},
            collection_field="items",
            invalid_code="RAZORPAY_INVOICE_COLLECTION_INVALID",
            maximum_items=1_000,
        )
        return RazorpaySubscriptionOnboardingBundle(
            subscription=subscription,
            plan=plan,
            invoices=invoices,
        )

    async def fetch_invoice_snapshot(self, *, merchant_id: str, invoice_id: str) -> InvoiceSnapshot:
        """Fetch one invoice so a webhook can join an already connected subscription."""

        del merchant_id  # Credentials are selected by the merchant-scoped factory.
        if not invoice_id.startswith("inv_") or len(invoice_id) > 128:
            raise RazorpayContractError(
                "RAZORPAY_INVOICE_ID_INVALID",
                "A valid Razorpay invoice id is required for correlation.",
            )
        invoice = await self._request_json("GET", f"/v1/invoices/{invoice_id}")
        if invoice.get("id") != invoice_id:
            raise RazorpayContractError(
                "RAZORPAY_INVOICE_RESPONSE_MISMATCH",
                "Razorpay returned a different invoice than requested.",
                requested_invoice_id=invoice_id,
            )
        subscription_id = _text(invoice.get("subscription_id"))
        if (
            subscription_id is None
            or not subscription_id.startswith("sub_")
            or len(subscription_id) > 128
        ):
            raise RazorpayContractError(
                "RAZORPAY_INVOICE_SUBSCRIPTION_MISSING",
                "Razorpay invoice has no valid subscription id.",
                invoice_id=invoice_id,
            )
        amount_paise = _integer(invoice.get("amount"))
        amount_paid_paise = _integer(invoice.get("amount_paid"))
        if amount_paise is None or amount_paise < 0:
            raise RazorpayContractError(
                "RAZORPAY_INVOICE_AMOUNT_INVALID",
                "Razorpay invoice has no valid integer amount.",
                invoice_id=invoice_id,
            )
        if amount_paid_paise is None or amount_paid_paise < 0 or amount_paid_paise > amount_paise:
            raise RazorpayContractError(
                "RAZORPAY_INVOICE_AMOUNT_INVALID",
                "Razorpay invoice has an invalid amount_paid.",
                invoice_id=invoice_id,
            )
        currency = _text(invoice.get("currency"))
        if currency is None or len(currency) != 3:
            raise RazorpayContractError(
                "RAZORPAY_INVOICE_CURRENCY_INVALID",
                "Razorpay invoice has no valid currency.",
                invoice_id=invoice_id,
            )
        invoice_state = _text(invoice.get("status"))
        if invoice_state is None or len(invoice_state) > 32:
            raise RazorpayContractError(
                "RAZORPAY_INVOICE_STATE_INVALID",
                "Razorpay invoice has no valid status.",
                invoice_id=invoice_id,
            )
        due_at: datetime | None = None
        for field in ("expire_by", "billing_end"):
            timestamp = _integer(invoice.get(field))
            if timestamp is not None and timestamp >= 0:
                try:
                    due_at = datetime.fromtimestamp(timestamp, UTC)
                except (OSError, OverflowError, ValueError) as error:
                    raise RazorpayContractError(
                        "RAZORPAY_INVOICE_TIMESTAMP_INVALID",
                        "Razorpay invoice has an invalid due timestamp.",
                        invoice_id=invoice_id,
                    ) from error
                break
        return InvoiceSnapshot(
            provider="razorpay",
            invoice_id=invoice_id,
            subscription_id=subscription_id,
            amount_paise=amount_paise,
            amount_paid_paise=amount_paid_paise,
            currency=currency.upper(),
            invoice_state=invoice_state.lower(),
            due_at=due_at,
            observed_at=datetime.now(UTC),
            authoritative=True,
        )

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
            if uncertain_reference_id is not None and response.status_code >= 500:
                # The provider may have committed the write before its upstream
                # failed to produce a response.  Only a reference lookup can
                # distinguish an accepted create from a safe retry.
                raise RazorpayUncertainSubmissionError(reference_id=uncertain_reference_id)
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
        except (ValueError, RazorpayContractError) as error:
            if uncertain_reference_id is not None:
                # A successful HTTP status does not prove the create was absent.
                # Invalid JSON or a non-object body is therefore ambiguous.
                raise RazorpayUncertainSubmissionError(
                    reference_id=uncertain_reference_id
                ) from error
            raise RazorpayContractError(
                "RAZORPAY_RESPONSE_INVALID", "Razorpay returned invalid JSON."
            ) from error

    async def _list_objects(
        self,
        path: str,
        *,
        params: dict[str, str],
        collection_field: str,
        invalid_code: str,
        maximum_items: int,
    ) -> tuple[dict[str, Any], ...]:
        """Read a Razorpay collection completely, with an explicit safety bound."""

        items: list[dict[str, Any]] = []
        while len(items) <= maximum_items:
            page_size = min(100, maximum_items + 1 - len(items))
            collection = await self._request_json(
                "GET",
                path,
                params={
                    **params,
                    "count": str(page_size),
                    "skip": str(len(items)),
                },
            )
            page = collection.get(collection_field)
            if not isinstance(page, list):
                raise RazorpayContractError(
                    invalid_code,
                    f"Razorpay collection has no {collection_field} array.",
                )
            if len(page) > page_size or any(not isinstance(item, dict) for item in page):
                raise RazorpayContractError(
                    invalid_code,
                    "Razorpay collection returned an invalid page.",
                )
            items.extend(cast(list[dict[str, Any]], page))
            if len(items) > maximum_items:
                raise RazorpayContractError(
                    f"{invalid_code.removesuffix('_INVALID')}_TOO_LARGE",
                    "Razorpay collection exceeds the bounded read limit.",
                    maximum_items=maximum_items,
                )
            if len(page) < page_size:
                return tuple(items)
        raise AssertionError("bounded Razorpay collection read did not return")

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
        # The key id is designed to be exposed to Checkout. The secret remains
        # server-only. Keeping the exact subscription and case in the generated
        # URL makes the customer surface self-contained without trusting a
        # browser callback as proof of recovery.
        query = urlencode(
            {
                "case_id": request.case_id,
                "subscription_id": request.subscription_id,
                "key_id": self.config.key_id,
            }
        )
        customer_url = (
            f"{_checkout_origin(self.config.checkout_origin)}/payments/razorpay/card-update?{query}"
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
        invoice = await self._request_json("GET", f"/v1/invoices/{request.failed_invoice_id}")
        if (
            invoice.get("id") != request.failed_invoice_id
            or invoice.get("subscription_id") != request.subscription_id
        ):
            raise RazorpayContractError(
                "RAZORPAY_INVOICE_SCOPE_MISMATCH",
                "The requested invoice does not belong to the requested subscription.",
                invoice_id=request.failed_invoice_id,
                subscription_id=request.subscription_id,
            )
        if invoice.get("status") in {"paid", "cancelled"} or not _text(invoice.get("short_url")):
            raise RazorpayContractError(
                "RAZORPAY_UNPAID_INVOICE_LINK_NOT_FOUND",
                "The exact failed invoice has no payable short_url.",
                invoice_id=request.failed_invoice_id,
            )
        return PaymentSurfaceResult(
            provider="razorpay",
            provider_reference=request.failed_invoice_id,
            surface_type=request.surface_type,
            customer_url=_provider_https_url(
                invoice["short_url"], code="RAZORPAY_INVOICE_URL_INVALID"
            ),
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
        if len(request.notes) > 15 or any(
            not key or len(key) > 256 or len(value) > 256 for key, value in request.notes.items()
        ):
            raise RazorpayContractError(
                "RAZORPAY_PAYMENT_LINK_NOTES_INVALID",
                "Payment Link notes exceed Razorpay's bounded notes contract.",
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
        decision = self._payment_link_breaker.before_call()
        if not decision.allowed:
            reason = decision.reason
            if reason is None:  # pragma: no cover - defensive invariant
                raise RuntimeError("blocked circuit decision omitted its fallback reason")
            raise RazorpayRequestError(
                reason.code,
                "Razorpay Payment Link creation is temporarily blocked by provider safety.",
                status_code=503,
                retriable=reason.automatic_retry_permitted,
                metadata=_fallback_metadata(reason),
            )
        try:
            link = await self._request_json(
                "POST",
                "/v1/payment_links",
                json=body,
                uncertain_reference_id=request.reference_id,
            )
        except RazorpayUncertainSubmissionError:
            self._payment_link_breaker.record_failure(FailureKind.UNCERTAIN_SUBMISSION)
            raise
        except RazorpayRequestError as error:
            reason = self._payment_link_breaker.record_failure(
                FailureKind.RETRYABLE if error.retriable else FailureKind.PERMANENT
            )
            if reason is not None:
                error.metadata.update(_fallback_metadata(reason))
            raise
        link_id = _text(link.get("id"))
        short_url = _text(link.get("short_url"))
        if (
            link_id is None
            or not link_id.startswith("plink_")
            or len(link_id) > 128
            or short_url is None
        ):
            self._payment_link_breaker.record_failure(FailureKind.UNCERTAIN_SUBMISSION)
            raise RazorpayUncertainSubmissionError(
                reference_id=request.reference_id,
            )
        try:
            customer_url = _provider_https_url(short_url, code="RAZORPAY_PAYMENT_LINK_URL_INVALID")
        except RazorpayContractError as error:
            self._payment_link_breaker.record_failure(FailureKind.UNCERTAIN_SUBMISSION)
            raise RazorpayUncertainSubmissionError(
                reference_id=request.reference_id,
            ) from error
        self._payment_link_breaker.record_success()
        return PaymentSurfaceResult(
            provider="razorpay",
            provider_reference=link_id,
            surface_type=request.surface_type,
            customer_url=customer_url,
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
        if invoice.get("id") != invoice_id:
            raise RazorpayContractError(
                "RAZORPAY_INVOICE_RESPONSE_MISMATCH",
                "Razorpay returned a different invoice than requested.",
                requested_invoice_id=invoice_id,
            )
        provider_payment_id = payment_id or _text(invoice.get("payment_id"))
        payment: dict[str, Any] = {}
        if provider_payment_id:
            payment = await self._request_json("GET", f"/v1/payments/{provider_payment_id}")
            if payment.get("id") != provider_payment_id:
                raise RazorpayContractError(
                    "RAZORPAY_PAYMENT_RESPONSE_MISMATCH",
                    "Razorpay returned a different payment than requested.",
                    requested_payment_id=provider_payment_id,
                )
            payment_invoice_id = _text(payment.get("invoice_id"))
            if payment_invoice_id is not None and payment_invoice_id != invoice_id:
                raise RazorpayContractError(
                    "RAZORPAY_PAYMENT_INVOICE_MISMATCH",
                    "Razorpay payment belongs to a different invoice.",
                    requested_invoice_id=invoice_id,
                    payment_invoice_id=payment_invoice_id,
                )
        subscription_id = _text(invoice.get("subscription_id"))
        subscription: dict[str, Any] = {}
        if subscription_id:
            subscription = await self._request_json("GET", f"/v1/subscriptions/{subscription_id}")
            if subscription.get("id") != subscription_id:
                raise RazorpayContractError(
                    "RAZORPAY_SUBSCRIPTION_RESPONSE_MISMATCH",
                    "Razorpay returned a different subscription than requested.",
                    requested_subscription_id=subscription_id,
                )
        amount = _integer(payment.get("amount"))
        if amount is None:
            amount = _integer(invoice.get("amount"))
        if amount is None or amount < 0:
            raise RazorpayContractError(
                "RAZORPAY_PAYMENT_AMOUNT_INVALID",
                "Razorpay returned no valid integer payment amount.",
            )
        currency = _text(payment.get("currency")) or _text(invoice.get("currency"))
        if currency is None or len(currency) != 3:
            raise RazorpayContractError(
                "RAZORPAY_PAYMENT_CURRENCY_INVALID",
                "Razorpay returned no valid payment currency.",
            )
        return PaymentSnapshot(
            provider="razorpay",
            payment_id=provider_payment_id,
            invoice_id=invoice_id,
            subscription_id=subscription_id,
            payment_state=_payment_state(payment.get("status")),
            subscription_state=_subscription_state(subscription.get("status")),
            amount_paise=amount,
            currency=currency.upper(),
            observed_at=datetime.now(UTC),
            authoritative=True,
        )

    async def reconcile_payment_link_by_reference(
        self, *, reference_id: str
    ) -> PaymentSurfaceResult | None:
        """Resolve an uncertain create before an activity decides whether to resubmit.

        Razorpay documents ``reference_id`` as a filter on this collection.  A
        valid empty collection is therefore confirmed absence; malformed or
        ambiguous responses raise and must remain unresolved upstream.
        """

        collection = await self._request_json(
            "GET", "/v1/payment_links", params={"reference_id": reference_id}
        )
        items = collection.get("payment_links", collection.get("items"))
        if not isinstance(items, list):
            raise RazorpayContractError(
                "RAZORPAY_PAYMENT_LINK_COLLECTION_INVALID",
                "Razorpay Payment Link collection has no payment_links array.",
            )
        matches = [
            cast(dict[str, Any], item)
            for item in items
            if isinstance(item, dict) and item.get("reference_id") == reference_id
        ]
        if len(matches) > 1:
            raise RazorpayContractError(
                "RAZORPAY_PAYMENT_LINK_REFERENCE_AMBIGUOUS",
                "Razorpay returned multiple Payment Links for one unique reference_id.",
                reference_id=reference_id,
            )
        match = matches[0] if matches else None
        if match is None:
            if self._payment_link_breaker.uncertain_submission:
                self._payment_link_breaker.reconcile_uncertain(provider_confirmed_absent=True)
            return None
        link_id = _text(match.get("id"))
        short_url = _text(match.get("short_url"))
        if (
            link_id is None
            or not link_id.startswith("plink_")
            or len(link_id) > 128
            or short_url is None
        ):
            raise RazorpayContractError(
                "RAZORPAY_PAYMENT_LINK_RESPONSE_INVALID",
                "Reconciled Payment Link has no id or short_url.",
                reference_id=reference_id,
            )
        if self._payment_link_breaker.uncertain_submission:
            self._payment_link_breaker.reconcile_uncertain(provider_confirmed_absent=False)
        expire_by = _integer(match.get("expire_by"))
        expires_at = datetime.fromtimestamp(expire_by, UTC) if expire_by else None
        return PaymentSurfaceResult(
            provider="razorpay",
            provider_reference=link_id,
            surface_type=PaymentSurfaceType.STANDARD_PAYMENT_LINK,
            customer_url=_provider_https_url(short_url, code="RAZORPAY_PAYMENT_LINK_URL_INVALID"),
            expires_at=expires_at,
            authoritative=True,
        )

    async def revoke_standard_payment_link(
        self, *, provider_reference: str
    ) -> Literal["CANCELLED", "ALREADY_INACTIVE", "PAYMENT_PRESENT"]:
        """Cancel a created link while converging harmless terminal races.

        A paid or partially-paid link cannot be cancelled.  Reporting that state
        lets authoritative invoice/payment reconciliation proceed instead of
        turning terminal-case cleanup into a false payment failure.
        """

        async def fetch() -> dict[str, Any]:
            return await self._request_json("GET", f"/v1/payment_links/{provider_reference}")

        def terminal_state(
            link: dict[str, Any],
        ) -> Literal["ALREADY_INACTIVE", "PAYMENT_PRESENT"] | None:
            status = _text(link.get("status"))
            if status in {"cancelled", "expired"}:
                return "ALREADY_INACTIVE"
            if status in {"paid", "partially_paid"}:
                return "PAYMENT_PRESENT"
            return None

        link = await fetch()
        terminal = terminal_state(link)
        if terminal is not None:
            return terminal
        if link.get("status") != "created":
            raise RazorpayContractError(
                "RAZORPAY_PAYMENT_LINK_STATUS_UNRESOLVED",
                "Payment Link cannot be safely cancelled from its current state.",
                provider_reference=provider_reference,
                provider_status=link.get("status"),
            )
        try:
            cancelled = await self._request_json(
                "POST", f"/v1/payment_links/{provider_reference}/cancel"
            )
        except RazorpayRequestError:
            # Payment or another cancellation can win after the read.  A second
            # authoritative read makes those races idempotent; otherwise the
            # original error remains unresolved and is not treated as success.
            terminal = terminal_state(await fetch())
            if terminal is not None:
                return terminal
            raise
        if cancelled.get("status") != "cancelled":
            raise RazorpayContractError(
                "RAZORPAY_PAYMENT_LINK_CANCEL_UNCONFIRMED",
                "Razorpay did not confirm Payment Link cancellation.",
                provider_reference=provider_reference,
                provider_status=cancelled.get("status"),
            )
        return "CANCELLED"
