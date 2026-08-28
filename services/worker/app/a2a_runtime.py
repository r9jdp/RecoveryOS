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

from pydantic import ValidationError

from services.api.app.domain.enums import PaymentSurfaceType
from services.api.app.integrations.a2a.client import A2ACustomerAgentClient
from services.api.app.integrations.a2a.factory import create_mandate_verifier_from_env
from services.api.app.integrations.a2a.mandates import (
    MandateVerificationError,
    MandateVerifier,
)
from services.api.app.integrations.a2a.models import ExpectedMandateScope, SignedMandate
from services.api.app.integrations.a2a.receipts import create_receipt_signer_from_env
from services.api.app.providers.contracts import CustomerAgentRecoveryRequest
from services.api.app.providers.interfaces import CustomerAgentClient

from .contracts import (
    A2AAuthorizationResult,
    A2AMandatePollResult,
    A2APaymentReceiptResult,
    PollA2AMandateInput,
    SendA2APaymentReceiptInput,
    StartA2AAuthorizationInput,
)


@dataclass
class LiveA2AMandateActivityServices:
    """Customer-agent client plus pinned-key, single-use mandate verifier."""

    client: CustomerAgentClient
    verifier: MandateVerifier
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    async def start_authorization(
        self, command: StartA2AAuthorizationInput
    ) -> A2AAuthorizationResult:
        deadline = _parse_instant(command.recovery_deadline)
        task = await self.client.send_recovery_request(
            CustomerAgentRecoveryRequest(
                idempotency_key=command.idempotency_key,
                case_id=command.case_id,
                merchant_id=command.merchant_id,
                customer_id=command.customer_id,
                exact_amount_paise=command.exact_amount_paise,
                currency=command.currency,
                payment_surface_type=PaymentSurfaceType(command.payment_surface_type),
                payment_surface_reference=command.payment_surface_reference,
                expires_at=deadline,
                context={"recovery_case_id": command.case_id},
            )
        )
        return A2AAuthorizationResult(remote_task_id=task.remote_task_id, state=task.state)

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
        )

    async def send_payment_receipt(
        self, command: SendA2APaymentReceiptInput
    ) -> A2APaymentReceiptResult:
        observed_at = _parse_instant(command.observed_at)
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

    return LiveA2AMandateActivityServices(
        client=A2ACustomerAgentClient(
            origin=os.getenv("CUSTOMER_AGENT_ORIGIN", "http://localhost:8010"),
            receipt_signer=create_receipt_signer_from_env(),
        ),
        verifier=create_mandate_verifier_from_env(),
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
