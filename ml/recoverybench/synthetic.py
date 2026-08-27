"""Fixed-seed, paired synthetic cases for offline RecoveryBench evaluation.

The hidden-state response model is intentionally separate from the features
shown to a scorer.  Treatment and baseline share one outcome draw per case,
which makes comparisons paired and reproducible without pretending that the
synthetic outcomes are verified merchant revenue.
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass
from typing import Any

from services.api.app.domain.enums import Diagnosis, RecoveryActionType

DIAGNOSES = tuple(Diagnosis)
ACTION_COST_PAISE: dict[RecoveryActionType, int] = {
    RecoveryActionType.WAIT_FOR_GATEWAY_RETRY: 0,
    RecoveryActionType.OPEN_CUSTOMER_PAYMENT_SURFACE: 250,
    RecoveryActionType.START_VOICE: 1_200,
    RecoveryActionType.SEND_TO_CUSTOMER_AGENT: 500,
    RecoveryActionType.ESCALATE_TO_HUMAN: 3_500,
    RecoveryActionType.STOP: 0,
}


@dataclass(frozen=True, slots=True)
class HiddenCustomerState:
    recovery_propensity: float
    digital_affinity: float
    voice_affinity: float
    liquidity: float
    contact_aversion: float
    outcome_draw: float


@dataclass(frozen=True, slots=True)
class SyntheticCase:
    case_id: str
    amount_at_risk_paise: int
    diagnosis: Diagnosis
    candidate_action: RecoveryActionType
    tenure_days: int
    prior_successful_payments: int
    failed_attempt_count: int
    customer_agent_available: bool
    voice_consent: bool
    is_quiet_hours: bool
    hidden_state: HiddenCustomerState
    baseline_probability: float
    treatment_probability: float
    baseline_recovered: bool
    treatment_recovered: bool

    @property
    def simulated_incremental_recovery_paise(self) -> int:
        return (
            self.amount_at_risk_paise
            if self.treatment_recovered and not self.baseline_recovered
            else 0
        )

    def model_features(self) -> dict[str, str | int | float | bool]:
        """Return observable features only; hidden state must never leak."""

        return {
            "amount_at_risk_paise": self.amount_at_risk_paise,
            "diagnosis": self.diagnosis.value,
            "candidate_action": self.candidate_action.value,
            "tenure_days": self.tenure_days,
            "prior_successful_payments": self.prior_successful_payments,
            "failed_attempt_count": self.failed_attempt_count,
            "customer_agent_available": self.customer_agent_available,
            "voice_consent": self.voice_consent,
            "is_quiet_hours": self.is_quiet_hours,
        }

    def to_audit_dict(self) -> dict[str, Any]:
        """Expose hidden state only in offline, auditable benchmark output."""

        payload = asdict(self)
        payload["diagnosis"] = self.diagnosis.value
        payload["candidate_action"] = self.candidate_action.value
        return payload


def _clamp_probability(value: float) -> float:
    return min(max(value, 0.01), 0.98)


def _choose_action(
    diagnosis: Diagnosis,
    *,
    customer_agent_available: bool,
    voice_consent: bool,
    failed_attempt_count: int,
) -> RecoveryActionType:
    if diagnosis == Diagnosis.TRANSIENT_RETRYABLE and failed_attempt_count <= 2:
        return RecoveryActionType.WAIT_FOR_GATEWAY_RETRY
    if diagnosis in {
        Diagnosis.AUTHENTICATION_REQUIRED,
        Diagnosis.INSTRUMENT_INVALID,
        Diagnosis.INSUFFICIENT_FUNDS,
    }:
        return RecoveryActionType.OPEN_CUSTOMER_PAYMENT_SURFACE
    if diagnosis == Diagnosis.RISK_OR_COMPLIANCE_BLOCK:
        return RecoveryActionType.ESCALATE_TO_HUMAN
    if customer_agent_available:
        return RecoveryActionType.SEND_TO_CUSTOMER_AGENT
    if voice_consent:
        return RecoveryActionType.START_VOICE
    return RecoveryActionType.STOP


def _baseline_probability(
    state: HiddenCustomerState,
    diagnosis: Diagnosis,
    failed_attempt_count: int,
) -> float:
    diagnosis_effect = {
        Diagnosis.TRANSIENT_RETRYABLE: 0.19,
        Diagnosis.INSUFFICIENT_FUNDS: -0.12,
        Diagnosis.AUTHENTICATION_REQUIRED: -0.08,
        Diagnosis.INSTRUMENT_INVALID: -0.15,
        Diagnosis.MERCHANT_ERROR: -0.28,
        Diagnosis.RISK_OR_COMPLIANCE_BLOCK: -0.34,
        Diagnosis.UNKNOWN: -0.18,
    }[diagnosis]
    return _clamp_probability(
        0.08
        + (0.42 * state.recovery_propensity)
        + (0.18 * state.liquidity)
        + diagnosis_effect
        - (0.035 * max(failed_attempt_count - 1, 0))
    )


def _treatment_probability(
    baseline: float,
    *,
    action: RecoveryActionType,
    diagnosis: Diagnosis,
    state: HiddenCustomerState,
    voice_consent: bool,
    customer_agent_available: bool,
    is_quiet_hours: bool,
) -> float:
    effect = {
        RecoveryActionType.WAIT_FOR_GATEWAY_RETRY: (
            0.24 if diagnosis == Diagnosis.TRANSIENT_RETRYABLE else 0.03
        ),
        RecoveryActionType.OPEN_CUSTOMER_PAYMENT_SURFACE: (0.12 + (0.24 * state.digital_affinity)),
        RecoveryActionType.START_VOICE: (
            0.04 + (0.19 * state.voice_affinity) - (0.14 * state.contact_aversion)
            if voice_consent and not is_quiet_hours
            else 0.0
        ),
        RecoveryActionType.SEND_TO_CUSTOMER_AGENT: (
            0.06 + (0.22 * state.digital_affinity) if customer_agent_available else 0.0
        ),
        RecoveryActionType.ESCALATE_TO_HUMAN: 0.07,
        RecoveryActionType.STOP: 0.0,
    }[action]
    return _clamp_probability(baseline + max(effect, 0.0))


def generate_paired_cases(*, count: int = 1_000, seed: int = 20_260_827) -> list[SyntheticCase]:
    """Generate deterministic paired treatment/baseline potential outcomes."""

    if count < 1:
        raise ValueError("count must be at least 1")
    rng = random.Random(seed)
    cases: list[SyntheticCase] = []
    diagnosis_weights = (0.24, 0.23, 0.16, 0.12, 0.08, 0.05, 0.12)
    for index in range(count):
        diagnosis = rng.choices(DIAGNOSES, weights=diagnosis_weights, k=1)[0]
        amount_at_risk_paise = rng.randrange(5_000, 250_001, 100)
        tenure_days = rng.randint(14, 1_800)
        prior_successful_payments = rng.randint(0, 48)
        failed_attempt_count = rng.randint(1, 5)
        customer_agent_available = rng.random() < 0.58
        voice_consent = rng.random() < 0.42
        is_quiet_hours = rng.random() < 0.28
        state = HiddenCustomerState(
            recovery_propensity=rng.betavariate(2.4, 2.1),
            digital_affinity=rng.betavariate(2.7, 1.8),
            voice_affinity=rng.betavariate(1.8, 2.4),
            liquidity=rng.betavariate(2.0, 2.3),
            contact_aversion=rng.betavariate(1.6, 3.0),
            outcome_draw=rng.random(),
        )
        action = _choose_action(
            diagnosis,
            customer_agent_available=customer_agent_available,
            voice_consent=voice_consent,
            failed_attempt_count=failed_attempt_count,
        )
        baseline_probability = _baseline_probability(state, diagnosis, failed_attempt_count)
        treatment_probability = _treatment_probability(
            baseline_probability,
            action=action,
            diagnosis=diagnosis,
            state=state,
            voice_consent=voice_consent,
            customer_agent_available=customer_agent_available,
            is_quiet_hours=is_quiet_hours,
        )
        cases.append(
            SyntheticCase(
                case_id=f"syn_{seed}_{index:06d}",
                amount_at_risk_paise=amount_at_risk_paise,
                diagnosis=diagnosis,
                candidate_action=action,
                tenure_days=tenure_days,
                prior_successful_payments=prior_successful_payments,
                failed_attempt_count=failed_attempt_count,
                customer_agent_available=customer_agent_available,
                voice_consent=voice_consent,
                is_quiet_hours=is_quiet_hours,
                hidden_state=state,
                baseline_probability=baseline_probability,
                treatment_probability=treatment_probability,
                baseline_recovered=state.outcome_draw < baseline_probability,
                treatment_recovered=state.outcome_draw < treatment_probability,
            )
        )
    return cases
