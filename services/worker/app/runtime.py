"""Production activity composition and persistence-backed provider execution."""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from services.api.app.db import get_session_factory
from services.api.app.domain.enums import (
    ActionStatus,
    Diagnosis,
    EvidenceKind,
    PaymentState,
    PaymentSurfaceType,
    RecoveryActionType,
)
from services.api.app.integrations.razorpay import create_razorpay_client_from_env
from services.api.app.lab.scorer import create_recovery_scorer
from services.api.app.models import (
    RecoveryActionRecord,
    RecoveryCase,
    RecoveryEventRecord,
)
from services.api.app.providers.contracts import (
    OpenPaymentSurfaceRequest,
    RecoveryScoreRequest,
)
from services.api.app.providers.interfaces import PaymentProvider, RecoveryScorer
from services.api.app.services.mock_payment import MockPaymentProvider
from services.api.app.voice.factory import create_voice_service_from_env

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

    def __init__(self, *, payment_provider: PaymentProvider, scorer: RecoveryScorer) -> None:
        self._payment_provider = payment_provider
        self._scorer = scorer
        self._fallback = MockRecoveryActivityServices(require_manual_approval=True)

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
        # Manual approval remains the fail-closed production default. Merchant
        # policy decisions are persisted before this workflow is dispatched.
        return await self._fallback.evaluate_policy(command)

    async def execute_recovery_action(self, command: ExecuteActionInput) -> ActionExecutionResult:
        if command.action in {"WAIT_FOR_GATEWAY_RETRY", "STOP", "ESCALATE_TO_HUMAN"}:
            return ActionExecutionResult(status="SUCCEEDED", provider="workflow")
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

        action = await self._claim_payment_action(command)
        if isinstance(action, ActionExecutionResult):
            return action

        surface_type = PaymentSurfaceType(command.payment_surface_type)
        deadline = _instant(command.recovery_deadline)
        reference_id: str | None = None
        expires_at: datetime | None = None
        notes: dict[str, str] = {}
        if surface_type == PaymentSurfaceType.STANDARD_PAYMENT_LINK:
            reference_id = "rec_" + hashlib.sha256(action.idempotency_key.encode()).hexdigest()[:32]
            expires_at = deadline
            notes = {"case_id": command.case_id, "invoice_id": command.failed_invoice_id}

        try:
            result = await self._payment_provider.open_customer_payment_surface(
                OpenPaymentSurfaceRequest(
                    idempotency_key=action.idempotency_key,
                    case_id=command.case_id,
                    merchant_id=command.merchant_id,
                    customer_id=command.customer_id,
                    subscription_id=command.subscription_id,
                    failed_invoice_id=command.failed_invoice_id,
                    surface_type=surface_type,
                    exact_amount_paise=command.amount_paise,
                    currency=command.currency,
                    recovery_deadline=deadline,
                    expires_at=expires_at,
                    reference_id=reference_id,
                    notes=notes,
                )
            )
        except Exception:
            # Submission may be uncertain. The EXECUTING claim deliberately
            # prevents an automatic second provider call on activity replay.
            raise

        async with get_session_factory()() as session:
            persisted = await session.get(RecoveryActionRecord, action.id, with_for_update=True)
            if persisted is None:
                return ActionExecutionResult(
                    status="UNCERTAIN",
                    provider=result.provider,
                    provider_reference=result.provider_reference,
                    reason_code="ACTION_RECORD_MISSING_AFTER_SUBMISSION",
                )
            persisted.status = ActionStatus.SUCCEEDED
            persisted.external_reference = result.provider_reference
            persisted.customer_url = result.customer_url
            persisted.completed_at = datetime.now(UTC)
            await session.commit()
        return ActionExecutionResult(
            status="SUCCEEDED",
            provider=result.provider,
            provider_reference=result.provider_reference,
            customer_url=result.customer_url,
        )

    async def _claim_payment_action(
        self, command: ExecuteActionInput
    ) -> RecoveryActionRecord | ActionExecutionResult:
        if command.payment_surface_type is None:
            return ActionExecutionResult(
                status="REJECTED",
                provider="none",
                reason_code="PAYMENT_SURFACE_SCOPE_MISSING",
            )
        surface_type = PaymentSurfaceType(command.payment_surface_type)
        async with get_session_factory()() as session:
            statement = (
                select(RecoveryActionRecord)
                .where(
                    RecoveryActionRecord.case_id == command.case_id,
                    RecoveryActionRecord.action_type
                    == RecoveryActionType.OPEN_CUSTOMER_PAYMENT_SURFACE,
                    RecoveryActionRecord.payment_surface_type == surface_type,
                )
                .order_by(RecoveryActionRecord.created_at.desc())
                .with_for_update()
            )
            action = (await session.execute(statement)).scalars().first()
            if action is None:
                return ActionExecutionResult(
                    status="REJECTED",
                    provider="none",
                    reason_code="ACTION_RECORD_NOT_FOUND",
                )
            if action.status == ActionStatus.SUCCEEDED:
                return ActionExecutionResult(
                    status="SUCCEEDED",
                    provider="persisted",
                    provider_reference=action.external_reference,
                    customer_url=action.customer_url,
                    reason_code="ALREADY_EXECUTED",
                )
            if action.status == ActionStatus.EXECUTING:
                return ActionExecutionResult(
                    status="UNCERTAIN",
                    provider="unknown",
                    provider_reference=action.external_reference,
                    reason_code="SUBMISSION_RECONCILIATION_REQUIRED",
                )
            if action.status == ActionStatus.CANCELLED:
                return ActionExecutionResult(
                    status="REJECTED",
                    provider="none",
                    reason_code="ACTION_CANCELLED",
                )
            if action.status != ActionStatus.SCHEDULED:
                return ActionExecutionResult(
                    status="REJECTED",
                    provider="none",
                    reason_code="ACTION_NOT_AUTHORIZED",
                )
            action.status = ActionStatus.EXECUTING
            await session.commit()
            return action

    async def reconcile_case(self, command: ReconciliationInput) -> ReconciliationResult:
        if isinstance(self._payment_provider, MockPaymentProvider):
            return await self._fallback.reconcile_case(command)
        if command.failed_invoice_id is None:
            return ReconciliationResult(
                payment_state="UNKNOWN",
                subscription_state="UNKNOWN",
                authoritative=False,
                case_recovered=False,
                arrears_collected_paise=0,
                subscription_reactivated=False,
            )
        payment_id: str | None = None
        async with get_session_factory()() as session:
            recovery_case = await session.get(RecoveryCase, command.case_id)
            if recovery_case is not None and recovery_case.failed_payment_id:
                from services.api.app.models import PaymentAttempt

                payment = await session.get(PaymentAttempt, recovery_case.failed_payment_id)
                payment_id = payment.provider_payment_id if payment is not None else None
        snapshot = await self._payment_provider.fetch_payment_snapshot(
            merchant_id=command.merchant_id,
            payment_id=payment_id,
            invoice_id=command.failed_invoice_id,
        )
        recovered = snapshot.authoritative and snapshot.payment_state == PaymentState.CAPTURED
        return ReconciliationResult(
            payment_state=snapshot.payment_state.value,
            subscription_state=snapshot.subscription_state.value,
            authoritative=snapshot.authoritative,
            case_recovered=recovered,
            arrears_collected_paise=snapshot.amount_paise if recovered else 0,
            subscription_reactivated=recovered and snapshot.subscription_state.value == "ACTIVE",
            provider_reference=snapshot.payment_id or snapshot.invoice_id,
        )

    async def record_audit_event(self, command: AuditInput) -> AuditResult:
        source_event_id = f"temporal:{command.event_type}:{command.correlation_id}"
        evidence_kind = (
            EvidenceKind.RAZORPAY_TEST_VERIFIED
            if command.details.get("provider") == "razorpay"
            else EvidenceKind.SIMULATED
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
                action.status = ActionStatus.CANCELLED
                action.completed_at = datetime.now(UTC)
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
        return CancelActionResult(
            cancelled=True,
            reason_code=voice_reason or ("CANCELLED" if actions else "NO_ACTIVE_ACTION"),
        )
