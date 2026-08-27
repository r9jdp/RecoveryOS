from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from services.api.app.domain import (
    CaseOutcome,
    ContactDisposition,
    ErrorDetail,
    PaymentState,
    PaymentSurfaceType,
    RecoveryActionType,
    RecoveryCaseKey,
    RecoveryCaseState,
    RevenueAttribution,
    SubscriptionState,
)
from services.api.app.providers import OpenPaymentSurfaceRequest, PaymentProvider

NOW = datetime(2026, 8, 27, 10, 0, tzinfo=UTC)


def make_case(**overrides: object) -> RecoveryCaseState:
    values: dict[str, object] = {
        "id": "case_fitbox_aug_2026",
        "key": {
            "merchant_id": "merchant_fitbox",
            "failed_invoice_id": "inv_fitbox_aug_2026",
            "billing_cycle_key": "2026-08",
        },
        "customer_id": "customer_fitbox_001",
        "subscription_id": "sub_fitbox_annual_001",
        "failed_payment_id": "pay_fitbox_failed_001",
        "case_outcome": CaseOutcome.OPEN,
        "payment_state": PaymentState.FAILED,
        "subscription_state": SubscriptionState.PENDING,
        "contact_disposition": ContactDisposition.NOT_CONTACTED,
        "revenue_attribution": RevenueAttribution.NONE,
        "amount_at_risk_paise": 149_900,
        "opened_at": NOW,
        "recovery_deadline": NOW + timedelta(hours=72),
    }
    values.update(overrides)
    return RecoveryCaseState.model_validate(values)


def test_case_key_is_invoice_scoped_and_deterministic() -> None:
    key = RecoveryCaseKey(
        merchant_id="merchant_fitbox",
        failed_invoice_id="inv_fitbox_aug_2026",
        billing_cycle_key="2026-08",
    )

    assert key.idempotency_key == "merchant_fitbox:inv_fitbox_aug_2026"


def test_case_key_requires_invoice_or_billing_cycle() -> None:
    with pytest.raises(ValidationError, match="failed_invoice_id or billing_cycle_key"):
        RecoveryCaseKey(merchant_id="merchant_fitbox")


def test_state_axes_can_represent_opt_out_and_late_payment_together() -> None:
    recovered = make_case(
        case_outcome=CaseOutcome.RECOVERED,
        payment_state=PaymentState.CAPTURED,
        subscription_state=SubscriptionState.PENDING,
        contact_disposition=ContactDisposition.OPTED_OUT,
        revenue_attribution=RevenueAttribution.RAZORPAY_TEST_VERIFIED,
        arrears_collected_paise=149_900,
        case_recovered=True,
        subscription_reactivated=False,
        recovered_at=NOW + timedelta(minutes=15),
    )

    assert recovered.case_recovered is True
    assert recovered.subscription_reactivated is False
    assert recovered.contact_disposition == ContactDisposition.OPTED_OUT


def test_captured_payment_requires_collected_amount_and_attribution() -> None:
    with pytest.raises(ValidationError, match="CAPTURED payment requires"):
        make_case(payment_state=PaymentState.CAPTURED)


def test_fixed_action_set_does_not_expose_generic_retry_or_payment_link() -> None:
    actions = {action.value for action in RecoveryActionType}

    assert actions == {
        "WAIT_FOR_GATEWAY_RETRY",
        "OPEN_CUSTOMER_PAYMENT_SURFACE",
        "START_VOICE",
        "SEND_TO_CUSTOMER_AGENT",
        "ESCALATE_TO_HUMAN",
        "STOP",
    }
    assert "RETRY_LATER" not in actions
    assert "SEND_PAYMENT_LINK" not in actions


def test_standard_payment_link_requires_bounded_reference_and_notes() -> None:
    common = {
        "idempotency_key": "merchant_fitbox:inv_fitbox_aug_2026:surface",
        "case_id": "case_fitbox_aug_2026",
        "merchant_id": "merchant_fitbox",
        "customer_id": "customer_fitbox_001",
        "subscription_id": "sub_fitbox_annual_001",
        "failed_invoice_id": "inv_fitbox_aug_2026",
        "surface_type": PaymentSurfaceType.STANDARD_PAYMENT_LINK,
        "exact_amount_paise": 149_900,
        "currency": "INR",
        "recovery_deadline": NOW + timedelta(hours=72),
    }

    with pytest.raises(ValidationError, match="reference_id"):
        OpenPaymentSurfaceRequest.model_validate(common)

    request = OpenPaymentSurfaceRequest.model_validate(
        {
            **common,
            "expires_at": NOW + timedelta(hours=24),
            "reference_id": "rc_fitbox_aug_2026",
            "notes": {
                "case_id": "case_fitbox_aug_2026",
                "invoice_id": "inv_fitbox_aug_2026",
            },
        }
    )

    assert request.accept_partial is False
    assert request.notify_sms is False
    assert request.notify_email is False

    with pytest.raises(ValidationError, match="cannot expire after recovery_deadline"):
        OpenPaymentSurfaceRequest.model_validate(
            {
                **common,
                "expires_at": NOW + timedelta(hours=73),
                "reference_id": "rc_fitbox_aug_2026",
                "notes": {
                    "case_id": "case_fitbox_aug_2026",
                    "invoice_id": "inv_fitbox_aug_2026",
                },
            }
        )


def test_payment_provider_does_not_define_an_unsafe_charge_method() -> None:
    assert hasattr(PaymentProvider, "open_customer_payment_surface")
    assert hasattr(PaymentProvider, "fetch_payment_snapshot")
    assert not hasattr(PaymentProvider, "retry_payment")
    assert not hasattr(PaymentProvider, "charge_payment")


def test_error_codes_are_machine_stable() -> None:
    detail = ErrorDetail(code="CASE_ALREADY_RECOVERED", message="Case is terminal")
    assert detail.code == "CASE_ALREADY_RECOVERED"

    with pytest.raises(ValidationError):
        ErrorDetail(code="not-stable", message="Bad code")
