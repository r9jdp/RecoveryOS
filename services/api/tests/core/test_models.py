"""Persistence metadata and FitBox seed tests."""

from sqlalchemy import inspect, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.schema import CreateIndex, CreateTable

from services.api.app.db import Base
from services.api.app.models import Merchant, RecoveryCase
from services.api.app.seed import FITBOX_CASE_ID, seed_fitbox


def test_postgres_invariants_are_represented_in_metadata() -> None:
    case_table = Base.metadata.tables["recovery_cases"]
    constraint_names = {constraint.name for constraint in case_table.constraints}

    assert "case_failed_invoice" in constraint_names
    assert Base.metadata.tables["recovery_cases"].indexes
    index_names = {index.name for index in case_table.indexes}
    assert "uq_recovery_cases_fallback_cycle" in index_names
    assert "ck_recovery_cases_case_has_invoice_or_cycle" in constraint_names
    assert "ck_recovery_cases_case_risk_nonnegative" in constraint_names
    assert inspect(case_table).primary_key is not None
    assert Base.metadata.tables["revenue_recognition"].c.amount_paise.type.python_type is int


def test_all_metadata_compiles_for_postgres() -> None:
    dialect = postgresql.dialect()  # type: ignore[no-untyped-call]
    for table in Base.metadata.sorted_tables:
        assert str(CreateTable(table).compile(dialect=dialect))
        for index in table.indexes:
            assert str(CreateIndex(index).compile(dialect=dialect))


async def test_fitbox_seed_is_complete_and_idempotent(session: AsyncSession) -> None:
    assert await seed_fitbox(session) is True
    assert await seed_fitbox(session) is False

    recovery_case = await session.scalar(
        select(RecoveryCase).where(RecoveryCase.id == FITBOX_CASE_ID)
    )
    assert recovery_case is not None
    assert recovery_case.amount_at_risk_paise == 149_900
    assert recovery_case.failed_invoice_id == "inv_fitbox_aug_2026"
    assert recovery_case.billing_cycle_key == "2026-08"

    session.add(
        Merchant(
            id="merchant_unrelated",
            external_id="acct_unrelated",
            display_name="Unrelated Merchant",
            currency="INR",
        )
    )
    await session.commit()
    assert await seed_fitbox(session, reset=True) is True
    assert await session.get(Merchant, "merchant_unrelated") is not None
