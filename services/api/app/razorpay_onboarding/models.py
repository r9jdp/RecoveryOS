"""Contracts for importing real Razorpay Test subscription state."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from services.api.app.domain.enums import SubscriptionState


class OnboardingModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RazorpayTestSubscriptionSyncRequest(OnboardingModel):
    """Local customer identity for a provider subscription.

    Email and phone values are deliberately not accepted here. Provider
    onboarding establishes correlation only; contact consent and destinations
    are managed by their dedicated, authenticated flows.
    """

    customer_external_id: str = Field(min_length=1, max_length=128)
    customer_display_name: str = Field(min_length=1, max_length=200)
    preferred_language: str = Field(default="en-IN", min_length=2, max_length=32)


class SyncedCustomerResponse(OnboardingModel):
    id: str
    external_id: str
    created: bool


class SyncedSubscriptionResponse(OnboardingModel):
    id: str
    provider_subscription_id: str
    provider_plan_id: str
    plan_name: str
    amount_paise: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    subscription_state: SubscriptionState
    authorization_url: str | None = Field(default=None, pattern=r"^https://")
    created: bool


class SyncedInvoiceResponse(OnboardingModel):
    id: str
    provider_invoice_id: str
    billing_cycle_key: str
    amount_paise: int = Field(ge=0)
    amount_paid_paise: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    invoice_state: str
    payment_url: str | None = Field(default=None, pattern=r"^https://")
    created: bool


class RazorpayTestSubscriptionSyncResponse(OnboardingModel):
    mode: str = "razorpay_test"
    merchant_id: str
    customer: SyncedCustomerResponse
    subscription: SyncedSubscriptionResponse
    invoices: list[SyncedInvoiceResponse]
