"""Customer-agent task state machine.

The agent only records explicit authorization. Provider execution belongs to a
RecoveryOS activity after the resulting mandate has been verified and consumed.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote
from uuid import uuid4

from .llm import CustomerLanguageInterpreter
from .models import (
    ApprovalDecision,
    ApprovalSummary,
    AuthoritativeApprovalScope,
    CustomerLanguageInterpretation,
    CustomerLanguageRequest,
    Message,
    RecoveryMandateData,
    RecoveryReceiptData,
    RecoveryRequestData,
    SignedMandate,
    SignedRecoveryReceipt,
    TaskRecord,
)
from .signing import MandateSigner, ReceiptAuthenticationError, ReceiptVerifier
from .store import TaskStore, TaskVersionConflictError


class TaskNotFoundError(LookupError):
    pass


class TaskConflictError(ValueError):
    pass


class TaskAuthorizationError(PermissionError):
    pass


class CustomerAgentService:
    def __init__(
        self,
        *,
        store: TaskStore,
        signer: MandateSigner,
        receipt_verifier: ReceiptVerifier,
        language_interpreter: CustomerLanguageInterpreter,
        mandate_ttl_seconds: int = 900,
        approval_token_secret: str | None = None,
    ) -> None:
        self._store = store
        self._signer = signer
        self._receipt_verifier = receipt_verifier
        self._language_interpreter = language_interpreter
        self._mandate_ttl = timedelta(seconds=mandate_ttl_seconds)
        self._approval_token_secret = (
            approval_token_secret.encode("utf-8") if approval_token_secret else None
        )

    async def send_message(self, message: Message) -> TaskRecord:
        part = message.parts[0].data
        protocol_version = part.get("protocol_version") or part.get("protocolVersion")
        if protocol_version == "recovery.request.v2":
            request = RecoveryRequestData.model_validate(part)
            return await self._create_authorization_task(message=message, request=request)
        nested_data = part.get("data")
        nested_protocol = (
            nested_data.get("protocol_version") if isinstance(nested_data, dict) else None
        )
        if protocol_version == "recovery.receipt.v2" or nested_protocol == "recovery.receipt.v2":
            signed_receipt = SignedRecoveryReceipt.model_validate(part)
            try:
                receipt = self._receipt_verifier.verify(signed_receipt)
            except ReceiptAuthenticationError as exc:
                raise TaskConflictError(str(exc)) from exc
            return await self._complete_with_receipt(
                message=message,
                signed_receipt=signed_receipt,
                receipt=receipt,
            )
        raise TaskConflictError("unsupported recovery DataPart protocol_version")

    async def _create_authorization_task(
        self, *, message: Message, request: RecoveryRequestData
    ) -> TaskRecord:
        now = datetime.now(UTC)
        if request.expires_at <= now:
            raise TaskConflictError("recovery request has expired")
        task_id = f"task_{uuid4().hex}"
        context_id = message.context_id or f"ctx_{request.case_id}"
        task = TaskRecord(
            id=task_id,
            context_id=context_id,
            state="TASK_STATE_AUTH_REQUIRED",
            status={
                "state": "TASK_STATE_AUTH_REQUIRED",
                "timestamp": now.isoformat(),
                "message": {
                    "messageId": f"msg_{uuid4().hex}",
                    "role": "ROLE_AGENT",
                    "taskId": task_id,
                    "contextId": context_id,
                    "parts": [
                        {
                            "data": {
                                "protocol_version": "recovery.authorization-required.v1",
                                "approval_path": f"/a2a/{task_id}",
                                "case_id": request.case_id,
                            }
                        }
                    ],
                },
            },
            request=request,
            history=[message.model_dump(mode="json", by_alias=True, exclude_none=True)],
            created_at=now,
            updated_at=now,
        )
        return await self._store.create_once(idempotency_key=request.idempotency_key, task=task)

    async def get_task(self, task_id: str) -> TaskRecord:
        task = await self._store.get(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        return task

    def public_task(
        self,
        task: TaskRecord,
        *,
        history_length: int | None = None,
    ) -> dict[str, Any]:
        """Render an A2A task and attach its stateless approval capability.

        The token is derived for each response and is never persisted in the
        task store, signed artifacts, or model context.
        """

        public = deepcopy(task.public_dict(history_length=history_length))
        status = public.get("status")
        message = status.get("message") if isinstance(status, dict) else None
        parts = message.get("parts") if isinstance(message, dict) else None
        if isinstance(parts, list) and parts:
            first = parts[0]
            data = first.get("data") if isinstance(first, dict) else None
            if isinstance(data, dict) and "approval_path" in data:
                data["approval_path"] = self.approval_path(task)
        return public

    def approval_path(self, task: TaskRecord) -> str:
        base_path = f"/a2a/{quote(task.id, safe='')}"
        token = self._approval_token(task)
        if token is None:
            return base_path
        return f"{base_path}#token={token}"

    async def _authorized_task(
        self,
        task_id: str,
        *,
        approval_token: str | None,
    ) -> TaskRecord:
        task = await self.get_task(task_id)
        expected = self._approval_token(task)
        if expected is None:
            return task
        supplied = approval_token or ""
        if not hmac.compare_digest(supplied.encode("utf-8"), expected.encode("ascii")):
            raise TaskAuthorizationError("invalid customer approval capability")
        if task.request.expires_at <= datetime.now(UTC):
            raise TaskAuthorizationError("customer approval capability has expired")
        return task

    def _approval_token(self, task: TaskRecord) -> str | None:
        if self._approval_token_secret is None:
            return None
        identity = {
            "context_id": task.context_id,
            "request": task.request.model_dump(
                mode="json",
                by_alias=True,
                exclude_none=False,
            ),
            "task_id": task.id,
            "version": "recoveryos.customer-approval-capability.v1",
        }
        canonical_identity = json.dumps(
            identity,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        digest = hmac.new(
            self._approval_token_secret,
            canonical_identity,
            hashlib.sha256,
        ).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

    async def cancel_task(self, task_id: str, *, reason: str) -> TaskRecord:
        # Cancellation is safety-preferred. Retry only an optimistic conflict so
        # a concurrent approval cannot silently overwrite an accepted cancel.
        for _attempt in range(3):
            task = await self.get_task(task_id)
            if task.state in {"TASK_STATE_COMPLETED", "TASK_STATE_CANCELED"}:
                return task
            expected_revision = task.revision
            now = datetime.now(UTC)
            task.state = "TASK_STATE_CANCELED"
            task.status = {
                "state": task.state,
                "timestamp": now.isoformat(),
                "message": self._agent_message(
                    task,
                    {"protocol_version": "recovery.canceled.v1", "reason": reason},
                ),
            }
            task.updated_at = now
            try:
                await self._store.save(task, expected_revision=expected_revision)
            except TaskVersionConflictError:
                continue
            return task
        raise TaskConflictError("task changed concurrently; retry cancellation")

    async def approval_summary(
        self,
        task_id: str,
        *,
        approval_token: str | None = None,
    ) -> ApprovalSummary:
        task = await self._authorized_task(task_id, approval_token=approval_token)
        if task.state != "TASK_STATE_AUTH_REQUIRED":
            raise TaskConflictError("task is not awaiting customer authorization")
        return self._approval_summary(task)

    async def interpret_customer_language(
        self,
        *,
        task_id: str,
        request: CustomerLanguageRequest,
        approval_token: str | None = None,
    ) -> CustomerLanguageInterpretation:
        task = await self._authorized_task(task_id, approval_token=approval_token)
        if task.state != "TASK_STATE_AUTH_REQUIRED":
            raise TaskConflictError("task is not awaiting customer authorization")
        revision = task.revision
        summary = self._approval_summary(task)
        interpretation = await self._language_interpreter.interpret(
            request=request,
            summary=summary,
        )
        # Do not return a stale advisory result if an explicit decision landed
        # while the non-authoritative model call was in flight.
        latest = await self.get_task(task_id)
        if latest.revision != revision or latest.state != "TASK_STATE_AUTH_REQUIRED":
            raise TaskConflictError("authorization changed while language was interpreted")
        return CustomerLanguageInterpretation(
            task_id=task.id,
            intent=interpretation.intent,
            confidence_basis_points=interpretation.confidence_basis_points,
            explanation=interpretation.explanation,
            authoritative_scope=AuthoritativeApprovalScope(
                merchant_id=summary.merchant_id,
                case_id=summary.case_id,
                recovery_action_id=summary.recovery_action_id,
                failed_invoice_id=summary.failed_invoice_id,
                exact_amount_paise=summary.exact_amount_paise,
                currency=summary.currency,
                payment_surface_type=summary.payment_surface_type,
                payment_surface_reference=summary.payment_surface_reference,
                expires_at=summary.expires_at,
            ),
        )

    @staticmethod
    def _approval_summary(task: TaskRecord) -> ApprovalSummary:
        request = task.request
        return ApprovalSummary(
            task_id=task.id,
            state=task.state,
            merchant_id=request.merchant_id,
            case_id=request.case_id,
            recovery_action_id=request.recovery_action_id,
            failed_invoice_id=request.failed_invoice_id,
            exact_amount_paise=request.exact_amount_paise,
            currency=request.currency,
            payment_surface_type=request.payment_surface_type,
            payment_surface_reference=request.payment_surface_reference,
            expires_at=request.expires_at,
            merchant_display_name=request.context.merchant_display_name,
            plan_name=request.context.plan_name,
            failure_explanation=request.context.failure_explanation,
            invoice_state=request.context.invoice_state,
            payment_state=request.context.payment_state,
            subscription_state=request.context.subscription_state,
            provider_subscription_state=request.context.provider_subscription_state,
            preferred_language=request.context.preferred_language,
            invoice_due_at=request.context.invoice_due_at,
            recovery_deadline=request.context.recovery_deadline,
        )

    async def decide(
        self,
        *,
        task_id: str,
        decision: ApprovalDecision,
        approval_token: str | None = None,
    ) -> TaskRecord:
        task = await self._authorized_task(task_id, approval_token=approval_token)
        expected_revision = task.revision
        request = task.request
        if task.state != "TASK_STATE_AUTH_REQUIRED":
            raise TaskConflictError("authorization has already been decided")
        expected = (
            request.merchant_id,
            request.case_id,
            request.exact_amount_paise,
            request.payment_surface_reference,
        )
        received = (
            decision.merchant_id,
            decision.case_id,
            decision.exact_amount_paise,
            decision.payment_surface_reference,
        )
        if received != expected:
            raise TaskConflictError("approval scope does not match the recovery request")
        now = datetime.now(UTC)
        if request.expires_at <= now:
            raise TaskConflictError("recovery request has expired")
        if decision.decision == "REJECT":
            task.state = "TASK_STATE_CANCELED"
            task.status = {
                "state": task.state,
                "timestamp": now.isoformat(),
                "message": self._agent_message(
                    task,
                    {"protocol_version": "recovery.authorization-declined.v1"},
                ),
            }
            task.updated_at = now
            await self._save_once(task, expected_revision=expected_revision)
            return task

        mandate = RecoveryMandateData(
            mandate_id=f"mandate_{uuid4().hex}",
            nonce=secrets.token_urlsafe(24),
            signer_key_id=self._signer.signer_key_id,
            task_id=task.id,
            merchant_id=request.merchant_id,
            case_id=request.case_id,
            customer_id=request.customer_id,
            recovery_action_id=request.recovery_action_id,
            failed_invoice_id=request.failed_invoice_id,
            exact_amount_paise=request.exact_amount_paise,
            currency=request.currency,
            payment_surface_type=request.payment_surface_type,
            payment_surface_reference=request.payment_surface_reference,
            issued_at=now,
            expires_at=min(request.expires_at, now + self._mandate_ttl),
        )
        signed = self._signer.sign(mandate)
        task.state = "TASK_STATE_WORKING"
        task.artifacts = [self._mandate_artifact(signed)]
        task.status = {
            "state": task.state,
            "timestamp": now.isoformat(),
            "message": self._agent_message(
                task,
                {
                    "protocol_version": "recovery.authorization-granted.v1",
                    "mandate_id": mandate.mandate_id,
                    "notice": "Authorization recorded; RecoveryOS must verify it before use.",
                },
            ),
        }
        task.updated_at = now
        await self._save_once(task, expected_revision=expected_revision)
        return task

    async def _complete_with_receipt(
        self,
        *,
        message: Message,
        signed_receipt: SignedRecoveryReceipt,
        receipt: RecoveryReceiptData,
    ) -> TaskRecord:
        task_id = message.task_id or receipt.task_id
        task = await self.get_task(task_id)
        if self._is_duplicate_message(task, message):
            return task
        if task.state != "TASK_STATE_WORKING":
            raise TaskConflictError("task is not awaiting a payment receipt")
        if message.message_id != receipt.receipt_id:
            raise TaskConflictError("receipt ID does not match the A2A message ID")
        expected_revision = task.revision
        mandate_part = task.artifacts[0]["parts"][0]["data"]
        mandate_data = mandate_part["data"]
        expected = (
            task.id,
            mandate_data["mandate_id"],
            task.request.merchant_id,
            task.request.case_id,
            mandate_data["recovery_action_id"],
            mandate_data["failed_invoice_id"],
            task.request.exact_amount_paise,
            task.request.currency,
        )
        received = (
            receipt.task_id,
            receipt.mandate_id,
            receipt.merchant_id,
            receipt.case_id,
            receipt.recovery_action_id,
            receipt.failed_invoice_id,
            receipt.exact_amount_paise,
            receipt.currency,
        )
        if received != expected:
            raise TaskConflictError("receipt scope does not match the signed mandate")
        now = datetime.now(UTC)
        task.state = "TASK_STATE_COMPLETED"
        task.artifacts.append(
            {
                "artifactId": f"receipt_{uuid4().hex}",
                "name": "Recovery payment receipt",
                "parts": [{"data": signed_receipt.model_dump(mode="json")}],
            }
        )
        task.history.append(message.model_dump(mode="json", by_alias=True, exclude_none=True))
        task.status = {
            "state": task.state,
            "timestamp": now.isoformat(),
            "message": self._agent_message(
                task,
                {
                    "protocol_version": "recovery.completed.v1",
                    "payment_state": receipt.payment_state,
                    "provider_reference": receipt.provider_reference,
                },
            ),
        }
        task.updated_at = now
        try:
            await self._store.save(task, expected_revision=expected_revision)
        except TaskVersionConflictError as exc:
            latest = await self.get_task(task_id)
            if self._is_duplicate_message(latest, message):
                return latest
            raise TaskConflictError("task changed concurrently; retry receipt") from exc
        return task

    async def _save_once(self, task: TaskRecord, *, expected_revision: int) -> None:
        try:
            await self._store.save(task, expected_revision=expected_revision)
        except TaskVersionConflictError as exc:
            raise TaskConflictError("task changed concurrently; retry request") from exc

    @staticmethod
    def _is_duplicate_message(task: TaskRecord, message: Message) -> bool:
        received = message.model_dump(mode="json", by_alias=True, exclude_none=True)
        for item in task.history:
            if not isinstance(item, dict) or item.get("messageId") != message.message_id:
                continue
            if item != received:
                raise TaskConflictError("messageId was reused with different receipt data")
            return True
        return False

    @staticmethod
    def _agent_message(task: TaskRecord, data: dict[str, Any]) -> dict[str, Any]:
        return {
            "messageId": f"msg_{uuid4().hex}",
            "role": "ROLE_AGENT",
            "taskId": task.id,
            "contextId": task.context_id,
            "parts": [{"data": data}],
        }

    @staticmethod
    def _mandate_artifact(signed: SignedMandate) -> dict[str, Any]:
        return {
            "artifactId": signed.data.mandate_id,
            "name": "Exact payment-surface authorization",
            "description": (
                "Single-use customer authorization; this artifact does not execute payment."
            ),
            "parts": [{"data": signed.model_dump(mode="json")}],
        }
