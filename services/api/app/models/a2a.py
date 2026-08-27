"""Persistence used to consume signed A2A mandates exactly once."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from services.api.app.db.base import Base

from .entities import UTCDateTime


class A2AMandateNonceConsumption(Base):
    """Database serialization point for one-time mandate authorization."""

    __tablename__ = "a2a_mandate_nonce_consumptions"

    nonce: Mapped[str] = mapped_column(Text, primary_key=True)
    mandate_id: Mapped[str] = mapped_column(String(200), nullable=False)
    signer_key_id: Mapped[str] = mapped_column(String(128), nullable=False)
    merchant_id: Mapped[str] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False
    )
    case_id: Mapped[str] = mapped_column(
        ForeignKey("recovery_cases.id", ondelete="CASCADE"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime] = mapped_column(UTCDateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("mandate_id", name="a2a_mandate_consumption_mandate"),
        CheckConstraint("consumed_at <= expires_at", name="consumed_before_expiry"),
        Index("ix_a2a_mandate_consumption_expires_at", "expires_at"),
    )
