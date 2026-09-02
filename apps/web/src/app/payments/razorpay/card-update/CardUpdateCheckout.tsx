"use client";

import Link from "next/link";
import Script from "next/script";
import { useState } from "react";

import { Brand } from "@/components/layout";
import { Alert, Button, TestModeBadge } from "@/components/ui";

import styles from "./card-update.module.css";

interface RazorpayCheckout {
  open(): void;
  on(event: "payment.failed", callback: () => void): void;
}

interface RazorpayCheckoutConstructor {
  new (options: Record<string, unknown>): RazorpayCheckout;
}

declare global {
  interface Window {
    Razorpay?: RazorpayCheckoutConstructor;
  }
}

export interface CardUpdateCheckoutProps {
  caseId: string;
  keyId: string;
  subscriptionId: string;
}

type CheckoutStatus = "idle" | "opening" | "submitted" | "failed";

export function CardUpdateCheckout({
  caseId,
  keyId,
  subscriptionId,
}: CardUpdateCheckoutProps) {
  const [scriptReady, setScriptReady] = useState(false);
  const [status, setStatus] = useState<CheckoutStatus>("idle");

  const invalidRequest = !caseId || !keyId || !subscriptionId;

  function openCheckout() {
    if (invalidRequest || !scriptReady || !window.Razorpay) {
      setStatus("failed");
      return;
    }

    setStatus("opening");
    const checkout = new window.Razorpay({
      key: keyId,
      subscription_id: subscriptionId,
      subscription_card_change: true,
      name: "RecoveryOS merchant checkout",
      description: "Update the card used for this subscription",
      theme: { color: "#1748FF" },
      handler: () => {
        // The browser response is deliberately not used to close the case.
        // RecoveryOS waits for a verified webhook and authoritative fetch.
        setStatus("submitted");
      },
      modal: {
        ondismiss: () => setStatus("idle"),
      },
    });
    checkout.on("payment.failed", () => setStatus("failed"));
    checkout.open();
  }

  return (
    <main className={styles.page}>
      <Script
        src="https://checkout.razorpay.com/v1/checkout.js"
        strategy="afterInteractive"
        onLoad={() => setScriptReady(true)}
        onError={() => setStatus("failed")}
      />
      <section className={styles.shell} aria-labelledby="card-update-title">
        <header className={styles.header}>
          <Link
            className={styles.brandLink}
            href="/login"
            aria-label="RecoveryOS operator login"
          >
            <Brand variant="ledger" aria-hidden="true" />
          </Link>
          <TestModeBadge className={styles.statusTag} />
        </header>

        <div className={styles.content}>
          <div className={styles.documentMeta}>
            <span>Surface / Card update</span>
            <span>Provider / Razorpay</span>
          </div>
          <p className={styles.eyebrow}>Secure subscription recovery / 02</p>
          <h1 id="card-update-title">
            Update the card for this <em>subscription.</em>
          </h1>
          <p className={styles.description}>
            Razorpay Checkout collects the new card details. RecoveryOS never
            receives or stores the card number.
          </p>

          <dl className={styles.details}>
            <div>
              <dt>Recovery case</dt>
              <dd>{caseId || "Missing"}</dd>
            </div>
            <div>
              <dt>Subscription</dt>
              <dd>{subscriptionId || "Missing"}</dd>
            </div>
          </dl>

          {invalidRequest ? (
            <Alert
              className={styles.notice}
              tone="danger"
              title="This card-update link is incomplete"
            >
              Return to the merchant and request a new recovery link.
            </Alert>
          ) : status === "submitted" ? (
            <Alert
              className={styles.notice}
              tone="success"
              title="Card update submitted"
            >
              RecoveryOS is waiting for Razorpay&apos;s signed webhook and an
              authoritative provider check before it changes the case status.
            </Alert>
          ) : status === "failed" ? (
            <Alert
              className={styles.notice}
              tone="danger"
              title="Checkout could not be completed"
            >
              No recovery status was changed. You can safely try opening
              Checkout again.
            </Alert>
          ) : null}

          <Button
            className={styles.checkoutButton}
            fullWidth
            size="lg"
            onClick={openCheckout}
            disabled={invalidRequest || !scriptReady}
            loading={status === "opening"}
          >
            {scriptReady ? "Open secure Checkout" : "Loading secure Checkout"}
          </Button>

          <p className={styles.disclaimer}>
            Razorpay test mode. RecoveryOS is not affiliated with Razorpay. A
            browser success message is not proof of payment.
          </p>
        </div>
      </section>
    </main>
  );
}
