"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Brand } from "@/components/layout";
import { Alert, Button, Input, TestModeBadge } from "@/components/ui";
import styles from "@/components/features/merchant/merchant.module.css";
import { createOperatorSession } from "@/lib/operator-session";

export default function LoginPage() {
  const router = useRouter();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    const form = new FormData(event.currentTarget);
    try {
      await createOperatorSession(
        String(form.get("email") ?? ""),
        String(form.get("password") ?? ""),
      );
      window.sessionStorage.setItem("recoveryos-demo-session", "active");
      router.push("/dashboard");
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "The operator session could not be created.",
      );
      setSubmitting(false);
    }
  }

  return (
    <main className={styles.loginPage}>
      <section className={styles.loginHero} aria-labelledby="login-hero-title">
        <Link
          className={styles.brandLink}
          href="/"
          aria-label="RecoveryOS home"
        >
          <Brand />
        </Link>
        <div className={styles.loginHeroCopy}>
          <p className={styles.loginEyebrow}>Auditable revenue recovery</p>
          <h1 id="login-hero-title" className={styles.loginTitle}>
            Recover the payment. Preserve the trust.
          </h1>
          <p className={styles.loginDescription}>
            Understand every failed subscription, choose the safest recovery
            path, and keep humans in control of consequential actions.
          </p>
          <div className={styles.trustRow} aria-label="Product safeguards">
            <span className={styles.trustPill}>Invoice-scoped recovery</span>
            <span className={styles.trustPill}>Policy-first decisions</span>
            <span className={styles.trustPill}>Complete audit trail</span>
          </div>
        </div>
        <p className={styles.environmentCopy}>
          Independent hackathon demo · not affiliated with Razorpay.
        </p>
      </section>

      <section className={styles.loginPanel} aria-labelledby="login-heading">
        <div className={styles.loginCard}>
          <TestModeBadge />
          <h2 id="login-heading" className={styles.loginHeading}>
            Open the FitBox workspace
          </h2>
          <p className={styles.loginSubheading}>
            Use the seeded operator account to explore a complete
            failed-subscription recovery. No real provider action is enabled.
          </p>
          <form className={styles.loginForm} onSubmit={submit}>
            <Input
              label="Work email"
              name="email"
              type="email"
              autoComplete="email"
              defaultValue="demo@recoveryos.dev"
              required
            />
            <Input
              label="Demo access code"
              name="password"
              type="password"
              autoComplete="current-password"
              defaultValue="recovery-demo"
              required
            />
            <div className={styles.loginHint}>
              The API issues an HttpOnly operator session. Real payment and
              calling controls remain independently server-side gated.
            </div>
            {error && (
              <Alert tone="danger" title="Sign-in failed">
                {error}
              </Alert>
            )}
            <Button fullWidth size="lg" type="submit" loading={submitting}>
              Enter Control Tower
            </Button>
          </form>
        </div>
      </section>
    </main>
  );
}
