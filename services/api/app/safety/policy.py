"""Pure Phase 2 policy evaluation for customer and payment safety."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from services.api.app.domain.enums import (
    CaseOutcome,
    ContactDisposition,
    PaymentState,
    PaymentSurfaceType,
    PolicyDisposition,
    RecoveryActionType,
    SubscriptionState,
)

from .reasons import SafetyDecision, SafetyReason, SafetyReasonCode

_CUSTOMER_CONTACT_ACTIONS = frozenset(
    {
        RecoveryActionType.OPEN_CUSTOMER_PAYMENT_SURFACE,
        RecoveryActionType.START_VOICE,
        RecoveryActionType.SEND_TO_CUSTOMER_AGENT,
    }
)
_OUTREACH_ACTIONS = frozenset(
    {RecoveryActionType.START_VOICE, RecoveryActionType.SEND_TO_CUSTOMER_AGENT}
)
_TERMINAL_CONTROL_ACTIONS = frozenset(
    {RecoveryActionType.STOP, RecoveryActionType.ESCALATE_TO_HUMAN}
)


@dataclass(frozen=True, slots=True)
class SafetyPolicyConfig:
    """Merchant policy values supplied by an API/repository integration layer."""

    merchant_timezone: str = "Asia/Kolkata"
    quiet_hours_start: time | None = time(20, 0)
    quiet_hours_end: time | None = time(9, 0)
    max_contacts_per_window: int | None = 3
    manual_approval_actions: frozenset[RecoveryActionType] = field(default_factory=frozenset)
    manual_approval_above_paise: int | None = 500_000
    global_kill_switch: bool = False
    merchant_kill_switch: bool = False
    gateway_retry_delay: timedelta = timedelta(minutes=15)
    policy_version: str = "recovery-safety.v2"

    def __post_init__(self) -> None:
        try:
            ZoneInfo(self.merchant_timezone)
        except ZoneInfoNotFoundError as error:
            raise ValueError(f"unknown IANA timezone: {self.merchant_timezone}") from error
        if (self.quiet_hours_start is None) != (self.quiet_hours_end is None):
            raise ValueError("quiet-hours start and end must both be configured or both disabled")
        if self.quiet_hours_start is not None and self.quiet_hours_start == self.quiet_hours_end:
            raise ValueError("quiet-hours start and end cannot be equal")
        if self.max_contacts_per_window is not None and self.max_contacts_per_window < 1:
            raise ValueError("max_contacts_per_window must be positive or disabled")
        if self.manual_approval_above_paise is not None and self.manual_approval_above_paise < 0:
            raise ValueError("manual approval threshold cannot be negative")
        if self.gateway_retry_delay <= timedelta(0):
            raise ValueError("gateway_retry_delay must be positive")


@dataclass(frozen=True, slots=True)
class SafetyPolicyContext:
    """Complete deterministic input; no clock, database, or provider access is hidden."""

    now: datetime
    recovery_deadline: datetime
    case_outcome: CaseOutcome
    payment_state: PaymentState
    subscription_state: SubscriptionState
    contact_disposition: ContactDisposition
    action: RecoveryActionType
    payment_surface_type: PaymentSurfaceType | None
    amount_at_risk_paise: int
    active_gateway_retries: bool = False
    contact_attempts_in_window: int = 0
    contact_limit_resets_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_aware("now", self.now)
        _require_aware("recovery_deadline", self.recovery_deadline)
        if self.contact_limit_resets_at is not None:
            _require_aware("contact_limit_resets_at", self.contact_limit_resets_at)
        if isinstance(self.amount_at_risk_paise, bool) or self.amount_at_risk_paise < 0:
            raise ValueError("amount_at_risk_paise must be a non-negative integer")
        if isinstance(self.contact_attempts_in_window, bool) or self.contact_attempts_in_window < 0:
            raise ValueError("contact_attempts_in_window must be a non-negative integer")
        opens_surface = self.action == RecoveryActionType.OPEN_CUSTOMER_PAYMENT_SURFACE
        if opens_surface != (self.payment_surface_type is not None):
            raise ValueError(
                "payment_surface_type is required only for OPEN_CUSTOMER_PAYMENT_SURFACE"
            )


def _require_aware(field_name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _reason(code: SafetyReasonCode, message: str, field_name: str | None = None) -> SafetyReason:
    return SafetyReason(code=code, message=message, field=field_name)


def _decision(
    config: SafetyPolicyConfig,
    disposition: PolicyDisposition,
    *reasons: SafetyReason,
    delay_until: datetime | None = None,
) -> SafetyDecision:
    return SafetyDecision(
        disposition=disposition,
        decision_code=reasons[0].code,
        reasons=tuple(reasons),
        policy_version=config.policy_version,
        delay_until=delay_until.astimezone(UTC) if delay_until else None,
    )


def _valid_local_candidates(naive: datetime, timezone: ZoneInfo) -> tuple[datetime, ...]:
    candidates: dict[datetime, datetime] = {}
    for fold in (0, 1):
        candidate = naive.replace(tzinfo=timezone, fold=fold)
        roundtrip = candidate.astimezone(UTC).astimezone(timezone)
        if roundtrip.replace(tzinfo=None) == naive:
            candidates[candidate.astimezone(UTC)] = candidate
    return tuple(candidates[key] for key in sorted(candidates))


def _resolve_quiet_end(local_date: date, end: time, timezone: ZoneInfo) -> datetime:
    """Resolve a wall time, moving through gaps and choosing the later overlap instant."""

    naive = datetime.combine(local_date, end)
    for minute_offset in range(181):
        candidates = _valid_local_candidates(naive + timedelta(minutes=minute_offset), timezone)
        if candidates:
            return max(candidates, key=lambda candidate: candidate.astimezone(UTC))
    raise ValueError("quiet-hours end could not be resolved within a three-hour DST window")


def quiet_hours_delay_until(
    now: datetime,
    *,
    timezone_name: str,
    start: time,
    end: time,
) -> datetime | None:
    """Return the UTC end instant when `now` is inside the local quiet interval."""

    _require_aware("now", now)
    timezone = ZoneInfo(timezone_name)
    local_now = now.astimezone(timezone)
    local_time = local_now.timetz().replace(tzinfo=None)
    if start < end:
        if not start <= local_time < end:
            return None
        end_date = local_now.date()
    else:
        if local_time >= start:
            end_date = local_now.date() + timedelta(days=1)
        elif local_time < end:
            end_date = local_now.date()
        else:
            return None
    return _resolve_quiet_end(end_date, end, timezone).astimezone(UTC)


def evaluate_safety_policy(
    context: SafetyPolicyContext,
    config: SafetyPolicyConfig,
) -> SafetyDecision:
    """Evaluate strict safety precedence before approval or utility preferences."""

    action_is_contact = context.action in _CUSTOMER_CONTACT_ACTIONS
    action_is_outreach = context.action in _OUTREACH_ACTIONS
    action_is_terminal_control = context.action in _TERMINAL_CONTROL_ACTIONS

    if config.global_kill_switch and not action_is_terminal_control:
        return _decision(
            config,
            PolicyDisposition.BLOCK,
            _reason(
                SafetyReasonCode.GLOBAL_KILL_SWITCH_ENABLED,
                "All recovery execution is disabled by the platform kill switch.",
            ),
        )
    if config.merchant_kill_switch and not action_is_terminal_control:
        return _decision(
            config,
            PolicyDisposition.BLOCK,
            _reason(
                SafetyReasonCode.MERCHANT_KILL_SWITCH_ENABLED,
                "Recovery execution is disabled for this merchant.",
            ),
        )
    if context.case_outcome != CaseOutcome.OPEN and not action_is_terminal_control:
        return _decision(
            config,
            PolicyDisposition.BLOCK,
            _reason(SafetyReasonCode.CASE_TERMINAL, "The recovery case is already terminal."),
        )
    if context.payment_state == PaymentState.CAPTURED and not action_is_terminal_control:
        return _decision(
            config,
            PolicyDisposition.BLOCK,
            _reason(
                SafetyReasonCode.PAYMENT_ALREADY_CAPTURED,
                "Authoritative payment state already shows captured funds.",
                "payment_state",
            ),
        )

    suppression_reasons = {
        ContactDisposition.OPTED_OUT: _reason(
            SafetyReasonCode.CUSTOMER_OPTED_OUT,
            "Customer opted out; customer-facing recovery is suppressed.",
            "contact_disposition",
        ),
        ContactDisposition.WRONG_PERSON: _reason(
            SafetyReasonCode.WRONG_PERSON,
            "The contact is not the customer; customer-facing recovery is suppressed.",
            "contact_disposition",
        ),
        ContactDisposition.DISPUTE: _reason(
            SafetyReasonCode.CUSTOMER_DISPUTE,
            "The charge is disputed; automated customer-facing recovery is suppressed.",
            "contact_disposition",
        ),
        ContactDisposition.ALREADY_PAID: _reason(
            SafetyReasonCode.CUSTOMER_REPORTS_ALREADY_PAID,
            "Customer-reported payment requires reconciliation before further contact.",
            "contact_disposition",
        ),
    }
    suppression = suppression_reasons.get(context.contact_disposition)
    if action_is_contact and suppression is not None:
        return _decision(config, PolicyDisposition.BLOCK, suppression)

    if context.now >= context.recovery_deadline and not action_is_terminal_control:
        return _decision(
            config,
            PolicyDisposition.BLOCK,
            _reason(
                SafetyReasonCode.RECOVERY_WINDOW_EXPIRED,
                "The configured recovery deadline has passed.",
                "recovery_deadline",
            ),
        )

    if (
        context.action == RecoveryActionType.OPEN_CUSTOMER_PAYMENT_SURFACE
        and context.payment_surface_type == PaymentSurfaceType.STANDARD_PAYMENT_LINK
        and context.subscription_state == SubscriptionState.PENDING
        and context.active_gateway_retries
    ):
        return _decision(
            config,
            PolicyDisposition.BLOCK,
            _reason(
                SafetyReasonCode.GATEWAY_RETRY_ACTIVE,
                "Standalone collection is blocked while subscription auto-retries are active.",
                "payment_surface_type",
            ),
        )

    if (
        context.action == RecoveryActionType.WAIT_FOR_GATEWAY_RETRY
        and context.subscription_state == SubscriptionState.PENDING
        and context.active_gateway_retries
    ):
        delay_until = min(context.now + config.gateway_retry_delay, context.recovery_deadline)
        if delay_until > context.now:
            return _decision(
                config,
                PolicyDisposition.DELAY,
                _reason(
                    SafetyReasonCode.WAIT_FOR_PROVIDER_RETRY,
                    "The payment provider owns the active pending-subscription retry.",
                    "subscription_state",
                ),
                delay_until=delay_until,
            )

    if (
        action_is_outreach
        and config.max_contacts_per_window is not None
        and context.contact_attempts_in_window >= config.max_contacts_per_window
    ):
        reset_at = context.contact_limit_resets_at
        if reset_at is not None and context.now < reset_at < context.recovery_deadline:
            return _decision(
                config,
                PolicyDisposition.DELAY,
                _reason(
                    SafetyReasonCode.CONTACT_LIMIT_REACHED,
                    "The contact limit is reached; outreach is delayed until the window resets.",
                    "contact_attempts_in_window",
                ),
                delay_until=reset_at,
            )
        return _decision(
            config,
            PolicyDisposition.BLOCK,
            _reason(
                SafetyReasonCode.CONTACT_LIMIT_REACHED,
                "The contact limit is reached and no safe retry remains in the recovery window.",
                "contact_attempts_in_window",
            ),
        )

    if (
        action_is_outreach
        and config.quiet_hours_start is not None
        and config.quiet_hours_end is not None
    ):
        quiet_end = quiet_hours_delay_until(
            context.now,
            timezone_name=config.merchant_timezone,
            start=config.quiet_hours_start,
            end=config.quiet_hours_end,
        )
        if quiet_end is not None:
            if quiet_end < context.recovery_deadline:
                return _decision(
                    config,
                    PolicyDisposition.DELAY,
                    _reason(
                        SafetyReasonCode.QUIET_HOURS_ACTIVE,
                        "Outreach is delayed until merchant-local quiet hours end.",
                        "merchant_timezone",
                    ),
                    delay_until=quiet_end,
                )
            return _decision(
                config,
                PolicyDisposition.BLOCK,
                _reason(
                    SafetyReasonCode.QUIET_HOURS_ACTIVE,
                    "Quiet hours extend beyond the remaining recovery window.",
                    "merchant_timezone",
                ),
            )

    approval_reasons: list[SafetyReason] = []
    if not action_is_terminal_control and context.action in config.manual_approval_actions:
        approval_reasons.append(
            _reason(
                SafetyReasonCode.ACTION_REQUIRES_APPROVAL,
                "Merchant policy requires human approval for this action.",
                "action",
            )
        )
    if (
        action_is_contact
        and config.manual_approval_above_paise is not None
        and context.amount_at_risk_paise >= config.manual_approval_above_paise
    ):
        approval_reasons.append(
            _reason(
                SafetyReasonCode.AMOUNT_REQUIRES_APPROVAL,
                "The amount at risk meets the merchant's manual approval threshold.",
                "amount_at_risk_paise",
            )
        )
    if approval_reasons:
        return _decision(
            config,
            PolicyDisposition.REQUIRE_MANUAL_APPROVAL,
            *approval_reasons,
        )

    return _decision(
        config,
        PolicyDisposition.ALLOW,
        _reason(
            SafetyReasonCode.WITHIN_RECOVERY_WINDOW,
            "The case is within its configured recovery window.",
            "recovery_deadline",
        ),
        _reason(
            SafetyReasonCode.NO_SUPPRESSION,
            "No higher-priority suppression applies to this action.",
        ),
    )
