"""Persistence used to consume signed A2A mandates exactly once."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from services.api.app.db.base import Base

from .entities import UTCDateTime


class A2AMandateNonceConsumption(Base):
    """Database serialization point for one-time mandate authorization."""

    __tablename__ = "a2a_mandate_nonce_consumptions"

    nonce: Mapped[str] = mapped_column(Text, primary_key=True)
    mandate_id: Mapped[str] = mapped_column(String(200), nullable=False)
    claim_id: Mapped[str | None] = mapped_column(String(64))
    signer_key_id: Mapped[str] = mapped_column(String(128), nullable=False)
    task_id: Mapped[str | None] = mapped_column(String(96))
    merchant_id: Mapped[str] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False
    )
    case_id: Mapped[str] = mapped_column(
        ForeignKey("recovery_cases.id", ondelete="CASCADE"), nullable=False
    )
    customer_id: Mapped[str | None] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT")
    )
    recovery_action_id: Mapped[str | None] = mapped_column(
        ForeignKey("recovery_actions.id", ondelete="CASCADE")
    )
    failed_invoice_id: Mapped[str | None] = mapped_column(
        ForeignKey("invoices.id", ondelete="RESTRICT")
    )
    exact_amount_paise: Mapped[int | None] = mapped_column(BigInteger)
    currency: Mapped[str | None] = mapped_column(String(3))
    payment_surface_type: Mapped[str | None] = mapped_column(String(64))
    payment_surface_reference: Mapped[str | None] = mapped_column(String(256))
    authorized_action: Mapped[str | None] = mapped_column(String(64))
    issued_at: Mapped[datetime | None] = mapped_column(UTCDateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime] = mapped_column(UTCDateTime(timezone=True), nullable=False)
    execution_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="AUTHORIZED"
    )
    execution_claimed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(timezone=True))
    executed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("mandate_id", name="a2a_mandate_consumption_mandate"),
        UniqueConstraint("claim_id", name="uq_a2a_mandate_consumption_claim_id"),
        UniqueConstraint(
            "recovery_action_id",
            name="uq_a2a_mandate_consumption_recovery_action",
        ),
        CheckConstraint("consumed_at <= expires_at", name="consumed_before_expiry"),
        CheckConstraint(
            "execution_status IN ('LEGACY', 'AUTHORIZED', 'EXECUTING', 'SUCCEEDED', 'UNCERTAIN')",
            name="mandate_execution_status",
        ),
        Index("ix_a2a_mandate_consumption_expires_at", "expires_at"),
        Index("ix_a2a_mandate_action_status", "recovery_action_id", "execution_status"),
    )
