"""Razorpay test-mode payment boundary.

The adapter never charges an existing payment.  It can expose a customer-present
surface and reconcile authoritative provider state only.
"""

from .client import RazorpayClient, RazorpayConfig
from .factory import create_razorpay_client_from_env
from .models import NormalizedRazorpayEvent, PaymentRecoveryOutcome
from .signature import verify_webhook_signature

__all__ = [
    "NormalizedRazorpayEvent",
    "PaymentRecoveryOutcome",
    "RazorpayClient",
    "RazorpayConfig",
    "create_razorpay_client_from_env",
    "verify_webhook_signature",
]
