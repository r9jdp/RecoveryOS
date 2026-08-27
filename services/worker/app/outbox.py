"""Razorpay outbox polling and Temporal handoff for the worker process."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Coroutine
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from temporalio.client import Client, WorkflowHandle
from temporalio.exceptions import WorkflowAlreadyStartedError

from services.api.app.db import get_session_factory
from services.api.app.domain.enums import Diagnosis, SubscriptionState
from services.api.app.integrations.razorpay import create_razorpay_client_from_env
from services.api.app.models import Invoice, PaymentAttempt, RecoveryCase
from services.api.app.webhooks import RazorpayDownstreamSignal, RazorpayOutboxProcessor

from .contracts import PaymentEventSignal, ProviderEvent, RecoveryWorkflowInput
from .workflow import RecoveryCaseWorkflow, recovery_workflow_id

logger = logging.getLogger(__name__)

_CANONICAL_REASON_BY_DIAGNOSIS = {
    Diagnosis.AUTHENTICATION_REQUIRED: "BAD_REQUEST_PAYMENT_AUTHENTICATION_FAILED",
    Diagnosis.INSUFFICIENT_FUNDS: "BAD_REQUEST_PAYMENT_CARD_INSUFFICIENT_BALANCE",
    Diagnosis.INSTRUMENT_INVALID: "BAD_REQUEST_PAYMENT_CARD_EXPIRED",
    Diagnosis.TRANSIENT_RETRYABLE: "GATEWAY_ERROR",
    Diagnosis.MERCHANT_ERROR: "MERCHANT_CONFIGURATION_ERROR",
    Diagnosis.RISK_OR_COMPLIANCE_BLOCK: "RISK_CHECK_FAILED",
}


class TemporalRazorpaySignalDispatcher:
    """Start the invoice workflow once, then deliver idempotent payment signals."""

    def __init__(
        self,
        session: AsyncSession,
        client: Client,
        *,
        task_queue: str,
    ) -> None:
        self.session = session
        self.client = client
        self.task_queue = task_queue

    async def __call__(self, signal: RazorpayDownstreamSignal) -> None:
        if signal.case_id is None:
            # Subscription-only events can legitimately have no invoice-scoped case.
            return
        recovery_case = await self.session.get(RecoveryCase, signal.case_id)
        if recovery_case is None or recovery_case.merchant_id != signal.merchant_id:
            raise RuntimeError("Razorpay signal references an unknown merchant recovery case")

        # A second success event for the same provider payment is already reflected in
        # the database and must not try to signal a workflow that may be terminal.
        if (
            signal.event_type != "payment.failed"
            and signal.effects.get("newly_recognized") is False
        ):
            return
        if signal.event_type == "payment.failed" and signal.effects.get("state_applied") is False:
            return

        command = await self._workflow_input(recovery_case, signal)
        started = False
        try:
            handle = await self.client.start_workflow(
                RecoveryCaseWorkflow.run,
                command,
                id=recovery_workflow_id(recovery_case.id),
                task_queue=self.task_queue,
            )
            started = True
        except WorkflowAlreadyStartedError:
            handle = self.client.get_workflow_handle(recovery_workflow_id(recovery_case.id))

        if signal.event_type == "payment.failed" and started:
            # The first failure is already the workflow's immutable start input.
            return
        await self._signal_payment(handle, signal)

    async def _workflow_input(
        self,
        recovery_case: RecoveryCase,
        signal: RazorpayDownstreamSignal,
    ) -> RecoveryWorkflowInput:
        invoice = (
            await self.session.get(Invoice, recovery_case.failed_invoice_id)
            if recovery_case.failed_invoice_id
            else None
        )
        payment = (
            await self.session.get(PaymentAttempt, recovery_case.failed_payment_id)
            if recovery_case.failed_payment_id
            else None
        )
        if invoice is None:
            raise RuntimeError("Razorpay recovery workflow requires a trusted failed invoice")

        candidate_action = "OPEN_CUSTOMER_PAYMENT_SURFACE"
        payment_surface_type: str | None = "SUBSCRIPTION_INVOICE_LINK"
        if signal.event_type != "payment.failed":
            # A workflow started by a late success must reconcile before it can
            # submit any customer-facing action.
            candidate_action = "WAIT_FOR_GATEWAY_RETRY"
            payment_surface_type = None
        elif recovery_case.subscription_state == SubscriptionState.PENDING:
            if recovery_case.diagnosis in {
                Diagnosis.AUTHENTICATION_REQUIRED,
                Diagnosis.INSTRUMENT_INVALID,
            }:
                payment_surface_type = "SUBSCRIPTION_CARD_UPDATE"
            else:
                candidate_action = "WAIT_FOR_GATEWAY_RETRY"
                payment_surface_type = None

        reason_code = _CANONICAL_REASON_BY_DIAGNOSIS.get(recovery_case.diagnosis)
        return RecoveryWorkflowInput(
            case_id=recovery_case.id,
            merchant_id=recovery_case.merchant_id,
            customer_id=recovery_case.customer_id,
            subscription_id=recovery_case.subscription_id,
            failed_invoice_id=recovery_case.failed_invoice_id,
            failed_payment_id=recovery_case.failed_payment_id,
            amount_at_risk_paise=recovery_case.amount_at_risk_paise,
            currency=invoice.currency,
            recovery_deadline=recovery_case.recovery_deadline.isoformat(),
            failure_event=ProviderEvent(
                event_id=signal.provider_event_id,
                event_type=signal.event_type,
                occurred_at=signal.normalized_event.occurred_at.isoformat(),
                payload={
                    "payment_state": "FAILED",
                    "subscription_state": (
                        SubscriptionState.PENDING.value
                        if recovery_case.subscription_state == SubscriptionState.ACTIVE
                        else recovery_case.subscription_state.value
                    ),
                    "reason_code": reason_code,
                    "authoritative": False,
                    "provider_payment_id": payment.provider_payment_id if payment else None,
                },
            ),
            candidate_action=candidate_action,
            payment_surface_type=payment_surface_type,
        )

    @staticmethod
    async def _signal_payment(
        handle: WorkflowHandle[RecoveryCaseWorkflow, object],
        signal: RazorpayDownstreamSignal,
    ) -> None:
        authoritative = signal.event_type != "payment.failed"
        await handle.signal(
            "payment_event",
            PaymentEventSignal(
                signal_id=signal.idempotency_key,
                provider_event_id=signal.provider_event_id,
                payment_state=signal.normalized_event.payment_state.value,
                amount_paise=signal.normalized_event.amount_paise or 0,
                authoritative=authoritative,
            ),
        )


async def run_razorpay_outbox_poller(client: Client, *, task_queue: str) -> None:
    """Continuously drain durable Razorpay messages while the Temporal worker runs."""

    interval_seconds = max(float(os.getenv("RAZORPAY_OUTBOX_POLL_SECONDS", "0.5")), 0.05)
    provider = create_razorpay_client_from_env()
    session_factory = get_session_factory()
    try:
        while True:
            async with session_factory() as session:
                result = await RazorpayOutboxProcessor(
                    session,
                    provider,
                    TemporalRazorpaySignalDispatcher(session, client, task_queue=task_queue),
                ).process_next()
            if result is None:
                await asyncio.sleep(interval_seconds)
            elif result.status == "FAILED":
                logger.warning(
                    "Razorpay outbox processing failed",
                    extra={
                        "outbox_id": result.outbox_id,
                        "error_code": result.error_code,
                        "attempt_count": result.attempt_count,
                    },
                )
    finally:
        await provider.aclose()


async def run_worker_services(
    worker_run: Coroutine[Any, Any, None], client: Client, *, task_queue: str
) -> None:
    """Run Temporal and the optional provider poller with shared cancellation."""

    worker_task: asyncio.Task[None] = asyncio.create_task(worker_run)
    tasks: set[asyncio.Task[None]] = {worker_task}
    if os.getenv("PAYMENT_PROVIDER", "mock").strip().lower() == "razorpay":
        tasks.add(asyncio.create_task(run_razorpay_outbox_poller(client, task_queue=task_queue)))
    if len(tasks) == 1:
        await worker_task
        return
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    try:
        for task in done:
            task.result()
    finally:
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
