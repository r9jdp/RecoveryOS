"""Transactional application service for recovery case operations."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, time

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
from services.api.app.models import (
    PaymentAttempt,
    PolicyDecisionRecord,
    RecoveryActionRecord,
    RecoveryCase,
    RecoveryEventRecord,
    RevenueRecognitionRecord,
)
from services.api.app.providers.contracts import OpenPaymentSurfaceRequest
from services.api.app.providers.interfaces import PaymentProvider
from services.api.app.repositories import CaseFilters, CaseRepository
from services.api.app.repositories.cases import CaseAggregate, CasePage
from services.api.app.safety import (
    SafetyPolicyConfig,
    SafetyPolicyContext,
    evaluate_safety_policy,
)


class ApplicationServiceError(RuntimeError):
    code = "APPLICATION_ERROR"
    status_code = 400

    def __init__(self, message: str, *, metadata: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.metadata = metadata or {}


class CaseNotFoundError(ApplicationServiceError):
    code = "RESOURCE_NOT_FOUND"
    status_code = 404


class CaseConflictError(ApplicationServiceError):
    code = "VERSION_CONFLICT"
    status_code = 409


class PolicyBlockedError(ApplicationServiceError):
    code = "POLICY_BLOCKED"
    status_code = 409


class CaseAlreadyRecoveredError(ApplicationServiceError):
    code = "CASE_ALREADY_RECOVERED"
    status_code = 409


@dataclass(frozen=True, slots=True)
class DashboardSnapshot:
    metrics: dict[str, int]
    diagnosis_distribution: list[tuple[Diagnosis, int]]
    recent_events: list[RecoveryEventRecord]


@dataclass(frozen=True, slots=True)
class PaymentSuccessResult:
    recovery_case: RecoveryCase
    newly_recognized: bool


class RecoveryCaseService:
    """Coordinates repositories and provider ports without workflow concerns."""

    def __init__(
        self,
        repository: CaseRepository,
        payment_provider: PaymentProvider,
        *,
        global_kill_switch: bool = False,
    ) -> None:
        self.repository = repository
        self.payment_provider = payment_provider
        self.global_kill_switch = global_kill_switch

    async def list_cases(
        self,
        *,
        merchant_id: str,
        filters: CaseFilters,
        cursor: str | None,
        limit: int,
    ) -> CasePage:
        return await self.repository.list_cases(
            merchant_id=merchant_id,
            filters=filters,
            cursor=cursor,
            limit=limit,
        )

    async def get_case(self, *, merchant_id: str, case_id: str) -> CaseAggregate:
        aggregate = await self.repository.get_case_aggregate(
            merchant_id=merchant_id, case_id=case_id
        )
        if aggregate is None:
            raise CaseNotFoundError("Recovery case was not found.", metadata={"case_id": case_id})
        return aggregate

    async def dashboard(self, *, merchant_id: str) -> DashboardSnapshot:
        metrics = await self.repository.dashboard_metrics(merchant_id=merchant_id)
        human_review_count, policy_blocked_actions = await self.repository.review_and_block_counts(
            merchant_id=merchant_id
        )
        metrics["human_review_count"] = human_review_count
        metrics["policy_blocked_actions"] = policy_blocked_actions
        return DashboardSnapshot(
            metrics=metrics,
            diagnosis_distribution=await self.repository.diagnosis_distribution(
                merchant_id=merchant_id
            ),
            recent_events=await self.repository.recent_events(merchant_id=merchant_id),
        )

    async def timeline(self, *, merchant_id: str, case_id: str) -> list[RecoveryEventRecord]:
        recovery_case = await self.repository.get_case(merchant_id=merchant_id, case_id=case_id)
        if recovery_case is None:
            raise CaseNotFoundError("Recovery case was not found.", metadata={"case_id": case_id})
        return await self.repository.timeline(case_id=case_id)

    @staticmethod
    def recommended_action(
        diagnosis: Diagnosis, subscription_state: SubscriptionState
    ) -> tuple[RecoveryActionType, PaymentSurfaceType | None]:
        if diagnosis in {Diagnosis.AUTHENTICATION_REQUIRED, Diagnosis.INSTRUMENT_INVALID}:
            return (
                RecoveryActionType.OPEN_CUSTOMER_PAYMENT_SURFACE,
                PaymentSurfaceType.SUBSCRIPTION_CARD_UPDATE,
            )
        if (
            diagnosis == Diagnosis.TRANSIENT_RETRYABLE
            and subscription_state == SubscriptionState.PENDING
        ):
            return RecoveryActionType.WAIT_FOR_GATEWAY_RETRY, None
        if diagnosis == Diagnosis.INSUFFICIENT_FUNDS:
            return (
                RecoveryActionType.OPEN_CUSTOMER_PAYMENT_SURFACE,
                PaymentSurfaceType.SUBSCRIPTION_INVOICE_LINK,
            )
        return RecoveryActionType.ESCALATE_TO_HUMAN, None

    async def recommend_action(
        self,
        *,
        merchant_id: str,
        case_id: str,
        action_type: RecoveryActionType | None = None,
        payment_surface_type: PaymentSurfaceType | None = None,
        now: datetime | None = None,
    ) -> tuple[RecoveryActionRecord, PolicyDecisionRecord]:
        aggregate = await self.get_case(merchant_id=merchant_id, case_id=case_id)
        recovery_case = aggregate.recovery_case
        if action_type is None:
            action_type, inferred_surface = self.recommended_action(
                recovery_case.diagnosis, recovery_case.subscription_state
            )
            payment_surface_type = inferred_surface
        opens_surface = action_type == RecoveryActionType.OPEN_CUSTOMER_PAYMENT_SURFACE
        if opens_surface != (payment_surface_type is not None):
            raise CaseConflictError(
                "Payment surface type must be set only for customer payment surface actions."
            )
        evaluated_at = now or datetime.now(UTC)
        merchant_policy = await self.repository.get_merchant_policy_settings(
            merchant_id=merchant_id
        )
        if merchant_policy is None:
            raise CaseNotFoundError(
                "Merchant policy settings were not found.",
                metadata={"merchant_id": merchant_id},
            )
        merchant, settings = merchant_policy
        policy_config = SafetyPolicyConfig(
            merchant_timezone=merchant.timezone,
            quiet_hours_start=(
                time.fromisoformat(settings.quiet_hours_start)
                if settings.quiet_hours_start
                else None
            ),
            quiet_hours_end=(
                time.fromisoformat(settings.quiet_hours_end) if settings.quiet_hours_end else None
            ),
            max_contacts_per_window=settings.max_contacts_per_7_days,
            manual_approval_actions=frozenset(
                RecoveryActionType(value) for value in settings.require_approval_actions
            ),
            manual_approval_above_paise=settings.require_approval_above_paise,
            global_kill_switch=self.global_kill_switch,
            merchant_kill_switch=settings.recovery_kill_switch,
        )
        decision = evaluate_safety_policy(
            SafetyPolicyContext(
                now=evaluated_at,
                recovery_deadline=recovery_case.recovery_deadline,
                case_outcome=recovery_case.case_outcome,
                payment_state=recovery_case.payment_state,
                subscription_state=recovery_case.subscription_state,
                contact_disposition=recovery_case.contact_disposition,
                action=action_type,
                payment_surface_type=payment_surface_type,
                amount_at_risk_paise=recovery_case.amount_at_risk_paise,
                active_gateway_retries=(
                    recovery_case.subscription_state == SubscriptionState.PENDING
                ),
            ),
            policy_config,
        ).to_contract()
        statuses = {
            PolicyDisposition.ALLOW: ActionStatus.PROPOSED,
            PolicyDisposition.BLOCK: ActionStatus.CANCELLED,
            PolicyDisposition.DELAY: ActionStatus.SCHEDULED,
            PolicyDisposition.REQUIRE_MANUAL_APPROVAL: ActionStatus.AWAITING_APPROVAL,
        }
        idempotency_key = (
            f"case:{case_id}:action:{action_type.value}:surface:"
            f"{payment_surface_type.value if payment_surface_type else 'none'}"
        )
        existing_action = await self.repository.get_action_by_idempotency_key(
            idempotency_key=idempotency_key
        )
        if existing_action is not None:
            existing_policy = await self.repository.get_policy_for_action(
                action_id=existing_action.id
            )
            if existing_policy is None:
                raise RuntimeError("persisted recovery action has no policy decision")
            return existing_action, existing_policy
        action = RecoveryActionRecord(
            case_id=case_id,
            action_type=action_type,
            payment_surface_type=payment_surface_type,
            status=statuses[decision.disposition],
            idempotency_key=idempotency_key,
            scheduled_for=decision.delay_until,
            completed_at=evaluated_at if decision.disposition == PolicyDisposition.BLOCK else None,
        )
        policy = PolicyDecisionRecord(
            case_id=case_id,
            disposition=decision.disposition,
            decision_code=decision.decision_code,
            reason_codes=decision.reason_codes,
            reasons=decision.reasons,
            policy_version=decision.policy_version,
            delay_until=decision.delay_until,
        )
        await self.repository.add_action_with_policy(action, policy)
        await self.repository.add_event(
            RecoveryEventRecord(
                case_id=case_id,
                event_type="ACTION_RECOMMENDED",
                source="decision-engine",
                evidence_kind=EvidenceKind.SIMULATED,
                payload={
                    "action_type": action_type.value,
                    "payment_surface_type": (
                        payment_surface_type.value if payment_surface_type else None
                    ),
                    "policy_disposition": decision.disposition.value,
                    "decision_code": decision.decision_code,
                },
                occurred_at=evaluated_at,
                correlation_id=f"corr_{case_id}",
                source_event_id=f"recommendation:{action.id}",
            )
        )
        await self.repository.commit()
        return action, policy

    async def approve_action(
        self,
        *,
        merchant_id: str,
        case_id: str,
        action_id: str,
        now: datetime | None = None,
    ) -> RecoveryActionRecord:
        aggregate = await self.get_case(merchant_id=merchant_id, case_id=case_id)
        action = await self.repository.get_action(
            case_id=case_id, action_id=action_id, for_update=True
        )
        if action is None:
            raise CaseNotFoundError(
                "Recovery action was not found.", metadata={"action_id": action_id}
            )
        if action.status not in {ActionStatus.PROPOSED, ActionStatus.AWAITING_APPROVAL}:
            raise CaseConflictError(
                "Only a proposed or approval-pending action can be approved.",
                metadata={"action_id": action_id, "status": action.status.value},
            )
        completed_at = now or datetime.now(UTC)
        action_evidence = EvidenceKind.SIMULATED
        provider_name = "none"
        if action.action_type == RecoveryActionType.OPEN_CUSTOMER_PAYMENT_SURFACE:
            if action.payment_surface_type is None or aggregate.invoice is None:
                raise CaseConflictError("The recovery case has no payable failed invoice.")
            reference_id: str | None = None
            expires_at: datetime | None = None
            notes: dict[str, str] = {}
            if action.payment_surface_type == PaymentSurfaceType.STANDARD_PAYMENT_LINK:
                reference_id = (
                    "rec_" + hashlib.sha256(action.idempotency_key.encode()).hexdigest()[:32]
                )
                expires_at = aggregate.recovery_case.recovery_deadline
                notes = {
                    "case_id": case_id,
                    "invoice_id": aggregate.invoice.provider_invoice_id,
                }
            result = await self.payment_provider.open_customer_payment_surface(
                OpenPaymentSurfaceRequest(
                    idempotency_key=action.idempotency_key,
                    case_id=case_id,
                    merchant_id=merchant_id,
                    customer_id=aggregate.customer.id,
                    subscription_id=aggregate.subscription.provider_subscription_id,
                    failed_invoice_id=aggregate.invoice.provider_invoice_id,
                    surface_type=action.payment_surface_type,
                    exact_amount_paise=aggregate.recovery_case.amount_at_risk_paise,
                    currency=aggregate.invoice.currency,
                    recovery_deadline=aggregate.recovery_case.recovery_deadline,
                    expires_at=expires_at,
                    reference_id=reference_id,
                    notes=notes,
                )
            )
            action.external_reference = result.provider_reference
            action.customer_url = result.customer_url
            provider_name = result.provider
            if result.provider == "razorpay":
                action_evidence = EvidenceKind.RAZORPAY_TEST_VERIFIED
        action.status = ActionStatus.SUCCEEDED
        action.completed_at = completed_at
        await self.repository.add_event(
            RecoveryEventRecord(
                case_id=case_id,
                event_type="ACTION_APPROVED",
                source="operator",
                evidence_kind=action_evidence,
                payload={
                    "action_id": action.id,
                    "action_type": action.action_type.value,
                    "provider": provider_name,
                },
                occurred_at=completed_at,
                correlation_id=f"corr_{case_id}",
                source_event_id=f"approval:{action.id}",
            )
        )
        await self.repository.commit()
        return action

    async def reject_action(
        self,
        *,
        merchant_id: str,
        case_id: str,
        action_id: str,
        reason: str,
        now: datetime | None = None,
    ) -> RecoveryActionRecord:
        await self.get_case(merchant_id=merchant_id, case_id=case_id)
        action = await self.repository.get_action(
            case_id=case_id, action_id=action_id, for_update=True
        )
        if action is None:
            raise CaseNotFoundError(
                "Recovery action was not found.", metadata={"action_id": action_id}
            )
        if action.status not in {
            ActionStatus.PROPOSED,
            ActionStatus.AWAITING_APPROVAL,
            ActionStatus.SCHEDULED,
        }:
            raise CaseConflictError("This recovery action can no longer be rejected.")
        rejected_at = now or datetime.now(UTC)
        action.status = ActionStatus.CANCELLED
        action.completed_at = rejected_at
        await self.repository.add_event(
            RecoveryEventRecord(
                case_id=case_id,
                event_type="ACTION_REJECTED",
                source="operator",
                evidence_kind=EvidenceKind.SIMULATED,
                payload={"action_id": action.id, "reason": reason},
                occurred_at=rejected_at,
                correlation_id=f"corr_{case_id}",
                source_event_id=f"rejection:{action.id}",
            )
        )
        await self.repository.commit()
        return action

    async def stop_case(
        self, *, merchant_id: str, case_id: str, reason: str, now: datetime | None = None
    ) -> RecoveryCase:
        recovery_case = await self.repository.get_case_for_update(
            merchant_id=merchant_id, case_id=case_id
        )
        if recovery_case is None:
            raise CaseNotFoundError("Recovery case was not found.", metadata={"case_id": case_id})
        if recovery_case.case_outcome != CaseOutcome.OPEN:
            raise CaseConflictError("The recovery case is already terminal.")
        stopped_at = now or datetime.now(UTC)
        recovery_case.case_outcome = CaseOutcome.STOPPED
        recovery_case.version += 1
        await self.repository.cancel_nonterminal_actions(case_id=case_id, completed_at=stopped_at)
        await self.repository.add_event(
            RecoveryEventRecord(
                case_id=case_id,
                event_type="CASE_STOPPED",
                source="operator",
                evidence_kind=EvidenceKind.SIMULATED,
                payload={"reason": reason},
                occurred_at=stopped_at,
                correlation_id=f"corr_{case_id}",
                source_event_id=f"stop:{case_id}:{recovery_case.version}",
            )
        )
        await self.repository.commit()
        return recovery_case

    async def escalate_case(
        self, *, merchant_id: str, case_id: str, reason: str, now: datetime | None = None
    ) -> RecoveryCase:
        recovery_case = await self.repository.get_case_for_update(
            merchant_id=merchant_id, case_id=case_id
        )
        if recovery_case is None:
            raise CaseNotFoundError("Recovery case was not found.", metadata={"case_id": case_id})
        if recovery_case.case_outcome != CaseOutcome.OPEN:
            raise CaseConflictError("The recovery case is already terminal.")
        escalated_at = now or datetime.now(UTC)
        recovery_case.case_outcome = CaseOutcome.ESCALATED
        recovery_case.version += 1
        action = RecoveryActionRecord(
            case_id=case_id,
            action_type=RecoveryActionType.ESCALATE_TO_HUMAN,
            status=ActionStatus.SUCCEEDED,
            idempotency_key=f"case:{case_id}:escalation:{recovery_case.version}",
            completed_at=escalated_at,
        )
        policy = PolicyDecisionRecord(
            case_id=case_id,
            disposition=PolicyDisposition.ALLOW,
            decision_code="OPERATOR_ESCALATION",
            reason_codes=["OPERATOR_ESCALATION"],
            reasons=[reason],
            policy_version="fitbox-demo.v1",
        )
        await self.repository.add_action_with_policy(action, policy)
        await self.repository.cancel_nonterminal_actions(case_id=case_id, completed_at=escalated_at)
        await self.repository.add_event(
            RecoveryEventRecord(
                case_id=case_id,
                event_type="CASE_ESCALATED",
                source="operator",
                evidence_kind=EvidenceKind.SIMULATED,
                payload={"reason": reason, "action_id": action.id},
                occurred_at=escalated_at,
                correlation_id=f"corr_{case_id}",
                source_event_id=f"escalation:{action.id}",
            )
        )
        await self.repository.commit()
        return recovery_case

    async def record_safety_disposition(
        self,
        *,
        merchant_id: str,
        case_id: str,
        disposition: ContactDisposition,
        now: datetime | None = None,
    ) -> RecoveryCase:
        """Persist a safety-first customer disposition and cancel pending execution."""

        terminal_outcomes = {
            ContactDisposition.DISPUTE: CaseOutcome.DISPUTED,
            ContactDisposition.OPTED_OUT: CaseOutcome.STOPPED,
            ContactDisposition.WRONG_PERSON: CaseOutcome.STOPPED,
            ContactDisposition.ALREADY_PAID: CaseOutcome.ESCALATED,
        }
        if disposition not in terminal_outcomes:
            raise CaseConflictError(
                "This contact disposition is not a safety terminal.",
                metadata={"contact_disposition": disposition.value},
            )
        recovery_case = await self.repository.get_case_for_update(
            merchant_id=merchant_id, case_id=case_id
        )
        if recovery_case is None:
            raise CaseNotFoundError("Recovery case was not found.", metadata={"case_id": case_id})
        target_outcome = terminal_outcomes[disposition]
        if recovery_case.case_outcome != CaseOutcome.OPEN:
            if (
                recovery_case.case_outcome == target_outcome
                and recovery_case.contact_disposition == disposition
            ):
                return recovery_case
            raise CaseConflictError("The recovery case is already terminal.")

        recorded_at = now or datetime.now(UTC)
        recovery_case.contact_disposition = disposition
        recovery_case.case_outcome = target_outcome
        recovery_case.version += 1
        if disposition == ContactDisposition.OPTED_OUT:
            customer = await self.repository.get_customer_for_update(
                customer_id=recovery_case.customer_id
            )
            if customer is None:
                raise RuntimeError("recovery case has a missing customer")
            customer.opted_out_at = recorded_at
        await self.repository.cancel_nonterminal_actions(case_id=case_id, completed_at=recorded_at)
        await self.repository.add_event(
            RecoveryEventRecord(
                case_id=case_id,
                event_type=f"SAFETY_{disposition.value}",
                source="operator",
                evidence_kind=EvidenceKind.SIMULATED,
                payload={
                    "contact_disposition": disposition.value,
                    "case_outcome": target_outcome.value,
                    "provider_action_taken": False,
                },
                occurred_at=recorded_at,
                correlation_id=f"corr_{case_id}",
                source_event_id=f"safety:{case_id}:{disposition.value}",
            )
        )
        await self.repository.commit()
        return recovery_case

    async def apply_mock_payment_success(
        self,
        *,
        merchant_id: str,
        case_id: str,
        provider_event_id: str,
        amount_paise: int | None = None,
        occurred_at: datetime | None = None,
        subscription_reactivated: bool = False,
    ) -> PaymentSuccessResult:
        recovery_case = await self.repository.get_case_for_update(
            merchant_id=merchant_id, case_id=case_id
        )
        if recovery_case is None:
            raise CaseNotFoundError("Recovery case was not found.", metadata={"case_id": case_id})
        recognized_at = occurred_at or datetime.now(UTC)
        existing = await self.repository.find_revenue_recognition(
            merchant_id=merchant_id,
            provider="mock",
            provider_event_id=provider_event_id,
        )
        if existing is not None:
            return PaymentSuccessResult(
                recovery_case=recovery_case,
                newly_recognized=False,
            )
        remaining_paise = recovery_case.amount_at_risk_paise - recovery_case.arrears_collected_paise
        if remaining_paise <= 0:
            raise CaseAlreadyRecoveredError(
                "This recovery case has already collected its arrears.",
                metadata={"case_id": case_id},
            )
        amount = remaining_paise if amount_paise is None else amount_paise
        if amount <= 0 or amount > remaining_paise:
            raise CaseConflictError(
                "Mock success amount must be positive and no greater than remaining arrears."
            )
        if recovery_case.failed_invoice_id is None:
            raise CaseConflictError("Mock success requires a correlated failed invoice.")
        payment_attempt = PaymentAttempt(
            id=f"pay_mock_{hashlib.sha256(provider_event_id.encode()).hexdigest()[:24]}",
            merchant_id=merchant_id,
            invoice_id=recovery_case.failed_invoice_id,
            subscription_id=recovery_case.subscription_id,
            provider_payment_id=(
                f"mock_{hashlib.sha256(provider_event_id.encode()).hexdigest()[:32]}"
            ),
            amount_paise=amount,
            currency="INR",
            payment_state=PaymentState.CAPTURED,
            method="mock",
            occurred_at=recognized_at,
        )
        await self.repository.add_payment_attempt(payment_attempt)
        await self.repository.add_invoice_collection(
            invoice_id=recovery_case.failed_invoice_id,
            amount_paise=amount,
        )
        recognition = RevenueRecognitionRecord(
            case_id=case_id,
            merchant_id=merchant_id,
            payment_attempt_id=payment_attempt.id,
            provider="mock",
            provider_event_id=provider_event_id,
            amount_paise=amount,
            attribution=RevenueAttribution.SIMULATED,
            arrears_collected=True,
            subscription_reactivated=subscription_reactivated,
            recognized_at=recognized_at,
        )
        newly_recognized = await self.repository.recognize_revenue_once(recognition)
        if newly_recognized:
            recovery_case.arrears_collected_paise += amount
            recovery_case.revenue_attribution = RevenueAttribution.SIMULATED
            recovery_case.case_recovered = (
                recovery_case.arrears_collected_paise >= recovery_case.amount_at_risk_paise
            )
            recovery_case.payment_state = PaymentState.CAPTURED
            recovery_case.subscription_reactivated = subscription_reactivated
            recovery_case.case_outcome = (
                CaseOutcome.RECOVERED
                if recovery_case.case_recovered
                else CaseOutcome.PARTIALLY_RECOVERED
            )
            recovery_case.recovered_at = recognized_at
            recovery_case.version += 1
            await self.repository.cancel_nonterminal_actions(
                case_id=case_id, completed_at=recognized_at
            )
            await self.repository.add_event(
                RecoveryEventRecord(
                    case_id=case_id,
                    event_type="PAYMENT_CAPTURED",
                    source="mock-payment-provider",
                    evidence_kind=EvidenceKind.SIMULATED,
                    payload={
                        "amount_paise": amount,
                        "subscription_reactivated": subscription_reactivated,
                    },
                    occurred_at=recognized_at,
                    correlation_id=f"corr_{case_id}",
                    source_event_id=provider_event_id,
                )
            )
        await self.repository.commit()
        return PaymentSuccessResult(recovery_case=recovery_case, newly_recognized=newly_recognized)

    async def apply_late_failure_event(
        self,
        *,
        merchant_id: str,
        case_id: str,
        provider_event_id: str,
        occurred_at: datetime,
    ) -> bool:
        """Audit a late failure without regressing an authoritative captured state."""

        recovery_case = await self.repository.get_case_for_update(
            merchant_id=merchant_id, case_id=case_id
        )
        if recovery_case is None:
            raise CaseNotFoundError("Recovery case was not found.", metadata={"case_id": case_id})
        inserted = await self.repository.add_event(
            RecoveryEventRecord(
                case_id=case_id,
                event_type="PAYMENT_FAILED",
                source="mock-payment-provider",
                evidence_kind=EvidenceKind.SIMULATED,
                payload={"state_regressed": False},
                occurred_at=occurred_at,
                correlation_id=f"corr_{case_id}",
                source_event_id=provider_event_id,
            )
        )
        if inserted and recovery_case.payment_state != PaymentState.CAPTURED:
            recovery_case.payment_state = PaymentState.FAILED
            recovery_case.version += 1
        await self.repository.commit()
        return inserted
