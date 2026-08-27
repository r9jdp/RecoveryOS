"""Deterministic Temporal orchestration for one recovery case."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

from .activities import (
    CANCEL_RECOVERY_ACTION,
    DIAGNOSE_FAILURE,
    EVALUATE_POLICY,
    EXECUTE_RECOVERY_ACTION,
    NORMALIZE_FAILURE,
    POLL_A2A_MANDATE,
    RECONCILE_CASE,
    RECORD_AUDIT_EVENT,
    SCORE_RECOVERY,
    START_A2A_AUTHORIZATION,
)
from .contracts import (
    A2AAuthorizationResult,
    A2AMandatePollResult,
    A2AUpdateSignal,
    ActionExecutionResult,
    ApprovalSignal,
    AuditInput,
    AuditResult,
    CancelActionInput,
    CancelActionResult,
    CancellationSignal,
    CustomerIntentSignal,
    DiagnosisInput,
    DiagnosisResult,
    ExecuteActionInput,
    MandateSignal,
    NormalizedFailure,
    NormalizeFailureInput,
    OperatorEscalationSignal,
    OptOutSignal,
    PaymentEventSignal,
    PolicyInput,
    PolicyResult,
    PollA2AMandateInput,
    QueuedSignal,
    ReconciliationInput,
    ReconciliationResult,
    RecoveryWorkflowInput,
    RecoveryWorkflowResult,
    RecoveryWorkflowStatus,
    ScoreInput,
    ScoreResult,
    StartA2AAuthorizationInput,
)


def recovery_workflow_id(case_id: str) -> str:
    """Return the only valid workflow ID for a recovery case."""

    return f"recovery-case:{case_id}"


_STANDARD_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=10),
    maximum_attempts=3,
)
_PROVIDER_SUBMISSION_RETRY = RetryPolicy(maximum_attempts=1)
_ACTIVITY_TIMEOUT = timedelta(seconds=30)
_A2A_POLL_INTERVAL = timedelta(seconds=5)


@workflow.defn(name="recovery.case.v1")
class RecoveryCaseWorkflow:
    """Durable coordinator for exactly one failed invoice/billing cycle."""

    def __init__(self) -> None:
        self._case_id = ""
        self._phase = "INITIALIZING"
        self._terminal = False
        self._outcome: str | None = None
        self._diagnosis: str | None = None
        self._policy_disposition: str | None = None
        self._action: str | None = None
        self._action_status: str | None = None
        self._provider_reference: str | None = None
        self._payment_state = "FAILED"
        self._subscription_state = "UNKNOWN"
        self._contact_disposition = "NOT_CONTACTED"
        self._approval_required = False
        self._approval_received: bool | None = None
        self._outreach_suppressed = False
        self._a2a_state: str | None = None
        self._a2a_task_id: str | None = None
        self._next_a2a_poll_at: datetime | None = None
        self._mandate_received = False
        self._deadline: datetime | None = None
        self._signals: list[QueuedSignal] = []
        self._seen_signal_ids: set[str] = set()
        self._processed_signal_count = 0
        self._duplicate_signal_count = 0
        self._arrears_collected_paise = 0
        self._subscription_reactivated = False
        self._input: RecoveryWorkflowInput | None = None

    @workflow.run
    async def run(self, command: RecoveryWorkflowInput) -> RecoveryWorkflowResult:
        expected_id = recovery_workflow_id(command.case_id)
        if workflow.info().workflow_id != expected_id:
            raise ApplicationError(
                f"workflow ID must be {expected_id}",
                type="INVALID_WORKFLOW_ID",
                non_retryable=True,
            )
        if command.amount_at_risk_paise < 0:
            raise ApplicationError(
                "amount_at_risk_paise cannot be negative",
                type="INVALID_MONEY_AMOUNT",
                non_retryable=True,
            )

        self._case_id = command.case_id
        self._deadline = self._parse_instant(command.recovery_deadline)
        self._input = command

        normalized = await self._activity(
            NORMALIZE_FAILURE,
            NormalizeFailureInput(
                case_id=command.case_id,
                merchant_id=command.merchant_id,
                subscription_id=command.subscription_id,
                failed_invoice_id=command.failed_invoice_id,
                failed_payment_id=command.failed_payment_id,
                event=command.failure_event,
            ),
            NormalizedFailure,
        )
        self._payment_state = normalized.payment_state
        self._subscription_state = normalized.subscription_state

        self._phase = "DIAGNOSING"
        diagnosis = await self._activity(
            DIAGNOSE_FAILURE,
            DiagnosisInput(case_id=command.case_id, failure=normalized),
            DiagnosisResult,
        )
        self._diagnosis = diagnosis.diagnosis

        self._phase = "SCORING"
        await self._activity(
            SCORE_RECOVERY,
            ScoreInput(
                case_id=command.case_id,
                amount_at_risk_paise=command.amount_at_risk_paise,
                diagnosis=diagnosis.diagnosis,
                candidate_action=command.candidate_action,
            ),
            ScoreResult,
        )

        self._phase = "POLICY"
        policy = await self._activity(
            EVALUATE_POLICY,
            PolicyInput(
                case_id=command.case_id,
                merchant_id=command.merchant_id,
                amount_at_risk_paise=command.amount_at_risk_paise,
                diagnosis=diagnosis.diagnosis,
                candidate_action=command.candidate_action,
                payment_surface_type=command.payment_surface_type,
                recovery_deadline=command.recovery_deadline,
            ),
            PolicyResult,
        )
        self._policy_disposition = policy.disposition
        self._action = policy.action
        await self._audit(
            "POLICY_DECIDED",
            "initial-policy",
            {
                "disposition": policy.disposition,
                "decision_code": policy.decision_code,
                "action": policy.action,
                "reason_codes": list(policy.reason_codes),
            },
        )

        if policy.disposition == "BLOCK":
            self._finish("STOPPED", "BLOCKED_BY_POLICY")
            return self._result()

        if policy.disposition == "DELAY" and policy.delay_until is not None:
            self._phase = "POLICY_DELAY"
            await self._wait_until(self._parse_instant(policy.delay_until))
            if self._terminal:
                return self._result()

        if policy.disposition == "REQUIRE_MANUAL_APPROVAL":
            self._approval_required = True
            self._phase = "AWAITING_APPROVAL"
            await self._wait_for_approval_or_terminal()
            if self._terminal:
                return self._result()
            if self._approval_received is not True:
                self._finish("STOPPED", "APPROVAL_REJECTED")
                return self._result()

        if policy.action not in {"WAIT_FOR_GATEWAY_RETRY", "STOP"}:
            await self._execute_action(policy)
            if self._terminal:
                return self._result()
        elif policy.action == "STOP":
            self._finish("STOPPED", "POLICY_STOP")
            return self._result()
        else:
            self._action_status = "SCHEDULED"

        self._phase = (
            "AWAITING_CUSTOMER_AUTHORIZATION"
            if self._a2a_task_id is not None
            else "AWAITING_RECOVERY"
        )
        while not self._terminal:
            if self._deadline is not None and workflow.now() >= self._deadline:
                await self._cancel_active_action("RECOVERY_DEADLINE_EXPIRED")
                self._finish(self._deadline_outcome(), "DEADLINE_EXPIRED")
                break
            await self._poll_a2a_if_due()
            if self._terminal:
                break
            await self._wait_for_signal_or_deadline()
            await self._drain_signals()

        return self._result()

    @workflow.signal(name="payment_event")
    async def payment_event(self, signal: PaymentEventSignal) -> None:
        self._enqueue("PAYMENT_EVENT", signal.signal_id, asdict(signal))

    @workflow.signal(name="customer_intent")
    async def customer_intent(self, signal: CustomerIntentSignal) -> None:
        self._enqueue("CUSTOMER_INTENT", signal.signal_id, asdict(signal))

    @workflow.signal(name="approval")
    async def approval(self, signal: ApprovalSignal) -> None:
        self._enqueue("APPROVAL", signal.signal_id, asdict(signal))

    @workflow.signal(name="opt_out")
    async def opt_out(self, signal: OptOutSignal) -> None:
        self._enqueue("OPT_OUT", signal.signal_id, asdict(signal))

    @workflow.signal(name="cancel")
    async def cancel(self, signal: CancellationSignal) -> None:
        self._enqueue("CANCELLATION", signal.signal_id, asdict(signal))

    @workflow.signal(name="operator_escalation")
    async def operator_escalation(self, signal: OperatorEscalationSignal) -> None:
        self._enqueue("OPERATOR_ESCALATION", signal.signal_id, asdict(signal))

    @workflow.signal(name="a2a_update")
    async def a2a_update(self, signal: A2AUpdateSignal) -> None:
        self._enqueue("A2A_UPDATE", signal.signal_id, asdict(signal))

    @workflow.signal(name="mandate")
    async def mandate(self, signal: MandateSignal) -> None:
        self._enqueue("MANDATE", signal.signal_id, asdict(signal))

    @workflow.query(name="status")
    def status(self) -> RecoveryWorkflowStatus:
        return RecoveryWorkflowStatus(
            case_id=self._case_id,
            phase=self._phase,
            terminal=self._terminal,
            outcome=self._outcome,
            diagnosis=self._diagnosis,
            policy_disposition=self._policy_disposition,
            action=self._action,
            action_status=self._action_status,
            provider_reference=self._provider_reference,
            payment_state=self._payment_state,
            subscription_state=self._subscription_state,
            contact_disposition=self._contact_disposition,
            approval_required=self._approval_required,
            approval_received=self._approval_received,
            outreach_suppressed=self._outreach_suppressed,
            a2a_state=self._a2a_state,
            mandate_received=self._mandate_received,
            received_signal_count=len(self._seen_signal_ids),
            duplicate_signal_count=self._duplicate_signal_count,
            recovery_deadline=(self._deadline.isoformat() if self._deadline is not None else None),
        )

    def _enqueue(self, kind: str, signal_id: str, payload: dict[str, Any]) -> None:
        if signal_id in self._seen_signal_ids:
            self._duplicate_signal_count += 1
            return
        self._seen_signal_ids.add(signal_id)
        self._signals.append(QueuedSignal(kind=kind, signal_id=signal_id, payload=payload))

    async def _wait_for_approval_or_terminal(self) -> None:
        while self._approval_received is None and not self._terminal:
            await self._wait_for_signal_or_deadline()
            await self._drain_signals()
            if self._deadline is not None and workflow.now() >= self._deadline:
                await self._cancel_active_action("RECOVERY_DEADLINE_EXPIRED")
                self._finish(self._deadline_outcome(), "DEADLINE_EXPIRED")

    async def _wait_until(self, target: datetime) -> None:
        while not self._terminal and workflow.now() < target:
            deadline = self._deadline or target
            timeout = min(target, deadline) - workflow.now()
            if timeout.total_seconds() <= 0:
                break
            with suppress(TimeoutError):
                await workflow.wait_condition(lambda: bool(self._signals), timeout=timeout)
            await self._drain_signals()
        if self._deadline is not None and workflow.now() >= self._deadline and not self._terminal:
            await self._cancel_active_action("RECOVERY_DEADLINE_EXPIRED")
            self._finish(self._deadline_outcome(), "DEADLINE_EXPIRED")

    async def _wait_for_signal_or_deadline(self) -> None:
        if self._deadline is None:
            return
        wake_at = self._deadline
        if self._next_a2a_poll_at is not None:
            wake_at = min(wake_at, self._next_a2a_poll_at)
        remaining = wake_at - workflow.now()
        if remaining.total_seconds() <= 0:
            return
        with suppress(TimeoutError):
            await workflow.wait_condition(lambda: bool(self._signals), timeout=remaining)

    async def _drain_signals(self) -> None:
        while self._signals and not self._terminal:
            signal = self._signals.pop(0)
            self._processed_signal_count += 1
            if signal.kind == "APPROVAL":
                await self._handle_approval(signal)
            elif signal.kind == "PAYMENT_EVENT":
                await self._handle_payment(signal)
            elif signal.kind == "CUSTOMER_INTENT":
                await self._handle_customer_intent(signal)
            elif signal.kind == "OPT_OUT":
                await self._handle_opt_out(signal)
            elif signal.kind == "CANCELLATION":
                await self._handle_cancellation(signal)
            elif signal.kind == "OPERATOR_ESCALATION":
                await self._handle_operator_escalation(signal)
            elif signal.kind == "A2A_UPDATE":
                await self._handle_a2a_update(signal)
            elif signal.kind == "MANDATE":
                await self._handle_mandate(signal)

    async def _handle_approval(self, signal: QueuedSignal) -> None:
        if not self._approval_required or self._approval_received is not None:
            await self._audit("APPROVAL_IGNORED", signal.signal_id, {"reason": "NOT_AWAITED"})
            return
        self._approval_received = bool(signal.payload["approved"])
        await self._audit(
            "APPROVAL_RECORDED",
            signal.signal_id,
            {
                "approved": self._approval_received,
                "reviewer_id": signal.payload["reviewer_id"],
                "reason": signal.payload.get("reason"),
            },
        )

    async def _handle_payment(self, signal: QueuedSignal) -> None:
        command = self._require_input()
        result = await self._activity(
            RECONCILE_CASE,
            ReconciliationInput(
                case_id=command.case_id,
                merchant_id=command.merchant_id,
                failed_invoice_id=command.failed_invoice_id,
                failed_payment_id=command.failed_payment_id,
                trigger_event_id=str(signal.payload["provider_event_id"]),
                payment_state_hint=str(signal.payload["payment_state"]),
                amount_paise_hint=int(signal.payload["amount_paise"]),
                authoritative_hint=bool(signal.payload["authoritative"]),
            ),
            ReconciliationResult,
        )
        self._apply_reconciliation(result)
        await self._audit(
            "PAYMENT_RECONCILED",
            signal.signal_id,
            {
                "payment_state": result.payment_state,
                "authoritative": result.authoritative,
                "case_recovered": result.case_recovered,
            },
        )
        if result.case_recovered and result.authoritative:
            await self._cancel_active_action("AUTHORITATIVE_PAYMENT_SUCCESS")
            self._finish("RECOVERED", "PAYMENT_CAPTURED")

    async def _handle_customer_intent(self, signal: QueuedSignal) -> None:
        intent = str(signal.payload["intent"]).upper()
        disposition = {
            "OPT_OUT": "OPTED_OUT",
            "WRONG_PERSON": "WRONG_PERSON",
            "DISPUTE": "DISPUTE",
            "ALREADY_PAID": "ALREADY_PAID",
            "PROMISE_TO_PAY": "PROMISE_TO_PAY",
        }.get(intent, "ENGAGED")
        self._contact_disposition = disposition
        await self._audit(
            "CUSTOMER_INTENT_RECORDED",
            signal.signal_id,
            {"intent": intent, "confidence": signal.payload.get("confidence")},
        )
        if intent in {"OPT_OUT", "WRONG_PERSON"}:
            await self._suppress_outreach(signal.signal_id, disposition)
        elif intent == "DISPUTE":
            await self._cancel_active_action("CUSTOMER_DISPUTE")
            self._finish("DISPUTED", "CUSTOMER_DISPUTE")
        elif intent == "ALREADY_PAID":
            command = self._require_input()
            result = await self._activity(
                RECONCILE_CASE,
                ReconciliationInput(
                    case_id=command.case_id,
                    merchant_id=command.merchant_id,
                    failed_invoice_id=command.failed_invoice_id,
                    failed_payment_id=command.failed_payment_id,
                    trigger_event_id=signal.signal_id,
                ),
                ReconciliationResult,
            )
            self._apply_reconciliation(result)
            if result.case_recovered and result.authoritative:
                await self._cancel_active_action("AUTHORITATIVE_PAYMENT_SUCCESS")
                self._finish("RECOVERED", "ALREADY_PAID_RECONCILED")

    async def _handle_opt_out(self, signal: QueuedSignal) -> None:
        self._contact_disposition = "OPTED_OUT"
        await self._audit(
            "OUTREACH_SUPPRESSED",
            signal.signal_id,
            {"source": signal.payload["source"], "reason": signal.payload.get("reason")},
        )
        await self._suppress_outreach(signal.signal_id, "OPTED_OUT")

    async def _handle_cancellation(self, signal: QueuedSignal) -> None:
        await self._audit(
            "RECOVERY_CANCELLED",
            signal.signal_id,
            {
                "reason": signal.payload["reason"],
                "requested_by": signal.payload["requested_by"],
            },
        )
        await self._cancel_active_action(str(signal.payload["reason"]))
        self._finish("STOPPED", "CANCELLED")

    async def _handle_operator_escalation(self, signal: QueuedSignal) -> None:
        await self._audit(
            "RECOVERY_ESCALATED",
            signal.signal_id,
            {
                "reason": signal.payload["reason"],
                "requested_by": signal.payload["requested_by"],
            },
        )
        await self._cancel_active_action("OPERATOR_ESCALATION")
        self._finish("ESCALATED", "OPERATOR_ESCALATION")

    async def _handle_a2a_update(self, signal: QueuedSignal) -> None:
        remote_task_id = str(signal.payload["remote_task_id"])
        if self._a2a_task_id is None or remote_task_id != self._a2a_task_id:
            await self._audit(
                "A2A_UPDATE_IGNORED",
                signal.signal_id,
                {"reason": "TASK_ID_MISMATCH"},
            )
            return
        self._a2a_state = str(signal.payload["state"])
        await self._audit(
            "A2A_TASK_UPDATED",
            signal.signal_id,
            {
                "remote_task_id": remote_task_id,
                "state": self._a2a_state,
            },
        )
        # A signal is only a low-latency wake-up hint. The activity fetches the
        # authoritative task and verifies any artifact before the workflow acts.
        self._next_a2a_poll_at = workflow.now()

    async def _handle_mandate(self, signal: QueuedSignal) -> None:
        await self._audit(
            "MANDATE_SIGNAL_IGNORED",
            signal.signal_id,
            {
                "mandate_id": signal.payload["mandate_id"],
                "reason": "ACTIVITY_VERIFICATION_REQUIRED",
            },
        )
        if self._a2a_task_id is not None:
            self._next_a2a_poll_at = workflow.now()

    async def _suppress_outreach(self, signal_id: str, disposition: str) -> None:
        self._outreach_suppressed = True
        await self._cancel_active_action(disposition)
        await self._audit(
            "SUPPRESSION_PERSIST_REQUESTED",
            signal_id,
            {"contact_disposition": disposition},
        )
        # Keep the workflow passively open for authoritative late-payment signals.
        # Outreach is stopped, but contact and financial state are independent axes.
        self._outcome = "STOPPED"
        self._phase = "OUTREACH_SUPPRESSED"

    async def _start_a2a_authorization(self) -> None:
        command = self._require_input()
        surface_type = command.payment_surface_type
        surface_reference = self._expected_payment_surface_reference(command)
        if surface_type is None or surface_reference is None:
            await self._audit(
                "A2A_AUTHORIZATION_REJECTED",
                "a2a-start",
                {"reason_code": "EXACT_PAYMENT_SURFACE_REQUIRED"},
            )
            self._action_status = "REJECTED"
            self._finish("ESCALATED", "EXACT_PAYMENT_SURFACE_REQUIRED")
            return

        result = await self._activity(
            START_A2A_AUTHORIZATION,
            StartA2AAuthorizationInput(
                case_id=command.case_id,
                merchant_id=command.merchant_id,
                customer_id=command.customer_id,
                exact_amount_paise=command.amount_at_risk_paise,
                currency=command.currency,
                payment_surface_type=surface_type,
                payment_surface_reference=surface_reference,
                recovery_deadline=command.recovery_deadline,
                idempotency_key=f"{command.case_id}:SEND_TO_CUSTOMER_AGENT:1",
            ),
            A2AAuthorizationResult,
            provider_submission=True,
        )
        self._action = "SEND_TO_CUSTOMER_AGENT"
        self._action_status = result.state
        self._provider_reference = result.remote_task_id
        self._a2a_task_id = result.remote_task_id
        self._a2a_state = result.state
        self._next_a2a_poll_at = (
            workflow.now() if result.state == "WORKING" else workflow.now() + _A2A_POLL_INTERVAL
        )
        self._phase = "AWAITING_CUSTOMER_AUTHORIZATION"
        await self._audit(
            "A2A_AUTHORIZATION_STARTED",
            "a2a-start",
            {"remote_task_id": result.remote_task_id, "state": result.state},
        )

    async def _poll_a2a_if_due(self) -> None:
        if (
            self._a2a_task_id is None
            or self._next_a2a_poll_at is None
            or workflow.now() < self._next_a2a_poll_at
        ):
            return
        command = self._require_input()
        surface_type = command.payment_surface_type
        surface_reference = self._expected_payment_surface_reference(command)
        if surface_type is None or surface_reference is None:
            self._next_a2a_poll_at = None
            self._action_status = "REJECTED"
            self._finish("ESCALATED", "EXACT_PAYMENT_SURFACE_REQUIRED")
            return
        result = await self._activity(
            POLL_A2A_MANDATE,
            PollA2AMandateInput(
                remote_task_id=self._a2a_task_id,
                case_id=command.case_id,
                merchant_id=command.merchant_id,
                customer_id=command.customer_id,
                exact_amount_paise=command.amount_at_risk_paise,
                currency=command.currency,
                payment_surface_type=surface_type,
                payment_surface_reference=surface_reference,
                recovery_deadline=command.recovery_deadline,
            ),
            A2AMandatePollResult,
        )
        self._a2a_state = result.task_state
        if result.verification_status == "PENDING":
            self._next_a2a_poll_at = workflow.now() + _A2A_POLL_INTERVAL
            return
        self._next_a2a_poll_at = None
        accepted = (
            result.verification_status == "VERIFIED"
            and result.mandate_id is not None
            and result.verified_artifact is not None
        )
        await self._audit(
            "MANDATE_VERIFICATION_COMPLETED",
            result.mandate_id or f"a2a:{self._a2a_task_id}",
            {
                "accepted": accepted,
                "reason_code": result.reason_code,
                "task_state": result.task_state,
            },
        )
        if not accepted:
            self._action_status = "REJECTED"
            self._finish("ESCALATED", result.reason_code or "MANDATE_REJECTED")
            return

        self._mandate_received = True
        policy = PolicyResult(
            disposition="ALLOW",
            decision_code="VERIFIED_MANDATE",
            action="OPEN_CUSTOMER_PAYMENT_SURFACE",
            payment_surface_type=surface_type,
        )
        await self._execute_action(policy, mandate=dict(result.verified_artifact))

    async def _execute_action(
        self, policy: PolicyResult, mandate: dict[str, Any] | None = None
    ) -> None:
        if policy.action == "SEND_TO_CUSTOMER_AGENT" and mandate is None:
            await self._start_a2a_authorization()
            return
        command = self._require_input()
        self._phase = "EXECUTING_ACTION"
        self._action_status = "EXECUTING"
        result = await self._activity(
            EXECUTE_RECOVERY_ACTION,
            ExecuteActionInput(
                case_id=command.case_id,
                merchant_id=command.merchant_id,
                customer_id=command.customer_id,
                subscription_id=command.subscription_id,
                failed_invoice_id=command.failed_invoice_id,
                amount_paise=command.amount_at_risk_paise,
                currency=command.currency,
                action=policy.action,
                payment_surface_type=policy.payment_surface_type,
                recovery_deadline=command.recovery_deadline,
                idempotency_key=f"{command.case_id}:{policy.action}:1",
                mandate=mandate,
            ),
            ActionExecutionResult,
            provider_submission=True,
        )
        self._action = policy.action
        self._action_status = result.status
        self._provider_reference = result.provider_reference
        await self._audit(
            "ACTION_SUBMITTED",
            "action-1",
            {
                "action": policy.action,
                "status": result.status,
                "provider": result.provider,
                "reason_code": result.reason_code,
            },
        )
        if result.status in {"FAILED", "REJECTED"}:
            self._finish("ESCALATED", "PROVIDER_REJECTED")
        elif result.status == "UNCERTAIN":
            self._phase = "RECONCILIATION_REQUIRED"

    @staticmethod
    def _expected_payment_surface_reference(command: RecoveryWorkflowInput) -> str | None:
        if command.payment_surface_reference:
            return command.payment_surface_reference
        if command.payment_surface_type == "SUBSCRIPTION_INVOICE_LINK":
            return command.failed_invoice_id
        if command.payment_surface_type == "SUBSCRIPTION_CARD_UPDATE":
            return command.subscription_id
        # A standard Payment Link must already exist before it can be authorized.
        # Its provider reference cannot be safely invented by the workflow.
        return None

    async def _cancel_active_action(self, reason: str) -> None:
        if self._action_status in {"CANCELLED", "FAILED", "REJECTED"}:
            return
        if self._action_status is None and reason != "AUTHORITATIVE_PAYMENT_SUCCESS":
            return
        result = await self._activity(
            CANCEL_RECOVERY_ACTION,
            CancelActionInput(
                case_id=self._case_id,
                provider_reference=self._provider_reference,
                reason=reason,
                idempotency_key=f"{self._case_id}:cancel:action-1",
            ),
            CancelActionResult,
            provider_submission=True,
        )
        if result.cancelled:
            self._action_status = "CANCELLED"

    async def _audit(self, event_type: str, correlation_id: str, details: dict[str, Any]) -> None:
        await self._activity(
            RECORD_AUDIT_EVENT,
            AuditInput(
                case_id=self._case_id,
                event_type=event_type,
                correlation_id=correlation_id,
                details=details,
            ),
            AuditResult,
        )

    async def _activity(
        self,
        activity_name: str,
        argument: Any,
        result_type: type[Any],
        *,
        provider_submission: bool = False,
    ) -> Any:
        return await workflow.execute_activity(
            activity_name,
            argument,
            result_type=result_type,
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
            retry_policy=(_PROVIDER_SUBMISSION_RETRY if provider_submission else _STANDARD_RETRY),
        )

    def _apply_reconciliation(self, result: ReconciliationResult) -> None:
        if not result.authoritative:
            return
        self._payment_state = result.payment_state
        self._subscription_state = result.subscription_state
        self._arrears_collected_paise = result.arrears_collected_paise
        self._subscription_reactivated = result.subscription_reactivated

    def _finish(self, outcome: str, reason: str) -> None:
        self._outcome = outcome
        self._phase = f"TERMINAL_{outcome}"
        self._terminal = True
        if outcome == "RECOVERED":
            self._payment_state = "CAPTURED"
        workflow.logger.info("Recovery workflow finished", extra={"reason": reason})

    def _deadline_outcome(self) -> str:
        return "STOPPED" if self._outreach_suppressed else "EXPIRED"

    def _require_input(self) -> RecoveryWorkflowInput:
        if self._input is None:
            raise RuntimeError("workflow input is not initialized")
        return self._input

    @staticmethod
    def _parse_instant(value: str) -> datetime:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError("Temporal instants must include a UTC offset")
        return instant

    def _result(self) -> RecoveryWorkflowResult:
        return RecoveryWorkflowResult(
            case_id=self._case_id,
            outcome=self._outcome or "STOPPED",
            payment_state=self._payment_state,
            subscription_state=self._subscription_state,
            case_recovered=self._outcome == "RECOVERED",
            arrears_collected_paise=self._arrears_collected_paise,
            subscription_reactivated=self._subscription_reactivated,
            contact_disposition=self._contact_disposition,
            processed_signal_count=self._processed_signal_count,
            duplicate_signal_count=self._duplicate_signal_count,
        )
