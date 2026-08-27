"""Durable Razorpay outbox processing and case-state convergence."""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Select, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from services.api.app.domain.enums import (
    ActionStatus,
    CaseOutcome,
    ContactDisposition,
    EvidenceKind,
    PaymentState,
    RevenueAttribution,
    SubscriptionState,
)
from services.api.app.integrations.razorpay.errors import (
    RazorpayContractError,
    RazorpayIntegrationError,
)
from services.api.app.integrations.razorpay.models import (
    NormalizedRazorpayEvent,
    RazorpayOutboxPayload,
)
from services.api.app.integrations.razorpay.normalizer import normalize_webhook
from services.api.app.integrations.razorpay.reconciliation import reconcile_payment_success
from services.api.app.models import (
    Customer,
    Invoice,
    OutboxMessage,
    PaymentAttempt,
    RecoveryActionRecord,
    RecoveryCase,
    RecoveryEventRecord,
    RevenueRecognitionRecord,
    Subscription,
    WebhookInboxEntry,
)
from services.api.app.providers.interfaces import PaymentProvider
from services.api.app.services.diagnosis import DiagnosisEvidence, diagnose_failure

DEFAULT_RECOVERY_WINDOW = timedelta(days=3)


class RazorpayDownstreamSignal(BaseModel):
    """Idempotent handoff for a Temporal signal or equivalent dispatcher."""

    model_config = ConfigDict(extra="forbid")

    idempotency_key: str
    merchant_id: str
    provider_event_id: str
    event_type: str
    case_id: str | None
    normalized_event: NormalizedRazorpayEvent
    effects: dict[str, str | int | bool | None] = Field(default_factory=dict)


DownstreamSignalCallback = Callable[[RazorpayDownstreamSignal], Awaitable[None]]


class OutboxProcessResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outbox_id: str
    status: Literal["PUBLISHED", "FAILED"]
    attempt_count: int = Field(ge=1)
    provider_event_id: str | None = None
    case_id: str | None = None
    error_code: str | None = None


@dataclass(slots=True)
class _Correlation:
    subscription: Subscription | None
    invoice: Invoice | None
    recovery_case: RecoveryCase | None


class _DownstreamSignalError(RazorpayIntegrationError):
    def __init__(self) -> None:
        super().__init__(
            "RAZORPAY_DOWNSTREAM_SIGNAL_FAILED",
            "The downstream recovery signal was not confirmed.",
            retriable=True,
        )


class RazorpayOutboxProcessor:
    """Process unpublished Razorpay outbox rows with idempotent state convergence."""

    def __init__(
        self,
        session: AsyncSession,
        payment_provider: PaymentProvider,
        downstream_signal: DownstreamSignalCallback,
        *,
        clock: Callable[[], datetime] | None = None,
        retry_base_delay: timedelta = timedelta(seconds=5),
    ) -> None:
        if retry_base_delay < timedelta(0):
            raise ValueError("retry_base_delay cannot be negative")
        self.session = session
        self.payment_provider = payment_provider
        self.downstream_signal = downstream_signal
        self.clock = clock or (lambda: datetime.now(UTC))
        self.retry_base_delay = retry_base_delay

    async def process_next(self) -> OutboxProcessResult | None:
        now = self.clock()
        statement: Select[tuple[OutboxMessage]] = (
            select(OutboxMessage)
            .where(
                OutboxMessage.aggregate_type == "razorpay_webhook",
                OutboxMessage.event_type == "RAZORPAY_WEBHOOK_RECEIVED",
                OutboxMessage.published_at.is_(None),
                OutboxMessage.available_at <= now,
            )
            .order_by(OutboxMessage.available_at, OutboxMessage.created_at, OutboxMessage.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        outbox = cast(OutboxMessage | None, await self.session.scalar(statement))
        if outbox is None:
            await self.session.rollback()
            return None
        outbox_id = outbox.id
        payload: RazorpayOutboxPayload | None = None
        case_id: str | None = None
        try:
            payload = RazorpayOutboxPayload.model_validate(outbox.payload)
            inbox = await self._lock_inbox(payload)
            correlation = await self._correlate(payload)
            effects = await self._apply_event(payload, correlation)
            case_id = correlation.recovery_case.id if correlation.recovery_case else None
            outbox.attempt_count += 1
            signal = RazorpayDownstreamSignal(
                idempotency_key=outbox.deduplication_key,
                merchant_id=payload.merchant_id,
                provider_event_id=payload.event.provider_event_id,
                event_type=payload.event.event_type,
                case_id=case_id,
                normalized_event=payload.event,
                effects=effects,
            )
            try:
                await self.downstream_signal(signal)
            except Exception as error:
                raise _DownstreamSignalError from error
            completed_at = self.clock()
            inbox.processed_at = completed_at
            inbox.processing_error_code = None
            outbox.published_at = completed_at
            outbox.last_error_code = None
            await self.session.commit()
            return OutboxProcessResult(
                outbox_id=outbox_id,
                status="PUBLISHED",
                attempt_count=outbox.attempt_count,
                provider_event_id=payload.event.provider_event_id,
                case_id=case_id,
            )
        except Exception as error:
            await self.session.rollback()
            error_code = self._error_code(error)
            attempt_count = await self._record_failure(
                outbox_id=outbox_id,
                payload=payload,
                error_code=error_code,
            )
            return OutboxProcessResult(
                outbox_id=outbox_id,
                status="FAILED",
                attempt_count=attempt_count,
                provider_event_id=(payload.event.provider_event_id if payload else None),
                case_id=case_id,
                error_code=error_code,
            )

    @staticmethod
    def _error_code(error: Exception) -> str:
        if isinstance(error, RazorpayIntegrationError):
            return error.code[:128]
        return "RAZORPAY_OUTBOX_PROCESSING_FAILED"

    async def _record_failure(
        self,
        *,
        outbox_id: str,
        payload: RazorpayOutboxPayload | None,
        error_code: str,
    ) -> int:
        outbox = cast(
            OutboxMessage | None,
            await self.session.scalar(
                select(OutboxMessage).where(OutboxMessage.id == outbox_id).with_for_update()
            ),
        )
        if outbox is None:
            await self.session.rollback()
            raise RuntimeError("outbox disappeared while recording a processing failure")
        outbox.attempt_count += 1
        outbox.last_error_code = error_code
        outbox.published_at = None
        multiplier = min(2 ** (outbox.attempt_count - 1), 64)
        outbox.available_at = self.clock() + self.retry_base_delay * multiplier
        if payload is not None:
            inbox = await self._find_inbox(payload, for_update=True)
            if inbox is not None:
                inbox.processing_error_code = error_code
                inbox.processed_at = None
        await self.session.commit()
        return outbox.attempt_count

    async def _find_inbox(
        self, payload: RazorpayOutboxPayload, *, for_update: bool
    ) -> WebhookInboxEntry | None:
        statement = select(WebhookInboxEntry).where(
            WebhookInboxEntry.merchant_id == payload.merchant_id,
            WebhookInboxEntry.provider == "razorpay",
            WebhookInboxEntry.provider_event_id == payload.event.provider_event_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return cast(WebhookInboxEntry | None, await self.session.scalar(statement))

    async def _lock_inbox(self, payload: RazorpayOutboxPayload) -> WebhookInboxEntry:
        inbox = await self._find_inbox(payload, for_update=True)
        if inbox is None:
            raise RazorpayContractError(
                "RAZORPAY_INBOX_NOT_FOUND",
                "Outbox message has no matching Razorpay inbox entry.",
            )
        if inbox.processed_at is not None:
            raise RazorpayContractError(
                "RAZORPAY_INBOX_ALREADY_PROCESSED",
                "Published state is inconsistent with an already processed inbox entry.",
            )
        return inbox

    async def _correlate(self, payload: RazorpayOutboxPayload) -> _Correlation:
        event = payload.event
        merchant_id = payload.merchant_id
        recovery_case: RecoveryCase | None = None
        invoice: Invoice | None = None
        subscription: Subscription | None = None

        if event.case_id:
            recovery_case = cast(
                RecoveryCase | None,
                await self.session.scalar(
                    select(RecoveryCase)
                    .where(
                        RecoveryCase.id == event.case_id,
                        RecoveryCase.merchant_id == merchant_id,
                    )
                    .with_for_update()
                ),
            )
            if recovery_case is None:
                raise RazorpayContractError(
                    "RAZORPAY_CASE_NOT_CORRELATED",
                    "Webhook case_id does not belong to this merchant.",
                )

        if event.invoice_id:
            invoice = cast(
                Invoice | None,
                await self.session.scalar(
                    select(Invoice)
                    .where(
                        Invoice.merchant_id == merchant_id,
                        Invoice.provider_invoice_id == event.invoice_id,
                    )
                    .with_for_update()
                ),
            )
            if invoice is None:
                raise RazorpayContractError(
                    "RAZORPAY_INVOICE_NOT_CORRELATED",
                    "Webhook invoice does not belong to this merchant.",
                )
        elif recovery_case and recovery_case.failed_invoice_id:
            invoice = cast(
                Invoice | None,
                await self.session.scalar(
                    select(Invoice)
                    .where(
                        Invoice.id == recovery_case.failed_invoice_id,
                        Invoice.merchant_id == merchant_id,
                    )
                    .with_for_update()
                ),
            )

        if event.subscription_id:
            subscription = cast(
                Subscription | None,
                await self.session.scalar(
                    select(Subscription)
                    .where(
                        Subscription.merchant_id == merchant_id,
                        Subscription.provider_subscription_id == event.subscription_id,
                    )
                    .with_for_update()
                ),
            )
            if subscription is None:
                raise RazorpayContractError(
                    "RAZORPAY_SUBSCRIPTION_NOT_CORRELATED",
                    "Webhook subscription does not belong to this merchant.",
                )
        elif invoice:
            subscription = cast(
                Subscription | None,
                await self.session.scalar(
                    select(Subscription)
                    .where(
                        Subscription.id == invoice.subscription_id,
                        Subscription.merchant_id == merchant_id,
                    )
                    .with_for_update()
                ),
            )
        elif recovery_case:
            subscription = cast(
                Subscription | None,
                await self.session.scalar(
                    select(Subscription)
                    .where(
                        Subscription.id == recovery_case.subscription_id,
                        Subscription.merchant_id == merchant_id,
                    )
                    .with_for_update()
                ),
            )

        if invoice and subscription and invoice.subscription_id != subscription.id:
            raise RazorpayContractError(
                "RAZORPAY_CORRELATION_MISMATCH",
                "Webhook invoice and subscription do not match.",
            )
        if recovery_case and invoice and recovery_case.failed_invoice_id != invoice.id:
            raise RazorpayContractError(
                "RAZORPAY_CORRELATION_MISMATCH",
                "Webhook case and invoice do not match.",
            )
        if recovery_case and subscription and recovery_case.subscription_id != subscription.id:
            raise RazorpayContractError(
                "RAZORPAY_CORRELATION_MISMATCH",
                "Webhook case and subscription do not match.",
            )

        if recovery_case is None and invoice is not None:
            recovery_case = cast(
                RecoveryCase | None,
                await self.session.scalar(
                    select(RecoveryCase)
                    .where(
                        RecoveryCase.merchant_id == merchant_id,
                        RecoveryCase.failed_invoice_id == invoice.id,
                    )
                    .with_for_update()
                ),
            )
        if recovery_case is None and subscription is not None and invoice is None:
            recovery_case = cast(
                RecoveryCase | None,
                await self.session.scalar(
                    select(RecoveryCase)
                    .where(
                        RecoveryCase.merchant_id == merchant_id,
                        RecoveryCase.subscription_id == subscription.id,
                    )
                    .order_by(RecoveryCase.opened_at.desc(), RecoveryCase.id.desc())
                    .limit(1)
                    .with_for_update()
                ),
            )
        return _Correlation(subscription, invoice, recovery_case)

    async def _apply_event(
        self, payload: RazorpayOutboxPayload, correlation: _Correlation
    ) -> dict[str, str | int | bool | None]:
        event = payload.event
        if event.event_type == "payment.failed":
            return await self._apply_payment_failed(payload, correlation)
        if event.payment_state == PaymentState.CAPTURED:
            return await self._apply_captured(payload, correlation)
        if event.event_type in {"subscription.pending", "subscription.halted"}:
            return await self._apply_subscription_only(payload, correlation)
        raise RazorpayContractError(
            "RAZORPAY_EVENT_PROCESSOR_UNSUPPORTED",
            f"No outbox processor exists for {event.event_type}.",
        )

    @staticmethod
    def _payment_entity(event: NormalizedRazorpayEvent) -> dict[str, Any]:
        raw_payload = event.provider_payload.get("payload")
        if not isinstance(raw_payload, dict):
            return {}
        payment_container = raw_payload.get("payment")
        if not isinstance(payment_container, dict):
            return {}
        entity = payment_container.get("entity")
        return cast(dict[str, Any], entity) if isinstance(entity, dict) else {}

    @staticmethod
    def _payment_attempt_id(provider_payment_id: str) -> str:
        digest = hashlib.sha256(provider_payment_id.encode()).hexdigest()[:48]
        return f"pay_rzp_{digest}"

    async def _payment_attempt(
        self, *, merchant_id: str, provider_payment_id: str
    ) -> PaymentAttempt | None:
        return cast(
            PaymentAttempt | None,
            await self.session.scalar(
                select(PaymentAttempt)
                .where(
                    PaymentAttempt.merchant_id == merchant_id,
                    PaymentAttempt.provider_payment_id == provider_payment_id,
                )
                .with_for_update()
            ),
        )

    async def _apply_payment_failed(
        self, payload: RazorpayOutboxPayload, correlation: _Correlation
    ) -> dict[str, str | int | bool | None]:
        event = payload.event
        if correlation.invoice is None or correlation.subscription is None:
            raise RazorpayContractError(
                "RAZORPAY_FAILURE_NOT_CORRELATED",
                "payment.failed requires a known invoice and subscription.",
            )
        if event.payment_id is None or event.amount_paise is None or event.currency is None:
            raise RazorpayContractError(
                "RAZORPAY_FAILURE_PAYMENT_INVALID",
                "payment.failed is missing payment identity, amount, or currency.",
            )
        if (
            event.amount_paise <= 0
            or event.amount_paise > correlation.invoice.amount_paise
            or event.currency != correlation.invoice.currency
        ):
            raise RazorpayContractError(
                "RAZORPAY_FAILURE_AMOUNT_MISMATCH",
                "Failed payment amount or currency does not match the trusted invoice.",
            )
        payment_entity = self._payment_entity(event)
        payment = await self._payment_attempt(
            merchant_id=payload.merchant_id, provider_payment_id=event.payment_id
        )
        state_applied = False
        if payment is None:
            payment = PaymentAttempt(
                id=self._payment_attempt_id(event.payment_id),
                merchant_id=payload.merchant_id,
                invoice_id=correlation.invoice.id,
                subscription_id=correlation.subscription.id,
                provider_payment_id=event.payment_id,
                amount_paise=event.amount_paise,
                currency=event.currency,
                payment_state=PaymentState.FAILED,
                method=cast(str | None, payment_entity.get("method")),
                error_code=cast(str | None, payment_entity.get("error_code")),
                error_source=cast(str | None, payment_entity.get("error_source")),
                error_step=cast(str | None, payment_entity.get("error_step")),
                error_reason=cast(str | None, payment_entity.get("error_reason")),
                occurred_at=event.occurred_at,
            )
            self.session.add(payment)
            await self.session.flush()
            state_applied = True
        elif payment.invoice_id != correlation.invoice.id:
            raise RazorpayContractError(
                "RAZORPAY_PAYMENT_CORRELATION_MISMATCH",
                "Provider payment is already attached to another invoice.",
            )
        elif (
            payment.payment_state != PaymentState.CAPTURED
            and event.occurred_at >= payment.occurred_at
        ):
            payment.payment_state = PaymentState.FAILED
            payment.error_code = cast(str | None, payment_entity.get("error_code"))
            payment.error_source = cast(str | None, payment_entity.get("error_source"))
            payment.error_step = cast(str | None, payment_entity.get("error_step"))
            payment.error_reason = cast(str | None, payment_entity.get("error_reason"))
            payment.occurred_at = event.occurred_at
            state_applied = True

        recovery_case = correlation.recovery_case
        case_created = recovery_case is None
        if recovery_case is None:
            recovery_case = await self._create_case_for_failure(
                payload=payload,
                correlation=correlation,
                payment=payment,
                payment_entity=payment_entity,
            )
            correlation.recovery_case = recovery_case
        if recovery_case is not None:
            if (
                state_applied
                and not case_created
                and recovery_case.payment_state != PaymentState.CAPTURED
            ):
                recovery_case.payment_state = PaymentState.FAILED
                recovery_case.failed_payment_id = payment.id
                recovery_case.version += 1
            await self._add_audit_event(
                recovery_case,
                event,
                {
                    "payment_id": event.payment_id,
                    "payment_state": PaymentState.FAILED.value,
                    "state_applied": state_applied,
                    "state_regressed": False,
                    "case_created": case_created,
                },
            )
        return {
            "payment_state": PaymentState.FAILED.value,
            "state_applied": state_applied,
            "case_correlated": recovery_case is not None,
            "case_created": case_created,
            "arrears_collected_paise": 0,
            "subscription_reactivated": False,
        }

    async def _create_case_for_failure(
        self,
        *,
        payload: RazorpayOutboxPayload,
        correlation: _Correlation,
        payment: PaymentAttempt,
        payment_entity: dict[str, Any],
    ) -> RecoveryCase:
        event = payload.event
        invoice = correlation.invoice
        subscription = correlation.subscription
        if invoice is None or subscription is None:
            raise RazorpayContractError(
                "RAZORPAY_FAILURE_NOT_CORRELATED",
                "A recovery case requires a trusted invoice and subscription.",
            )
        customer = cast(
            Customer | None,
            await self.session.scalar(
                select(Customer)
                .where(
                    Customer.id == subscription.customer_id,
                    Customer.merchant_id == payload.merchant_id,
                )
                .with_for_update()
            ),
        )
        if customer is None:
            raise RazorpayContractError(
                "RAZORPAY_CUSTOMER_NOT_CORRELATED",
                "The persisted subscription has no trusted merchant customer.",
            )
        amount_at_risk_paise = invoice.amount_paise - invoice.amount_paid_paise
        if amount_at_risk_paise <= 0:
            raise RazorpayContractError(
                "RAZORPAY_INVOICE_ALREADY_PAID",
                "A recovery case cannot be opened for a fully paid invoice.",
            )
        digest = hashlib.sha256(f"{payload.merchant_id}:{invoice.id}".encode()).hexdigest()[:40]
        diagnosis = diagnose_failure(
            DiagnosisEvidence(
                payment_state=PaymentState.FAILED,
                event_type=event.event_type,
                invoice_correlated=True,
                subscription_correlated=True,
                error_code=cast(str | None, payment_entity.get("error_code")),
                error_source=cast(str | None, payment_entity.get("error_source")),
                error_step=cast(str | None, payment_entity.get("error_step")),
                error_reason=cast(str | None, payment_entity.get("error_reason")),
            )
        )
        recovery_case = RecoveryCase(
            id=f"case_rzp_{digest}",
            merchant_id=payload.merchant_id,
            customer_id=customer.id,
            subscription_id=subscription.id,
            failed_invoice_id=invoice.id,
            billing_cycle_key=invoice.billing_cycle_key,
            failed_payment_id=payment.id,
            case_outcome=CaseOutcome.OPEN,
            payment_state=PaymentState.FAILED,
            subscription_state=subscription.subscription_state,
            contact_disposition=ContactDisposition.NOT_CONTACTED,
            revenue_attribution=RevenueAttribution.NONE,
            diagnosis=diagnosis,
            amount_at_risk_paise=amount_at_risk_paise,
            arrears_collected_paise=0,
            case_recovered=False,
            subscription_reactivated=False,
            opened_at=event.occurred_at,
            recovery_deadline=event.occurred_at + DEFAULT_RECOVERY_WINDOW,
            version=1,
        )
        self.session.add(recovery_case)
        await self.session.flush()
        return recovery_case

    async def _apply_captured(
        self, payload: RazorpayOutboxPayload, correlation: _Correlation
    ) -> dict[str, str | int | bool | None]:
        event = payload.event
        recovery_case = correlation.recovery_case
        invoice = correlation.invoice
        subscription = correlation.subscription
        if recovery_case is None or invoice is None or subscription is None:
            raise RazorpayContractError(
                "RAZORPAY_CAPTURE_NOT_CORRELATED",
                "Captured payment requires a known recovery case, invoice, and subscription.",
            )
        snapshot = await self.payment_provider.fetch_payment_snapshot(
            merchant_id=payload.merchant_id,
            payment_id=event.payment_id,
            invoice_id=invoice.provider_invoice_id,
        )
        outcome = reconcile_payment_success(
            event=event,
            snapshot=snapshot,
            current_payment_state=recovery_case.payment_state,
        )
        if snapshot.payment_state != PaymentState.CAPTURED:
            raise RazorpayContractError(
                "RAZORPAY_CAPTURE_NOT_CONFIRMED",
                "Authoritative Razorpay state does not confirm capture.",
            )
        if (
            snapshot.subscription_id
            and snapshot.subscription_id != subscription.provider_subscription_id
        ):
            raise RazorpayContractError(
                "RAZORPAY_CORRELATION_MISMATCH",
                "Authoritative subscription does not match the failed invoice.",
            )
        if snapshot.currency != invoice.currency:
            raise RazorpayContractError(
                "RAZORPAY_CAPTURE_CURRENCY_MISMATCH",
                "Captured payment currency does not match the invoice.",
            )
        provider_payment_id = snapshot.payment_id or event.payment_id
        if provider_payment_id is None:
            raise RazorpayContractError(
                "RAZORPAY_CAPTURE_PAYMENT_ID_MISSING",
                "Authoritative capture has no payment id.",
            )
        payment = await self._payment_attempt(
            merchant_id=payload.merchant_id,
            provider_payment_id=provider_payment_id,
        )
        if payment is None:
            payment = PaymentAttempt(
                id=self._payment_attempt_id(provider_payment_id),
                merchant_id=payload.merchant_id,
                invoice_id=invoice.id,
                subscription_id=subscription.id,
                provider_payment_id=provider_payment_id,
                amount_paise=snapshot.amount_paise,
                currency=snapshot.currency,
                payment_state=PaymentState.CAPTURED,
                method=cast(str | None, self._payment_entity(event).get("method")),
                occurred_at=event.occurred_at,
            )
            self.session.add(payment)
            await self.session.flush()
        elif payment.invoice_id != invoice.id:
            raise RazorpayContractError(
                "RAZORPAY_PAYMENT_CORRELATION_MISMATCH",
                "Captured provider payment is attached to another invoice.",
            )
        else:
            payment.payment_state = PaymentState.CAPTURED
            payment.amount_paise = snapshot.amount_paise
            payment.currency = snapshot.currency
            if event.occurred_at >= payment.occurred_at:
                payment.occurred_at = event.occurred_at

        existing_recognition = cast(
            RevenueRecognitionRecord | None,
            await self.session.scalar(
                select(RevenueRecognitionRecord)
                .where(
                    RevenueRecognitionRecord.merchant_id == payload.merchant_id,
                    RevenueRecognitionRecord.provider == "razorpay",
                    or_(
                        RevenueRecognitionRecord.provider_event_id == event.provider_event_id,
                        RevenueRecognitionRecord.payment_attempt_id == payment.id,
                    ),
                )
                .with_for_update()
            ),
        )
        newly_recognized = existing_recognition is None
        amount_collected = 0
        secondary_case_change = (
            recovery_case.payment_state != PaymentState.CAPTURED
            or (outcome.subscription_reactivated and not recovery_case.subscription_reactivated)
            or (
                snapshot.subscription_state != SubscriptionState.UNKNOWN
                and recovery_case.subscription_state != snapshot.subscription_state
            )
        )
        if newly_recognized:
            remaining_invoice = invoice.amount_paise - invoice.amount_paid_paise
            remaining_case = (
                recovery_case.amount_at_risk_paise - recovery_case.arrears_collected_paise
            )
            if snapshot.amount_paise <= 0 or snapshot.amount_paise > min(
                remaining_invoice, remaining_case
            ):
                raise RazorpayContractError(
                    "RAZORPAY_CAPTURE_AMOUNT_INVALID",
                    "Captured amount exceeds the remaining correlated arrears.",
                )
            amount_collected = snapshot.amount_paise
            self.session.add(
                RevenueRecognitionRecord(
                    case_id=recovery_case.id,
                    merchant_id=payload.merchant_id,
                    payment_attempt_id=payment.id,
                    provider="razorpay",
                    provider_event_id=event.provider_event_id,
                    amount_paise=amount_collected,
                    attribution=RevenueAttribution.RAZORPAY_TEST_VERIFIED,
                    arrears_collected=True,
                    subscription_reactivated=outcome.subscription_reactivated,
                    recognized_at=event.occurred_at,
                )
            )
            await self.session.flush()
            invoice.amount_paid_paise += amount_collected
            if invoice.amount_paid_paise == invoice.amount_paise:
                invoice.invoice_state = "paid"
            recovery_case.arrears_collected_paise += amount_collected
            recovery_case.revenue_attribution = RevenueAttribution.RAZORPAY_TEST_VERIFIED
            recovery_case.version += 1
        elif secondary_case_change:
            recovery_case.version += 1

        recovery_case.payment_state = PaymentState.CAPTURED
        recovery_case.subscription_reactivated = (
            recovery_case.subscription_reactivated or outcome.subscription_reactivated
        )
        if snapshot.subscription_state != SubscriptionState.UNKNOWN:
            subscription.subscription_state = snapshot.subscription_state
            recovery_case.subscription_state = snapshot.subscription_state
        recovery_case.case_recovered = (
            recovery_case.arrears_collected_paise >= recovery_case.amount_at_risk_paise
        )
        if recovery_case.case_recovered:
            recovery_case.case_outcome = CaseOutcome.RECOVERED
            recovery_case.recovered_at = event.occurred_at
            await self.session.execute(
                update(RecoveryActionRecord)
                .where(
                    RecoveryActionRecord.case_id == recovery_case.id,
                    RecoveryActionRecord.status.in_(
                        {
                            ActionStatus.PROPOSED,
                            ActionStatus.AWAITING_APPROVAL,
                            ActionStatus.SCHEDULED,
                            ActionStatus.EXECUTING,
                        }
                    ),
                )
                .values(
                    status=ActionStatus.CANCELLED,
                    completed_at=event.occurred_at,
                    updated_at=event.occurred_at,
                )
            )
        elif recovery_case.arrears_collected_paise > 0:
            recovery_case.case_outcome = CaseOutcome.PARTIALLY_RECOVERED
        await self._add_audit_event(
            recovery_case,
            event,
            {
                "payment_id": provider_payment_id,
                "amount_paise": snapshot.amount_paise,
                "newly_recognized": newly_recognized,
                "arrears_collected": outcome.arrears_collected,
                "subscription_reactivated": outcome.subscription_reactivated,
                "late_success": outcome.late_success,
            },
        )
        return {
            "payment_state": PaymentState.CAPTURED.value,
            "newly_recognized": newly_recognized,
            "arrears_collected_paise": amount_collected,
            "subscription_reactivated": outcome.subscription_reactivated,
            "case_recovered": recovery_case.case_recovered,
        }

    async def _newer_processed_subscription_event_exists(
        self, payload: RazorpayOutboxPayload
    ) -> bool:
        subscription_id = payload.event.subscription_id
        if subscription_id is None:
            return False
        entries = list(
            (
                await self.session.scalars(
                    select(WebhookInboxEntry).where(
                        WebhookInboxEntry.merchant_id == payload.merchant_id,
                        WebhookInboxEntry.provider == "razorpay",
                        WebhookInboxEntry.processed_at.is_not(None),
                        WebhookInboxEntry.event_type.in_(
                            {"subscription.pending", "subscription.halted"}
                        ),
                        WebhookInboxEntry.occurred_at > payload.event.occurred_at,
                    )
                )
            ).all()
        )
        for entry in entries:
            try:
                normalized = normalize_webhook(
                    provider_event_id=entry.provider_event_id,
                    payload=entry.payload,
                )
            except RazorpayIntegrationError:
                continue
            if normalized.subscription_id == subscription_id:
                return True
        return False

    async def _apply_subscription_only(
        self, payload: RazorpayOutboxPayload, correlation: _Correlation
    ) -> dict[str, str | int | bool | None]:
        event = payload.event
        if (
            correlation.subscription is None
            or event.subscription_state == SubscriptionState.UNKNOWN
        ):
            raise RazorpayContractError(
                "RAZORPAY_SUBSCRIPTION_EVENT_NOT_CORRELATED",
                "Subscription lifecycle event has no known subscription.",
            )
        stale = await self._newer_processed_subscription_event_exists(payload)
        if not stale:
            correlation.subscription.subscription_state = event.subscription_state
            if correlation.recovery_case is not None:
                correlation.recovery_case.subscription_state = event.subscription_state
                correlation.recovery_case.version += 1
        if correlation.recovery_case is not None:
            await self._add_audit_event(
                correlation.recovery_case,
                event,
                {
                    "subscription_state": event.subscription_state.value,
                    "state_applied": not stale,
                    "stale_event": stale,
                },
            )
        return {
            "subscription_state": event.subscription_state.value,
            "state_applied": not stale,
            "stale_event": stale,
            "case_correlated": correlation.recovery_case is not None,
            "arrears_collected_paise": 0,
        }

    async def _add_audit_event(
        self,
        recovery_case: RecoveryCase,
        event: NormalizedRazorpayEvent,
        details: dict[str, Any],
    ) -> None:
        existing = await self.session.scalar(
            select(RecoveryEventRecord.id).where(
                RecoveryEventRecord.case_id == recovery_case.id,
                RecoveryEventRecord.source_event_id == event.provider_event_id,
            )
        )
        if existing is not None:
            return
        self.session.add(
            RecoveryEventRecord(
                case_id=recovery_case.id,
                event_type=event.event_type.upper().replace(".", "_"),
                source="razorpay",
                evidence_kind=EvidenceKind.RAZORPAY_TEST_VERIFIED,
                payload=details,
                occurred_at=event.occurred_at,
                correlation_id=f"rzp_{recovery_case.id}"[:128],
                source_event_id=event.provider_event_id,
            )
        )
