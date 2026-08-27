"use client";

import Link from "next/link";
import { useCallback, useMemo, useState } from "react";

import {
  Alert,
  Badge,
  Button,
  Card,
  CardBody,
  CardFooter,
  CardHeader,
  EmptyState,
  Skeleton,
} from "@/components/ui";
import { useRecoveryResource } from "@/hooks/use-recovery-resource";
import { executeCaseCommand, getCaseDetail } from "@/lib/api/recovery-client";
import {
  formatDateTime,
  formatPaise,
  formatProbability,
  humanize,
} from "@/lib/recovery-format";
import type {
  CaseCommand,
  CaseDetailFixture,
  CaseOutcome,
  CommandResult,
} from "@/types/recovery";

import styles from "./merchant.module.css";

function caseOutcomeTone(
  outcome: CaseOutcome,
): "neutral" | "info" | "success" | "warning" | "danger" {
  if (outcome === "RECOVERED") return "success";
  if (outcome === "ESCALATED" || outcome === "PARTIALLY_RECOVERED")
    return "warning";
  if (outcome === "STOPPED" || outcome === "DISPUTED" || outcome === "EXPIRED")
    return "danger";
  return "info";
}

function optimisticOutcome(
  command: CaseCommand,
  current: CaseOutcome,
): CaseOutcome {
  if (command === "ESCALATE_TO_HUMAN") return "ESCALATED";
  if (command === "STOP" || command === "REJECT") return "STOPPED";
  return current;
}

function ActionLabel({ command }: { command: CaseCommand }) {
  const labels: Record<CaseCommand, string> = {
    APPROVE: "Approve recovery",
    ESCALATE_TO_HUMAN: "Escalate to human",
    REJECT: "Reject action",
    STOP: "Stop recovery",
  };
  return labels[command];
}

export function CaseLoading() {
  return (
    <div
      className={styles.pageStack}
      aria-busy="true"
      aria-label="Loading case workspace"
    >
      <div className={styles.stack}>
        <Skeleton width="8rem" />
        <Skeleton width="min(34rem, 90%)" height="2.5rem" />
        <Skeleton width="min(42rem, 100%)" />
      </div>
      <div className={styles.skeletonGrid}>
        {Array.from({ length: 4 }, (_, index) => (
          <div className={styles.skeletonCard} key={index}>
            <Skeleton width="55%" />
            <Skeleton width="75%" height="1.75rem" />
          </div>
        ))}
      </div>
      <div className={styles.twoColumn}>
        <div className={styles.skeletonCard}>
          <Skeleton height="16rem" />
        </div>
        <div className={styles.skeletonCard}>
          <Skeleton height="16rem" />
        </div>
      </div>
    </div>
  );
}

function CaseContent({
  fixture,
  source,
}: {
  fixture: CaseDetailFixture;
  source: "api" | "mock";
}) {
  const [pendingCommand, setPendingCommand] = useState<CaseCommand | null>(
    null,
  );
  const [result, setResult] = useState<CommandResult | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [displayedOutcome, setDisplayedOutcome] = useState(
    fixture.case.case_outcome,
  );

  const execute = useCallback(
    async (command: CaseCommand) => {
      const previousOutcome = displayedOutcome;
      setPendingCommand(command);
      setActionError(null);
      setResult(null);
      setDisplayedOutcome(optimisticOutcome(command, displayedOutcome));
      try {
        const commandResult = await executeCaseCommand(
          fixture.case.id,
          command,
        );
        setResult(commandResult);
      } catch (error) {
        setDisplayedOutcome(previousOutcome);
        setActionError(
          error instanceof Error
            ? error.message
            : "The command could not be submitted.",
        );
      } finally {
        setPendingCommand(null);
      }
    },
    [displayedOutcome, fixture.case.id],
  );

  const timeline = useMemo(() => {
    const base = fixture.timeline.map((event) => ({
      description: `Source: ${event.source} · Evidence: ${humanize(event.evidence_kind)}`,
      id: event.id,
      meta: `${formatDateTime(event.occurred_at)} · ${event.correlation_id}`,
      optimistic: false,
      title: humanize(event.event_type),
    }));

    if (pendingCommand) {
      base.push({
        description:
          "Optimistic UI only. The case will roll back if the command is rejected.",
        id: `pending-${pendingCommand}`,
        meta: "Submitting now",
        optimistic: true,
        title: `${humanize(pendingCommand)} requested`,
      });
    } else if (result) {
      base.push({
        description: result.message,
        id: `result-${result.command}-${result.occurred_at}`,
        meta: `${formatDateTime(result.occurred_at)} · ${humanize(result.source)}`,
        optimistic: false,
        title: `${humanize(result.command)} accepted`,
      });
    }
    return base;
  }, [fixture.timeline, pendingCommand, result]);

  const canRun = (command: CaseCommand) =>
    fixture.available_commands.includes(command);
  const recoveryCase = fixture.case;

  return (
    <div className={styles.pageStack}>
      <div className={styles.stack}>
        <Link className={styles.textLink} href="/dashboard">
          ← Back to Control Tower
        </Link>
        <div className={styles.split}>
          <div>
            <p className={styles.loginEyebrow}>Case workspace</p>
            <div className={styles.caseIdentity}>
              <h1 className={styles.caseTitle}>
                {fixture.customer.display_name} ·{" "}
                {fixture.subscription.plan_name}
              </h1>
              <Badge tone={caseOutcomeTone(displayedOutcome)} showDot>
                {humanize(displayedOutcome)}
              </Badge>
            </div>
            <p className={styles.sectionCopy}>
              {recoveryCase.id} · Failed invoice{" "}
              {recoveryCase.key.failed_invoice_id} · Billing cycle{" "}
              {recoveryCase.key.billing_cycle_key}
            </p>
          </div>
          <Badge tone={source === "api" ? "success" : "neutral"} showDot>
            {source === "api" ? "API connected" : "Simulated evidence"}
          </Badge>
        </div>
      </div>

      <section aria-label="Case state" className={styles.summaryGrid}>
        <Card>
          <CardBody>
            <p className={styles.label}>Amount at risk</p>
            <p className={styles.value}>
              {formatPaise(recoveryCase.amount_at_risk_paise)}
            </p>
          </CardBody>
        </Card>
        <Card>
          <CardBody>
            <p className={styles.label}>Payment state</p>
            <p className={styles.value}>
              {humanize(recoveryCase.payment_state)}
            </p>
          </CardBody>
        </Card>
        <Card>
          <CardBody>
            <p className={styles.label}>Subscription state</p>
            <p className={styles.value}>
              {humanize(recoveryCase.subscription_state)}
            </p>
          </CardBody>
        </Card>
        <Card>
          <CardBody>
            <p className={styles.label}>Recovery deadline</p>
            <p className={styles.value}>
              {formatDateTime(recoveryCase.recovery_deadline)}
            </p>
          </CardBody>
        </Card>
      </section>

      <Card className={styles.actionDock}>
        <CardBody>
          <div className={styles.split}>
            <div>
              <h2 className={styles.cardHeading}>Operator decision</h2>
              <p className={styles.cardCopy}>
                Commands are auditable. In demo mode they never contact a real
                provider.
              </p>
            </div>
            <div className={styles.actionRow} aria-label="Case actions">
              <Button
                loading={pendingCommand === "APPROVE"}
                disabled={!canRun("APPROVE") || pendingCommand !== null}
                onClick={() => execute("APPROVE")}
              >
                <ActionLabel command="APPROVE" />
              </Button>
              <Button
                variant="secondary"
                loading={pendingCommand === "ESCALATE_TO_HUMAN"}
                disabled={
                  !canRun("ESCALATE_TO_HUMAN") || pendingCommand !== null
                }
                onClick={() => execute("ESCALATE_TO_HUMAN")}
              >
                <ActionLabel command="ESCALATE_TO_HUMAN" />
              </Button>
              <Button
                variant="ghost"
                loading={pendingCommand === "REJECT"}
                disabled={!canRun("REJECT") || pendingCommand !== null}
                onClick={() => execute("REJECT")}
              >
                <ActionLabel command="REJECT" />
              </Button>
              <Button
                variant="danger"
                loading={pendingCommand === "STOP"}
                disabled={!canRun("STOP") || pendingCommand !== null}
                onClick={() => execute("STOP")}
              >
                <ActionLabel command="STOP" />
              </Button>
            </div>
          </div>
          <div aria-live="polite">
            {result && (
              <Alert
                tone="success"
                title={`${humanize(result.command)} accepted`}
              >
                {result.message}
              </Alert>
            )}
            {actionError && (
              <Alert tone="danger" title="Command was not applied">
                {actionError}
              </Alert>
            )}
          </div>
        </CardBody>
      </Card>

      <div className={styles.twoColumn}>
        <Card className={styles.recommendationCard}>
          <CardHeader
            title="Recommended recovery action"
            description="Ranked by expected utility after deterministic policy checks."
            action={
              <Badge
                tone={
                  fixture.policy.disposition === "ALLOW" ? "success" : "warning"
                }
              >
                {humanize(fixture.policy.disposition)}
              </Badge>
            }
          />
          <CardBody>
            <div className={styles.split}>
              <div>
                <p className={styles.label}>Action</p>
                <p className={styles.value}>
                  {humanize(fixture.recommendation.action)}
                </p>
                {fixture.recommendation.payment_surface_type && (
                  <p className={styles.quiet}>
                    {humanize(fixture.recommendation.payment_surface_type)}
                  </p>
                )}
              </div>
              <div>
                <p className={styles.label}>Predicted recovery</p>
                <p className={styles.probability}>
                  {formatProbability(
                    fixture.recommendation.predicted_recovery_probability,
                  )}
                </p>
                <p className={styles.quiet}>
                  {formatProbability(fixture.recommendation.confidence)}{" "}
                  confidence
                </p>
              </div>
            </div>
            <ul className={styles.reasonList}>
              {fixture.recommendation.reasons.map((reason, index) => (
                <li
                  className={styles.reasonItem}
                  key={fixture.recommendation.reason_codes[index] ?? reason}
                >
                  <p className={styles.reasonTitle}>{reason}</p>
                  <p className={styles.mono}>
                    {fixture.recommendation.reason_codes[index]}
                  </p>
                </li>
              ))}
            </ul>
          </CardBody>
          <CardFooter>
            <div className={styles.statRow}>
              <div>
                <p className={styles.label}>Expected recovered</p>
                <p className={styles.value}>
                  {formatPaise(fixture.recommendation.expected_recovered_paise)}
                </p>
              </div>
              <div>
                <p className={styles.label}>Expected utility</p>
                <p className={styles.value}>
                  {formatPaise(fixture.recommendation.expected_utility_paise)}
                </p>
              </div>
            </div>
          </CardFooter>
        </Card>

        <Card>
          <CardHeader
            title="Diagnosis evidence"
            description="Inspectable facts used by the decision engine."
          />
          <CardBody>
            <div className={styles.stack}>
              <Alert tone="warning" title={humanize(recoveryCase.diagnosis)}>
                {humanize(fixture.payment_failure.error_reason)} during{" "}
                {humanize(fixture.payment_failure.error_step)}.
              </Alert>
              <ul className={styles.evidenceList}>
                {fixture.evidence.map((item) => (
                  <li
                    className={styles.evidenceItem}
                    key={`${item.source_event}-${item.field}`}
                  >
                    <div className={styles.split}>
                      <p className={styles.reasonTitle}>
                        {humanize(item.field)}
                      </p>
                      <Badge
                        tone={item.kind === "SIMULATED" ? "neutral" : "success"}
                      >
                        {humanize(item.kind)}
                      </Badge>
                    </div>
                    <p className={styles.value}>{humanize(item.value)}</p>
                    <p className={styles.mono}>Source: {item.source_event}</p>
                  </li>
                ))}
              </ul>
            </div>
          </CardBody>
        </Card>
      </div>

      <div className={styles.twoColumn}>
        <Card>
          <CardHeader
            title="Policy decision"
            description={`${fixture.policy.policy_version} · ${fixture.policy.decision_code}`}
          />
          <CardBody>
            <ul className={styles.reasonList}>
              {fixture.policy.reasons.map((reason, index) => (
                <li
                  className={styles.reasonItem}
                  key={fixture.policy.reason_codes[index] ?? reason}
                >
                  <p className={styles.reasonTitle}>{reason}</p>
                  <p className={styles.mono}>
                    {fixture.policy.reason_codes[index]}
                  </p>
                </li>
              ))}
            </ul>
          </CardBody>
        </Card>

        <Card>
          <CardHeader
            title="Rejected alternatives"
            description="Why apparently valid paths were ruled out."
          />
          <CardBody>
            <ul className={styles.reasonList}>
              {fixture.recommendation.rejected_alternatives.map(
                (alternative) => (
                  <li
                    className={styles.reasonItem}
                    key={`${alternative.action}-${alternative.reason_code}`}
                  >
                    <p className={styles.reasonTitle}>
                      {humanize(alternative.action)}
                      {alternative.payment_surface_type
                        ? ` · ${humanize(alternative.payment_surface_type)}`
                        : ""}
                    </p>
                    <p className={styles.quiet}>{alternative.reason}</p>
                    <p className={styles.mono}>{alternative.reason_code}</p>
                  </li>
                ),
              )}
            </ul>
          </CardBody>
        </Card>
      </div>

      <div className={styles.twoColumn}>
        <Card>
          <CardHeader
            title="Customer and payment context"
            description="Independent case, payment, subscription, and contact facts."
          />
          <CardBody>
            <dl className={styles.detailList}>
              <div>
                <dt>Customer</dt>
                <dd>{fixture.customer.display_name}</dd>
              </div>
              <div>
                <dt>Preferred language</dt>
                <dd>{fixture.customer.preferred_language}</dd>
              </div>
              <div>
                <dt>Contact disposition</dt>
                <dd>{humanize(recoveryCase.contact_disposition)}</dd>
              </div>
              <div>
                <dt>Voice consent</dt>
                <dd>
                  {fixture.customer.voice_consent ? "Recorded" : "Not recorded"}
                </dd>
              </div>
              <div>
                <dt>Payment method</dt>
                <dd>{humanize(fixture.payment_failure.method)}</dd>
              </div>
              <div>
                <dt>Payment ID</dt>
                <dd>{fixture.payment_failure.payment_id}</dd>
              </div>
              <div>
                <dt>Payment surface</dt>
                <dd>{humanize(fixture.payment_surface.type)}</dd>
              </div>
              <div>
                <dt>Surface status</dt>
                <dd>{humanize(fixture.payment_surface.status)}</dd>
              </div>
              <div>
                <dt>Arrears collected</dt>
                <dd>{formatPaise(recoveryCase.arrears_collected_paise)}</dd>
              </div>
              <div>
                <dt>Subscription reactivated</dt>
                <dd>{recoveryCase.subscription_reactivated ? "Yes" : "No"}</dd>
              </div>
            </dl>
          </CardBody>
        </Card>

        <Card>
          <CardHeader
            title="Case timeline"
            description="Provider facts and RecoveryOS decisions in causal order."
          />
          <CardBody>
            <ol className={styles.timelineList} aria-live="polite">
              {timeline.map((event) => (
                <li className={styles.timelineItem} key={event.id}>
                  <span
                    className={`${styles.timelineMarker} ${event.optimistic ? styles.timelineMarkerOptimistic : ""}`}
                    aria-hidden="true"
                  />
                  <div>
                    <p className={styles.timelineTitle}>{event.title}</p>
                    <p className={styles.timelineMeta}>{event.meta}</p>
                    <p className={styles.timelineDescription}>
                      {event.description}
                    </p>
                  </div>
                </li>
              ))}
            </ol>
          </CardBody>
        </Card>
      </div>
    </div>
  );
}

export function CaseWorkspace({ caseId }: { caseId: string }) {
  const loader = useCallback(
    (signal: AbortSignal) => getCaseDetail(caseId, signal),
    [caseId],
  );
  const resource = useRecoveryResource(loader);

  if (resource.loading) return <CaseLoading />;

  if (resource.error || !resource.data || !resource.source) {
    return (
      <EmptyState
        title="Case workspace could not load"
        description={resource.error ?? "The case response was empty."}
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
      <CaseContent fixture={resource.data} source={resource.source} />
    </div>
  );
}
