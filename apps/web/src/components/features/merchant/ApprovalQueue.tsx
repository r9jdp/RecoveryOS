"use client";

import { CircleAlert } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { PageHeader } from "@/components/layout";
import { Alert, AlertDescription, AlertTitle } from "@/components/shadcn/alert";
import { Badge } from "@/components/shadcn/badge";
import { Button } from "@/components/shadcn/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/shadcn/card";
import { Field, FieldDescription, FieldLabel } from "@/components/shadcn/field";
import { Input } from "@/components/shadcn/input";
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
import { executeCaseCommand, getDashboard } from "@/lib/api/recovery-client";
import { buildApprovalItems } from "@/lib/merchant-demo";
import {
  formatDateTime,
  formatEvidenceKind,
  formatPaise,
  humanize,
} from "@/lib/recovery-format";
import type { ApprovalItem, CommandResult } from "@/types/recovery";

import { ConfirmDialog } from "./ConfirmDialog";

interface ApprovalQueueProps {
  runApproval?: (caseId: string) => Promise<CommandResult>;
}

function QueueEmpty({
  filtered,
  onClear,
}: {
  filtered: boolean;
  onClear: () => void;
}) {
  return (
    <div className="grid min-h-48 place-items-center px-4 text-center">
      <div className="max-w-sm">
        <div className="mx-auto mb-3 grid size-9 place-items-center rounded-lg border bg-muted/30 text-muted-foreground">
          <CircleAlert aria-hidden="true" className="size-4" />
        </div>
        <h2 className="text-base font-medium">
          {filtered ? "No matching approvals" : "Approval queue is clear"}
        </h2>
        <p className="mt-1 text-base leading-6 text-muted-foreground">
          {filtered
            ? "Try a different customer, case, or plan."
            : "Every high-impact recovery action has been reviewed."}
        </p>
        {filtered ? (
          <Button className="mt-4" variant="secondary" onClick={onClear}>
            Clear filter
          </Button>
        ) : null}
      </div>
    </div>
  );
}

export function ApprovalQueue({
  runApproval = (caseId) => executeCaseCommand(caseId, "APPROVE"),
}: ApprovalQueueProps) {
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<ApprovalItem | null>(null);
  const [busy, setBusy] = useState(false);
  const [approved, setApproved] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const resource = useRecoveryResource(getDashboard);
  const approvalItems = useMemo(
    () => (resource.data ? buildApprovalItems(resource.data) : []),
    [resource.data],
  );
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return approvalItems.filter((item) =>
      [item.customer_display_name, item.case_id, item.plan_name].some((value) =>
        value.toLowerCase().includes(needle),
      ),
    );
  }, [approvalItems, query]);

  async function approve() {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      await runApproval(selected.case_id);
      setApproved((current) => [...current, selected.case_id]);
      setSelected(null);
      if (resource.source === "api") resource.reload();
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "Approval could not be submitted.",
      );
      setSelected(null);
    } finally {
      setBusy(false);
    }
  }

  const awaitingReview = approvalItems.filter(
    (item) => !approved.includes(item.case_id),
  );
  const pending = filtered.filter((item) => !approved.includes(item.case_id));
  const amountAtRiskPaise = awaitingReview.reduce(
    (total, item) => total + item.amount_at_risk_paise,
    0,
  );
  const verifiedEvidenceCount = awaitingReview.filter(
    (item) => item.evidence_kind === "RAZORPAY_TEST_VERIFIED",
  ).length;

  if (resource.loading) {
    return (
      <div className="grid gap-4" aria-busy="true">
        <Skeleton className="h-9 w-60" />
        <Skeleton className="h-72 w-full" />
      </div>
    );
  }

  if (resource.error || !resource.data || !resource.source) {
    return (
      <Card className="mx-auto w-full max-w-lg">
        <CardHeader>
          <CardTitle>Approval queue could not load</CardTitle>
          <CardDescription>
            {resource.error ?? "The approval response was empty."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button onClick={resource.reload}>Try again</Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="grid gap-4">
      <PageHeader
        eyebrow="Human review"
        title="Approval queue"
        description="Review the exact customer surface before a recovery action is opened."
        action={
          <Badge variant="warning">
            {awaitingReview.length} awaiting review
          </Badge>
        }
      />

      {error ? (
        <Alert variant="destructive">
          <AlertTitle>Approval failed</AlertTitle>
          <AlertDescription>
            {error} The case remains unchanged and can be retried safely.
          </AlertDescription>
        </Alert>
      ) : null}

      {resource.warning ? (
        <Alert variant="info">
          <AlertTitle>Fallback approval data</AlertTitle>
          <AlertDescription>{resource.warning}</AlertDescription>
        </Alert>
      ) : null}

      <section aria-labelledby="approval-overview-title">
        <h2 id="approval-overview-title" className="sr-only">
          Approval overview
        </h2>
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          <Card>
            <CardHeader>
              <CardDescription>Awaiting review</CardDescription>
            </CardHeader>
            <CardContent>
              <p className="text-2xl leading-tight font-semibold">
                {awaitingReview.length}
              </p>
              <p className="text-base leading-6 text-muted-foreground">
                Recovery surfaces that still need an operator decision.
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardDescription>Amount at risk</CardDescription>
            </CardHeader>
            <CardContent>
              <p className="text-2xl leading-tight font-semibold text-destructive">
                {formatPaise(amountAtRiskPaise)}
              </p>
              <p className="text-base leading-6 text-muted-foreground">
                Total unpaid value across approvals still in the queue.
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardDescription>Provider-verified evidence</CardDescription>
            </CardHeader>
            <CardContent>
              <p className="text-2xl leading-tight font-semibold">
                {verifiedEvidenceCount}
              </p>
              <p className="text-base leading-6 text-muted-foreground">
                Items backed by a verified Razorpay test-mode event.
              </p>
            </CardContent>
          </Card>
        </div>
      </section>

      <Card>
        <CardHeader className="border-b">
          <CardTitle>Manual approvals</CardTitle>
          <CardDescription>
            Only the exact recovery surface shown here can be authorized.
          </CardDescription>
          <CardAction>
            <Badge variant="secondary">{pending.length} shown</Badge>
          </CardAction>
        </CardHeader>
        <CardContent className="flex flex-col gap-4 px-0">
          <Field className="px-(--card-spacing) sm:max-w-md">
            <FieldLabel htmlFor="approval-filter">Filter approvals</FieldLabel>
            <Input
              id="approval-filter"
              type="search"
              placeholder="Customer, case, or plan"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
            <FieldDescription>
              Search by customer name, case ID, or subscription plan.
            </FieldDescription>
          </Field>

          {pending.length ? (
            <Table>
              <TableCaption className="sr-only">
                Recovery cases waiting for an operator decision.
              </TableCaption>
              <TableHeader>
                <TableRow>
                  <TableHead className="pl-4">Customer</TableHead>
                  <TableHead>Action</TableHead>
                  <TableHead>Amount</TableHead>
                  <TableHead>Evidence</TableHead>
                  <TableHead>Deadline</TableHead>
                  <TableHead className="pr-4 text-right">Decision</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {pending.map((item) => (
                  <TableRow key={item.case_id}>
                    <TableCell className="pl-4">
                      <Link
                        className="font-medium underline-offset-4 hover:underline"
                        href={`/cases/${item.case_id}`}
                      >
                        {item.customer_display_name}
                      </Link>
                      <span className="mt-1 block text-sm text-muted-foreground">
                        {item.plan_name}
                      </span>
                    </TableCell>
                    <TableCell className="max-w-72 whitespace-normal">
                      <span className="font-medium">
                        {humanize(
                          item.payment_surface_type ?? item.recommended_action,
                        )}
                      </span>
                      <span className="mt-1 block text-sm text-muted-foreground">
                        {item.policy_reason}
                      </span>
                    </TableCell>
                    <TableCell className="font-medium tabular-nums text-destructive">
                      {formatPaise(item.amount_at_risk_paise)}
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-1">
                        <Badge variant="info">{humanize(item.provider)}</Badge>
                        <Badge
                          variant={
                            item.evidence_kind === "RAZORPAY_TEST_VERIFIED"
                              ? "success"
                              : "warning"
                          }
                        >
                          {formatEvidenceKind(item.evidence_kind)}
                        </Badge>
                      </div>
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {item.deadline
                        ? formatDateTime(item.deadline)
                        : "Open case for deadline"}
                    </TableCell>
                    <TableCell className="pr-4 text-right">
                      <Button size="sm" onClick={() => setSelected(item)}>
                        Review
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <QueueEmpty
              filtered={Boolean(query)}
              onClear={() => setQuery("")}
            />
          )}
        </CardContent>
      </Card>

      <ConfirmDialog
        open={Boolean(selected)}
        title="Approve this recovery surface?"
        description={`RecoveryOS will authorize one ${humanize(selected?.payment_surface_type ?? "OPEN_CUSTOMER_PAYMENT_SURFACE")} for ${selected?.customer_display_name ?? "this customer"}.`}
        confirmationText={
          resource.source === "mock"
            ? "This demo remains in mock mode; no charge is attempted and a browser callback never proves payment."
            : "Only this exact surface is approved. A browser callback never proves payment; provider reconciliation remains authoritative."
        }
        confirmLabel="Approve exact surface"
        busy={busy}
        onCancel={() => setSelected(null)}
        onConfirm={approve}
      />
    </div>
  );
}
