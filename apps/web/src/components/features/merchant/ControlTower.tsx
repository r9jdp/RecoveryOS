"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { PageHeader } from "@/components/layout";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
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
import { useRecoveryResource } from "@/hooks/use-recovery-resource";
import { getDashboard } from "@/lib/api/recovery-client";
import { approvalItems } from "@/lib/merchant-demo";
import {
  formatBasisPoints,
  formatDateTime,
  formatEvidenceKind,
  formatPaise,
  humanize,
} from "@/lib/recovery-format";
import type {
  DashboardCase,
  DashboardFixture,
  PaymentSurfaceType,
} from "@/types/recovery";

import styles from "./merchant.module.css";

function outcomeTone(
  outcome: DashboardCase["case_outcome"],
): "neutral" | "info" | "success" | "warning" | "danger" {
  if (outcome === "RECOVERED") return "success";
  if (outcome === "STOPPED" || outcome === "DISPUTED" || outcome === "EXPIRED")
    return "danger";
  if (outcome === "ESCALATED" || outcome === "PARTIALLY_RECOVERED")
    return "warning";
  return "info";
}

export function DashboardLoading() {
  return (
    <div
      className={styles.pageStack}
      aria-busy="true"
      aria-label="Loading Control Tower"
    >
      <div className={styles.stack}>
        <Skeleton width="9rem" height="0.75rem" />
        <Skeleton width="min(32rem, 90%)" height="2.5rem" />
        <Skeleton width="min(42rem, 100%)" height="1rem" />
      </div>
      <div className={styles.skeletonGrid}>
        {Array.from({ length: 4 }, (_, index) => (
          <div className={styles.skeletonCard} key={index}>
            <Skeleton width="55%" />
            <Skeleton width="72%" height="2rem" />
          </div>
        ))}
      </div>
      <div className={styles.skeletonCard}>
        <Skeleton width="30%" height="1.5rem" />
        <Skeleton height="8rem" />
      </div>
    </div>
  );
}

function ControlTowerContent({
  fixture,
  source,
}: {
  fixture: DashboardFixture;
  source: "api" | "mock";
}) {
  const [query, setQuery] = useState("");
  const [outcome, setOutcome] = useState("ALL");
  const [surface, setSurface] = useState<"ALL" | PaymentSurfaceType>("ALL");
  const normalizedQuery = query.trim().toLowerCase();
  const filteredCases = useMemo(
    () =>
      fixture.cases.filter(
        (recoveryCase) =>
          (outcome === "ALL" || recoveryCase.case_outcome === outcome) &&
          (surface === "ALL" ||
            recoveryCase.payment_surface_type === surface) &&
          [
            recoveryCase.id,
            recoveryCase.customer_display_name,
            recoveryCase.plan_name,
            recoveryCase.diagnosis,
          ].some((value) => value.toLowerCase().includes(normalizedQuery)),
      ),
    [fixture.cases, normalizedQuery, outcome, surface],
  );
  const maxDiagnosisCount = Math.max(
    ...fixture.diagnosis_distribution.map((item) => item.case_count),
    1,
  );
  const displayedHumanReviewCount = Math.max(
    fixture.metrics.human_review_count,
    source === "mock" ? approvalItems.length : 0,
  );

  return (
    <div className={styles.pageStack}>
      <PageHeader
        eyebrow="Live recovery operations"
        title="Control Tower"
        description="See every failed billing cycle, the evidence behind its diagnosis, and the safest next action from one auditable workspace."
        action={
          <Badge tone={source === "api" ? "success" : "neutral"} showDot>
            {source === "api" ? "API connected" : "Simulated"}
          </Badge>
        }
      />

      <section aria-labelledby="metrics-heading">
        <h2 id="metrics-heading" className={styles.srOnly}>
          Recovery overview
        </h2>
        <div className={styles.summaryGrid}>
          <MetricCard
            label="Revenue at risk"
            value={formatPaise(fixture.metrics.revenue_at_risk_paise)}
            delta={`${fixture.metrics.active_cases} active billing cycle${fixture.metrics.active_cases === 1 ? "" : "s"}`}
          />
          <MetricCard
            label="Verified recovered"
            value={formatPaise(
              fixture.metrics.verified_recovered_revenue_paise,
            )}
            delta="Authoritative provider events only"
            badge={<Badge tone="success">Verified</Badge>}
          />
          <MetricCard
            label="Recovery rate"
            value={formatBasisPoints(
              fixture.metrics.recovery_rate_basis_points,
            )}
            delta="Verified revenue / eligible arrears"
          />
          <MetricCard
            label="Needs human review"
            value={String(displayedHumanReviewCount)}
            delta={`${fixture.metrics.policy_blocked_actions} policy-blocked action${fixture.metrics.policy_blocked_actions === 1 ? "" : "s"}`}
            badge={
              <Badge
                tone={displayedHumanReviewCount > 0 ? "warning" : "neutral"}
              >
                Review
              </Badge>
            }
          />
        </div>
      </section>

      <div className={styles.twoColumn}>
        <Card>
          <CardHeader
            title="Diagnosis distribution"
            description="Deterministic diagnosis across active invoice-scoped cases."
            action={
              <Badge tone="info">{fixture.metrics.active_cases} active</Badge>
            }
          />
          <CardBody>
            {fixture.diagnosis_distribution.length > 0 ? (
              <div className={styles.diagnosisBars}>
                {fixture.diagnosis_distribution.map((item) => (
                  <div key={item.diagnosis}>
                    <div className={styles.diagnosisHeader}>
                      <p className={styles.diagnosisLabel}>
                        {humanize(item.diagnosis)}
                      </p>
                      <p className={styles.diagnosisCount}>{item.case_count}</p>
                    </div>
                    <div className={styles.diagnosisTrack} aria-hidden="true">
                      <div
                        className={styles.diagnosisBar}
                        style={{
                          width: `${(item.case_count * 100) / maxDiagnosisCount}%`,
                        }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <EmptyState
                title="No diagnosis data"
                description="Diagnosis counts appear after a failed payment is correlated."
              />
            )}
          </CardBody>
        </Card>

        <Card id="audit">
          <CardHeader
            title="Recent audit events"
            description="Correlated decisions and recovery state changes."
          />
          <CardBody>
            {fixture.recent_events.length > 0 ? (
              <ol className={styles.auditList}>
                {fixture.recent_events.map((event) => (
                  <li className={styles.auditItem} key={event.id}>
                    <span className={styles.auditDot} aria-hidden="true" />
                    <div>
                      <p className={styles.reasonTitle}>
                        {humanize(event.event_type)}
                      </p>
                      <p className={styles.quiet}>
                        {formatDateTime(event.occurred_at)}
                      </p>
                      <p className={styles.mono}>{event.correlation_id}</p>
                    </div>
                  </li>
                ))}
              </ol>
            ) : (
              <EmptyState
                title="No audit events"
                description="Events will appear when a recovery case changes."
              />
            )}
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader
          title="Recovery channels"
          description="Invoice-safe surfaces and assisted channels across active cases."
          action={
            <Badge tone="neutral">
              Evidence: {formatEvidenceKind(fixture.evidence_kind)}
            </Badge>
          }
        />
        <CardBody>
          <div className={styles.channelGrid}>
            {fixture.recovery_by_channel.map((channel) => (
              <div className={styles.channelCard} key={channel.channel}>
                <div className={styles.split}>
                  <p className={styles.reasonTitle}>
                    {humanize(channel.channel)}
                  </p>
                  <Badge tone={channel.case_count ? "info" : "neutral"}>
                    {channel.case_count} cases
                  </Badge>
                </div>
                <p className={styles.channelValue}>
                  {formatPaise(channel.recovered_paise)}
                </p>
                <p className={styles.quiet}>Authoritatively recovered</p>
              </div>
            ))}
          </div>
        </CardBody>
      </Card>

      <section aria-labelledby="active-cases-heading" className={styles.stack}>
        <div className={styles.split}>
          <div>
            <h2 id="active-cases-heading" className={styles.sectionTitle}>
              Active recovery cases
            </h2>
            <p className={styles.sectionCopy}>
              Invoice-scoped cases, ordered by their latest activity.
            </p>
          </div>
          <div className={styles.filterControls}>
            <label>
              <span className={styles.label}>Search cases</span>
              <input
                className={styles.filterInput}
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Customer, case, plan, diagnosis"
              />
            </label>
            <label>
              <span className={styles.label}>Outcome</span>
              <select
                aria-label="Filter by outcome"
                className={styles.filterSelect}
                value={outcome}
                onChange={(event) => setOutcome(event.target.value)}
              >
                <option value="ALL">All outcomes</option>
                <option value="OPEN">Open</option>
                <option value="ESCALATED">Escalated</option>
                <option value="RECOVERED">Recovered</option>
              </select>
            </label>
            <label>
              <span className={styles.label}>Payment surface</span>
              <select
                aria-label="Filter by payment surface"
                className={styles.filterSelect}
                value={surface}
                onChange={(event) =>
                  setSurface(event.target.value as "ALL" | PaymentSurfaceType)
                }
              >
                <option value="ALL">All surfaces</option>
                <option value="SUBSCRIPTION_CARD_UPDATE">Card update</option>
                <option value="SUBSCRIPTION_INVOICE_LINK">Invoice link</option>
                <option value="STANDARD_PAYMENT_LINK">Payment link</option>
              </select>
            </label>
          </div>
        </div>

        {filteredCases.length > 0 ? (
          <TableViewport>
            <Table>
              <TableCaption>
                Active recovery cases. Open a case to inspect evidence and
                approve an action.
              </TableCaption>
              <TableHead>
                <TableRow>
                  <TableHeaderCell>Case</TableHeaderCell>
                  <TableHeaderCell>Customer</TableHeaderCell>
                  <TableHeaderCell>Diagnosis</TableHeaderCell>
                  <TableHeaderCell>Amount at risk</TableHeaderCell>
                  <TableHeaderCell>Subscription</TableHeaderCell>
                  <TableHeaderCell>Outcome</TableHeaderCell>
                  <TableHeaderCell>Updated</TableHeaderCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {filteredCases.map((recoveryCase) => (
                  <TableRow key={recoveryCase.id}>
                    <TableCell>
                      <Link
                        className={styles.caseLink}
                        href={`/cases/${recoveryCase.id}`}
                      >
                        {recoveryCase.id
                          .replace("case_", "REC-")
                          .replaceAll("_", "-")
                          .toUpperCase()}
                      </Link>
                      <p className={styles.mono}>
                        {recoveryCase.failed_invoice_id}
                      </p>
                    </TableCell>
                    <TableCell>
                      <strong>{recoveryCase.customer_display_name}</strong>
                      <p className={styles.quiet}>{recoveryCase.plan_name}</p>
                    </TableCell>
                    <TableCell>{humanize(recoveryCase.diagnosis)}</TableCell>
                    <TableCell>
                      {formatPaise(recoveryCase.amount_at_risk_paise)}
                    </TableCell>
                    <TableCell>
                      <Badge tone="warning">
                        {humanize(recoveryCase.subscription_state)}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge tone={outcomeTone(recoveryCase.case_outcome)}>
                        {humanize(recoveryCase.case_outcome)}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      {formatDateTime(recoveryCase.updated_at)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableViewport>
        ) : (
          <EmptyState
            title="No matching cases"
            description="Change the filter or clear it to return to all active recovery cases."
            action={
              <Button
                variant="secondary"
                size="sm"
                onClick={() => {
                  setQuery("");
                  setOutcome("ALL");
                  setSurface("ALL");
                }}
              >
                Clear filter
              </Button>
            }
          />
        )}
      </section>
    </div>
  );
}

export function ControlTower() {
  const resource = useRecoveryResource(getDashboard);

  if (resource.loading) {
    return <DashboardLoading />;
  }

  if (resource.error || !resource.data || !resource.source) {
    return (
      <EmptyState
        title="Control Tower could not load"
        description={resource.error ?? "The dashboard response was empty."}
        action={<Button onClick={resource.reload}>Try again</Button>}
      />
    );
  }

  return (
    <div className={styles.pageStack}>
      {resource.warning && (
        <Alert tone="info" title="Demo data active">
          {resource.warning}
        </Alert>
      )}
      <ControlTowerContent fixture={resource.data} source={resource.source} />
    </div>
  );
}
