"""Deterministic CatBoost training and calibrated artifact production."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
from catboost import CatBoostClassifier  # type: ignore[import-untyped]
from sklearn.isotonic import IsotonicRegression  # type: ignore[import-untyped]

from .metrics import build_metric_report
from .synthetic import SyntheticCase, generate_paired_cases

ARTIFACT_VERSION = "recoverybench.v1"
REPORT_SCHEMA_VERSION = "recoverybench.report.v1"
DEFAULT_SEED = 20_260_827
FEATURE_COLUMNS = [
    "amount_at_risk_paise",
    "diagnosis",
    "candidate_action",
    "tenure_days",
    "prior_successful_payments",
    "failed_attempt_count",
    "customer_agent_available",
    "voice_consent",
    "is_quiet_hours",
]
CATEGORICAL_FEATURES = ["diagnosis", "candidate_action"]
_DETERMINISTIC_TRAIN_FINISH_TIME = "1970-01-01T00:00:00Z"


def _frame(cases: Sequence[SyntheticCase]) -> pd.DataFrame:
    return pd.DataFrame([case.model_features() for case in cases], columns=FEATURE_COLUMNS)


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, separators=(",", ": ")) + "\n"


def apply_calibration(raw_probability: float, calibration: dict[str, list[float]]) -> float:
    x = calibration["x_thresholds"]
    y = calibration["y_thresholds"]
    if not x or len(x) != len(y):
        return min(max(raw_probability, 0.0), 1.0)
    if raw_probability <= x[0]:
        return y[0]
    if raw_probability >= x[-1]:
        return y[-1]
    for index in range(1, len(x)):
        if raw_probability <= x[index]:
            width = x[index] - x[index - 1]
            if width == 0:
                return y[index]
            fraction = (raw_probability - x[index - 1]) / width
            return y[index - 1] + (fraction * (y[index] - y[index - 1]))
    return y[-1]


def artifact_checksum(artifact_dir: Path) -> str:
    return hashlib.sha256(
        (artifact_dir / "model.cbm").read_bytes() + (artifact_dir / "calibration.json").read_bytes()
    ).hexdigest()


def _deterministic_model_metadata(*, seed: int, case_count: int) -> dict[str, str]:
    """Replace CatBoost's wall-clock and random model metadata.

    CatBoost otherwise writes a random ``model_guid`` and the current training
    completion time into every CBM file. Those values do not affect inference,
    but they make a fixed-seed build produce different artifact bytes and a
    different checksum. Supplying the reserved metadata keys at construction
    time makes the serialized model reproducible without rewriting its binary
    format after training.
    """

    digest = hashlib.sha256(
        f"{ARTIFACT_VERSION}:{seed}:{case_count}".encode("utf-8")
    ).hexdigest()
    return {
        "model_guid": "-".join(digest[index : index + 8] for index in range(0, 32, 8)),
        "train_finish_time": _DETERMINISTIC_TRAIN_FINISH_TIME,
    }


def train_artifact(
    artifact_dir: Path,
    *,
    seed: int = DEFAULT_SEED,
    case_count: int = 1_200,
) -> dict[str, Any]:
    """Train, calibrate, evaluate, and write one self-verifying artifact."""

    if case_count < 300:
        raise ValueError("case_count must be at least 300 for stable paired splits")
    cases = generate_paired_cases(count=case_count, seed=seed)
    train_end = int(case_count * 0.60)
    calibration_end = int(case_count * 0.80)
    training_cases = cases[:train_end]
    calibration_cases = cases[train_end:calibration_end]
    evaluation_cases = cases[calibration_end:]

    model = CatBoostClassifier(
        iterations=120,
        depth=6,
        learning_rate=0.05,
        loss_function="Logloss",
        random_seed=seed,
        random_strength=0.0,
        bootstrap_type="No",
        thread_count=1,
        verbose=False,
        allow_writing_files=False,
        metadata=_deterministic_model_metadata(seed=seed, case_count=case_count),
    )
    model.fit(
        _frame(training_cases),
        [int(case.treatment_recovered) for case in training_cases],
        cat_features=CATEGORICAL_FEATURES,
    )
    raw_calibration = [float(row[1]) for row in model.predict_proba(_frame(calibration_cases))]
    calibrator = IsotonicRegression(out_of_bounds="clip", y_min=0.01, y_max=0.99)
    calibrator.fit(
        raw_calibration,
        [int(case.treatment_recovered) for case in calibration_cases],
    )
    calibration = {
        "x_thresholds": [float(value) for value in calibrator.X_thresholds_],
        "y_thresholds": [float(value) for value in calibrator.y_thresholds_],
    }
    raw_evaluation = [float(row[1]) for row in model.predict_proba(_frame(evaluation_cases))]
    probabilities = [apply_calibration(value, calibration) for value in raw_evaluation]

    artifact_dir.mkdir(parents=True, exist_ok=True)
    model.save_model(str(artifact_dir / "model.cbm"))
    calibration_text = _canonical_json(calibration)
    (artifact_dir / "calibration.json").write_text(calibration_text, encoding="utf-8")
    checksum = artifact_checksum(artifact_dir)
    manifest = {
        "schema_version": "recoverybench.artifact.v1",
        "artifact_version": ARTIFACT_VERSION,
        "artifact_checksum": checksum,
        "model_type": "CatBoostClassifier+isotonic",
        "feature_columns": FEATURE_COLUMNS,
        "categorical_features": CATEGORICAL_FEATURES,
        "training_seed": seed,
    }
    (artifact_dir / "manifest.json").write_text(_canonical_json(manifest), encoding="utf-8")

    metric_report = build_metric_report(evaluation_cases, probabilities)
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "report_version": ARTIFACT_VERSION,
        "generated_at": datetime(2026, 8, 27, 0, 0, tzinfo=UTC).isoformat(),
        "title": "RecoveryBench simulated incremental recovery evaluation",
        "evidence_kind": "SIMULATED",
        "artifact": manifest,
        "dataset": {
            "generator_version": "hidden-customer-state.v1",
            "seed": seed,
            "total_case_count": case_count,
            "training_case_count": len(training_cases),
            "calibration_case_count": len(calibration_cases),
            "evaluation_case_count": len(evaluation_cases),
            "cohort_design": "paired treatment and baseline potential outcomes",
        },
        "metrics": metric_report,
        "guardrails": {
            "merchant_revenue_mutated": False,
            "production_artifact_required": False,
            "label": "simulated incremental recovery",
        },
    }
    (artifact_dir / "report.json").write_text(_canonical_json(report), encoding="utf-8")
    return report
