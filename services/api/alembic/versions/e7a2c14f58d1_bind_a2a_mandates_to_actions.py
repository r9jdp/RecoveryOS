"""bind A2A v2 mandates to exact recovery actions

Revision ID: e7a2c14f58d1
Revises: 9f7c2a1e4d88
Create Date: 2026-09-01 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from services.api.app.models.entities import UTCDateTime

revision: str = "e7a2c14f58d1"
down_revision: str | None = "9f7c2a1e4d88"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    table = "a2a_mandate_nonce_consumptions"
    op.add_column(table, sa.Column("claim_id", sa.String(length=64), nullable=True))
    op.add_column(table, sa.Column("task_id", sa.String(length=96), nullable=True))
    op.add_column(table, sa.Column("customer_id", sa.String(length=64), nullable=True))
    op.add_column(table, sa.Column("recovery_action_id", sa.String(length=64), nullable=True))
    op.add_column(table, sa.Column("failed_invoice_id", sa.String(length=64), nullable=True))
    op.add_column(table, sa.Column("exact_amount_paise", sa.BigInteger(), nullable=True))
    op.add_column(table, sa.Column("currency", sa.String(length=3), nullable=True))
    op.add_column(table, sa.Column("payment_surface_type", sa.String(length=64), nullable=True))
    op.add_column(
        table,
        sa.Column("payment_surface_reference", sa.String(length=256), nullable=True),
    )
    op.add_column(table, sa.Column("authorized_action", sa.String(length=64), nullable=True))
    op.add_column(table, sa.Column("issued_at", UTCDateTime(timezone=True), nullable=True))
    op.add_column(
        table,
        sa.Column(
            "execution_status",
            sa.String(length=32),
            server_default="LEGACY",
            nullable=False,
        ),
    )
    op.add_column(
        table,
        sa.Column("execution_claimed_at", UTCDateTime(timezone=True), nullable=True),
    )
    op.add_column(table, sa.Column("executed_at", UTCDateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        op.f("fk_a2a_mandate_nonce_consumptions_customer_id_customers"),
        table,
        "customers",
        ["customer_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        op.f("fk_a2a_mandate_nonce_consumptions_recovery_action_id_recovery_actions"),
        table,
        "recovery_actions",
        ["recovery_action_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        op.f("fk_a2a_mandate_nonce_consumptions_failed_invoice_id_invoices"),
        table,
        "invoices",
        ["failed_invoice_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_a2a_mandate_consumption_claim_id",
        table,
        ["claim_id"],
    )
    op.create_unique_constraint(
        "uq_a2a_mandate_consumption_recovery_action",
        table,
        ["recovery_action_id"],
    )
    op.create_check_constraint(
        op.f("ck_a2a_mandate_nonce_consumptions_mandate_execution_status"),
        table,
        "execution_status IN ('LEGACY', 'AUTHORIZED', 'EXECUTING', 'SUCCEEDED', 'UNCERTAIN')",
    )
    op.create_index(
        "ix_a2a_mandate_action_status",
        table,
        ["recovery_action_id", "execution_status"],
        unique=False,
    )


def downgrade() -> None:
    table = "a2a_mandate_nonce_consumptions"
    op.drop_index("ix_a2a_mandate_action_status", table_name=table)
    op.drop_constraint(
        op.f("ck_a2a_mandate_nonce_consumptions_mandate_execution_status"),
        table,
        type_="check",
    )
    op.drop_constraint("uq_a2a_mandate_consumption_recovery_action", table, type_="unique")
    op.drop_constraint("uq_a2a_mandate_consumption_claim_id", table, type_="unique")
    op.drop_constraint(
        op.f("fk_a2a_mandate_nonce_consumptions_failed_invoice_id_invoices"),
        table,
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_a2a_mandate_nonce_consumptions_recovery_action_id_recovery_actions"),
        table,
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_a2a_mandate_nonce_consumptions_customer_id_customers"),
        table,
        type_="foreignkey",
    )
    for column in (
        "executed_at",
        "execution_claimed_at",
        "execution_status",
        "issued_at",
        "authorized_action",
        "payment_surface_reference",
        "payment_surface_type",
        "currency",
        "exact_amount_paise",
        "failed_invoice_id",
        "recovery_action_id",
        "customer_id",
        "task_id",
        "claim_id",
    ):
        op.drop_column(table, column)
