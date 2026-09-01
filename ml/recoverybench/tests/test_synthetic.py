from ml.recoverybench.synthetic import (
    HiddenCustomerState,
    _treatment_probability,
    generate_paired_cases,
)
from services.api.app.domain.enums import Diagnosis, PaymentSurfaceType, RecoveryActionType


def test_fixed_seed_is_deterministic_and_paired() -> None:
    first = generate_paired_cases(count=100, seed=912)
    second = generate_paired_cases(count=100, seed=912)

    assert first == second
    assert len(first) == 100
    assert all(case.treatment_probability >= case.baseline_probability for case in first)
    assert all(not case.baseline_recovered or case.treatment_recovered for case in first)
    assert all("hidden_state" not in case.model_features() for case in first)


def test_different_seed_changes_cases() -> None:
    assert generate_paired_cases(count=10, seed=1) != generate_paired_cases(count=10, seed=2)


def test_payment_surfaces_are_observable_and_only_attached_to_surface_actions() -> None:
    cases = generate_paired_cases(count=1_000, seed=912)
    surface_cases = [
        case
        for case in cases
        if case.candidate_action == RecoveryActionType.OPEN_CUSTOMER_PAYMENT_SURFACE
    ]

    assert surface_cases
    assert all(case.payment_surface_type is not None for case in surface_cases)
    assert all(
        case.payment_surface_type is None
        for case in cases
        if case.candidate_action != RecoveryActionType.OPEN_CUSTOMER_PAYMENT_SURFACE
    )
    observed = {case.payment_surface_type for case in surface_cases}
    assert observed == set(PaymentSurfaceType)
    assert {case.model_features()["payment_surface_type"] for case in surface_cases} == {
        surface.value for surface in PaymentSurfaceType
    }


def test_surface_treatment_effect_reverses_for_authentication_and_liquidity_failures() -> None:
    state = HiddenCustomerState(
        recovery_propensity=0.5,
        digital_affinity=0.6,
        voice_affinity=0.3,
        liquidity=0.4,
        contact_aversion=0.2,
        outcome_draw=0.5,
    )

    def probability(diagnosis: Diagnosis, surface: PaymentSurfaceType) -> float:
        return _treatment_probability(
            0.20,
            action=RecoveryActionType.OPEN_CUSTOMER_PAYMENT_SURFACE,
            payment_surface_type=surface,
            diagnosis=diagnosis,
            state=state,
            voice_consent=False,
            customer_agent_available=False,
            is_quiet_hours=False,
        )

    assert probability(
        Diagnosis.AUTHENTICATION_REQUIRED,
        PaymentSurfaceType.SUBSCRIPTION_CARD_UPDATE,
    ) > probability(
        Diagnosis.AUTHENTICATION_REQUIRED,
        PaymentSurfaceType.SUBSCRIPTION_INVOICE_LINK,
    )
    assert probability(
        Diagnosis.INSUFFICIENT_FUNDS,
        PaymentSurfaceType.SUBSCRIPTION_INVOICE_LINK,
    ) > probability(
        Diagnosis.INSUFFICIENT_FUNDS,
        PaymentSurfaceType.SUBSCRIPTION_CARD_UPDATE,
    )
