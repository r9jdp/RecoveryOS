from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from services.api.app.db import Base
from services.api.app.domain.enums import ActionStatus, PaymentSurfaceType
from services.api.app.integrations.razorpay.errors import RazorpayUncertainSubmissionError
from services.api.app.models import Merchant, RecoveryActionRecord  # noqa: F401
from services.api.app.providers.contracts import (
    OpenPaymentSurfaceRequest,
    PaymentSnapshot,
    PaymentSurfaceResult,
    RecoveryScoreRequest,
    RecoveryScoreResult,
)
from services.api.app.seed import FITBOX_CASE_ID, seed_fitbox
from services.worker.app.contracts import CancelActionInput, ExecuteActionInput
from services.worker.app.runtime import ProductionRecoveryActivityServices

NOW = datetime(2026, 8, 28, 10, 0, tzinfo=UTC)


@pytest.fixture
async def runtime_engine() -> AsyncIterator[AsyncEngine]:
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
def runtime_sessions(runtime_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(runtime_engine, expire_on_commit=False)


class FixedScorer:
    async def score(self, request: RecoveryScoreRequest) -> RecoveryScoreResult:
        return RecoveryScoreResult(
            model_name="fixed",
            model_version="test",
            recovery_probability=0.5,
            expected_recovered_paise=request.amount_at_risk_paise // 2,
            expected_utility_paise=request.amount_at_risk_paise // 2,
        )


class LifecyclePaymentProvider:
    def __init__(
        self,
        *,
        lookup: PaymentSurfaceResult | None = None,
        lookup_error: Exception | None = None,
        revocation: str = "CANCELLED",
        open_errors: list[Exception] | None = None,
    ) -> None:
        self.lookup = lookup
        self.lookup_error = lookup_error
        self.revocation = revocation
        self.open_errors = list(open_errors or [])
        self.lookups: list[str] = []
        self.opens: list[OpenPaymentSurfaceRequest] = []
        self.revocations: list[str] = []
        self.block_open = False
        self.open_started = asyncio.Event()
        self.open_release = asyncio.Event()

    async def open_customer_payment_surface(
        self, request: OpenPaymentSurfaceRequest
    ) -> PaymentSurfaceResult:
        self.opens.append(request)
        if self.open_errors:
            raise self.open_errors.pop(0)
        if self.block_open:
            self.open_started.set()
            await self.open_release.wait()
        return _surface("plink_created")

    async def fetch_payment_snapshot(
        self, *, merchant_id: str, payment_id: str | None, invoice_id: str
    ) -> PaymentSnapshot:
        raise AssertionError((merchant_id, payment_id, invoice_id))

    async def reconcile_payment_link_by_reference(
        self, *, reference_id: str
    ) -> PaymentSurfaceResult | None:
        self.lookups.append(reference_id)
        if self.lookup_error is not None:
            raise self.lookup_error
        return self.lookup

    async def revoke_standard_payment_link(self, *, provider_reference: str) -> str:
        self.revocations.append(provider_reference)
        return self.revocation


def _surface(reference: str = "plink_existing") -> PaymentSurfaceResult:
    return PaymentSurfaceResult(
        provider="razorpay",
        provider_reference=reference,
        surface_type=PaymentSurfaceType.STANDARD_PAYMENT_LINK,
        customer_url=f"https://rzp.test/i/{reference}",
        authoritative=True,
    )


def _command() -> ExecuteActionInput:
    return ExecuteActionInput(
        case_id=FITBOX_CASE_ID,
        merchant_id="merchant_fitbox",
        customer_id="customer_fitbox_001",
        subscription_id="sub_fitbox_annual_001",
        failed_invoice_id="inv_fitbox_aug_2026",
        amount_paise=149_900,
        currency="INR",
        action="OPEN_CUSTOMER_PAYMENT_SURFACE",
        payment_surface_type="STANDARD_PAYMENT_LINK",
        recovery_deadline="2026-08-30T10:00:01+00:00",
        idempotency_key="case:case_fitbox_aug_2026:surface:standard:v1",
    )


async def _seed_standard_action(
    sessions: async_sessionmaker[AsyncSession],
    *,
    status: ActionStatus,
    external_reference: str | None = None,
) -> RecoveryActionRecord:
    async with sessions() as session:
        await seed_fitbox(session)
        action = await session.scalar(
            select(RecoveryActionRecord).where(RecoveryActionRecord.case_id == FITBOX_CASE_ID)
        )
        assert action is not None
        action.payment_surface_type = PaymentSurfaceType.STANDARD_PAYMENT_LINK
        action.status = status
        action.idempotency_key = _command().idempotency_key
        action.external_reference = external_reference
        action.customer_url = (
            f"https://rzp.test/i/{external_reference}" if external_reference else None
        )
        await session.commit()
        return action


def _services(provider: LifecyclePaymentProvider) -> ProductionRecoveryActivityServices:
    return ProductionRecoveryActivityServices(
        payment_provider=provider,
        scorer=FixedScorer(),
        clock=lambda: NOW,
    )


def _reference_id() -> str:
    digest = hashlib.sha256(_command().idempotency_key.encode()).hexdigest()[:32]
    return f"rec_{digest}"


async def test_initial_uncertain_create_reconciles_existing_without_activity_failure(
    runtime_sessions: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed_standard_action(runtime_sessions, status=ActionStatus.PROPOSED)
    monkeypatch.setattr("services.worker.app.runtime.get_session_factory", lambda: runtime_sessions)
    provider = LifecyclePaymentProvider(
        lookup=_surface(),
        open_errors=[RazorpayUncertainSubmissionError(reference_id=_reference_id())],
    )

    result = await _services(provider).execute_recovery_action(_command())

    assert result.status == "SUCCEEDED"
    assert result.reason_code == "SUBMISSION_RECONCILED"
    assert len(provider.opens) == len(provider.lookups) == 1


async def test_initial_uncertain_create_resubmits_only_after_confirmed_absence(
    runtime_sessions: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed_standard_action(runtime_sessions, status=ActionStatus.PROPOSED)
    monkeypatch.setattr("services.worker.app.runtime.get_session_factory", lambda: runtime_sessions)
    provider = LifecyclePaymentProvider(
        lookup=None,
        open_errors=[RazorpayUncertainSubmissionError(reference_id=_reference_id())],
    )

    result = await _services(provider).execute_recovery_action(_command())

    assert result.status == "SUCCEEDED"
    assert result.reason_code == "CONFIRMED_ABSENT_RESUBMITTED"
    assert len(provider.opens) == 2
    assert len(provider.lookups) == 1


async def test_initial_uncertain_create_returns_uncertain_when_lookup_is_unresolved(
    runtime_sessions: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed_standard_action(runtime_sessions, status=ActionStatus.PROPOSED)
    monkeypatch.setattr("services.worker.app.runtime.get_session_factory", lambda: runtime_sessions)
    provider = LifecyclePaymentProvider(
        lookup_error=RuntimeError("reference lookup unavailable"),
        open_errors=[RazorpayUncertainSubmissionError(reference_id=_reference_id())],
    )

    result = await _services(provider).execute_recovery_action(_command())

    assert result.status == "UNCERTAIN"
    assert result.reason_code == "PAYMENT_LINK_RECONCILIATION_UNRESOLVED"
    assert len(provider.opens) == len(provider.lookups) == 1


async def test_initial_uncertain_create_rejects_a_mismatched_reference_without_lookup(
    runtime_sessions: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed_standard_action(runtime_sessions, status=ActionStatus.PROPOSED)
    monkeypatch.setattr("services.worker.app.runtime.get_session_factory", lambda: runtime_sessions)
    provider = LifecyclePaymentProvider(
        lookup=_surface(),
        open_errors=[RazorpayUncertainSubmissionError(reference_id="rec_wrong_action")],
    )

    result = await _services(provider).execute_recovery_action(_command())

    assert result.status == "UNCERTAIN"
    assert result.reason_code == "SUBMISSION_REFERENCE_MISMATCH"
    assert len(provider.opens) == 1
    assert provider.lookups == []


async def test_executing_link_reconciles_existing_once_without_resubmit(
    runtime_sessions: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed_standard_action(runtime_sessions, status=ActionStatus.EXECUTING)
    monkeypatch.setattr("services.worker.app.runtime.get_session_factory", lambda: runtime_sessions)
    provider = LifecyclePaymentProvider(lookup=_surface())
    services = _services(provider)

    reconciled = await services.execute_recovery_action(_command())
    duplicate = await services.execute_recovery_action(_command())

    assert reconciled.status == duplicate.status == "SUCCEEDED"
    assert reconciled.reason_code == "SUBMISSION_RECONCILED"
    assert provider.opens == []
    assert len(provider.lookups) == 1
    async with runtime_sessions() as session:
        action = await session.scalar(
            select(RecoveryActionRecord).where(RecoveryActionRecord.case_id == FITBOX_CASE_ID)
        )
        assert action is not None
        assert action.status == ActionStatus.SUCCEEDED
        assert action.external_reference == "plink_existing"


async def test_only_confirmed_absence_can_resubmit(
    runtime_sessions: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed_standard_action(runtime_sessions, status=ActionStatus.EXECUTING)
    monkeypatch.setattr("services.worker.app.runtime.get_session_factory", lambda: runtime_sessions)

    unresolved_provider = LifecyclePaymentProvider(
        lookup_error=RuntimeError("provider read unavailable")
    )
    unresolved = await _services(unresolved_provider).execute_recovery_action(_command())
    assert unresolved.status == "UNCERTAIN"
    assert unresolved.reason_code == "PAYMENT_LINK_RECONCILIATION_UNRESOLVED"
    assert unresolved_provider.opens == []

    absent_provider = LifecyclePaymentProvider(lookup=None)
    resumed = await _services(absent_provider).execute_recovery_action(_command())
    assert resumed.status == "SUCCEEDED"
    assert resumed.reason_code == "CONFIRMED_ABSENT_RESUBMITTED"
    assert len(absent_provider.lookups) == len(absent_provider.opens) == 1


async def test_concurrent_delivery_does_not_reconcile_while_create_is_in_flight(
    runtime_sessions: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed_standard_action(runtime_sessions, status=ActionStatus.PROPOSED)
    monkeypatch.setattr("services.worker.app.runtime.get_session_factory", lambda: runtime_sessions)
    provider = LifecyclePaymentProvider()
    provider.block_open = True
    services = _services(provider)

    first_task = asyncio.create_task(services.execute_recovery_action(_command()))
    await provider.open_started.wait()
    competing = await services.execute_recovery_action(_command())
    provider.open_release.set()
    first = await first_task

    assert first.status == "SUCCEEDED"
    assert competing.status == "UNCERTAIN"
    assert competing.reason_code == "SUBMISSION_RECONCILIATION_REQUIRED"
    assert provider.lookups == []
    assert len(provider.opens) == 1


async def test_terminal_cleanup_reconciles_and_revokes_link_idempotently(
    runtime_sessions: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed_standard_action(runtime_sessions, status=ActionStatus.EXECUTING)
    monkeypatch.setattr("services.worker.app.runtime.get_session_factory", lambda: runtime_sessions)
    provider = LifecyclePaymentProvider(lookup=_surface())
    services = _services(provider)
    command = CancelActionInput(
        case_id=FITBOX_CASE_ID,
        provider_reference=None,
        reason="OPERATOR_ESCALATION",
        idempotency_key=f"{FITBOX_CASE_ID}:cancel:action-1",
    )

    first = await services.cancel_recovery_action(command)
    duplicate = await services.cancel_recovery_action(command)

    assert first.cancelled is duplicate.cancelled is True
    assert provider.revocations == ["plink_existing"]
    async with runtime_sessions() as session:
        action = await session.scalar(
            select(RecoveryActionRecord).where(RecoveryActionRecord.case_id == FITBOX_CASE_ID)
        )
        assert action is not None
        assert action.status == ActionStatus.CANCELLED


async def test_paid_link_cleanup_preserves_success_for_authoritative_reconciliation(
    runtime_sessions: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed_standard_action(
        runtime_sessions,
        status=ActionStatus.SUCCEEDED,
        external_reference="plink_paid",
    )
    monkeypatch.setattr("services.worker.app.runtime.get_session_factory", lambda: runtime_sessions)
    provider = LifecyclePaymentProvider(revocation="PAYMENT_PRESENT")
    services = _services(provider)

    result = await services.cancel_recovery_action(
        CancelActionInput(
            case_id=FITBOX_CASE_ID,
            provider_reference="plink_paid",
            reason="RECOVERY_DEADLINE_EXPIRED",
            idempotency_key=f"{FITBOX_CASE_ID}:cancel:action-1",
        )
    )

    assert result.cancelled is True
    assert result.reason_code == "PAYMENT_LINK_PAYMENT_PRESENT_RECONCILIATION_REQUIRED"
    async with runtime_sessions() as session:
        action = await session.scalar(
            select(RecoveryActionRecord).where(RecoveryActionRecord.case_id == FITBOX_CASE_ID)
        )
        assert action is not None
        assert action.status == ActionStatus.SUCCEEDED
