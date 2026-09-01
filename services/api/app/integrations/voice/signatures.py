"""Provider webhook signature verification without SDK-specific dependencies."""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from collections.abc import Mapping


def twilio_signature(*, auth_token: str, url: str, parameters: Mapping[str, str]) -> str:
    """Return the Twilio form-webhook HMAC-SHA1 signature.

    Twilio signs the exact public URL followed by form keys in lexical order and
    each key's value. The endpoint must therefore receive its externally visible
    URL from trusted server configuration when it is behind Caddy or another proxy.
    """

    payload = url + "".join(f"{key}{parameters[key]}" for key in sorted(parameters))
    digest = hmac.new(auth_token.encode(), payload.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def verify_twilio_signature(
    *, auth_token: str, url: str, parameters: Mapping[str, str], supplied: str | None
) -> bool:
    if not auth_token or not supplied:
        return False
    expected = twilio_signature(auth_token=auth_token, url=url, parameters=parameters)
    return hmac.compare_digest(expected, supplied)


def elevenlabs_signature(*, secret: str, body: bytes, timestamp: str) -> str:
    """Create ElevenLabs' ``t=<unix>,v0=<hex>`` HMAC header for tests."""

    payload = timestamp.encode() + b"." + body
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v0={digest}"


def verify_elevenlabs_signature(
    *,
    secret: str,
    body: bytes,
    supplied: str | None,
    now: int | None = None,
    tolerance_seconds: int = 30 * 60,
) -> bool:
    """Verify the official ElevenLabs signature over the exact raw body.

    The timestamp and one or more ``v0`` digests are carried in the single
    ``ElevenLabs-Signature`` header.  A bounded timestamp window prevents a
    valid captured delivery from being replayed indefinitely.
    """

    if not secret or not supplied:
        return False
    if tolerance_seconds < 0:
        return False
    timestamp: str | None = None
    signatures: list[str] = []
    for component in supplied.split(","):
        name, separator, value = component.strip().partition("=")
        if not separator or not value:
            return False
        if name == "t":
            if timestamp is not None:
                return False
            timestamp = value
        elif name == "v0":
            signatures.append(value)
    if timestamp is None or not signatures:
        return False
    try:
        signed_at = int(timestamp)
    except ValueError:
        return False
    current = int(time.time()) if now is None else now
    if abs(current - signed_at) > tolerance_seconds:
        return False
    expected = hmac.new(
        secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256
    ).hexdigest()
    valid = False
    for candidate in signatures:
        # Do not reveal which rotation candidate matched through early exit.
        valid = hmac.compare_digest(expected, candidate) or valid
    return valid
