"""Normalized persistence model for recovery orchestration.

All monetary values are integer paise. Independent recovery state axes remain
separate columns so contact suppression, payment collection, subscription state,
and accounting attribution can converge independently.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from services.api.app.db.base import Base
from services.api.app.domain.enums import (
    ActionStatus,
    CaseOutcome,
    ContactDisposition,
    Diagnosis,
    EvidenceKind,
    PaymentState,
    PaymentSurfaceType,
    PolicyDisposition,
    RecoveryActionType,
    RevenueAttribution,
    SubscriptionState,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid4())


class UTCDateTime(TypeDecorator[datetime]):
    """Persist UTC and restore tzinfo for dialects such as SQLite."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        del dialect
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("database timestamps must be timezone-aware")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        del dialect
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


def enum_type(enum: type[StrEnum], name: str) -> Enum:
    """Use checks locally while retaining explicit stable enum names for Postgres."""

    return Enum(enum, name=name, native_enum=False, create_constraint=True)


class Timestamped:
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class Merchant(Timestamped, Base):
    __tablename__ = "merchants"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    external_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Kolkata")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")

    __table_args__ = (CheckConstraint("length(currency) = 3", name="currency_length"),)


class MerchantPolicySetting(Timestamped, Base):
    """Mutable merchant controls kept separate from the frozen merchant identity."""

    __tablename__ = "merchant_policy_settings"

    merchant_id: Mapped[str] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"), primary_key=True
    )
    quiet_hours_start: Mapped[str | None] = mapped_column(String(5), default="20:00")
    quiet_hours_end: Mapped[str | None] = mapped_column(String(5), default="09:00")
    max_contacts_per_7_days: Mapped[int | None] = mapped_column(Integer, default=2)
    require_approval_above_paise: Mapped[int | None] = mapped_column(BigInteger, default=500_000)
    require_approval_actions: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    recovery_kill_switch: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "(quiet_hours_start IS NULL) = (quiet_hours_end IS NULL)",
            name="policy_quiet_pair",
        ),
        CheckConstraint(
            "max_contacts_per_7_days IS NULL OR max_contacts_per_7_days > 0",
            name="policy_contact_limit_positive",
        ),
        CheckConstraint(
            "require_approval_above_paise IS NULL OR require_approval_above_paise >= 0",
            name="approval_threshold_nonnegative",
        ),
        CheckConstraint("version >= 1", name="policy_settings_version_positive"),
    )


class Customer(Timestamped, Base):
    __tablename__ = "customers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    merchant_id: Mapped[str] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    email_token: Mapped[str | None] = mapped_column(String(256))
    phone_token: Mapped[str | None] = mapped_column(String(256))
    preferred_language: Mapped[str] = mapped_column(String(32), nullable=False, default="en-IN")
    voice_consent_at: Mapped[datetime | None] = mapped_column(UTCDateTime(timezone=True))
    opted_out_at: Mapped[datetime | None] = mapped_column(UTCDateTime(timezone=True))
    customer_agent_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint("merchant_id", "external_id", name="customer_merchant_external"),
    )


class Subscription(Timestamped, Base):
    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    merchant_id: Mapped[str] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[str] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    provider_subscription_id: Mapped[str] = mapped_column(String(128), nullable=False)
    plan_name: Mapped[str] = mapped_column(String(200), nullable=False)
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    subscription_state: Mapped[SubscriptionState] = mapped_column(
        enum_type(SubscriptionState, "subscription_state"),
        nullable=False,
        default=SubscriptionState.UNKNOWN,
    )
    current_billing_cycle_key: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        UniqueConstraint(
            "merchant_id", "provider_subscription_id", name="subscription_merchant_provider"
        ),
        CheckConstraint("amount_paise >= 0", name="subscription_amount_nonnegative"),
        CheckConstraint("length(currency) = 3", name="subscription_currency_length"),
    )


class Invoice(Timestamped, Base):
    __tablename__ = "invoices"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    merchant_id: Mapped[str] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subscription_id: Mapped[str] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    provider_invoice_id: Mapped[str] = mapped_column(String(128), nullable=False)
    billing_cycle_key: Mapped[str] = mapped_column(String(64), nullable=False)
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount_paid_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    invoice_state: Mapped[str] = mapped_column(String(32), nullable=False, default="issued")
    due_at: Mapped[datetime | None] = mapped_column(UTCDateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("merchant_id", "provider_invoice_id", name="invoice_merchant_provider"),
        UniqueConstraint(
            "merchant_id", "subscription_id", "billing_cycle_key", name="invoice_billing_cycle"
        ),
        CheckConstraint("amount_paise >= 0", name="invoice_amount_nonnegative"),
        CheckConstraint("amount_paid_paise >= 0", name="invoice_paid_nonnegative"),
        CheckConstraint("amount_paid_paise <= amount_paise", name="invoice_paid_lte_amount"),
    )


class PaymentAttempt(Timestamped, Base):
    __tablename__ = "payment_attempts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    merchant_id: Mapped[str] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    invoice_id: Mapped[str] = mapped_column(
        ForeignKey("invoices.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    subscription_id: Mapped[str] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    provider_payment_id: Mapped[str | None] = mapped_column(String(128))
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    payment_state: Mapped[PaymentState] = mapped_column(
        enum_type(PaymentState, "payment_state"), nullable=False, default=PaymentState.UNKNOWN
    )
    method: Mapped[str | None] = mapped_column(String(32))
    error_code: Mapped[str | None] = mapped_column(String(128))
    error_source: Mapped[str | None] = mapped_column(String(64))
    error_step: Mapped[str | None] = mapped_column(String(64))
    error_reason: Mapped[str | None] = mapped_column(String(128))
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "merchant_id", "provider_payment_id", name="payment_attempt_merchant_provider"
        ),
        CheckConstraint("amount_paise >= 0", name="payment_attempt_amount_nonnegative"),
    )


class RecoveryCase(Timestamped, Base):
    __tablename__ = "recovery_cases"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    merchant_id: Mapped[str] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[str] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    subscription_id: Mapped[str] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    failed_invoice_id: Mapped[str | None] = mapped_column(
        ForeignKey("invoices.id", ondelete="RESTRICT"), index=True
    )
    billing_cycle_key: Mapped[str | None] = mapped_column(String(64))
    failed_payment_id: Mapped[str | None] = mapped_column(
        ForeignKey("payment_attempts.id", ondelete="SET NULL")
    )
    case_outcome: Mapped[CaseOutcome] = mapped_column(
        enum_type(CaseOutcome, "case_outcome"), nullable=False, default=CaseOutcome.OPEN
    )
    payment_state: Mapped[PaymentState] = mapped_column(
        enum_type(PaymentState, "case_payment_state"),
        nullable=False,
        default=PaymentState.FAILED,
    )
    subscription_state: Mapped[SubscriptionState] = mapped_column(
        enum_type(SubscriptionState, "case_subscription_state"),
        nullable=False,
        default=SubscriptionState.UNKNOWN,
    )
    contact_disposition: Mapped[ContactDisposition] = mapped_column(
        enum_type(ContactDisposition, "contact_disposition"),
        nullable=False,
        default=ContactDisposition.NOT_CONTACTED,
    )
    revenue_attribution: Mapped[RevenueAttribution] = mapped_column(
        enum_type(RevenueAttribution, "revenue_attribution"),
        nullable=False,
        default=RevenueAttribution.NONE,
    )
    diagnosis: Mapped[Diagnosis] = mapped_column(
        enum_type(Diagnosis, "diagnosis"), nullable=False, default=Diagnosis.UNKNOWN
    )
    amount_at_risk_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    arrears_collected_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    case_recovered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    subscription_reactivated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    opened_at: Mapped[datetime] = mapped_column(UTCDateTime(timezone=True), nullable=False)
    recovery_deadline: Mapped[datetime] = mapped_column(UTCDateTime(timezone=True), nullable=False)
    recovered_at: Mapped[datetime | None] = mapped_column(UTCDateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        UniqueConstraint("merchant_id", "failed_invoice_id", name="case_failed_invoice"),
        CheckConstraint(
            "failed_invoice_id IS NOT NULL OR billing_cycle_key IS NOT NULL",
            name="case_has_invoice_or_cycle",
        ),
        CheckConstraint("amount_at_risk_paise >= 0", name="case_risk_nonnegative"),
        CheckConstraint("arrears_collected_paise >= 0", name="case_collected_nonnegative"),
        CheckConstraint("version >= 1", name="case_version_positive"),
        CheckConstraint("recovery_deadline > opened_at", name="case_deadline_after_open"),
        Index(
            "uq_recovery_cases_fallback_cycle",
            "merchant_id",
            "billing_cycle_key",
            unique=True,
            postgresql_where=(failed_invoice_id.is_(None)),
            sqlite_where=(failed_invoice_id.is_(None)),
        ),
        Index("ix_recovery_cases_outcome_opened", "case_outcome", "opened_at", "id"),
    )


class PolicyDecisionRecord(Base):
    __tablename__ = "policy_decisions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("recovery_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action_id: Mapped[str | None] = mapped_column(
        ForeignKey("recovery_actions.id", ondelete="SET NULL"), index=True
    )
    disposition: Mapped[PolicyDisposition] = mapped_column(
        enum_type(PolicyDisposition, "policy_disposition"), nullable=False
    )
    decision_code: Mapped[str] = mapped_column(String(128), nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    reasons: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    delay_until: Mapped[datetime | None] = mapped_column(UTCDateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(timezone=True), default=utc_now)

    __table_args__ = (
        CheckConstraint(
            "(disposition = 'DELAY' AND delay_until IS NOT NULL) OR "
            "(disposition <> 'DELAY' AND delay_until IS NULL)",
            name="policy_delay_timestamp",
        ),
    )


class RecoveryActionRecord(Timestamped, Base):
    __tablename__ = "recovery_actions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("recovery_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action_type: Mapped[RecoveryActionType] = mapped_column(
        enum_type(RecoveryActionType, "recovery_action_type"), nullable=False
    )
    payment_surface_type: Mapped[PaymentSurfaceType | None] = mapped_column(
        enum_type(PaymentSurfaceType, "payment_surface_type")
    )
    status: Mapped[ActionStatus] = mapped_column(
        enum_type(ActionStatus, "action_status"), nullable=False, default=ActionStatus.PROPOSED
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    scheduled_for: Mapped[datetime | None] = mapped_column(UTCDateTime(timezone=True))
    external_reference: Mapped[str | None] = mapped_column(String(256))
    customer_url: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "(action_type = 'OPEN_CUSTOMER_PAYMENT_SURFACE' AND "
            "payment_surface_type IS NOT NULL) OR "
            "(action_type <> 'OPEN_CUSTOMER_PAYMENT_SURFACE' AND "
            "payment_surface_type IS NULL)",
            name="action_surface_matches_type",
        ),
    )


class RecoveryEventRecord(Base):
    __tablename__ = "recovery_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("recovery_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_kind: Mapped[EvidenceKind] = mapped_column(
        enum_type(EvidenceKind, "evidence_kind"), nullable=False
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        UTCDateTime(timezone=True), nullable=False, default=utc_now
    )
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    source_event_id: Mapped[str | None] = mapped_column(String(200))

    __table_args__ = (
        UniqueConstraint("case_id", "source_event_id", name="event_case_source_event"),
        Index("ix_recovery_events_timeline", "case_id", "occurred_at", "recorded_at", "id"),
    )


class WebhookInboxEntry(Base):
    __tablename__ = "webhook_inbox"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    merchant_id: Mapped[str] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(200), nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        UTCDateTime(timezone=True), nullable=False, default=utc_now
    )
    occurred_at: Mapped[datetime | None] = mapped_column(UTCDateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(timezone=True))
    processing_error_code: Mapped[str | None] = mapped_column(String(128))

    __table_args__ = (
        UniqueConstraint(
            "merchant_id", "provider", "provider_event_id", name="webhook_provider_event"
        ),
    )


class OutboxMessage(Base):
    __tablename__ = "outbox_messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    deduplication_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    available_at: Mapped[datetime] = mapped_column(
        UTCDateTime(timezone=True), nullable=False, default=utc_now
    )
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error_code: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(timezone=True), nullable=False, default=utc_now
    )

    __table_args__ = (
        CheckConstraint("attempt_count >= 0", name="outbox_attempt_nonnegative"),
        Index("ix_outbox_unpublished", "published_at", "available_at", "id"),
    )


class RevenueRecognitionRecord(Base):
    __tablename__ = "revenue_recognition"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("recovery_cases.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    merchant_id: Mapped[str] = mapped_column(
        ForeignKey("merchants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    payment_attempt_id: Mapped[str | None] = mapped_column(
        ForeignKey("payment_attempts.id", ondelete="SET NULL")
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(200), nullable=False)
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    attribution: Mapped[RevenueAttribution] = mapped_column(
        enum_type(RevenueAttribution, "recognition_attribution"), nullable=False
    )
    arrears_collected: Mapped[bool] = mapped_column(Boolean, nullable=False)
    subscription_reactivated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    recognized_at: Mapped[datetime] = mapped_column(UTCDateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "merchant_id", "provider", "provider_event_id", name="revenue_provider_event"
        ),
        CheckConstraint("amount_paise > 0", name="revenue_amount_positive"),
        CheckConstraint("attribution <> 'NONE'", name="revenue_has_attribution"),
    )
