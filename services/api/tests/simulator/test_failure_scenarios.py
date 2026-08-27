"""Deterministic webhook delivery and reconciliation scenarios."""

from datetime import datetime

import pytest

from services.api.app.domain.enums import EvidenceKind, PaymentState
from services.api.app.simulator import FailureScenario, build_failure_scenario


@pytest.mark.parametrize("scenario", list(FailureScenario))
def test_scenarios_are_fixed_seed_deterministic(scenario: FailureScenario) -> None:
    first = build_failure_scenario(scenario, seed=42)
    second = build_failure_scenario(scenario, seed=42)

    assert first == second
    assert first.to_api_dict() == second.to_api_dict()
    assert all(delivery.evidence_kind == EvidenceKind.SIMULATED for delivery in first.deliveries)
    assert all(delivery.payload["synthetic"] is True for delivery in first.deliveries)


def test_different_seeds_produce_distinct_idempotency_keys() -> None:
    first = build_failure_scenario(FailureScenario.DUPLICATE_WEBHOOK, seed=1)
    second = build_failure_scenario(FailureScenario.DUPLICATE_WEBHOOK, seed=2)

    assert first.case_id != second.case_id
    assert first.deliveries[0].provider_event_id != second.deliveries[0].provider_event_id


def test_duplicate_webhook_reuses_provider_event_id_but_not_delivery_id() -> None:
    simulation = build_failure_scenario(FailureScenario.DUPLICATE_WEBHOOK)
    first, duplicate = simulation.deliveries

    assert first.provider_event_id == duplicate.provider_event_id
    assert first.delivery_id != duplicate.delivery_id
    assert first.occurred_at == duplicate.occurred_at
    assert first.delivered_at < duplicate.delivered_at
    assert simulation.expected_revenue_entries == 0


def test_out_of_order_delivery_cannot_regress_authoritative_capture() -> None:
    simulation = build_failure_scenario(FailureScenario.OUT_OF_ORDER_WEBHOOK)
    captured, stale_failed = simulation.deliveries

    assert captured.delivered_at < stale_failed.delivered_at
    assert captured.occurred_at > stale_failed.occurred_at
    assert stale_failed.observed_payment_state == PaymentState.FAILED
    assert stale_failed.authoritative_payment_state == PaymentState.CAPTURED
    assert simulation.expected_final_payment_state == PaymentState.CAPTURED
    assert simulation.expected_revenue_entries == 1


def test_late_success_is_delivered_after_initial_failure() -> None:
    simulation = build_failure_scenario(FailureScenario.LATE_SUCCESS)
    failed, captured = simulation.deliveries

    assert failed.event_type == "payment.failed"
    assert captured.event_type == "payment.captured"
    assert captured.delivered_at > captured.occurred_at
    assert captured.delivered_at > failed.delivered_at
    assert simulation.expected_final_payment_state == PaymentState.CAPTURED


def test_changed_state_marks_webhook_observation_and_fetch_result_separately() -> None:
    simulation = build_failure_scenario(FailureScenario.CHANGED_AUTHORITATIVE_PAYMENT_STATE)
    delivery = simulation.deliveries[0]

    assert delivery.observed_payment_state == PaymentState.FAILED
    assert delivery.authoritative_payment_state == PaymentState.CAPTURED


def test_razorpay_test_evidence_is_never_mislabelled_simulated() -> None:
    simulation = build_failure_scenario(
        FailureScenario.LATE_SUCCESS,
        evidence_kind=EvidenceKind.RAZORPAY_TEST_VERIFIED,
    )

    assert all(
        delivery.evidence_kind == EvidenceKind.RAZORPAY_TEST_VERIFIED
        for delivery in simulation.deliveries
    )
    assert all(delivery.payload["synthetic"] is False for delivery in simulation.deliveries)
    assert simulation.to_api_dict()["deliveries"][0]["evidence_kind"] == ("RAZORPAY_TEST_VERIFIED")


def test_json_ready_shape_uses_integer_paise_and_iso_timestamps() -> None:
    payload = build_failure_scenario(
        FailureScenario.DUPLICATE_WEBHOOK,
        amount_paise=149_900,
    ).to_api_dict()

    assert payload["amount_paise"] == 149_900
    assert isinstance(payload["amount_paise"], int)
    assert payload["deliveries"][0]["occurred_at"].endswith("+00:00")


def test_invalid_inputs_are_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        build_failure_scenario(
            FailureScenario.LATE_SUCCESS,
            base_time=datetime(2026, 8, 27, 9),
        )
    with pytest.raises(ValueError, match="positive integer"):
        build_failure_scenario(FailureScenario.LATE_SUCCESS, amount_paise=0)
