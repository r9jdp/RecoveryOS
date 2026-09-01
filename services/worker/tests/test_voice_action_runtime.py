from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from services.api.app.db import Base
from services.api.app.domain.enums import (
    ActionStatus,
    EvidenceKind,
    PolicyDisposition,
    RecoveryActionType,
)
from services.api.app.models import (
    PolicyDecisionRecord,
    RecoveryActionRecord,
    RecoveryEventRecord,
)
from services.api.app.providers.contracts import (
    RecoveryScoreRequest,
    RecoveryScoreResult,
    VoiceContactResult,
)
from services.api.app.seed import FITBOX_CASE_ID, seed_fitbox
from services.api.app.services.mock_payment import MockPaymentProvider
from services.worker.app.contracts import ExecuteActionInput
from services.worker.app.runtime import ProductionRecoveryActivityServices

NOW = datetime(2026, 8, 30, 10, 0, tzinfo=UTC)


@pytest.fixture
async def voice_runtime_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def voice_runtime_sessions(
    voice_runtime_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(voice_runtime_engine, expire_on_commit=False)


class FixedScorer:
    async def score(self, request: RecoveryScoreRequest) -> RecoveryScoreResult:
        return RecoveryScoreResult(
            model_name="fixed",
            model_version="test",
            recovery_probability=0.5,
            expected_recovered_paise=request.amount_at_risk_paise // 2,
            expected_utility_paise=request.amount_at_risk_paise // 2,
        )


class RecordingVoiceStartService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def start(self, **kwargs: object) -> VoiceContactResult:
        self.calls.append(kwargs)
        return VoiceContactResult(
            provider="twilio",
            contact_attempt_id=str(kwargs["idempotency_key"]),
            provider_call_id="CA-APPROVED-1",
            status="SUBMITTED",
        )


class RecordingVoiceResources:
    def __init__(self, service: RecordingVoiceStartService) -> None:
        self.service = service

    async def aclose(self) -> None:
        return None


def _command() -> ExecuteActionInput:
    return ExecuteActionInput(
        case_id=FITBOX_CASE_ID,
        merchant_id="merchant_fitbox",
        customer_id="customer_fitbox_001",
        subscription_id="sub_fitbox_annual_001",
        failed_invoice_id="inv_fitbox_aug_2026",
        amount_paise=149_900,
        currency="INR",
        action="START_VOICE",
        payment_surface_type=None,
        recovery_deadline="2026-08-30T15:30:00+00:00",
        idempotency_key=f"{FITBOX_CASE_ID}:START_VOICE:1",
    )


async def _seed_voice_action(
    sessions: async_sessionmaker[AsyncSession],
    *,
    policy: PolicyDisposition = PolicyDisposition.REQUIRE_MANUAL_APPROVAL,
    approved: bool,
) -> RecoveryActionRecord:
    async with sessions() as session:
        await seed_fitbox(session)
        action = RecoveryActionRecord(
            id="voice-action-1",
            case_id=FITBOX_CASE_ID,
            action_type=RecoveryActionType.START_VOICE,
            status=ActionStatus.SCHEDULED,
            idempotency_key="case:fitbox:voice:1",
        )
        session.add(action)
        session.add(
            PolicyDecisionRecord(
                id="voice-policy-1",
                case_id=FITBOX_CASE_ID,
                action_id=action.id,
                disposition=policy,
                decision_code="VOICE_OPERATOR_APPROVAL_REQUIRED",
                reason_codes=["ACTION_REQUIRES_APPROVAL"],
                reasons=["A real call requires explicit operator approval."],
                policy_version="voice.test.v1",
            )
        )
        if approved:
            session.add(
                RecoveryEventRecord(
                    id="voice-approval-event-1",
                    case_id=FITBOX_CASE_ID,
                    event_type="ACTION_APPROVED",
                    source="operator",
                    evidence_kind=EvidenceKind.SYSTEM_DERIVED,
                    payload={
                        "action_id": action.id,
                        "action_type": RecoveryActionType.START_VOICE.value,
                        "execution_owner": "temporal",
                    },
                    occurred_at=NOW,
                    correlation_id=f"corr_{FITBOX_CASE_ID}",
                    source_event_id="approval:voice-action-1",
                )
            )
        await session.commit()
        return action


def _services() -> ProductionRecoveryActivityServices:
    return ProductionRecoveryActivityServices(
        payment_provider=MockPaymentProvider(),
        scorer=FixedScorer(),
        clock=lambda: NOW,
    )


async def test_temporal_voice_executor_requires_persisted_operator_approval(
    voice_runtime_sessions: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_voice_action(voice_runtime_sessions, approved=False)
    recorder = RecordingVoiceStartService()
    monkeypatch.setattr("services.worker.app.runtime.voice_provider_ready", lambda: True)
    monkeypatch.setattr(
        "services.worker.app.runtime.get_session_factory", lambda: voice_runtime_sessions
    )
    monkeypatch.setattr(
        "services.worker.app.runtime.create_voice_service_from_env",
        lambda session: RecordingVoiceResources(recorder),
    )

    result = await _services().execute_recovery_action(_command())

    assert result.status == "REJECTED"
    assert result.reason_code == "VOICE_OPERATOR_APPROVAL_NOT_PERSISTED"
    assert recorder.calls == []


async def test_temporal_voice_executor_submits_once_after_manual_approval(
    voice_runtime_sessions: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_voice_action(voice_runtime_sessions, approved=True)
    recorder = RecordingVoiceStartService()
    monkeypatch.setenv("VOICE_OPERATOR_TOKEN", "server-voice-token")
    monkeypatch.setattr("services.worker.app.runtime.voice_provider_ready", lambda: True)
    monkeypatch.setattr(
        "services.worker.app.runtime.get_session_factory", lambda: voice_runtime_sessions
    )
    monkeypatch.setattr(
        "services.worker.app.runtime.create_voice_service_from_env",
        lambda session: RecordingVoiceResources(recorder),
    )
    services = _services()

    first = await services.execute_recovery_action(_command())
    replay = await services.execute_recovery_action(_command())

    assert first.status == replay.status == "SUCCEEDED"
    assert first.provider_reference == replay.provider_reference == "CA-APPROVED-1"
    assert len(recorder.calls) == 1
    assert recorder.calls[0]["supplied_operator_token"] == "server-voice-token"


async def test_temporal_voice_executor_rejects_allow_policy_even_with_approval_event(
    voice_runtime_sessions: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_voice_action(
        voice_runtime_sessions,
        policy=PolicyDisposition.ALLOW,
        approved=True,
    )
    monkeypatch.setattr("services.worker.app.runtime.voice_provider_ready", lambda: True)
    monkeypatch.setattr(
        "services.worker.app.runtime.get_session_factory", lambda: voice_runtime_sessions
    )

    result = await _services().execute_recovery_action(_command())

    assert result.status == "REJECTED"
    assert result.reason_code == "VOICE_MANUAL_APPROVAL_POLICY_REQUIRED"
