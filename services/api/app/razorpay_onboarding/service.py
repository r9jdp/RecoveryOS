"""Idempotent persistence of Razorpay Test subscription correlation state."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, cast
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from services.api.app.domain.enums import SubscriptionState
from services.api.app.integrations.razorpay.client import (
    RazorpaySubscriptionOnboardingBundle,
)
from services.api.app.integrations.razorpay.errors import (
    RazorpayContractError,
    RazorpayIntegrationError,
)
from services.api.app.models import (
    Customer,
    Invoice,
    Merchant,
    MerchantPolicySetting,
    Subscription,
)

from .models import (
    RazorpayTestSubscriptionSyncRequest,
    RazorpayTestSubscriptionSyncResponse,
    SyncedCustomerResponse,
    SyncedInvoiceResponse,
    SyncedSubscriptionResponse,
)


class RazorpayOnboardingProvider(Protocol):
    async def fetch_test_subscription_onboarding_bundle(
        self, *, subscription_id: str
    ) -> RazorpaySubscriptionOnboardingBundle: ...


@dataclass(frozen=True, slots=True)
class MerchantIdentity:
    id: str
    external_id: str
    display_name: str
    timezone: str
    currency: str


def merchant_identity_from_env() -> MerchantIdentity:
    """Resolve one server-owned merchant scope; request data cannot override it."""

    merchant_id = os.getenv("RECOVERY_MERCHANT_ID", "").strip()
    display_name = os.getenv("RECOVERY_MERCHANT_DISPLAY_NAME", "").strip()
    external_id = os.getenv("RECOVERY_MERCHANT_EXTERNAL_ID", merchant_id).strip()
    timezone = os.getenv("RECOVERY_MERCHANT_TIMEZONE", "Asia/Kolkata").strip()
    currency = os.getenv("RECOVERY_MERCHANT_CURRENCY", "INR").strip().upper()
    if not merchant_id or not display_name or not external_id:
        raise RazorpayIntegrationError(
            "RAZORPAY_MERCHANT_SCOPE_NOT_CONFIGURED",
            "RECOVERY_MERCHANT_ID and RECOVERY_MERCHANT_DISPLAY_NAME are required.",
            status_code=503,
        )
    if len(merchant_id) > 64 or len(external_id) > 128 or len(display_name) > 200:
        raise RazorpayIntegrationError(
            "RAZORPAY_MERCHANT_SCOPE_INVALID",
            "Configured merchant identity exceeds the persistence contract.",
            status_code=503,
        )
    if len(currency) != 3:
        raise RazorpayIntegrationError(
            "RAZORPAY_MERCHANT_SCOPE_INVALID",
            "RECOVERY_MERCHANT_CURRENCY must be a three-letter currency code.",
            status_code=503,
        )
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as error:
        raise RazorpayIntegrationError(
            "RAZORPAY_MERCHANT_SCOPE_INVALID",
            "RECOVERY_MERCHANT_TIMEZONE must be a valid IANA timezone.",
            status_code=503,
        ) from error
    return MerchantIdentity(
        id=merchant_id,
        external_id=external_id,
        display_name=display_name,
        timezone=timezone,
        currency=currency,
    )


def _stable_id(prefix: str, *scope: str) -> str:
    digest = hashlib.sha256(":".join(scope).encode("utf-8")).hexdigest()[:40]
    return f"{prefix}_{digest}"


def _required_text(payload: dict[str, Any], field: str, *, code: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise RazorpayContractError(code, f"Razorpay {field} is missing or invalid.")
    return value


def _nonnegative_integer(payload: dict[str, Any], field: str, *, code: str) -> int:
    value = payload.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RazorpayContractError(code, f"Razorpay {field} is missing or invalid.")
    return value


def _positive_integer(payload: dict[str, Any], field: str, *, default: int = 1) -> int:
    value = payload.get(field, default)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise RazorpayContractError(
            "RAZORPAY_SUBSCRIPTION_QUANTITY_INVALID",
            "Razorpay subscription quantity must be a positive integer.",
        )
    return value


def _provider_https_url(payload: dict[str, Any], field: str, *, code: str) -> str | None:
    """Accept only an HTTPS URL returned by the authenticated provider API."""

    value = payload.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 2_048:
        raise RazorpayContractError(code, f"Razorpay {field} is invalid.")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise RazorpayContractError(
            code,
            f"Razorpay {field} must be a provider-returned HTTPS URL.",
        )
    return value


def _subscription_state(value: object) -> SubscriptionState:
    if not isinstance(value, str):
        return SubscriptionState.UNKNOWN
    mapping = {state.value.lower(): state for state in SubscriptionState}
    return mapping.get(value.lower(), SubscriptionState.UNKNOWN)


def _provider_timestamp(payload: dict[str, Any], *fields: str) -> datetime | None:
    for field in fields:
        value = payload.get(field)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            try:
                return datetime.fromtimestamp(value, UTC)
            except (OSError, OverflowError, ValueError) as error:
                raise RazorpayContractError(
                    "RAZORPAY_TIMESTAMP_INVALID",
                    f"Razorpay {field} is outside the supported timestamp range.",
                ) from error
    return None


@dataclass(frozen=True, slots=True)
class _InvoiceData:
    provider_id: str
    billing_cycle_key: str
    amount_paise: int
    amount_paid_paise: int
    currency: str
    state: str
    payment_url: str | None
    due_at: datetime | None
    sort_timestamp: int


class RazorpaySubscriptionOnboardingService:
    def __init__(self, session: AsyncSession, provider: RazorpayOnboardingProvider) -> None:
        self.session = session
        self.provider = provider

    async def sync(
        self,
        *,
        merchant: MerchantIdentity,
        subscription_id: str,
        request: RazorpayTestSubscriptionSyncRequest,
    ) -> RazorpayTestSubscriptionSyncResponse:
        if not subscription_id.startswith("sub_") or len(subscription_id) > 128:
            raise RazorpayContractError(
                "RAZORPAY_SUBSCRIPTION_ID_INVALID",
                "A valid Razorpay subscription id is required.",
            )
        bundle = await self.provider.fetch_test_subscription_onboarding_bundle(
            subscription_id=subscription_id
        )
        for attempt in range(2):
            try:
                response = await self._persist(
                    merchant=merchant,
                    subscription_id=subscription_id,
                    request=request,
                    bundle=bundle,
                )
                await self.session.commit()
                return response
            except IntegrityError as error:
                await self.session.rollback()
                if attempt == 1:
                    raise RazorpayContractError(
                        "RAZORPAY_ONBOARDING_CONFLICT",
                        "Concurrent onboarding could not converge safely.",
                    ) from error
            except Exception:
                await self.session.rollback()
                raise
        raise AssertionError("bounded onboarding retry did not return")

    async def _persist(
        self,
        *,
        merchant: MerchantIdentity,
        subscription_id: str,
        request: RazorpayTestSubscriptionSyncRequest,
        bundle: RazorpaySubscriptionOnboardingBundle,
    ) -> RazorpayTestSubscriptionSyncResponse:
        subscription_payload = bundle.subscription
        plan_payload = bundle.plan
        provider_subscription_id = _required_text(
            subscription_payload,
            "id",
            code="RAZORPAY_SUBSCRIPTION_RESPONSE_INVALID",
        )
        if provider_subscription_id != subscription_id:
            raise RazorpayContractError(
                "RAZORPAY_SUBSCRIPTION_RESPONSE_MISMATCH",
                "Razorpay returned a different subscription than requested.",
            )
        provider_plan_id = _required_text(
            subscription_payload,
            "plan_id",
            code="RAZORPAY_SUBSCRIPTION_PLAN_MISSING",
        )
        if not provider_plan_id.startswith("plan_"):
            raise RazorpayContractError(
                "RAZORPAY_SUBSCRIPTION_PLAN_MISSING",
                "Razorpay subscription has no valid provider plan id.",
            )
        if plan_payload.get("id") != provider_plan_id:
            raise RazorpayContractError(
                "RAZORPAY_PLAN_RESPONSE_MISMATCH",
                "Razorpay plan does not belong to the subscription.",
            )
        plan_item = plan_payload.get("item")
        if not isinstance(plan_item, dict):
            raise RazorpayContractError(
                "RAZORPAY_PLAN_ITEM_INVALID",
                "Razorpay plan has no valid item.",
            )
        plan_name = _required_text(
            cast(dict[str, Any], plan_item),
            "name",
            code="RAZORPAY_PLAN_ITEM_INVALID",
        )
        if len(plan_name) > 200 or len(provider_plan_id) > 128:
            raise RazorpayContractError(
                "RAZORPAY_PLAN_ITEM_INVALID",
                "Razorpay plan identity exceeds the persistence contract.",
            )
        unit_amount_paise = _nonnegative_integer(
            cast(dict[str, Any], plan_item),
            "amount",
            code="RAZORPAY_PLAN_ITEM_INVALID",
        )
        currency = _required_text(
            cast(dict[str, Any], plan_item),
            "currency",
            code="RAZORPAY_PLAN_ITEM_INVALID",
        ).upper()
        if len(currency) != 3 or currency != merchant.currency:
            raise RazorpayContractError(
                "RAZORPAY_CURRENCY_SCOPE_MISMATCH",
                "Razorpay plan currency does not match the configured merchant currency.",
            )
        quantity = _positive_integer(subscription_payload, "quantity")
        amount_paise = unit_amount_paise * quantity
        state = _subscription_state(subscription_payload.get("status"))
        subscription_short_url = _provider_https_url(
            subscription_payload,
            "short_url",
            code="RAZORPAY_SUBSCRIPTION_URL_INVALID",
        )
        invoices = [
            self._invoice_data(
                payload=invoice_payload,
                subscription_id=subscription_id,
                currency=currency,
            )
            for invoice_payload in bundle.invoices
        ]

        merchant_record = await self._upsert_merchant(merchant)
        customer, customer_created = await self._upsert_customer(
            merchant=merchant_record,
            request=request,
        )
        subscription, subscription_created = await self._upsert_subscription(
            merchant=merchant_record,
            customer=customer,
            provider_subscription_id=provider_subscription_id,
            plan_name=plan_name,
            amount_paise=amount_paise,
            currency=currency,
            state=state,
        )
        invoice_responses: list[SyncedInvoiceResponse] = []
        for invoice_data in sorted(invoices, key=lambda item: item.sort_timestamp):
            invoice, invoice_created = await self._upsert_invoice(
                merchant=merchant_record,
                subscription=subscription,
                data=invoice_data,
            )
            invoice_responses.append(
                SyncedInvoiceResponse(
                    id=invoice.id,
                    provider_invoice_id=invoice.provider_invoice_id,
                    billing_cycle_key=invoice.billing_cycle_key,
                    amount_paise=invoice.amount_paise,
                    amount_paid_paise=invoice.amount_paid_paise,
                    currency=invoice.currency,
                    invoice_state=invoice.invoice_state,
                    payment_url=invoice_data.payment_url,
                    created=invoice_created,
                )
            )
        if invoices:
            subscription.current_billing_cycle_key = max(
                invoices, key=lambda item: item.sort_timestamp
            ).billing_cycle_key
        await self.session.flush()
        return RazorpayTestSubscriptionSyncResponse(
            merchant_id=merchant_record.id,
            customer=SyncedCustomerResponse(
                id=customer.id,
                external_id=customer.external_id,
                created=customer_created,
            ),
            subscription=SyncedSubscriptionResponse(
                id=subscription.id,
                provider_subscription_id=subscription.provider_subscription_id,
                provider_plan_id=provider_plan_id,
                plan_name=subscription.plan_name,
                amount_paise=subscription.amount_paise,
                currency=subscription.currency,
                subscription_state=subscription.subscription_state,
                authorization_url=subscription_short_url,
                created=subscription_created,
            ),
            invoices=invoice_responses,
        )

    @staticmethod
    def _invoice_data(
        *, payload: dict[str, Any], subscription_id: str, currency: str
    ) -> _InvoiceData:
        provider_id = _required_text(payload, "id", code="RAZORPAY_INVOICE_RESPONSE_INVALID")
        if not provider_id.startswith("inv_") or len(provider_id) > 128:
            raise RazorpayContractError(
                "RAZORPAY_INVOICE_RESPONSE_INVALID",
                "Razorpay invoice id exceeds the persistence contract.",
            )
        provider_subscription_id = _required_text(
            payload,
            "subscription_id",
            code="RAZORPAY_INVOICE_RESPONSE_INVALID",
        )
        if provider_subscription_id != subscription_id:
            raise RazorpayContractError(
                "RAZORPAY_INVOICE_SUBSCRIPTION_MISMATCH",
                "Razorpay invoice does not belong to the requested subscription.",
                provider_invoice_id=provider_id,
            )
        invoice_currency = _required_text(
            payload, "currency", code="RAZORPAY_INVOICE_RESPONSE_INVALID"
        ).upper()
        if invoice_currency != currency:
            raise RazorpayContractError(
                "RAZORPAY_INVOICE_CURRENCY_MISMATCH",
                "Razorpay invoice currency does not match its plan.",
                provider_invoice_id=provider_id,
            )
        amount_paise = _nonnegative_integer(
            payload, "amount", code="RAZORPAY_INVOICE_RESPONSE_INVALID"
        )
        amount_paid_paise = _nonnegative_integer(
            payload, "amount_paid", code="RAZORPAY_INVOICE_RESPONSE_INVALID"
        )
        if amount_paid_paise > amount_paise:
            raise RazorpayContractError(
                "RAZORPAY_INVOICE_AMOUNT_INVALID",
                "Razorpay invoice amount_paid exceeds amount.",
                provider_invoice_id=provider_id,
            )
        state = _required_text(payload, "status", code="RAZORPAY_INVOICE_RESPONSE_INVALID").lower()
        if len(state) > 32:
            raise RazorpayContractError(
                "RAZORPAY_INVOICE_RESPONSE_INVALID",
                "Razorpay invoice status exceeds the persistence contract.",
            )
        timestamp = next(
            (
                value
                for field in ("billing_start", "issued_at", "date", "created_at")
                if isinstance((value := payload.get(field)), int)
                and not isinstance(value, bool)
                and value >= 0
            ),
            0,
        )
        raw_billing_cycle_key = f"razorpay:{provider_id}"
        billing_cycle_key = (
            raw_billing_cycle_key
            if len(raw_billing_cycle_key) <= 64
            else f"razorpay:{hashlib.sha256(provider_id.encode()).hexdigest()[:40]}"
        )
        return _InvoiceData(
            provider_id=provider_id,
            billing_cycle_key=billing_cycle_key,
            amount_paise=amount_paise,
            amount_paid_paise=amount_paid_paise,
            currency=invoice_currency,
            state=state,
            payment_url=_provider_https_url(
                payload,
                "short_url",
                code="RAZORPAY_INVOICE_URL_INVALID",
            ),
            due_at=_provider_timestamp(payload, "expire_by", "billing_end"),
            sort_timestamp=timestamp,
        )

    async def _upsert_merchant(self, identity: MerchantIdentity) -> Merchant:
        external_owner = cast(
            Merchant | None,
            await self.session.scalar(
                select(Merchant)
                .where(Merchant.external_id == identity.external_id)
                .with_for_update()
            ),
        )
        merchant = cast(
            Merchant | None,
            await self.session.scalar(
                select(Merchant).where(Merchant.id == identity.id).with_for_update()
            ),
        )
        if external_owner is not None and external_owner.id != identity.id:
            raise RazorpayContractError(
                "RAZORPAY_MERCHANT_SCOPE_CONFLICT",
                "Configured merchant external_id belongs to another merchant.",
            )
        if merchant is None:
            merchant = Merchant(
                id=identity.id,
                external_id=identity.external_id,
                display_name=identity.display_name,
                timezone=identity.timezone,
                currency=identity.currency,
            )
            self.session.add(merchant)
            self.session.add(MerchantPolicySetting(merchant_id=identity.id))
            await self.session.flush()
            return merchant
        if merchant.external_id != identity.external_id or merchant.currency != identity.currency:
            raise RazorpayContractError(
                "RAZORPAY_MERCHANT_SCOPE_CONFLICT",
                "Configured merchant identity does not match the persisted merchant.",
            )
        merchant.display_name = identity.display_name
        merchant.timezone = identity.timezone
        policy = await self.session.get(MerchantPolicySetting, merchant.id)
        if policy is None:
            self.session.add(MerchantPolicySetting(merchant_id=merchant.id))
        return merchant

    async def _upsert_customer(
        self,
        *,
        merchant: Merchant,
        request: RazorpayTestSubscriptionSyncRequest,
    ) -> tuple[Customer, bool]:
        customer = cast(
            Customer | None,
            await self.session.scalar(
                select(Customer)
                .where(
                    Customer.merchant_id == merchant.id,
                    Customer.external_id == request.customer_external_id,
                )
                .with_for_update()
            ),
        )
        created = customer is None
        if customer is None:
            customer = Customer(
                id=_stable_id("customer_rzp", merchant.id, request.customer_external_id),
                merchant_id=merchant.id,
                external_id=request.customer_external_id,
                display_name=request.customer_display_name,
                preferred_language=request.preferred_language,
                customer_agent_available=False,
            )
            self.session.add(customer)
        else:
            customer.display_name = request.customer_display_name
            customer.preferred_language = request.preferred_language
        await self.session.flush()
        return customer, created

    async def _upsert_subscription(
        self,
        *,
        merchant: Merchant,
        customer: Customer,
        provider_subscription_id: str,
        plan_name: str,
        amount_paise: int,
        currency: str,
        state: SubscriptionState,
    ) -> tuple[Subscription, bool]:
        subscription = cast(
            Subscription | None,
            await self.session.scalar(
                select(Subscription)
                .where(
                    Subscription.merchant_id == merchant.id,
                    Subscription.provider_subscription_id == provider_subscription_id,
                )
                .with_for_update()
            ),
        )
        created = subscription is None
        if subscription is None:
            subscription = Subscription(
                id=_stable_id("subscription_rzp", merchant.id, provider_subscription_id),
                merchant_id=merchant.id,
                customer_id=customer.id,
                provider_subscription_id=provider_subscription_id,
                plan_name=plan_name,
                amount_paise=amount_paise,
                currency=currency,
                subscription_state=state,
            )
            self.session.add(subscription)
        else:
            if subscription.customer_id != customer.id:
                raise RazorpayContractError(
                    "RAZORPAY_SUBSCRIPTION_CUSTOMER_CONFLICT",
                    "Razorpay subscription is already bound to another local customer.",
                )
            subscription.plan_name = plan_name
            subscription.amount_paise = amount_paise
            subscription.currency = currency
            subscription.subscription_state = state
        await self.session.flush()
        return subscription, created

    async def _upsert_invoice(
        self,
        *,
        merchant: Merchant,
        subscription: Subscription,
        data: _InvoiceData,
    ) -> tuple[Invoice, bool]:
        invoice = cast(
            Invoice | None,
            await self.session.scalar(
                select(Invoice)
                .where(
                    Invoice.merchant_id == merchant.id,
                    Invoice.provider_invoice_id == data.provider_id,
                )
                .with_for_update()
            ),
        )
        created = invoice is None
        if invoice is None:
            invoice = Invoice(
                id=_stable_id("invoice_rzp", merchant.id, data.provider_id),
                merchant_id=merchant.id,
                subscription_id=subscription.id,
                provider_invoice_id=data.provider_id,
                billing_cycle_key=data.billing_cycle_key,
                amount_paise=data.amount_paise,
                amount_paid_paise=data.amount_paid_paise,
                currency=data.currency,
                invoice_state=data.state,
                due_at=data.due_at,
            )
            self.session.add(invoice)
        else:
            if invoice.subscription_id != subscription.id:
                raise RazorpayContractError(
                    "RAZORPAY_INVOICE_SUBSCRIPTION_CONFLICT",
                    "Razorpay invoice is already bound to another local subscription.",
                )
            invoice.amount_paise = data.amount_paise
            invoice.amount_paid_paise = data.amount_paid_paise
            invoice.currency = data.currency
            invoice.invoice_state = data.state
            invoice.due_at = data.due_at
        await self.session.flush()
        return invoice, created
