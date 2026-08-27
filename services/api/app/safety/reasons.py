"""Stable, structured safety decision results for APIs and audit events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from services.api.app.domain.enums import PolicyDisposition
from services.api.app.domain.models import PolicyDecision


class SafetyReasonCode(StrEnum):
    """Machine-stable codes; user-facing copy may evolve independently."""

    GLOBAL_KILL_SWITCH_ENABLED = "GLOBAL_KILL_SWITCH_ENABLED"
    MERCHANT_KILL_SWITCH_ENABLED = "MERCHANT_KILL_SWITCH_ENABLED"
    CASE_TERMINAL = "CASE_TERMINAL"
    PAYMENT_ALREADY_CAPTURED = "PAYMENT_ALREADY_CAPTURED"
    CUSTOMER_OPTED_OUT = "CUSTOMER_OPTED_OUT"
    WRONG_PERSON = "WRONG_PERSON"
    CUSTOMER_DISPUTE = "CUSTOMER_DISPUTE"
    CUSTOMER_REPORTS_ALREADY_PAID = "CUSTOMER_REPORTS_ALREADY_PAID"
    RECOVERY_WINDOW_EXPIRED = "RECOVERY_WINDOW_EXPIRED"
    GATEWAY_RETRY_ACTIVE = "GATEWAY_RETRY_ACTIVE"
    WAIT_FOR_PROVIDER_RETRY = "WAIT_FOR_PROVIDER_RETRY"
    CONTACT_LIMIT_REACHED = "CONTACT_LIMIT_REACHED"
    QUIET_HOURS_ACTIVE = "QUIET_HOURS_ACTIVE"
    ACTION_REQUIRES_APPROVAL = "ACTION_REQUIRES_APPROVAL"
    AMOUNT_REQUIRES_APPROVAL = "AMOUNT_REQUIRES_APPROVAL"
    WITHIN_RECOVERY_WINDOW = "WITHIN_RECOVERY_WINDOW"
    NO_SUPPRESSION = "NO_SUPPRESSION"


@dataclass(frozen=True, slots=True)
class SafetyReason:
    """A reason suitable for audit storage and direct API serialization."""

    code: SafetyReasonCode
    message: str
    field: str | None = None

    def to_api_dict(self) -> dict[str, str]:
        result = {"code": self.code.value, "message": self.message}
        if self.field is not None:
            result["field"] = self.field
        return result


@dataclass(frozen=True, slots=True)
class SafetyDecision:
    """Policy result with structured reasons and a frozen contract adapter."""

    disposition: PolicyDisposition
    decision_code: SafetyReasonCode
    reasons: tuple[SafetyReason, ...]
    policy_version: str
    delay_until: datetime | None = None

    def __post_init__(self) -> None:
        if not self.reasons:
            raise ValueError("at least one safety reason is required")
        if self.reasons[0].code != self.decision_code:
            raise ValueError("decision_code must match the first structured reason")
        is_delay = self.disposition == PolicyDisposition.DELAY
        if is_delay != (self.delay_until is not None):
            raise ValueError("delay_until is required only for DELAY decisions")

    def to_contract(self) -> PolicyDecision:
        """Convert without changing the Phase 1 shared schema."""

        return PolicyDecision(
            disposition=self.disposition,
            decision_code=self.decision_code.value,
            reason_codes=[reason.code.value for reason in self.reasons],
            reasons=[reason.message for reason in self.reasons],
            policy_version=self.policy_version,
            delay_until=self.delay_until,
        )

    def to_api_dict(self) -> dict[str, Any]:
        """Return a JSON-encoder-ready representation with stable keys."""

        return {
            "disposition": self.disposition.value,
            "decision_code": self.decision_code.value,
            "reasons": [reason.to_api_dict() for reason in self.reasons],
            "policy_version": self.policy_version,
            "delay_until": self.delay_until.isoformat() if self.delay_until else None,
        }
