from ml.recoverybench.synthetic import generate_paired_cases


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
