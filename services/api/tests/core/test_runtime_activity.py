from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from services.api.app.domain.enums import ActionStatus, PaymentSurfaceType
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


class FixedScorer:
    async def score(self, request: RecoveryScoreRequest) -> RecoveryScoreResult:
        return RecoveryScoreResult(
            model_name="fixed",
            model_version="test",
            recovery_probability=0.5,
            expected_recovered_paise=request.amount_at_risk_paise // 2,
            expected_utility_paise=request.amount_at_risk_paise // 2,
        )


def payment_command() -> ExecuteActionInput:
    return ExecuteActionInput(
        case_id=FITBOX_CASE_ID,
        merchant_id="merchant_fitbox",
        customer_id="customer_fitbox",
        subscription_id="sub_fitbox_monthly",
        failed_invoice_id="inv_fitbox_aug_2026",
        amount_paise=149_900,
        currency="INR",
        action="OPEN_CUSTOMER_PAYMENT_SURFACE",
        payment_surface_type="SUBSCRIPTION_CARD_UPDATE",
        recovery_deadline=(datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        idempotency_key=f"{FITBOX_CASE_ID}:OPEN_CUSTOMER_PAYMENT_SURFACE:1",
    )


async def test_provider_submission_requires_durable_operator_authorization(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch
) -> None:
    async with session_factory() as session:
        await seed_fitbox(session)
    monkeypatch.setattr(
        "services.worker.app.runtime.get_session_factory", lambda: session_factory
    )
    provider = RecordingPaymentProvider()
    services = ProductionRecoveryActivityServices(
        payment_provider=provider,
        scorer=FixedScorer(),
    )

    unauthorized = await services.execute_recovery_action(payment_command())
    assert unauthorized.status == "REJECTED"
    assert unauthorized.reason_code == "ACTION_NOT_AUTHORIZED"
    assert provider.requests == []

    async with session_factory() as session:
        from sqlalchemy import select

        from services.api.app.models import RecoveryActionRecord

        action = await session.scalar(
            select(RecoveryActionRecord).where(
                RecoveryActionRecord.case_id == FITBOX_CASE_ID,
                RecoveryActionRecord.payment_surface_type
                == PaymentSurfaceType.SUBSCRIPTION_CARD_UPDATE,
            )
        )
        assert action is not None
        action.status = ActionStatus.SCHEDULED
        await session.commit()

    submitted = await services.execute_recovery_action(payment_command())
    duplicate = await services.execute_recovery_action(payment_command())

    assert submitted.status == duplicate.status == "SUCCEEDED"
    assert submitted.provider_reference == duplicate.provider_reference == "surface-authorized"
    assert len(provider.requests) == 1
