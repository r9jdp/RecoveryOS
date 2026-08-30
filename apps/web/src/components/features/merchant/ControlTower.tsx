"use client";

import {
  ArrowUpRight,
  Info,
  RefreshCw,
  Search,
  TriangleAlert,
} from "lucide-react";
import Link from "next/link";
import { Fragment, useMemo, useState } from "react";

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
import { Input } from "@/components/shadcn/input";
import { Separator } from "@/components/shadcn/separator";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/shadcn/select";
import { Skeleton } from "@/components/shadcn/skeleton";
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/shadcn/table";
import { useRecoveryResource } from "@/hooks/use-recovery-resource";
import { getDashboard } from "@/lib/api/recovery-client";
import { approvalItems } from "@/lib/merchant-demo";
import { cn } from "@/lib/utils";
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

type BadgeVariant =
  | "default"
  | "secondary"
  | "destructive"
  | "success"
  | "warning"
  | "info"
  | "outline"
  | "ghost";

type SemanticTone = "default" | "destructive" | "success" | "warning" | "info";

const metricToneClasses: Record<SemanticTone, string> = {
  default: "text-foreground",
  destructive: "text-destructive",
  success: "text-success",
  warning: "text-warning",
  info: "text-info",
};

const outcomeItems = [
  { label: "All outcomes", value: "ALL" },
  { label: "Open", value: "OPEN" },
  { label: "Escalated", value: "ESCALATED" },
  { label: "Recovered", value: "RECOVERED" },
];

const surfaceItems = [
  { label: "All surfaces", value: "ALL" },
  { label: "Card update", value: "SUBSCRIPTION_CARD_UPDATE" },
  { label: "Invoice link", value: "SUBSCRIPTION_INVOICE_LINK" },
  { label: "Payment link", value: "STANDARD_PAYMENT_LINK" },
];

function outcomeVariant(outcome: DashboardCase["case_outcome"]): BadgeVariant {
  if (outcome === "RECOVERED" || outcome === "PARTIALLY_RECOVERED") {
    return "success";
  }
  if (
    outcome === "STOPPED" ||
    outcome === "DISPUTED" ||
    outcome === "EXPIRED"
  ) {
    return "destructive";
  }
  if (outcome === "ESCALATED") return "warning";
  return "info";
}

function subscriptionVariant(
  state: DashboardCase["subscription_state"],
): BadgeVariant {
  if (
    state === "ACTIVE" ||
    state === "AUTHENTICATED" ||
    state === "COMPLETED"
  ) {
    return "success";
  }
  if (state === "PENDING" || state === "PAUSED") return "warning";
  if (state === "HALTED" || state === "CANCELLED") return "destructive";
  return "secondary";
}

function auditEventDotClass(eventType: string): string {
  const normalizedEventType = eventType.toUpperCase();

  if (
    normalizedEventType.includes("FAILED") ||
    normalizedEventType.includes("DISPUTED") ||
    normalizedEventType.includes("STOPPED") ||
    normalizedEventType.includes("EXPIRED")
  ) {
    return "bg-destructive";
  }

  if (
    normalizedEventType.includes("APPROVED") ||
    normalizedEventType.includes("RECOVERED") ||
    normalizedEventType.includes("CAPTURED") ||
    normalizedEventType.includes("SUCCEEDED")
  ) {
    return "bg-success";
  }

  if (
    normalizedEventType.includes("ESCALATED") ||
    normalizedEventType.includes("REVIEW") ||
    normalizedEventType.includes("PENDING")
  ) {
    return "bg-warning";
  }

  return "bg-info";
}

function MetricCard({
  label,
  value,
  detail,
  tone = "default",
}: {
  label: string;
  value: string | number;
  detail?: string;
  tone?: SemanticTone;
}) {
  return (
    <Card size="sm" aria-label={label}>
      <CardHeader>
        <CardDescription>{label}</CardDescription>
      </CardHeader>
      <CardContent className="flex min-w-0 flex-col gap-1">
        <p
          className={cn(
            "text-2xl leading-tight font-semibold tracking-tight tabular-nums",
            metricToneClasses[tone],
          )}
        >
          {value}
        </p>
        {detail ? (
          <p className="text-sm leading-5 text-muted-foreground">{detail}</p>
        ) : null}
      </CardContent>
    </Card>
  );
}

export function DashboardLoading() {
  return (
    <div
      className="flex flex-col gap-6"
      aria-busy="true"
      aria-label="Loading Control Tower"
    >
      <div className="flex flex-col gap-2">
        <Skeleton className="h-4 w-32" />
        <Skeleton className="h-9 w-52" />
        <Skeleton className="h-5 w-full max-w-xl" />
      </div>

      <section className="flex flex-col gap-3" aria-label="Loading overview">
        <div className="flex flex-col gap-2">
          <Skeleton className="h-6 w-32" />
          <Skeleton className="h-4 w-72 max-w-full" />
        </div>
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 4 }, (_, index) => (
            <Card size="sm" key={index}>
              <CardHeader>
                <Skeleton className="h-4 w-24" />
              </CardHeader>
              <CardContent className="flex flex-col gap-2">
                <Skeleton className="h-7 w-28" />
                <Skeleton className="h-4 w-36 max-w-full" />
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
        {Array.from({ length: 3 }, (_, index) => (
          <Card
            key={index}
            className={cn(index === 2 && "lg:col-span-2 xl:col-span-1")}
          >
            <CardHeader>
              <Skeleton className="h-5 w-40" />
              <Skeleton className="h-4 w-56 max-w-full" />
            </CardHeader>
            <CardContent>
              <Skeleton className="h-32 w-full" />
            </CardContent>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader>
          <Skeleton className="h-5 w-44" />
          <Skeleton className="h-4 w-64 max-w-full" />
        </CardHeader>
        <CardContent>
          <Skeleton className="h-40 w-full" />
        </CardContent>
      </Card>
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
  const filtersAreActive =
    query !== "" || outcome !== "ALL" || surface !== "ALL";

  const clearFilters = () => {
    setQuery("");
    setOutcome("ALL");
    setSurface("ALL");
  };

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 flex-col gap-1">
          <p className="text-sm font-medium text-muted-foreground">
            Live recovery operations
          </p>
          <h1 className="text-2xl leading-tight font-semibold tracking-tight sm:text-3xl">
            Control Tower
          </h1>
          <p className="max-w-2xl text-base leading-6 text-muted-foreground">
            Failed billing cycles, verified recovery, and cases that need a
            decision.
          </p>
        </div>
        <Badge variant={source === "api" ? "success" : "info"}>
          {source === "api" ? "API connected" : "Local demo"}
        </Badge>
      </header>

      <section className="flex flex-col gap-3" aria-labelledby="overview-title">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h2 id="overview-title" className="text-lg font-medium">
              At a glance
            </h2>
            <p className="text-sm text-muted-foreground">
              Current revenue exposure and provider-confirmed outcomes.
            </p>
          </div>
          <div className="self-start sm:self-auto">
            <Badge
              variant={
                fixture.evidence_kind === "RAZORPAY_TEST_VERIFIED"
                  ? "success"
                  : "info"
              }
            >
              {formatEvidenceKind(fixture.evidence_kind)}
            </Badge>
          </div>
        </div>

        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard
            label="Revenue at risk"
            value={formatPaise(fixture.metrics.revenue_at_risk_paise)}
            detail={`${fixture.metrics.active_cases} active billing cycle${fixture.metrics.active_cases === 1 ? "" : "s"}`}
            tone="destructive"
          />
          <MetricCard
            label="Verified recovered"
            value={formatPaise(
              fixture.metrics.verified_recovered_revenue_paise,
            )}
            detail={`Net recovered ${formatPaise(fixture.metrics.net_recovered_value_paise)}`}
            tone="success"
          />
          <MetricCard
            label="Recovery rate"
            value={formatBasisPoints(
              fixture.metrics.recovery_rate_basis_points,
            )}
            detail={`Synthetic estimate ${formatPaise(fixture.metrics.simulated_incremental_recovery_paise)}`}
            tone="info"
          />
          <MetricCard
            label="Needs human review"
            value={displayedHumanReviewCount}
            detail={`${fixture.metrics.policy_blocked_actions} policy-blocked action${fixture.metrics.policy_blocked_actions === 1 ? "" : "s"}`}
            tone="warning"
          />
        </div>
      </section>

      <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
        <Card aria-labelledby="diagnosis-heading">
          <CardHeader className="border-b">
            <CardTitle id="diagnosis-heading">Diagnosis distribution</CardTitle>
            <CardDescription>
              Active cases grouped by the reason payment failed.
            </CardDescription>
            <CardAction>
              <Badge variant="info">
                {fixture.metrics.active_cases} active
              </Badge>
            </CardAction>
          </CardHeader>
          <CardContent>
            {fixture.diagnosis_distribution.length > 0 ? (
              <div className="flex flex-col gap-4">
                {fixture.diagnosis_distribution.map((item) => {
                  const progress = (item.case_count * 100) / maxDiagnosisCount;

                  return (
                    <div className="flex flex-col gap-2" key={item.diagnosis}>
                      <div className="flex items-center justify-between gap-3 text-base">
                        <span className="truncate">
                          {humanize(item.diagnosis)}
                        </span>
                        <span className="font-medium tabular-nums">
                          {item.case_count}
                        </span>
                      </div>
                      <div
                        className="h-1.5 overflow-hidden rounded-full bg-muted"
                        role="progressbar"
                        aria-label={`${humanize(item.diagnosis)} cases`}
                        aria-valuemin={0}
                        aria-valuemax={maxDiagnosisCount}
                        aria-valuenow={item.case_count}
                      >
                        <div
                          className="h-full rounded-full bg-primary transition-[width] duration-200 motion-reduce:transition-none"
                          style={{ width: `${progress}%` }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <p className="text-base leading-6 text-muted-foreground">
                Diagnosis counts appear after a failed payment is correlated.
              </p>
            )}
          </CardContent>
        </Card>

        <Card aria-labelledby="channels-heading">
          <CardHeader className="border-b">
            <CardTitle id="channels-heading">Recovery channels</CardTitle>
            <CardDescription>
              Provider-confirmed recovery by payment surface.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {fixture.recovery_by_channel.length > 0 ? (
              <div className="flex flex-col">
                {fixture.recovery_by_channel.map((channel, index) => (
                  <Fragment key={channel.channel}>
                    {index > 0 ? <Separator /> : null}
                    <div className="flex items-center justify-between gap-4 py-3">
                      <div className="min-w-0">
                        <p className="truncate text-base font-medium">
                          {humanize(channel.channel)}
                        </p>
                        <p className="text-sm text-muted-foreground">
                          {channel.case_count} case
                          {channel.case_count === 1 ? "" : "s"}
                        </p>
                      </div>
                      <p
                        className={cn(
                          "text-base font-medium tabular-nums",
                          channel.recovered_paise > 0
                            ? "text-success"
                            : "text-muted-foreground",
                        )}
                      >
                        {formatPaise(channel.recovered_paise)}
                      </p>
                    </div>
                  </Fragment>
                ))}
              </div>
            ) : (
              <p className="text-base leading-6 text-muted-foreground">
                Recovered revenue will appear after provider confirmation.
              </p>
            )}
          </CardContent>
        </Card>

        <Card className="lg:col-span-2 xl:col-span-1" id="audit">
          <CardHeader className="border-b">
            <CardTitle>Recent audit events</CardTitle>
            <CardDescription>
              Latest decisions and recovery state changes.
            </CardDescription>
            <CardAction>
              <Badge variant="info">{fixture.recent_events.length}</Badge>
            </CardAction>
          </CardHeader>
          <CardContent>
            {fixture.recent_events.length > 0 ? (
              <ol className="flex flex-col">
                {fixture.recent_events.map((event, index) => (
                  <Fragment key={event.id}>
                    {index > 0 ? <Separator /> : null}
                    <li className="flex min-w-0 flex-col gap-1 py-2.5">
                      <div className="flex items-center justify-between gap-3">
                        <div className="flex min-w-0 items-center gap-2">
                          <span
                            className={cn(
                              "size-1.5 shrink-0 rounded-full",
                              auditEventDotClass(event.event_type),
                            )}
                            aria-hidden="true"
                          />
                          <p className="truncate text-base font-medium">
                            {humanize(event.event_type)}
                          </p>
                        </div>
                        <time className="shrink-0 text-sm text-muted-foreground">
                          {formatDateTime(event.occurred_at)}
                        </time>
                      </div>
                      <code
                        className="truncate text-sm text-muted-foreground"
                        title={event.correlation_id}
                      >
                        {event.correlation_id}
                      </code>
                    </li>
                  </Fragment>
                ))}
              </ol>
            ) : (
              <p className="text-base leading-6 text-muted-foreground">
                Audit events will appear when a recovery case changes.
              </p>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="border-b">
          <CardTitle>Active recovery cases</CardTitle>
          <CardDescription>
            Inspect case evidence and approve the next safe action.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <div className="flex flex-col gap-2 lg:flex-row lg:items-center">
            <label className="relative block min-w-0 flex-1">
              <span className="sr-only">Search cases</span>
              <Search
                className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground"
                aria-hidden="true"
              />
              <Input
                className="pl-8"
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search customer, case, plan, or diagnosis"
              />
            </label>

            <div className="flex flex-wrap gap-2">
              <Select
                items={outcomeItems}
                value={outcome}
                onValueChange={(value) => {
                  if (value) setOutcome(value);
                }}
              >
                <SelectTrigger
                  className="min-w-36"
                  aria-label="Filter by outcome"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    {outcomeItems.map((item) => (
                      <SelectItem key={item.value} value={item.value}>
                        {item.label}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>

              <Select
                items={surfaceItems}
                value={surface}
                onValueChange={(value) => {
                  if (value) {
                    setSurface(value as "ALL" | PaymentSurfaceType);
                  }
                }}
              >
                <SelectTrigger
                  className="min-w-36"
                  aria-label="Filter by payment surface"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    {surfaceItems.map((item) => (
                      <SelectItem key={item.value} value={item.value}>
                        {item.label}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
              {filtersAreActive ? (
                <Button variant="ghost" size="sm" onClick={clearFilters}>
                  Clear
                </Button>
              ) : null}
            </div>
          </div>

          {filteredCases.length > 0 ? (
            <Table>
              <TableCaption className="sr-only">
                Showing {filteredCases.length} of {fixture.cases.length}{" "}
                recovery cases
              </TableCaption>
              <TableHeader>
                <TableRow>
                  <TableHead>Case</TableHead>
                  <TableHead>Customer</TableHead>
                  <TableHead>Diagnosis</TableHead>
                  <TableHead>Amount at risk</TableHead>
                  <TableHead>Subscription</TableHead>
                  <TableHead>Outcome</TableHead>
                  <TableHead>Updated</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredCases.map((recoveryCase) => (
                  <TableRow key={recoveryCase.id}>
                    <TableCell>
                      <Link
                        className="inline-flex items-center gap-1 font-medium text-primary underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        href={`/cases/${recoveryCase.id}`}
                      >
                        <span>
                          {recoveryCase.id
                            .replace("case_", "REC-")
                            .replaceAll("_", "-")
                            .toUpperCase()}
                        </span>
                        <ArrowUpRight className="size-3.5" aria-hidden="true" />
                      </Link>
                      <p className="font-mono text-xs text-muted-foreground">
                        {recoveryCase.failed_invoice_id}
                      </p>
                    </TableCell>
                    <TableCell>
                      <p className="font-medium">
                        {recoveryCase.customer_display_name}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {recoveryCase.plan_name}
                      </p>
                    </TableCell>
                    <TableCell>{humanize(recoveryCase.diagnosis)}</TableCell>
                    <TableCell className="font-medium text-destructive tabular-nums">
                      {formatPaise(recoveryCase.amount_at_risk_paise)}
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant={subscriptionVariant(
                          recoveryCase.subscription_state,
                        )}
                      >
                        {humanize(recoveryCase.subscription_state)}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant={outcomeVariant(recoveryCase.case_outcome)}
                      >
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
          ) : (
            <div className="flex flex-col items-center gap-3 py-8 text-center">
              <div className="flex max-w-sm flex-col gap-1">
                <p className="text-sm font-medium">No matching cases</p>
                <p className="text-sm text-muted-foreground">
                  Change the filters to return to all recovery cases.
                </p>
              </div>
              <Button variant="secondary" size="sm" onClick={clearFilters}>
                Clear filters
              </Button>
            </div>
          )}
        </CardContent>
        <CardFooter className="justify-between gap-3">
          <p className="text-xs text-muted-foreground">
            Showing {filteredCases.length} of {fixture.cases.length} cases
          </p>
          <p className="text-xs text-muted-foreground">
            {formatEvidenceKind(fixture.evidence_kind)}
          </p>
        </CardFooter>
      </Card>
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
      <div>
        <Card className="mx-auto max-w-xl">
          <CardHeader>
            <CardTitle>Control Tower could not load</CardTitle>
            <CardDescription>
              The dashboard data is currently unavailable.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Alert variant="destructive">
              <TriangleAlert />
              <AlertTitle>Dashboard request failed</AlertTitle>
              <AlertDescription>
                {resource.error ?? "The dashboard response was empty."}
              </AlertDescription>
            </Alert>
          </CardContent>
          <CardFooter>
            <Button onClick={resource.reload}>
              <RefreshCw data-icon="inline-start" />
              Try again
            </Button>
          </CardFooter>
        </Card>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {resource.warning ? (
        <Alert variant="info">
          <Info />
          <AlertTitle>Demo data active</AlertTitle>
          <AlertDescription>{resource.warning}</AlertDescription>
        </Alert>
      ) : null}
      <ControlTowerContent fixture={resource.data} source={resource.source} />
    </div>
  );
}
