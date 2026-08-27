"""Raw-body Razorpay webhook signature validation."""

from __future__ import annotations

import hashlib
import hmac

from .errors import InvalidWebhookSignatureError


def webhook_signature(raw_body: bytes, secret: str) -> str:
    """Return the lowercase SHA-256 HMAC hex digest for test/support tooling."""

    if not secret:
        raise ValueError("webhook secret must not be empty")
    return hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()


def verify_webhook_signature(raw_body: bytes, received_signature: str, secret: str) -> None:
    """Validate the signature over the exact bytes received, before JSON parsing."""

    if not received_signature or not secret:
        raise InvalidWebhookSignatureError
    expected = webhook_signature(raw_body, secret)
    if not hmac.compare_digest(expected, received_signature.strip().lower()):
        raise InvalidWebhookSignatureError
