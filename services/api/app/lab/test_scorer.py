from __future__ import annotations

import pytest

from ml.recoverybench.baseline import DeterministicRecoveryScorer, RecoveryBenchScorer

from .scorer import create_recovery_scorer


def test_factory_uses_only_deterministic_scorer_when_model_is_not_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("RECOVERY_MODEL_REQUIRED", "false")

    assert isinstance(create_recovery_scorer(), DeterministicRecoveryScorer)


def test_factory_requires_model_without_deterministic_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RECOVERY_MODEL_REQUIRED", "true")
    monkeypatch.setenv("RECOVERYBENCH_ARTIFACT_DIR", "ml/recoverybench/artifacts/recoverybench.v1")

    scorer = create_recovery_scorer()

    assert isinstance(scorer, RecoveryBenchScorer)
    assert scorer.allow_deterministic_fallback is False
