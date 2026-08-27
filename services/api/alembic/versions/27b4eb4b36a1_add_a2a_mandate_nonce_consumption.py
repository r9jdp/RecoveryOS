"""add A2A mandate nonce consumption

Revision ID: 27b4eb4b36a1
Revises: 6c59c834a0ef
Create Date: 2026-08-28 01:05:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from services.api.app.models.entities import UTCDateTime

revision: str = "27b4eb4b36a1"
down_revision: str | None = "6c59c834a0ef"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "a2a_mandate_nonce_consumptions",
        sa.Column("nonce", sa.Text(), nullable=False),
        sa.Column("mandate_id", sa.String(length=200), nullable=False),
        sa.Column("signer_key_id", sa.String(length=128), nullable=False),
        sa.Column("merchant_id", sa.String(length=64), nullable=False),
        sa.Column("case_id", sa.String(length=64), nullable=False),
        sa.Column("expires_at", UTCDateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", UTCDateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "consumed_at <= expires_at",
            name=op.f("ck_a2a_mandate_nonce_consumptions_a2a_mandate_consumed_before_expiry"),
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["recovery_cases.id"],
            name=op.f("fk_a2a_mandate_nonce_consumptions_case_id_recovery_cases"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["merchant_id"],
            ["merchants.id"],
            name=op.f("fk_a2a_mandate_nonce_consumptions_merchant_id_merchants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("nonce", name=op.f("pk_a2a_mandate_nonce_consumptions")),
        sa.UniqueConstraint("mandate_id", name="a2a_mandate_consumption_mandate"),
    )
    op.create_index(
        "ix_a2a_mandate_consumption_expires_at",
        "a2a_mandate_nonce_consumptions",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_a2a_mandate_consumption_expires_at",
        table_name="a2a_mandate_nonce_consumptions",
    )
    op.drop_table("a2a_mandate_nonce_consumptions")
