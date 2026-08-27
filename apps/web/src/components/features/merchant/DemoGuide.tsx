"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { Badge } from "@/components/ui";

import styles from "./merchant.module.css";

const STORAGE_KEY = "recoveryos-fitbox-demo-progress-v1";

const demoSteps = [
  {
    id: "control-tower",
    href: "/dashboard",
    label: "Frame the failure",
    detail: "Open the Control Tower and confirm ₹1,499 is at risk.",
    duration: "0:45",
    matches: (pathname: string) => pathname === "/dashboard",
  },
  {
    id: "fitbox-case",
    href: "/cases/case_fitbox_aug_2026",
    label: "Inspect the decision",
    detail: "Show authentication evidence, policy, and the native surface.",
    duration: "1:30",
    matches: (pathname: string) => pathname.startsWith("/cases/"),
  },
  {
    id: "approval",
    href: "/approvals",
    label: "Demonstrate control",
    detail: "Review the exact surface and the mock-only approval guardrail.",
    duration: "0:45",
    matches: (pathname: string) => pathname === "/approvals",
  },
  {
    id: "voice",
    href: "/voice",
    label: "Rehearse safe outreach",
    detail: "Use browser rehearsal to show opt-out and intent precedence.",
    duration: "0:45",
    matches: (pathname: string) => pathname === "/voice",
  },
  {
    id: "lab",
    href: "/lab",
    label: "Close with evidence",
    detail: "Explain the fixed-seed evaluation and simulated-only metrics.",
    duration: "1:15",
    matches: (pathname: string) => pathname === "/lab",
  },
] as const;

function readVisitedSteps(): string[] {
  try {
    const stored = window.sessionStorage.getItem(STORAGE_KEY);
    const parsed: unknown = stored ? JSON.parse(stored) : [];
    return Array.isArray(parsed)
      ? parsed.filter((item): item is string => typeof item === "string")
      : [];
  } catch {
    return [];
  }
}

export function DemoGuide() {
  const pathname = usePathname();
  const router = useRouter();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLElement>(null);
  const [open, setOpen] = useState(false);
  const [visited, setVisited] = useState<string[]>([]);
  const [announcement, setAnnouncement] = useState("");

  useEffect(() => {
    const updateProgress = window.setTimeout(() => {
      const currentStep = demoSteps.find((step) => step.matches(pathname));
      const stored = readVisitedSteps();
      const next = currentStep
        ? Array.from(new Set([...stored, currentStep.id]))
        : stored;
      setVisited(next);
      window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    }, 0);
    return () => window.clearTimeout(updateProgress);
  }, [pathname]);

  useEffect(() => {
    if (!open) return;
    closeRef.current?.focus({ preventScroll: true });
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        triggerRef.current?.focus({ preventScroll: true });
        return;
      }
      if (event.key !== "Tab" || !panelRef.current) return;
      const focusable = Array.from(
        panelRef.current.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus({ preventScroll: true });
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus({ preventScroll: true });
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open]);

  const currentIndex = demoSteps.findIndex((step) => step.matches(pathname));
  const nextStep = useMemo(
    () => demoSteps.find((step) => !visited.includes(step.id)),
    [visited],
  );

  const resetGuide = () => {
    window.sessionStorage.removeItem(STORAGE_KEY);
    setVisited([]);
    setAnnouncement(
      "Guided demo progress reset. Case data and provider safety settings were not changed.",
    );
    router.push("/dashboard");
  };

  const closeGuide = () => {
    setOpen(false);
    triggerRef.current?.focus({ preventScroll: true });
  };

  return (
    <>
      <button
        ref={triggerRef}
        className={styles.demoTrigger}
        type="button"
        aria-label="Open 5-min demo guide for FitBox"
        aria-expanded={open}
        aria-controls="fitbox-demo-guide"
        onClick={() => setOpen(true)}
      >
        <span className={styles.demoTriggerDot} aria-hidden="true" />
        <span>5-min demo</span>
        <span className={styles.demoTriggerProgress}>
          {visited.length}/{demoSteps.length}
        </span>
      </button>

      {open && (
        <div className={styles.demoBackdrop} role="presentation">
          <aside
            ref={panelRef}
            id="fitbox-demo-guide"
            className={styles.demoPanel}
            role="dialog"
            aria-modal="true"
            aria-labelledby="fitbox-demo-title"
            aria-describedby="fitbox-demo-description"
          >
            <div className={styles.demoPanelHeader}>
              <div>
                <div className={styles.demoPanelEyebrow}>
                  <Badge tone="info">Mock-only walkthrough</Badge>
                  <span>5:00 total</span>
                </div>
                <h2 id="fitbox-demo-title" className={styles.demoPanelTitle}>
                  FitBox judge route
                </h2>
                <p
                  id="fitbox-demo-description"
                  className={styles.demoPanelDescription}
                >
                  Five focused stops from failure to auditable recovery. This
                  guide only navigates and tracks progress in this browser tab.
                </p>
              </div>
              <button
                ref={closeRef}
                className={styles.demoClose}
                type="button"
                aria-label="Close five-minute demo guide"
                onClick={closeGuide}
              >
                ×
              </button>
            </div>

            <div className={styles.demoSafetyStrip}>
              <span className={styles.demoSafetyIcon} aria-hidden="true">
                ✓
              </span>
              <div>
                <strong>External actions stay locked</strong>
                <p>
                  Navigation and reset cannot enable Razorpay, Twilio, or any
                  other provider action.
                </p>
              </div>
            </div>

            <ol className={styles.demoSteps}>
              {demoSteps.map((step, index) => {
                const isCurrent = index === currentIndex;
                const isVisited = visited.includes(step.id);
                return (
                  <li
                    className={`${styles.demoStep} ${isCurrent ? styles.demoStepCurrent : ""}`}
                    key={step.id}
                  >
                    <span className={styles.demoStepNumber} aria-hidden="true">
                      {isVisited && !isCurrent ? "✓" : index + 1}
                    </span>
                    <div className={styles.demoStepBody}>
                      <div className={styles.demoStepHeading}>
                        <Link href={step.href} onClick={() => setOpen(false)}>
                          {step.label}
                        </Link>
                        <span>{step.duration}</span>
                      </div>
                      <p>{step.detail}</p>
                      <span className={styles.demoStepStatus}>
                        {isCurrent
                          ? "Current stop"
                          : isVisited
                            ? "Visited"
                            : "Ready"}
                      </span>
                    </div>
                  </li>
                );
              })}
            </ol>

            <div className={styles.demoPanelFooter}>
              <div className={styles.demoStatus} role="status">
                <strong>
                  {visited.length === demoSteps.length
                    ? "Walkthrough complete"
                    : `${visited.length} of ${demoSteps.length} stops visited`}
                </strong>
                <span>
                  {nextStep
                    ? `Next: ${nextStep.label}`
                    : "Ready to reset and replay."}
                </span>
              </div>
              <button
                className={styles.demoReset}
                type="button"
                onClick={resetGuide}
              >
                Reset guided demo
              </button>
            </div>
            <p className={styles.srOnly} aria-live="polite">
              {announcement}
            </p>
          </aside>
        </div>
      )}
    </>
  );
}
