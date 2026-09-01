"""HTTP request and response contracts for the merchant recovery API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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


class RecoveryChannelResponse(ApiModel):
    channel: Literal[
        "SUBSCRIPTION_CARD_UPDATE",
        "SUBSCRIPTION_INVOICE_LINK",
        "STANDARD_PAYMENT_LINK",
        "VOICE",
        "CUSTOMER_AGENT",
    ]
    case_count: int
    recovered_paise: int


class ApprovalQueueItemResponse(ApiModel):
    case_id: str
    action_id: str
    customer_display_name: str
    plan_name: str
    amount_at_risk_paise: int
    recommended_action: RecoveryActionType
    payment_surface_type: PaymentSurfaceType | None
    policy_reason: str
    deadline: datetime
    evidence_kind: EvidenceKind
    provider: Literal["RAZORPAY_TEST", "RECOVERYOS"]


class ApprovalQueueResponse(ApiModel):
    items: list[ApprovalQueueItemResponse]


class DashboardResponse(ApiModel):
    evidence_kind: EvidenceKind = EvidenceKind.SIMULATED
    currency: str = "INR"
    metrics: DashboardMetricsResponse
    diagnosis_distribution: list[DiagnosisBucketResponse]
    recovery_by_channel: list[RecoveryChannelResponse]
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
    action_id: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_action_scope(self) -> OperatorCommandRequest:
        action_scoped = self.command in {"APPROVE", "REJECT"}
        if action_scoped and self.action_id is None:
            raise ValueError("action_id is required for APPROVE and REJECT commands")
        if not action_scoped and self.action_id is not None:
            raise ValueError("action_id is accepted only for APPROVE and REJECT commands")
        return self


class OperatorCommandResponse(ApiModel):
    command: str
    message: str
    occurred_at: datetime
    source: Literal["api"] = "api"
    status: Literal["ACCEPTED"] = "ACCEPTED"


class SafetyDispositionRequest(ApiModel):
    disposition: Literal[
        "MARK_DISPUTE",
        "MARK_OPT_OUT",
        "MARK_ALREADY_PAID",
        "MARK_WRONG_PERSON",
        "ESCALATE_TO_HUMAN",
    ]


class SafetyDispositionResponse(ApiModel):
    disposition: str
    message: str
    occurred_at: datetime
    case: RecoveryCaseResponse
    source: Literal["api"] = "api"
    status: Literal["ACCEPTED"] = "ACCEPTED"


class PolicySettingsUpdate(ApiModel):
    timezone: str = Field(min_length=1, max_length=64)
    quiet_hours_start: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    quiet_hours_end: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    max_contacts_per_7_days: int | None = Field(default=None, gt=0)
    require_approval_above_paise: int | None = Field(default=None, ge=0)
    require_approval_actions: list[RecoveryActionType] = Field(default_factory=list)
    recovery_kill_switch: bool

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise ValueError("timezone must be a known IANA timezone") from error
        return value

    @model_validator(mode="after")
    def validate_quiet_hours(self) -> PolicySettingsUpdate:
        if (self.quiet_hours_start is None) != (self.quiet_hours_end is None):
            raise ValueError("quiet-hours start and end must both be set or both be disabled")
        if self.quiet_hours_start == self.quiet_hours_end and self.quiet_hours_start is not None:
            raise ValueError("quiet-hours start and end cannot be equal")
        return self


class PolicySettingsResponse(PolicySettingsUpdate):
    version: int = Field(ge=1)
    updated_at: datetime


class RazorpayWebhookAckResponse(ApiModel):
    provider_event_id: str
    inbox_id: str
    outbox_id: str
    accepted: bool
    duplicate: bool
    acknowledge_elapsed_ms: float = Field(ge=0)
    acknowledge_within_sla: bool


class FailureSimulationRequest(ApiModel):
    scenario: Literal[
        "DUPLICATE_WEBHOOK",
        "OUT_OF_ORDER_WEBHOOK",
        "LATE_SUCCESS",
        "CHANGED_AUTHORITATIVE_PAYMENT_STATE",
    ]
    seed: int = 20_260_827
    amount_paise: int = Field(default=149_900, gt=0)
    evidence_kind: EvidenceKind = EvidenceKind.SIMULATED


class SimulatedDeliveryResponse(ApiModel):
    delivery_id: str
    provider_event_id: str
    event_type: str
    occurred_at: datetime
    delivered_at: datetime
    observed_payment_state: PaymentState
    authoritative_payment_state: PaymentState
    evidence_kind: EvidenceKind
    payload: dict[str, object]


class FailureSimulationResponse(ApiModel):
    scenario: str
    seed: int
    case_id: str
    payment_id: str
    amount_paise: int
    deliveries: list[SimulatedDeliveryResponse]
    expected_final_payment_state: PaymentState
    expected_revenue_entries: int = Field(ge=0)


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
