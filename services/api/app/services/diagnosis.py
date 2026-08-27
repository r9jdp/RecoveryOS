"""Deterministic, evidence-conservative payment failure diagnosis."""

from __future__ import annotations

from dataclasses import dataclass

from services.api.app.domain.enums import Diagnosis, PaymentState


@dataclass(frozen=True, slots=True)
class DiagnosisEvidence:
    payment_state: PaymentState
    event_type: str
    invoice_correlated: bool
    subscription_correlated: bool
    error_code: str | None = None
    error_source: str | None = None
    error_step: str | None = None
    error_reason: str | None = None


_INSUFFICIENT_FUNDS = frozenset(
    {
        "BAD_REQUEST_PAYMENT_CARD_INSUFFICIENT_BALANCE",
        "INSUFFICIENT_FUNDS",
        "INSUFFICIENT_BALANCE",
    }
)
_AUTHENTICATION_REQUIRED = frozenset(
    {
        "BAD_REQUEST_PAYMENT_AUTHENTICATION_FAILED",
        "AUTHENTICATION_FAILED",
        "INCORRECT_OTP",
        "OTP_ATTEMPTS_EXCEEDED",
        "3DS_AUTHENTICATION_FAILED",
    }
)
_INSTRUMENT_INVALID = frozenset(
    {
        "BAD_REQUEST_PAYMENT_CARD_EXPIRED",
        "BAD_REQUEST_PAYMENT_INVALID_CARD",
        "CARD_EXPIRED",
        "INVALID_CARD",
        "CARD_DECLINED",
    }
)
_TRANSIENT = frozenset(
    {
        "GATEWAY_ERROR",
        "BAD_REQUEST_PAYMENT_PENDING",
        "BANK_SYSTEM_ERROR",
        "NETWORK_ERROR",
        "REQUEST_TIMED_OUT",
        "ISSUER_UNAVAILABLE",
    }
)
_MERCHANT_ERROR = frozenset(
    {
        "MERCHANT_CONFIGURATION_ERROR",
        "INVALID_MERCHANT_CONFIGURATION",
    }
)
_RISK_BLOCK = frozenset(
    {
        "RISK_CHECK_FAILED",
        "PAYMENT_RISK_REJECTED",
        "COMPLIANCE_BLOCK",
        "FRAUD_SUSPECTED",
    }
)


def diagnose_failure(evidence: DiagnosisEvidence) -> Diagnosis:
    """Return a diagnosis only when payment, invoice, and subscription agree.

    Subscription events commonly omit payment failure evidence. Missing or
    contradictory correlation deliberately returns ``UNKNOWN``.
    """

    if (
        evidence.event_type != "payment.failed"
        or evidence.payment_state != PaymentState.FAILED
        or not evidence.invoice_correlated
        or not evidence.subscription_correlated
    ):
        return Diagnosis.UNKNOWN

    tokens = {
        token.strip().upper()
        for token in (
            evidence.error_code,
            evidence.error_source,
            evidence.error_step,
            evidence.error_reason,
        )
        if token and token.strip()
    }
    if tokens & _RISK_BLOCK:
        return Diagnosis.RISK_OR_COMPLIANCE_BLOCK
    # Razorpay's BAD_REQUEST_ERROR is a generic envelope code. It must not
    # override specific customer/authentication evidence carried by the other
    # fields. Only an explicit merchant token or merchant-specific code is
    # sufficient for MERCHANT_ERROR.
    if tokens & _MERCHANT_ERROR or "MERCHANT" in tokens:
        return Diagnosis.MERCHANT_ERROR
    if tokens & _INSUFFICIENT_FUNDS:
        return Diagnosis.INSUFFICIENT_FUNDS
    if tokens & _AUTHENTICATION_REQUIRED or "PAYMENT_AUTHENTICATION" in tokens:
        return Diagnosis.AUTHENTICATION_REQUIRED
    if tokens & _INSTRUMENT_INVALID:
        return Diagnosis.INSTRUMENT_INVALID
    if tokens & _TRANSIENT or "GATEWAY" in tokens or "BANK" in tokens:
        return Diagnosis.TRANSIENT_RETRYABLE
    return Diagnosis.UNKNOWN
