"""Typed normalized events and reconciliation outcomes."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from services.api.app.domain.enums import PaymentState, SubscriptionState


class RazorpayModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CorrelationKind(StrEnum):
    INVOICE_AND_SUBSCRIPTION_FROM_PAYMENT = "INVOICE_AND_SUBSCRIPTION_FROM_PAYMENT"
    SUBSCRIPTION_ONLY = "SUBSCRIPTION_ONLY"
    CASE_AND_INVOICE_FROM_NOTES_REQUIRES_RECONCILIATION = (
        "CASE_AND_INVOICE_FROM_NOTES_REQUIRES_RECONCILIATION"
    )


class NormalizedRazorpayEvent(RazorpayModel):
    provider_event_id: str
    event_type: str
    occurred_at: datetime
    account_id: str | None = None
    merchant_reference: str | None = None
    case_id: str | None = None
    payment_id: str | None = None
    payment_link_id: str | None = None
    invoice_id: str | None = None
    subscription_id: str | None = None
    amount_paise: int | None = Field(default=None, ge=0)
    currency: str | None = None
    payment_state: PaymentState = PaymentState.UNKNOWN
    subscription_state: SubscriptionState = SubscriptionState.UNKNOWN
    correlation_kind: CorrelationKind
    requires_authoritative_fetch: bool
    provider_payload: dict[str, Any]


class RazorpayOutboxPayload(RazorpayModel):
    merchant_id: str
    event: NormalizedRazorpayEvent


class ProviderStateCursor(RazorpayModel):
    """Per-axis event clock used to make out-of-order delivery deterministic."""

    payment_state: PaymentState = PaymentState.UNKNOWN
    payment_observed_at: datetime | None = None
    subscription_state: SubscriptionState = SubscriptionState.UNKNOWN
    subscription_observed_at: datetime | None = None


class PaymentRecoveryOutcome(RazorpayModel):
    """Accounting and lifecycle effects remain intentionally independent."""

    provider_event_id: str
    payment_id: str | None = None
    invoice_id: str
    subscription_id: str | None = None
    authoritative_payment_state: PaymentState
    authoritative_subscription_state: SubscriptionState
    amount_paise: int = Field(ge=0)
    arrears_collected: bool
    subscription_reactivated: bool
    late_success: bool
    should_close_case: bool
