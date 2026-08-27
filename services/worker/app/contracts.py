"""Serializable commands and results for the recovery workflow.

The worker keeps these transport models deliberately independent of database and
provider SDK types.  They are persisted in Temporal history, so fields should be
added compatibly and existing meanings must not be changed in place.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ProviderEvent:
    event_id: str
    event_type: str
    occurred_at: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RecoveryWorkflowInput:
    case_id: str
    merchant_id: str
    customer_id: str
    subscription_id: str
    failed_invoice_id: str | None
    failed_payment_id: str | None
    amount_at_risk_paise: int
    currency: str
    recovery_deadline: str
    failure_event: ProviderEvent
    candidate_action: str = "OPEN_CUSTOMER_PAYMENT_SURFACE"
    payment_surface_type: str | None = "SUBSCRIPTION_INVOICE_LINK"
    payment_surface_reference: str | None = None


@dataclass(frozen=True)
class NormalizeFailureInput:
    case_id: str
    merchant_id: str
    subscription_id: str
    failed_invoice_id: str | None
    failed_payment_id: str | None
    event: ProviderEvent


@dataclass(frozen=True)
class NormalizedFailure:
    case_id: str
    provider_event_id: str
    payment_state: str
    subscription_state: str
    reason_code: str | None
    authoritative: bool
    occurred_at: str


@dataclass(frozen=True)
class DiagnosisInput:
    case_id: str
    failure: NormalizedFailure


@dataclass(frozen=True)
class DiagnosisResult:
    diagnosis: str
    confidence: float
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScoreInput:
    case_id: str
    amount_at_risk_paise: int
    diagnosis: str
    candidate_action: str


@dataclass(frozen=True)
class ScoreResult:
    model_name: str
    model_version: str
    recovery_probability: float
    expected_recovered_paise: int
    expected_utility_paise: int
    explanation: tuple[str, ...] = ()


@dataclass(frozen=True)
class PolicyInput:
    case_id: str
    merchant_id: str
    amount_at_risk_paise: int
    diagnosis: str
    candidate_action: str
    payment_surface_type: str | None
    recovery_deadline: str


@dataclass(frozen=True)
class PolicyResult:
    disposition: str
    decision_code: str
    action: str
    payment_surface_type: str | None
    reason_codes: tuple[str, ...] = ()
    delay_until: str | None = None


@dataclass(frozen=True)
class ExecuteActionInput:
    case_id: str
    merchant_id: str
    customer_id: str
    subscription_id: str
    failed_invoice_id: str | None
    amount_paise: int
    currency: str
    action: str
    payment_surface_type: str | None
    recovery_deadline: str
    idempotency_key: str
    mandate: dict[str, Any] | None = None


@dataclass(frozen=True)
class ActionExecutionResult:
    status: str
    provider: str
    provider_reference: str | None = None
    customer_url: str | None = None
    reason_code: str | None = None


@dataclass(frozen=True)
class StartA2AAuthorizationInput:
    case_id: str
    merchant_id: str
    customer_id: str
    exact_amount_paise: int
    currency: str
    payment_surface_type: str
    payment_surface_reference: str
    recovery_deadline: str
    idempotency_key: str


@dataclass(frozen=True)
class A2AAuthorizationResult:
    remote_task_id: str
    state: str


@dataclass(frozen=True)
class PollA2AMandateInput:
    remote_task_id: str
    case_id: str
    merchant_id: str
    customer_id: str
    exact_amount_paise: int
    currency: str
    payment_surface_type: str
    payment_surface_reference: str
    recovery_deadline: str


@dataclass(frozen=True)
class A2AMandatePollResult:
    remote_task_id: str
    task_state: str
    verification_status: str
    mandate_id: str | None = None
    verified_artifact: dict[str, Any] | None = None
    reason_code: str | None = None


@dataclass(frozen=True)
class ReconciliationInput:
    case_id: str
    merchant_id: str
    failed_invoice_id: str | None
    failed_payment_id: str | None
    trigger_event_id: str
    payment_state_hint: str | None = None
    amount_paise_hint: int | None = None
    authoritative_hint: bool = False


@dataclass(frozen=True)
class ReconciliationResult:
    payment_state: str
    subscription_state: str
    authoritative: bool
    case_recovered: bool
    arrears_collected_paise: int
    subscription_reactivated: bool
    provider_reference: str | None = None


@dataclass(frozen=True)
class AuditInput:
    case_id: str
    event_type: str
    correlation_id: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AuditResult:
    audit_event_id: str
    recorded: bool


@dataclass(frozen=True)
class CancelActionInput:
    case_id: str
    provider_reference: str | None
    reason: str
    idempotency_key: str


@dataclass(frozen=True)
class CancelActionResult:
    cancelled: bool
    reason_code: str | None = None


@dataclass(frozen=True)
class PaymentEventSignal:
    signal_id: str
    provider_event_id: str
    payment_state: str
    amount_paise: int
    authoritative: bool


@dataclass(frozen=True)
class CustomerIntentSignal:
    signal_id: str
    intent: str
    confidence: float | None = None


@dataclass(frozen=True)
class ApprovalSignal:
    signal_id: str
    approved: bool
    reviewer_id: str
    reason: str | None = None


@dataclass(frozen=True)
class OptOutSignal:
    signal_id: str
    source: str
    reason: str | None = None


@dataclass(frozen=True)
class CancellationSignal:
    signal_id: str
    reason: str
    requested_by: str


@dataclass(frozen=True)
class OperatorEscalationSignal:
    signal_id: str
    reason: str
    requested_by: str


@dataclass(frozen=True)
class A2AUpdateSignal:
    signal_id: str
    remote_task_id: str
    state: str
    artifact: dict[str, Any] | None = None


@dataclass(frozen=True)
class MandateSignal:
    signal_id: str
    mandate_id: str
    verified: bool
    payment_surface_reference: str
    exact_amount_paise: int
    expires_at: str
    artifact: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class QueuedSignal:
    kind: str
    signal_id: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class RecoveryWorkflowStatus:
    case_id: str
    phase: str
    terminal: bool
    outcome: str | None
    diagnosis: str | None
    policy_disposition: str | None
    action: str | None
    action_status: str | None
    provider_reference: str | None
    payment_state: str
    subscription_state: str
    contact_disposition: str
    approval_required: bool
    approval_received: bool | None
    outreach_suppressed: bool
    a2a_state: str | None
    mandate_received: bool
    received_signal_count: int
    duplicate_signal_count: int
    recovery_deadline: str | None


@dataclass(frozen=True)
class RecoveryWorkflowResult:
    case_id: str
    outcome: str
    payment_state: str
    subscription_state: str
    case_recovered: bool
    arrears_collected_paise: int
    subscription_reactivated: bool
    contact_disposition: str
    processed_signal_count: int
    duplicate_signal_count: int
