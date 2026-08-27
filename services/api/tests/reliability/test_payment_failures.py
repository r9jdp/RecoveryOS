import pytest

from services.api.app.reliability.payment_projection import PaymentEventProjection
from services.api.app.simulator.failure_scenarios import (
    FailureScenario,
    build_failure_scenario,
)


@pytest.mark.parametrize("scenario", list(FailureScenario))
def test_failure_scenarios_converge_without_duplicate_revenue(
    scenario: FailureScenario,
) -> None:
    simulated = build_failure_scenario(scenario, seed=4096, amount_paise=149_900)
    replay = build_failure_scenario(scenario, seed=4096, amount_paise=149_900)
    assert simulated == replay

    projection = PaymentEventProjection()
    effects = [projection.apply(delivery) for delivery in simulated.deliveries]

    assert projection.payment_state == simulated.expected_final_payment_state
    assert projection.revenue_entries == simulated.expected_revenue_entries
    assert projection.arrears_collected_paise == (
        simulated.amount_paise if simulated.expected_revenue_entries else 0
    )
    if scenario == FailureScenario.DUPLICATE_WEBHOOK:
        assert effects[1].duplicate
    if scenario == FailureScenario.OUT_OF_ORDER_WEBHOOK:
        assert effects[1].stale
        assert sum(effect.revenue_recorded for effect in effects) == 1


def test_replaying_the_complete_delivery_stream_is_idempotent() -> None:
    simulated = build_failure_scenario(FailureScenario.LATE_SUCCESS)
    projection = PaymentEventProjection()
    for delivery in (*simulated.deliveries, *simulated.deliveries):
        projection.apply(delivery)
    assert projection.revenue_entries == 1
    assert projection.arrears_collected_paise == simulated.amount_paise
