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
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
  TableViewport,
} from "@/components/ui";
import { executeCaseCommand } from "@/lib/api/recovery-client";
import { approvalItems } from "@/lib/merchant-demo";
import {
  formatDateTime,
  formatEvidenceKind,
  formatPaise,
  humanize,
} from "@/lib/recovery-format";
import type { ApprovalItem, CommandResult } from "@/types/recovery";

import { ConfirmDialog } from "./ConfirmDialog";
import styles from "./merchant.module.css";

interface ApprovalQueueProps {
  runApproval?: (caseId: string) => Promise<CommandResult>;
}

export function ApprovalQueue({
  runApproval = (caseId) => executeCaseCommand(caseId, "APPROVE"),
}: ApprovalQueueProps) {
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<ApprovalItem | null>(null);
  const [busy, setBusy] = useState(false);
  const [approved, setApproved] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return approvalItems.filter((item) =>
      [item.customer_display_name, item.case_id, item.plan_name].some((value) =>
        value.toLowerCase().includes(needle),
      ),
    );
  }, [query]);

  async function approve() {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      await runApproval(selected.case_id);
      setApproved((current) => [...current, selected.case_id]);
      setSelected(null);
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

  const pending = filtered.filter((item) => !approved.includes(item.case_id));
  return (
    <div className={styles.pageStack}>
      <PageHeader
        eyebrow="Human review"
        title="Approval queue"
        description="Review the policy evidence and exact customer surface before any recovery action is opened."
        action={<Badge tone="warning">{pending.length} awaiting review</Badge>}
      />
      {error && (
        <Alert tone="danger" title="Approval failed">
          {error} The case remains unchanged and can be retried safely.
        </Alert>
      )}
      <h2 className={styles.srOnly}>Cases awaiting operator approval</h2>
      <Card>
        <CardHeader
          title="Manual approvals"
          description="Only the exact surface shown below will be authorized."
          action={
            <label>
              <span className={styles.srOnly}>Filter approval queue</span>
              <input
                className={styles.filterInput}
                type="search"
                placeholder="Customer, case, or plan"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
            </label>
          }
        />
        <CardBody>
          {pending.length ? (
            <TableViewport>
              <Table>
                <TableCaption>
                  Recovery cases waiting for an operator decision.
                </TableCaption>
                <TableHead>
                  <TableRow>
                    <TableHeaderCell>Customer</TableHeaderCell>
                    <TableHeaderCell>Action</TableHeaderCell>
                    <TableHeaderCell>Amount</TableHeaderCell>
                    <TableHeaderCell>Evidence</TableHeaderCell>
                    <TableHeaderCell>Deadline</TableHeaderCell>
                    <TableHeaderCell>Decision</TableHeaderCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {pending.map((item) => (
                    <TableRow key={item.case_id}>
                      <TableCell>
                        <Link
                          className={styles.caseLink}
                          href={`/cases/${item.case_id}`}
                        >
                          {item.customer_display_name}
                        </Link>
                        <p className={styles.quiet}>{item.plan_name}</p>
                      </TableCell>
                      <TableCell>
                        <strong>
                          {humanize(
                            item.payment_surface_type ??
                              item.recommended_action,
                          )}
                        </strong>
                        <p className={styles.quiet}>{item.policy_reason}</p>
                      </TableCell>
                      <TableCell>
                        {formatPaise(item.amount_at_risk_paise)}
                      </TableCell>
                      <TableCell>
                        <div className={styles.badgeStack}>
                          <Badge tone="neutral">
                            {humanize(item.provider)}
                          </Badge>
                          <Badge
                            tone={
                              item.evidence_kind === "SIMULATED"
                                ? "info"
                                : "success"
                            }
                          >
                            {formatEvidenceKind(item.evidence_kind)}
                          </Badge>
                        </div>
                      </TableCell>
                      <TableCell>{formatDateTime(item.deadline)}</TableCell>
                      <TableCell>
                        <Button size="sm" onClick={() => setSelected(item)}>
                          Review
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableViewport>
          ) : (
            <EmptyState
              title={
                query ? "No matching approvals" : "Approval queue is clear"
              }
              description={
                query
                  ? "Try a different customer, case, or plan."
                  : "Every high-impact recovery action has been reviewed."
              }
              action={
                query ? (
                  <Button variant="secondary" onClick={() => setQuery("")}>
                    Clear filter
                  </Button>
                ) : undefined
              }
            />
          )}
        </CardBody>
      </Card>
      <ConfirmDialog
        open={Boolean(selected)}
        title="Approve this recovery surface?"
        description={`RecoveryOS will authorize one ${humanize(selected?.payment_surface_type ?? "OPEN_CUSTOMER_PAYMENT_SURFACE")} for ${selected?.customer_display_name ?? "this customer"}.`}
        confirmationText="This demo remains in mock mode; no charge is attempted and a browser callback never proves payment."
        confirmLabel="Approve exact surface"
        busy={busy}
        onCancel={() => setSelected(null)}
        onConfirm={approve}
      />
    </div>
  );
}
