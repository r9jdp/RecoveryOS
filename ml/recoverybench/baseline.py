"""RecoveryScorer implementations with a no-artifact deterministic fallback."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from services.api.app.domain.enums import Diagnosis, RecoveryActionType
from services.api.app.providers.contracts import RecoveryScoreRequest, RecoveryScoreResult

from .synthetic import ACTION_COST_PAISE

FALLBACK_VERSION = "deterministic.v1"
FALLBACK_CHECKSUM = hashlib.sha256(FALLBACK_VERSION.encode()).hexdigest()


def deterministic_probability(request: RecoveryScoreRequest) -> float:
    base = {
        Diagnosis.TRANSIENT_RETRYABLE: 0.68,
        Diagnosis.INSUFFICIENT_FUNDS: 0.32,
        Diagnosis.AUTHENTICATION_REQUIRED: 0.48,
        Diagnosis.INSTRUMENT_INVALID: 0.37,
        Diagnosis.MERCHANT_ERROR: 0.11,
        Diagnosis.RISK_OR_COMPLIANCE_BLOCK: 0.06,
        Diagnosis.UNKNOWN: 0.19,
    }[request.diagnosis]
    action_adjustment = {
        RecoveryActionType.WAIT_FOR_GATEWAY_RETRY: 0.07,
        RecoveryActionType.OPEN_CUSTOMER_PAYMENT_SURFACE: 0.12,
        RecoveryActionType.START_VOICE: 0.03,
        RecoveryActionType.SEND_TO_CUSTOMER_AGENT: 0.08,
        RecoveryActionType.ESCALATE_TO_HUMAN: -0.01,
        RecoveryActionType.STOP: -0.15,
    }[request.candidate_action]
    prior_successes = request.features.get("prior_successful_payments", 0)
    prior_adjustment = min(int(prior_successes or 0), 24) * 0.004
    return min(max(base + action_adjustment + prior_adjustment, 0.01), 0.95)


class DeterministicRecoveryScorer:
    """Dependency-free scorer used whenever an artifact cannot be loaded."""

    async def score(self, request: RecoveryScoreRequest) -> RecoveryScoreResult:
        probability = deterministic_probability(request)
        expected_recovered = round(request.amount_at_risk_paise * probability)
        action_cost = ACTION_COST_PAISE[request.candidate_action]
        return RecoveryScoreResult(
            model_name="recoverybench-deterministic",
            model_version=FALLBACK_VERSION,
            artifact_checksum=FALLBACK_CHECKSUM,
            recovery_probability=probability,
            expected_recovered_paise=expected_recovered,
            expected_utility_paise=expected_recovered - action_cost,
            explanation=[
                "Deterministic fallback used; no model artifact was required.",
                f"Diagnosis={request.diagnosis.value}; action={request.candidate_action.value}.",
            ],
        )


class RecoveryModelUnavailableError(RuntimeError):
    """Raised when a deployment requires the trained artifact but it cannot load."""


class RecoveryBenchScorer:
    """Lazy CatBoost adapter that degrades safely to the deterministic scorer."""

    def __init__(
        self,
        artifact_dir: Path | None = None,
        *,
        allow_deterministic_fallback: bool = True,
    ) -> None:
        self.artifact_dir = artifact_dir
        self.allow_deterministic_fallback = allow_deterministic_fallback
        self.fallback = DeterministicRecoveryScorer()
        self._model: Any | None = None
        self._manifest: dict[str, Any] | None = None
        self._calibration: dict[str, Any] | None = None

    def _try_load(self) -> bool:
        if self._model is not None:
            return True
        if self.artifact_dir is None:
            return False
        model_path = self.artifact_dir / "model.cbm"
        calibration_path = self.artifact_dir / "calibration.json"
        manifest_path = self.artifact_dir / "manifest.json"
        if not (model_path.is_file() and calibration_path.is_file() and manifest_path.is_file()):
            return False
        try:
            from catboost import CatBoostClassifier  # type: ignore[import-untyped]

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            calibration_bytes = calibration_path.read_bytes()
            checksum = hashlib.sha256(model_path.read_bytes() + calibration_bytes).hexdigest()
            if checksum != manifest["artifact_checksum"]:
                return False
            model = CatBoostClassifier()
            model.load_model(str(model_path))
            self._model = model
            self._manifest = manifest
            self._calibration = json.loads(calibration_bytes)
        except (ImportError, KeyError, OSError, ValueError, json.JSONDecodeError):
            return False
        return True

    async def score(self, request: RecoveryScoreRequest) -> RecoveryScoreResult:
        if not self._try_load():
            if not self.allow_deterministic_fallback:
                raise RecoveryModelUnavailableError(
                    "The checksum-verified RecoveryBench model is unavailable."
                )
            return await self.fallback.score(request)

        import pandas as pd  # type: ignore[import-untyped]

        from .training import FEATURE_COLUMNS, apply_calibration

        assert self._model is not None
        assert self._manifest is not None
        assert self._calibration is not None
        row = {column: request.features.get(column) for column in FEATURE_COLUMNS}
        row["payment_surface_type"] = request.features.get("payment_surface_type") or "NONE"
        row.update(
            {
                "amount_at_risk_paise": request.amount_at_risk_paise,
                "diagnosis": request.diagnosis.value,
                "candidate_action": request.candidate_action.value,
            }
        )
        frame = pd.DataFrame([row], columns=FEATURE_COLUMNS)
        raw_probability = float(self._model.predict_proba(frame)[0][1])
        probability = apply_calibration(raw_probability, self._calibration)
        expected_recovered = round(request.amount_at_risk_paise * probability)
        action_cost = ACTION_COST_PAISE[request.candidate_action]
        return RecoveryScoreResult(
            model_name="recoverybench-catboost",
            model_version=str(self._manifest["artifact_version"]),
            artifact_checksum=str(self._manifest["artifact_checksum"]),
            recovery_probability=probability,
            expected_recovered_paise=expected_recovered,
            expected_utility_paise=expected_recovered - action_cost,
            explanation=[
                "Calibrated CatBoost recoverability estimate.",
                "Artifact checksum was verified before scoring.",
            ],
        )
