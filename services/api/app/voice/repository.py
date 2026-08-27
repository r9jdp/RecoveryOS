"""SQL persistence adapter for guarded voice attempts and callback receipts."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from services.api.app.domain.enums import ContactDisposition
from services.api.app.models.entities import (
    Customer,
    Merchant,
    MerchantPolicySetting,
    RecoveryCase,
)

from .models import VoiceContactAttemptRecord, VoiceSuppressionRecord, VoiceWebhookReceiptRecord
from .service import AI_DISCLOSURE, VoiceAttempt, VoiceSubject


def _to_attempt(record: VoiceContactAttemptRecord) -> VoiceAttempt:
    return VoiceAttempt(
        id=record.id,
        merchant_id=record.merchant_id,
        case_id=record.case_id,
        customer_id=record.customer_id,
        idempotency_key=record.idempotency_key,
        provider=record.provider,
        status=record.status,
        created_at=record.created_at,
        provider_call_id=record.provider_call_id,
        disposition=record.disposition,
        transcript=record.transcript,
        detected_intent=record.detected_intent,
        confidence_basis_points=record.confidence_basis_points,
        duration_seconds=record.duration_seconds,
        disclosure_delivered_at=record.disclosure_delivered_at,
        uncertain_submission=record.uncertain_submission,
    )


class SqlVoiceRepository:
    """Flushes changes into a coordinator-owned request transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def load_subject(self, case_id: str) -> VoiceSubject | None:
        statement = (
            select(RecoveryCase, Customer, Merchant, MerchantPolicySetting)
            .join(Customer, Customer.id == RecoveryCase.customer_id)
            .join(Merchant, Merchant.id == RecoveryCase.merchant_id)
            .outerjoin(MerchantPolicySetting, MerchantPolicySetting.merchant_id == Merchant.id)
            .where(RecoveryCase.id == case_id)
        )
        row = (await self.session.execute(statement)).one_or_none()
        if row is None:
            return None
        recovery_case, customer, merchant, setting = row
        if not customer.phone_token:
            return None
        return VoiceSubject(
            merchant_id=recovery_case.merchant_id,
            case_id=recovery_case.id,
            customer_id=customer.id,
            destination_token=customer.phone_token,
            preferred_language=customer.preferred_language,
            consent_verified_at=customer.voice_consent_at,
            opted_out_at=customer.opted_out_at,
            timezone=merchant.timezone,
            kill_switch=setting.recovery_kill_switch if setting else False,
            quiet_hours_start=_parse_time(setting.quiet_hours_start if setting else "20:00"),
            quiet_hours_end=_parse_time(setting.quiet_hours_end if setting else "09:00"),
        )

    async def get_by_idempotency(self, idempotency_key: str) -> VoiceAttempt | None:
        record = await self.session.scalar(
            select(VoiceContactAttemptRecord).where(
                VoiceContactAttemptRecord.idempotency_key == idempotency_key
            )
        )
        return _to_attempt(record) if record else None

    async def active_count(self) -> int:
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(VoiceContactAttemptRecord)
                .where(
                    VoiceContactAttemptRecord.status.in_(
                        {"RESERVED", "SUBMITTED", "RINGING", "IN_PROGRESS"}
                    )
                )
            )
            or 0
        )

    async def calls_today(self, now: datetime) -> int:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(VoiceContactAttemptRecord)
                .where(
                    VoiceContactAttemptRecord.created_at >= start,
                    VoiceContactAttemptRecord.created_at < start + timedelta(days=1),
                )
            )
            or 0
        )

    async def save_attempt(self, attempt: VoiceAttempt) -> VoiceAttempt:
        record = await self.session.get(VoiceContactAttemptRecord, attempt.id)
        if record is None:
            subject = await self.load_subject(attempt.case_id)
            if subject is None or subject.consent_verified_at is None:
                raise ValueError("voice subject and consent are required before reservation")
            record = VoiceContactAttemptRecord(
                id=attempt.id,
                merchant_id=attempt.merchant_id,
                case_id=attempt.case_id,
                customer_id=attempt.customer_id,
                idempotency_key=attempt.idempotency_key,
                destination_token=subject.destination_token,
                provider=attempt.provider,
                status=attempt.status,
                disclosure_text=AI_DISCLOSURE,
                consent_verified_at=subject.consent_verified_at,
                uncertain_submission=attempt.uncertain_submission,
                recording_enabled=False,
                max_duration_seconds=180,
                created_at=attempt.created_at,
                updated_at=attempt.created_at,
            )
            self.session.add(record)
        else:
            record.provider_call_id = attempt.provider_call_id
            record.status = attempt.status
            record.disposition = attempt.disposition
            record.transcript = attempt.transcript
            record.detected_intent = attempt.detected_intent
            record.confidence_basis_points = attempt.confidence_basis_points
            record.duration_seconds = attempt.duration_seconds
            record.disclosure_delivered_at = attempt.disclosure_delivered_at
            record.uncertain_submission = attempt.uncertain_submission
        await self.session.flush()
        return _to_attempt(record)

    async def get_attempt(self, attempt_id: str) -> VoiceAttempt | None:
        record = await self.session.get(VoiceContactAttemptRecord, attempt_id)
        return _to_attempt(record) if record else None

    async def list_attempts(self, case_id: str) -> list[VoiceAttempt]:
        records = (
            await self.session.scalars(
                select(VoiceContactAttemptRecord)
                .where(VoiceContactAttemptRecord.case_id == case_id)
                .order_by(VoiceContactAttemptRecord.created_at.desc())
            )
        ).all()
        return [_to_attempt(item) for item in records]

    async def apply_callback(
        self, *, provider: str, event_id: str, attempt_id: str, changes: dict[str, Any]
    ) -> tuple[VoiceAttempt | None, bool]:
        duplicate = False
        try:
            async with self.session.begin_nested():
                self.session.add(
                    VoiceWebhookReceiptRecord(
                        provider=provider,
                        provider_event_id=event_id,
                        attempt_id=attempt_id,
                        payload=changes,
                    )
                )
                await self.session.flush()
        except IntegrityError:
            duplicate = True
        record = await self.session.get(VoiceContactAttemptRecord, attempt_id)
        if record is None or duplicate:
            return (_to_attempt(record) if record else None), duplicate
        for name, value in changes.items():
            if name not in {
                "status",
                "disposition",
                "transcript",
                "detected_intent",
                "confidence_basis_points",
                "duration_seconds",
                "disclosure_delivered_at",
            }:
                raise ValueError(f"unsupported voice callback field: {name}")
            setattr(record, name, value)
        await self.session.flush()
        return _to_attempt(record), False

    async def suppress(self, *, attempt: VoiceAttempt, reason_code: str) -> bool:
        created = False
        try:
            async with self.session.begin_nested():
                self.session.add(
                    VoiceSuppressionRecord(
                        merchant_id=attempt.merchant_id,
                        customer_id=attempt.customer_id,
                        source_attempt_id=attempt.id,
                        reason_code=reason_code,
                    )
                )
                await self.session.flush()
            created = True
        except IntegrityError:
            pass
        if created:
            customer = await self.session.get(Customer, attempt.customer_id)
            recovery_case = await self.session.get(RecoveryCase, attempt.case_id)
            if customer:
                customer.opted_out_at = datetime.now(UTC)
            if recovery_case:
                recovery_case.contact_disposition = ContactDisposition.OPTED_OUT
            await self.session.flush()
        return created


def _parse_time(value: str | None) -> time | None:
    if value is None:
        return None
    return datetime.strptime(value, "%H:%M").time()
