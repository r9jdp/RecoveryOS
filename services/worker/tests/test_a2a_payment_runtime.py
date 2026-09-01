from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast

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
    PaymentSurfaceType,
    PolicyDisposition,
    RecoveryActionType,
)
from services.api.app.integrations.a2a.mandates import canonical_json
from services.api.app.integrations.a2a.models import RecoveryMandateData
from services.api.app.models import (
    A2AMandateNonceConsumption,
    PolicyDecisionRecord,
    RecoveryActionRecord,
)
from services.api.app.providers.contracts import (
    OpenPaymentSurfaceRequest,
    PaymentSnapshot,
    PaymentSurfaceResult,
    RecoveryScoreRequest,
    RecoveryScoreResult,
)
from services.api.app.seed import FITBOX_CASE_ID, seed_fitbox
from services.worker.app.contracts import ExecuteActionInput
from services.worker.app.runtime import ProductionRecoveryActivityServices

NOW = datetime(2026, 8, 28, 10, 0, tzinfo=UTC)
SEND_ACTION_ID = "action_fitbox_customer_agent_001"
OLDER_OPEN_ACTION_ID = "action_fitbox_card_update_001"
FAILED_INVOICE_ID = "inv_fitbox_aug_2026"
MANDATE_ID = "mandate_fitbox_customer_agent_001"
NONCE = "nonce_fitbox_customer_agent_001"


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


class RecordingPaymentProvider:
    def __init__(self) -> None:
        self.opens: list[OpenPaymentSurfaceRequest] = []

    async def open_customer_payment_surface(
        self, request: OpenPaymentSurfaceRequest
    ) -> PaymentSurfaceResult:
        self.opens.append(request)
        return PaymentSurfaceResult(
            provider="razorpay-test",
            provider_reference="inv_fitbox_aug_2026",
            surface_type=PaymentSurfaceType.SUBSCRIPTION_INVOICE_LINK,
            customer_url="https://rzp.test/invoices/inv_fitbox_aug_2026",
            authoritative=True,
        )

    async def fetch_payment_snapshot(
        self,
        *,
        merchant_id: str,
        payment_id: str | None,
        invoice_id: str,
    ) -> PaymentSnapshot:
        raise AssertionError((merchant_id, payment_id, invoice_id))


def _services(provider: RecordingPaymentProvider) -> ProductionRecoveryActivityServices:
    return ProductionRecoveryActivityServices(
        payment_provider=provider,
        scorer=FixedScorer(),
        clock=lambda: NOW,
    )


def _mandate_data() -> RecoveryMandateData:
    return RecoveryMandateData(
        protocol_version="recovery.mandate.v2",
        mandate_id=MANDATE_ID,
        nonce=NONCE,
        signer_key_id="customer-agent-key-v2",
        task_id="customer-agent-task-001",
        merchant_id="merchant_fitbox",
        case_id=FITBOX_CASE_ID,
        customer_id="customer_fitbox_001",
        recovery_action_id=SEND_ACTION_ID,
        failed_invoice_id=FAILED_INVOICE_ID,
        exact_amount_paise=149_900,
        currency="INR",
        payment_surface_type="SUBSCRIPTION_INVOICE_LINK",
        payment_surface_reference=FAILED_INVOICE_ID,
        authorized_action="OPEN_EXACT_PAYMENT_SURFACE",
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=12),
    )


def _envelope(data: RecoveryMandateData | None = None) -> dict[str, Any]:
    mandate = data or _mandate_data()
    return {
        "algorithm": "Ed25519",
        "data": mandate.model_dump(mode="json"),
        "signature": "persisted-verification-is-the-runtime-trust-anchor",
    }


def _command(envelope: dict[str, Any]) -> ExecuteActionInput:
    return ExecuteActionInput(
        case_id=FITBOX_CASE_ID,
        merchant_id="merchant_fitbox",
        customer_id="customer_fitbox_001",
        subscription_id="sub_fitbox_annual_001",
        failed_invoice_id=FAILED_INVOICE_ID,
        amount_paise=149_900,
        currency="INR",
        action="OPEN_CUSTOMER_PAYMENT_SURFACE",
        payment_surface_type="SUBSCRIPTION_INVOICE_LINK",
        recovery_deadline="2026-08-30T10:00:01+00:00",
        idempotency_key="workflow:a2a:fitbox:execute:v2",
        mandate=envelope,
        provider_subscription_id="sub_fitbox_annual_001",
        provider_invoice_id=FAILED_INVOICE_ID,
        recovery_action_id=SEND_ACTION_ID,
    )


async def _seed_verified_authorization(
    sessions: async_sessionmaker[AsyncSession],
) -> dict[str, Any]:
    data = _mandate_data()
    async with sessions() as session:
        await seed_fitbox(session)
        send_action = RecoveryActionRecord(
            id=SEND_ACTION_ID,
            case_id=FITBOX_CASE_ID,
            action_type=RecoveryActionType.SEND_TO_CUSTOMER_AGENT,
            payment_surface_type=None,
            status=ActionStatus.PROPOSED,
            idempotency_key="case:case_fitbox_aug_2026:action:SEND_TO_CUSTOMER_AGENT:v2",
            created_at=NOW - timedelta(hours=1),
            updated_at=NOW - timedelta(hours=1),
        )
        session.add(send_action)
        await session.flush()
        session.add(
            PolicyDecisionRecord(
                id="policy_fitbox_customer_agent_001",
                case_id=FITBOX_CASE_ID,
                action_id=SEND_ACTION_ID,
                disposition=PolicyDisposition.ALLOW,
                decision_code="TEST_A2A_CUSTOMER_AUTHORIZED",
                reason_codes=["TEST_VERIFIED_MANDATE"],
                reasons=["The customer approved the exact persisted payment scope."],
                policy_version="test-a2a.v2",
                created_at=NOW - timedelta(hours=1),
            )
        )
        await session.flush()
        session.add(
            A2AMandateNonceConsumption(
                nonce=data.nonce,
                mandate_id=data.mandate_id,
                claim_id=hashlib.sha256(canonical_json(data)).hexdigest(),
                signer_key_id=data.signer_key_id,
                task_id=data.task_id,
                merchant_id=data.merchant_id,
                case_id=data.case_id,
                customer_id=data.customer_id,
                recovery_action_id=data.recovery_action_id,
                failed_invoice_id=data.failed_invoice_id,
                exact_amount_paise=data.exact_amount_paise,
                currency=data.currency,
                payment_surface_type=data.payment_surface_type,
                payment_surface_reference=data.payment_surface_reference,
                authorized_action=data.authorized_action,
                issued_at=data.issued_at,
                expires_at=data.expires_at,
                consumed_at=NOW - timedelta(seconds=30),
                execution_status="AUTHORIZED",
            )
        )
        await session.commit()
    return _envelope(data)


async def test_exact_v2_authorization_claims_send_action_and_replay_is_idempotent(
    runtime_sessions: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    envelope = await _seed_verified_authorization(runtime_sessions)
    monkeypatch.setattr("services.worker.app.runtime.get_session_factory", lambda: runtime_sessions)
    provider = RecordingPaymentProvider()
    services = _services(provider)

    first = await services.execute_recovery_action(_command(envelope))
    duplicate = await services.execute_recovery_action(_command(envelope))

    assert first.status == duplicate.status == "SUCCEEDED"
    assert duplicate.reason_code == "ALREADY_EXECUTED"
    assert len(provider.opens) == 1
    opened = provider.opens[0]
    assert opened.idempotency_key == "case:case_fitbox_aug_2026:action:SEND_TO_CUSTOMER_AGENT:v2"
    assert opened.failed_invoice_id == FAILED_INVOICE_ID
    assert opened.subscription_id == "sub_fitbox_annual_001"
    assert opened.exact_amount_paise == 149_900

    async with runtime_sessions() as session:
        send_action = await session.get(RecoveryActionRecord, SEND_ACTION_ID)
        older_open_action = await session.get(RecoveryActionRecord, OLDER_OPEN_ACTION_ID)
        authorization = await session.get(A2AMandateNonceConsumption, NONCE)
        assert send_action is not None
        assert send_action.status == ActionStatus.SUCCEEDED
        assert send_action.external_reference == FAILED_INVOICE_ID
        assert older_open_action is not None
        assert older_open_action.status == ActionStatus.AWAITING_APPROVAL
        assert older_open_action.external_reference is None
        assert authorization is not None
        assert authorization.execution_status == "SUCCEEDED"
        assert authorization.executed_at is not None


async def test_missing_provider_scope_does_not_consume_verified_authorization(
    runtime_sessions: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    envelope = await _seed_verified_authorization(runtime_sessions)
    command = replace(
        _command(envelope),
        provider_subscription_id=None,
        provider_invoice_id=None,
    )
    monkeypatch.setattr("services.worker.app.runtime.get_session_factory", lambda: runtime_sessions)
    provider = RecordingPaymentProvider()

    result = await _services(provider).execute_recovery_action(command)

    assert result.status == "REJECTED"
    assert result.reason_code == "PAYMENT_PROVIDER_SCOPE_MISSING"
    assert provider.opens == []
    async with runtime_sessions() as session:
        action = await session.get(RecoveryActionRecord, SEND_ACTION_ID)
        authorization = await session.get(A2AMandateNonceConsumption, NONCE)
        assert action is not None
        assert action.status == ActionStatus.PROPOSED
        assert authorization is not None
        assert authorization.execution_status == "AUTHORIZED"
        assert authorization.execution_claimed_at is None


@pytest.mark.parametrize(
    ("variant", "reason_code"),
    [
        ("missing_action", "A2A_DURABLE_SCOPE_MISSING"),
        ("mismatched_action", "A2A_VERIFIED_AUTHORIZATION_NOT_FOUND"),
        ("missing_invoice", "PAYMENT_SURFACE_SCOPE_MISSING"),
        ("mismatched_invoice", "A2A_VERIFIED_AUTHORIZATION_NOT_FOUND"),
        ("missing_claim", "A2A_VERIFIED_AUTHORIZATION_NOT_FOUND"),
        ("mismatched_claim", "A2A_VERIFIED_AUTHORIZATION_NOT_FOUND"),
    ],
)
async def test_missing_or_mismatched_persisted_scope_is_rejected_before_provider_call(
    variant: str,
    reason_code: str,
    runtime_sessions: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    envelope = await _seed_verified_authorization(runtime_sessions)
    command = _command(envelope)

    if variant == "missing_action":
        command = replace(command, recovery_action_id=None)
    elif variant == "missing_invoice":
        command = replace(command, failed_invoice_id=None)
    elif variant in {"mismatched_action", "mismatched_invoice"}:
        data = cast(dict[str, Any], envelope["data"]).copy()
        if variant == "mismatched_action":
            data["recovery_action_id"] = OLDER_OPEN_ACTION_ID
            command = replace(command, recovery_action_id=OLDER_OPEN_ACTION_ID)
        else:
            data["failed_invoice_id"] = "invoice-from-another-case"
            command = replace(command, failed_invoice_id="invoice-from-another-case")
        envelope = {**envelope, "data": data}
        command = replace(command, mandate=envelope)
    else:
        async with runtime_sessions() as session:
            authorization = await session.get(A2AMandateNonceConsumption, NONCE)
            assert authorization is not None
            authorization.claim_id = None if variant == "missing_claim" else "0" * 64
            await session.commit()

    monkeypatch.setattr("services.worker.app.runtime.get_session_factory", lambda: runtime_sessions)
    provider = RecordingPaymentProvider()
    result = await _services(provider).execute_recovery_action(command)

    assert result.status == "REJECTED"
    assert result.reason_code == reason_code
    assert provider.opens == []
    async with runtime_sessions() as session:
        send_action = await session.get(RecoveryActionRecord, SEND_ACTION_ID)
        older_open_action = await session.get(RecoveryActionRecord, OLDER_OPEN_ACTION_ID)
        assert send_action is not None
        assert send_action.status == ActionStatus.PROPOSED
        assert older_open_action is not None
        assert older_open_action.status == ActionStatus.AWAITING_APPROVAL
