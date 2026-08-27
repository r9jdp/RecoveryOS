"""Normalize supported Razorpay webhook shapes without assuming delivery order."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from services.api.app.domain.enums import PaymentState, SubscriptionState

from .errors import RazorpayContractError, UnsupportedWebhookEventError
from .models import CorrelationKind, NormalizedRazorpayEvent, ProviderStateCursor

SUPPORTED_EVENTS = frozenset(
    {
        "payment.failed",
        "subscription.pending",
        "subscription.halted",
        "subscription.charged",
        "payment.captured",
        "payment_link.paid",
    }
)


def _entity(payload: dict[str, Any], name: str) -> dict[str, Any]:
    container = payload.get(name)
    if not isinstance(container, dict):
        return {}
    entity = container.get("entity")
    return cast(dict[str, Any], entity) if isinstance(entity, dict) else {}


def _notes(entity: dict[str, Any]) -> dict[str, Any]:
    notes = entity.get("notes")
    return cast(dict[str, Any], notes) if isinstance(notes, dict) else {}


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _integer(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _occurred_at(payload: dict[str, Any], payment: dict[str, Any]) -> datetime:
    timestamp = _integer(payment.get("created_at")) or _integer(payload.get("created_at"))
    if timestamp is None:
        raise RazorpayContractError(
            "RAZORPAY_WEBHOOK_TIMESTAMP_MISSING", "Webhook has no integer created_at."
        )
    return datetime.fromtimestamp(timestamp, tz=UTC)


def normalize_webhook(
    *, provider_event_id: str, payload: dict[str, Any]
) -> NormalizedRazorpayEvent:
    event_type = _text(payload.get("event"))
    if event_type is None:
        raise RazorpayContractError("RAZORPAY_WEBHOOK_EVENT_MISSING", "Webhook has no event name.")
    if event_type not in SUPPORTED_EVENTS:
        raise UnsupportedWebhookEventError(event_type)
    if not provider_event_id:
        raise RazorpayContractError("RAZORPAY_EVENT_ID_MISSING", "X-Razorpay-Event-Id is required.")
    if len(provider_event_id) > 200:
        raise RazorpayContractError(
            "RAZORPAY_EVENT_ID_TOO_LONG",
            "X-Razorpay-Event-Id exceeds the durable inbox limit.",
        )

    raw_event_payload = payload.get("payload")
    if not isinstance(raw_event_payload, dict):
        raise RazorpayContractError(
            "RAZORPAY_WEBHOOK_PAYLOAD_INVALID", "Webhook payload must be an object."
        )
    event_payload = cast(dict[str, Any], raw_event_payload)
    payment = _entity(event_payload, "payment")
    subscription = _entity(event_payload, "subscription")
    payment_link = _entity(event_payload, "payment_link")
    payment_notes = _notes(payment)
    subscription_notes = _notes(subscription)
    link_notes = _notes(payment_link)

    payment_state = PaymentState.UNKNOWN
    subscription_state = SubscriptionState.UNKNOWN
    if event_type == "payment.failed":
        payment_state = PaymentState.FAILED
    elif event_type in {"payment.captured", "subscription.charged", "payment_link.paid"}:
        payment_state = PaymentState.CAPTURED
    if event_type == "subscription.pending":
        subscription_state = SubscriptionState.PENDING
    elif event_type == "subscription.halted":
        subscription_state = SubscriptionState.HALTED
    elif event_type == "subscription.charged":
        subscription_state = SubscriptionState.ACTIVE

    if event_type in {"subscription.pending", "subscription.halted"}:
        correlation_kind = CorrelationKind.SUBSCRIPTION_ONLY
    elif event_type == "payment_link.paid":
        correlation_kind = CorrelationKind.CASE_AND_INVOICE_FROM_NOTES_REQUIRES_RECONCILIATION
    else:
        correlation_kind = CorrelationKind.INVOICE_AND_SUBSCRIPTION_FROM_PAYMENT

    invoice_id = _text(payment.get("invoice_id")) or _text(link_notes.get("invoice_id"))
    subscription_id = (
        _text(subscription.get("id"))
        or _text(payment_notes.get("subscription_id"))
        or _text(link_notes.get("subscription_id"))
    )
    amount_paise = _integer(payment.get("amount"))
    if amount_paise is None:
        amount_paise = _integer(payment_link.get("amount_paid"))

    return NormalizedRazorpayEvent(
        provider_event_id=provider_event_id,
        event_type=event_type,
        occurred_at=_occurred_at(payload, payment),
        account_id=_text(payload.get("account_id")),
        merchant_reference=(
            _text(payment_notes.get("merchant_id")) or _text(subscription_notes.get("merchant_id"))
        ),
        case_id=_text(payment_notes.get("case_id")) or _text(link_notes.get("case_id")),
        payment_id=_text(payment.get("id")),
        payment_link_id=_text(payment_link.get("id")),
        invoice_id=invoice_id,
        subscription_id=subscription_id,
        amount_paise=amount_paise,
        currency=_text(payment.get("currency")) or _text(payment_link.get("currency")),
        payment_state=payment_state,
        subscription_state=subscription_state,
        correlation_kind=correlation_kind,
        requires_authoritative_fetch=payment_state == PaymentState.CAPTURED,
        provider_payload=payload,
    )


def reduce_provider_state(
    cursor: ProviderStateCursor, event: NormalizedRazorpayEvent
) -> ProviderStateCursor:
    """Apply independent event clocks and never regress a captured payment."""

    values = cursor.model_dump()
    if event.payment_state != PaymentState.UNKNOWN:
        is_newer = (
            cursor.payment_observed_at is None or event.occurred_at >= cursor.payment_observed_at
        )
        can_change = cursor.payment_state != PaymentState.CAPTURED
        if is_newer and (can_change or event.payment_state == PaymentState.CAPTURED):
            values["payment_state"] = event.payment_state
            values["payment_observed_at"] = event.occurred_at
    if event.subscription_state != SubscriptionState.UNKNOWN:
        is_newer = (
            cursor.subscription_observed_at is None
            or event.occurred_at >= cursor.subscription_observed_at
        )
        if is_newer:
            values["subscription_state"] = event.subscription_state
            values["subscription_observed_at"] = event.occurred_at
    return ProviderStateCursor.model_validate(values)
