"""Authenticated RecoveryOS payment receipts for the customer-agent boundary."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import datetime
from typing import Literal

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import BaseModel, ConfigDict, Field, model_validator

MOCK_RECEIPT_SIGNER_KEY_ID = "recoveryos-receipt-mock-2026-01"
_MOCK_RECEIPT_SEED = hashlib.sha256(b"recoveryos-recovery-agent-receipt-mock-key-v1").digest()


class ReceiptConfigurationError(RuntimeError):
    pass


class ReceiptWireModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RecoveryReceiptData(ReceiptWireModel):
    protocol_version: Literal["recovery.receipt.v2"] = "recovery.receipt.v2"
    receipt_id: str = Field(min_length=1)
    signer_key_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    mandate_id: str = Field(min_length=1)
    merchant_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    recovery_action_id: str = Field(min_length=1)
    failed_invoice_id: str = Field(min_length=1)
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


class SignedRecoveryReceipt(ReceiptWireModel):
    algorithm: Literal["Ed25519"] = "Ed25519"
    data: RecoveryReceiptData
    signature: str = Field(min_length=1)


def canonical_receipt_json(data: RecoveryReceiptData) -> bytes:
    """Serialize the complete signed receipt scope deterministically."""

    return json.dumps(
        data.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


class RecoveryReceiptSigner:
    def __init__(self, *, signer_key_id: str, private_key: Ed25519PrivateKey) -> None:
        self.signer_key_id = signer_key_id
        self._private_key = private_key

    @classmethod
    def from_seed(cls, *, signer_key_id: str, seed: bytes) -> RecoveryReceiptSigner:
        if len(seed) != 32:
            raise ReceiptConfigurationError(
                "recovery receipt Ed25519 seed must contain exactly 32 bytes"
            )
        return cls(
            signer_key_id=signer_key_id,
            private_key=Ed25519PrivateKey.from_private_bytes(seed),
        )

    @classmethod
    def mock(cls) -> RecoveryReceiptSigner:
        return cls.from_seed(
            signer_key_id=MOCK_RECEIPT_SIGNER_KEY_ID,
            seed=_MOCK_RECEIPT_SEED,
        )

    def sign(self, data: RecoveryReceiptData) -> SignedRecoveryReceipt:
        if data.signer_key_id != self.signer_key_id:
            raise ValueError("receipt signer_key_id does not match the active signer")
        return SignedRecoveryReceipt(
            data=data,
            signature=_b64url_encode(self._private_key.sign(canonical_receipt_json(data))),
        )

    @property
    def public_key_base64(self) -> str:
        return _b64url_encode(self._private_key.public_key().public_bytes_raw())


def create_receipt_signer_from_env() -> RecoveryReceiptSigner:
    mode = os.getenv("RECOVERY_AGENT_RECEIPT_SIGNING_MODE", "mock").strip().lower()
    if mode == "mock":
        return RecoveryReceiptSigner.mock()
    if mode != "configured":
        raise ReceiptConfigurationError(
            "RECOVERY_AGENT_RECEIPT_SIGNING_MODE must be mock or configured"
        )
    signer_key_id = os.getenv("RECOVERY_AGENT_RECEIPT_SIGNER_KEY_ID", "").strip()
    encoded_seed = os.getenv("RECOVERY_AGENT_RECEIPT_ED25519_PRIVATE_KEY", "").strip()
    if not signer_key_id or not encoded_seed:
        raise ReceiptConfigurationError(
            "configured receipt signing requires signer key ID and Ed25519 private key"
        )
    try:
        seed = _b64url_decode(encoded_seed)
    except ValueError as exc:
        raise ReceiptConfigurationError(
            "RECOVERY_AGENT_RECEIPT_ED25519_PRIVATE_KEY must be base64url"
        ) from exc
    return RecoveryReceiptSigner.from_seed(signer_key_id=signer_key_id, seed=seed)


def mock_receipt_public_key_base64() -> str:
    return RecoveryReceiptSigner.mock().public_key_base64


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    try:
        return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid base64url value") from exc
