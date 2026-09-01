"""Production activity composition and persistence-backed provider execution."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError

from services.api.app.db import get_session_factory
from services.api.app.domain.enums import (
    ActionStatus,
    CaseOutcome,
    Diagnosis,
    EvidenceKind,
    PaymentState,
    PaymentSurfaceType,
    PolicyDisposition,
    RecoveryActionType,
    RevenueAttribution,
)
from services.api.app.integrations.a2a.mandates import canonical_json
from services.api.app.integrations.a2a.models import SignedMandate
from services.api.app.integrations.razorpay import create_razorpay_client_from_env
from services.api.app.integrations.razorpay.errors import (
    RazorpayIntegrationError,
    RazorpayUncertainSubmissionError,
)
from services.api.app.integrations.razorpay.normalizer import normalize_webhook
from services.api.app.lab.scorer import create_recovery_scorer
from services.api.app.models import (
    A2AMandateNonceConsumption,
    Invoice,
    PaymentAttempt,
    PolicyDecisionRecord,
    RecoveryActionRecord,
    RecoveryCase,
    RecoveryEventRecord,
    RevenueRecognitionRecord,
    Subscription,
    WebhookInboxEntry,
)
from services.api.app.providers.contracts import (
    OpenPaymentSurfaceRequest,
    PaymentSurfaceResult,
    RecoveryScoreRequest,
)
from services.api.app.providers.interfaces import (
    PaymentProvider,
    RecoveryScorer,
    StandardPaymentLinkLifecycleProvider,
)
from services.api.app.services.mock_payment import MockPaymentProvider
from services.api.app.voice.factory import create_voice_service_from_env, voice_provider_ready

from .activities import MockRecoveryActivityServices
from .contracts import (
    ActionExecutionResult,
    AuditInput,
    AuditResult,
    CancelActionInput,
    CancelActionResult,
    DiagnosisInput,
    DiagnosisResult,
    ExecuteActionInput,
    NormalizedFailure,
    NormalizeFailureInput,
    PolicyInput,
    PolicyResult,
    ReconciliationInput,
    ReconciliationResult,
    ScoreInput,
    ScoreResult,
)
from .ports import RecoveryActivityServices


class ActivityConfigurationError(RuntimeError):
    """Raised before worker startup when provider flags are unsafe or incomplete."""


@dataclass(frozen=True, slots=True)
class _PaymentActionClaim:
    action: RecoveryActionRecord
    reconcile_before_submission: bool


@dataclass(frozen=True, slots=True)
class _VoiceActionClaim:
    action: RecoveryActionRecord


def _enabled(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes"}


def _instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("activity timestamp must include a UTC offset")
    return parsed


def create_activity_services_from_env() -> RecoveryActivityServices:
    """Select activity wiring while keeping the safe mock as the default."""

    mode = os.getenv("RECOVERY_ACTIVITY_MODE", "mock").strip().lower()
    if mode == "mock":
        return MockRecoveryActivityServices()
    if mode != "production":
        raise ActivityConfigurationError("RECOVERY_ACTIVITY_MODE must be mock or production")
    if not os.getenv("DATABASE_URL", "").strip():
        raise ActivityConfigurationError("production activities require DATABASE_URL")

    provider_name = os.getenv("PAYMENT_PROVIDER", "mock").strip().lower()
    if provider_name == "mock":
        payment_provider: PaymentProvider = MockPaymentProvider()
    elif provider_name == "razorpay":
        if not _enabled("RECOVERY_ALLOW_REAL_PAYMENT_ACTIONS"):
            raise ActivityConfigurationError(
                "Razorpay activities require RECOVERY_ALLOW_REAL_PAYMENT_ACTIONS=true"
            )
        if not _enabled("RAZORPAY_TEST_MODE_REQUIRED", "true"):
            raise ActivityConfigurationError("Razorpay production-mode keys are not supported")
        payment_provider = create_razorpay_client_from_env()
    else:
        raise ActivityConfigurationError("PAYMENT_PROVIDER must be mock or razorpay")

    return ProductionRecoveryActivityServices(
        payment_provider=payment_provider,
        scorer=create_recovery_scorer(),
    )


class ProductionRecoveryActivityServices:
    """Persistence-backed activity services; every provider call happens here."""

    def __init__(
        self,
        *,
        payment_provider: PaymentProvider,
        scorer: RecoveryScorer,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._payment_provider = payment_provider
        self._scorer = scorer
        self._clock = clock or (lambda: datetime.now(UTC))
        self._fallback = MockRecoveryActivityServices(require_manual_approval=True)
        self._payment_submissions_in_flight: set[str] = set()

    async def normalize_failure(self, command: NormalizeFailureInput) -> NormalizedFailure:
        return await self._fallback.normalize_failure(command)

    async def diagnose_failure(self, command: DiagnosisInput) -> DiagnosisResult:
        return await self._fallback.diagnose_failure(command)

    async def score_recovery(self, command: ScoreInput) -> ScoreResult:
        try:
            result = await self._scorer.score(
                RecoveryScoreRequest(
                    case_id=command.case_id,
                    amount_at_risk_paise=command.amount_at_risk_paise,
                    diagnosis=Diagnosis(command.diagnosis),
                    candidate_action=RecoveryActionType(command.candidate_action),
                    features={},
                )
            )
        except (ValueError, FileNotFoundError):
            return await self._fallback.score_recovery(command)
        return ScoreResult(
            model_name=result.model_name,
            model_version=result.model_version,
            recovery_probability=result.recovery_probability,
            expected_recovered_paise=result.expected_recovered_paise,
            expected_utility_paise=result.expected_utility_paise,
            explanation=tuple(result.explanation),
        )

    async def evaluate_policy(self, command: PolicyInput) -> PolicyResult:
        """Return only the action's durable merchant-policy decision.

        The Temporal history carries a convenient policy result, but the database
        remains the authorization boundary.  Missing or mismatched durable state
        therefore fails closed instead of manufacturing a manual-approval policy.
        """

        try:
            action_type = RecoveryActionType(command.candidate_action)
            surface_type = (
                PaymentSurfaceType(command.payment_surface_type)
                if command.payment_surface_type is not None
                else None
            )
        except ValueError:
            return self._blocked_policy(command, "PERSISTED_ACTION_SCOPE_INVALID")

        # Only OPEN_CUSTOMER_PAYMENT_SURFACE owns a persisted surface subtype.
        # A2A and voice actions may carry the eventual exact surface in the
        # workflow input, but the action-table constraint correctly stores NULL.
        persisted_surface_type = (
            surface_type
            if action_type == RecoveryActionType.OPEN_CUSTOMER_PAYMENT_SURFACE
            else None
        )

        async with get_session_factory()() as session:
            statement = (
                select(RecoveryActionRecord, PolicyDecisionRecord, RecoveryCase)
                .join(RecoveryCase, RecoveryCase.id == RecoveryActionRecord.case_id)
                .join(
                    PolicyDecisionRecord,
                    PolicyDecisionRecord.action_id == RecoveryActionRecord.id,
                )
                .where(
                    RecoveryActionRecord.case_id == command.case_id,
                    RecoveryCase.merchant_id == command.merchant_id,
                    RecoveryActionRecord.action_type == action_type,
                    RecoveryActionRecord.payment_surface_type == persisted_surface_type,
                )
                .order_by(
                    RecoveryActionRecord.created_at.desc(),
                    PolicyDecisionRecord.created_at.desc(),
                )
                .limit(1)
            )
            row = (await session.execute(statement)).first()
            if row is None:
                return self._blocked_policy(command, "PERSISTED_POLICY_NOT_FOUND")
            action, policy, recovery_case = row._tuple()

        if recovery_case.amount_at_risk_paise != command.amount_at_risk_paise:
            return self._blocked_policy(command, "PERSISTED_CASE_SCOPE_MISMATCH")
        delay_until = self._effective_delay(action, policy)
        return PolicyResult(
            disposition=policy.disposition.value,
            decision_code=policy.decision_code,
            action=action.action_type.value,
            payment_surface_type=(
                action.payment_surface_type.value if action.payment_surface_type else None
            ),
            reason_codes=tuple(policy.reason_codes),
            delay_until=delay_until.isoformat() if delay_until is not None else None,
        )

    @staticmethod
    def _blocked_policy(command: PolicyInput, decision_code: str) -> PolicyResult:
        return PolicyResult(
            disposition=PolicyDisposition.BLOCK.value,
            decision_code=decision_code,
            action=command.candidate_action,
            payment_surface_type=command.payment_surface_type,
            reason_codes=(decision_code,),
        )

    @staticmethod
    def _effective_delay(
        action: RecoveryActionRecord, policy: PolicyDecisionRecord
    ) -> datetime | None:
        instants = [instant for instant in (action.scheduled_for, policy.delay_until) if instant]
        return max(instants) if instants else None

    async def execute_recovery_action(self, command: ExecuteActionInput) -> ActionExecutionResult:
        if command.action in {"WAIT_FOR_GATEWAY_RETRY", "STOP", "ESCALATE_TO_HUMAN"}:
            return ActionExecutionResult(status="SUCCEEDED", provider="workflow")
        if command.action == "START_VOICE":
            return await self._execute_voice_action(command)
        if command.action != "OPEN_CUSTOMER_PAYMENT_SURFACE":
            return ActionExecutionResult(
                status="REJECTED",
                provider="none",
                reason_code="ACTIVITY_PROVIDER_NOT_CONFIGURED",
            )
        if command.failed_invoice_id is None or command.payment_surface_type is None:
            return ActionExecutionResult(
                status="REJECTED",
                provider="none",
                reason_code="PAYMENT_SURFACE_SCOPE_MISSING",
            )

        surface_type = PaymentSurfaceType(command.payment_surface_type)
        provider_subscription_id: str | None
        provider_invoice_id: str | None
        if isinstance(self._payment_provider, MockPaymentProvider):
            provider_subscription_id = command.provider_subscription_id or command.subscription_id
            provider_invoice_id = command.provider_invoice_id or command.failed_invoice_id
        else:
            provider_subscription_id = command.provider_subscription_id
            provider_invoice_id = command.provider_invoice_id
            if provider_subscription_id is None or provider_invoice_id is None:
                return ActionExecutionResult(
                    status="REJECTED",
                    provider="none",
                    reason_code="PAYMENT_PROVIDER_SCOPE_MISSING",
                )

        # Validate every provider identifier before atomically consuming an A2A
        # authorization or claiming its durable action. A malformed activity
        # delivery must not burn a valid mandate when no provider call can occur.
        claim = await self._claim_payment_action(command)
        if isinstance(claim, ActionExecutionResult):
            return claim
        action = claim.action
        deadline = _instant(command.recovery_deadline)
        reference_id: str | None = None
        expires_at: datetime | None = None
        notes: dict[str, str] = {}
        if surface_type == PaymentSurfaceType.STANDARD_PAYMENT_LINK:
            reference_id = self._standard_payment_link_reference(action.idempotency_key)
            expires_at = deadline
            notes = {
                "case_id": command.case_id,
                "invoice_id": provider_invoice_id,
                "subscription_id": provider_subscription_id,
            }

        request = OpenPaymentSurfaceRequest(
            idempotency_key=action.idempotency_key,
            case_id=command.case_id,
            merchant_id=command.merchant_id,
            customer_id=command.customer_id,
            subscription_id=provider_subscription_id,
            failed_invoice_id=provider_invoice_id,
            surface_type=surface_type,
            exact_amount_paise=command.amount_paise,
            currency=command.currency,
            recovery_deadline=deadline,
            expires_at=expires_at,
            reference_id=reference_id,
            notes=notes,
        )
        if claim.reconcile_before_submission:
            if surface_type != PaymentSurfaceType.STANDARD_PAYMENT_LINK:
                return ActionExecutionResult(
                    status="UNCERTAIN",
                    provider="unknown",
                    provider_reference=action.external_reference,
                    reason_code="SUBMISSION_RECONCILIATION_REQUIRED",
                )
            return await self._reconcile_or_resume_standard_payment_link(
                action_id=action.id,
                request=request,
            )

        self._payment_submissions_in_flight.add(action.id)
        try:
            result = await self._payment_provider.open_customer_payment_surface(request)
        except RazorpayUncertainSubmissionError as error:
            # Convert the first transport-uncertain create into a durable result
            # in this activity invocation.  The only permitted next write is
            # behind the provider's authoritative reference lookup.
            if (
                surface_type != PaymentSurfaceType.STANDARD_PAYMENT_LINK
                or request.reference_id is None
                or error.metadata.get("reference_id") != request.reference_id
            ):
                return ActionExecutionResult(
                    status="UNCERTAIN",
                    provider="razorpay",
                    reason_code="SUBMISSION_REFERENCE_MISMATCH",
                )
            return await self._reconcile_or_resume_standard_payment_link(
                action_id=action.id,
                request=request,
            )
        except Exception:
            # Submission may be uncertain. The EXECUTING claim deliberately
            # prevents an automatic second provider call on activity replay.
            raise
        finally:
            self._payment_submissions_in_flight.discard(action.id)
        return await self._persist_payment_surface(action.id, result)

    async def _execute_voice_action(self, command: ExecuteActionInput) -> ActionExecutionResult:
        """Execute only a durable, explicitly operator-approved voice action."""

        claim = await self._claim_voice_action(
            command,
            provider_ready=voice_provider_ready(),
        )
        if isinstance(claim, ActionExecutionResult):
            return claim

        async with get_session_factory()() as session:
            resources = create_voice_service_from_env(session)
            try:
                result = await resources.service.start(
                    case_id=command.case_id,
                    idempotency_key=command.idempotency_key,
                    supplied_operator_token=os.getenv("VOICE_OPERATOR_TOKEN", ""),
                    max_duration_seconds=180,
                    now=self._clock(),
                )
                await session.commit()
            finally:
                await resources.aclose()

        provider_reference = result.provider_call_id or result.contact_attempt_id
        if result.status == "SUBMITTED":
            await self._finalize_voice_action(
                action_id=claim.action.id,
                status=ActionStatus.SUCCEEDED,
                provider_reference=provider_reference,
            )
            return ActionExecutionResult(
                status="SUCCEEDED",
                provider=result.provider,
                provider_reference=provider_reference,
                reason_code=result.reason_code,
            )
        if result.status == "REJECTED":
            await self._finalize_voice_action(
                action_id=claim.action.id,
                status=ActionStatus.CANCELLED,
                provider_reference=None,
            )
            return ActionExecutionResult(
                status="REJECTED",
                provider=result.provider,
                reason_code=result.reason_code,
            )
        return ActionExecutionResult(
            status="UNCERTAIN",
            provider=result.provider,
            provider_reference=provider_reference,
            reason_code=result.reason_code or "VOICE_SUBMISSION_RECONCILIATION_REQUIRED",
        )

    async def _claim_voice_action(
        self,
        command: ExecuteActionInput,
        *,
        provider_ready: bool,
    ) -> _VoiceActionClaim | ActionExecutionResult:
        """Claim a voice action only after a persisted manual approval event."""

        async with get_session_factory()() as session:
            statement = (
                select(RecoveryActionRecord, PolicyDecisionRecord, RecoveryCase)
                .join(RecoveryCase, RecoveryCase.id == RecoveryActionRecord.case_id)
                .join(
                    PolicyDecisionRecord,
                    PolicyDecisionRecord.action_id == RecoveryActionRecord.id,
                )
                .where(
                    RecoveryActionRecord.case_id == command.case_id,
                    RecoveryCase.merchant_id == command.merchant_id,
                    RecoveryCase.customer_id == command.customer_id,
                    RecoveryCase.subscription_id == command.subscription_id,
                    RecoveryCase.amount_at_risk_paise == command.amount_paise,
                    RecoveryActionRecord.action_type == RecoveryActionType.START_VOICE,
                )
                .order_by(RecoveryActionRecord.created_at.desc())
                .limit(1)
                .with_for_update()
            )
            row = (await session.execute(statement)).first()
            if row is None:
                return ActionExecutionResult(
                    status="REJECTED",
                    provider="none",
                    reason_code="VOICE_PERSISTED_POLICY_NOT_FOUND",
                )
            action, policy, _ = row._tuple()
            if policy.disposition != PolicyDisposition.REQUIRE_MANUAL_APPROVAL:
                return ActionExecutionResult(
                    status="REJECTED",
                    provider="none",
                    reason_code="VOICE_MANUAL_APPROVAL_POLICY_REQUIRED",
                )
            approval_events = (
                await session.scalars(
                    select(RecoveryEventRecord)
                    .where(
                        RecoveryEventRecord.case_id == command.case_id,
                        RecoveryEventRecord.event_type == "ACTION_APPROVED",
                        RecoveryEventRecord.source == "operator",
                    )
                    .order_by(RecoveryEventRecord.occurred_at.desc())
                )
            ).all()
            approved = any(
                isinstance(event.payload, dict)
                and event.payload.get("action_id") == action.id
                and event.payload.get("action_type") == RecoveryActionType.START_VOICE.value
                for event in approval_events
            )
            if not approved:
                return ActionExecutionResult(
                    status="REJECTED",
                    provider="none",
                    reason_code="VOICE_OPERATOR_APPROVAL_NOT_PERSISTED",
                )
            if action.status == ActionStatus.SUCCEEDED:
                return ActionExecutionResult(
                    status="SUCCEEDED",
                    provider="persisted",
                    provider_reference=action.external_reference,
                    reason_code="ALREADY_EXECUTED",
                )
            if action.status == ActionStatus.CANCELLED:
                return ActionExecutionResult(
                    status="REJECTED",
                    provider="none",
                    reason_code="ACTION_CANCELLED",
                )
            if action.status == ActionStatus.EXECUTING:
                if not provider_ready:
                    return ActionExecutionResult(
                        status="UNCERTAIN",
                        provider="unknown",
                        provider_reference=action.external_reference,
                        reason_code="VOICE_SUBMISSION_RECONCILIATION_REQUIRED",
                    )
                return _VoiceActionClaim(action=action)
            if action.status != ActionStatus.SCHEDULED:
                return ActionExecutionResult(
                    status="REJECTED",
                    provider="none",
                    reason_code="VOICE_ACTION_NOT_MANUALLY_APPROVED",
                )
            if not provider_ready:
                return ActionExecutionResult(
                    status="REJECTED",
                    provider="none",
                    reason_code="VOICE_PROVIDER_NOT_READY",
                )
            action.status = ActionStatus.EXECUTING
            action.updated_at = self._clock()
            await session.commit()
            return _VoiceActionClaim(action=action)

    async def _finalize_voice_action(
        self,
        *,
        action_id: str,
        status: ActionStatus,
        provider_reference: str | None,
    ) -> None:
        async with get_session_factory()() as session:
            action = await session.get(RecoveryActionRecord, action_id, with_for_update=True)
            if action is None:
                return
            if action.status == ActionStatus.SUCCEEDED:
                return
            action.status = status
            action.external_reference = provider_reference
            action.completed_at = self._clock() if status != ActionStatus.EXECUTING else None
            await session.commit()

    @staticmethod
    def _standard_payment_link_reference(idempotency_key: str) -> str:
        return "rec_" + hashlib.sha256(idempotency_key.encode()).hexdigest()[:32]

    async def _persist_payment_surface(
        self, action_id: str, result: PaymentSurfaceResult
    ) -> ActionExecutionResult:
        async with get_session_factory()() as session:
            persisted = await session.get(RecoveryActionRecord, action_id, with_for_update=True)
            if persisted is None:
                return ActionExecutionResult(
                    status="UNCERTAIN",
                    provider=result.provider,
                    provider_reference=result.provider_reference,
                    reason_code="ACTION_RECORD_MISSING_AFTER_SUBMISSION",
                )
            if persisted.status == ActionStatus.CANCELLED:
                return ActionExecutionResult(
                    status="REJECTED",
                    provider=result.provider,
                    provider_reference=result.provider_reference,
                    reason_code="ACTION_CANCELLED_AFTER_SUBMISSION",
                )
            if persisted.status == ActionStatus.SUCCEEDED:
                return ActionExecutionResult(
                    status="SUCCEEDED",
                    provider="persisted",
                    provider_reference=persisted.external_reference,
                    customer_url=persisted.customer_url,
                    reason_code="ALREADY_EXECUTED",
                )
            persisted.status = ActionStatus.SUCCEEDED
            persisted.external_reference = result.provider_reference
            persisted.customer_url = result.customer_url
            persisted.completed_at = datetime.now(UTC)
            authorization = await session.scalar(
                select(A2AMandateNonceConsumption)
                .where(A2AMandateNonceConsumption.recovery_action_id == action_id)
                .with_for_update()
            )
            if authorization is not None:
                authorization.execution_status = "SUCCEEDED"
                authorization.executed_at = persisted.completed_at
            await session.commit()
        return ActionExecutionResult(
            status="SUCCEEDED",
            provider=result.provider,
            provider_reference=result.provider_reference,
            customer_url=result.customer_url,
        )

    async def _reconcile_or_resume_standard_payment_link(
        self,
        *,
        action_id: str,
        request: OpenPaymentSurfaceRequest,
    ) -> ActionExecutionResult:
        if not isinstance(self._payment_provider, StandardPaymentLinkLifecycleProvider):
            return ActionExecutionResult(
                status="UNCERTAIN",
                provider="unknown",
                reason_code="PAYMENT_LINK_RECONCILIATION_UNSUPPORTED",
            )

        # The row lock serializes competing activity deliveries around the
        # provider lookup and any confirmed-absent resubmission.  No second
        # create can begin while another reconciler is deciding this action.
        async with get_session_factory()() as session:
            persisted = await session.get(RecoveryActionRecord, action_id, with_for_update=True)
            if persisted is None:
                return ActionExecutionResult(
                    status="UNCERTAIN",
                    provider="unknown",
                    reason_code="ACTION_RECORD_MISSING_DURING_RECONCILIATION",
                )
            if persisted.status == ActionStatus.SUCCEEDED:
                return ActionExecutionResult(
                    status="SUCCEEDED",
                    provider="persisted",
                    provider_reference=persisted.external_reference,
                    customer_url=persisted.customer_url,
                    reason_code="ALREADY_EXECUTED",
                )
            if persisted.status == ActionStatus.CANCELLED:
                return ActionExecutionResult(
                    status="REJECTED",
                    provider="none",
                    reason_code="ACTION_CANCELLED",
                )
            if persisted.status != ActionStatus.EXECUTING:
                return ActionExecutionResult(
                    status="UNCERTAIN",
                    provider="unknown",
                    reason_code="ACTION_STATE_CHANGED_DURING_RECONCILIATION",
                )
            assert request.reference_id is not None
            try:
                reconciled = await self._payment_provider.reconcile_payment_link_by_reference(
                    reference_id=request.reference_id
                )
            except Exception:
                return ActionExecutionResult(
                    status="UNCERTAIN",
                    provider="razorpay",
                    reason_code="PAYMENT_LINK_RECONCILIATION_UNRESOLVED",
                )

            if reconciled is None:
                try:
                    reconciled = await self._payment_provider.open_customer_payment_surface(request)
                except Exception:
                    return ActionExecutionResult(
                        status="UNCERTAIN",
                        provider="razorpay",
                        reason_code="CONFIRMED_ABSENT_RESUBMISSION_UNCERTAIN",
                    )
                reason_code = "CONFIRMED_ABSENT_RESUBMITTED"
            else:
                reason_code = "SUBMISSION_RECONCILED"

            persisted.status = ActionStatus.SUCCEEDED
            persisted.external_reference = reconciled.provider_reference
            persisted.customer_url = reconciled.customer_url
            persisted.completed_at = self._clock()
            authorization = await session.scalar(
                select(A2AMandateNonceConsumption)
                .where(A2AMandateNonceConsumption.recovery_action_id == action_id)
                .with_for_update()
            )
            if authorization is not None:
                authorization.execution_status = "SUCCEEDED"
                authorization.executed_at = persisted.completed_at
            await session.commit()
            return ActionExecutionResult(
                status="SUCCEEDED",
                provider=reconciled.provider,
                provider_reference=reconciled.provider_reference,
                customer_url=reconciled.customer_url,
                reason_code=reason_code,
            )

    async def _claim_payment_action(
        self, command: ExecuteActionInput
    ) -> _PaymentActionClaim | ActionExecutionResult:
        if command.payment_surface_type is None:
            return ActionExecutionResult(
                status="REJECTED",
                provider="none",
                reason_code="PAYMENT_SURFACE_SCOPE_MISSING",
            )
        surface_type = PaymentSurfaceType(command.payment_surface_type)
        if command.mandate is not None:
            return await self._claim_a2a_payment_action(command, surface_type=surface_type)
        async with get_session_factory()() as session:
            statement = (
                select(RecoveryActionRecord, PolicyDecisionRecord)
                .join(RecoveryCase, RecoveryCase.id == RecoveryActionRecord.case_id)
                .join(
                    PolicyDecisionRecord,
                    PolicyDecisionRecord.action_id == RecoveryActionRecord.id,
                )
                .where(
                    RecoveryActionRecord.case_id == command.case_id,
                    RecoveryCase.merchant_id == command.merchant_id,
                    RecoveryActionRecord.action_type
                    == RecoveryActionType.OPEN_CUSTOMER_PAYMENT_SURFACE,
                    RecoveryActionRecord.payment_surface_type == surface_type,
                )
                .order_by(RecoveryActionRecord.created_at.desc())
                .with_for_update()
            )
            row = (await session.execute(statement)).first()
            if row is None:
                return ActionExecutionResult(
                    status="REJECTED",
                    provider="none",
                    reason_code="PERSISTED_POLICY_NOT_FOUND",
                )
            action, policy = row._tuple()
            if action.status == ActionStatus.SUCCEEDED:
                return ActionExecutionResult(
                    status="SUCCEEDED",
                    provider="persisted",
                    provider_reference=action.external_reference,
                    customer_url=action.customer_url,
                    reason_code="ALREADY_EXECUTED",
                )
            if action.status == ActionStatus.EXECUTING:
                if action.id in self._payment_submissions_in_flight:
                    return ActionExecutionResult(
                        status="UNCERTAIN",
                        provider="unknown",
                        provider_reference=action.external_reference,
                        reason_code="SUBMISSION_RECONCILIATION_REQUIRED",
                    )
                if surface_type == PaymentSurfaceType.STANDARD_PAYMENT_LINK:
                    return _PaymentActionClaim(
                        action=action,
                        reconcile_before_submission=True,
                    )
                return ActionExecutionResult(
                    status="UNCERTAIN",
                    provider="unknown",
                    provider_reference=action.external_reference,
                    reason_code="SUBMISSION_RECONCILIATION_REQUIRED",
                )
            if policy.disposition == PolicyDisposition.BLOCK:
                return ActionExecutionResult(
                    status="REJECTED",
                    provider="none",
                    reason_code="POLICY_BLOCKED",
                )
            if action.status == ActionStatus.CANCELLED:
                return ActionExecutionResult(
                    status="REJECTED",
                    provider="none",
                    reason_code="ACTION_CANCELLED",
                )

            claimable_statuses = {
                PolicyDisposition.ALLOW: {ActionStatus.PROPOSED, ActionStatus.SCHEDULED},
                PolicyDisposition.DELAY: {ActionStatus.SCHEDULED},
                PolicyDisposition.REQUIRE_MANUAL_APPROVAL: {ActionStatus.SCHEDULED},
            }.get(policy.disposition, set())
            if action.status not in claimable_statuses:
                return ActionExecutionResult(
                    status="REJECTED",
                    provider="none",
                    reason_code="ACTION_NOT_AUTHORIZED",
                )

            claimed_at = self._clock()
            if claimed_at.tzinfo is None or claimed_at.utcoffset() is None:
                raise ValueError("activity clock must return an offset-aware instant")
            due_at = self._effective_delay(action, policy)
            if due_at is not None and claimed_at < due_at:
                return ActionExecutionResult(
                    status="REJECTED",
                    provider="none",
                    reason_code="ACTION_NOT_DUE",
                )

            original_status = action.status
            claimed_action_id = await session.scalar(
                update(RecoveryActionRecord)
                .where(
                    RecoveryActionRecord.id == action.id,
                    RecoveryActionRecord.status == original_status,
                    or_(
                        RecoveryActionRecord.scheduled_for.is_(None),
                        RecoveryActionRecord.scheduled_for <= claimed_at,
                    ),
                )
                .values(status=ActionStatus.EXECUTING, updated_at=claimed_at)
                .returning(RecoveryActionRecord.id)
                .execution_options(synchronize_session=False)
            )
            if claimed_action_id != action.id:
                await session.rollback()
                current = await session.get(RecoveryActionRecord, action.id)
                if current is not None and current.status == ActionStatus.SUCCEEDED:
                    return ActionExecutionResult(
                        status="SUCCEEDED",
                        provider="persisted",
                        provider_reference=current.external_reference,
                        customer_url=current.customer_url,
                        reason_code="ALREADY_EXECUTED",
                    )
                if (
                    current is not None
                    and current.status == ActionStatus.EXECUTING
                    and current.id not in self._payment_submissions_in_flight
                    and surface_type == PaymentSurfaceType.STANDARD_PAYMENT_LINK
                ):
                    return _PaymentActionClaim(
                        action=current,
                        reconcile_before_submission=True,
                    )
                return ActionExecutionResult(
                    status="UNCERTAIN",
                    provider="unknown",
                    provider_reference=current.external_reference if current else None,
                    reason_code="SUBMISSION_RECONCILIATION_REQUIRED",
                )
            await session.commit()
            action.status = ActionStatus.EXECUTING
            return _PaymentActionClaim(
                action=action,
                reconcile_before_submission=False,
            )

    async def _claim_a2a_payment_action(
        self,
        command: ExecuteActionInput,
        *,
        surface_type: PaymentSurfaceType,
    ) -> _PaymentActionClaim | ActionExecutionResult:
        """Claim the exact SEND action backed by a persisted verified v2 mandate."""

        if command.recovery_action_id is None or command.failed_invoice_id is None:
            return ActionExecutionResult(
                status="REJECTED",
                provider="none",
                reason_code="A2A_DURABLE_SCOPE_MISSING",
            )
        try:
            signed = SignedMandate.model_validate(command.mandate)
        except ValidationError:
            return ActionExecutionResult(
                status="REJECTED",
                provider="none",
                reason_code="A2A_MANDATE_MALFORMED",
            )

        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("activity clock must return an offset-aware instant")
        data = signed.data
        command_scope = (
            command.recovery_action_id,
            command.failed_invoice_id,
            command.case_id,
            command.merchant_id,
            command.customer_id,
            command.amount_paise,
            command.currency,
            surface_type.value,
            command.provider_invoice_id or command.failed_invoice_id,
        )
        signed_scope = (
            data.recovery_action_id,
            data.failed_invoice_id,
            data.case_id,
            data.merchant_id,
            data.customer_id,
            data.exact_amount_paise,
            data.currency,
            data.payment_surface_type,
            data.payment_surface_reference,
        )
        if signed_scope != command_scope:
            return ActionExecutionResult(
                status="REJECTED",
                provider="none",
                reason_code="A2A_MANDATE_COMMAND_SCOPE_MISMATCH",
            )

        async with get_session_factory()() as session:
            statement = (
                select(
                    RecoveryActionRecord,
                    PolicyDecisionRecord,
                    RecoveryCase,
                    Invoice,
                    A2AMandateNonceConsumption,
                )
                .join(RecoveryCase, RecoveryCase.id == RecoveryActionRecord.case_id)
                .join(
                    PolicyDecisionRecord,
                    PolicyDecisionRecord.action_id == RecoveryActionRecord.id,
                )
                .join(Invoice, Invoice.id == RecoveryCase.failed_invoice_id)
                .join(
                    A2AMandateNonceConsumption,
                    A2AMandateNonceConsumption.recovery_action_id == RecoveryActionRecord.id,
                )
                .where(
                    RecoveryActionRecord.id == command.recovery_action_id,
                    RecoveryActionRecord.case_id == command.case_id,
                    PolicyDecisionRecord.case_id == command.case_id,
                    A2AMandateNonceConsumption.mandate_id == data.mandate_id,
                    A2AMandateNonceConsumption.claim_id
                    == hashlib.sha256(canonical_json(data)).hexdigest(),
                )
                .with_for_update()
            )
            row = (await session.execute(statement)).first()
            if row is None:
                return ActionExecutionResult(
                    status="REJECTED",
                    provider="none",
                    reason_code="A2A_VERIFIED_AUTHORIZATION_NOT_FOUND",
                )
            action, policy, recovery_case, invoice, authorization = row._tuple()

            persisted_scope = (
                authorization.recovery_action_id,
                authorization.failed_invoice_id,
                authorization.case_id,
                authorization.merchant_id,
                authorization.customer_id,
                authorization.exact_amount_paise,
                authorization.currency,
                authorization.payment_surface_type,
                authorization.payment_surface_reference,
            )
            current_scope = (
                action.id,
                invoice.id,
                recovery_case.id,
                recovery_case.merchant_id,
                recovery_case.customer_id,
                recovery_case.amount_at_risk_paise,
                invoice.currency,
                surface_type.value,
                invoice.provider_invoice_id,
            )
            outstanding_paise = invoice.amount_paise - invoice.amount_paid_paise
            unsafe = (
                persisted_scope != signed_scope
                or current_scope != signed_scope
                or authorization.task_id != data.task_id
                or authorization.signer_key_id != data.signer_key_id
                or authorization.authorized_action != "OPEN_EXACT_PAYMENT_SURFACE"
                or authorization.issued_at != data.issued_at
                or authorization.expires_at != data.expires_at
                or data.expires_at <= now
                or data.expires_at > recovery_case.recovery_deadline
                or _instant(command.recovery_deadline) != recovery_case.recovery_deadline
                or outstanding_paise != data.exact_amount_paise
                or recovery_case.case_outcome != CaseOutcome.OPEN
                or recovery_case.payment_state == PaymentState.CAPTURED
                or recovery_case.case_recovered
                or action.action_type != RecoveryActionType.SEND_TO_CUSTOMER_AGENT
                or policy.disposition
                not in {PolicyDisposition.ALLOW, PolicyDisposition.DELAY}
            )
            if unsafe:
                return ActionExecutionResult(
                    status="REJECTED",
                    provider="none",
                    reason_code="A2A_AUTHORIZATION_STALE_OR_MISMATCHED",
                )

            if action.status == ActionStatus.SUCCEEDED:
                return ActionExecutionResult(
                    status="SUCCEEDED",
                    provider="persisted",
                    provider_reference=action.external_reference,
                    customer_url=action.customer_url,
                    reason_code="ALREADY_EXECUTED",
                )
            if action.status == ActionStatus.CANCELLED:
                return ActionExecutionResult(
                    status="REJECTED",
                    provider="none",
                    reason_code="ACTION_CANCELLED",
                )
            if authorization.execution_status in {"EXECUTING", "UNCERTAIN"}:
                if surface_type == PaymentSurfaceType.STANDARD_PAYMENT_LINK:
                    return _PaymentActionClaim(action=action, reconcile_before_submission=True)
                return ActionExecutionResult(
                    status="UNCERTAIN",
                    provider="unknown",
                    provider_reference=action.external_reference,
                    reason_code="SUBMISSION_RECONCILIATION_REQUIRED",
                )
            if authorization.execution_status == "SUCCEEDED":
                return ActionExecutionResult(
                    status="SUCCEEDED",
                    provider="persisted",
                    provider_reference=action.external_reference,
                    customer_url=action.customer_url,
                    reason_code="ALREADY_EXECUTED",
                )
            if authorization.execution_status != "AUTHORIZED":
                return ActionExecutionResult(
                    status="REJECTED",
                    provider="none",
                    reason_code="A2A_AUTHORIZATION_NOT_EXECUTABLE",
                )
            if action.status not in {ActionStatus.PROPOSED, ActionStatus.SCHEDULED}:
                return ActionExecutionResult(
                    status="REJECTED",
                    provider="none",
                    reason_code="ACTION_NOT_AUTHORIZED",
                )
            due_at = self._effective_delay(action, policy)
            if due_at is not None and now < due_at:
                return ActionExecutionResult(
                    status="REJECTED",
                    provider="none",
                    reason_code="ACTION_NOT_DUE",
                )

            action.status = ActionStatus.EXECUTING
            action.updated_at = now
            authorization.execution_status = "EXECUTING"
            authorization.execution_claimed_at = now
            await session.commit()
            return _PaymentActionClaim(action=action, reconcile_before_submission=False)

    async def reconcile_case(self, command: ReconciliationInput) -> ReconciliationResult:
        if isinstance(self._payment_provider, MockPaymentProvider):
            return await self._fallback.reconcile_case(command)
        if command.failed_invoice_id is None:
            return self._unreconciled_case()

        provider_payment_id: str | None = None
        provider_invoice_id: str | None = None
        expected_subscription_id: str | None = None
        expected_currency: str | None = None
        required_arrears_paise = 0
        existing_arrears_paise = 0
        async with get_session_factory()() as session:
            recovery_case = await session.scalar(
                select(RecoveryCase).where(
                    RecoveryCase.id == command.case_id,
                    RecoveryCase.merchant_id == command.merchant_id,
                    RecoveryCase.failed_invoice_id == command.failed_invoice_id,
                )
            )
            if recovery_case is None:
                return self._unreconciled_case()
            invoice = await session.scalar(
                select(Invoice).where(
                    Invoice.id == command.failed_invoice_id,
                    Invoice.merchant_id == command.merchant_id,
                    Invoice.subscription_id == recovery_case.subscription_id,
                )
            )
            subscription = await session.scalar(
                select(Subscription).where(
                    Subscription.id == recovery_case.subscription_id,
                    Subscription.merchant_id == command.merchant_id,
                )
            )
            if invoice is None or subscription is None:
                return self._unreconciled_case()

            # The webhook processor persists the accounting recognition before it
            # signals Temporal.  Prefer that exact, invoice-scoped evidence.  A
            # duplicate/late event may have a different event id after the same
            # payment was already recognized, so a terminal case may use its
            # existing Razorpay recognition as the convergence source.
            recognition_filter = [
                RevenueRecognitionRecord.case_id == recovery_case.id,
                RevenueRecognitionRecord.merchant_id == command.merchant_id,
                RevenueRecognitionRecord.provider == "razorpay",
                RevenueRecognitionRecord.attribution == RevenueAttribution.RAZORPAY_TEST_VERIFIED,
                RevenueRecognitionRecord.arrears_collected.is_(True),
                PaymentAttempt.invoice_id == invoice.id,
                PaymentAttempt.payment_state == PaymentState.CAPTURED,
            ]
            if not recovery_case.case_recovered:
                recognition_filter.append(
                    RevenueRecognitionRecord.provider_event_id == command.trigger_event_id
                )
            recognized = (
                await session.execute(
                    select(RevenueRecognitionRecord, PaymentAttempt)
                    .join(
                        PaymentAttempt,
                        PaymentAttempt.id == RevenueRecognitionRecord.payment_attempt_id,
                    )
                    .where(*recognition_filter)
                    .order_by(RevenueRecognitionRecord.recognized_at.desc())
                    .limit(1)
                )
            ).first()
            if recognized is not None:
                _, recognized_payment = recognized
                return ReconciliationResult(
                    payment_state=recovery_case.payment_state.value,
                    subscription_state=recovery_case.subscription_state.value,
                    authoritative=True,
                    case_recovered=recovery_case.case_recovered,
                    arrears_collected_paise=recovery_case.arrears_collected_paise,
                    subscription_reactivated=recovery_case.subscription_reactivated,
                    provider_reference=(
                        recognized_payment.provider_payment_id or command.trigger_event_id
                    ),
                )

            inbox = await session.scalar(
                select(WebhookInboxEntry).where(
                    WebhookInboxEntry.merchant_id == command.merchant_id,
                    WebhookInboxEntry.provider == "razorpay",
                    WebhookInboxEntry.provider_event_id == command.trigger_event_id,
                )
            )
            if inbox is not None:
                try:
                    event = normalize_webhook(
                        provider_event_id=inbox.provider_event_id,
                        payload=inbox.payload,
                    )
                except RazorpayIntegrationError:
                    return self._unreconciled_case()
                invoice_matches = event.invoice_id == invoice.provider_invoice_id
                subscription_matches = event.subscription_id in {
                    None,
                    subscription.provider_subscription_id,
                }
                if event.event_type == "payment_link.paid":
                    # Replacement Payment Links are arrears collection only and
                    # must carry both exact case and invoice notes.  They do not
                    # imply that the subscription mandate became active again.
                    scope_matches = (
                        event.case_id == recovery_case.id
                        and invoice_matches
                        and subscription_matches
                    )
                else:
                    # Native invoice payments and card-update/gateway retries are
                    # tied to the failed invoice; a case note is optional.
                    scope_matches = (
                        event.payment_state == PaymentState.CAPTURED
                        and invoice_matches
                        and subscription_matches
                        and event.case_id in {None, recovery_case.id}
                    )
                if (
                    not scope_matches
                    or event.payment_state != PaymentState.CAPTURED
                    or event.payment_id is None
                ):
                    return self._unreconciled_case()
                provider_payment_id = event.payment_id
            elif command.authoritative_hint:
                # An asserted success without a durable signed webhook is never
                # payment truth (in particular, browser callbacks are ignored).
                return self._unreconciled_case()

            provider_invoice_id = invoice.provider_invoice_id
            expected_subscription_id = subscription.provider_subscription_id
            expected_currency = invoice.currency
            existing_arrears_paise = recovery_case.arrears_collected_paise
            required_arrears_paise = max(
                recovery_case.amount_at_risk_paise - existing_arrears_paise,
                0,
            )

        if (
            provider_invoice_id is None
            or expected_subscription_id is None
            or expected_currency is None
        ):
            return self._unreconciled_case()
        snapshot = await self._payment_provider.fetch_payment_snapshot(
            merchant_id=command.merchant_id,
            # For a webhook signal this is the newly captured payment, not the
            # original failed attempt.  For an already-paid reconciliation it is
            # deliberately None so Razorpay's current invoice payment wins.
            payment_id=provider_payment_id,
            invoice_id=provider_invoice_id,
        )
        recovered = (
            snapshot.authoritative
            and snapshot.payment_state == PaymentState.CAPTURED
            and snapshot.invoice_id == provider_invoice_id
            and snapshot.subscription_id == expected_subscription_id
            and snapshot.currency == expected_currency
            and snapshot.amount_paise == required_arrears_paise
            and required_arrears_paise > 0
            and (provider_payment_id is None or snapshot.payment_id == provider_payment_id)
        )
        return ReconciliationResult(
            payment_state=snapshot.payment_state.value,
            subscription_state=snapshot.subscription_state.value,
            authoritative=snapshot.authoritative,
            case_recovered=recovered,
            arrears_collected_paise=(
                existing_arrears_paise + snapshot.amount_paise if recovered else 0
            ),
            subscription_reactivated=recovered and snapshot.subscription_state.value == "ACTIVE",
            provider_reference=snapshot.payment_id or snapshot.invoice_id,
        )

    @staticmethod
    def _unreconciled_case() -> ReconciliationResult:
        return ReconciliationResult(
            payment_state="UNKNOWN",
            subscription_state="UNKNOWN",
            authoritative=False,
            case_recovered=False,
            arrears_collected_paise=0,
            subscription_reactivated=False,
        )

    async def record_audit_event(self, command: AuditInput) -> AuditResult:
        source_event_id = f"temporal:{command.event_type}:{command.correlation_id}"
        evidence_kind = (
            EvidenceKind.RAZORPAY_TEST_VERIFIED
            if command.details.get("provider") == "razorpay"
            else EvidenceKind.SYSTEM_DERIVED
        )
        async with get_session_factory()() as session:
            event = RecoveryEventRecord(
                case_id=command.case_id,
                event_type=command.event_type,
                source="temporal-workflow",
                evidence_kind=evidence_kind,
                payload=command.details,
                occurred_at=datetime.now(UTC),
                correlation_id=command.correlation_id,
                source_event_id=source_event_id,
            )
            session.add(event)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                existing = await session.scalar(
                    select(RecoveryEventRecord).where(
                        RecoveryEventRecord.case_id == command.case_id,
                        RecoveryEventRecord.source_event_id == source_event_id,
                    )
                )
                return AuditResult(
                    audit_event_id=existing.id if existing is not None else source_event_id,
                    recorded=existing is not None,
                )
            return AuditResult(audit_event_id=event.id, recorded=True)

    async def cancel_recovery_action(self, command: CancelActionInput) -> CancelActionResult:
        payment_link_cleanup_ok, payment_link_reason = await self._cleanup_standard_payment_links(
            command.case_id
        )
        async with get_session_factory()() as session:
            actions = list(
                (
                    await session.execute(
                        select(RecoveryActionRecord)
                        .where(
                            RecoveryActionRecord.case_id == command.case_id,
                            RecoveryActionRecord.status.in_(
                                [
                                    ActionStatus.PROPOSED,
                                    ActionStatus.AWAITING_APPROVAL,
                                    ActionStatus.SCHEDULED,
                                    ActionStatus.EXECUTING,
                                    ActionStatus.SUCCEEDED,
                                ]
                            ),
                        )
                        .with_for_update()
                    )
                )
                .scalars()
                .all()
            )
            for action in actions:
                if action.payment_surface_type == PaymentSurfaceType.STANDARD_PAYMENT_LINK:
                    # Standalone links were reconciled/revoked above.  Never
                    # overwrite a PAYMENT_PRESENT or unresolved provider state.
                    continue
                if action.status == ActionStatus.SUCCEEDED:
                    # Provider-owned invoice and card-update surfaces are not
                    # cancellable RecoveryOS resources.
                    continue
                action.status = ActionStatus.CANCELLED
                action.completed_at = self._clock()
            await session.commit()

        voice_reason: str | None = None
        if command.reason == "AUTHORITATIVE_PAYMENT_SUCCESS":
            voice_cancellation_key = f"voice:{command.idempotency_key}:{command.reason.casefold()}"
            async with get_session_factory()() as voice_session:
                resources = create_voice_service_from_env(voice_session)
                try:
                    voice_result = await resources.service.cancel_for_authoritative_payment(
                        case_id=command.case_id,
                        cancellation_key=voice_cancellation_key,
                        now=datetime.now(UTC),
                    )
                finally:
                    await resources.aclose()
            voice_reason = voice_result.reason_code or f"VOICE_{voice_result.status}"
            if voice_result.status == "UNCERTAIN":
                return CancelActionResult(cancelled=False, reason_code=voice_reason)
        if not payment_link_cleanup_ok:
            return CancelActionResult(
                cancelled=False,
                reason_code=payment_link_reason or "PAYMENT_LINK_CLEANUP_UNRESOLVED",
            )
        return CancelActionResult(
            cancelled=True,
            reason_code=(
                voice_reason
                or payment_link_reason
                or ("CANCELLED" if actions else "NO_ACTIVE_ACTION")
            ),
        )

    async def _cleanup_standard_payment_links(self, case_id: str) -> tuple[bool, str | None]:
        async with get_session_factory()() as session:
            actions = list(
                (
                    await session.execute(
                        select(RecoveryActionRecord)
                        .where(
                            RecoveryActionRecord.case_id == case_id,
                            RecoveryActionRecord.payment_surface_type
                            == PaymentSurfaceType.STANDARD_PAYMENT_LINK,
                            RecoveryActionRecord.status.in_(
                                [ActionStatus.EXECUTING, ActionStatus.SUCCEEDED]
                            ),
                        )
                        .with_for_update()
                    )
                )
                .scalars()
                .all()
            )
            if not actions:
                return True, None

            if isinstance(self._payment_provider, MockPaymentProvider):
                for action in actions:
                    action.status = ActionStatus.CANCELLED
                    action.completed_at = self._clock()
                await session.commit()
                return True, "PAYMENT_LINK_MOCK_CANCELLED"

            if not isinstance(self._payment_provider, StandardPaymentLinkLifecycleProvider):
                return False, "PAYMENT_LINK_CLEANUP_UNSUPPORTED"

            payment_present = False
            for action in actions:
                provider_reference = action.external_reference
                if provider_reference is None:
                    reference_id = self._standard_payment_link_reference(action.idempotency_key)
                    try:
                        reconciled = (
                            await self._payment_provider.reconcile_payment_link_by_reference(
                                reference_id=reference_id
                            )
                        )
                    except Exception:
                        await session.rollback()
                        return False, "PAYMENT_LINK_CLEANUP_RECONCILIATION_UNRESOLVED"
                    if reconciled is None:
                        action.status = ActionStatus.CANCELLED
                        action.completed_at = self._clock()
                        continue
                    action.status = ActionStatus.SUCCEEDED
                    action.external_reference = reconciled.provider_reference
                    action.customer_url = reconciled.customer_url
                    provider_reference = reconciled.provider_reference

                try:
                    revocation = await self._payment_provider.revoke_standard_payment_link(
                        provider_reference=provider_reference
                    )
                except Exception:
                    await session.rollback()
                    return False, "PAYMENT_LINK_CLEANUP_UNRESOLVED"
                if revocation == "PAYMENT_PRESENT":
                    # Preserve the successful surface and let the normal signed
                    # webhook / authoritative snapshot path recognize payment.
                    payment_present = True
                    continue
                if revocation not in {"CANCELLED", "ALREADY_INACTIVE"}:
                    await session.rollback()
                    return False, "PAYMENT_LINK_CLEANUP_STATUS_UNRESOLVED"
                action.status = ActionStatus.CANCELLED
                action.completed_at = self._clock()

            await session.commit()
            return (
                True,
                "PAYMENT_LINK_PAYMENT_PRESENT_RECONCILIATION_REQUIRED"
                if payment_present
                else "PAYMENT_LINK_REVOKED",
            )
