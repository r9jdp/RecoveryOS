"""Prepare and inspect the isolated real-service Playwright scenario.

This helper is intentionally test-only. It starts the seeded case workflow and
lets Playwright prove database and Temporal state without adding debug routes to
the production API.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from temporalio.client import Client
from temporalio.exceptions import WorkflowAlreadyStartedError

from services.api.app.db import get_session_factory
from services.api.app.models import (
    RecoveryActionRecord,
    RecoveryCase,
    RecoveryEventRecord,
    RevenueRecognitionRecord,
)
from services.worker.app.contracts import (
    ProviderEvent,
    RecoveryWorkflowInput,
    RecoveryWorkflowStatus,
)
from services.worker.app.workflow import RecoveryCaseWorkflow, recovery_workflow_id

CASE_ID = "case_fitbox_aug_2026"
MERCHANT_ID = "merchant_fitbox"


async def _client() -> Client:
    return await Client.connect(
        os.getenv("TEMPORAL_ADDRESS", "127.0.0.1:7233"),
        namespace=os.getenv("TEMPORAL_NAMESPACE", "default"),
    )


async def start_workflow() -> dict[str, Any]:
    now = datetime.now(UTC)
    command = RecoveryWorkflowInput(
        case_id=CASE_ID,
        merchant_id=MERCHANT_ID,
        customer_id="customer_fitbox_001",
        subscription_id="sub_fitbox_annual_001",
        failed_invoice_id="inv_fitbox_aug_2026",
        failed_payment_id="pay_fitbox_failed_001",
        amount_at_risk_paise=149_900,
        currency="INR",
        recovery_deadline=(now + timedelta(hours=1)).isoformat(),
        failure_event=ProviderEvent(
            event_id="service-e2e-payment-failed-001",
            event_type="payment.failed",
            occurred_at=now.isoformat(),
            payload={
                "payment_state": "FAILED",
                "subscription_state": "PENDING",
                "reason_code": "BAD_REQUEST_PAYMENT_AUTHENTICATION_FAILED",
                "authoritative": False,
            },
        ),
        candidate_action="OPEN_CUSTOMER_PAYMENT_SURFACE",
        payment_surface_type="SUBSCRIPTION_CARD_UPDATE",
    )
    client = await _client()
    try:
        handle = await client.start_workflow(
            RecoveryCaseWorkflow.run,
            command,
            id=recovery_workflow_id(CASE_ID),
            task_queue=os.getenv("TEMPORAL_TASK_QUEUE", "recovery-os-service-e2e"),
        )
        started = True
    except WorkflowAlreadyStartedError:
        handle = client.get_workflow_handle(recovery_workflow_id(CASE_ID))
        started = False

    status: RecoveryWorkflowStatus | None = None
    for _ in range(80):
        status = await handle.query("status", result_type=RecoveryWorkflowStatus)
        if status.phase == "AWAITING_APPROVAL":
            break
        await asyncio.sleep(0.25)
    if status is None or status.phase != "AWAITING_APPROVAL":
        raise RuntimeError(f"workflow did not reach approval gate: {status!r}")
    return {
        "started": started,
        "workflow_id": recovery_workflow_id(CASE_ID),
        "phase": status.phase,
    }


async def snapshot() -> dict[str, Any]:
    async with get_session_factory()() as session:
        recovery_case = await session.get(RecoveryCase, CASE_ID)
        if recovery_case is None:
            raise RuntimeError("seeded FitBox case is missing")
        action = await session.scalar(
            select(RecoveryActionRecord)
            .where(RecoveryActionRecord.case_id == CASE_ID)
            .order_by(RecoveryActionRecord.created_at.desc())
        )
        revenue_count = await session.scalar(
            select(func.count(RevenueRecognitionRecord.id)).where(
                RevenueRecognitionRecord.case_id == CASE_ID
            )
        )
        event_types = list(
            (
                await session.scalars(
                    select(RecoveryEventRecord.event_type)
                    .where(RecoveryEventRecord.case_id == CASE_ID)
                    .order_by(RecoveryEventRecord.recorded_at, RecoveryEventRecord.id)
                )
            ).all()
        )
        database = {
            "case_outcome": recovery_case.case_outcome.value,
            "payment_state": recovery_case.payment_state.value,
            "arrears_collected_paise": recovery_case.arrears_collected_paise,
            "revenue_attribution": recovery_case.revenue_attribution.value,
            "revenue_recognition_count": int(revenue_count or 0),
            "action_status": action.status.value if action is not None else None,
            "action_external_reference": action.external_reference if action is not None else None,
            "event_types": event_types,
        }

    client = await _client()
    handle = client.get_workflow_handle(recovery_workflow_id(CASE_ID))
    description = await handle.describe()
    status = await handle.query("status", result_type=RecoveryWorkflowStatus)
    temporal = {
        "execution_status": description.status.name
        if description.status is not None
        else "UNKNOWN",
        "phase": status.phase,
        "approval_received": status.approval_received,
        "action_status": status.action_status,
        "outcome": status.outcome,
        "payment_state": status.payment_state,
        "duplicate_signal_count": status.duplicate_signal_count,
    }
    return {"database": database, "temporal": temporal}


async def main(command: str) -> None:
    if command == "start-workflow":
        result = await start_workflow()
    else:
        result = await snapshot()
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("start-workflow", "snapshot"))
    arguments = parser.parse_args()
    asyncio.run(main(arguments.command))
