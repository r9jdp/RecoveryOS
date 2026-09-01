"""Server-side factory for the optional RecoveryBench scorer adapter."""

from __future__ import annotations

import os
from pathlib import Path

from ml.recoverybench.baseline import RecoveryBenchScorer
from services.api.app.providers.interfaces import RecoveryScorer


def create_recovery_scorer() -> RecoveryScorer:
    configured_path = os.getenv("RECOVERYBENCH_ARTIFACT_DIR", "").strip()
    model_required = os.getenv(
        "RECOVERY_MODEL_REQUIRED",
        "true" if os.getenv("APP_ENV", "development").strip().lower() == "production" else "false",
    ).strip().lower() in {"1", "true", "yes", "on"}
    return RecoveryBenchScorer(
        Path(configured_path) if configured_path else None,
        allow_deterministic_fallback=not model_required,
    )
