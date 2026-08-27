"""Fail-closed authorization for consequential non-mock provider actions."""

from __future__ import annotations

import hmac
import os
from typing import Annotated

from fastapi import Header

from services.api.app.services.cases import ApplicationServiceError


class OperatorAuthorizationRequiredError(ApplicationServiceError):
    code = "OPERATOR_AUTH_REQUIRED"
    status_code = 401


class OperatorAuthorizationNotConfiguredError(ApplicationServiceError):
    code = "OPERATOR_AUTH_NOT_CONFIGURED"
    status_code = 503


def require_operator_for_non_mock_payment(
    x_recoveryos_operator_token: Annotated[
        str | None,
        Header(alias="X-RecoveryOS-Operator-Token"),
    ] = None,
) -> None:
    """Permit mock demos while protecting every real-provider command surface.

    The header is intentionally required only when the payment adapter is not
    mock. This keeps the public deterministic demo usable while ensuring that
    enabling Razorpay cannot silently expose payment actions to anonymous users.
    """

    if os.getenv("PAYMENT_PROVIDER", "mock").strip().lower() == "mock":
        return

    expected_token = os.getenv("OPERATOR_DEMO_TOKEN", "").strip()
    if not expected_token or expected_token == "change-me-locally":
        raise OperatorAuthorizationNotConfiguredError(
            "A non-default server-side operator token is required before enabling a real "
            "payment provider."
        )
    if x_recoveryos_operator_token is None or not hmac.compare_digest(
        x_recoveryos_operator_token,
        expected_token,
    ):
        raise OperatorAuthorizationRequiredError(
            "A valid operator token is required for non-mock payment actions."
        )
