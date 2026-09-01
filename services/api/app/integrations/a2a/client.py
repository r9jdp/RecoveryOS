"""HTTP JSON-RPC client implementing the frozen CustomerAgentClient port."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx

from services.api.app.providers.contracts import CustomerAgentRecoveryRequest, CustomerAgentTask

from .receipts import RecoveryReceiptData, RecoveryReceiptSigner

RECOVERY_MANDATE_EXTENSION_URI = "https://recoveryos.dev/a2a/recovery-mandate/v2"
RECOVERY_RECEIPT_EXTENSION_URI = "https://recoveryos.dev/a2a/recovery-receipt/v2"


class CustomerAgentProtocolError(RuntimeError):
    pass


_STATE_MAP = {
    "TASK_STATE_SUBMITTED": "SUBMITTED",
    "TASK_STATE_WORKING": "WORKING",
    "TASK_STATE_AUTH_REQUIRED": "AUTH_REQUIRED",
    "TASK_STATE_COMPLETED": "COMPLETED",
    "TASK_STATE_FAILED": "FAILED",
    "TASK_STATE_CANCELED": "CANCELED",
}


class A2ACustomerAgentClient:
    def __init__(
        self,
        *,
        origin: str,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 5.0,
        receipt_signer: RecoveryReceiptSigner | None = None,
        bearer_token: str | None = None,
    ) -> None:
        self._origin = origin.rstrip("/")
        self._provided_client = client
        self._timeout = timeout_seconds
        self._receipt_signer = receipt_signer or RecoveryReceiptSigner.mock()
        configured_token = (
            bearer_token
            if bearer_token is not None
            else os.getenv("CUSTOMER_AGENT_S2S_BEARER_TOKEN", "")
        )
        self._bearer_token = configured_token.strip() or None

    async def send_recovery_request(
        self, request: CustomerAgentRecoveryRequest
    ) -> CustomerAgentTask:
        params = {
            "message": {
                "messageId": request.idempotency_key,
                "role": "ROLE_USER",
                "contextId": f"recovery:{request.case_id}",
                "parts": [{"data": request.model_dump(mode="json")}],
            },
            "configuration": {"returnImmediately": False},
        }
        result = await self._rpc("SendMessage", params)
        task = _object(result.get("task"), "SendMessage result.task")
        return self._map_task(task)

    async def get_task(self, *, remote_task_id: str) -> CustomerAgentTask:
        result = await self._rpc("GetTask", {"id": remote_task_id})
        return self._map_task(result)

    async def send_payment_receipt(
        self,
        *,
        remote_task_id: str,
        mandate_id: str,
        merchant_id: str,
        case_id: str,
        recovery_action_id: str,
        failed_invoice_id: str,
        exact_amount_paise: int,
        currency: str,
        provider_reference: str,
        observed_at: datetime,
        idempotency_key: str,
    ) -> CustomerAgentTask:
        """Complete an authorized task with an idempotent captured-payment receipt."""

        receipt = RecoveryReceiptData(
            receipt_id=idempotency_key,
            signer_key_id=self._receipt_signer.signer_key_id,
            task_id=remote_task_id,
            mandate_id=mandate_id,
            merchant_id=merchant_id,
            case_id=case_id,
            recovery_action_id=recovery_action_id,
            failed_invoice_id=failed_invoice_id,
            exact_amount_paise=exact_amount_paise,
            currency=currency,
            provider_reference=provider_reference,
            observed_at=observed_at,
        )
        signed_receipt = self._receipt_signer.sign(receipt)
        result = await self._rpc(
            "SendMessage",
            {
                "message": {
                    "messageId": idempotency_key,
                    "role": "ROLE_USER",
                    "taskId": remote_task_id,
                    "parts": [{"data": signed_receipt.model_dump(mode="json")}],
                }
            },
        )
        task = self._map_task(_object(result.get("task"), "SendMessage result.task"))
        if task.remote_task_id != remote_task_id:
            raise CustomerAgentProtocolError("payment receipt response task ID does not match")
        if task.state != "COMPLETED":
            raise CustomerAgentProtocolError("customer task did not complete after payment receipt")
        return task

    async def cancel_task(self, *, remote_task_id: str, reason: str) -> CustomerAgentTask:
        result = await self._rpc("CancelTask", {"id": remote_task_id, "reason": reason})
        return self._map_task(result)

    async def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid4()),
            "method": method,
            "params": params,
        }
        if self._provided_client is not None:
            return await self._post(self._provided_client, payload)
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            return await self._post(client, payload)

    async def _post(self, client: httpx.AsyncClient, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "A2A-Version": "1.0",
            "A2A-Extensions": (
                f"{RECOVERY_MANDATE_EXTENSION_URI},{RECOVERY_RECEIPT_EXTENSION_URI}"
            ),
        }
        if self._bearer_token is not None:
            headers["Authorization"] = f"Bearer {self._bearer_token}"
        response = await client.post(
            f"{self._origin}/rpc",
            json=payload,
            headers=headers,
        )
        response.raise_for_status()
        body = _object(response.json(), "JSON-RPC response")
        error = body.get("error")
        if error is not None:
            detail = _object(error, "JSON-RPC error")
            error_message = detail.get("message", "unknown error")
            raise CustomerAgentProtocolError(
                f"customer agent rejected {payload['method']}: {error_message}"
            )
        return _object(body.get("result"), "JSON-RPC result")

    @staticmethod
    def _map_task(task: dict[str, Any]) -> CustomerAgentTask:
        status = _object(task.get("status"), "task.status")
        raw_state = str(status.get("state", ""))
        state = _STATE_MAP.get(raw_state)
        if state is None:
            raise CustomerAgentProtocolError(f"unsupported A2A task state: {raw_state}")
        raw_metadata = task.get("metadata")
        metadata: dict[str, Any] = raw_metadata if isinstance(raw_metadata, dict) else {}
        updated_at_value = metadata.get("updatedAt") or status.get("timestamp")
        updated_at = (
            datetime.fromisoformat(str(updated_at_value).replace("Z", "+00:00"))
            if updated_at_value
            else datetime.now(UTC)
        )
        artifacts = task.get("artifacts")
        artifact = None
        if isinstance(artifacts, list) and artifacts:
            first = _object(artifacts[0], "task artifact")
            parts = first.get("parts")
            if isinstance(parts, list) and parts:
                artifact = _object(parts[0], "artifact part").get("data")
        approval_path = None
        status_message = status.get("message")
        if isinstance(status_message, dict):
            message_parts = status_message.get("parts")
            if isinstance(message_parts, list) and message_parts:
                first_part = message_parts[0]
                part_data = first_part.get("data") if isinstance(first_part, dict) else None
                raw_approval_path = (
                    part_data.get("approval_path") if isinstance(part_data, dict) else None
                )
                if isinstance(raw_approval_path, str) and raw_approval_path:
                    approval_path = raw_approval_path
        return CustomerAgentTask(
            remote_task_id=str(task["id"]),
            state=state,
            approval_path=approval_path,
            artifact=artifact if isinstance(artifact, dict) else None,
            updated_at=updated_at,
        )


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CustomerAgentProtocolError(f"{label} must be an object")
    return value
