"""Merchant-local quiet hours, including midnight and DST transitions."""

from datetime import UTC, datetime, time

from services.api.app.domain.enums import PolicyDisposition, RecoveryActionType
from services.api.app.safety import (
    SafetyPolicyConfig,
    SafetyPolicyContext,
    evaluate_safety_policy,
)
from services.api.app.safety.policy import quiet_hours_delay_until
from services.api.tests.safety.test_policy import context


def test_midnight_wrapping_quiet_hours_use_merchant_timezone() -> None:
    delay_until = quiet_hours_delay_until(
        datetime(2026, 8, 27, 16, tzinfo=UTC),  # 21:30 Asia/Kolkata
        timezone_name="Asia/Kolkata",
        start=time(20),
        end=time(9),
    )

    assert delay_until == datetime(2026, 8, 28, 3, 30, tzinfo=UTC)


def test_quiet_hours_are_inactive_at_end_boundary() -> None:
    assert (
        quiet_hours_delay_until(
            datetime(2026, 8, 28, 3, 30, tzinfo=UTC),
            timezone_name="Asia/Kolkata",
            start=time(20),
            end=time(9),
        )
        is None
    )


def test_non_wrapping_quiet_interval() -> None:
    delay_until = quiet_hours_delay_until(
        datetime(2026, 8, 27, 4, 30, tzinfo=UTC),  # 10:00 Asia/Kolkata
        timezone_name="Asia/Kolkata",
        start=time(9),
        end=time(17),
    )

    assert delay_until == datetime(2026, 8, 27, 11, 30, tzinfo=UTC)


def test_spring_forward_gap_uses_first_valid_instant_after_quiet_end() -> None:
    delay_until = quiet_hours_delay_until(
        datetime(2026, 3, 8, 6, 30, tzinfo=UTC),  # 01:30 EST
        timezone_name="America/New_York",
        start=time(20),
        end=time(2, 30),  # nonexistent on spring transition day
    )

    assert delay_until == datetime(2026, 3, 8, 7, 0, tzinfo=UTC)  # 03:00 EDT


def test_fall_back_overlap_uses_later_quiet_end_occurrence() -> None:
    delay_until = quiet_hours_delay_until(
        datetime(2026, 11, 1, 4, 30, tzinfo=UTC),  # 00:30 EDT
        timezone_name="America/New_York",
        start=time(20),
        end=time(1, 30),  # occurs twice
    )

    assert delay_until == datetime(2026, 11, 1, 6, 30, tzinfo=UTC)  # 01:30 EST


def test_policy_delays_outreach_and_serializes_utc_timestamp() -> None:
    now = datetime(2026, 8, 27, 16, tzinfo=UTC)
    policy_context: SafetyPolicyContext = context(
        now=now,
        recovery_deadline=datetime(2026, 8, 29, tzinfo=UTC),
        action=RecoveryActionType.START_VOICE,
        payment_surface_type=None,
    )
    decision = evaluate_safety_policy(policy_context, SafetyPolicyConfig())

    assert decision.disposition == PolicyDisposition.DELAY
    assert decision.to_api_dict()["delay_until"] == "2026-08-28T03:30:00+00:00"


def test_quiet_hours_block_when_they_outlast_recovery_window() -> None:
    now = datetime(2026, 8, 27, 16, tzinfo=UTC)
    decision = evaluate_safety_policy(
        context(
            now=now,
            recovery_deadline=datetime(2026, 8, 27, 18, tzinfo=UTC),
            action=RecoveryActionType.START_VOICE,
            payment_surface_type=None,
        ),
        SafetyPolicyConfig(),
    )

    assert decision.disposition == PolicyDisposition.BLOCK
