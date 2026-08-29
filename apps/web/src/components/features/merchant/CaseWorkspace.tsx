"use client";

import {
  ArrowLeft,
  CheckCircle2,
  ChevronDown,
  CircleAlert,
  ExternalLink,
  LoaderCircle,
  ShieldCheck,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useMemo, useState, type ReactNode } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/shadcn/alert";
import { Badge } from "@/components/shadcn/badge";
import { Button } from "@/components/shadcn/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/shadcn/card";
import { Separator } from "@/components/shadcn/separator";
import { Skeleton } from "@/components/shadcn/skeleton";
import { useRecoveryResource } from "@/hooks/use-recovery-resource";
import {
  executeCaseCommand,
  executeSafetyDisposition,
  getCaseDetail,
} from "@/lib/api/recovery-client";
import { cn } from "@/lib/utils";
import {
  formatDateTime,
  formatEvidenceKind,
  formatPaise,
  formatProbability,
  humanize,
} from "@/lib/recovery-format";
import type {
  CaseCommand,
  CaseDetailFixture,
  CaseOutcome,
  CommandResult,
  ContactDisposition,
  PaymentState,
  PaymentSurfaceType,
  SafetyDisposition,
  SafetyDispositionResult,
  SubscriptionState,
} from "@/types/recovery";

import { ConfirmDialog } from "./ConfirmDialog";

type BadgeVariant =
  | "default"
  | "secondary"
  | "destructive"
  | "success"
  | "warning"
  | "info"
  | "outline"
  | "ghost"
  | "link";

function caseOutcomeVariant(outcome: CaseOutcome): BadgeVariant {
  if (
    outcome === "STOPPED" ||
    outcome === "DISPUTED" ||
    outcome === "EXPIRED"
  ) {
    return "destructive";
  }
  if (outcome === "RECOVERED") return "success";
  if (outcome === "ESCALATED" || outcome === "PARTIALLY_RECOVERED") {
    return "warning";
  }
  return "info";
}

function policyVariant(
  disposition: CaseDetailFixture["policy"]["disposition"],
): BadgeVariant {
  if (disposition === "BLOCK") return "destructive";
  if (disposition === "ALLOW") return "success";
  return "warning";
}

function paymentStateTone(state: PaymentState): string {
  if (state === "CAPTURED") return "text-success";
  if (state === "FAILED" || state === "REFUNDED") return "text-destructive";
  if (state === "PENDING" || state === "AUTHORIZED") return "text-warning";
  return "text-muted-foreground";
}

function subscriptionStateTone(state: SubscriptionState): string {
  if (
    state === "ACTIVE" ||
    state === "AUTHENTICATED" ||
    state === "COMPLETED"
  ) {
    return "text-success";
  }
  if (state === "HALTED" || state === "CANCELLED") {
    return "text-destructive";
  }
  if (state === "PENDING" || state === "CREATED" || state === "PAUSED") {
    return "text-warning";
  }
  return "text-muted-foreground";
}

function optimisticOutcome(
  command: CaseCommand,
  current: CaseOutcome,
): CaseOutcome {
  if (command === "ESCALATE_TO_HUMAN") return "ESCALATED";
  if (command === "STOP" || command === "REJECT") return "STOPPED";
  return current;
}

function paymentSurfaceLabel(type: PaymentSurfaceType | null): string {
  return type ? humanize(type) : "Not selected";
}

function customerInstruction(type: PaymentSurfaceType | null): string {
  if (type === "SUBSCRIPTION_CARD_UPDATE") {
    return "Update the saved card and complete authentication";
  }
  if (type === "SUBSCRIPTION_INVOICE_LINK") {
    return "Open the subscription invoice and pay the outstanding amount";
  }
  if (type === "STANDARD_PAYMENT_LINK") {
    return "Open the secure payment link and complete payment";
  }
  return "Complete the operator-approved recovery step";
}

function safetyContactDisposition(
  disposition: SafetyDisposition,
  current: ContactDisposition,
): ContactDisposition {
  if (disposition === "MARK_DISPUTE") return "DISPUTE";
  if (disposition === "MARK_OPT_OUT") return "OPTED_OUT";
  if (disposition === "MARK_WRONG_PERSON") return "WRONG_PERSON";
  if (disposition === "MARK_ALREADY_PAID") return "ALREADY_PAID";
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

function CommandButtonLabel({
  command,
  pendingCommand,
}: {
  command: CaseCommand;
  pendingCommand: CaseCommand | null;
}) {
  return (
    <>
      {pendingCommand === command && (
        <LoaderCircle
          className="animate-spin motion-reduce:animate-none"
          data-icon="inline-start"
        />
      )}
      <ActionLabel command={command} />
    </>
  );
}

function Disclosure({
  children,
  defaultOpen = false,
  description,
  title,
}: {
  children: ReactNode;
  defaultOpen?: boolean;
  description: string;
  title: string;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <details
      className="group rounded-xl border border-border bg-card"
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary className="flex cursor-pointer list-none items-center justify-between gap-4 px-4 py-3 [&::-webkit-details-marker]:hidden">
        <span className="flex min-w-0 flex-col gap-0.5">
          <strong className="text-sm font-medium">{title}</strong>
          <small className="truncate text-xs text-muted-foreground">
            {description}
          </small>
        </span>
        <ChevronDown
          className="size-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-180 motion-reduce:transition-none"
          aria-hidden="true"
        />
      </summary>
      <Separator />
      <div className="flex flex-col gap-4 p-4">{children}</div>
    </details>
  );
}

function DetailGrid({
  items,
}: {
  items: Array<{ label: string; value: ReactNode }>;
}) {
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
      {items.map((item) => (
        <div className="min-w-0" key={item.label}>
          <dt className="text-xs text-muted-foreground">{item.label}</dt>
          <dd className="mt-1 break-words text-sm font-medium">{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function CaseLoading() {
  return (
    <div
      className="flex flex-col gap-4"
      aria-busy="true"
      aria-label="Loading case workspace"
    >
      <div className="flex flex-col gap-2">
        <Skeleton className="h-7 w-32" />
        <Skeleton className="h-8 w-full max-w-lg" />
        <Skeleton className="h-4 w-full max-w-xl" />
      </div>
      <Card size="sm">
        <CardHeader>
          <CardTitle>
            <Skeleton className="h-4 w-28" />
          </CardTitle>
          <CardDescription>
            <Skeleton className="h-3 w-44" />
          </CardDescription>
        </CardHeader>
        <CardContent className="grid grid-cols-2 gap-4 md:grid-cols-4">
          {Array.from({ length: 4 }, (_, index) => (
            <div className="flex flex-col gap-2" key={index}>
              <Skeleton className="h-3 w-20" />
              <Skeleton className="h-5 w-28 max-w-full" />
            </div>
          ))}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>
            <Skeleton className="h-5 w-48" />
          </CardTitle>
          <CardDescription>
            <Skeleton className="h-4 w-full max-w-md" />
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-3/4" />
        </CardContent>
        <CardFooter className="gap-2">
          <Skeleton className="h-8 w-32" />
          <Skeleton className="h-8 w-32" />
        </CardFooter>
      </Card>
    </div>
  );
}

function CaseContent({
  fixture,
  onRefresh,
  source,
}: {
  fixture: CaseDetailFixture;
  onRefresh: () => void;
  source: "api" | "mock";
}) {
  const [pendingCommand, setPendingCommand] = useState<CaseCommand | null>(
    null,
  );
  const [result, setResult] = useState<CommandResult | null>(null);
  const [safetyResult, setSafetyResult] =
    useState<SafetyDispositionResult | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [displayedOutcome, setDisplayedOutcome] = useState(
    fixture.case.case_outcome,
  );
  const [displayedContactDisposition, setDisplayedContactDisposition] =
    useState(fixture.case.contact_disposition);
  const [selectedSafety, setSelectedSafety] =
    useState<SafetyDisposition | null>(null);
  const [safetyPending, setSafetyPending] = useState(false);

  const execute = useCallback(
    async (command: CaseCommand) => {
      const previousOutcome = displayedOutcome;
      setPendingCommand(command);
      setActionError(null);
      setResult(null);
      setSafetyResult(null);
      setDisplayedOutcome(optimisticOutcome(command, displayedOutcome));
      try {
        const commandResult = await executeCaseCommand(
          fixture.case.id,
          command,
        );
        if (source === "api") onRefresh();
        else setResult(commandResult);
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
    [displayedOutcome, fixture.case.id, onRefresh, source],
  );

  const timeline = useMemo(() => {
    const base = fixture.timeline.map((event) => ({
      description: `Source: ${event.source} · Evidence: ${formatEvidenceKind(event.evidence_kind)}`,
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
    } else if (safetyResult) {
      base.push({
        description: safetyResult.message,
        id: `safety-${safetyResult.disposition}-${safetyResult.occurred_at}`,
        meta: `${formatDateTime(safetyResult.occurred_at)} · ${humanize(safetyResult.source)}`,
        optimistic: false,
        title: `${humanize(safetyResult.disposition)} recorded`,
      });
    }
    return base;
  }, [fixture.timeline, pendingCommand, result, safetyResult]);

  const canRun = (command: CaseCommand) =>
    fixture.available_commands.includes(command);
  const recoveryCase = fixture.case;
  const displayedEvidenceKind =
    fixture.evidence.find((item) => item.kind === "RAZORPAY_TEST_VERIFIED")
      ?.kind ??
    fixture.timeline.find(
      (item) => item.evidence_kind === "RAZORPAY_TEST_VERIFIED",
    )?.evidence_kind ??
    "SIMULATED";
  const diagnosisLabel = humanize(recoveryCase.diagnosis);
  const failureReason = humanize(fixture.payment_failure.error_reason);
  const recommendedSurface = paymentSurfaceLabel(
    fixture.recommendation.payment_surface_type,
  );
  const hasReliableScore =
    fixture.recommendation.confidence > 0 &&
    fixture.recommendation.predicted_recovery_probability > 0;

  const applySafetyDisposition = useCallback(async () => {
    if (!selectedSafety) return;
    setSafetyPending(true);
    setActionError(null);
    setResult(null);
    try {
      const commandResult = await executeSafetyDisposition(
        fixture.case.id,
        selectedSafety,
      );
      setSafetyResult(commandResult);
      setDisplayedContactDisposition((current) =>
        safetyContactDisposition(selectedSafety, current),
      );
      if (selectedSafety === "MARK_DISPUTE") setDisplayedOutcome("DISPUTED");
      if (selectedSafety === "ESCALATE_TO_HUMAN") {
        setDisplayedOutcome("ESCALATED");
      }
      if (selectedSafety === "MARK_OPT_OUT") setDisplayedOutcome("STOPPED");
      if (selectedSafety === "MARK_WRONG_PERSON") {
        setDisplayedOutcome("STOPPED");
      }
      setSelectedSafety(null);
      if (source === "api") onRefresh();
    } catch (error) {
      setActionError(
        error instanceof Error
          ? error.message
          : "The safety disposition could not be recorded.",
      );
      setSelectedSafety(null);
    } finally {
      setSafetyPending(false);
    }
  }, [fixture.case.id, onRefresh, selectedSafety, source]);

  const paymentDetails = [
    { label: "Customer", value: fixture.customer.display_name },
    {
      label: "Preferred language",
      value: fixture.customer.preferred_language,
    },
    {
      label: "Contact status",
      value: humanize(displayedContactDisposition),
    },
    {
      label: "Voice consent",
      value: fixture.customer.voice_consent ? "Recorded" : "Not recorded",
    },
    {
      label: "Customer agent",
      value: fixture.customer.customer_agent_available
        ? "Available"
        : "Unavailable",
    },
    {
      label: "Payment method",
      value: humanize(fixture.payment_failure.method),
    },
    {
      label: "Authoritative payment state",
      value: humanize(fixture.payment_surface.authoritative_payment_state),
    },
    { label: "Case ID", value: recoveryCase.id },
    { label: "Payment ID", value: fixture.payment_failure.payment_id },
    { label: "Invoice ID", value: fixture.payment_failure.invoice_id },
    { label: "Subscription ID", value: recoveryCase.subscription_id },
    {
      label: "Recovery method",
      value: paymentSurfaceLabel(fixture.payment_surface.type),
    },
    {
      label: "Method status",
      value: humanize(fixture.payment_surface.status),
    },
    {
      label: "Provider reference",
      value: fixture.payment_surface.provider_reference ?? "Not created",
    },
    {
      label: "Arrears collected",
      value: formatPaise(fixture.payment_surface.arrears_collected_paise),
    },
    {
      label: "Subscription reactivated",
      value: fixture.payment_surface.subscription_reactivated ? "Yes" : "No",
    },
  ];

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-col gap-3">
        <Button
          variant="ghost"
          size="sm"
          className="self-start"
          render={<Link href="/dashboard" />}
          nativeButton={false}
        >
          <ArrowLeft data-icon="inline-start" />
          Control Tower
        </Button>
        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div className="min-w-0">
            <p className="text-xs font-medium text-muted-foreground">
              Payment recovery case
            </p>
            <h1 className="mt-1 truncate text-2xl font-semibold tracking-tight">
              {fixture.customer.display_name} · {fixture.subscription.plan_name}
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              One failed subscription payment and its safest next action.
            </p>
          </div>
          <div
            className="flex flex-wrap items-center gap-2"
            aria-label="Case status"
          >
            <Badge variant={caseOutcomeVariant(displayedOutcome)}>
              {humanize(displayedOutcome)}
            </Badge>
            <Badge variant={source === "api" ? "success" : "info"}>
              {source === "api" ? "Backend connected" : "Local demo"}
            </Badge>
            <Badge
              variant={
                displayedEvidenceKind === "RAZORPAY_TEST_VERIFIED"
                  ? "success"
                  : "warning"
              }
            >
              {displayedEvidenceKind === "RAZORPAY_TEST_VERIFIED"
                ? "Razorpay test verified"
                : "Simulated data"}
            </Badge>
          </div>
        </div>
      </header>

      <Card size="sm" aria-label="Case summary">
        <CardHeader className="sr-only">
          <CardTitle>Case summary</CardTitle>
          <CardDescription>Current payment and recovery state.</CardDescription>
        </CardHeader>
        <CardContent>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-3 md:grid-cols-4">
            <div>
              <dt className="text-xs text-muted-foreground">
                Amount to recover
              </dt>
              <dd
                className={cn(
                  "mt-1 text-lg font-semibold",
                  paymentStateTone(recoveryCase.payment_state),
                )}
              >
                {formatPaise(recoveryCase.amount_at_risk_paise)}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Payment</dt>
              <dd
                className={cn(
                  "mt-1 text-sm font-medium",
                  paymentStateTone(recoveryCase.payment_state),
                )}
              >
                {humanize(recoveryCase.payment_state)}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Subscription</dt>
              <dd
                className={cn(
                  "mt-1 text-sm font-medium",
                  subscriptionStateTone(recoveryCase.subscription_state),
                )}
              >
                {humanize(recoveryCase.subscription_state)}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Act before</dt>
              <dd className="mt-1 text-sm font-medium text-warning">
                {formatDateTime(recoveryCase.recovery_deadline)}
              </dd>
            </div>
          </dl>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>
            <h2>Recommended recovery action</h2>
          </CardTitle>
          <CardDescription>
            Selected by the backend after diagnosis, ranking, and policy checks.
          </CardDescription>
          <CardAction>
            <Badge variant={policyVariant(fixture.policy.disposition)}>
              {fixture.policy.disposition === "ALLOW"
                ? "Ready for approval"
                : humanize(fixture.policy.disposition)}
            </Badge>
          </CardAction>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(18rem,0.7fr)]">
            <div className="flex flex-col gap-3">
              <div>
                <p className="text-xs font-medium text-muted-foreground">
                  Proposed recovery surface
                </p>
                <h2 className="mt-1 text-xl font-semibold text-primary">
                  {recommendedSurface}
                </h2>
                <p className="mt-1 text-sm text-muted-foreground">
                  {customerInstruction(
                    fixture.recommendation.payment_surface_type,
                  )}
                  . RecoveryOS then waits for authoritative Razorpay proof
                  before changing the payment state.
                </p>
              </div>

              <Alert variant="info">
                <ShieldCheck />
                <AlertTitle>Subscription-safe recovery</AlertTitle>
                <AlertDescription>
                  <span>
                    Standalone collection is blocked while gateway retries are
                    active
                  </span>
                  <span className="mt-0.5 block">
                    Use the subscription-native surface above so invoice
                    correlation is preserved.
                  </span>
                </AlertDescription>
              </Alert>

              {fixture.payment_surface.customer_url && (
                <Button
                  variant="outline"
                  size="sm"
                  className="self-start"
                  render={
                    <a
                      href={fixture.payment_surface.customer_url}
                      target="_blank"
                      rel="noreferrer"
                    />
                  }
                  nativeButton={false}
                >
                  Open customer payment surface
                  <ExternalLink data-icon="inline-end" />
                </Button>
              )}
            </div>

            <ol className="flex flex-col" aria-label="Situation summary">
              {[
                {
                  label: "Payment failed",
                  value: `${formatPaise(recoveryCase.amount_at_risk_paise)} remains unpaid`,
                },
                {
                  label: diagnosisLabel,
                  value: `${failureReason} during ${humanize(fixture.payment_failure.error_step)}`,
                },
                {
                  label:
                    displayedOutcome === "OPEN"
                      ? "Awaiting operator action"
                      : `Recovery ${humanize(displayedOutcome).toLowerCase()}`,
                  value: `Contact status: ${humanize(displayedContactDisposition)}`,
                },
              ].map((item, index) => (
                <li className="flex flex-col gap-2" key={item.label}>
                  {index > 0 && <Separator className="mb-3" />}
                  <div className="flex items-start gap-3">
                    <Badge
                      variant={
                        index === 0
                          ? "destructive"
                          : index === 1
                            ? "warning"
                            : "info"
                      }
                    >
                      {index + 1}
                    </Badge>
                    <div className="min-w-0">
                      <p className="text-sm font-medium">{item.label}</p>
                      <p className="text-xs text-muted-foreground">
                        {item.value}
                      </p>
                    </div>
                  </div>
                </li>
              ))}
            </ol>
          </div>

          <div className="flex flex-col gap-2" aria-live="polite">
            {result && (
              <Alert variant="success">
                <CheckCircle2 />
                <AlertTitle>{humanize(result.command)} accepted</AlertTitle>
                <AlertDescription>{result.message}</AlertDescription>
              </Alert>
            )}
            {safetyResult && (
              <Alert variant="success">
                <CheckCircle2 />
                <AlertTitle>
                  {humanize(safetyResult.disposition)} recorded
                </AlertTitle>
                <AlertDescription>{safetyResult.message}</AlertDescription>
              </Alert>
            )}
            {actionError && (
              <Alert variant="destructive">
                <CircleAlert />
                <AlertTitle>Action could not be completed</AlertTitle>
                <AlertDescription>{actionError}</AlertDescription>
              </Alert>
            )}
          </div>
        </CardContent>
        <CardFooter className="flex flex-wrap gap-2">
          <Button
            disabled={!canRun("APPROVE") || pendingCommand !== null}
            onClick={() => execute("APPROVE")}
          >
            <CommandButtonLabel
              command="APPROVE"
              pendingCommand={pendingCommand}
            />
          </Button>
          <Button
            variant="outline"
            disabled={!canRun("ESCALATE_TO_HUMAN") || pendingCommand !== null}
            onClick={() => execute("ESCALATE_TO_HUMAN")}
          >
            <CommandButtonLabel
              command="ESCALATE_TO_HUMAN"
              pendingCommand={pendingCommand}
            />
          </Button>
          <Button
            variant="ghost"
            disabled={!canRun("REJECT") || pendingCommand !== null}
            onClick={() => execute("REJECT")}
          >
            <CommandButtonLabel
              command="REJECT"
              pendingCommand={pendingCommand}
            />
          </Button>
          <Button
            variant="destructive"
            disabled={!canRun("STOP") || pendingCommand !== null}
            onClick={() => execute("STOP")}
          >
            <CommandButtonLabel
              command="STOP"
              pendingCommand={pendingCommand}
            />
          </Button>
        </CardFooter>
      </Card>

      <div className="flex flex-col gap-2">
        <Disclosure
          title="Evidence and payment details"
          description="Diagnosis, provider state, identifiers, and payment proof"
        >
          <div className="flex flex-col gap-1">
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-sm font-medium text-warning">
                {diagnosisLabel}
              </p>
              <Badge
                variant={
                  displayedEvidenceKind === "RAZORPAY_TEST_VERIFIED"
                    ? "success"
                    : "warning"
                }
              >
                {formatEvidenceKind(displayedEvidenceKind)}
              </Badge>
            </div>
            <p className="text-sm text-muted-foreground">
              {failureReason} during{" "}
              {humanize(fixture.payment_failure.error_step)}. The customer must
              authenticate again; browser callbacks are not treated as proof of
              payment.
            </p>
          </div>

          {fixture.evidence.length > 0 && (
            <div className="flex flex-col gap-2">
              <p className="text-xs font-medium text-muted-foreground">
                Evidence received
              </p>
              <ul className="grid gap-2 sm:grid-cols-2">
                {fixture.evidence.map((item) => (
                  <li
                    className="rounded-lg border border-border bg-muted/30 px-3 py-2"
                    key={`${item.source_event}-${item.field}`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs font-medium">
                        {humanize(item.field)}
                      </span>
                      <Badge
                        variant={
                          item.kind === "RAZORPAY_TEST_VERIFIED"
                            ? "success"
                            : "warning"
                        }
                      >
                        {formatEvidenceKind(item.kind)}
                      </Badge>
                    </div>
                    <p className="mt-1 break-words text-xs text-muted-foreground">
                      {item.value} · {humanize(item.source_event)}
                    </p>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <Separator />
          <DetailGrid items={paymentDetails} />

          <Alert variant="success">
            <ShieldCheck />
            <AlertTitle>Payment proof is authoritative</AlertTitle>
            <AlertDescription>
              RecoveryOS waits for a Razorpay fetch or signed webhook. A browser
              callback alone never marks the invoice as paid.
            </AlertDescription>
          </Alert>
        </Disclosure>

        <Disclosure
          title="Decision details"
          description="Policy result, confidence, reasons, and rejected alternatives"
        >
          <DetailGrid
            items={[
              {
                label: "Recommended action",
                value: humanize(fixture.recommendation.action),
              },
              {
                label: "Safety decision",
                value: humanize(fixture.policy.disposition),
              },
              {
                label: "Recovery score",
                value: hasReliableScore
                  ? formatProbability(
                      fixture.recommendation.predicted_recovery_probability,
                    )
                  : "Not enough data",
              },
              {
                label: "Score confidence",
                value: formatProbability(fixture.recommendation.confidence),
              },
              {
                label: "Expected recovery",
                value: formatPaise(
                  fixture.recommendation.expected_recovered_paise,
                ),
              },
              {
                label: "Expected utility",
                value: formatPaise(
                  fixture.recommendation.expected_utility_paise,
                ),
              },
              {
                label: "Policy version",
                value: fixture.policy.policy_version,
              },
              {
                label: "Decision code",
                value: fixture.policy.decision_code,
              },
            ]}
          />

          <Separator />

          <div className="grid gap-4 lg:grid-cols-2">
            <div className="flex flex-col gap-2">
              <p className="text-sm font-medium">Why it was selected</p>
              <ul className="flex flex-col gap-2">
                {fixture.policy.reasons.map((reason, index) => (
                  <li
                    className="flex items-start justify-between gap-3"
                    key={fixture.policy.reason_codes[index] ?? reason}
                  >
                    <span className="text-sm text-muted-foreground">
                      {reason}
                    </span>
                    <Badge variant="info">
                      {fixture.policy.reason_codes[index] ?? "Policy"}
                    </Badge>
                  </li>
                ))}
                {fixture.recommendation.reasons.map((reason, index) => (
                  <li
                    className="flex items-start justify-between gap-3"
                    key={fixture.recommendation.reason_codes[index] ?? reason}
                  >
                    <span className="text-sm text-muted-foreground">
                      {reason}
                    </span>
                    <Badge variant="info">
                      {fixture.recommendation.reason_codes[index] ?? "Ranking"}
                    </Badge>
                  </li>
                ))}
              </ul>
            </div>

            <div className="flex flex-col gap-2">
              <p className="text-sm font-medium">Not selected</p>
              {fixture.recommendation.rejected_alternatives.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No alternative actions were returned.
                </p>
              ) : (
                <ul className="flex flex-col gap-2">
                  {fixture.recommendation.rejected_alternatives.map(
                    (alternative) => (
                      <li
                        className="rounded-lg border border-border px-3 py-2"
                        key={`${alternative.action}-${alternative.reason_code}`}
                      >
                        <div className="flex items-center justify-between gap-3">
                          <p className="text-sm font-medium">
                            {humanize(alternative.action)}
                            {alternative.payment_surface_type
                              ? ` · ${humanize(alternative.payment_surface_type)}`
                              : ""}
                          </p>
                          <Badge variant="outline">
                            {alternative.reason_code}
                          </Badge>
                        </div>
                        <p className="mt-1 text-xs text-muted-foreground">
                          {alternative.reason}
                        </p>
                      </li>
                    ),
                  )}
                </ul>
              )}
            </div>
          </div>
        </Disclosure>

        <Disclosure
          title="Customer safeguards"
          description="Record a dispute, opt-out, already-paid claim, or wrong person"
          defaultOpen
        >
          <div
            className="flex flex-wrap gap-2"
            aria-label="Customer safety actions"
          >
            <Button
              variant="destructive"
              size="sm"
              disabled={safetyPending}
              onClick={() => setSelectedSafety("MARK_DISPUTE")}
            >
              Mark dispute
            </Button>
            <Button
              variant="destructive"
              size="sm"
              disabled={safetyPending}
              onClick={() => setSelectedSafety("MARK_OPT_OUT")}
            >
              Record opt-out
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={safetyPending}
              onClick={() => setSelectedSafety("MARK_ALREADY_PAID")}
            >
              Customer says already paid
            </Button>
            <Button
              variant="destructive"
              size="sm"
              disabled={safetyPending}
              onClick={() => setSelectedSafety("MARK_WRONG_PERSON")}
            >
              Mark wrong person
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={safetyPending}
              onClick={() => setSelectedSafety("ESCALATE_TO_HUMAN")}
            >
              Escalate for review
            </Button>
          </div>
          <Alert variant="warning">
            <ShieldCheck />
            <AlertTitle>Safety controls run first</AlertTitle>
            <AlertDescription>
              Disputes and opt-outs stop incompatible outreach immediately.
              “Already paid” pauses recovery until Razorpay confirms payment.
            </AlertDescription>
          </Alert>
        </Disclosure>

        <Disclosure
          title="Full case history"
          description={`${timeline.length} provider and RecoveryOS event${timeline.length === 1 ? "" : "s"}`}
        >
          <ol className="flex flex-col" aria-live="polite">
            {timeline.map((event, index) => (
              <li className="flex flex-col gap-3" key={event.id}>
                {index > 0 && <Separator />}
                <div className="flex items-start gap-3">
                  <Badge variant={event.optimistic ? "warning" : "info"}>
                    {index + 1}
                  </Badge>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="text-sm font-medium">{event.title}</p>
                      <Badge variant={event.optimistic ? "warning" : "success"}>
                        {event.optimistic ? "Pending" : "Recorded"}
                      </Badge>
                    </div>
                    <p className="mt-1 break-words text-xs text-muted-foreground">
                      {event.meta}
                    </p>
                    <p className="mt-1 text-sm text-muted-foreground">
                      {event.description}
                    </p>
                  </div>
                </div>
              </li>
            ))}
          </ol>
        </Disclosure>
      </div>

      <ConfirmDialog
        open={Boolean(selectedSafety)}
        danger={
          selectedSafety === "MARK_DISPUTE" ||
          selectedSafety === "MARK_OPT_OUT" ||
          selectedSafety === "MARK_WRONG_PERSON"
        }
        busy={safetyPending}
        title={
          selectedSafety === "MARK_DISPUTE"
            ? "Record a payment dispute?"
            : selectedSafety === "MARK_OPT_OUT"
              ? "Suppress all customer outreach?"
              : selectedSafety === "MARK_WRONG_PERSON"
                ? "Record a wrong-person contact?"
                : selectedSafety === "MARK_ALREADY_PAID"
                  ? "Pause and reconcile payment?"
                  : "Escalate this case?"
        }
        description="RecoveryOS will persist this disposition before cancelling incompatible pending actions."
        confirmationText="A customer statement is not authoritative proof of payment; already-paid cases remain open until provider reconciliation succeeds."
        confirmLabel="Confirm safety disposition"
        onCancel={() => setSelectedSafety(null)}
        onConfirm={applySafetyDisposition}
      />
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
      <Alert variant="destructive">
        <CircleAlert />
        <AlertTitle>Case workspace could not load</AlertTitle>
        <AlertDescription className="flex flex-col items-start gap-3">
          <p>{resource.error ?? "The case response was empty."}</p>
          <Button variant="outline" size="sm" onClick={resource.reload}>
            Try again
          </Button>
        </AlertDescription>
      </Alert>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {resource.warning && (
        <Alert variant="info">
          <CircleAlert />
          <AlertTitle>Demo data active</AlertTitle>
          <AlertDescription>{resource.warning}</AlertDescription>
        </Alert>
      )}
      <CaseContent
        fixture={resource.data}
        onRefresh={resource.reload}
        source={resource.source}
      />
    </div>
  );
}
