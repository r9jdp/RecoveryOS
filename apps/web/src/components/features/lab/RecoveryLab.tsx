"use client";

import { useEffect, useState } from "react";

import { PageHeader } from "@/components/layout";
import {
  Alert,
  Badge,
  Card,
  CardBody,
  CardHeader,
  MetricCard,
  Skeleton,
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
  TableViewport,
} from "@/components/ui";
import { getLabReport, type LabReport, type LabReportResult } from "@/lib/lab";
import {
  formatPaise,
  formatProbability,
  humanize,
} from "@/lib/recovery-format";

import styles from "./lab.module.css";

function formatMetric(value: number, digits = 3): string {
  return new Intl.NumberFormat("en-IN", {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  }).format(value);
}

function shortChecksum(checksum: string): string {
  return `${checksum.slice(0, 10)}…${checksum.slice(-8)}`;
}

export function RecoveryLabLoading() {
  return (
    <div
      className={styles.page}
      aria-busy="true"
      aria-label="Loading RecoveryBench"
    >
      <Skeleton width="12rem" />
      <Skeleton width="min(32rem, 90%)" height="2.5rem" />
      <div className={styles.metricGrid}>
        {Array.from({ length: 4 }, (_, index) => (
          <Skeleton key={index} height="9rem" />
        ))}
      </div>
      <Skeleton height="20rem" />
    </div>
  );
}

function CalibrationChart({ report }: { report: LabReport }) {
  const populated = report.metrics.calibration.filter(
    (bucket) => bucket.case_count > 0,
  );
  return (
    <div
      className={styles.calibration}
      role="img"
      aria-label={populated
        .map(
          (bucket) =>
            `${Math.round(bucket.lower_bound * 100)} to ${Math.round(bucket.upper_bound * 100)} percent: predicted ${formatProbability(bucket.mean_predicted_probability)}, observed ${formatProbability(bucket.observed_recovery_rate)}, ${bucket.case_count} cases`,
        )
        .join("; ")}
    >
      <div className={styles.legend} aria-hidden="true">
        <span>
          <i className={styles.predictedKey} />
          Predicted
        </span>
        <span>
          <i className={styles.observedKey} />
          Observed
        </span>
      </div>
      <div className={styles.chartRows} aria-hidden="true">
        {populated.map((bucket) => (
          <div className={styles.chartRow} key={bucket.lower_bound}>
            <span className={styles.binLabel}>
              {Math.round(bucket.lower_bound * 100)}–
              {Math.round(bucket.upper_bound * 100)}%
            </span>
            <span className={styles.track}>
              <i
                className={styles.predictedBar}
                style={{ width: `${bucket.mean_predicted_probability * 100}%` }}
              />
              <i
                className={styles.observedBar}
                style={{ width: `${bucket.observed_recovery_rate * 100}%` }}
              />
            </span>
            <span className={styles.binCount}>{bucket.case_count}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function RecoveryLabView({
  report,
  source,
  warning,
}: {
  report: LabReport;
  source: LabReportResult["source"];
  warning?: string;
}) {
  return (
    <div className={styles.page}>
      <PageHeader
        eyebrow="Offline evaluation"
        title="RecoveryBench ML Lab"
        description="Inspect a fixed-seed, paired-cohort evaluation of recoverability ranking and calibration before any model is considered for recovery decisions."
        action={
          <div className={styles.badges}>
            <Badge tone="warning">Synthetic evaluation</Badge>
            <Badge tone={source === "api" ? "success" : "neutral"} showDot>
              {source === "api" ? "Live report" : "Bundled report"}
            </Badge>
          </div>
        }
      />

      {warning && (
        <Alert title="Live evaluation report unavailable">{warning}</Alert>
      )}
      <Alert tone="warning" title="Synthetic evaluation — not merchant revenue">
        Treatment and baseline outcomes come from the same hidden customer-state
        model and shared outcome draw. These results never modify verified
        recovered revenue.
      </Alert>

      <h2 className={styles.srOnly}>Evaluation overview</h2>
      <section
        className={styles.metricGrid}
        aria-label="Model evaluation metrics"
      >
        <MetricCard
          className={styles.metricCard}
          label="Precision–recall AUC"
          value={formatMetric(report.metrics.pr_auc)}
          delta="Higher is better for recovery ranking"
        />
        <MetricCard
          className={styles.metricCard}
          label="Brier score"
          value={formatMetric(report.metrics.brier_score)}
          delta="Lower is better for probability accuracy"
        />
        <MetricCard
          className={styles.metricCard}
          label="Top-decile lift"
          value={`${formatMetric(report.metrics.top_decile_lift, 2)}×`}
          delta="Recovery rate versus the full cohort"
        />
        <MetricCard
          className={styles.metricCard}
          label="Amount-weighted lift"
          value={`${formatMetric(report.metrics.amount_weighted_lift, 2)}×`}
          delta="Paise-weighted top decile versus cohort"
        />
      </section>

      <div className={styles.twoColumn}>
        <Card>
          <CardHeader
            title="Calibration"
            description="Predicted and observed treatment recovery by probability bin. Empty bins are omitted."
            action={
              <Badge tone="info">
                {report.dataset.evaluation_case_count} eval cases
              </Badge>
            }
          />
          <CardBody>
            <CalibrationChart report={report} />
          </CardBody>
        </Card>

        <Card>
          <CardHeader
            title="Evaluation integrity"
            description="Immutable artifact identity and deterministic cohort provenance."
          />
          <CardBody>
            <dl className={styles.detailList}>
              <div>
                <dt>Artifact</dt>
                <dd>{report.artifact.artifact_version}</dd>
              </div>
              <div>
                <dt>Model</dt>
                <dd>{report.artifact.model_type}</dd>
              </div>
              <div>
                <dt>Checksum</dt>
                <dd
                  className={styles.mono}
                  title={report.artifact.artifact_checksum}
                >
                  {shortChecksum(report.artifact.artifact_checksum)}
                </dd>
              </div>
              <div>
                <dt>Fixed seed</dt>
                <dd>{report.dataset.seed}</dd>
              </div>
              <div>
                <dt>Synthetic cases</dt>
                <dd>
                  {report.dataset.total_case_count.toLocaleString("en-IN")}
                </dd>
              </div>
              <div>
                <dt>Cohorts</dt>
                <dd>Paired treatment / baseline</dd>
              </div>
            </dl>
          </CardBody>
        </Card>
      </div>

      <h2 className={styles.srOnly}>Action evaluation</h2>
      <Card>
        <CardHeader
          title="Recovery by action"
          description="Observed paired-cohort outcomes and synthetic incremental recovery. Values are integer paise before display formatting."
          action={<Badge tone="warning">Synthetic evaluation</Badge>}
        />
        <CardBody>
          <TableViewport>
            <Table>
              <TableCaption>
                RecoveryBench evaluation grouped by candidate action
              </TableCaption>
              <TableHead>
                <TableRow>
                  <TableHeaderCell>Candidate action</TableHeaderCell>
                  <TableHeaderCell>Cases</TableHeaderCell>
                  <TableHeaderCell>Treatment / baseline</TableHeaderCell>
                  <TableHeaderCell>Predicted</TableHeaderCell>
                  <TableHeaderCell>Observed</TableHeaderCell>
                  <TableHeaderCell>Synthetic incremental</TableHeaderCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {report.metrics.recovery_by_action.map((item) => (
                  <TableRow key={item.action}>
                    <TableCell>
                      <strong>{humanize(item.action)}</strong>
                    </TableCell>
                    <TableCell>{item.case_count}</TableCell>
                    <TableCell>
                      {item.treatment_recovered_count} /{" "}
                      {item.baseline_recovered_count}
                    </TableCell>
                    <TableCell>
                      {formatProbability(item.mean_predicted_probability)}
                    </TableCell>
                    <TableCell>
                      {formatProbability(item.observed_treatment_recovery_rate)}
                    </TableCell>
                    <TableCell>
                      {formatPaise(item.simulated_incremental_recovery_paise)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableViewport>
          <div className={styles.incrementalTotal}>
            <span>Synthetic incremental recovery across evaluation cohort</span>
            <strong>
              {formatPaise(report.metrics.simulated_incremental_recovery_paise)}
            </strong>
          </div>
        </CardBody>
      </Card>
    </div>
  );
}

export function RecoveryLab() {
  const [result, setResult] = useState<LabReportResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getLabReport(controller.signal)
      .then(setResult)
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError")
          return;
        setError(
          reason instanceof Error
            ? reason.message
            : "RecoveryBench could not load.",
        );
      });
    return () => controller.abort();
  }, []);

  if (error)
    return (
      <Alert tone="danger" title="RecoveryBench unavailable">
        {error}
      </Alert>
    );
  if (!result) return <RecoveryLabLoading />;
  return (
    <RecoveryLabView
      report={result.data}
      source={result.source}
      warning={result.warning}
    />
  );
}
