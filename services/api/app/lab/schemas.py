"""Local response schemas for the isolated RecoveryBench API."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class LabSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ArtifactMetadata(LabSchema):
    schema_version: str
    artifact_version: str
    artifact_checksum: str = Field(pattern=r"^[a-f0-9]{64}$")
    model_type: str
    feature_columns: list[str]
    categorical_features: list[str]
    training_seed: int


class DatasetSummary(LabSchema):
    generator_version: str
    seed: int
    total_case_count: int = Field(ge=100)
    training_case_count: int = Field(gt=0)
    calibration_case_count: int = Field(gt=0)
    evaluation_case_count: int = Field(ge=100)
    cohort_design: str


class CalibrationBucket(LabSchema):
    lower_bound: float = Field(ge=0, le=1)
    upper_bound: float = Field(ge=0, le=1)
    case_count: int = Field(ge=0)
    mean_predicted_probability: float = Field(ge=0, le=1)
    observed_recovery_rate: float = Field(ge=0, le=1)


class ActionRecovery(LabSchema):
    action: str
    case_count: int = Field(ge=1)
    treatment_recovered_count: int = Field(ge=0)
    baseline_recovered_count: int = Field(ge=0)
    mean_predicted_probability: float = Field(ge=0, le=1)
    observed_treatment_recovery_rate: float = Field(ge=0, le=1)
    simulated_incremental_recovery_paise: int = Field(ge=0)


class MetricSummary(LabSchema):
    pr_auc: float = Field(ge=0, le=1)
    brier_score: float = Field(ge=0, le=1)
    top_decile_lift: float = Field(ge=0)
    amount_weighted_lift: float = Field(ge=0)
    calibration: list[CalibrationBucket]
    recovery_by_action: list[ActionRecovery]
    simulated_incremental_recovery_paise: int = Field(ge=0)


class LabGuardrails(LabSchema):
    merchant_revenue_mutated: bool
    production_artifact_required: bool
    label: str


class LabReport(LabSchema):
    schema_version: str
    report_version: str
    generated_at: str
    title: str
    evidence_kind: str
    artifact: ArtifactMetadata
    dataset: DatasetSummary
    metrics: MetricSummary
    guardrails: LabGuardrails
