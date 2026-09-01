from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from services.api.app.domain.enums import (
    ActionStatus,
    PaymentSurfaceType,
    PolicyDisposition,
    RecoveryActionType,
)
from services.api.app.models import PolicyDecisionRecord, RecoveryActionRecord
from services.api.app.providers.contracts import (
    OpenPaymentSurfaceRequest,
    PaymentSnapshot,
    PaymentSurfaceResult,
    RecoveryScoreRequest,
    RecoveryScoreResult,
)
from services.api.app.repositories import CaseRepository
from services.api.app.seed import FITBOX_CASE_ID, seed_fitbox
from services.api.app.services.cases import RecoveryCaseService
from services.api.app.services.mock_payment import MockPaymentProvider
from services.worker.app.contracts import CancelActionInput, ExecuteActionInput, PolicyInput
from services.worker.app.runtime import ProductionRecoveryActivityServices

TEST_NOW = datetime(2026, 8, 27, 11, 0, tzinfo=UTC)


class RecordingPaymentProvider:
    def __init__(self) -> None:
        self.requests: list[OpenPaymentSurfaceRequest] = []

    async def open_customer_payment_surface(
        self, request: OpenPaymentSurfaceRequest
    ) -> PaymentSurfaceResult:
        self.requests.append(request)
        return PaymentSurfaceResult(
            provider="mock-recording",
            provider_reference="surface-authorized",
            surface_type=request.surface_type,
            customer_url="https://mock.invalid/surface-authorized",
        )

    async def fetch_payment_snapshot(
        self, *, merchant_id: str, payment_id: str | None, invoice_id: str
    ) -> PaymentSnapshot:
        raise AssertionError("not used")


class BlockingPaymentProvider(RecordingPaymentProvider):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def open_customer_payment_surface(
        self, request: OpenPaymentSurfaceRequest
    ) -> PaymentSurfaceResult:
        self.requests.append(request)
        self.started.set()
        await self.release.wait()
        return PaymentSurfaceResult(
            provider="mock-recording",
            provider_reference="surface-authorized",
            surface_type=request.surface_type,
            customer_url="https://mock.invalid/surface-authorized",
        )


class FixedScorer:
    async def score(self, request: RecoveryScoreRequest) -> RecoveryScoreResult:
        return RecoveryScoreResult(
            model_name="fixed",
            model_version="test",
            recovery_probability=0.5,
            expected_recovered_paise=request.amount_at_risk_paise // 2,
            expected_utility_paise=request.amount_at_risk_paise // 2,
        )


class RecordingVoiceService:
    def __init__(self, status: str) -> None:
        self.status = status
        self.calls: list[dict[str, object]] = []

    async def cancel_for_authoritative_payment(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return SimpleNamespace(
            status=self.status,
            reason_code=(
                "VOICE_CANCELLATION_UNCERTAIN_RECONCILE_REQUIRED"
                if self.status == "UNCERTAIN"
                else None
            ),
        )


class RecordingVoiceResources:
    def __init__(self, service: RecordingVoiceService) -> None:
        self.service = service
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


def payment_command() -> ExecuteActionInput:
    return ExecuteActionInput(
        case_id=FITBOX_CASE_ID,
        merchant_id="merchant_fitbox",
        customer_id="customer_fitbox",
        subscription_id="sub_fitbox_monthly",
        failed_invoice_id="inv_fitbox_aug_2026",
        provider_subscription_id="sub_fitbox_monthly",
        provider_invoice_id="inv_fitbox_aug_2026",
        amount_paise=149_900,
        currency="INR",
        action="OPEN_CUSTOMER_PAYMENT_SURFACE",
        payment_surface_type="SUBSCRIPTION_CARD_UPDATE",
        recovery_deadline=(datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        idempotency_key=f"{FITBOX_CASE_ID}:OPEN_CUSTOMER_PAYMENT_SURFACE:1",
    )


def policy_command() -> PolicyInput:
    return PolicyInput(
        case_id=FITBOX_CASE_ID,
        merchant_id="merchant_fitbox",
        amount_at_risk_paise=149_900,
        diagnosis="AUTHENTICATION_REQUIRED",
        candidate_action="OPEN_CUSTOMER_PAYMENT_SURFACE",
        payment_surface_type="SUBSCRIPTION_CARD_UPDATE",
        recovery_deadline=(TEST_NOW + timedelta(hours=1)).isoformat(),
    )


async def action_and_policy(
    session: AsyncSession,
) -> tuple[RecoveryActionRecord, PolicyDecisionRecord]:
    from sqlalchemy import select

    action = await session.scalar(
        select(RecoveryActionRecord).where(
            RecoveryActionRecord.case_id == FITBOX_CASE_ID,
            RecoveryActionRecord.payment_surface_type
            == PaymentSurfaceType.SUBSCRIPTION_CARD_UPDATE,
        )
    )
    assert action is not None
    policy = await session.scalar(
        select(PolicyDecisionRecord).where(PolicyDecisionRecord.action_id == action.id)
    )
    assert policy is not None
    return action, policy


async def test_persisted_manual_policy_requires_schedule_then_authorizes_once(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    async with session_factory() as session:
        await seed_fitbox(session)
    monkeypatch.setattr("services.worker.app.runtime.get_session_factory", lambda: session_factory)
    provider = RecordingPaymentProvider()
    services = ProductionRecoveryActivityServices(
        payment_provider=provider,
        scorer=FixedScorer(),
        clock=lambda: TEST_NOW,
    )

    policy = await services.evaluate_policy(policy_command())
    blocked = await services.execute_recovery_action(payment_command())
    async with session_factory() as session:
        action, _ = await action_and_policy(session)
        action.status = ActionStatus.SCHEDULED
        await session.commit()
    submitted = await services.execute_recovery_action(payment_command())
    duplicate = await services.execute_recovery_action(payment_command())

    assert policy.disposition == "REQUIRE_MANUAL_APPROVAL"
    assert policy.decision_code == "FITBOX_DEMO_APPROVAL_REQUIRED"
    assert blocked.status == "REJECTED"
    assert blocked.reason_code == "ACTION_NOT_AUTHORIZED"
    assert submitted.status == duplicate.status == "SUCCEEDED"
    assert submitted.provider_reference == duplicate.provider_reference == "surface-authorized"
    assert len(provider.requests) == 1


async def test_a2a_policy_uses_nullable_persisted_surface_but_keeps_exact_workflow_scope(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    async with session_factory() as session:
        await seed_fitbox(session)
        action = RecoveryActionRecord(
            id="action_a2a_policy",
            case_id=FITBOX_CASE_ID,
            action_type=RecoveryActionType.SEND_TO_CUSTOMER_AGENT,
            payment_surface_type=None,
            status=ActionStatus.AWAITING_APPROVAL,
            idempotency_key=f"{FITBOX_CASE_ID}:SEND_TO_CUSTOMER_AGENT:action-fitbox:v2",
            created_at=TEST_NOW,
            updated_at=TEST_NOW,
        )
        session.add(action)
        await session.flush()
        session.add(
            PolicyDecisionRecord(
                id="policy_a2a_policy",
                case_id=FITBOX_CASE_ID,
                action_id=action.id,
                disposition=PolicyDisposition.REQUIRE_MANUAL_APPROVAL,
                decision_code="A2A_REQUIRES_APPROVAL",
                reason_codes=["A2A_REQUIRES_APPROVAL"],
                reasons=["Customer-agent delegation requires operator approval."],
                policy_version="policy-v1",
                created_at=TEST_NOW,
            )
        )
        await session.commit()

    monkeypatch.setattr("services.worker.app.runtime.get_session_factory", lambda: session_factory)
    services = ProductionRecoveryActivityServices(
        payment_provider=RecordingPaymentProvider(),
        scorer=FixedScorer(),
        clock=lambda: TEST_NOW,
    )
    command = PolicyInput(
        case_id=FITBOX_CASE_ID,
        merchant_id="merchant_fitbox",
        amount_at_risk_paise=149_900,
        diagnosis="AUTHENTICATION_REQUIRED",
        candidate_action="SEND_TO_CUSTOMER_AGENT",
        payment_surface_type="SUBSCRIPTION_INVOICE_LINK",
        recovery_deadline=(TEST_NOW + timedelta(hours=1)).isoformat(),
    )

    policy = await services.evaluate_policy(command)

    assert policy.disposition == "REQUIRE_MANUAL_APPROVAL"
    assert policy.action == "SEND_TO_CUSTOMER_AGENT"
    assert policy.payment_surface_type is None


async def test_future_delay_is_rejected_until_both_policy_and_action_are_due(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    due_at = TEST_NOW + timedelta(minutes=15)
    async with session_factory() as session:
        await seed_fitbox(session)
        action, policy = await action_and_policy(session)
        action.status = ActionStatus.SCHEDULED
        action.scheduled_for = due_at
        policy.disposition = PolicyDisposition.DELAY
        policy.decision_code = "QUIET_HOURS"
        policy.delay_until = due_at
        await session.commit()
    monkeypatch.setattr("services.worker.app.runtime.get_session_factory", lambda: session_factory)
    instants = [TEST_NOW]
    provider = RecordingPaymentProvider()
    services = ProductionRecoveryActivityServices(
        payment_provider=provider,
        scorer=FixedScorer(),
        clock=lambda: instants[0],
    )

    durable_policy = await services.evaluate_policy(policy_command())
    early = await services.execute_recovery_action(payment_command())
    instants[0] = due_at
    due = await services.execute_recovery_action(payment_command())

    assert durable_policy.disposition == "DELAY"
    assert durable_policy.delay_until == due_at.isoformat()
    assert early.status == "REJECTED"
    assert early.reason_code == "ACTION_NOT_DUE"
    assert due.status == "SUCCEEDED"
    assert len(provider.requests) == 1


async def test_explicit_approval_does_not_bypass_a_future_schedule(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    due_at = TEST_NOW + timedelta(minutes=10)
    async with session_factory() as session:
        await seed_fitbox(session)
        action, policy = await action_and_policy(session)
        action.status = ActionStatus.AWAITING_APPROVAL
        action.scheduled_for = due_at
        policy.disposition = PolicyDisposition.REQUIRE_MANUAL_APPROVAL
        policy.decision_code = "AMOUNT_REQUIRES_APPROVAL"
        await session.commit()

    monkeypatch.setattr("services.worker.app.runtime.get_session_factory", lambda: session_factory)
    instants = [TEST_NOW]
    provider = RecordingPaymentProvider()
    services = ProductionRecoveryActivityServices(
        payment_provider=provider,
        scorer=FixedScorer(),
        clock=lambda: instants[0],
    )
    before_approval = await services.execute_recovery_action(payment_command())

    async with session_factory() as session:
        service = RecoveryCaseService(CaseRepository(session), MockPaymentProvider())
        approved = await service.approve_action(
            merchant_id="merchant_fitbox",
            case_id=FITBOX_CASE_ID,
            action_id=action.id,
            now=TEST_NOW,
        )
        assert approved.status == ActionStatus.SCHEDULED
        assert approved.scheduled_for == due_at

    early = await services.execute_recovery_action(payment_command())
    instants[0] = due_at
    due = await services.execute_recovery_action(payment_command())

    assert before_approval.reason_code == "ACTION_NOT_AUTHORIZED"
    assert early.reason_code == "ACTION_NOT_DUE"
    assert due.status == "SUCCEEDED"
    assert len(provider.requests) == 1


async def test_persisted_block_cannot_be_overridden_by_scheduled_status(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    async with session_factory() as session:
        await seed_fitbox(session)
        action, policy = await action_and_policy(session)
        action.status = ActionStatus.SCHEDULED
        policy.disposition = PolicyDisposition.BLOCK
        policy.decision_code = "MERCHANT_KILL_SWITCH"
        await session.commit()
    monkeypatch.setattr("services.worker.app.runtime.get_session_factory", lambda: session_factory)
    provider = RecordingPaymentProvider()
    services = ProductionRecoveryActivityServices(
        payment_provider=provider,
        scorer=FixedScorer(),
        clock=lambda: TEST_NOW,
    )

    durable_policy = await services.evaluate_policy(policy_command())
    result = await services.execute_recovery_action(payment_command())

    assert durable_policy.disposition == "BLOCK"
    assert durable_policy.decision_code == "MERCHANT_KILL_SWITCH"
    assert result.status == "REJECTED"
    assert result.reason_code == "POLICY_BLOCKED"
    assert provider.requests == []


async def test_concurrent_claims_submit_provider_work_exactly_once(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    async with session_factory() as session:
        await seed_fitbox(session)
        action, _ = await action_and_policy(session)
        action.status = ActionStatus.SCHEDULED
        await session.commit()
    monkeypatch.setattr("services.worker.app.runtime.get_session_factory", lambda: session_factory)
    provider = BlockingPaymentProvider()
    services = ProductionRecoveryActivityServices(
        payment_provider=provider,
        scorer=FixedScorer(),
        clock=lambda: TEST_NOW,
    )

    first_task = asyncio.create_task(services.execute_recovery_action(payment_command()))
    await provider.started.wait()
    competing = await services.execute_recovery_action(payment_command())
    provider.release.set()
    first = await first_task
    duplicate = await services.execute_recovery_action(payment_command())

    assert first.status == duplicate.status == "SUCCEEDED"
    assert competing.status == "UNCERTAIN"
    assert competing.reason_code == "SUBMISSION_RECONCILIATION_REQUIRED"
    assert len(provider.requests) == 1


async def test_authoritative_payment_cancellation_invokes_voice_once_and_surfaces_uncertainty(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    async with session_factory() as session:
        await seed_fitbox(session)
    monkeypatch.setattr("services.worker.app.runtime.get_session_factory", lambda: session_factory)
    voice_service = RecordingVoiceService("UNCERTAIN")
    resources = RecordingVoiceResources(voice_service)
    monkeypatch.setattr(
        "services.worker.app.runtime.create_voice_service_from_env",
        lambda session: resources,
    )
    services = ProductionRecoveryActivityServices(
        payment_provider=RecordingPaymentProvider(), scorer=FixedScorer()
    )

    result = await services.cancel_recovery_action(
        CancelActionInput(
            case_id=FITBOX_CASE_ID,
            provider_reference=None,
            reason="AUTHORITATIVE_PAYMENT_SUCCESS",
            idempotency_key=f"{FITBOX_CASE_ID}:cancel:action-1",
        )
    )

    assert result.cancelled is False
    assert result.reason_code == "VOICE_CANCELLATION_UNCERTAIN_RECONCILE_REQUIRED"
    assert voice_service.calls[0]["cancellation_key"] == (
        f"voice:{FITBOX_CASE_ID}:cancel:action-1:authoritative_payment_success"
    )
    assert resources.closed is True
