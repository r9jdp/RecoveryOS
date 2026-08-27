"""HTTP request and response contracts for the merchant recovery API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from services.api.app.domain.enums import (
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


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class PageResponse(ApiModel):
    next_cursor: str | None
    has_more: bool
    limit: int


class CaseSummaryResponse(ApiModel):
    id: str
    merchant_id: str
    failed_invoice_id: str | None
    billing_cycle_key: str | None
    customer_display_name: str | None = None
    plan_name: str | None = None
    amount_at_risk_paise: int
    case_outcome: CaseOutcome
    payment_state: PaymentState
    subscription_state: SubscriptionState
    contact_disposition: ContactDisposition
    revenue_attribution: RevenueAttribution
    diagnosis: Diagnosis
    recommended_action: RecoveryActionType | None = None
    payment_surface_type: PaymentSurfaceType | None = None
    updated_at: datetime


class CaseListResponse(ApiModel):
    items: list[CaseSummaryResponse]
    page: PageResponse


class RecoveryCaseResponse(ApiModel):
    id: str
    merchant_id: str
    customer_id: str
    subscription_id: str
    failed_invoice_id: str | None
    billing_cycle_key: str | None
    failed_payment_id: str | None
    case_outcome: CaseOutcome
    payment_state: PaymentState
    subscription_state: SubscriptionState
    contact_disposition: ContactDisposition
    revenue_attribution: RevenueAttribution
    diagnosis: Diagnosis
    amount_at_risk_paise: int
    arrears_collected_paise: int
    case_recovered: bool
    subscription_reactivated: bool
    opened_at: datetime
    recovery_deadline: datetime
    recovered_at: datetime | None
    version: int
    updated_at: datetime


class CustomerResponse(ApiModel):
    id: str
    display_name: str
    preferred_language: str
    voice_consent_at: datetime | None
    opted_out_at: datetime | None
    customer_agent_available: bool


class SubscriptionResponse(ApiModel):
    id: str
    provider_subscription_id: str
    plan_name: str
    amount_paise: int
    currency: str
    subscription_state: SubscriptionState


class InvoiceResponse(ApiModel):
    id: str
    provider_invoice_id: str
    billing_cycle_key: str
    amount_paise: int
    amount_paid_paise: int
    currency: str
    invoice_state: str


class PaymentFailureResponse(ApiModel):
    id: str
    provider_payment_id: str | None
    amount_paise: int
    currency: str
    payment_state: PaymentState
    method: str | None
    error_code: str | None
    error_source: str | None
    error_step: str | None
    error_reason: str | None
    occurred_at: datetime


class PolicyResponse(ApiModel):
    id: str
    disposition: PolicyDisposition
    decision_code: str
    reason_codes: list[str]
    reasons: list[str]
    policy_version: str
    delay_until: datetime | None
    created_at: datetime


class ActionResponse(ApiModel):
    id: str
    case_id: str
    action_type: RecoveryActionType
    payment_surface_type: PaymentSurfaceType | None
    status: ActionStatus
    scheduled_for: datetime | None
    external_reference: str | None
    customer_url: str | None
    created_at: datetime
    completed_at: datetime | None


class CaseDetailResponse(ApiModel):
    case: RecoveryCaseResponse
    customer: CustomerResponse
    subscription: SubscriptionResponse
    invoice: InvoiceResponse | None
    payment_failure: PaymentFailureResponse | None
    latest_action: ActionResponse | None
    latest_policy: PolicyResponse | None
    available_commands: list[str]


class TimelineEventResponse(ApiModel):
    id: str
    case_id: str
    event_type: str
    source: str
    evidence_kind: EvidenceKind
    payload: dict[str, object]
    occurred_at: datetime
    recorded_at: datetime
    correlation_id: str


class TimelineResponse(ApiModel):
    items: list[TimelineEventResponse]


class DiagnosisBucketResponse(ApiModel):
    diagnosis: Diagnosis
    case_count: int


class RecentEventResponse(ApiModel):
    id: str
    case_id: str
    event_type: str
    occurred_at: datetime
    correlation_id: str


class DashboardMetricsResponse(ApiModel):
    revenue_at_risk_paise: int
    verified_recovered_revenue_paise: int
    simulated_incremental_recovery_paise: int
    net_recovered_value_paise: int
    active_cases: int
    recovered_cases: int
    total_cases: int
    recovery_rate_basis_points: int
    human_review_count: int
    policy_blocked_actions: int


class DashboardResponse(ApiModel):
    evidence_kind: EvidenceKind = EvidenceKind.SIMULATED
    currency: str = "INR"
    metrics: DashboardMetricsResponse
    diagnosis_distribution: list[DiagnosisBucketResponse]
    recent_events: list[RecentEventResponse]


class RecommendActionRequest(ApiModel):
    action_type: RecoveryActionType | None = None
    payment_surface_type: PaymentSurfaceType | None = None


class ActionDecisionResponse(ApiModel):
    action: ActionResponse
    policy: PolicyResponse


class RejectActionRequest(ApiModel):
    reason: str = Field(min_length=1, max_length=500)


class CaseCommandRequest(ApiModel):
    reason: str = Field(min_length=1, max_length=500)


class OperatorCommandRequest(ApiModel):
    command: Literal["APPROVE", "REJECT", "STOP", "ESCALATE_TO_HUMAN"]


class OperatorCommandResponse(ApiModel):
    command: str
    message: str
    occurred_at: datetime
    source: Literal["api"] = "api"
    status: Literal["ACCEPTED"] = "ACCEPTED"


class MockPaymentSuccessRequest(ApiModel):
    provider_event_id: str = Field(min_length=1, max_length=200)
    amount_paise: int | None = Field(default=None, gt=0)
    subscription_reactivated: bool = False
    occurred_at: datetime | None = None


class MockPaymentSurfaceRequest(ApiModel):
    action_id: str = Field(min_length=1, max_length=64)


class MockPaymentSuccessResponse(ApiModel):
    case: RecoveryCaseResponse
    newly_recognized: bool
