"""add voice contact persistence

Revision ID: 6c59c834a0ef
Revises: 77dabad16ba0
Create Date: 2026-08-28 00:58:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from services.api.app.models.entities import UTCDateTime

revision: str = "6c59c834a0ef"
down_revision: str | None = "77dabad16ba0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "voice_contact_attempts",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("merchant_id", sa.String(length=64), nullable=False),
        sa.Column("case_id", sa.String(length=64), nullable=False),
        sa.Column("customer_id", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("destination_token", sa.String(length=256), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_call_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("disposition", sa.String(length=32), nullable=True),
        sa.Column("transcript", sa.Text(), nullable=True),
        sa.Column("detected_intent", sa.String(length=32), nullable=True),
        sa.Column("confidence_basis_points", sa.Integer(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("provider_payload", sa.JSON(), nullable=False),
        sa.Column("disclosure_text", sa.Text(), nullable=False),
        sa.Column("disclosure_delivered_at", UTCDateTime(timezone=True), nullable=True),
        sa.Column("consent_verified_at", UTCDateTime(timezone=True), nullable=False),
        sa.Column("submitted_at", UTCDateTime(timezone=True), nullable=True),
        sa.Column("completed_at", UTCDateTime(timezone=True), nullable=True),
        sa.Column("uncertain_submission", sa.Boolean(), nullable=False),
        sa.Column("recording_enabled", sa.Boolean(), nullable=False),
        sa.Column("max_duration_seconds", sa.Integer(), nullable=False),
        sa.Column("created_at", UTCDateTime(timezone=True), nullable=False),
        sa.Column("updated_at", UTCDateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "confidence_basis_points IS NULL OR "
            "(confidence_basis_points >= 0 AND confidence_basis_points <= 10000)",
            name=op.f("ck_voice_contact_attempts_voice_confidence_basis_points_range"),
        ),
        sa.CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds >= 0",
            name=op.f("ck_voice_contact_attempts_voice_duration_nonnegative"),
        ),
        sa.CheckConstraint(
            "max_duration_seconds > 0 AND max_duration_seconds <= 180",
            name=op.f("ck_voice_contact_attempts_voice_max_duration_range"),
        ),
        sa.CheckConstraint(
            "recording_enabled = false",
            name=op.f("ck_voice_contact_attempts_voice_recording_always_disabled"),
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["recovery_cases.id"],
            name=op.f("fk_voice_contact_attempts_case_id_recovery_cases"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
            name=op.f("fk_voice_contact_attempts_customer_id_customers"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["merchant_id"],
            ["merchants.id"],
            name=op.f("fk_voice_contact_attempts_merchant_id_merchants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_voice_contact_attempts")),
        sa.UniqueConstraint(
            "idempotency_key", name=op.f("uq_voice_contact_attempts_idempotency_key")
        ),
        sa.UniqueConstraint(
            "provider_call_id", name=op.f("uq_voice_contact_attempts_provider_call_id")
        ),
    )
    op.create_index(
        op.f("ix_voice_contact_attempts_case_id"),
        "voice_contact_attempts",
        ["case_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_voice_contact_attempts_customer_id"),
        "voice_contact_attempts",
        ["customer_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_voice_contact_attempts_merchant_id"),
        "voice_contact_attempts",
        ["merchant_id"],
        unique=False,
    )
    op.create_index(
        "ix_voice_attempt_daily_limit",
        "voice_contact_attempts",
        ["created_at", "status"],
        unique=False,
    )
    op.create_index(
        "uq_voice_contact_one_active",
        "voice_contact_attempts",
        ["recording_enabled"],
        unique=True,
        postgresql_where=sa.text("status IN ('RESERVED', 'SUBMITTED', 'RINGING', 'IN_PROGRESS')"),
        sqlite_where=sa.text("status IN ('RESERVED', 'SUBMITTED', 'RINGING', 'IN_PROGRESS')"),
    )

    op.create_table(
        "voice_webhook_receipts",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_event_id", sa.String(length=200), nullable=False),
        sa.Column("attempt_id", sa.String(length=64), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("received_at", UTCDateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["voice_contact_attempts.id"],
            name=op.f("fk_voice_webhook_receipts_attempt_id_voice_contact_attempts"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_voice_webhook_receipts")),
        sa.UniqueConstraint(
            "provider",
            "provider_event_id",
            name="voice_webhook_provider_event",
        ),
    )
    op.create_index(
        op.f("ix_voice_webhook_receipts_attempt_id"),
        "voice_webhook_receipts",
        ["attempt_id"],
        unique=False,
    )

    op.create_table(
        "voice_suppressions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("merchant_id", sa.String(length=64), nullable=False),
        sa.Column("customer_id", sa.String(length=64), nullable=False),
        sa.Column("source_attempt_id", sa.String(length=64), nullable=True),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("suppressed_at", UTCDateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
            name=op.f("fk_voice_suppressions_customer_id_customers"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["merchant_id"],
            ["merchants.id"],
            name=op.f("fk_voice_suppressions_merchant_id_merchants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_attempt_id"],
            ["voice_contact_attempts.id"],
            name=op.f("fk_voice_suppressions_source_attempt_id_voice_contact_attempts"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_voice_suppressions")),
        sa.UniqueConstraint("merchant_id", "customer_id", name="voice_suppression_customer"),
    )


def downgrade() -> None:
    op.drop_table("voice_suppressions")
    op.drop_index(op.f("ix_voice_webhook_receipts_attempt_id"), table_name="voice_webhook_receipts")
    op.drop_table("voice_webhook_receipts")
    op.drop_index("uq_voice_contact_one_active", table_name="voice_contact_attempts")
    op.drop_index("ix_voice_attempt_daily_limit", table_name="voice_contact_attempts")
    op.drop_index(
        op.f("ix_voice_contact_attempts_merchant_id"), table_name="voice_contact_attempts"
    )
    op.drop_index(
        op.f("ix_voice_contact_attempts_customer_id"), table_name="voice_contact_attempts"
    )
    op.drop_index(op.f("ix_voice_contact_attempts_case_id"), table_name="voice_contact_attempts")
    op.drop_table("voice_contact_attempts")
