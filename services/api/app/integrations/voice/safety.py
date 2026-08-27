"""Deterministic, safety-first intent classification and call gating."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time
from enum import StrEnum


class VoiceIntent(StrEnum):
    OPT_OUT = "OPT_OUT"
    DISPUTE = "DISPUTE"
    WRONG_PERSON = "WRONG_PERSON"
    ALREADY_PAID = "ALREADY_PAID"
    CALLBACK = "CALLBACK"
    PROMISE_TO_PAY = "PROMISE_TO_PAY"
    NEED_PAYMENT_HELP = "NEED_PAYMENT_HELP"
    UNKNOWN = "UNKNOWN"


# The order is part of the policy: harm-preventing intents win even when a
# transcript also contains a lower-risk promise or callback phrase.
_INTENT_PATTERNS: tuple[tuple[VoiceIntent, tuple[str, ...]], ...] = (
    (VoiceIntent.OPT_OUT, ("stop calling", "do not call", "don't call", "opt out", "call mat")),
    (VoiceIntent.DISPUTE, ("dispute", "fraud", "not my charge", "galat charge", "scam")),
    (
        VoiceIntent.WRONG_PERSON,
        ("wrong person", "wrong number", "main woh nahi", "yeh unka number nahi"),
    ),
    (VoiceIntent.ALREADY_PAID, ("already paid", "payment kar diya", "paid already", "ho gaya")),
    (VoiceIntent.CALLBACK, ("call back", "later", "baad mein", "abhi busy")),
    (VoiceIntent.PROMISE_TO_PAY, ("will pay", "pay tomorrow", "kal pay", "kar dunga")),
    (VoiceIntent.NEED_PAYMENT_HELP, ("payment link", "card update", "help me pay", "kaise pay")),
)


def detect_voice_intent(transcript: str) -> VoiceIntent:
    normalized = re.sub(r"\s+", " ", transcript.casefold()).strip()
    for intent, phrases in _INTENT_PATTERNS:
        if any(phrase in normalized for phrase in phrases):
            return intent
    return VoiceIntent.UNKNOWN


@dataclass(frozen=True)
class VoiceSafetyContext:
    now_local: datetime
    quiet_hours_start: time | None
    quiet_hours_end: time | None
    real_calls_enabled: bool
    operator_authorized: bool
    kill_switch: bool
    destination_allowlisted: bool
    consent_verified_at: datetime | None
    opted_out_at: datetime | None
    active_calls: int
    calls_today: int
    max_duration_seconds: int


@dataclass(frozen=True)
class VoiceSafetyDecision:
    allowed: bool
    reason_code: str


def _inside_quiet_hours(value: time, start: time, end: time) -> bool:
    if start == end:
        return True
    if start < end:
        return start <= value < end
    return value >= start or value < end


def evaluate_voice_safety(context: VoiceSafetyContext) -> VoiceSafetyDecision:
    """Apply immutable platform limits before a provider call is submitted."""

    checks = (
        (not context.real_calls_enabled, "REAL_CALLS_DISABLED"),
        (not context.operator_authorized, "OPERATOR_AUTH_REQUIRED"),
        (context.kill_switch, "VOICE_KILL_SWITCH"),
        (not context.destination_allowlisted, "DESTINATION_NOT_ALLOWLISTED"),
        (context.consent_verified_at is None, "CONSENT_NOT_VERIFIED"),
        (context.opted_out_at is not None, "CUSTOMER_SUPPRESSED"),
        (context.active_calls >= 1, "CONCURRENT_CALL_LIMIT"),
        (context.calls_today >= 10, "DAILY_CALL_LIMIT"),
        (context.max_duration_seconds > 180, "DURATION_LIMIT"),
        (
            context.quiet_hours_start is not None
            and context.quiet_hours_end is not None
            and _inside_quiet_hours(
                context.now_local.timetz().replace(tzinfo=None),
                context.quiet_hours_start,
                context.quiet_hours_end,
            ),
            "QUIET_HOURS",
        ),
    )
    for blocked, code in checks:
        if blocked:
            return VoiceSafetyDecision(False, code)
    return VoiceSafetyDecision(True, "VOICE_CONTACT_ALLOWED")
