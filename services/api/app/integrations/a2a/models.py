"""Recovery-side representation of the signed customer mandate."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class A2AModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RecoveryMandateData(A2AModel):
    protocol_version: Literal["recovery.mandate.v2"]
    mandate_id: str = Field(min_length=1)
    nonce: str = Field(min_length=1)
    signer_key_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    merchant_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    customer_id: str = Field(min_length=1)
    recovery_action_id: str = Field(min_length=1)
    failed_invoice_id: str = Field(min_length=1)
    exact_amount_paise: int = Field(gt=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    payment_surface_type: str
    payment_surface_reference: str
    authorized_action: Literal["OPEN_EXACT_PAYMENT_SURFACE"]
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


class SignedMandate(A2AModel):
    algorithm: Literal["Ed25519"]
    data: RecoveryMandateData
    signature: str


class ExpectedMandateScope(A2AModel):
    task_id: str
    merchant_id: str
    case_id: str
    customer_id: str
    recovery_action_id: str
    failed_invoice_id: str
    exact_amount_paise: int = Field(gt=0)
    currency: str
    payment_surface_type: str
    payment_surface_reference: str
