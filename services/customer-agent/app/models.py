"""A2A 1.0 wire models and the bounded recovery mandate contract."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class DataPart(WireModel):
    data: dict[str, Any]


class Message(WireModel):
    message_id: str = Field(alias="messageId", min_length=1)
    role: Literal["ROLE_USER", "ROLE_AGENT"]
    parts: list[DataPart] = Field(min_length=1)
    task_id: str | None = Field(default=None, alias="taskId")
    context_id: str | None = Field(default=None, alias="contextId")


class SendMessageParams(WireModel):
    message: Message
    configuration: dict[str, Any] = Field(default_factory=dict)


class GetTaskParams(WireModel):
    id: str = Field(min_length=1)
    history_length: int | None = Field(default=None, alias="historyLength", ge=0)


class CancelTaskParams(WireModel):
    id: str = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=500)


class JsonRpcRequest(WireModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: str | int
    method: str = Field(min_length=1)
    params: dict[str, Any]


class RecoveryRequestData(WireModel):
    protocol_version: Literal["recovery.request.v1"] = "recovery.request.v1"
    idempotency_key: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    merchant_id: str = Field(min_length=1)
    customer_id: str = Field(min_length=1)
    exact_amount_paise: int = Field(gt=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    payment_surface_type: str = Field(min_length=1)
    payment_surface_reference: str = Field(min_length=1)
    expires_at: datetime
    context: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_future_utc_expiry(self) -> RecoveryRequestData:
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise ValueError("expires_at must be timezone-aware")
        return self


class RecoveryReceiptData(WireModel):
    protocol_version: Literal["recovery.receipt.v1"] = "recovery.receipt.v1"
    receipt_id: str = Field(min_length=1)
    signer_key_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    mandate_id: str = Field(min_length=1)
    merchant_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    exact_amount_paise: int = Field(gt=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    provider_reference: str = Field(min_length=1)
    payment_state: Literal["CAPTURED"] = "CAPTURED"
    observed_at: datetime

    @model_validator(mode="after")
    def require_aware_observation(self) -> RecoveryReceiptData:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("receipt observed_at must be timezone-aware")
        return self


class SignedRecoveryReceipt(WireModel):
    algorithm: Literal["Ed25519"] = "Ed25519"
    data: RecoveryReceiptData
    signature: str = Field(min_length=1)


class RecoveryMandateData(WireModel):
    protocol_version: Literal["recovery.mandate.v1"] = "recovery.mandate.v1"
    mandate_id: str
    nonce: str
    signer_key_id: str
    task_id: str
    merchant_id: str
    case_id: str
    customer_id: str
    exact_amount_paise: int = Field(gt=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    payment_surface_type: str
    payment_surface_reference: str
    authorized_action: Literal["OPEN_EXACT_PAYMENT_SURFACE"] = "OPEN_EXACT_PAYMENT_SURFACE"
    issued_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def validate_window(self) -> RecoveryMandateData:
        for value in (self.issued_at, self.expires_at):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("mandate timestamps must be timezone-aware")
        if self.expires_at <= self.issued_at:
            raise ValueError("mandate expires_at must be after issued_at")
        return self


class SignedMandate(WireModel):
    algorithm: Literal["Ed25519"] = "Ed25519"
    data: RecoveryMandateData
    signature: str


class ApprovalDecision(WireModel):
    decision: Literal["APPROVE", "REJECT"]
    merchant_id: str
    case_id: str
    exact_amount_paise: int = Field(gt=0)
    payment_surface_reference: str


class TaskRecord(WireModel):
    id: str
    context_id: str
    state: Literal[
        "TASK_STATE_AUTH_REQUIRED",
        "TASK_STATE_WORKING",
        "TASK_STATE_COMPLETED",
        "TASK_STATE_FAILED",
        "TASK_STATE_CANCELED",
    ]
    status: dict[str, Any]
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    history: list[dict[str, Any]] = Field(default_factory=list)
    request: RecoveryRequestData
    created_at: datetime
    updated_at: datetime
    revision: int = Field(default=1, ge=1, exclude=True)

    def public_dict(self, *, history_length: int | None = None) -> dict[str, Any]:
        history = self.history
        if history_length is not None:
            history = history[-history_length:] if history_length else []
        return {
            "id": self.id,
            "contextId": self.context_id,
            "status": self.status,
            "artifacts": self.artifacts,
            "history": history,
            "metadata": {
                "caseId": self.request.case_id,
                "protocolVersion": self.request.protocol_version,
                "updatedAt": self.updated_at.astimezone(UTC).isoformat(),
            },
        }


class ApprovalSummary(WireModel):
    task_id: str
    state: str
    merchant_id: str
    case_id: str
    exact_amount_paise: int
    currency: str
    payment_surface_type: str
    payment_surface_reference: str
    expires_at: datetime
    merchant_display_name: str
    recovery_reason: str
