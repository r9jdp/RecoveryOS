"""Recovery-case queries and atomic persistence operations."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from sqlalchemy import Select, and_, case, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from services.api.app.domain.enums import (
    ActionStatus,
    CaseOutcome,
    Diagnosis,
    PaymentSurfaceType,
    RecoveryActionType,
    RevenueAttribution,
    SubscriptionState,
)
from services.api.app.models import (
    Customer,
    Invoice,
    Merchant,
    MerchantPolicySetting,
    PaymentAttempt,
    PolicyDecisionRecord,
    RecoveryActionRecord,
    RecoveryCase,
    RecoveryEventRecord,
    RevenueRecognitionRecord,
    Subscription,
)


class InvalidCursorError(ValueError):
    """Raised when a cursor is malformed or uses an unsupported version."""


@dataclass(frozen=True, slots=True)
class CaseFilters:
    outcomes: tuple[CaseOutcome, ...] = ()
    diagnoses: tuple[Diagnosis, ...] = ()
    subscription_states: tuple[SubscriptionState, ...] = ()
    opened_from: datetime | None = None
    opened_to: datetime | None = None


@dataclass(frozen=True, slots=True)
class CasePage:
    items: list[RecoveryCase]
    next_cursor: str | None
    has_more: bool


@dataclass(frozen=True, slots=True)
class CaseAggregate:
    recovery_case: RecoveryCase
    customer: Customer
    subscription: Subscription
    invoice: Invoice | None
    failed_payment: PaymentAttempt | None
    latest_action: RecoveryActionRecord | None
    latest_policy: PolicyDecisionRecord | None


def _encode_cursor(opened_at: datetime, case_id: str) -> str:
    payload = json.dumps(
        {"v": 1, "opened_at": opened_at.isoformat(), "id": case_id},
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode())
        if payload.get("v") != 1 or not isinstance(payload.get("id"), str):
            raise InvalidCursorError("unsupported cursor")
        opened_at = datetime.fromisoformat(payload["opened_at"])
        if opened_at.tzinfo is None:
            raise InvalidCursorError("cursor timestamp must be timezone-aware")
        return opened_at, payload["id"]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise InvalidCursorError("invalid recovery-case cursor") from exc


class CaseRepository:
    """All database access needed by the Phase 1 application service."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_merchant_policy_settings(
        self, *, merchant_id: str
    ) -> tuple[Merchant, MerchantPolicySetting] | None:
        merchant = await self.session.get(Merchant, merchant_id)
        settings = await self.session.get(MerchantPolicySetting, merchant_id)
        if merchant is None or settings is None:
            return None
        return merchant, settings

    async def list_cases(
        self,
        *,
        merchant_id: str,
        filters: CaseFilters,
        cursor: str | None,
        limit: int,
    ) -> CasePage:
        statement: Select[tuple[RecoveryCase]] = select(RecoveryCase).where(
            RecoveryCase.merchant_id == merchant_id
        )
        if filters.outcomes:
            statement = statement.where(RecoveryCase.case_outcome.in_(filters.outcomes))
        if filters.diagnoses:
            statement = statement.where(RecoveryCase.diagnosis.in_(filters.diagnoses))
        if filters.subscription_states:
            statement = statement.where(
                RecoveryCase.subscription_state.in_(filters.subscription_states)
            )
        if filters.opened_from:
            statement = statement.where(RecoveryCase.opened_at >= filters.opened_from)
        if filters.opened_to:
            statement = statement.where(RecoveryCase.opened_at <= filters.opened_to)
        if cursor:
            opened_at, case_id = _decode_cursor(cursor)
            statement = statement.where(
                or_(
                    RecoveryCase.opened_at < opened_at,
                    and_(RecoveryCase.opened_at == opened_at, RecoveryCase.id < case_id),
                )
            )
        statement = statement.order_by(RecoveryCase.opened_at.desc(), RecoveryCase.id.desc()).limit(
            limit + 1
        )
        rows = list((await self.session.scalars(statement)).all())
        has_more = len(rows) > limit
        items = rows[:limit]
        next_cursor = None
        if has_more and items:
            next_cursor = _encode_cursor(items[-1].opened_at, items[-1].id)
        return CasePage(items=items, next_cursor=next_cursor, has_more=has_more)

    async def get_case(self, *, merchant_id: str, case_id: str) -> RecoveryCase | None:
        return cast(
            RecoveryCase | None,
            await self.session.scalar(
                select(RecoveryCase).where(
                    RecoveryCase.id == case_id,
                    RecoveryCase.merchant_id == merchant_id,
                )
            ),
        )

    async def get_case_for_update(self, *, merchant_id: str, case_id: str) -> RecoveryCase | None:
        return cast(
            RecoveryCase | None,
            await self.session.scalar(
                select(RecoveryCase)
                .where(
                    RecoveryCase.id == case_id,
                    RecoveryCase.merchant_id == merchant_id,
                )
                .with_for_update()
            ),
        )

    async def get_customer_for_update(self, *, customer_id: str) -> Customer | None:
        return cast(
            Customer | None,
            await self.session.scalar(
                select(Customer).where(Customer.id == customer_id).with_for_update()
            ),
        )

    async def get_case_aggregate(self, *, merchant_id: str, case_id: str) -> CaseAggregate | None:
        recovery_case = await self.get_case(merchant_id=merchant_id, case_id=case_id)
        if recovery_case is None:
            return None
        customer = await self.session.get(Customer, recovery_case.customer_id)
        subscription = await self.session.get(Subscription, recovery_case.subscription_id)
        invoice = (
            await self.session.get(Invoice, recovery_case.failed_invoice_id)
            if recovery_case.failed_invoice_id
            else None
        )
        payment = (
            await self.session.get(PaymentAttempt, recovery_case.failed_payment_id)
            if recovery_case.failed_payment_id
            else None
        )
        action = await self.session.scalar(
            select(RecoveryActionRecord)
            .where(RecoveryActionRecord.case_id == case_id)
            .order_by(RecoveryActionRecord.created_at.desc(), RecoveryActionRecord.id.desc())
            .limit(1)
        )
        policy = await self.session.scalar(
            select(PolicyDecisionRecord)
            .where(PolicyDecisionRecord.case_id == case_id)
            .order_by(PolicyDecisionRecord.created_at.desc(), PolicyDecisionRecord.id.desc())
            .limit(1)
        )
        if customer is None or subscription is None:
            raise RuntimeError("recovery case has broken customer/subscription references")
        return CaseAggregate(
            recovery_case=recovery_case,
            customer=customer,
            subscription=subscription,
            invoice=invoice,
            failed_payment=payment,
            latest_action=action,
            latest_policy=policy,
        )

    async def timeline(self, *, case_id: str) -> list[RecoveryEventRecord]:
        return list(
            (
                await self.session.scalars(
                    select(RecoveryEventRecord)
                    .where(RecoveryEventRecord.case_id == case_id)
                    .order_by(
                        RecoveryEventRecord.occurred_at.asc(),
                        RecoveryEventRecord.recorded_at.asc(),
                        RecoveryEventRecord.id.asc(),
                    )
                )
            ).all()
        )

    async def add_event(self, event: RecoveryEventRecord) -> bool:
        """Persist an audit event once; duplicates are acknowledged as no-ops."""

        if event.source_event_id:
            existing = await self.session.scalar(
                select(RecoveryEventRecord.id).where(
                    RecoveryEventRecord.case_id == event.case_id,
                    RecoveryEventRecord.source_event_id == event.source_event_id,
                )
            )
            if existing:
                return False
        try:
            async with self.session.begin_nested():
                self.session.add(event)
                await self.session.flush()
        except IntegrityError:
            return False
        return True

    async def add_action_with_policy(
        self,
        action: RecoveryActionRecord,
        policy: PolicyDecisionRecord,
    ) -> None:
        self.session.add(action)
        await self.session.flush()
        policy.action_id = action.id
        self.session.add(policy)
        await self.session.flush()

    async def get_action(
        self, *, case_id: str, action_id: str, for_update: bool = False
    ) -> RecoveryActionRecord | None:
        statement = select(RecoveryActionRecord).where(
            RecoveryActionRecord.id == action_id,
            RecoveryActionRecord.case_id == case_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return cast(RecoveryActionRecord | None, await self.session.scalar(statement))

    async def get_action_by_idempotency_key(
        self, *, idempotency_key: str
    ) -> RecoveryActionRecord | None:
        return cast(
            RecoveryActionRecord | None,
            await self.session.scalar(
                select(RecoveryActionRecord).where(
                    RecoveryActionRecord.idempotency_key == idempotency_key
                )
            ),
        )

    async def get_policy_for_action(self, *, action_id: str) -> PolicyDecisionRecord | None:
        return cast(
            PolicyDecisionRecord | None,
            await self.session.scalar(
                select(PolicyDecisionRecord)
                .where(PolicyDecisionRecord.action_id == action_id)
                .order_by(PolicyDecisionRecord.created_at.desc())
                .limit(1)
            ),
        )

    async def recognize_revenue_once(self, record: RevenueRecognitionRecord) -> bool:
        existing = await self.session.scalar(
            select(RevenueRecognitionRecord.id).where(
                RevenueRecognitionRecord.merchant_id == record.merchant_id,
                RevenueRecognitionRecord.provider == record.provider,
                RevenueRecognitionRecord.provider_event_id == record.provider_event_id,
            )
        )
        if existing:
            return False
        try:
            async with self.session.begin_nested():
                self.session.add(record)
                await self.session.flush()
        except IntegrityError:
            return False
        return True

    async def find_revenue_recognition(
        self, *, merchant_id: str, provider: str, provider_event_id: str
    ) -> RevenueRecognitionRecord | None:
        return cast(
            RevenueRecognitionRecord | None,
            await self.session.scalar(
                select(RevenueRecognitionRecord).where(
                    RevenueRecognitionRecord.merchant_id == merchant_id,
                    RevenueRecognitionRecord.provider == provider,
                    RevenueRecognitionRecord.provider_event_id == provider_event_id,
                )
            ),
        )

    async def add_payment_attempt(self, payment_attempt: PaymentAttempt) -> None:
        self.session.add(payment_attempt)
        await self.session.flush()

    async def add_invoice_collection(self, *, invoice_id: str, amount_paise: int) -> None:
        invoice = await self.session.get(Invoice, invoice_id)
        if invoice is None:
            raise RuntimeError("recovery case has no persisted invoice")
        invoice.amount_paid_paise = min(
            invoice.amount_paise,
            invoice.amount_paid_paise + amount_paise,
        )
        if invoice.amount_paid_paise == invoice.amount_paise:
            invoice.invoice_state = "paid"

    async def dashboard_metrics(self, *, merchant_id: str) -> dict[str, int]:
        active_outcomes = (CaseOutcome.OPEN, CaseOutcome.PARTIALLY_RECOVERED)
        remaining_at_risk = case(
            (
                RecoveryCase.amount_at_risk_paise > RecoveryCase.arrears_collected_paise,
                RecoveryCase.amount_at_risk_paise - RecoveryCase.arrears_collected_paise,
            ),
            else_=0,
        )
        row = (
            await self.session.execute(
                select(
                    func.coalesce(
                        func.sum(remaining_at_risk).filter(
                            RecoveryCase.case_outcome.in_(active_outcomes)
                        ),
                        0,
                    ),
                    func.count(RecoveryCase.id).filter(
                        RecoveryCase.case_outcome.in_(active_outcomes)
                    ),
                    func.count(RecoveryCase.id).filter(
                        RecoveryCase.case_outcome == CaseOutcome.RECOVERED
                    ),
                    func.count(RecoveryCase.id),
                ).where(RecoveryCase.merchant_id == merchant_id)
            )
        ).one()
        at_risk, active, recovered, total = (int(value) for value in row)
        verified = int(
            (
                await self.session.scalar(
                    select(func.coalesce(func.sum(RevenueRecognitionRecord.amount_paise), 0)).where(
                        RevenueRecognitionRecord.merchant_id == merchant_id,
                        RevenueRecognitionRecord.arrears_collected.is_(True),
                        RevenueRecognitionRecord.attribution.in_(
                            (
                                RevenueAttribution.RAZORPAY_TEST_VERIFIED,
                                RevenueAttribution.VERIFIED_EXTERNAL,
                            )
                        ),
                    )
                )
            )
            or 0
        )

        # The current persistence contract has no intervention-cost field. Treating
        # provider prices or estimated labor as costs here would invent money, so
        # recorded intervention cost is exactly zero until a versioned cost ledger
        # exists. The API field therefore equals verified gross after recorded costs.
        recorded_intervention_cost_paise = 0
        return {
            "revenue_at_risk_paise": at_risk,
            "verified_recovered_revenue_paise": verified,
            # Merchant case recovery does not contain a paired baseline or intervention
            # cost. Keep incremental recovery exclusive to RecoveryBench instead of
            # relabelling gross simulated arrears as causal lift.
            "simulated_incremental_recovery_paise": 0,
            "net_recovered_value_paise": verified - recorded_intervention_cost_paise,
            "active_cases": active,
            "recovered_cases": recovered,
            "total_cases": total,
            "recovery_rate_basis_points": (recovered * 10_000 // total) if total else 0,
        }

    async def diagnosis_distribution(self, *, merchant_id: str) -> list[tuple[Diagnosis, int]]:
        rows = (
            await self.session.execute(
                select(RecoveryCase.diagnosis, func.count(RecoveryCase.id))
                .where(RecoveryCase.merchant_id == merchant_id)
                .group_by(RecoveryCase.diagnosis)
                .order_by(RecoveryCase.diagnosis)
            )
        ).all()
        return [(diagnosis, int(count)) for diagnosis, count in rows]

    async def recovery_by_channel(self, *, merchant_id: str) -> list[tuple[str, int, int]]:
        """Return case volume and verified recovered paise by the latest recovery channel.

        A recognition record does not currently own an action ID, so attribution uses the
        case's latest persisted action. This is exact for the normal one-active-action flow and
        avoids manufacturing recovered revenue when no immutable provider recognition exists.
        """

        latest_action_id = (
            select(RecoveryActionRecord.id)
            .where(RecoveryActionRecord.case_id == RecoveryCase.id)
            .order_by(RecoveryActionRecord.created_at.desc(), RecoveryActionRecord.id.desc())
            .limit(1)
            .correlate(RecoveryCase)
            .scalar_subquery()
        )
        rows = (
            await self.session.execute(
                select(
                    RecoveryActionRecord.action_type,
                    RecoveryActionRecord.payment_surface_type,
                    func.count(func.distinct(RecoveryCase.id)),
                    func.coalesce(func.sum(RevenueRecognitionRecord.amount_paise), 0),
                )
                .select_from(RecoveryCase)
                .join(RecoveryActionRecord, RecoveryActionRecord.id == latest_action_id)
                .outerjoin(
                    RevenueRecognitionRecord,
                    and_(
                        RevenueRecognitionRecord.case_id == RecoveryCase.id,
                        RevenueRecognitionRecord.merchant_id == merchant_id,
                        RevenueRecognitionRecord.arrears_collected.is_(True),
                        RevenueRecognitionRecord.attribution.in_(
                            (
                                RevenueAttribution.RAZORPAY_TEST_VERIFIED,
                                RevenueAttribution.VERIFIED_EXTERNAL,
                            )
                        ),
                    ),
                )
                .where(RecoveryCase.merchant_id == merchant_id)
                .group_by(
                    RecoveryActionRecord.action_type,
                    RecoveryActionRecord.payment_surface_type,
                )
            )
        ).all()
        result: list[tuple[str, int, int]] = []
        for action_type, surface_type, case_count, recovered_paise in rows:
            if action_type == RecoveryActionType.START_VOICE:
                channel = "VOICE"
            elif action_type == RecoveryActionType.SEND_TO_CUSTOMER_AGENT:
                channel = "CUSTOMER_AGENT"
            elif (
                action_type == RecoveryActionType.OPEN_CUSTOMER_PAYMENT_SURFACE
                and isinstance(surface_type, PaymentSurfaceType)
            ):
                channel = surface_type.value
            else:
                continue
            result.append((channel, int(case_count), int(recovered_paise)))
        return result

    async def review_and_block_counts(self, *, merchant_id: str) -> tuple[int, int]:
        review_count = await self.session.scalar(
            select(func.count(RecoveryActionRecord.id))
            .join(RecoveryCase, RecoveryCase.id == RecoveryActionRecord.case_id)
            .where(
                RecoveryCase.merchant_id == merchant_id,
                RecoveryActionRecord.status == ActionStatus.AWAITING_APPROVAL,
            )
        )
        blocked_count = await self.session.scalar(
            select(func.count(PolicyDecisionRecord.id))
            .join(RecoveryCase, RecoveryCase.id == PolicyDecisionRecord.case_id)
            .where(
                RecoveryCase.merchant_id == merchant_id,
                PolicyDecisionRecord.disposition == "BLOCK",
            )
        )
        return int(review_count or 0), int(blocked_count or 0)

    async def recent_events(
        self, *, merchant_id: str, limit: int = 20
    ) -> list[RecoveryEventRecord]:
        return list(
            (
                await self.session.scalars(
                    select(RecoveryEventRecord)
                    .join(RecoveryCase, RecoveryCase.id == RecoveryEventRecord.case_id)
                    .where(RecoveryCase.merchant_id == merchant_id)
                    .order_by(RecoveryEventRecord.recorded_at.desc(), RecoveryEventRecord.id.desc())
                    .limit(limit)
                )
            ).all()
        )

    async def cancel_nonterminal_actions(self, *, case_id: str, completed_at: datetime) -> None:
        await self.session.execute(
            update(RecoveryActionRecord)
            .where(
                RecoveryActionRecord.case_id == case_id,
                RecoveryActionRecord.status.in_(
                    (
                        ActionStatus.PROPOSED,
                        ActionStatus.AWAITING_APPROVAL,
                        ActionStatus.SCHEDULED,
                        ActionStatus.EXECUTING,
                    )
                ),
            )
            .values(
                status=ActionStatus.CANCELLED,
                completed_at=completed_at,
                updated_at=completed_at,
            )
        )

    async def commit(self) -> None:
        await self.session.commit()
