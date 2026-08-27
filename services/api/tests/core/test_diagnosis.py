"""Evidence correlation and deterministic diagnosis tests."""

import json
from pathlib import Path

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


def test_payment_failed_fixture_prefers_specific_authentication_evidence() -> None:
    fixture_path = Path(__file__).parents[1] / "fixtures" / "razorpay" / "payment.failed.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    payment = fixture["payload"]["payment"]["entity"]

    evidence = DiagnosisEvidence(
        payment_state=PaymentState.FAILED,
        event_type=fixture["event"],
        invoice_correlated=payment["invoice_id"] is not None,
        subscription_correlated=payment["notes"]["subscription_id"] is not None,
        error_code=payment["error_code"],
        error_source=payment["error_source"],
        error_step=payment["error_step"],
        error_reason=payment["error_reason"],
    )

    assert {
        evidence.error_code,
        evidence.error_source,
        evidence.error_step,
        evidence.error_reason,
    } == {
        "BAD_REQUEST_ERROR",
        "customer",
        "payment_authentication",
        "incorrect_otp",
    }
    assert diagnose_failure(evidence) == Diagnosis.AUTHENTICATION_REQUIRED


def test_explicit_merchant_evidence_remains_merchant_error() -> None:
    evidence = DiagnosisEvidence(
        payment_state=PaymentState.FAILED,
        event_type="payment.failed",
        invoice_correlated=True,
        subscription_correlated=True,
        error_code="BAD_REQUEST_ERROR",
        error_source="merchant",
        error_step="payment_initialization",
        error_reason="invalid_merchant_configuration",
    )

    assert diagnose_failure(evidence) == Diagnosis.MERCHANT_ERROR


def test_generic_bad_request_without_specific_evidence_is_unknown() -> None:
    evidence = DiagnosisEvidence(
        payment_state=PaymentState.FAILED,
        event_type="payment.failed",
        invoice_correlated=True,
        subscription_correlated=True,
        error_code="BAD_REQUEST_ERROR",
    )

    assert diagnose_failure(evidence) == Diagnosis.UNKNOWN
