"""Canonical JSON and Ed25519 signing for exact recovery mandates."""

from __future__ import annotations

import base64
import json

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from .models import RecoveryMandateData, SignedMandate


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def canonical_json(data: RecoveryMandateData | dict[str, object]) -> bytes:
    """Serialize the signed DataPart with stable RFC-8259-compatible JSON."""

    payload = data.model_dump(mode="json") if isinstance(data, RecoveryMandateData) else data
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


class MandateSigner:
    def __init__(self, *, signer_key_id: str, private_key: Ed25519PrivateKey) -> None:
        self.signer_key_id = signer_key_id
        self._private_key = private_key

    @classmethod
    def from_seed(cls, *, signer_key_id: str, seed: bytes) -> MandateSigner:
        if len(seed) != 32:
            raise ValueError("Ed25519 private seed must contain exactly 32 bytes")
        return cls(
            signer_key_id=signer_key_id,
            private_key=Ed25519PrivateKey.from_private_bytes(seed),
        )

    @classmethod
    def from_base64_seed(cls, *, signer_key_id: str, seed: str) -> MandateSigner:
        return cls.from_seed(signer_key_id=signer_key_id, seed=_b64url_decode(seed))

    @property
    def public_key_base64(self) -> str:
        raw = self._private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return _b64url_encode(raw)

    def sign(self, mandate: RecoveryMandateData) -> SignedMandate:
        if mandate.signer_key_id != self.signer_key_id:
            raise ValueError("mandate signer_key_id does not match the active signer")
        return SignedMandate(
            data=mandate,
            signature=_b64url_encode(self._private_key.sign(canonical_json(mandate))),
        )


def public_key_from_base64(value: str) -> Ed25519PublicKey:
    raw = _b64url_decode(value)
    if len(raw) != 32:
        raise ValueError("Ed25519 public key must contain exactly 32 bytes")
    return Ed25519PublicKey.from_public_bytes(raw)


def decode_signature(value: str) -> bytes:
    return _b64url_decode(value)
