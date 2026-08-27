"""add durable customer-agent tasks

Revision ID: b160d73bfe19
Revises: 27b4eb4b36a1
Create Date: 2026-08-28 03:05:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from services.api.app.models.entities import UTCDateTime

revision: str = "b160d73bfe19"
down_revision: str | None = "27b4eb4b36a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "customer_agent_tasks",
        sa.Column("task_id", sa.String(length=96), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("state", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "version",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("created_at", UTCDateTime(timezone=True), nullable=False),
        sa.Column("updated_at", UTCDateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "version >= 1",
            name=op.f("ck_customer_agent_tasks_version_positive"),
        ),
        sa.PrimaryKeyConstraint("task_id", name=op.f("pk_customer_agent_tasks")),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_customer_agent_tasks_idempotency_key",
        ),
    )
    op.create_index(
        "ix_customer_agent_tasks_state_updated",
        "customer_agent_tasks",
        ["state", "updated_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_customer_agent_tasks_state_updated",
        table_name="customer_agent_tasks",
    )
    op.drop_table("customer_agent_tasks")
