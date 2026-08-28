from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from services.worker.app.activities import MockRecoveryActivityServices, RecoveryActivities
from services.worker.app.contracts import (
    ActionExecutionResult,
    CancellationSignal,
    ExecuteActionInput,
    ProviderEvent,
    RecoveryWorkflowInput,
    RecoveryWorkflowStatus,
)
from services.worker.app.workflow import RecoveryCaseWorkflow, recovery_workflow_id


class UncertainSurfaceServices(MockRecoveryActivityServices):
    async def execute_recovery_action(self, command: ExecuteActionInput) -> ActionExecutionResult:
        self.executed_commands.append(command)
        return ActionExecutionResult(
            status="UNCERTAIN",
            provider="razorpay",
            reason_code="PAYMENT_LINK_RECONCILIATION_UNRESOLVED",
        )


async def test_uncertain_surface_result_keeps_workflow_alive_for_safe_reconciliation() -> None:
    async with await WorkflowEnvironment.start_time_skipping() as environment:
        services = UncertainSurfaceServices(require_manual_approval=False)
        activities = RecoveryActivities(services)
        task_queue = "recovery-uncertain-surface"
        async with Worker(
            environment.client,
            task_queue=task_queue,
            workflows=[RecoveryCaseWorkflow],
            activities=activities.registrations(),
        ):
            now = datetime.now(UTC)
            command = RecoveryWorkflowInput(
                case_id="uncertain-surface",
                merchant_id="merchant-fitbox",
                customer_id="customer-fitbox",
                subscription_id="sub-fitbox",
                failed_invoice_id="inv-uncertain-surface",
                failed_payment_id="pay-uncertain-surface",
                amount_at_risk_paise=149_900,
                currency="INR",
                recovery_deadline=(now + timedelta(hours=1)).isoformat(),
                failure_event=ProviderEvent(
                    event_id="evt-failed-uncertain-surface",
                    event_type="payment.failed",
                    occurred_at=now.isoformat(),
                    payload={
                        "payment_state": "FAILED",
                        "subscription_state": "HALTED",
                        "reason_code": "BAD_REQUEST_PAYMENT_CARD_INSUFFICIENT_BALANCE",
                    },
                ),
                payment_surface_type="STANDARD_PAYMENT_LINK",
            )
            handle = await environment.client.start_workflow(
                RecoveryCaseWorkflow.run,
                command,
                id=recovery_workflow_id(command.case_id),
                task_queue=task_queue,
            )

            for _ in range(100):
                status = await handle.query("status", result_type=RecoveryWorkflowStatus)
                if status.phase == "RECONCILIATION_REQUIRED":
                    break
                await asyncio.sleep(0.01)
            else:
                pytest.fail("workflow did not preserve the uncertain action")

            assert status.action_status == "UNCERTAIN"
            assert len(services.executed_commands) == 1
            await handle.signal(
                "cancel",
                CancellationSignal(
                    signal_id="cancel-uncertain-surface",
                    reason="operator review",
                    requested_by="operator-1",
                ),
            )
            result = await handle.result()

    assert result.outcome == "STOPPED"
