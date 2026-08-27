"""Fail-closed operator sessions for consequential provider actions."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Annotated, Any

from fastapi import APIRouter, Cookie, Header, Response
from pydantic import BaseModel, ConfigDict, Field

from services.api.app.services.cases import ApplicationServiceError

_COOKIE_NAME = "recoveryos_operator_session"
_LOCAL_EMAIL = "demo@recoveryos.dev"
_LOCAL_CREDENTIAL = "recovery-demo"
_LOCAL_SESSION_SECRET = "recoveryos-local-session-v1"

operator_router = APIRouter(prefix="/v1/operator", tags=["operator"])


class OperatorAuthorizationRequiredError(ApplicationServiceError):
    code = "OPERATOR_AUTH_REQUIRED"
    status_code = 401


class OperatorAuthorizationNotConfiguredError(ApplicationServiceError):
    code = "OPERATOR_AUTH_NOT_CONFIGURED"
    status_code = 503


class OperatorLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=512)


class OperatorSessionResponse(BaseModel):
    operator: str
    csrf_token: str
    expires_at_epoch: int


def _enabled(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _authorization_required() -> bool:
    """Use an API-owned guard instead of trusting a worker-only provider setting."""

    return (
        os.getenv("PAYMENT_PROVIDER", "mock").strip().lower() != "mock"
        or _enabled("RECOVERY_ALLOW_REAL_PAYMENT_ACTIONS")
        or _enabled("OPERATOR_AUTH_REQUIRED")
    )


def _configured_credential(*, required: bool) -> str:
    configured = os.getenv("OPERATOR_DEMO_TOKEN", "").strip()
    if configured:
        if required and configured in {"change-me-locally", _LOCAL_CREDENTIAL}:
            raise OperatorAuthorizationNotConfiguredError(
                "A non-default server-side operator credential is required before enabling "
                "real payment actions."
            )
        return configured
    if required:
        raise OperatorAuthorizationNotConfiguredError(
            "A server-side operator credential is required before enabling real payment actions."
        )
    return _LOCAL_CREDENTIAL


def _session_secret(*, required: bool) -> bytes:
    configured = os.getenv("OPERATOR_SESSION_SECRET", "").strip()
    if configured:
        if required and configured == _LOCAL_SESSION_SECRET:
            raise OperatorAuthorizationNotConfiguredError(
                "A non-default OPERATOR_SESSION_SECRET is required for real payment actions."
            )
        return configured.encode("utf-8")
    if required:
        raise OperatorAuthorizationNotConfiguredError(
            "OPERATOR_SESSION_SECRET is required before enabling real payment actions."
        )
    return _LOCAL_SESSION_SECRET.encode("utf-8")


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _sign_session(payload: dict[str, Any], secret: bytes) -> str:
    encoded = _encode(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
    signature = hmac.new(secret, encoded.encode("ascii"), hashlib.sha256).digest()
    return f"{encoded}.{_encode(signature)}"


def _verify_session(token: str, secret: bytes) -> dict[str, Any] | None:
    try:
        encoded, supplied_signature = token.split(".", 1)
        expected = hmac.new(secret, encoded.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(_decode(supplied_signature), expected):
            return None
        payload = json.loads(_decode(encoded))
        if not isinstance(payload, dict):
            return None
        if payload.get("sub") != "demo-operator":
            return None
        if not isinstance(payload.get("csrf"), str):
            return None
        if not isinstance(payload.get("exp"), int) or payload["exp"] <= int(time.time()):
            return None
        return payload
    except (ValueError, TypeError, UnicodeError, binascii.Error, json.JSONDecodeError):
        return None


@operator_router.post("/session", response_model=OperatorSessionResponse)
async def create_operator_session(
    request: OperatorLoginRequest,
    response: Response,
) -> OperatorSessionResponse:
    required = _authorization_required()
    expected_email = os.getenv("OPERATOR_DEMO_EMAIL", _LOCAL_EMAIL).strip().casefold()
    expected_credential = _configured_credential(required=required)
    if not (
        hmac.compare_digest(request.email.strip().casefold(), expected_email)
        and hmac.compare_digest(request.password, expected_credential)
    ):
        raise OperatorAuthorizationRequiredError("The operator credentials are invalid.")

    ttl_seconds = 8 * 60 * 60
    csrf_token = secrets.token_urlsafe(32)
    expires_at = int(time.time()) + ttl_seconds
    token = _sign_session(
        {"sub": "demo-operator", "csrf": csrf_token, "exp": expires_at},
        _session_secret(required=required),
    )
    app_env = os.getenv("APP_ENV", "development").strip().lower()
    secure_default = "true" if app_env in {"staging", "production"} else "false"
    response.set_cookie(
        key=_COOKIE_NAME,
        value=token,
        max_age=ttl_seconds,
        httponly=True,
        secure=_enabled("OPERATOR_COOKIE_SECURE", secure_default),
        samesite="lax",
        path="/",
    )
    return OperatorSessionResponse(
        operator="demo-operator",
        csrf_token=csrf_token,
        expires_at_epoch=expires_at,
    )


def require_operator_for_non_mock_payment(
    x_recoveryos_operator_token: Annotated[
        str | None,
        Header(alias="X-RecoveryOS-Operator-Token"),
    ] = None,
    x_recoveryos_csrf_token: Annotated[
        str | None,
        Header(alias="X-RecoveryOS-CSRF-Token"),
    ] = None,
    operator_session: Annotated[str | None, Cookie(alias=_COOKIE_NAME)] = None,
) -> None:
    """Permit safe mock demos and authenticate every potentially real action.

    Server-to-server smoke clients may use the legacy operator header. Browser
    clients use an HttpOnly signed session plus a matching CSRF header; the raw
    operator credential is never stored in browser-accessible state.
    """

    if not _authorization_required():
        return

    expected_credential = _configured_credential(required=True)
    if x_recoveryos_operator_token is not None and hmac.compare_digest(
        x_recoveryos_operator_token,
        expected_credential,
    ):
        return

    if operator_session is not None:
        payload = _verify_session(operator_session, _session_secret(required=True))
        expected_csrf = payload.get("csrf") if payload is not None else None
        if (
            isinstance(expected_csrf, str)
            and x_recoveryos_csrf_token is not None
            and hmac.compare_digest(x_recoveryos_csrf_token, expected_csrf)
        ):
            return

    raise OperatorAuthorizationRequiredError(
        "A valid operator session is required for non-mock payment actions."
    )
