from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from services.api.app.domain.enums import (
    ActionStatus,
    PaymentState,
    PolicyDisposition,
    RecoveryActionType,
    SubscriptionState,
)
from services.api.app.integrations.razorpay.signature import webhook_signature
from services.api.app.models import (
    OutboxMessage,
    PolicyDecisionRecord,
    RecoveryActionRecord,
    RecoveryCase,
)
from services.api.app.providers.contracts import (
    OpenPaymentSurfaceRequest,
    PaymentSnapshot,
    PaymentSurfaceResult,
    RecoveryScoreRequest,
    RecoveryScoreResult,
)
from services.api.app.seed import FITBOX_CASE_ID, seed_fitbox
from services.api.app.webhooks.processor import RazorpayOutboxProcessor
from services.api.app.webhooks.razorpay import RazorpayWebhookIngestionService
from services.api.app.webhooks.repository import InboxOutboxStore
from services.worker.app.activities import RecoveryActivities
from services.worker.app.contracts import (
    ActionExecutionResult,
    AuditInput,
    AuditResult,
    CancelActionInput,
    CancelActionResult,
    ExecuteActionInput,
    ReconciliationInput,
    ReconciliationResult,
    RecoveryWorkflowResult,
)
from services.worker.app.outbox import TemporalRazorpaySignalDispatcher
from services.worker.app.runtime import ProductionRecoveryActivityServices
from services.worker.app.workflow import RecoveryCaseWorkflow, recovery_workflow_id

FIXTURE = Path("services/api/tests/fixtures/razorpay/payment.captured.json")
SECRET = "late_success_test_secret"


class RecordingPaymentProvider:
    def __init__(self) -> None:
        self.open_requests: list[OpenPaymentSurfaceRequest] = []
        self.fetch_count = 0

    async def open_customer_payment_surface(
        self, request: OpenPaymentSurfaceRequest
    ) -> PaymentSurfaceResult:
        self.open_requests.append(request)
        raise AssertionError("late success must not open a customer payment surface")

    async def fetch_payment_snapshot(
        self, *, merchant_id: str, payment_id: str | None, invoice_id: str
    ) -> PaymentSnapshot:
        del merchant_id, payment_id, invoice_id
        self.fetch_count += 1
        return PaymentSnapshot(
            provider="razorpay",
            payment_id="pay_fitbox_recovered_001",
            invoice_id="inv_fitbox_aug_2026",
            subscription_id="sub_fitbox_annual_001",
            payment_state=PaymentState.CAPTURED,
            subscription_state=SubscriptionState.ACTIVE,
            amount_paise=149_900,
            currency="INR",
            observed_at=datetime.now(UTC),
            authoritative=True,
        )


class FixedScorer:
    async def score(self, request: RecoveryScoreRequest) -> RecoveryScoreResult:
        return RecoveryScoreResult(
            model_name="late-success-test",
            model_version="v1",
            recovery_probability=1.0,
            expected_recovered_paise=request.amount_at_risk_paise,
            expected_utility_paise=request.amount_at_risk_paise,
        )


class LateSuccessActivityServices(ProductionRecoveryActivityServices):
    def __init__(self, payment_provider: RecordingPaymentProvider) -> None:
        super().__init__(payment_provider=payment_provider, scorer=FixedScorer())
        self.executions: list[ExecuteActionInput] = []
        self.cancellations: list[CancelActionInput] = []
        self.audits: list[AuditInput] = []

    async def execute_recovery_action(self, command: ExecuteActionInput) -> ActionExecutionResult:
        self.executions.append(command)
        raise AssertionError("reconciliation-only startup must not execute a provider action")

    async def reconcile_case(self, command: ReconciliationInput) -> ReconciliationResult:
        assert command.authoritative_hint is True
        assert command.payment_state_hint == PaymentState.CAPTURED.value
        return ReconciliationResult(
            payment_state=PaymentState.CAPTURED.value,
            subscription_state=SubscriptionState.ACTIVE.value,
            authoritative=True,
            case_recovered=True,
            arrears_collected_paise=149_900,
            subscription_reactivated=True,
            provider_reference="pay_fitbox_recovered_001",
        )

    async def record_audit_event(self, command: AuditInput) -> AuditResult:
        self.audits.append(command)
        return AuditResult(audit_event_id=f"audit-{len(self.audits)}", recorded=True)

    async def cancel_recovery_action(self, command: CancelActionInput) -> CancelActionResult:
        self.cancellations.append(command)
        return CancelActionResult(cancelled=True, reason_code="AUTHORITATIVE_PAYMENT_SUCCESS")


@pytest.mark.asyncio
async def test_late_success_starts_reconciliation_only_workflow_and_cancels_cleanup(
    processor_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = processor_session
    await seed_fitbox(session)
    raw_body = json.dumps(
        json.loads(FIXTURE.read_text(encoding="utf-8")), separators=(",", ":")
    ).encode()
    await RazorpayWebhookIngestionService(InboxOutboxStore(session)).ingest(
        merchant_id="merchant_fitbox",
        raw_body=raw_body,
        signature=webhook_signature(raw_body, SECRET),
        provider_event_id="evt_late_success_workflow",
        webhook_secret=SECRET,
    )
    assert session.bind is not None
    verification_sessions = async_sessionmaker(session.bind, expire_on_commit=False)
    monkeypatch.setattr(
        "services.worker.app.runtime.get_session_factory", lambda: verification_sessions
    )
    provider = RecordingPaymentProvider()
    services = LateSuccessActivityServices(provider)

    async with await WorkflowEnvironment.start_time_skipping() as environment:
        task_queue = "late-success-reconciliation-only"
        activities = RecoveryActivities(services)
        async with Worker(
            environment.client,
            task_queue=task_queue,
            workflows=[RecoveryCaseWorkflow],
            activities=activities.registrations(),
        ):
            dispatcher = TemporalRazorpaySignalDispatcher(
                session,
                environment.client,
                task_queue=task_queue,
            )
            processed = await RazorpayOutboxProcessor(
                session,
                provider,
                dispatcher,
            ).process_next()
            assert processed is not None and processed.status == "PUBLISHED"
            handle = environment.client.get_workflow_handle(
                recovery_workflow_id(FITBOX_CASE_ID),
                result_type=RecoveryWorkflowResult,
            )
            workflow_result = await handle.result()

    recovery_case = await session.get(RecoveryCase, FITBOX_CASE_ID)
    original_surface_action = await session.get(
        RecoveryActionRecord, "action_fitbox_card_update_001"
    )
    reconciliation_action = await session.scalar(
        select(RecoveryActionRecord).where(
            RecoveryActionRecord.case_id == FITBOX_CASE_ID,
            RecoveryActionRecord.action_type == RecoveryActionType.WAIT_FOR_GATEWAY_RETRY,
            RecoveryActionRecord.idempotency_key.like(
                "%purpose:authoritative-success-reconciliation"
            ),
        )
    )
    assert reconciliation_action is not None
    reconciliation_policy = await session.scalar(
        select(PolicyDecisionRecord).where(
            PolicyDecisionRecord.action_id == reconciliation_action.id
        )
    )
    outbox = await session.scalar(
        select(OutboxMessage).where(OutboxMessage.deduplication_key.like("razorpay:%"))
    )
    assert recovery_case is not None and recovery_case.case_recovered is True
    assert recovery_case.payment_state == PaymentState.CAPTURED
    assert original_surface_action is not None
    assert original_surface_action.status == ActionStatus.CANCELLED
    assert reconciliation_action.payment_surface_type is None
    assert reconciliation_policy is not None
    assert reconciliation_policy.disposition == PolicyDisposition.ALLOW
    assert reconciliation_policy.decision_code == "AUTHORITATIVE_PAYMENT_RECONCILIATION_ONLY"
    assert outbox is not None and outbox.published_at is not None
    assert workflow_result.outcome == "RECOVERED"
    assert workflow_result.case_recovered is True
    assert services.executions == []
    assert len(services.cancellations) == 1
    assert services.cancellations[0].reason == "AUTHORITATIVE_PAYMENT_SUCCESS"
    assert services.cancellations[0].provider_reference is None
    assert provider.open_requests == []
    assert provider.fetch_count == 1
    policy_audit = next(audit for audit in services.audits if audit.event_type == "POLICY_DECIDED")
    assert policy_audit.details["decision_code"] == "AUTHORITATIVE_PAYMENT_RECONCILIATION_ONLY"
    assert any(audit.event_type == "PAYMENT_RECONCILED" for audit in services.audits)


@pytest.mark.asyncio
async def test_same_late_success_retries_dispatch_without_duplicate_authorization(
    processor_session: AsyncSession,
) -> None:
    session = processor_session
    await seed_fitbox(session)
    raw_body = FIXTURE.read_bytes()
    await RazorpayWebhookIngestionService(InboxOutboxStore(session)).ingest(
        merchant_id="merchant_fitbox",
        raw_body=raw_body,
        signature=webhook_signature(raw_body, SECRET),
        provider_event_id="evt_late_success_retry",
        webhook_secret=SECRET,
    )
    provider = RecordingPaymentProvider()
    fail = True

    async def callback(signal: object) -> None:
        nonlocal fail
        del signal
        if fail:
            fail = False
            raise RuntimeError("simulated Temporal start outage")

    processor = RazorpayOutboxProcessor(
        session,
        provider,
        callback,
        retry_base_delay=datetime.resolution,
    )
    failed = await processor.process_next()
    assert failed is not None and failed.status == "FAILED"
    succeeded = await processor.process_next()
    assert succeeded is not None and succeeded.status == "PUBLISHED"
    action_count = len(
        (
            await session.scalars(
                select(RecoveryActionRecord).where(
                    RecoveryActionRecord.idempotency_key.like(
                        "%purpose:authoritative-success-reconciliation"
                    )
                )
            )
        ).all()
    )
    policy_count = len(
        (
            await session.scalars(
                select(PolicyDecisionRecord).where(
                    PolicyDecisionRecord.decision_code
                    == "AUTHORITATIVE_PAYMENT_RECONCILIATION_ONLY"
                )
            )
        ).all()
    )
    assert action_count == policy_count == 1
    assert provider.fetch_count == 2
