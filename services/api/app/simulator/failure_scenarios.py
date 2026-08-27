"""Fixed-seed webhook and reconciliation scenario generation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from random import Random
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from services.api.app.domain.enums import EvidenceKind, PaymentState


class FailureScenario(StrEnum):
    DUPLICATE_WEBHOOK = "DUPLICATE_WEBHOOK"
    OUT_OF_ORDER_WEBHOOK = "OUT_OF_ORDER_WEBHOOK"
    LATE_SUCCESS = "LATE_SUCCESS"
    CHANGED_AUTHORITATIVE_PAYMENT_STATE = "CHANGED_AUTHORITATIVE_PAYMENT_STATE"


@dataclass(frozen=True, slots=True)
class SimulatedDelivery:
    delivery_id: str
    provider_event_id: str
    event_type: str
    occurred_at: datetime
    delivered_at: datetime
    observed_payment_state: PaymentState
    authoritative_payment_state: PaymentState
    evidence_kind: EvidenceKind
    payload: dict[str, Any]

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "delivery_id": self.delivery_id,
            "provider_event_id": self.provider_event_id,
            "event_type": self.event_type,
            "occurred_at": self.occurred_at.isoformat(),
            "delivered_at": self.delivered_at.isoformat(),
            "observed_payment_state": self.observed_payment_state.value,
            "authoritative_payment_state": self.authoritative_payment_state.value,
            "evidence_kind": self.evidence_kind.value,
            "payload": self.payload.copy(),
        }


@dataclass(frozen=True, slots=True)
class SimulationCase:
    scenario: FailureScenario
    seed: int
    case_id: str
    payment_id: str
    amount_paise: int
    deliveries: tuple[SimulatedDelivery, ...]
    expected_final_payment_state: PaymentState
    expected_revenue_entries: int

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario.value,
            "seed": self.seed,
            "case_id": self.case_id,
            "payment_id": self.payment_id,
            "amount_paise": self.amount_paise,
            "deliveries": [delivery.to_api_dict() for delivery in self.deliveries],
            "expected_final_payment_state": self.expected_final_payment_state.value,
            "expected_revenue_entries": self.expected_revenue_entries,
        }


def _stable_id(seed: int, scenario: FailureScenario, label: str) -> str:
    return uuid5(NAMESPACE_URL, f"recovery-os:{seed}:{scenario.value}:{label}").hex


def _delivery(
    *,
    seed: int,
    scenario: FailureScenario,
    index: int,
    provider_event_id: str,
    event_type: str,
    occurred_at: datetime,
    delivered_at: datetime,
    observed: PaymentState,
    authoritative: PaymentState,
    evidence_kind: EvidenceKind,
    case_id: str,
    payment_id: str,
    amount_paise: int,
) -> SimulatedDelivery:
    return SimulatedDelivery(
        delivery_id=_stable_id(seed, scenario, f"delivery:{index}"),
        provider_event_id=provider_event_id,
        event_type=event_type,
        occurred_at=occurred_at,
        delivered_at=delivered_at,
        observed_payment_state=observed,
        authoritative_payment_state=authoritative,
        evidence_kind=evidence_kind,
        payload={
            "case_id": case_id,
            "payment_id": payment_id,
            "amount_paise": amount_paise,
            "synthetic": evidence_kind == EvidenceKind.SIMULATED,
        },
    )


def build_failure_scenario(
    scenario: FailureScenario,
    *,
    seed: int = 20260827,
    base_time: datetime = datetime(2026, 8, 27, 9, tzinfo=UTC),
    amount_paise: int = 149_900,
    evidence_kind: EvidenceKind = EvidenceKind.SIMULATED,
) -> SimulationCase:
    """Build a deterministic delivery sequence without accessing providers or a clock."""

    if base_time.tzinfo is None or base_time.utcoffset() is None:
        raise ValueError("base_time must be timezone-aware")
    if isinstance(amount_paise, bool) or amount_paise <= 0:
        raise ValueError("amount_paise must be a positive integer")
    if evidence_kind not in {EvidenceKind.SIMULATED, EvidenceKind.RAZORPAY_TEST_VERIFIED}:
        raise ValueError("failure scenarios require simulated or Razorpay test evidence")

    rng = Random(seed)
    jitter = timedelta(seconds=rng.randrange(3, 13))
    case_id = f"case_{_stable_id(seed, scenario, 'case')[:16]}"
    payment_id = f"pay_{_stable_id(seed, scenario, 'payment')[:14]}"
    failed_event_id = f"evt_{_stable_id(seed, scenario, 'failed')[:14]}"
    captured_event_id = f"evt_{_stable_id(seed, scenario, 'captured')[:14]}"

    failed_at = base_time.astimezone(UTC)
    captured_at = failed_at + timedelta(minutes=45)
    deliveries: tuple[SimulatedDelivery, ...]

    if scenario == FailureScenario.DUPLICATE_WEBHOOK:
        first = _delivery(
            seed=seed,
            scenario=scenario,
            index=0,
            provider_event_id=failed_event_id,
            event_type="payment.failed",
            occurred_at=failed_at,
            delivered_at=failed_at + jitter,
            observed=PaymentState.FAILED,
            authoritative=PaymentState.FAILED,
            evidence_kind=evidence_kind,
            case_id=case_id,
            payment_id=payment_id,
            amount_paise=amount_paise,
        )
        duplicate = _delivery(
            seed=seed,
            scenario=scenario,
            index=1,
            provider_event_id=failed_event_id,
            event_type="payment.failed",
            occurred_at=failed_at,
            delivered_at=first.delivered_at + timedelta(seconds=2),
            observed=PaymentState.FAILED,
            authoritative=PaymentState.FAILED,
            evidence_kind=evidence_kind,
            case_id=case_id,
            payment_id=payment_id,
            amount_paise=amount_paise,
        )
        deliveries = (first, duplicate)
        final_state = PaymentState.FAILED
        revenue_entries = 0
    elif scenario == FailureScenario.OUT_OF_ORDER_WEBHOOK:
        captured = _delivery(
            seed=seed,
            scenario=scenario,
            index=0,
            provider_event_id=captured_event_id,
            event_type="payment.captured",
            occurred_at=captured_at,
            delivered_at=captured_at + jitter,
            observed=PaymentState.CAPTURED,
            authoritative=PaymentState.CAPTURED,
            evidence_kind=evidence_kind,
            case_id=case_id,
            payment_id=payment_id,
            amount_paise=amount_paise,
        )
        stale_failed = _delivery(
            seed=seed,
            scenario=scenario,
            index=1,
            provider_event_id=failed_event_id,
            event_type="payment.failed",
            occurred_at=failed_at,
            delivered_at=captured.delivered_at + timedelta(seconds=2),
            observed=PaymentState.FAILED,
            authoritative=PaymentState.CAPTURED,
            evidence_kind=evidence_kind,
            case_id=case_id,
            payment_id=payment_id,
            amount_paise=amount_paise,
        )
        deliveries = (captured, stale_failed)
        final_state = PaymentState.CAPTURED
        revenue_entries = 1
    elif scenario == FailureScenario.LATE_SUCCESS:
        failed = _delivery(
            seed=seed,
            scenario=scenario,
            index=0,
            provider_event_id=failed_event_id,
            event_type="payment.failed",
            occurred_at=failed_at,
            delivered_at=failed_at + jitter,
            observed=PaymentState.FAILED,
            authoritative=PaymentState.FAILED,
            evidence_kind=evidence_kind,
            case_id=case_id,
            payment_id=payment_id,
            amount_paise=amount_paise,
        )
        captured = _delivery(
            seed=seed,
            scenario=scenario,
            index=1,
            provider_event_id=captured_event_id,
            event_type="payment.captured",
            occurred_at=captured_at,
            delivered_at=captured_at + timedelta(minutes=30) + jitter,
            observed=PaymentState.CAPTURED,
            authoritative=PaymentState.CAPTURED,
            evidence_kind=evidence_kind,
            case_id=case_id,
            payment_id=payment_id,
            amount_paise=amount_paise,
        )
        deliveries = (failed, captured)
        final_state = PaymentState.CAPTURED
        revenue_entries = 1
    else:
        changed = _delivery(
            seed=seed,
            scenario=scenario,
            index=0,
            provider_event_id=failed_event_id,
            event_type="payment.failed",
            occurred_at=failed_at,
            delivered_at=captured_at + jitter,
            observed=PaymentState.FAILED,
            authoritative=PaymentState.CAPTURED,
            evidence_kind=evidence_kind,
            case_id=case_id,
            payment_id=payment_id,
            amount_paise=amount_paise,
        )
        deliveries = (changed,)
        final_state = PaymentState.CAPTURED
        revenue_entries = 1

    return SimulationCase(
        scenario=scenario,
        seed=seed,
        case_id=case_id,
        payment_id=payment_id,
        amount_paise=amount_paise,
        deliveries=deliveries,
        expected_final_payment_state=final_state,
        expected_revenue_entries=revenue_entries,
    )
