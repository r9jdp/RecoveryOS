import { ArrowRightIcon } from "lucide-react";
import Link from "next/link";

import { Brand } from "@/components/layout";
import { buttonVariants } from "@/components/shadcn/button";
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
import { cn } from "@/lib/utils";

import styles from "./page.module.css";

const caseFacts = [
  { label: "Failure", value: "Payment authorization declined" },
  { label: "Diagnosis", value: "Customer authentication required" },
  { label: "Policy checkpoint", value: "Operator review" },
  { label: "Recovery path", value: "Secure payment update" },
];

const recoveryFlow = [
  {
    time: "09:42:17",
    machineLabel: "EVIDENCE / PAYMENT.FAILED",
    title: "Provider failure verified",
    description: "Webhook signature and invoice correlation remain attached.",
  },
  {
    time: "09:42:19",
    machineLabel: "DECISION / ACTION.RECOMMENDED",
    title: "Secure payment update selected",
    description: "Policy matched a subscription-scoped recovery path.",
  },
  {
    time: "PENDING",
    machineLabel: "CONTROL / OPERATOR",
    title: "Approval checkpoint ready",
    description: "Approve, reject, stop, or escalate from the case workspace.",
  },
  {
    time: "AWAITING",
    machineLabel: "PROOF / RAZORPAY",
    title: "Provider confirmation pending",
    description: "Recovered revenue updates only after settlement evidence.",
  },
];

const auditRecords = [
  {
    index: "01",
    label: "Evidence",
    traceState: "recorded",
    title: "Keep the source attached.",
    description:
      "Signature, evidence kind, correlation ID, and failed invoice stay inspectable.",
  },
  {
    index: "02",
    label: "Decision",
    traceState: "derived",
    title: "Make the choice legible.",
    description:
      "Deterministic recovery logic records the selected surface and rejected alternatives.",
  },
  {
    index: "03",
    label: "Control",
    traceState: "gated",
    title: "Let policy win.",
    description:
      "Consent, disputes, suppression, and operator commands remain authoritative.",
  },
  {
    index: "04",
    label: "Proof",
    traceState: "awaiting",
    title: "Count only what settled.",
    description:
      "Provider-confirmed payment state—not a browser callback—changes recovered revenue.",
  },
];

const safetyRows = [
  {
    term: "Invoice scope",
    detail:
      "One failed invoice anchors the case, action, and reconciliation trail.",
  },
  {
    term: "Policy precedence",
    detail:
      "Opt-outs and disputes override recovery value and channel preference.",
  },
  {
    term: "Evidence labels",
    detail:
      "Evidence classes remain distinct until Razorpay confirms the outcome.",
  },
];

export default function HomePage() {
  return (
    <div
      className={cn(
        styles.landingTheme,
        "min-h-svh bg-background text-foreground",
      )}
    >
      <header className={styles.masthead}>
        <nav
          className="mx-auto flex w-full max-w-[96rem] items-center justify-between gap-6 px-5 py-3 md:px-8"
          aria-label="Public navigation"
        >
          <Link
            href="/"
            className={styles.wordmarkLink}
            aria-label="RecoveryOS home"
          >
            <Brand variant="ledger" aria-hidden="true" />
          </Link>
          <div className={styles.navMeta}>
            <span className={styles.documentLocator}>
              Audit ledger / Case 001
            </span>
            <span className={styles.testMode}>
              <span className={styles.liveDot} aria-hidden="true" />
              Razorpay evidence loop
            </span>
          </div>
        </nav>
      </header>

      <main className="mx-auto w-full max-w-[96rem] px-5 md:px-8">
        <section className={styles.heroGrid} aria-labelledby="hero-title">
          <header className={styles.heroCopy}>
            <p className={styles.kicker}>Deterministic payment recovery / 01</p>
            <h1 id="hero-title" className={styles.heroTitle}>
              Recover the payment.
              <span>Preserve the evidence.</span>
            </h1>
            <p className={styles.heroDescription}>
              RecoveryOS turns a failed subscription into a deterministic,
              policy-constrained next action—and does not count recovery until
              Razorpay confirms it.
            </p>

            <div className="flex w-full flex-col gap-3 sm:w-auto sm:flex-row">
              <Link
                className={buttonVariants({
                  size: "lg",
                  className: "min-h-11 px-4",
                })}
                href="/login"
              >
                Explore the recovery workspace
                <ArrowRightIcon data-icon="inline-end" />
              </Link>
              <Link
                className={buttonVariants({
                  size: "lg",
                  variant: "secondary",
                  className: "min-h-11 px-4",
                })}
                href="/dashboard"
              >
                View Control Tower
              </Link>
            </div>

            <div className={styles.boundaryNote}>
              <span>Operational controls</span>
              <p>Actions remain policy-gated and provider-verified</p>
            </div>
          </header>

          <article
            className={styles.caseColumn}
            aria-labelledby="recovery-ledger-title"
          >
            <Card className={cn(styles.caseLedger, "gap-0 py-0")}>
              <CardHeader className={styles.caseHeader}>
                <CardDescription className={styles.caseIndex}>
                  <span>Case /</span> <span>RCV-2026-0842</span>
                </CardDescription>
                <CardTitle>
                  <h2 id="recovery-ledger-title">
                    Account 2847 · Annual subscription
                  </h2>
                </CardTitle>
                <CardAction>
                  <span className={styles.failureState}>
                    <span aria-hidden="true" />
                    Payment failed
                  </span>
                </CardAction>
              </CardHeader>

              <Separator />

              <CardContent className="px-0">
                <div className={styles.amountBlock}>
                  <p>Amount at risk</p>
                  <strong>₹2,400</strong>
                  <span>INR · recurring invoice</span>
                </div>

                <dl className={styles.caseFacts}>
                  {caseFacts.map(({ label, value }) => (
                    <div key={label}>
                      <dt>{label}</dt>
                      <dd>{value}</dd>
                    </div>
                  ))}
                </dl>

                <Separator />

                <div className={styles.eventHeader}>
                  <span>Recovery workflow</span>
                  <span>4 records</span>
                </div>
                <ol
                  className={styles.eventLedger}
                  aria-label="Recovery workflow"
                >
                  {recoveryFlow.map(
                    ({ time, machineLabel, title, description }) => (
                      <li key={machineLabel}>
                        <time>{time}</time>
                        <div className={styles.eventBody}>
                          <span>{machineLabel}</span>
                          <strong>{title}</strong>
                          <p>{description}</p>
                        </div>
                      </li>
                    ),
                  )}
                </ol>
              </CardContent>

              <CardFooter className={styles.caseFooter}>
                <div>
                  <span>Provider-confirmed recovery</span>
                  <strong>₹0</strong>
                </div>
                <p>
                  Only Razorpay-confirmed payment changes recovered revenue.
                </p>
              </CardFooter>
            </Card>
          </article>
        </section>

        <section
          className={styles.auditSection}
          aria-labelledby="audit-trail-title"
        >
          <header className={styles.sectionHeader}>
            <div className={styles.auditAside}>
              <p className={styles.auditKicker}>System loop / 4 records</p>
              <ol className={styles.auditSpine} aria-hidden="true">
                {auditRecords.map(({ index, label, traceState }) => (
                  <li key={index} data-state={traceState}>
                    <span className={styles.spineDot} />
                    <span className={styles.spineIndex}>{index}</span>
                    <strong>{label}</strong>
                    <span className={styles.spineState}>{traceState}</span>
                  </li>
                ))}
              </ol>
              <span className={styles.traceCase} aria-hidden="true">
                Case / RCV-2026-0842
              </span>
            </div>
            <div className={styles.sectionIntro}>
              <h2 id="audit-trail-title">What the audit trail records.</h2>
              <p>
                Every step explains what happened, what was allowed, and what
                still needs proof.
              </p>
            </div>
          </header>

          <ol
            className={styles.auditStrip}
            aria-label="Audit record categories"
          >
            {auditRecords.map(({ index, label, title, description }) => (
              <li key={index}>
                <article>
                  <div className={styles.recordMeta}>
                    <span>{index}</span>
                    <span>{label}</span>
                  </div>
                  <div
                    className={styles.recordSignal}
                    data-step={index}
                    aria-hidden="true"
                  >
                    <span />
                    <span />
                    <span />
                    <span />
                  </div>
                  <h3>{title}</h3>
                  <p>{description}</p>
                </article>
              </li>
            ))}
          </ol>
        </section>

        <section
          className={styles.safetySection}
          aria-labelledby="safety-title"
        >
          <header>
            <p className={styles.kicker}>Safety appendix / A</p>
            <h2 id="safety-title">Safety, written into the system.</h2>
            <p>
              Recovery is useful only when its limits are visible and
              enforceable.
            </p>
          </header>

          <dl className={styles.safetyRows}>
            {safetyRows.map(({ term, detail }) => (
              <div key={term}>
                <dt>{term}</dt>
                <dd>{detail}</dd>
              </div>
            ))}
          </dl>
        </section>
      </main>

      <footer className={styles.footer}>
        <div className="mx-auto flex w-full max-w-[96rem] flex-col justify-between gap-2 px-5 py-5 sm:flex-row md:px-8">
          <span>RecoveryOS / auditable revenue recovery</span>
          <span>Independent product showcase · no Razorpay endorsement</span>
        </div>
      </footer>
    </div>
  );
}
