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
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from temporalio.client import Client
from temporalio.exceptions import WorkflowAlreadyStartedError

from services.api.app.db import get_session_factory
from services.api.app.domain.enums import (
    ActionStatus,
    CaseOutcome,
    ContactDisposition,
    Diagnosis,
    PaymentState,
    PolicyDisposition,
    RecoveryActionType,
    RevenueAttribution,
    SubscriptionState,
)
from services.api.app.models import (
    A2AMandateNonceConsumption,
    CustomerAgentTaskRecord,
    Invoice,
    PolicyDecisionRecord,
    RecoveryActionRecord,
    RecoveryCase,
    RecoveryEventRecord,
    RevenueRecognitionRecord,
)
from services.worker.app.a2a_runtime import create_live_a2a_services_from_env
from services.worker.app.contracts import (
    PollA2AMandateInput,
    ProviderEvent,
    RecoveryWorkflowInput,
    RecoveryWorkflowStatus,
)
from services.worker.app.workflow import RecoveryCaseWorkflow, recovery_workflow_id

CASE_ID = "case_fitbox_aug_2026"
MERCHANT_ID = "merchant_fitbox"
A2A_CASE_ID = "case_fitbox_a2a_service_e2e"
A2A_INVOICE_ID = "inv_fitbox_a2a_service_e2e"
A2A_ACTION_ID = "action_fitbox_a2a_delegation_service_e2e"
A2A_ACTION_POLICY_ID = "policy_fitbox_a2a_delegation_service_e2e"
A2A_BILLING_CYCLE = "service-e2e-a2a"
A2A_AMOUNT_PAISE = 149_900


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


async def _ensure_a2a_case() -> datetime:
    now = datetime.now(UTC)
    deadline = now + timedelta(minutes=30)
    async with get_session_factory()() as session:
        existing = await session.get(RecoveryCase, A2A_CASE_ID)
        if existing is not None:
            return existing.recovery_deadline

        invoice = Invoice(
            id=A2A_INVOICE_ID,
            merchant_id=MERCHANT_ID,
            subscription_id="sub_fitbox_annual_001",
            provider_invoice_id=A2A_INVOICE_ID,
            billing_cycle_key=A2A_BILLING_CYCLE,
            amount_paise=A2A_AMOUNT_PAISE,
            amount_paid_paise=0,
            currency="INR",
            invoice_state="issued",
            due_at=now,
        )
        recovery_case = RecoveryCase(
            id=A2A_CASE_ID,
            merchant_id=MERCHANT_ID,
            customer_id="customer_fitbox_001",
            subscription_id="sub_fitbox_annual_001",
            failed_invoice_id=A2A_INVOICE_ID,
            billing_cycle_key=A2A_BILLING_CYCLE,
            failed_payment_id=None,
            case_outcome=CaseOutcome.OPEN,
            payment_state=PaymentState.FAILED,
            subscription_state=SubscriptionState.PENDING,
            contact_disposition=ContactDisposition.NOT_CONTACTED,
            revenue_attribution=RevenueAttribution.NONE,
            diagnosis=Diagnosis.AUTHENTICATION_REQUIRED,
            amount_at_risk_paise=A2A_AMOUNT_PAISE,
            arrears_collected_paise=0,
            case_recovered=False,
            subscription_reactivated=False,
            opened_at=now,
            recovery_deadline=deadline,
            version=1,
        )
        action = RecoveryActionRecord(
            id=A2A_ACTION_ID,
            case_id=A2A_CASE_ID,
            action_type=RecoveryActionType.SEND_TO_CUSTOMER_AGENT,
            payment_surface_type=None,
            status=ActionStatus.PROPOSED,
            idempotency_key=f"{A2A_CASE_ID}:SEND_TO_CUSTOMER_AGENT:v2",
            created_at=now,
            updated_at=now,
        )
        action_policy = PolicyDecisionRecord(
            id=A2A_ACTION_POLICY_ID,
            case_id=A2A_CASE_ID,
            action_id=A2A_ACTION_ID,
            disposition=PolicyDisposition.ALLOW,
            decision_code="A2A_EXACT_INVOICE_ALLOWED",
            reason_codes=["A2A_EXACT_INVOICE_ALLOWED"],
            reasons=["The customer agent may authorize only the persisted invoice surface."],
            policy_version="service-e2e.v2",
            created_at=now,
        )
        for record in (
            invoice,
            recovery_case,
            action,
            action_policy,
        ):
            session.add(record)
            await session.flush()
        await session.commit()
    return deadline


async def start_a2a_workflow() -> dict[str, Any]:
    deadline = await _ensure_a2a_case()
    now = datetime.now(UTC)
    command = RecoveryWorkflowInput(
        case_id=A2A_CASE_ID,
        merchant_id=MERCHANT_ID,
        customer_id="customer_fitbox_001",
        subscription_id="sub_fitbox_annual_001",
        failed_invoice_id=A2A_INVOICE_ID,
        failed_payment_id=None,
        amount_at_risk_paise=A2A_AMOUNT_PAISE,
        currency="INR",
        recovery_deadline=deadline.isoformat(),
        failure_event=ProviderEvent(
            event_id="service-e2e-a2a-payment-failed-001",
            event_type="payment.failed",
            occurred_at=now.isoformat(),
            payload={
                "payment_state": "FAILED",
                "subscription_state": "PENDING",
                "reason_code": "BAD_REQUEST_PAYMENT_AUTHENTICATION_FAILED",
                "authoritative": False,
            },
        ),
        candidate_action="SEND_TO_CUSTOMER_AGENT",
        payment_surface_type="SUBSCRIPTION_INVOICE_LINK",
        payment_surface_reference=A2A_INVOICE_ID,
        provider_subscription_id="sub_fitbox_annual_001",
        provider_invoice_id=A2A_INVOICE_ID,
        recovery_action_id=A2A_ACTION_ID,
    )
    client = await _client()
    try:
        handle = await client.start_workflow(
            RecoveryCaseWorkflow.run,
            command,
            id=recovery_workflow_id(A2A_CASE_ID),
            task_queue=os.getenv("TEMPORAL_TASK_QUEUE", "recovery-os-service-e2e"),
        )
    except WorkflowAlreadyStartedError:
        handle = client.get_workflow_handle(recovery_workflow_id(A2A_CASE_ID))

    status: RecoveryWorkflowStatus | None = None
    for _ in range(80):
        status = await handle.query("status", result_type=RecoveryWorkflowStatus)
        if status.provider_reference is not None:
            break
        await asyncio.sleep(0.25)
    if status is None:
        raise RuntimeError("A2A workflow did not become queryable")

    for _ in range(120):
        status = await handle.query("status", result_type=RecoveryWorkflowStatus)
        if status.provider_reference is not None and status.a2a_state == "AUTH_REQUIRED":
            break
        await asyncio.sleep(0.25)
    if status.provider_reference is None or status.a2a_state != "AUTH_REQUIRED":
        raise RuntimeError(f"A2A workflow did not create an authorization task: {status!r}")
    return {
        "workflow_id": recovery_workflow_id(A2A_CASE_ID),
        "task_id": status.provider_reference,
        "case_id": A2A_CASE_ID,
        "merchant_id": MERCHANT_ID,
        "customer_id": "customer_fitbox_001",
        "exact_amount_paise": A2A_AMOUNT_PAISE,
        "recovery_action_id": A2A_ACTION_ID,
        "failed_invoice_id": A2A_INVOICE_ID,
        "currency": "INR",
        "payment_surface_type": "SUBSCRIPTION_INVOICE_LINK",
        "payment_surface_reference": A2A_INVOICE_ID,
        "recovery_deadline": deadline.isoformat(),
    }


async def a2a_snapshot() -> dict[str, Any]:
    async with get_session_factory()() as session:
        action = await session.get(RecoveryActionRecord, A2A_ACTION_ID)
        recovery_case = await session.get(RecoveryCase, A2A_CASE_ID)
        task = await session.scalar(
            select(CustomerAgentTaskRecord).where(
                CustomerAgentTaskRecord.idempotency_key
                == f"{A2A_CASE_ID}:SEND_TO_CUSTOMER_AGENT:{A2A_ACTION_ID}:v2"
            )
        )
        nonce_count = await session.scalar(
            select(func.count(A2AMandateNonceConsumption.nonce)).where(
                A2AMandateNonceConsumption.case_id == A2A_CASE_ID
            )
        )
        revenue_count = await session.scalar(
            select(func.count(RevenueRecognitionRecord.id)).where(
                RevenueRecognitionRecord.case_id == A2A_CASE_ID
            )
        )
    receipt_count = 0
    if task is not None:
        for artifact in task.payload.get("artifacts", []):
            for part in artifact.get("parts", []):
                data = part.get("data", {})
                signed_data = data.get("data", {})
                if (
                    data.get("algorithm") == "Ed25519"
                    and isinstance(signed_data, dict)
                    and signed_data.get("protocol_version") == "recovery.receipt.v2"
                ):
                    receipt_count += 1
    client = await _client()
    handle = client.get_workflow_handle(recovery_workflow_id(A2A_CASE_ID))
    status = await handle.query("status", result_type=RecoveryWorkflowStatus)
    return {
        "database": {
            "action_status": action.status.value if action is not None else None,
            "action_external_reference": (
                action.external_reference if action is not None else None
            ),
            "customer_task_id": task.task_id if task is not None else None,
            "customer_task_state": task.state if task is not None else None,
            "customer_task_version": task.version if task is not None else None,
            "customer_task_receipt_count": receipt_count,
            "nonce_consumption_count": int(nonce_count or 0),
            "case_outcome": recovery_case.case_outcome.value if recovery_case is not None else None,
            "revenue_recognition_count": int(revenue_count or 0),
        },
        "temporal": {
            "phase": status.phase,
            "action": status.action,
            "action_status": status.action_status,
            "provider_reference": status.provider_reference,
            "a2a_state": status.a2a_state,
            "mandate_received": status.mandate_received,
            "outcome": status.outcome,
        },
    }


async def replay_a2a_mandate() -> dict[str, Any]:
    state = await a2a_snapshot()
    task_id = state["database"]["customer_task_id"]
    if not isinstance(task_id, str):
        raise RuntimeError("A2A task is not persisted")
    recovery_case_deadline = await _ensure_a2a_case()
    services = create_live_a2a_services_from_env()
    result = await services.poll_and_verify_mandate(
        PollA2AMandateInput(
            remote_task_id=task_id,
            case_id=A2A_CASE_ID,
            merchant_id=MERCHANT_ID,
            customer_id="customer_fitbox_001",
            exact_amount_paise=A2A_AMOUNT_PAISE,
            currency="INR",
            payment_surface_type="SUBSCRIPTION_INVOICE_LINK",
            payment_surface_reference=A2A_INVOICE_ID,
            recovery_deadline=recovery_case_deadline.isoformat(),
            recovery_action_id=A2A_ACTION_ID,
            failed_invoice_id=A2A_INVOICE_ID,
            provider_invoice_id=A2A_INVOICE_ID,
        )
    )
    return asdict(result)


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
    elif command == "snapshot":
        result = await snapshot()
    elif command == "start-a2a-workflow":
        result = await start_a2a_workflow()
    elif command == "a2a-snapshot":
        result = await a2a_snapshot()
    else:
        result = await replay_a2a_mandate()
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=(
            "start-workflow",
            "snapshot",
            "start-a2a-workflow",
            "a2a-snapshot",
            "replay-a2a-mandate",
        ),
    )
    arguments = parser.parse_args()
    asyncio.run(main(arguments.command))
