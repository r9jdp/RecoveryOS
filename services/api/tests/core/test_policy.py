"""Policy precedence and all four dispositions."""

from datetime import UTC, datetime, timedelta

import pytest

from services.api.app.domain.enums import (
    CaseOutcome,
    ContactDisposition,
    PaymentState,
    PaymentSurfaceType,
    PolicyDisposition,
    RecoveryActionType,
    SubscriptionState,
)
from services.api.app.services.policy import PolicyContext, evaluate_policy

NOW = datetime(2026, 8, 27, 10, tzinfo=UTC)


def context(**overrides: object) -> PolicyContext:
    values: dict[str, object] = {
        "now": NOW,
        "recovery_deadline": NOW + timedelta(days=2),
        "case_outcome": CaseOutcome.OPEN,
        "payment_state": PaymentState.FAILED,
        "subscription_state": SubscriptionState.ACTIVE,
        "contact_disposition": ContactDisposition.NOT_CONTACTED,
        "action": RecoveryActionType.OPEN_CUSTOMER_PAYMENT_SURFACE,
        "payment_surface_type": PaymentSurfaceType.SUBSCRIPTION_CARD_UPDATE,
        "amount_at_risk_paise": 149_900,
    }
    values.update(overrides)
    return PolicyContext(**values)  # type: ignore[arg-type]


def test_normal_native_surface_is_allowed() -> None:
    assert evaluate_policy(context()).disposition == PolicyDisposition.ALLOW


def test_amount_threshold_requires_manual_approval() -> None:
    decision = evaluate_policy(context(amount_at_risk_paise=500_000))
    assert decision.disposition == PolicyDisposition.REQUIRE_MANUAL_APPROVAL
    assert decision.decision_code == "AMOUNT_REQUIRES_APPROVAL"


def test_pending_gateway_retry_is_delayed_not_charged() -> None:
    decision = evaluate_policy(
        context(
            subscription_state=SubscriptionState.PENDING,
            action=RecoveryActionType.WAIT_FOR_GATEWAY_RETRY,
            payment_surface_type=None,
        )
    )
    assert decision.disposition == PolicyDisposition.DELAY
    assert decision.delay_until == NOW + timedelta(minutes=15)


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"recovery_kill_switch": True}, "RECOVERY_KILL_SWITCH_ENABLED"),
        ({"contact_disposition": ContactDisposition.OPTED_OUT}, "CUSTOMER_OPTED_OUT"),
        ({"payment_state": PaymentState.CAPTURED}, "PAYMENT_ALREADY_CAPTURED"),
        (
            {
                "subscription_state": SubscriptionState.PENDING,
                "payment_surface_type": PaymentSurfaceType.STANDARD_PAYMENT_LINK,
            },
            "GATEWAY_RETRY_ACTIVE",
        ),
    ],
)
def test_safety_rules_block_before_utility(overrides: dict[str, object], code: str) -> None:
    decision = evaluate_policy(context(**overrides))
    assert decision.disposition == PolicyDisposition.BLOCK
    assert decision.decision_code == code
