"""Server-only Razorpay client construction shared by API and worker processes."""

from __future__ import annotations

import os

from .client import RazorpayClient, RazorpayConfig
from .errors import RazorpayIntegrationError


def create_razorpay_client_from_env() -> RazorpayClient:
    """Build a test-mode client without exposing provider secrets to browser code."""

    key_id = os.getenv("RAZORPAY_KEY_ID", "").strip()
    key_secret = os.getenv("RAZORPAY_KEY_SECRET", "").strip()
    if not key_id or not key_secret:
        raise RazorpayIntegrationError(
            "RAZORPAY_CREDENTIALS_NOT_CONFIGURED",
            "Razorpay test credentials are not configured.",
            status_code=503,
        )
    if os.getenv(
        "RAZORPAY_TEST_MODE_REQUIRED", "true"
    ).strip().lower() == "true" and not key_id.startswith("rzp_test_"):
        raise RazorpayIntegrationError(
            "RAZORPAY_TEST_MODE_REQUIRED",
            "Only Razorpay test-mode credentials are accepted.",
            status_code=503,
        )
    return RazorpayClient(
        RazorpayConfig(
            key_id=key_id,
            key_secret=key_secret,
            checkout_origin=os.getenv(
                "RAZORPAY_CHECKOUT_ORIGIN",
                os.getenv("WEB_ORIGIN", "http://localhost:3000").split(",", maxsplit=1)[0],
            ).strip(),
            base_url=os.getenv("RAZORPAY_API_BASE_URL", "https://api.razorpay.com").strip(),
        )
    )
