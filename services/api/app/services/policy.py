"""Deterministic action policy with explicit allow/block/delay/approval states."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from services.api.app.domain.enums import (
    CaseOutcome,
    ContactDisposition,
    PaymentState,
    PaymentSurfaceType,
    PolicyDisposition,
    RecoveryActionType,
    SubscriptionState,
)
from services.api.app.domain.models import PolicyDecision


@dataclass(frozen=True, slots=True)
class PolicyContext:
    now: datetime
    recovery_deadline: datetime
    case_outcome: CaseOutcome
    payment_state: PaymentState
    subscription_state: SubscriptionState
    contact_disposition: ContactDisposition
    action: RecoveryActionType
    payment_surface_type: PaymentSurfaceType | None
    amount_at_risk_paise: int
    require_approval_above_paise: int = 500_000
    recovery_kill_switch: bool = False
    policy_version: str = "fitbox-demo.v1"


def _decision(
    context: PolicyContext,
    disposition: PolicyDisposition,
    code: str,
    reason: str,
    *,
    delay_until: datetime | None = None,
) -> PolicyDecision:
    return PolicyDecision(
        disposition=disposition,
        decision_code=code,
        reason_codes=[code],
        reasons=[reason],
        policy_version=context.policy_version,
        delay_until=delay_until,
    )


def evaluate_policy(context: PolicyContext) -> PolicyDecision:
    """Apply highest-severity safety rules before utility or channel preferences."""

    if context.recovery_kill_switch:
        return _decision(
            context,
            PolicyDisposition.BLOCK,
            "RECOVERY_KILL_SWITCH_ENABLED",
            "Recovery actions are disabled by the operator kill switch.",
        )
    if context.case_outcome != CaseOutcome.OPEN:
        return _decision(
            context,
            PolicyDisposition.BLOCK,
            "CASE_TERMINAL",
            "The recovery case is already terminal.",
        )
    if context.payment_state == PaymentState.CAPTURED:
        return _decision(
            context,
            PolicyDisposition.BLOCK,
            "PAYMENT_ALREADY_CAPTURED",
            "Authoritative payment state already shows captured funds.",
        )
    suppression_codes = {
        ContactDisposition.OPTED_OUT: ("CUSTOMER_OPTED_OUT", "Customer opted out of outreach."),
        ContactDisposition.WRONG_PERSON: ("WRONG_PERSON", "The contact is not the customer."),
        ContactDisposition.DISPUTE: ("CUSTOMER_DISPUTE", "The customer disputes the charge."),
        ContactDisposition.ALREADY_PAID: (
            "CUSTOMER_REPORTS_ALREADY_PAID",
            "Customer-reported payment requires reconciliation before action.",
        ),
    }
    if context.contact_disposition in suppression_codes:
        code, reason = suppression_codes[context.contact_disposition]
        return _decision(context, PolicyDisposition.BLOCK, code, reason)
    if context.now >= context.recovery_deadline:
        return _decision(
            context,
            PolicyDisposition.BLOCK,
            "RECOVERY_WINDOW_EXPIRED",
            "The configured recovery deadline has passed.",
        )
    if (
        context.action == RecoveryActionType.OPEN_CUSTOMER_PAYMENT_SURFACE
        and context.payment_surface_type == PaymentSurfaceType.STANDARD_PAYMENT_LINK
        and context.subscription_state == SubscriptionState.PENDING
    ):
        return _decision(
            context,
            PolicyDisposition.BLOCK,
            "GATEWAY_RETRY_ACTIVE",
            "Standalone collection is blocked while subscription gateway retries are active.",
        )
    if (
        context.action == RecoveryActionType.WAIT_FOR_GATEWAY_RETRY
        and context.subscription_state == SubscriptionState.PENDING
    ):
        delay_until = min(context.now + timedelta(minutes=15), context.recovery_deadline)
        return _decision(
            context,
            PolicyDisposition.DELAY,
            "WAIT_FOR_PROVIDER_RETRY",
            "Razorpay owns the retry for a pending subscription.",
            delay_until=delay_until,
        )
    if context.amount_at_risk_paise >= context.require_approval_above_paise:
        return _decision(
            context,
            PolicyDisposition.REQUIRE_MANUAL_APPROVAL,
            "AMOUNT_REQUIRES_APPROVAL",
            "The amount at risk meets the merchant's manual approval threshold.",
        )
    return PolicyDecision(
        disposition=PolicyDisposition.ALLOW,
        decision_code="POLICY_ALLOWED",
        reason_codes=["WITHIN_RECOVERY_WINDOW", "NO_SUPPRESSION"],
        reasons=["Case is within its recovery window.", "Customer has no suppression."],
        policy_version=context.policy_version,
    )
