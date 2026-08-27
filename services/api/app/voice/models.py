"""Persistence shapes for voice attempts, callbacks, and suppression.

These models deliberately live in the isolated voice module. The coordinator
must import them from the central model registry and create an Alembic migration
before production routes are enabled.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from services.api.app.db.base import Base
from services.api.app.models.entities import UTCDateTime, new_id, utc_now


class VoiceContactAttemptRecord(Base):
    __tablename__ = "voice_contact_attempts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    merchant_id: Mapped[str] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    case_id: Mapped[str] = mapped_column(
        ForeignKey("recovery_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[str] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    destination_token: Mapped[str] = mapped_column(String(256), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_call_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    disposition: Mapped[str | None] = mapped_column(String(32))
    transcript: Mapped[str | None] = mapped_column(Text)
    detected_intent: Mapped[str | None] = mapped_column(String(32))
    confidence_basis_points: Mapped[int | None] = mapped_column(Integer)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    provider_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    disclosure_text: Mapped[str] = mapped_column(Text, nullable=False)
    disclosure_delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime(timezone=True))
    consent_verified_at: Mapped[datetime] = mapped_column(
        UTCDateTime(timezone=True), nullable=False
    )
    submitted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(timezone=True))
    uncertain_submission: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    recording_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    max_duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=180)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    __table_args__ = (
        CheckConstraint(
            "max_duration_seconds > 0 AND max_duration_seconds <= 180",
            name="voice_max_duration_range",
        ),
        CheckConstraint("recording_enabled = false", name="voice_recording_always_disabled"),
        CheckConstraint(
            "confidence_basis_points IS NULL OR "
            "(confidence_basis_points >= 0 AND confidence_basis_points <= 10000)",
            name="voice_confidence_basis_points_range",
        ),
        CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds >= 0", name="voice_duration_nonnegative"
        ),
        # PostgreSQL enforces the platform-wide one-active-call invariant even
        # when two workers race past the application-level count check.
        Index(
            "uq_voice_contact_one_active",
            "recording_enabled",
            unique=True,
            postgresql_where=text("status IN ('RESERVED', 'SUBMITTED', 'RINGING', 'IN_PROGRESS')"),
            sqlite_where=text("status IN ('RESERVED', 'SUBMITTED', 'RINGING', 'IN_PROGRESS')"),
        ),
        Index("ix_voice_attempt_daily_limit", "created_at", "status"),
    )


class VoiceWebhookReceiptRecord(Base):
    __tablename__ = "voice_webhook_receipts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(200), nullable=False)
    attempt_id: Mapped[str | None] = mapped_column(
        ForeignKey("voice_contact_attempts.id", ondelete="SET NULL"), index=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        UTCDateTime(timezone=True), nullable=False, default=utc_now
    )

    __table_args__ = (
        UniqueConstraint("provider", "provider_event_id", name="voice_webhook_provider_event"),
    )


class VoiceSuppressionRecord(Base):
    __tablename__ = "voice_suppressions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    merchant_id: Mapped[str] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False
    )
    customer_id: Mapped[str] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    source_attempt_id: Mapped[str | None] = mapped_column(
        ForeignKey("voice_contact_attempts.id", ondelete="SET NULL")
    )
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    suppressed_at: Mapped[datetime] = mapped_column(
        UTCDateTime(timezone=True), nullable=False, default=utc_now
    )

    __table_args__ = (
        UniqueConstraint("merchant_id", "customer_id", name="voice_suppression_customer"),
    )
