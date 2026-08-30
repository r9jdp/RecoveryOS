"use client";

import {
  CheckIcon,
  MapIcon,
  RotateCcwIcon,
  ShieldCheckIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/shadcn/alert";
import { Badge } from "@/components/shadcn/badge";
import { Button } from "@/components/shadcn/button";
import { Separator } from "@/components/shadcn/separator";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/shadcn/sheet";

const STORAGE_KEY = "recoveryos-fitbox-demo-progress-v1";

const demoSteps = [
  {
    id: "control-tower",
    href: "/dashboard",
    label: "Frame the failure",
    detail: "Open the Control Tower and confirm ₹1,499 is at risk.",
    matches: (pathname: string) => pathname === "/dashboard",
  },
  {
    id: "fitbox-case",
    href: "/cases/case_fitbox_aug_2026",
    label: "Inspect the decision",
    detail: "Show authentication evidence, policy, and the native surface.",
    matches: (pathname: string) => pathname.startsWith("/cases/"),
  },
  {
    id: "approval",
    href: "/approvals",
    label: "Demonstrate control",
    detail:
      "Review the exact surface and its provider-safe approval guardrail.",
    matches: (pathname: string) => pathname === "/approvals",
  },
  {
    id: "voice",
    href: "/voice",
    label: "Rehearse safe outreach",
    detail: "Use browser rehearsal to show opt-out and intent precedence.",
    matches: (pathname: string) => pathname === "/voice",
  },
  {
    id: "lab",
    href: "/lab",
    label: "Close with evidence",
    detail: "Explain the fixed-seed evaluation and its metric safeguards.",
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

  const currentIndex = demoSteps.findIndex((step) => step.matches(pathname));
  const nextStep = useMemo(
    () => demoSteps.find((step) => !visited.includes(step.id)),
    [visited],
  );

  const resetGuide = () => {
    window.sessionStorage.removeItem(STORAGE_KEY);
    setVisited([]);
    setAnnouncement(
      "Product tour progress reset. Case data and provider safety settings were not changed.",
    );
    router.push("/dashboard");
  };

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger
        render={
          <Button
            variant="outline"
            size="sm"
            aria-label="Open the RecoveryOS product tour"
          />
        }
      >
        <MapIcon data-icon="inline-start" />
        Product tour
        <Badge variant="info">
          {visited.length}/{demoSteps.length} pages
        </Badge>
      </SheetTrigger>

      <SheetContent id="fitbox-demo-guide" side="right">
        <SheetHeader className="gap-3">
          <Badge className="w-fit" variant="info">
            Navigation-only walkthrough
          </Badge>
          <div className="flex flex-col gap-1">
            <SheetTitle>RecoveryOS product tour</SheetTitle>
            <SheetDescription>
              Visit five product pages to follow a failed payment from detection
              to auditable recovery. The tour only navigates and tracks page
              visits in this browser tab.
            </SheetDescription>
          </div>
        </SheetHeader>

        <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-4">
          <Alert variant="info">
            <ShieldCheckIcon />
            <AlertTitle>External actions stay locked</AlertTitle>
            <AlertDescription>
              Navigation and reset cannot enable Razorpay, Twilio, or any other
              provider action.
            </AlertDescription>
          </Alert>

          <Separator />

          <ol className="flex flex-col">
            {demoSteps.map((step, index) => {
              const isCurrent = index === currentIndex;
              const isVisited = visited.includes(step.id);
              return (
                <li key={step.id} aria-current={isCurrent ? "step" : undefined}>
                  <div className="grid grid-cols-[auto_minmax(0,1fr)] gap-3 py-3">
                    <Badge
                      variant={
                        isCurrent ? "info" : isVisited ? "success" : "outline"
                      }
                    >
                      {isVisited && !isCurrent ? (
                        <CheckIcon data-icon="inline-start" />
                      ) : (
                        index + 1
                      )}
                    </Badge>

                    <div className="flex min-w-0 flex-col gap-1">
                      <Link
                        className="text-sm font-medium text-foreground transition-colors hover:text-muted-foreground"
                        href={step.href}
                        onClick={() => setOpen(false)}
                      >
                        {step.label}
                      </Link>
                      <p className="text-sm text-muted-foreground">
                        {step.detail}
                      </p>
                      <span className="text-xs text-muted-foreground">
                        {isCurrent
                          ? "Current stop"
                          : isVisited
                            ? "Visited"
                            : "Ready"}
                      </span>
                    </div>
                  </div>
                  {index < demoSteps.length - 1 ? <Separator /> : null}
                </li>
              );
            })}
          </ol>
        </div>

        <Separator />

        <SheetFooter>
          <div className="flex flex-col gap-1" role="status">
            <strong className="text-sm font-medium">
              {visited.length === demoSteps.length
                ? "Product tour complete"
                : `${visited.length} of ${demoSteps.length} pages visited`}
            </strong>
            <span className="text-xs text-muted-foreground">
              {nextStep
                ? `Next: ${nextStep.label}`
                : "Ready to reset and replay."}
            </span>
          </div>
          <Button variant="outline" onClick={resetGuide}>
            <RotateCcwIcon data-icon="inline-start" />
            Reset tour
          </Button>
        </SheetFooter>

        <p className="sr-only" aria-live="polite">
          {announcement}
        </p>
      </SheetContent>
    </Sheet>
  );
}
