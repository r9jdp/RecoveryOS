import Link from "next/link";

import { Brand } from "@/components/layout";
import { Badge, TestModeBadge } from "@/components/ui";
import styles from "@/components/features/merchant/merchant.module.css";

const demoStops = [
  "See the ₹1,499 FitBox failure",
  "Inspect diagnosis and policy evidence",
  "Approve one mock-only recovery surface",
  "Close with deterministic RecoveryBench results",
];

export default function HomePage() {
  return (
    <main className={styles.landingPage}>
      <nav className={styles.landingNav} aria-label="Public navigation">
        <Link
          className={styles.brandLink}
          href="/"
          aria-label="RecoveryOS home"
        >
          <Brand />
        </Link>
        <div className={styles.landingNavMeta}>
          <TestModeBadge />
          <span>Independent hackathon demo</span>
        </div>
      </nav>

      <section className={styles.landingHero}>
        <div className={styles.landingCopy}>
          <p className={styles.landingEyebrow}>Mock-first revenue recovery</p>
          <h1>From failed invoice to an auditable next action.</h1>
          <p className={styles.landingDescription}>
            RecoveryOS explains subscription failures, applies deterministic
            safety policy, and keeps a human in control of every consequential
            recovery action.
          </p>
          <div className={styles.landingActions}>
            <Link className={styles.landingPrimary} href="/login">
              Open the FitBox demo
              <span aria-hidden="true">→</span>
            </Link>
            <Link className={styles.landingSecondary} href="/dashboard">
              View seeded Control Tower
            </Link>
          </div>
          <p className={styles.landingSafetyNote}>
            <span aria-hidden="true">✓</span> Demo access is prefilled. Real
            payment and calling controls remain server-side gated.
          </p>
        </div>

        <aside className={styles.landingDemoCard} aria-label="FitBox demo path">
          <div className={styles.landingDemoHeader}>
            <div>
              <p>Seeded judge scenario</p>
              <h2>FitBox Annual</h2>
            </div>
            <Badge tone="info">5:00 route</Badge>
          </div>
          <div className={styles.landingAmount}>
            <span>Revenue at risk</span>
            <strong>₹1,499</strong>
            <Badge tone="warning">Authentication required</Badge>
          </div>
          <ol className={styles.landingDemoSteps}>
            {demoStops.map((stop, index) => (
              <li key={stop}>
                <span aria-hidden="true">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <p>{stop}</p>
              </li>
            ))}
          </ol>
          <div className={styles.landingEvidence}>
            <Badge tone="neutral">SIMULATED</Badge>
            <span>Default evidence · no external action</span>
          </div>
        </aside>
      </section>

      <section className={styles.landingProof} aria-label="Product safeguards">
        <div>
          <strong>Invoice scoped</strong>
          <span>No detached payment recovery</span>
        </div>
        <div>
          <strong>Policy first</strong>
          <span>Opt-out and dispute precedence</span>
        </div>
        <div>
          <strong>Evidence labelled</strong>
          <span>Simulation never counts as verified revenue</span>
        </div>
      </section>

      <footer className={styles.landingFooter}>
        <span>RecoveryOS</span>
        <span>No Razorpay affiliation or endorsement implied.</span>
      </footer>
    </main>
  );
}
