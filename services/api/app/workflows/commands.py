"""Idempotent command delivery to the workflow that owns a recovery case.

The API never starts a workflow here: only the durable webhook/outbox path has
the trusted invoice, payment and failure payload required for immutable workflow
input.  A missing execution is therefore an explicit recoverable error rather
than an excuse to start a second, partially initialized coordinator.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.service import RPCError, RPCStatusCode

from services.api.app.services.cases import ApplicationServiceError
from services.worker.app.contracts import (
    ApprovalSignal,
    CancellationSignal,
    OperatorEscalationSignal,
)
from services.worker.app.workflow import recovery_workflow_id


class WorkflowCommandUnavailableError(ApplicationServiceError):
    """A command could not be handed to its existing durable coordinator."""

    code = "RECOVERY_WORKFLOW_UNAVAILABLE"
    status_code = 503


@dataclass(frozen=True, slots=True)
class WorkflowCommandDelivery:
    workflow_id: str
    signal_id: str
    status: str


class RecoveryWorkflowCommander(Protocol):
    async def approval(
        self,
        *,
        case_id: str,
        action_id: str,
        approved: bool,
        reason: str | None,
    ) -> WorkflowCommandDelivery: ...

    async def stop(self, *, case_id: str, reason: str) -> WorkflowCommandDelivery: ...

    async def escalate(self, *, case_id: str, reason: str) -> WorkflowCommandDelivery: ...


class TemporalRecoveryWorkflowCommander:
    """Deliver deterministic signals without invoking provider code in the API."""

    def __init__(self, client: Client) -> None:
        self._client = client

    async def approval(
        self,
        *,
        case_id: str,
        action_id: str,
        approved: bool,
        reason: str | None,
    ) -> WorkflowCommandDelivery:
        signal_id = f"operator:{'approve' if approved else 'reject'}:{action_id}"
        return await self._deliver(
            case_id=case_id,
            signal_name="approval",
            signal_id=signal_id,
            payload=ApprovalSignal(
                signal_id=signal_id,
                approved=approved,
                reviewer_id="merchant-operator",
                reason=reason,
            ),
        )

    async def stop(self, *, case_id: str, reason: str) -> WorkflowCommandDelivery:
        signal_id = f"operator:stop:{case_id}"
        return await self._deliver(
            case_id=case_id,
            signal_name="cancel",
            signal_id=signal_id,
            payload=CancellationSignal(
                signal_id=signal_id,
                reason=reason,
                requested_by="merchant-operator",
            ),
        )

    async def escalate(self, *, case_id: str, reason: str) -> WorkflowCommandDelivery:
        signal_id = f"operator:escalate:{case_id}"
        return await self._deliver(
            case_id=case_id,
            signal_name="operator_escalation",
            signal_id=signal_id,
            payload=OperatorEscalationSignal(
                signal_id=signal_id,
                reason=reason,
                requested_by="merchant-operator",
            ),
        )

    async def _deliver(
        self,
        *,
        case_id: str,
        signal_name: str,
        signal_id: str,
        payload: object,
    ) -> WorkflowCommandDelivery:
        workflow_id = recovery_workflow_id(case_id)
        handle = self._client.get_workflow_handle(workflow_id)
        try:
            description = await handle.describe()
            if description.status != WorkflowExecutionStatus.RUNNING:
                # A retry may arrive after the first command made the workflow
                # terminal. Persistence remains the authority for whether the
                # requested state transition itself is idempotently acceptable.
                return WorkflowCommandDelivery(workflow_id, signal_id, "ALREADY_TERMINAL")
            await handle.signal(signal_name, payload)
        except RPCError as exc:
            if exc.status == RPCStatusCode.NOT_FOUND:
                reason = "WORKFLOW_NOT_FOUND"
            elif exc.status == RPCStatusCode.FAILED_PRECONDITION:
                reason = "WORKFLOW_CLOSED_DURING_DELIVERY"
            else:
                reason = "TEMPORAL_RPC_FAILED"
            raise WorkflowCommandUnavailableError(
                "The recovery workflow could not accept the operator command.",
                metadata={
                    "case_id": case_id,
                    "workflow_id": workflow_id,
                    "signal_id": signal_id,
                    "reason": reason,
                },
            ) from exc
        except Exception as exc:
            raise WorkflowCommandUnavailableError(
                "The recovery workflow could not accept the operator command.",
                metadata={
                    "case_id": case_id,
                    "workflow_id": workflow_id,
                    "signal_id": signal_id,
                    "reason": "DELIVERY_FAILED",
                },
            ) from exc
        return WorkflowCommandDelivery(workflow_id, signal_id, "DELIVERED")


async def get_recovery_workflow_commander() -> RecoveryWorkflowCommander:
    """Construct the server-only Temporal command client from shared settings."""

    address = os.getenv("TEMPORAL_ADDRESS", "localhost:7233").strip()
    namespace = os.getenv("TEMPORAL_NAMESPACE", "default").strip()
    api_key = os.getenv("TEMPORAL_API_KEY", "").strip() or None
    use_tls = os.getenv("TEMPORAL_TLS", "false").strip().lower() in {"1", "true", "yes"}
    client = await Client.connect(
        address,
        namespace=namespace,
        api_key=api_key,
        tls=use_tls,
    )
    return TemporalRecoveryWorkflowCommander(client)
