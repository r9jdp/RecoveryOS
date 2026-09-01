"""add system-derived recovery evidence

Revision ID: 9f7c2a1e4d88
Revises: b160d73bfe19
Create Date: 2026-08-30 18:30:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "9f7c2a1e4d88"
down_revision: str | None = "b160d73bfe19"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT = "ck_recovery_events_evidence_kind"


def upgrade() -> None:
    with op.batch_alter_table("recovery_events") as batch_op:
        batch_op.drop_constraint(op.f(_CONSTRAINT), type_="check")
        batch_op.create_check_constraint(
            op.f(_CONSTRAINT),
            "evidence_kind IN ('SIMULATED', 'SYSTEM_DERIVED', 'RAZORPAY_TEST_VERIFIED')",
        )


def downgrade() -> None:
    op.execute(
        "UPDATE recovery_events SET evidence_kind = 'SIMULATED' "
        "WHERE evidence_kind = 'SYSTEM_DERIVED'"
    )
    with op.batch_alter_table("recovery_events") as batch_op:
        batch_op.drop_constraint(op.f(_CONSTRAINT), type_="check")
        batch_op.create_check_constraint(
            op.f(_CONSTRAINT),
            "evidence_kind IN ('SIMULATED', 'RAZORPAY_TEST_VERIFIED')",
        )
