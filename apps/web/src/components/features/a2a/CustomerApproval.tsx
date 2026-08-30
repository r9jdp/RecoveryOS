"use client";

import { useCallback, useEffect, useId, useState } from "react";
import Link from "next/link";

import { Alert, Badge, Button } from "@/components/ui";
import {
  loadApprovalSummary,
  submitApprovalDecision,
  type ApprovalChoice,
  type ApprovalResult,
  type ApprovalSubmission,
  type ApprovalSummary,
} from "@/lib/a2a/client";

import styles from "./a2a.module.css";

interface CustomerApprovalProps {
  taskId: string;
  customerAgentOrigin: string;
  loadApproval?: (
    taskId: string,
    signal?: AbortSignal,
  ) => Promise<ApprovalSummary>;
  submitApproval?: (
    taskId: string,
    submission: ApprovalSubmission,
  ) => Promise<ApprovalResult>;
}

type ViewState = "loading" | "ready" | "approved" | "rejected" | "error";

export function CustomerApproval({
  taskId,
  customerAgentOrigin,
  loadApproval,
  submitApproval,
}: CustomerApprovalProps) {
  const [summary, setSummary] = useState<ApprovalSummary | null>(null);
  const [viewState, setViewState] = useState<ViewState>("loading");
  const [confirmed, setConfirmed] = useState(false);
  const [submitting, setSubmitting] = useState<ApprovalChoice | null>(null);
  const [error, setError] = useState<string | null>(null);
  const confirmationId = useId();

  const fetchApproval = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const result = await (loadApproval
          ? loadApproval(taskId, signal)
          : loadApprovalSummary(customerAgentOrigin, taskId, signal));
        if (signal?.aborted) return;
        setSummary(result);
        if (result.state === "TASK_STATE_CANCELED") setViewState("rejected");
        else if (result.state !== "TASK_STATE_AUTH_REQUIRED")
          setViewState("approved");
        else setViewState("ready");
      } catch (reason) {
        if (signal?.aborted) return;
        setError(
          reason instanceof Error
            ? reason.message
            : "Unable to load authorization",
        );
        setViewState("error");
      }
    },
    [customerAgentOrigin, loadApproval, taskId],
  );

  useEffect(() => {
    const controller = new AbortController();
    const kickoff = window.setTimeout(() => {
      void fetchApproval(controller.signal);
    }, 0);
    return () => {
      window.clearTimeout(kickoff);
      controller.abort();
    };
  }, [fetchApproval]);

  const retry = () => {
    setViewState("loading");
    setError(null);
    void fetchApproval();
  };

  const decide = async (decision: ApprovalChoice) => {
    if (!summary || (decision === "APPROVE" && !confirmed)) return;
    setSubmitting(decision);
    setError(null);
    const payload: ApprovalSubmission = {
      decision,
      merchant_id: summary.merchant_id,
      case_id: summary.case_id,
      exact_amount_paise: summary.exact_amount_paise,
      payment_surface_reference: summary.payment_surface_reference,
    };
    try {
      await (submitApproval
        ? submitApproval(taskId, payload)
        : submitApprovalDecision(customerAgentOrigin, taskId, payload));
      setViewState(decision === "APPROVE" ? "approved" : "rejected");
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Unable to save your decision",
      );
    } finally {
      setSubmitting(null);
    }
  };

  return (
    <main className={styles.canvas}>
      <header className={styles.header}>
        <Link className={styles.brand} href="/" aria-label="RecoveryOS home">
          <span className={styles.brandMark} aria-hidden="true">
            R
          </span>
          <span>RecoveryOS</span>
        </Link>
        <Badge tone="info" showDot>
          Secure A2A approval
        </Badge>
      </header>

      <section className={styles.stage} aria-labelledby="approval-title">
        {viewState === "loading" && <ApprovalLoading />}
        {viewState === "error" && (
          <div className={styles.stateCard}>
            <span className={styles.stateIcon} aria-hidden="true">
              !
            </span>
            <h1 id="approval-title">We could not load this request</h1>
            <Alert tone="danger" title="Authorization unavailable">
              {error}
            </Alert>
            <Button onClick={retry}>Try again</Button>
          </div>
        )}
        {viewState === "ready" && summary && (
          <article className={styles.approvalCard}>
            <header className={styles.requestHeader}>
              <div className={styles.eyebrow}>Customer authorization</div>
              <h1 id="approval-title">Review recovery authorization</h1>
              <p className={styles.intro}>
                {summary.merchant_display_name} is asking you to approve one
                exact payment surface for a failed subscription renewal.
              </p>
            </header>

            {error && (
              <Alert tone="danger" title="Your decision was not saved">
                {error}
              </Alert>
            )}

            <section
              className={styles.summaryCard}
              aria-labelledby="request-details"
            >
              <div className={styles.sectionHeading}>
                <h2 id="request-details">Payment request</h2>
                <p>Confirm the exact amount, merchant, and payment surface.</p>
              </div>
              <dl className={styles.summary}>
                <div className={styles.amountRow}>
                  <dt>Exact amount</dt>
                  <dd>
                    {formatPaise(summary.exact_amount_paise, summary.currency)}
                  </dd>
                </div>
                <div>
                  <dt>Merchant</dt>
                  <dd>{summary.merchant_display_name}</dd>
                </div>
                <div>
                  <dt>Reason</dt>
                  <dd>{summary.recovery_reason}</dd>
                </div>
                <div>
                  <dt>Payment surface</dt>
                  <dd>{surfaceLabel(summary.payment_surface_type)}</dd>
                </div>
                <div>
                  <dt>Reference</dt>
                  <dd className={styles.mono}>
                    {summary.payment_surface_reference}
                  </dd>
                </div>
                <div>
                  <dt>Authorization expires</dt>
                  <dd>{formatExpiry(summary.expires_at)}</dd>
                </div>
              </dl>
            </section>

            <section className={styles.safetyPanel}>
              <h2>What this approval means</h2>
              <ul>
                <li>
                  It is valid only for the amount and surface shown above.
                </li>
                <li>
                  The authorization is signed and can be consumed only once.
                </li>
                <li>
                  This customer agent never executes a payment. RecoveryOS
                  verifies the mandate before a provider activity may open the
                  exact surface.
                </li>
                <li>
                  A browser callback is never accepted as proof of payment.
                </li>
              </ul>
            </section>

            <section
              className={styles.decisionPanel}
              aria-labelledby="decision-heading"
            >
              <div className={styles.sectionHeading}>
                <h2 id="decision-heading">Your decision</h2>
                <p>No charge happens on this page.</p>
              </div>
              <label className={styles.confirmation} htmlFor={confirmationId}>
                <input
                  id={confirmationId}
                  type="checkbox"
                  checked={confirmed}
                  onChange={(event) => setConfirmed(event.target.checked)}
                />
                <span>
                  I approve this exact{" "}
                  {formatPaise(summary.exact_amount_paise, summary.currency)}
                  {" payment surface."}
                </span>
              </label>

              <div className={styles.actions}>
                <Button
                  variant="secondary"
                  disabled={submitting !== null}
                  loading={submitting === "REJECT"}
                  onClick={() => void decide("REJECT")}
                >
                  Decline
                </Button>
                <Button
                  disabled={!confirmed || submitting !== null}
                  loading={submitting === "APPROVE"}
                  onClick={() => void decide("APPROVE")}
                >
                  Approve exact surface
                </Button>
              </div>
            </section>
          </article>
        )}
        {viewState === "approved" && (
          <DecisionState
            title="Authorization recorded"
            message="Your single-use mandate is ready. RecoveryOS must verify its signature and exact scope before opening the payment surface. A provider receipt will complete the task."
          />
        )}
        {viewState === "rejected" && (
          <DecisionState
            title="Authorization declined"
            message="No payment mandate was issued. RecoveryOS will record your decision and stop this authorization path."
          />
        )}
      </section>

      <footer className={styles.footer}>
        Independent RecoveryOS demo · No Razorpay affiliation implied
      </footer>
    </main>
  );
}

function ApprovalLoading() {
  return (
    <div className={styles.loadingCard} role="status" aria-live="polite">
      <span className={styles.spinner} aria-hidden="true" />
      <p>Loading secure authorization…</p>
    </div>
  );
}

function DecisionState({ title, message }: { title: string; message: string }) {
  return (
    <div className={styles.stateCard}>
      <span className={styles.successIcon} aria-hidden="true">
        ✓
      </span>
      <h1 id="approval-title">{title}</h1>
      <p>{message}</p>
      <Badge tone="success" showDot>
        Decision saved
      </Badge>
    </div>
  );
}

export function formatPaise(amountPaise: number, currency: string): string {
  if (!Number.isSafeInteger(amountPaise) || amountPaise < 0)
    return "Invalid amount";
  const paise = BigInt(amountPaise);
  const whole = paise / 100n;
  const fraction = (paise % 100n).toString().padStart(2, "0");
  const formattedWhole = new Intl.NumberFormat("en-IN", {
    maximumFractionDigits: 0,
  }).format(whole);
  const symbol = currency === "INR" ? "₹" : `${currency} `;
  return `${symbol}${formattedWhole}.${fraction}`;
}

function formatExpiry(value: string): string {
  return new Intl.DateTimeFormat("en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZoneName: undefined,
  }).format(new Date(value));
}

function surfaceLabel(value: string): string {
  return value
    .toLowerCase()
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}
