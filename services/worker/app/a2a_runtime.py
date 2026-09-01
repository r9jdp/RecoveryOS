"""Activity-side A2A authorization and mandate verification.

HTTP task state, wall-clock checks, signature verification, and atomic nonce
consumption are deliberately kept behind this boundary. Temporal workflow code
only acts on the persisted result of ``poll_and_verify_mandate``.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from services.api.app.db import get_session_factory
from services.api.app.domain.enums import (
    ActionStatus,
    CaseOutcome,
    Diagnosis,
    PaymentState,
    PaymentSurfaceType,
    PolicyDisposition,
    RecoveryActionType,
)
from services.api.app.integrations.a2a.client import A2ACustomerAgentClient
from services.api.app.integrations.a2a.factory import create_mandate_verifier_from_env
from services.api.app.integrations.a2a.mandates import (
    MandateVerificationError,
    MandateVerifier,
)
from services.api.app.integrations.a2a.models import ExpectedMandateScope, SignedMandate
from services.api.app.integrations.a2a.receipts import create_receipt_signer_from_env
from services.api.app.models import (
    Customer,
    Invoice,
    Merchant,
    PolicyDecisionRecord,
    RecoveryActionRecord,
    RecoveryCase,
    Subscription,
)
from services.api.app.providers.contracts import (
    CustomerAgentDisplayContext,
    CustomerAgentRecoveryRequest,
)
from services.api.app.providers.interfaces import CustomerAgentClient

from .contracts import (
    A2AAuthorizationResult,
    A2AMandatePollResult,
    A2APaymentReceiptResult,
    PollA2AMandateInput,
    SendA2APaymentReceiptInput,
    StartA2AAuthorizationInput,
)

_FAILURE_EXPLANATIONS = {
    Diagnosis.TRANSIENT_RETRYABLE: "The payment provider reported a temporary processing issue.",
    Diagnosis.INSUFFICIENT_FUNDS: (
        "The payment could not be completed with the payment method's available balance."
    ),
    Diagnosis.AUTHENTICATION_REQUIRED: (
        "The payment needs customer authentication before it can continue."
    ),
    Diagnosis.INSTRUMENT_INVALID: "The saved payment method could not be used.",
    Diagnosis.MERCHANT_ERROR: "The payment setup needs merchant review.",
    Diagnosis.RISK_OR_COMPLIANCE_BLOCK: ("The payment was blocked by a risk or compliance check."),
    Diagnosis.UNKNOWN: ("The payment could not be completed; no verified reason is available yet."),
}


class A2ADisplayContextLoader(Protocol):
    async def load(
        self,
        *,
        case_id: str,
        merchant_id: str,
        customer_id: str,
    ) -> CustomerAgentDisplayContext: ...


@dataclass(frozen=True)
class SqlAlchemyA2ADisplayContextLoader:
    """Resolve display-only A2A context from the authoritative recovery case."""

    session_factory: async_sessionmaker[AsyncSession]
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    async def load(
        self,
        *,
        case_id: str,
        merchant_id: str,
        customer_id: str,
    ) -> CustomerAgentDisplayContext:
        async with self.session_factory() as session:
            result = await session.execute(
                select(
                    Merchant.display_name,
                    Subscription.plan_name,
                    RecoveryCase.diagnosis,
                    Invoice.invoice_state,
                    RecoveryCase.payment_state,
                    RecoveryCase.subscription_state,
                    Subscription.subscription_state,
                    Customer.preferred_language,
                    Invoice.due_at,
                    RecoveryCase.recovery_deadline,
                )
                .select_from(RecoveryCase)
                .join(Merchant, Merchant.id == RecoveryCase.merchant_id)
                .join(Customer, Customer.id == RecoveryCase.customer_id)
                .join(Subscription, Subscription.id == RecoveryCase.subscription_id)
                .join(Invoice, Invoice.id == RecoveryCase.failed_invoice_id)
                .where(
                    RecoveryCase.id == case_id,
                    RecoveryCase.merchant_id == merchant_id,
                    RecoveryCase.customer_id == customer_id,
                )
            )
            row = result.one_or_none()
        if row is None:
            raise ValueError("A2A display context does not match the recovery case scope")

        (
            merchant_display_name,
            plan_name,
            raw_diagnosis,
            invoice_state,
            payment_state,
            subscription_state,
            provider_subscription_state,
            preferred_language,
            invoice_due_at,
            recovery_deadline,
        ) = row
        diagnosis = Diagnosis(raw_diagnosis)
        return CustomerAgentDisplayContext(
            merchant_display_name=_clean_display_value(merchant_display_name),
            plan_name=_clean_display_value(plan_name),
            failure_explanation=_FAILURE_EXPLANATIONS[diagnosis],
            invoice_state=str(invoice_state),
            payment_state=payment_state.value,
            subscription_state=subscription_state.value,
            provider_subscription_state=provider_subscription_state.value,
            preferred_language=str(preferred_language),
            invoice_due_at=invoice_due_at,
            recovery_deadline=recovery_deadline,
        )

    async def load_authoritative_request(
        self,
        command: StartA2AAuthorizationInput,
    ) -> CustomerAgentRecoveryRequest:
        """Rebuild and validate the complete v2 request from current SQL state.

        Temporal input is a staleable snapshot.  It is compared with, but never
        substituted for, the case, invoice, and exact durable policy action at
        the authorization boundary.
        """

        if command.recovery_action_id is None or command.failed_invoice_id is None:
            raise ValueError("A2A v2 requires a durable action and failed invoice")
        async with self.session_factory() as session:
            result = await session.execute(
                select(
                    Merchant.display_name,
                    Customer.preferred_language,
                    Subscription.plan_name,
                    Subscription.subscription_state,
                    RecoveryCase.case_outcome,
                    RecoveryCase.payment_state,
                    RecoveryCase.subscription_state,
                    RecoveryCase.diagnosis,
                    RecoveryCase.amount_at_risk_paise,
                    RecoveryCase.recovery_deadline,
                    RecoveryCase.case_recovered,
                    Invoice.id,
                    Invoice.provider_invoice_id,
                    Invoice.amount_paise,
                    Invoice.amount_paid_paise,
                    Invoice.currency,
                    Invoice.invoice_state,
                    Invoice.due_at,
                    RecoveryActionRecord.id,
                    RecoveryActionRecord.action_type,
                    RecoveryActionRecord.status,
                    PolicyDecisionRecord.disposition,
                )
                .select_from(RecoveryCase)
                .join(Merchant, Merchant.id == RecoveryCase.merchant_id)
                .join(Customer, Customer.id == RecoveryCase.customer_id)
                .join(Subscription, Subscription.id == RecoveryCase.subscription_id)
                .join(Invoice, Invoice.id == RecoveryCase.failed_invoice_id)
                .join(
                    RecoveryActionRecord,
                    RecoveryActionRecord.case_id == RecoveryCase.id,
                )
                .join(
                    PolicyDecisionRecord,
                    PolicyDecisionRecord.action_id == RecoveryActionRecord.id,
                )
                .where(
                    RecoveryCase.id == command.case_id,
                    RecoveryCase.merchant_id == command.merchant_id,
                    RecoveryCase.customer_id == command.customer_id,
                    Invoice.id == command.failed_invoice_id,
                    RecoveryActionRecord.id == command.recovery_action_id,
                    PolicyDecisionRecord.case_id == RecoveryCase.id,
                )
            )
            row = result.one_or_none()
        if row is None:
            raise ValueError("A2A authoritative scope does not match persisted recovery data")

        (
            merchant_display_name,
            preferred_language,
            plan_name,
            subscription_state,
            case_outcome,
            payment_state,
            case_subscription_state,
            raw_diagnosis,
            amount_at_risk_paise,
            recovery_deadline,
            case_recovered,
            invoice_id,
            provider_invoice_id,
            invoice_amount_paise,
            invoice_paid_paise,
            invoice_currency,
            invoice_state,
            invoice_due_at,
            recovery_action_id,
            action_type,
            action_status,
            policy_disposition,
        ) = row

        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("A2A context loader clock must be timezone-aware")
        deadline = _parse_instant(command.recovery_deadline)
        outstanding_paise = invoice_amount_paise - invoice_paid_paise
        expected_surface = PaymentSurfaceType.SUBSCRIPTION_INVOICE_LINK
        stale_or_unsafe = (
            case_outcome != CaseOutcome.OPEN
            or payment_state == PaymentState.CAPTURED
            or case_recovered
            or recovery_deadline <= now
            or recovery_deadline != deadline
            or amount_at_risk_paise != outstanding_paise
            or command.exact_amount_paise != outstanding_paise
            or command.currency != invoice_currency
            or command.payment_surface_type != expected_surface.value
            or command.payment_surface_reference != provider_invoice_id
            or (
                command.provider_invoice_id is not None
                and command.provider_invoice_id != provider_invoice_id
            )
            or action_type != RecoveryActionType.SEND_TO_CUSTOMER_AGENT
            or action_status not in {ActionStatus.PROPOSED, ActionStatus.SCHEDULED}
            or policy_disposition not in {PolicyDisposition.ALLOW, PolicyDisposition.DELAY}
        )
        if stale_or_unsafe:
            raise ValueError("A2A authorization scope is stale or no longer safe")

        diagnosis = Diagnosis(raw_diagnosis)
        context_kwargs: dict[str, object] = {
            "merchant_display_name": _clean_display_value(merchant_display_name),
            "plan_name": _clean_display_value(plan_name),
            "failure_explanation": _FAILURE_EXPLANATIONS[diagnosis],
        }
        # Newer protocol models expose these sanitized, DB-derived facts.  The
        # conditional keeps old Temporal/test fixtures readable during rollout.
        optional_context = {
            "invoice_state": str(invoice_state),
            "payment_state": payment_state.value,
            "subscription_state": case_subscription_state.value,
            "provider_subscription_state": subscription_state.value,
            "preferred_language": str(preferred_language),
            "invoice_due_at": invoice_due_at,
            "recovery_deadline": recovery_deadline,
        }
        context_fields = CustomerAgentDisplayContext.model_fields
        context_kwargs.update(
            {key: value for key, value in optional_context.items() if key in context_fields}
        )
        return CustomerAgentRecoveryRequest(
            idempotency_key=command.idempotency_key,
            recovery_action_id=recovery_action_id,
            failed_invoice_id=invoice_id,
            case_id=command.case_id,
            merchant_id=command.merchant_id,
            customer_id=command.customer_id,
            exact_amount_paise=outstanding_paise,
            currency=invoice_currency,
            payment_surface_type=expected_surface,
            payment_surface_reference=provider_invoice_id,
            expires_at=recovery_deadline,
            context=CustomerAgentDisplayContext.model_validate(context_kwargs),
        )


@dataclass
class LiveA2AMandateActivityServices:
    """Customer-agent client plus pinned-key, single-use mandate verifier."""

    client: CustomerAgentClient
    verifier: MandateVerifier
    display_context_loader: A2ADisplayContextLoader
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    async def start_authorization(
        self, command: StartA2AAuthorizationInput
    ) -> A2AAuthorizationResult:
        authoritative_loader = getattr(
            self.display_context_loader,
            "load_authoritative_request",
            None,
        )
        if authoritative_loader is not None:
            request = await authoritative_loader(command)
        else:
            # Test/mock loaders remain supported, but real wiring always uses
            # the SQL authoritative loader above.
            if command.recovery_action_id is None or command.failed_invoice_id is None:
                raise ValueError("A2A v2 requires a durable action and failed invoice")
            deadline = _parse_instant(command.recovery_deadline)
            display_context = await self.display_context_loader.load(
                case_id=command.case_id,
                merchant_id=command.merchant_id,
                customer_id=command.customer_id,
            )
            request = CustomerAgentRecoveryRequest(
                idempotency_key=command.idempotency_key,
                recovery_action_id=command.recovery_action_id,
                failed_invoice_id=command.failed_invoice_id,
                case_id=command.case_id,
                merchant_id=command.merchant_id,
                customer_id=command.customer_id,
                exact_amount_paise=command.exact_amount_paise,
                currency=command.currency,
                payment_surface_type=PaymentSurfaceType(command.payment_surface_type),
                payment_surface_reference=command.payment_surface_reference,
                expires_at=deadline,
                context=display_context,
            )
        task = await self.client.send_recovery_request(request)
        return A2AAuthorizationResult(
            remote_task_id=task.remote_task_id,
            state=task.state,
            approval_path=task.approval_path,
        )

    async def poll_and_verify_mandate(self, command: PollA2AMandateInput) -> A2AMandatePollResult:
        task = await self.client.get_task(remote_task_id=command.remote_task_id)
        if task.remote_task_id != command.remote_task_id:
            return _rejected(command, task.state, "A2A_TASK_ID_MISMATCH")
        if task.state in {"SUBMITTED", "AUTH_REQUIRED"}:
            return A2AMandatePollResult(
                remote_task_id=task.remote_task_id,
                task_state=task.state,
                verification_status="PENDING",
            )
        if task.state in {"FAILED", "CANCELED", "COMPLETED"}:
            return _rejected(command, task.state, f"A2A_TASK_{task.state}")
        if task.artifact is None:
            return _rejected(command, task.state, "MISSING_MANDATE_ARTIFACT")
        if command.recovery_action_id is None or command.failed_invoice_id is None:
            return _rejected(command, task.state, "DURABLE_ACTION_SCOPE_REQUIRED")

        # Reject an over-broad authorization before consuming its nonce. The
        # verifier subsequently authenticates the exact same expiry value.
        try:
            signed = SignedMandate.model_validate(task.artifact)
        except ValidationError:
            return _rejected(command, task.state, "MALFORMED_MANDATE")
        deadline = _parse_instant(command.recovery_deadline)
        if signed.data.expires_at > deadline:
            return _rejected(command, task.state, "EXPIRES_AFTER_RECOVERY_DEADLINE")

        expected = ExpectedMandateScope(
            task_id=command.remote_task_id,
            recovery_action_id=command.recovery_action_id,
            failed_invoice_id=command.failed_invoice_id,
            merchant_id=command.merchant_id,
            case_id=command.case_id,
            customer_id=command.customer_id,
            exact_amount_paise=command.exact_amount_paise,
            currency=command.currency,
            payment_surface_type=command.payment_surface_type,
            payment_surface_reference=command.payment_surface_reference,
        )
        try:
            verified = await self.verifier.verify_and_consume(
                signed,
                expected=expected,
                now=self.clock(),
            )
        except MandateVerificationError as exc:
            return _rejected(command, task.state, exc.code)

        return A2AMandatePollResult(
            remote_task_id=task.remote_task_id,
            task_state=task.state,
            verification_status="VERIFIED",
            mandate_id=verified.data.mandate_id,
            verified_artifact=signed.model_dump(mode="json"),
        )

    async def send_payment_receipt(
        self, command: SendA2APaymentReceiptInput
    ) -> A2APaymentReceiptResult:
        observed_at = _parse_instant(command.observed_at)
        recovery_action_id = command.recovery_action_id
        failed_invoice_id = command.failed_invoice_id
        if recovery_action_id is None or failed_invoice_id is None:
            raise ValueError("A2A v2 receipt requires durable action and failed invoice scope")
        task = await self.client.send_payment_receipt(
            remote_task_id=command.remote_task_id,
            mandate_id=command.mandate_id,
            merchant_id=command.merchant_id,
            case_id=command.case_id,
            exact_amount_paise=command.exact_amount_paise,
            currency=command.currency,
            provider_reference=command.provider_reference,
            observed_at=observed_at,
            idempotency_key=command.idempotency_key,
            recovery_action_id=recovery_action_id,
            failed_invoice_id=failed_invoice_id,
        )
        return A2APaymentReceiptResult(
            remote_task_id=task.remote_task_id,
            task_state=task.state,
            delivered=task.state == "COMPLETED",
        )


@dataclass
class MockA2AMandateActivityServices:
    """Safe default that never treats a workflow signal as authorization."""

    poll_results: list[A2AMandatePollResult] = field(default_factory=list)
    started: list[StartA2AAuthorizationInput] = field(default_factory=list)
    polls: list[PollA2AMandateInput] = field(default_factory=list)
    receipts: list[SendA2APaymentReceiptInput] = field(default_factory=list)

    async def start_authorization(
        self, command: StartA2AAuthorizationInput
    ) -> A2AAuthorizationResult:
        self.started.append(command)
        return A2AAuthorizationResult(
            remote_task_id=f"mock-a2a:{command.case_id}",
            state="AUTH_REQUIRED",
            approval_path=f"/a2a/mock-a2a:{command.case_id}",
        )

    async def poll_and_verify_mandate(self, command: PollA2AMandateInput) -> A2AMandatePollResult:
        self.polls.append(command)
        if self.poll_results:
            return self.poll_results.pop(0)
        return A2AMandatePollResult(
            remote_task_id=command.remote_task_id,
            task_state="AUTH_REQUIRED",
            verification_status="PENDING",
        )

    async def send_payment_receipt(
        self, command: SendA2APaymentReceiptInput
    ) -> A2APaymentReceiptResult:
        if command not in self.receipts:
            self.receipts.append(command)
        return A2APaymentReceiptResult(
            remote_task_id=command.remote_task_id,
            task_state="COMPLETED",
            delivered=True,
        )


def create_live_a2a_services_from_env() -> LiveA2AMandateActivityServices:
    """Build live A2A services only after the server-side flag is enabled."""

    bearer_token = os.getenv("CUSTOMER_AGENT_S2S_BEARER_TOKEN", "").strip()
    if not bearer_token and os.getenv("APP_ENV", "development").strip().lower() == "production":
        raise ValueError("live A2A requires CUSTOMER_AGENT_S2S_BEARER_TOKEN")
    return LiveA2AMandateActivityServices(
        client=A2ACustomerAgentClient(
            origin=os.getenv("CUSTOMER_AGENT_ORIGIN", "http://localhost:8010"),
            receipt_signer=create_receipt_signer_from_env(),
            bearer_token=bearer_token or None,
        ),
        verifier=create_mandate_verifier_from_env(),
        display_context_loader=SqlAlchemyA2ADisplayContextLoader(get_session_factory()),
    )


def _rejected(
    command: PollA2AMandateInput, task_state: str, reason_code: str
) -> A2AMandatePollResult:
    return A2AMandatePollResult(
        remote_task_id=command.remote_task_id,
        task_state=task_state,
        verification_status="REJECTED",
        reason_code=reason_code,
    )


def _parse_instant(value: str) -> datetime:
    instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("A2A recovery deadline must include a UTC offset")
    return instant


def _clean_display_value(value: str) -> str:
    cleaned = " ".join(value.split())
    if not cleaned:
        raise ValueError("A2A display context contains an empty display value")
    return cleaned
