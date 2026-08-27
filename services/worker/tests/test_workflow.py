from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from services.worker.app.activities import MockRecoveryActivityServices, RecoveryActivities
from services.worker.app.contracts import (
    A2AUpdateSignal,
    ApprovalSignal,
    CancellationSignal,
    CustomerIntentSignal,
    MandateSignal,
    OptOutSignal,
    PaymentEventSignal,
    ProviderEvent,
    RecoveryWorkflowInput,
    RecoveryWorkflowStatus,
)
from services.worker.app.workflow import RecoveryCaseWorkflow, recovery_workflow_id


def workflow_input(case_id: str, *, deadline_seconds: int = 3600) -> RecoveryWorkflowInput:
    now = datetime.now(UTC)
    return RecoveryWorkflowInput(
        case_id=case_id,
        merchant_id="merchant-fitbox",
        customer_id="customer-fitbox",
        subscription_id="sub-fitbox",
        failed_invoice_id=f"inv-{case_id}",
        failed_payment_id=f"pay-{case_id}",
        amount_at_risk_paise=149_900,
        currency="INR",
        recovery_deadline=(now + timedelta(seconds=deadline_seconds)).isoformat(),
        failure_event=ProviderEvent(
            event_id=f"evt-failed-{case_id}",
            event_type="payment.failed",
            occurred_at=now.isoformat(),
            payload={
                "payment_state": "FAILED",
                "subscription_state": "PENDING",
                "reason_code": "BAD_REQUEST_PAYMENT_CARD_INSUFFICIENT_BALANCE",
            },
        ),
    )


@pytest.mark.asyncio
async def test_workflow_deduplicates_signals_recovers_and_replays_history() -> None:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        services = MockRecoveryActivityServices(require_manual_approval=True)
        activities = RecoveryActivities(services)
        task_queue = "recovery-happy-path"
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[RecoveryCaseWorkflow],
            activities=activities.registrations(),
        ):
            command = workflow_input("happy")
            handle = await env.client.start_workflow(
                RecoveryCaseWorkflow.run,
                command,
                id=recovery_workflow_id(command.case_id),
                task_queue=task_queue,
            )
            approval = ApprovalSignal(
                signal_id="approval-1",
                approved=True,
                reviewer_id="operator-1",
            )
            await handle.signal("approval", approval)
            for _ in range(100):
                status = await handle.query("status", result_type=RecoveryWorkflowStatus)
                if status.action_status == "SUCCEEDED":
                    break
                await asyncio.sleep(0.01)
            else:
                pytest.fail("workflow did not execute the approved action")
            await handle.signal("approval", approval)
            await handle.signal(
                "payment_event",
                PaymentEventSignal(
                    signal_id="payment-1",
                    provider_event_id="evt-captured-happy",
                    payment_state="CAPTURED",
                    amount_paise=149_900,
                    authoritative=True,
                ),
            )

            result = await handle.result()
            history = await handle.fetch_history()

        assert result.outcome == "RECOVERED"
        assert result.case_recovered is True
        assert result.arrears_collected_paise == 149_900
        assert result.processed_signal_count == 2
        assert result.duplicate_signal_count == 1
        assert len(services.executed_actions) == 1
        assert len(services.cancelled_keys) == 1
        assert any(event.event_type == "PAYMENT_RECONCILED" for event in services.audits)

        replay_result = await Replayer(workflows=[RecoveryCaseWorkflow]).replay_workflow(history)
        assert replay_result.replay_failure is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("signal_name", "signal", "expected_disposition"),
    [
        (
            "opt_out",
            OptOutSignal(signal_id="optout-1", source="browser", reason="customer request"),
            "OPTED_OUT",
        ),
        (
            "cancel",
            CancellationSignal(
                signal_id="cancel-1",
                reason="operator kill switch",
                requested_by="operator-1",
            ),
            "NOT_CONTACTED",
        ),
    ],
)
async def test_safety_signals_stop_workflow(
    signal_name: str,
    signal: OptOutSignal | CancellationSignal,
    expected_disposition: str,
) -> None:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        services = MockRecoveryActivityServices(require_manual_approval=True)
        activities = RecoveryActivities(services)
        task_queue = f"recovery-{signal_name}"
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[RecoveryCaseWorkflow],
            activities=activities.registrations(),
        ):
            command = workflow_input(signal_name)
            handle = await env.client.start_workflow(
                RecoveryCaseWorkflow.run,
                command,
                id=recovery_workflow_id(command.case_id),
                task_queue=task_queue,
            )
            await handle.signal(signal_name, signal)
            result = await handle.result()

        assert result.outcome == "STOPPED"
        assert result.contact_disposition == expected_disposition
        if signal_name == "opt_out":
            assert any(
                event.event_type == "SUPPRESSION_PERSIST_REQUESTED" for event in services.audits
            )


@pytest.mark.asyncio
async def test_deadline_expires_without_external_action_retry() -> None:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        services = MockRecoveryActivityServices(require_manual_approval=False)
        activities = RecoveryActivities(services)
        task_queue = "recovery-deadline"
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[RecoveryCaseWorkflow],
            activities=activities.registrations(),
        ):
            command = workflow_input("deadline", deadline_seconds=2)
            result = await env.client.execute_workflow(
                RecoveryCaseWorkflow.run,
                command,
                id=recovery_workflow_id(command.case_id),
                task_queue=task_queue,
            )

        assert result.outcome == "EXPIRED"
        assert len(services.executed_actions) == 1
        assert len(services.cancelled_keys) == 1


@pytest.mark.asyncio
async def test_authoritative_payment_can_recover_after_opt_out() -> None:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        services = MockRecoveryActivityServices(require_manual_approval=True)
        activities = RecoveryActivities(services)
        task_queue = "recovery-late-payment-after-optout"
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[RecoveryCaseWorkflow],
            activities=activities.registrations(),
        ):
            command = workflow_input("late-after-optout")
            handle = await env.client.start_workflow(
                RecoveryCaseWorkflow.run,
                command,
                id=recovery_workflow_id(command.case_id),
                task_queue=task_queue,
            )
            await handle.signal(
                "opt_out",
                OptOutSignal(signal_id="optout-late", source="voice"),
            )
            await handle.signal(
                "payment_event",
                PaymentEventSignal(
                    signal_id="payment-late",
                    provider_event_id="evt-captured-late",
                    payment_state="CAPTURED",
                    amount_paise=149_900,
                    authoritative=True,
                ),
            )
            result = await handle.result()

        assert result.outcome == "RECOVERED"
        assert result.case_recovered is True
        assert result.contact_disposition == "OPTED_OUT"
        assert result.arrears_collected_paise == 149_900


@pytest.mark.asyncio
async def test_a2a_mandate_and_customer_intent_signals_are_processed() -> None:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        services = MockRecoveryActivityServices(require_manual_approval=False)
        activities = RecoveryActivities(services)
        task_queue = "recovery-a2a"
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[RecoveryCaseWorkflow],
            activities=activities.registrations(),
        ):
            base = workflow_input("a2a")
            command = RecoveryWorkflowInput(
                **{
                    **base.__dict__,
                    "candidate_action": "SEND_TO_CUSTOMER_AGENT",
                }
            )
            handle = await env.client.start_workflow(
                RecoveryCaseWorkflow.run,
                command,
                id=recovery_workflow_id(command.case_id),
                task_queue=task_queue,
            )
            await handle.signal(
                "a2a_update",
                A2AUpdateSignal(
                    signal_id="a2a-update-1",
                    remote_task_id="remote-task-1",
                    state="AUTH_REQUIRED",
                ),
            )
            await handle.signal(
                "mandate",
                MandateSignal(
                    signal_id="mandate-1",
                    mandate_id="mandate-demo",
                    verified=True,
                    payment_surface_reference="surface-demo",
                    exact_amount_paise=149_900,
                    expires_at=(datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
                    artifact={"protocol_version": "recovery.mandate.v1"},
                ),
            )
            await handle.signal(
                "customer_intent",
                CustomerIntentSignal(
                    signal_id="intent-1",
                    intent="PROMISE_TO_PAY",
                    confidence=0.93,
                ),
            )
            await handle.signal(
                "cancel",
                CancellationSignal(
                    signal_id="cancel-a2a",
                    reason="test complete",
                    requested_by="operator-1",
                ),
            )
            result = await handle.result()

        assert result.outcome == "STOPPED"
        assert result.contact_disposition == "PROMISE_TO_PAY"
        assert result.processed_signal_count == 4
        assert len(services.executed_actions) == 2
        event_types = {event.event_type for event in services.audits}
        assert {
            "A2A_TASK_UPDATED",
            "MANDATE_RECEIVED",
            "CUSTOMER_INTENT_RECORDED",
            "RECOVERY_CANCELLED",
        } <= event_types
