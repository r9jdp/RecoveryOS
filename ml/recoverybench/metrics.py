"""Versioned RecoveryBench report metrics."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sklearn.metrics import (  # type: ignore[import-untyped]
    average_precision_score,
    brier_score_loss,
)

from services.api.app.domain.enums import RecoveryActionType

from .synthetic import SyntheticCase


def _safe_ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def calibration_bins(
    outcomes: Sequence[int], probabilities: Sequence[float], *, bin_count: int = 10
) -> list[dict[str, int | float]]:
    bins: list[dict[str, int | float]] = []
    for index in range(bin_count):
        lower = index / bin_count
        upper = (index + 1) / bin_count
        selected = [
            row
            for row, probability in enumerate(probabilities)
            if lower <= probability < upper or (index == bin_count - 1 and probability == 1.0)
        ]
        bins.append(
            {
                "lower_bound": lower,
                "upper_bound": upper,
                "case_count": len(selected),
                "mean_predicted_probability": (
                    sum(probabilities[row] for row in selected) / len(selected) if selected else 0.0
                ),
                "observed_recovery_rate": (
                    sum(outcomes[row] for row in selected) / len(selected) if selected else 0.0
                ),
            }
        )
    return bins


def build_metric_report(
    cases: Sequence[SyntheticCase], probabilities: Sequence[float]
) -> dict[str, Any]:
    if len(cases) != len(probabilities) or not cases:
        raise ValueError("cases and probabilities must have the same non-zero length")
    outcomes = [int(case.treatment_recovered) for case in cases]
    ranked = sorted(range(len(cases)), key=lambda row: (-probabilities[row], cases[row].case_id))
    top_count = max(1, (len(cases) + 9) // 10)
    top_rows = ranked[:top_count]
    overall_rate = sum(outcomes) / len(outcomes)
    top_rate = sum(outcomes[row] for row in top_rows) / len(top_rows)
    total_amount = sum(case.amount_at_risk_paise for case in cases)
    recovered_amount = sum(case.amount_at_risk_paise for case in cases if case.treatment_recovered)
    top_total_amount = sum(cases[row].amount_at_risk_paise for row in top_rows)
    top_recovered_amount = sum(
        cases[row].amount_at_risk_paise for row in top_rows if cases[row].treatment_recovered
    )
    overall_amount_weighted_rate = _safe_ratio(recovered_amount, total_amount)
    top_amount_weighted_rate = _safe_ratio(top_recovered_amount, top_total_amount)

    by_action: list[dict[str, Any]] = []
    for action in RecoveryActionType:
        rows = [row for row, case in enumerate(cases) if case.candidate_action == action]
        if not rows:
            continue
        by_action.append(
            {
                "action": action.value,
                "case_count": len(rows),
                "treatment_recovered_count": sum(outcomes[row] for row in rows),
                "baseline_recovered_count": sum(int(cases[row].baseline_recovered) for row in rows),
                "mean_predicted_probability": sum(probabilities[row] for row in rows) / len(rows),
                "observed_treatment_recovery_rate": sum(outcomes[row] for row in rows) / len(rows),
                "simulated_incremental_recovery_paise": sum(
                    cases[row].simulated_incremental_recovery_paise for row in rows
                ),
            }
        )

    return {
        "pr_auc": float(average_precision_score(outcomes, probabilities)),
        "brier_score": float(brier_score_loss(outcomes, probabilities)),
        "top_decile_lift": _safe_ratio(top_rate, overall_rate),
        "amount_weighted_lift": _safe_ratio(top_amount_weighted_rate, overall_amount_weighted_rate),
        "calibration": calibration_bins(outcomes, probabilities),
        "recovery_by_action": by_action,
        "simulated_incremental_recovery_paise": sum(
            case.simulated_incremental_recovery_paise for case in cases
        ),
    }
