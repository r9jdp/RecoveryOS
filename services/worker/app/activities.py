"""Temporal activity registrations and Phase 1 mock implementations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from temporalio import activity

from .contracts import (
    A2AAuthorizationResult,
    A2AMandatePollResult,
    A2APaymentReceiptResult,
    ActionExecutionResult,
    AuditInput,
    AuditResult,
    CancelActionInput,
    CancelActionResult,
    DiagnosisInput,
    DiagnosisResult,
    ExecuteActionInput,
    NormalizedFailure,
    NormalizeFailureInput,
    PolicyInput,
    PolicyResult,
    PollA2AMandateInput,
    ReconciliationInput,
    ReconciliationResult,
    ScoreInput,
    ScoreResult,
    SendA2APaymentReceiptInput,
    StartA2AAuthorizationInput,
)
from .ports import A2AMandateActivityServices, RecoveryActivityServices

NORMALIZE_FAILURE = "recovery.normalize_failure"
DIAGNOSE_FAILURE = "recovery.diagnose_failure"
SCORE_RECOVERY = "recovery.score_recovery"
EVALUATE_POLICY = "recovery.evaluate_policy"
EXECUTE_RECOVERY_ACTION = "recovery.execute_recovery_action"
RECONCILE_CASE = "recovery.reconcile_case"
RECORD_AUDIT_EVENT = "recovery.record_audit_event"
CANCEL_RECOVERY_ACTION = "recovery.cancel_recovery_action"
START_A2A_AUTHORIZATION = "recovery.start_a2a_authorization"
POLL_A2A_MANDATE = "recovery.poll_a2a_mandate"
SEND_A2A_PAYMENT_RECEIPT = "recovery.send_a2a_payment_receipt"


class RecoveryActivities:
    """Thin activity boundary around injectable application services."""

    def __init__(
        self,
        services: RecoveryActivityServices,
        a2a_services: A2AMandateActivityServices | None = None,
    ) -> None:
        self._services = services
        self._a2a_services = a2a_services or DisabledA2AMandateActivityServices()

    @activity.defn(name=NORMALIZE_FAILURE)
    async def normalize_failure(self, command: NormalizeFailureInput) -> NormalizedFailure:
        return await self._services.normalize_failure(command)

    @activity.defn(name=DIAGNOSE_FAILURE)
    async def diagnose_failure(self, command: DiagnosisInput) -> DiagnosisResult:
        return await self._services.diagnose_failure(command)

    @activity.defn(name=SCORE_RECOVERY)
    async def score_recovery(self, command: ScoreInput) -> ScoreResult:
        return await self._services.score_recovery(command)

    @activity.defn(name=EVALUATE_POLICY)
    async def evaluate_policy(self, command: PolicyInput) -> PolicyResult:
        return await self._services.evaluate_policy(command)

    @activity.defn(name=EXECUTE_RECOVERY_ACTION)
    async def execute_recovery_action(self, command: ExecuteActionInput) -> ActionExecutionResult:
        return await self._services.execute_recovery_action(command)

    @activity.defn(name=RECONCILE_CASE)
    async def reconcile_case(self, command: ReconciliationInput) -> ReconciliationResult:
        return await self._services.reconcile_case(command)

    @activity.defn(name=RECORD_AUDIT_EVENT)
    async def record_audit_event(self, command: AuditInput) -> AuditResult:
        return await self._services.record_audit_event(command)

    @activity.defn(name=CANCEL_RECOVERY_ACTION)
    async def cancel_recovery_action(self, command: CancelActionInput) -> CancelActionResult:
        return await self._services.cancel_recovery_action(command)

    @activity.defn(name=START_A2A_AUTHORIZATION)
    async def start_a2a_authorization(
        self, command: StartA2AAuthorizationInput
    ) -> A2AAuthorizationResult:
        return await self._a2a_services.start_authorization(command)

    @activity.defn(name=POLL_A2A_MANDATE)
    async def poll_a2a_mandate(self, command: PollA2AMandateInput) -> A2AMandatePollResult:
        return await self._a2a_services.poll_and_verify_mandate(command)

    @activity.defn(name=SEND_A2A_PAYMENT_RECEIPT)
    async def send_a2a_payment_receipt(
        self, command: SendA2APaymentReceiptInput
    ) -> A2APaymentReceiptResult:
        return await self._a2a_services.send_payment_receipt(command)

    def registrations(self) -> list[Callable[..., Any]]:
        return [
            self.normalize_failure,
            self.diagnose_failure,
            self.score_recovery,
            self.evaluate_policy,
            self.execute_recovery_action,
            self.reconcile_case,
            self.record_audit_event,
            self.cancel_recovery_action,
            self.start_a2a_authorization,
            self.poll_a2a_mandate,
            self.send_a2a_payment_receipt,
        ]


@dataclass
class MockRecoveryActivityServices:
    """Deterministic, side-effect-contained services used by default in mock mode."""

    require_manual_approval: bool = True
    audits: list[AuditInput] = field(default_factory=list)
    executed_actions: dict[str, ActionExecutionResult] = field(default_factory=dict)
    executed_commands: list[ExecuteActionInput] = field(default_factory=list)
    cancelled_keys: set[str] = field(default_factory=set)

    async def normalize_failure(self, command: NormalizeFailureInput) -> NormalizedFailure:
        payload = command.event.payload
        return NormalizedFailure(
            case_id=command.case_id,
            provider_event_id=command.event.event_id,
            payment_state=str(payload.get("payment_state", "FAILED")),
            subscription_state=str(payload.get("subscription_state", "PENDING")),
            reason_code=(str(payload["reason_code"]) if payload.get("reason_code") else None),
            authoritative=bool(payload.get("authoritative", False)),
            occurred_at=command.event.occurred_at,
        )

    async def diagnose_failure(self, command: DiagnosisInput) -> DiagnosisResult:
        reason = command.failure.reason_code
        mapping = {
            "BAD_REQUEST_PAYMENT_CARD_INSUFFICIENT_BALANCE": "INSUFFICIENT_FUNDS",
            "BAD_REQUEST_PAYMENT_AUTHENTICATION_FAILED": "AUTHENTICATION_REQUIRED",
            "BAD_REQUEST_PAYMENT_CARD_EXPIRED": "INSTRUMENT_INVALID",
            "GATEWAY_ERROR": "TRANSIENT_RETRYABLE",
        }
        diagnosis = mapping.get(reason or "", "UNKNOWN")
        confidence = 0.9 if diagnosis != "UNKNOWN" else 0.35
        return DiagnosisResult(
            diagnosis=diagnosis,
            confidence=confidence,
            reason_codes=((reason,) if reason else ("MISSING_PROVIDER_REASON",)),
        )

    async def score_recovery(self, command: ScoreInput) -> ScoreResult:
        probability_by_diagnosis = {
            "INSUFFICIENT_FUNDS": 0.71,
            "AUTHENTICATION_REQUIRED": 0.76,
            "INSTRUMENT_INVALID": 0.62,
            "TRANSIENT_RETRYABLE": 0.82,
            "UNKNOWN": 0.40,
        }
        probability = probability_by_diagnosis.get(command.diagnosis, 0.40)
        expected = int(
            (Decimal(command.amount_at_risk_paise) * Decimal(str(probability))).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
        return ScoreResult(
            model_name="deterministic-fallback",
            model_version="phase-1",
            recovery_probability=probability,
            expected_recovered_paise=expected,
            expected_utility_paise=expected - 1500,
            explanation=("Fixed Phase 1 fallback score",),
        )

    async def evaluate_policy(self, command: PolicyInput) -> PolicyResult:
        if command.amount_at_risk_paise <= 0:
            return PolicyResult(
                disposition="BLOCK",
                decision_code="INVALID_AMOUNT",
                action="STOP",
                payment_surface_type=None,
                reason_codes=("NON_POSITIVE_AMOUNT",),
            )
        if self.require_manual_approval:
            disposition = "REQUIRE_MANUAL_APPROVAL"
            decision_code = "DEMO_APPROVAL_REQUIRED"
        else:
            disposition = "ALLOW"
            decision_code = "MOCK_PROVIDER_ALLOWED"
        return PolicyResult(
            disposition=disposition,
            decision_code=decision_code,
            action=command.candidate_action,
            payment_surface_type=command.payment_surface_type,
            reason_codes=("MOCK_MODE",),
        )

    async def execute_recovery_action(self, command: ExecuteActionInput) -> ActionExecutionResult:
        existing = self.executed_actions.get(command.idempotency_key)
        if existing is not None:
            return existing
        self.executed_commands.append(command)
        result = ActionExecutionResult(
            status="SUCCEEDED",
            provider="mock",
            provider_reference=f"mock:{command.case_id}:surface",
            customer_url=f"https://mock.recovery.invalid/pay/{command.case_id}",
        )
        self.executed_actions[command.idempotency_key] = result
        return result

    async def reconcile_case(self, command: ReconciliationInput) -> ReconciliationResult:
        recovered = command.authoritative_hint and command.payment_state_hint == "CAPTURED"
        amount = command.amount_paise_hint if recovered else 0
        return ReconciliationResult(
            payment_state="CAPTURED" if recovered else (command.payment_state_hint or "UNKNOWN"),
            subscription_state="ACTIVE" if recovered else "PENDING",
            authoritative=command.authoritative_hint,
            case_recovered=recovered,
            arrears_collected_paise=amount or 0,
            subscription_reactivated=recovered,
            provider_reference=command.trigger_event_id,
        )

    async def record_audit_event(self, command: AuditInput) -> AuditResult:
        self.audits.append(command)
        return AuditResult(
            audit_event_id=f"audit:{command.case_id}:{command.correlation_id}",
            recorded=True,
        )

    async def cancel_recovery_action(self, command: CancelActionInput) -> CancelActionResult:
        if command.idempotency_key in self.cancelled_keys:
            return CancelActionResult(cancelled=True, reason_code="ALREADY_CANCELLED")
        self.cancelled_keys.add(command.idempotency_key)
        return CancelActionResult(cancelled=True)


class DisabledA2AMandateActivityServices:
    """Credential-free default that never manufactures customer authorization."""

    async def start_authorization(
        self, command: StartA2AAuthorizationInput
    ) -> A2AAuthorizationResult:
        return A2AAuthorizationResult(
            remote_task_id=f"mock-a2a:{command.case_id}",
            state="AUTH_REQUIRED",
        )

    async def poll_and_verify_mandate(self, command: PollA2AMandateInput) -> A2AMandatePollResult:
        return A2AMandatePollResult(
            remote_task_id=command.remote_task_id,
            task_state="AUTH_REQUIRED",
            verification_status="PENDING",
        )

    async def send_payment_receipt(
        self, command: SendA2APaymentReceiptInput
    ) -> A2APaymentReceiptResult:
        return A2APaymentReceiptResult(
            remote_task_id=command.remote_task_id,
            task_state="FAILED",
            delivered=False,
        )
