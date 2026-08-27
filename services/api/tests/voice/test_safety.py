from datetime import UTC, datetime, time

import pytest

from services.api.app.integrations.voice.safety import (
    VoiceIntent,
    VoiceSafetyContext,
    detect_voice_intent,
    evaluate_voice_safety,
)


def allowed_context(**overrides: object) -> VoiceSafetyContext:
    values: dict[str, object] = {
        "now_local": datetime(2026, 8, 28, 14, tzinfo=UTC),
        "quiet_hours_start": time(20),
        "quiet_hours_end": time(9),
        "real_calls_enabled": True,
        "operator_authorized": True,
        "kill_switch": False,
        "destination_allowlisted": True,
        "consent_verified_at": datetime(2026, 8, 1, tzinfo=UTC),
        "opted_out_at": None,
        "active_calls": 0,
        "calls_today": 0,
        "max_duration_seconds": 180,
    }
    values.update(overrides)
    return VoiceSafetyContext(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"real_calls_enabled": False}, "REAL_CALLS_DISABLED"),
        ({"operator_authorized": False}, "OPERATOR_AUTH_REQUIRED"),
        ({"kill_switch": True}, "VOICE_KILL_SWITCH"),
        ({"destination_allowlisted": False}, "DESTINATION_NOT_ALLOWLISTED"),
        ({"consent_verified_at": None}, "CONSENT_NOT_VERIFIED"),
        ({"opted_out_at": datetime(2026, 8, 2, tzinfo=UTC)}, "CUSTOMER_SUPPRESSED"),
        ({"active_calls": 1}, "CONCURRENT_CALL_LIMIT"),
        ({"calls_today": 10}, "DAILY_CALL_LIMIT"),
        ({"max_duration_seconds": 181}, "DURATION_LIMIT"),
        ({"now_local": datetime(2026, 8, 28, 22, tzinfo=UTC)}, "QUIET_HOURS"),
    ],
)
def test_voice_safety_blocks_every_platform_guardrail(
    overrides: dict[str, object], expected: str
) -> None:
    assert evaluate_voice_safety(allowed_context(**overrides)).reason_code == expected


def test_voice_safety_allows_only_a_fully_guarded_call() -> None:
    assert evaluate_voice_safety(allowed_context()).reason_code == "VOICE_CONTACT_ALLOWED"


def test_harm_preventing_intent_precedes_payment_promise() -> None:
    assert detect_voice_intent("Please stop calling, main kal pay kar dunga") == VoiceIntent.OPT_OUT
    assert detect_voice_intent("This is fraud but call me later") == VoiceIntent.DISPUTE


def test_hinglish_intents_are_supported() -> None:
    assert detect_voice_intent("Payment kar diya, ho gaya") == VoiceIntent.ALREADY_PAID
    assert detect_voice_intent("Abhi busy, baad mein") == VoiceIntent.CALLBACK
