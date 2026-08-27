"""Safety policy decisions, precedence, and contract adaptation."""

from datetime import UTC, datetime, time, timedelta

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
from services.api.app.safety import (
    SafetyPolicyConfig,
    SafetyPolicyContext,
    evaluate_safety_policy,
)
from services.api.app.safety.reasons import SafetyReasonCode

NOW = datetime(2026, 8, 27, 10, tzinfo=UTC)


def context(**overrides: object) -> SafetyPolicyContext:
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
    return SafetyPolicyContext(**values)  # type: ignore[arg-type]


def config(**overrides: object) -> SafetyPolicyConfig:
    values: dict[str, object] = {
        "quiet_hours_start": time(20),
        "quiet_hours_end": time(9),
        "manual_approval_above_paise": 500_000,
    }
    values.update(overrides)
    return SafetyPolicyConfig(**values)  # type: ignore[arg-type]


def test_native_surface_is_allowed_with_structured_reasons() -> None:
    decision = evaluate_safety_policy(context(), config())

    assert decision.disposition == PolicyDisposition.ALLOW
    assert decision.decision_code == SafetyReasonCode.WITHIN_RECOVERY_WINDOW
    assert [reason.code for reason in decision.reasons] == [
        SafetyReasonCode.WITHIN_RECOVERY_WINDOW,
        SafetyReasonCode.NO_SUPPRESSION,
    ]
    assert decision.to_api_dict() == {
        "disposition": "ALLOW",
        "decision_code": "WITHIN_RECOVERY_WINDOW",
        "reasons": [
            {
                "code": "WITHIN_RECOVERY_WINDOW",
                "message": "The case is within its configured recovery window.",
                "field": "recovery_deadline",
            },
            {
                "code": "NO_SUPPRESSION",
                "message": "No higher-priority suppression applies to this action.",
            },
        ],
        "policy_version": "recovery-safety.v2",
        "delay_until": None,
    }


@pytest.mark.parametrize(
    ("policy_overrides", "reason"),
    [
        ({"global_kill_switch": True}, SafetyReasonCode.GLOBAL_KILL_SWITCH_ENABLED),
        ({"merchant_kill_switch": True}, SafetyReasonCode.MERCHANT_KILL_SWITCH_ENABLED),
    ],
)
def test_kill_switches_block_before_approval(
    policy_overrides: dict[str, object], reason: SafetyReasonCode
) -> None:
    decision = evaluate_safety_policy(
        context(amount_at_risk_paise=900_000), config(**policy_overrides)
    )

    assert decision.disposition == PolicyDisposition.BLOCK
    assert decision.decision_code == reason


@pytest.mark.parametrize(
    ("disposition", "reason"),
    [
        (ContactDisposition.OPTED_OUT, SafetyReasonCode.CUSTOMER_OPTED_OUT),
        (ContactDisposition.WRONG_PERSON, SafetyReasonCode.WRONG_PERSON),
        (ContactDisposition.DISPUTE, SafetyReasonCode.CUSTOMER_DISPUTE),
        (
            ContactDisposition.ALREADY_PAID,
            SafetyReasonCode.CUSTOMER_REPORTS_ALREADY_PAID,
        ),
    ],
)
def test_customer_suppressions_block_before_quiet_hours_and_approval(
    disposition: ContactDisposition, reason: SafetyReasonCode
) -> None:
    decision = evaluate_safety_policy(
        context(
            now=datetime(2026, 8, 27, 18, tzinfo=UTC),
            contact_disposition=disposition,
            action=RecoveryActionType.START_VOICE,
            payment_surface_type=None,
            amount_at_risk_paise=900_000,
        ),
        config(),
    )

    assert decision.disposition == PolicyDisposition.BLOCK
    assert decision.decision_code == reason


def test_authoritative_capture_blocks_before_customer_report() -> None:
    decision = evaluate_safety_policy(
        context(
            payment_state=PaymentState.CAPTURED,
            contact_disposition=ContactDisposition.ALREADY_PAID,
        ),
        config(),
    )

    assert decision.decision_code == SafetyReasonCode.PAYMENT_ALREADY_CAPTURED


def test_stop_and_escalate_remain_available_under_suppression_and_kill_switch() -> None:
    unsafe_context = {
        "contact_disposition": ContactDisposition.OPTED_OUT,
        "payment_state": PaymentState.CAPTURED,
        "amount_at_risk_paise": 900_000,
    }
    safety_config = config(global_kill_switch=True, merchant_kill_switch=True)

    for action in (RecoveryActionType.STOP, RecoveryActionType.ESCALATE_TO_HUMAN):
        decision = evaluate_safety_policy(
            context(action=action, payment_surface_type=None, **unsafe_context), safety_config
        )
        assert decision.disposition == PolicyDisposition.ALLOW


def test_expired_window_blocks_recovery_execution() -> None:
    decision = evaluate_safety_policy(
        context(now=NOW + timedelta(days=3)),
        config(),
    )

    assert decision.disposition == PolicyDisposition.BLOCK
    assert decision.decision_code == SafetyReasonCode.RECOVERY_WINDOW_EXPIRED


def test_pending_subscription_blocks_standard_link_only_during_active_retries() -> None:
    pending_link = context(
        subscription_state=SubscriptionState.PENDING,
        payment_surface_type=PaymentSurfaceType.STANDARD_PAYMENT_LINK,
        active_gateway_retries=True,
    )
    decision = evaluate_safety_policy(pending_link, config())

    assert decision.disposition == PolicyDisposition.BLOCK
    assert decision.decision_code == SafetyReasonCode.GATEWAY_RETRY_ACTIVE

    allowed = evaluate_safety_policy(
        context(
            subscription_state=SubscriptionState.PENDING,
            payment_surface_type=PaymentSurfaceType.STANDARD_PAYMENT_LINK,
            active_gateway_retries=False,
        ),
        config(),
    )
    assert allowed.disposition == PolicyDisposition.ALLOW


def test_pending_retry_wait_is_delayed_and_capped_by_deadline() -> None:
    deadline = NOW + timedelta(minutes=7)
    decision = evaluate_safety_policy(
        context(
            recovery_deadline=deadline,
            subscription_state=SubscriptionState.PENDING,
            action=RecoveryActionType.WAIT_FOR_GATEWAY_RETRY,
            payment_surface_type=None,
            active_gateway_retries=True,
        ),
        config(),
    )

    assert decision.disposition == PolicyDisposition.DELAY
    assert decision.decision_code == SafetyReasonCode.WAIT_FOR_PROVIDER_RETRY
    assert decision.delay_until == deadline


def test_contact_limit_delays_until_reset() -> None:
    reset_at = NOW + timedelta(hours=4)
    decision = evaluate_safety_policy(
        context(
            action=RecoveryActionType.START_VOICE,
            payment_surface_type=None,
            contact_attempts_in_window=3,
            contact_limit_resets_at=reset_at,
        ),
        config(),
    )

    assert decision.disposition == PolicyDisposition.DELAY
    assert decision.decision_code == SafetyReasonCode.CONTACT_LIMIT_REACHED
    assert decision.delay_until == reset_at


def test_contact_limit_blocks_without_safe_reset() -> None:
    decision = evaluate_safety_policy(
        context(
            action=RecoveryActionType.SEND_TO_CUSTOMER_AGENT,
            payment_surface_type=None,
            contact_attempts_in_window=3,
            contact_limit_resets_at=NOW + timedelta(days=3),
        ),
        config(),
    )

    assert decision.disposition == PolicyDisposition.BLOCK
    assert decision.decision_code == SafetyReasonCode.CONTACT_LIMIT_REACHED


@pytest.mark.parametrize(
    ("amount_paise", "approval_actions", "expected_reason"),
    [
        (149_900, frozenset({RecoveryActionType.START_VOICE}), "ACTION_REQUIRES_APPROVAL"),
        (500_000, frozenset(), "AMOUNT_REQUIRES_APPROVAL"),
    ],
)
def test_action_or_amount_can_independently_require_manual_approval(
    amount_paise: int,
    approval_actions: frozenset[RecoveryActionType],
    expected_reason: str,
) -> None:
    decision = evaluate_safety_policy(
        context(
            action=RecoveryActionType.START_VOICE,
            payment_surface_type=None,
            amount_at_risk_paise=amount_paise,
        ),
        config(manual_approval_actions=approval_actions),
    )

    assert decision.disposition == PolicyDisposition.REQUIRE_MANUAL_APPROVAL
    assert decision.to_contract().reason_codes == [expected_reason]


def test_action_and_amount_reasons_are_both_preserved() -> None:
    decision = evaluate_safety_policy(
        context(
            action=RecoveryActionType.START_VOICE,
            payment_surface_type=None,
            amount_at_risk_paise=500_000,
        ),
        config(manual_approval_actions=frozenset({RecoveryActionType.START_VOICE})),
    )

    assert decision.disposition == PolicyDisposition.REQUIRE_MANUAL_APPROVAL
    assert [reason.code for reason in decision.reasons] == [
        SafetyReasonCode.ACTION_REQUIRES_APPROVAL,
        SafetyReasonCode.AMOUNT_REQUIRES_APPROVAL,
    ]
    contract = decision.to_contract()
    assert contract.reason_codes == [
        "ACTION_REQUIRES_APPROVAL",
        "AMOUNT_REQUIRES_APPROVAL",
    ]


def test_context_rejects_float_money_and_surface_mismatch() -> None:
    with pytest.raises(ValueError, match="amount_at_risk_paise"):
        context(amount_at_risk_paise=-1)
    with pytest.raises(ValueError, match="payment_surface_type"):
        context(action=RecoveryActionType.START_VOICE)


def test_policy_configuration_validates_timezone_and_quiet_interval() -> None:
    with pytest.raises(ValueError, match="unknown IANA timezone"):
        config(merchant_timezone="Mars/Olympus_Mons")
    with pytest.raises(ValueError, match="cannot be equal"):
        config(quiet_hours_start=time(9), quiet_hours_end=time(9))
