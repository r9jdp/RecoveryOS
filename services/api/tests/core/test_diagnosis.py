"""Evidence correlation and deterministic diagnosis tests."""

import pytest

from services.api.app.domain.enums import Diagnosis, PaymentState
from services.api.app.services.diagnosis import DiagnosisEvidence, diagnose_failure


@pytest.mark.parametrize(
    ("error_code", "error_reason", "expected"),
    [
        (
            "BAD_REQUEST_PAYMENT_CARD_INSUFFICIENT_BALANCE",
            None,
            Diagnosis.INSUFFICIENT_FUNDS,
        ),
        ("BAD_REQUEST_PAYMENT_AUTHENTICATION_FAILED", None, Diagnosis.AUTHENTICATION_REQUIRED),
        ("BAD_REQUEST_PAYMENT_CARD_EXPIRED", None, Diagnosis.INSTRUMENT_INVALID),
        ("GATEWAY_ERROR", None, Diagnosis.TRANSIENT_RETRYABLE),
        ("MERCHANT_CONFIGURATION_ERROR", None, Diagnosis.MERCHANT_ERROR),
        ("RISK_CHECK_FAILED", None, Diagnosis.RISK_OR_COMPLIANCE_BLOCK),
        (None, "incorrect_otp", Diagnosis.AUTHENTICATION_REQUIRED),
        (None, "unclassified", Diagnosis.UNKNOWN),
    ],
)
def test_correlated_payment_failure_is_classified(
    error_code: str | None,
    error_reason: str | None,
    expected: Diagnosis,
) -> None:
    evidence = DiagnosisEvidence(
        payment_state=PaymentState.FAILED,
        event_type="payment.failed",
        invoice_correlated=True,
        subscription_correlated=True,
        error_code=error_code,
        error_reason=error_reason,
    )

    assert diagnose_failure(evidence) == expected


@pytest.mark.parametrize(
    "evidence",
    [
        DiagnosisEvidence(
            payment_state=PaymentState.FAILED,
            event_type="subscription.pending",
            invoice_correlated=True,
            subscription_correlated=True,
            error_reason="incorrect_otp",
        ),
        DiagnosisEvidence(
            payment_state=PaymentState.FAILED,
            event_type="payment.failed",
            invoice_correlated=False,
            subscription_correlated=True,
            error_reason="incorrect_otp",
        ),
        DiagnosisEvidence(
            payment_state=PaymentState.CAPTURED,
            event_type="payment.failed",
            invoice_correlated=True,
            subscription_correlated=True,
            error_reason="incorrect_otp",
        ),
    ],
)
def test_missing_or_contradictory_correlation_is_unknown(
    evidence: DiagnosisEvidence,
) -> None:
    assert diagnose_failure(evidence) == Diagnosis.UNKNOWN
