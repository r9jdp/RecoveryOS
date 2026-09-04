"""Provider request/result objects.

Provider adapters may translate these contracts to SDK-specific objects, but
SDK types must not leak into the domain or Temporal workflow interfaces.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from services.api.app.domain.enums import (
    Diagnosis,
    PaymentState,
    PaymentSurfaceType,
    RecoveryActionType,
    SubscriptionState,
)


class ProviderContract(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())


class OpenPaymentSurfaceRequest(ProviderContract):
    idempotency_key: str
    case_id: str
    merchant_id: str
    customer_id: str
    subscription_id: str
    failed_invoice_id: str
    surface_type: PaymentSurfaceType
    exact_amount_paise: int = Field(gt=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    recovery_deadline: datetime
    expires_at: datetime | None = None
    callback_url: str | None = None
    # Standalone Payment Link controls.  They stay explicit so an adapter cannot
    # accidentally enable provider notifications or partial collection.
    accept_partial: Literal[False] = False
    notify_sms: Literal[False] = False
    notify_email: Literal[False] = False
    reference_id: str | None = Field(default=None, max_length=40)
    notes: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def guard_standard_payment_link(self) -> "OpenPaymentSurfaceRequest":
        if self.surface_type == PaymentSurfaceType.STANDARD_PAYMENT_LINK:
            if not self.reference_id:
                raise ValueError("STANDARD_PAYMENT_LINK requires a deterministic reference_id")
            if self.expires_at is None:
                raise ValueError("STANDARD_PAYMENT_LINK requires expires_at")
            if self.expires_at > self.recovery_deadline:
                raise ValueError("STANDARD_PAYMENT_LINK cannot expire after recovery_deadline")
            if self.notes.get("case_id") != self.case_id:
                raise ValueError("STANDARD_PAYMENT_LINK notes must contain case_id")
            if self.notes.get("invoice_id") != self.failed_invoice_id:
                raise ValueError("STANDARD_PAYMENT_LINK notes must contain invoice_id")
        return self


class PaymentSurfaceResult(ProviderContract):
    provider: str
    provider_reference: str
    surface_type: PaymentSurfaceType
    customer_url: str
    expires_at: datetime | None = None
    authoritative: bool = False


class PaymentSnapshot(ProviderContract):
    provider: str
    payment_id: str | None = None
    invoice_id: str | None = None
    subscription_id: str | None = None
    payment_state: PaymentState
    subscription_state: SubscriptionState
    amount_paise: int = Field(ge=0)
    currency: str
    observed_at: datetime
    authoritative: bool


class InvoiceSnapshot(ProviderContract):
    """Authoritative provider invoice data used for webhook correlation."""

    provider: str
    invoice_id: str
    subscription_id: str
    amount_paise: int = Field(ge=0)
    amount_paid_paise: int = Field(ge=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    invoice_state: str = Field(min_length=1, max_length=32)
    due_at: datetime | None = None
    observed_at: datetime
    authoritative: bool

    @model_validator(mode="after")
    def guard_paid_amount(self) -> "InvoiceSnapshot":
        if self.amount_paid_paise > self.amount_paise:
            raise ValueError("amount_paid_paise cannot exceed amount_paise")
        return self


class VoiceContactRequest(ProviderContract):
    idempotency_key: str
    case_id: str
    customer_id: str
    destination_token: str
    preferred_language: str
    consent_verified_at: datetime
    max_duration_seconds: int = Field(gt=0, le=180)
    disclosure_text: str


class VoiceContactResult(ProviderContract):
    provider: str
    contact_attempt_id: str
    provider_call_id: str | None = None
    status: Literal["SUBMITTED", "REJECTED", "UNCERTAIN"]
    reason_code: str | None = None


class VoiceContactSnapshot(ProviderContract):
    contact_attempt_id: str
    status: str
    disposition: str | None = None
    transcript: str | None = None
    detected_intent: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    duration_seconds: int | None = Field(default=None, ge=0)
    observed_at: datetime


class RecoveryScoreRequest(ProviderContract):
    case_id: str
    amount_at_risk_paise: int = Field(ge=0)
    diagnosis: Diagnosis
    candidate_action: RecoveryActionType
    features: dict[str, str | int | float | bool | None]


class RecoveryScoreResult(ProviderContract):
    model_name: str
    model_version: str
    artifact_checksum: str | None = None
    recovery_probability: float = Field(ge=0, le=1)
    expected_recovered_paise: int = Field(ge=0)
    expected_utility_paise: int
    explanation: list[str] = Field(default_factory=list)


class CustomerAgentDisplayContext(ProviderContract):
    """Non-sensitive case context shown to the customer.

    These fields improve comprehension but never participate in, or broaden,
    the exact mandate scope. They are resolved from RecoveryOS persistence by
    the worker instead of being invented by the customer-agent service.
    """

    merchant_display_name: str = Field(min_length=1, max_length=200)
    plan_name: str = Field(min_length=1, max_length=200)
    failure_explanation: str = Field(min_length=1, max_length=500)
    invoice_state: str = Field(min_length=1, max_length=64)
    payment_state: str = Field(min_length=1, max_length=64)
    subscription_state: str = Field(min_length=1, max_length=64)
    provider_subscription_state: str = Field(min_length=1, max_length=64)
    preferred_language: str = Field(min_length=2, max_length=35)
    invoice_due_at: datetime | None = None
    recovery_deadline: datetime


class CustomerAgentRecoveryRequest(ProviderContract):
    protocol_version: Literal["recovery.request.v2"] = "recovery.request.v2"
    idempotency_key: str
    case_id: str
    merchant_id: str
    customer_id: str
    recovery_action_id: str
    failed_invoice_id: str
    exact_amount_paise: int = Field(gt=0)
    currency: str
    payment_surface_type: PaymentSurfaceType
    payment_surface_reference: str
    expires_at: datetime
    context: CustomerAgentDisplayContext


class CustomerAgentTask(ProviderContract):
    remote_task_id: str
    state: Literal[
        "SUBMITTED",
        "WORKING",
        "AUTH_REQUIRED",
        "COMPLETED",
        "FAILED",
        "CANCELED",
    ]
    approval_path: str | None = None
    artifact: dict[str, Any] | None = None
    updated_at: datetime
