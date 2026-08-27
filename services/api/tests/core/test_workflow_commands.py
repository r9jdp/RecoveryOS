from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

import pytest
from temporalio.client import WorkflowExecutionStatus
from temporalio.service import RPCError, RPCStatusCode

from services.api.app.workflows.commands import (
    TemporalRecoveryWorkflowCommander,
    WorkflowCommandUnavailableError,
)


@dataclass
class FakeDescription:
    status: WorkflowExecutionStatus


class FakeHandle:
    def __init__(
        self,
        *,
        status: WorkflowExecutionStatus = WorkflowExecutionStatus.RUNNING,
        error: Exception | None = None,
    ) -> None:
        self.status = status
        self.error = error
        self.signals: list[tuple[str, object]] = []

    async def describe(self) -> FakeDescription:
        if self.error is not None:
            raise self.error
        return FakeDescription(self.status)

    async def signal(self, name: str, payload: object) -> None:
        if self.error is not None:
            raise self.error
        self.signals.append((name, payload))


class FakeClient:
    def __init__(self, handle: FakeHandle) -> None:
        self.handle = handle
        self.workflow_ids: list[str] = []

    def get_workflow_handle(self, workflow_id: str) -> FakeHandle:
        self.workflow_ids.append(workflow_id)
        return self.handle


def commander_for(handle: FakeHandle) -> TemporalRecoveryWorkflowCommander:
    return TemporalRecoveryWorkflowCommander(cast(Any, FakeClient(handle)))


async def test_each_operator_command_uses_stable_signal_ids() -> None:
    handle = FakeHandle()
    commander = commander_for(handle)

    first = await commander.approval(
        case_id="case-1", action_id="action-1", approved=True, reason=None
    )
    duplicate = await commander.approval(
        case_id="case-1", action_id="action-1", approved=True, reason=None
    )
    rejected = await commander.approval(
        case_id="case-1", action_id="action-1", approved=False, reason="not now"
    )
    stopped = await commander.stop(case_id="case-1", reason="operator stop")
    escalated = await commander.escalate(case_id="case-1", reason="human review")

    assert first.signal_id == duplicate.signal_id == "operator:approve:action-1"
    assert rejected.signal_id == "operator:reject:action-1"
    assert stopped.signal_id == "operator:stop:case-1"
    assert escalated.signal_id == "operator:escalate:case-1"
    assert [name for name, _ in handle.signals] == [
        "approval",
        "approval",
        "approval",
        "cancel",
        "operator_escalation",
    ]


async def test_terminal_workflow_is_reconciled_without_a_blind_signal() -> None:
    handle = FakeHandle(status=WorkflowExecutionStatus.COMPLETED)
    delivery = await commander_for(handle).stop(case_id="case-1", reason="duplicate")

    assert delivery.status == "ALREADY_TERMINAL"
    assert handle.signals == []


async def test_missing_workflow_returns_structured_unavailable_error() -> None:
    handle = FakeHandle(
        error=RPCError("not found", RPCStatusCode.NOT_FOUND, b"not-found")
    )

    with pytest.raises(WorkflowCommandUnavailableError) as rejected:
        await commander_for(handle).escalate(case_id="case-missing", reason="review")

    assert rejected.value.metadata == {
        "case_id": "case-missing",
        "workflow_id": "recovery-case:case-missing",
        "signal_id": "operator:escalate:case-missing",
        "reason": "WORKFLOW_NOT_FOUND",
    }
