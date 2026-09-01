"""Pinned-key verification and single-use consumption for A2A mandates."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import MappingProxyType

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import ValidationError

from .models import ExpectedMandateScope, RecoveryMandateData, SignedMandate
from .nonce_store import MandateNonceClaim, NonceClaimOutcome, NonceStore


class MandateVerificationError(ValueError):
    """A safe, structured rejection at the payment authorization boundary."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class VerifiedMandate:
    data: RecoveryMandateData
    verified_at: datetime
    claim_id: str


def canonical_json(data: RecoveryMandateData) -> bytes:
    return json.dumps(
        data.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _decode(value: str) -> bytes:
    try:
        return base64.b64decode(
            value + "=" * (-len(value) % 4),
            altchars=b"-_",
            validate=True,
        )
    except (ValueError, UnicodeEncodeError, binascii.Error) as exc:
        raise MandateVerificationError("INVALID_ENCODING", "invalid base64url value") from exc


class MandateVerifier:
    def __init__(
        self,
        *,
        pinned_public_keys: Mapping[str, str],
        nonce_store: NonceStore,
        max_clock_skew: timedelta = timedelta(seconds=30),
    ) -> None:
        if not pinned_public_keys:
            raise ValueError("at least one pinned customer-agent public key is required")
        parsed: dict[str, Ed25519PublicKey] = {}
        for key_id, encoded in pinned_public_keys.items():
            raw = _decode(encoded)
            if len(raw) != 32:
                raise ValueError(f"public key {key_id!r} must contain 32 bytes")
            parsed[key_id] = Ed25519PublicKey.from_public_bytes(raw)
        self._keys: Mapping[str, Ed25519PublicKey] = MappingProxyType(parsed)
        self._nonce_store = nonce_store
        self._max_clock_skew = max_clock_skew

    async def verify_and_consume(
        self,
        envelope: SignedMandate | dict[str, object],
        *,
        expected: ExpectedMandateScope,
        now: datetime | None = None,
    ) -> VerifiedMandate:
        try:
            signed = (
                envelope
                if isinstance(envelope, SignedMandate)
                else SignedMandate.model_validate(envelope)
            )
        except ValidationError as exc:
            raise MandateVerificationError(
                "MALFORMED_MANDATE", "mandate envelope does not match recovery.mandate.v2"
            ) from exc
        public_key = self._keys.get(signed.data.signer_key_id)
        if public_key is None:
            raise MandateVerificationError("UNKNOWN_SIGNER_KEY", "signer key is not pinned")
        signature = _decode(signed.signature)
        try:
            public_key.verify(signature, canonical_json(signed.data))
        except InvalidSignature as exc:
            raise MandateVerificationError(
                "INVALID_SIGNATURE", "mandate signature is invalid"
            ) from exc

        observed_at = now or datetime.now(UTC)
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("verification time must be timezone-aware")
        if signed.data.issued_at > observed_at + self._max_clock_skew:
            raise MandateVerificationError("NOT_YET_VALID", "mandate issue time is in the future")
        expired = signed.data.expires_at <= observed_at

        scope_fields = (
            "task_id",
            "merchant_id",
            "case_id",
            "customer_id",
            "recovery_action_id",
            "failed_invoice_id",
            "exact_amount_paise",
            "currency",
            "payment_surface_type",
            "payment_surface_reference",
        )
        mismatches = [
            field
            for field in scope_fields
            if getattr(signed.data, field) != getattr(expected, field)
        ]
        if mismatches:
            raise MandateVerificationError(
                "SCOPE_MISMATCH",
                f"mandate does not match expected {', '.join(mismatches)}",
            )

        claim_id = hashlib.sha256(canonical_json(signed.data)).hexdigest()
        claim = MandateNonceClaim(
            claim_id=claim_id,
            nonce=signed.data.nonce,
            mandate_id=signed.data.mandate_id,
            signer_key_id=signed.data.signer_key_id,
            task_id=signed.data.task_id,
            merchant_id=signed.data.merchant_id,
            case_id=signed.data.case_id,
            customer_id=signed.data.customer_id,
            recovery_action_id=signed.data.recovery_action_id,
            failed_invoice_id=signed.data.failed_invoice_id,
            exact_amount_paise=signed.data.exact_amount_paise,
            currency=signed.data.currency,
            payment_surface_type=signed.data.payment_surface_type,
            payment_surface_reference=signed.data.payment_surface_reference,
            authorized_action=signed.data.authorized_action,
            issued_at=signed.data.issued_at,
            expires_at=signed.data.expires_at,
            consumed_at=observed_at,
        )
        outcome = await self._nonce_store.consume(claim, allow_new=not expired)
        if outcome == NonceClaimOutcome.CONFLICT:
            if expired:
                raise MandateVerificationError("EXPIRED", "mandate has expired")
            raise MandateVerificationError(
                "REPLAYED", "mandate nonce or ID was reused with different signed scope"
            )
        if expired and outcome != NonceClaimOutcome.ALREADY_CLAIMED:
            raise MandateVerificationError("EXPIRED", "mandate has expired")
        return VerifiedMandate(
            data=signed.data,
            verified_at=observed_at,
            claim_id=claim_id,
        )
