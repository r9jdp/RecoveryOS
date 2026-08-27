"""Fresh-database reset/reseed gate for the complete FitBox judge scenario."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from services.api.app.db import Base
from services.api.app.domain.enums import CaseOutcome, PaymentState
from services.api.app.models import A2AMandateNonceConsumption, Merchant, RecoveryCase
from services.api.app.seed import FITBOX_CASE_ID, seed_fitbox


async def _session_factory() -> tuple[async_sessionmaker[AsyncSession], object]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_connection: object, _: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False), engine


async def test_reset_reseed_restores_demo_and_removes_phase3_authorization_state() -> None:
    factory, engine = await _session_factory()
    try:
        async with factory() as session:
            assert await seed_fitbox(session) is True
            recovery_case = await session.get(RecoveryCase, FITBOX_CASE_ID)
            assert recovery_case is not None
            recovery_case.case_outcome = CaseOutcome.STOPPED
            recovery_case.payment_state = PaymentState.CAPTURED
            recovery_case.arrears_collected_paise = 149_900
            recovery_case.version += 1
            now = datetime.now(UTC)
            session.add(
                A2AMandateNonceConsumption(
                    nonce="phase4-reset-nonce",
                    mandate_id="phase4-reset-mandate",
                    signer_key_id="recoveryos-mock-2026-01",
                    merchant_id="merchant_fitbox",
                    case_id=FITBOX_CASE_ID,
                    expires_at=now + timedelta(minutes=5),
                    consumed_at=now,
                )
            )
            session.add(
                Merchant(
                    id="merchant_phase4_unrelated",
                    external_id="acct_phase4_unrelated",
                    display_name="Unrelated merchant",
                    currency="INR",
                )
            )
            await session.commit()

            assert await seed_fitbox(session, reset=True) is True
            restored = await session.get(RecoveryCase, FITBOX_CASE_ID)
            assert restored is not None
            assert restored.case_outcome is CaseOutcome.OPEN
            assert restored.payment_state is PaymentState.FAILED
            assert restored.arrears_collected_paise == 0
            assert restored.amount_at_risk_paise == 149_900
            assert await session.get(A2AMandateNonceConsumption, "phase4-reset-nonce") is None
            assert await session.get(Merchant, "merchant_phase4_unrelated") is not None

            # Repeating the reset produces exactly one complete FitBox case.
            assert await seed_fitbox(session, reset=True) is True
            count = await session.scalar(
                select(func.count())
                .select_from(RecoveryCase)
                .where(RecoveryCase.id == FITBOX_CASE_ID)
            )
            assert count == 1
    finally:
        await engine.dispose()  # type: ignore[attr-defined]
