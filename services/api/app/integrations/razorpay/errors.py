"""Structured errors at the Razorpay provider boundary."""

from __future__ import annotations

from typing import Any


class RazorpayIntegrationError(RuntimeError):
    """Base error safe for translation into the shared error envelope."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int | None = None,
        retriable: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.retriable = retriable
        self.metadata = metadata or {}


class InvalidWebhookSignatureError(RazorpayIntegrationError):
    def __init__(self) -> None:
        super().__init__(
            "RAZORPAY_WEBHOOK_SIGNATURE_INVALID",
            "The Razorpay webhook signature is invalid.",
        )


class UnsupportedWebhookEventError(RazorpayIntegrationError):
    def __init__(self, event_type: str) -> None:
        super().__init__(
            "RAZORPAY_WEBHOOK_EVENT_UNSUPPORTED",
            f"Unsupported Razorpay webhook event: {event_type}",
            metadata={"event_type": event_type},
        )


class RazorpayContractError(RazorpayIntegrationError):
    def __init__(self, code: str, message: str, **metadata: Any) -> None:
        super().__init__(code, message, metadata=metadata)


class RazorpayRequestError(RazorpayIntegrationError):
    """A conclusive HTTP error response from Razorpay."""


class RazorpayUncertainSubmissionError(RazorpayIntegrationError):
    """A write may have reached Razorpay and must be reconciled, not retried blindly."""

    def __init__(self, *, reference_id: str) -> None:
        super().__init__(
            "RAZORPAY_SUBMISSION_UNCERTAIN",
            "Payment Link submission outcome is uncertain; reconcile by reference_id.",
            retriable=False,
            metadata={"reference_id": reference_id},
        )
