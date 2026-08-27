"""Pydantic contracts for RecoveryOS domain state.

The models intentionally separate independent state axes.  For example, an
opt-out contact disposition can coexist with a captured late payment, and a
captured arrears payment does not prove that a subscription was reactivated.
"""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .enums import (
    ActionStatus,
    CaseOutcome,
    ContactDisposition,
    Diagnosis,
    EvidenceKind,
    PaymentState,
    PaymentSurfaceType,
    PolicyDisposition,
    RecoveryActionType,
    RevenueAttribution,
    SubscriptionState,
)


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=False)


class RecoveryCaseKey(ContractModel):
    """Idempotency boundary for one failed invoice or billing cycle."""

    merchant_id: str = Field(min_length=1)
    failed_invoice_id: str | None = Field(default=None, min_length=1)
    billing_cycle_key: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def require_invoice_or_cycle(self) -> "RecoveryCaseKey":
        if not self.failed_invoice_id and not self.billing_cycle_key:
            raise ValueError("failed_invoice_id or billing_cycle_key is required")
        return self

    @property
    def idempotency_key(self) -> str:
        scope = self.failed_invoice_id or self.billing_cycle_key
        return f"{self.merchant_id}:{scope}"


class RecoveryCaseState(ContractModel):
    id: str
    key: RecoveryCaseKey
    customer_id: str
    subscription_id: str
    failed_payment_id: str | None = None
    case_outcome: CaseOutcome = CaseOutcome.OPEN
    payment_state: PaymentState = PaymentState.FAILED
    subscription_state: SubscriptionState = SubscriptionState.UNKNOWN
    contact_disposition: ContactDisposition = ContactDisposition.NOT_CONTACTED
    revenue_attribution: RevenueAttribution = RevenueAttribution.NONE
    diagnosis: Diagnosis = Diagnosis.UNKNOWN
    amount_at_risk_paise: int = Field(ge=0)
    arrears_collected_paise: int = Field(default=0, ge=0)
    case_recovered: bool = False
    subscription_reactivated: bool = False
    opened_at: datetime
    recovery_deadline: datetime
    recovered_at: datetime | None = None
    version: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def validate_state(self) -> "RecoveryCaseState":
        for field_name in ("opened_at", "recovery_deadline", "recovered_at"):
            value = getattr(self, field_name)
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError(f"{field_name} must be timezone-aware UTC")
            if value is not None and value.utcoffset() != UTC.utcoffset(value):
                raise ValueError(f"{field_name} must use UTC")
        if self.recovery_deadline <= self.opened_at:
            raise ValueError("recovery_deadline must be after opened_at")
        if self.case_recovered and self.arrears_collected_paise <= 0:
            raise ValueError("a recovered case must have collected arrears")
        if self.case_outcome == CaseOutcome.RECOVERED and not self.case_recovered:
            raise ValueError("RECOVERED outcome requires case_recovered=true")
        if self.payment_state == PaymentState.CAPTURED and self.arrears_collected_paise == 0:
            raise ValueError("CAPTURED payment requires a collected amount")
        if self.arrears_collected_paise > 0 and self.revenue_attribution == RevenueAttribution.NONE:
            raise ValueError("collected arrears require an attribution source")
        return self


class RejectedAlternative(ContractModel):
    action: RecoveryActionType
    payment_surface_type: PaymentSurfaceType | None = None
    reason_code: str
    reason: str


class ActionRecommendation(ContractModel):
    action: RecoveryActionType
    payment_surface_type: PaymentSurfaceType | None = None
    predicted_recovery_probability: float = Field(ge=0, le=1)
    expected_recovered_paise: int = Field(ge=0)
    expected_utility_paise: int
    confidence: float = Field(ge=0, le=1)
    reason_codes: list[str]
    reasons: list[str]
    rejected_alternatives: list[RejectedAlternative] = Field(default_factory=list)

    @model_validator(mode="after")
    def surface_only_for_surface_action(self) -> "ActionRecommendation":
        opens_surface = self.action == RecoveryActionType.OPEN_CUSTOMER_PAYMENT_SURFACE
        if opens_surface != (self.payment_surface_type is not None):
            raise ValueError(
                "payment_surface_type is required only for OPEN_CUSTOMER_PAYMENT_SURFACE"
            )
        return self


class PolicyDecision(ContractModel):
    disposition: PolicyDisposition
    decision_code: str
    reason_codes: list[str]
    reasons: list[str]
    policy_version: str
    delay_until: datetime | None = None

    @model_validator(mode="after")
    def delay_requires_timestamp(self) -> "PolicyDecision":
        if (self.disposition == PolicyDisposition.DELAY) != (self.delay_until is not None):
            raise ValueError("delay_until is required only for DELAY")
        return self


class RecoveryAction(ContractModel):
    id: str
    case_id: str
    action_type: RecoveryActionType
    payment_surface_type: PaymentSurfaceType | None = None
    status: ActionStatus
    scheduled_for: datetime | None = None
    policy_decision: PolicyDecision
    external_reference: str | None = None
    created_at: datetime
    completed_at: datetime | None = None


class RecoveryEvent(ContractModel):
    id: str
    case_id: str
    event_type: str
    source: str
    evidence_kind: EvidenceKind
    payload: dict[str, Any]
    occurred_at: datetime
    correlation_id: str


class RevenueRecognition(ContractModel):
    """One idempotent attribution record for one provider success event."""

    case_id: str
    merchant_id: str
    provider_event_id: str
    amount_paise: int = Field(gt=0)
    attribution: RevenueAttribution
    arrears_collected: bool
    subscription_reactivated: bool
    recognized_at: datetime

    @model_validator(mode="after")
    def attribution_must_be_verified(self) -> "RevenueRecognition":
        if self.attribution == RevenueAttribution.NONE:
            raise ValueError("revenue recognition cannot use NONE attribution")
        return self
