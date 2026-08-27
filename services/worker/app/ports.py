"""Activity-side ports.

Only activities use these interfaces.  Workflow code references activity names
and serializable contracts, keeping provider and persistence dependencies out of
the deterministic sandbox.
"""

from __future__ import annotations

from typing import Protocol

from .contracts import (
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
    ReconciliationInput,
    ReconciliationResult,
    ScoreInput,
    ScoreResult,
)


class RecoveryActivityServices(Protocol):
    async def normalize_failure(self, command: NormalizeFailureInput) -> NormalizedFailure: ...

    async def diagnose_failure(self, command: DiagnosisInput) -> DiagnosisResult: ...

    async def score_recovery(self, command: ScoreInput) -> ScoreResult: ...

    async def evaluate_policy(self, command: PolicyInput) -> PolicyResult: ...

    async def execute_recovery_action(
        self, command: ExecuteActionInput
    ) -> ActionExecutionResult: ...

    async def reconcile_case(self, command: ReconciliationInput) -> ReconciliationResult: ...

    async def record_audit_event(self, command: AuditInput) -> AuditResult: ...

    async def cancel_recovery_action(self, command: CancelActionInput) -> CancelActionResult: ...
