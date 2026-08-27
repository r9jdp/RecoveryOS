"""Provider webhook signature verification without SDK-specific dependencies."""

from __future__ import annotations

import base64
import hashlib
import hmac
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


def elevenlabs_signature(*, secret: str, body: bytes, timestamp: str | None = None) -> str:
    """Create the `v1=<hex>` HMAC-SHA256 used by the post-call endpoint.

    When a timestamp is supplied it is bound ahead of the body. This supports
    replay-window enforcement without parsing untrusted JSON first.
    """

    payload = body if timestamp is None else timestamp.encode() + b"." + body
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"v1={digest}"


def verify_elevenlabs_signature(
    *, secret: str, body: bytes, supplied: str | None, timestamp: str | None = None
) -> bool:
    if not secret or not supplied:
        return False
    expected = elevenlabs_signature(secret=secret, body=body, timestamp=timestamp)
    return hmac.compare_digest(expected, supplied)
