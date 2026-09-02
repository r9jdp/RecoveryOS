export interface LabArtifact {
  artifact_checksum: string;
  artifact_version: string;
  model_type: string;
  training_seed: number;
}

export interface LabDataset {
  calibration_case_count: number;
  cohort_design: string;
  evaluation_case_count: number;
  generator_version: string;
  seed: number;
  total_case_count: number;
  training_case_count: number;
}

export interface CalibrationBucket {
  case_count: number;
  lower_bound: number;
  mean_predicted_probability: number;
  observed_recovery_rate: number;
  upper_bound: number;
}

export interface ActionRecovery {
  action: string;
  baseline_recovered_count: number;
  case_count: number;
  mean_predicted_probability: number;
  observed_treatment_recovery_rate: number;
  simulated_incremental_recovery_paise: number;
  treatment_recovered_count: number;
}

export interface LabReport {
  artifact: LabArtifact;
  dataset: LabDataset;
  evidence_kind: "SIMULATED";
  generated_at: string;
  guardrails: {
    label: "projected incremental recovery";
    merchant_revenue_mutated: false;
    production_artifact_required: false;
  };
  metrics: {
    amount_weighted_lift: number;
    brier_score: number;
    calibration: CalibrationBucket[];
    pr_auc: number;
    recovery_by_action: ActionRecovery[];
    simulated_incremental_recovery_paise: number;
    top_decile_lift: number;
  };
  report_version: string;
  schema_version: string;
  title: string;
}

export interface LabReportResult {
  data: LabReport;
  source: "api" | "mock";
  warning?: string;
}
