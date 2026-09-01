import {
  ArrowRightIcon,
  CheckCircle2Icon,
  ReceiptTextIcon,
  ScanSearchIcon,
  ShieldCheckIcon,
} from "lucide-react";
import Link from "next/link";

import { Brand } from "@/components/layout";
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

const recoveryFlow = [
  "Receive and verify a failed-payment webhook",
  "Rank executable actions with the recovery model",
  "Apply deterministic consent and payment safety gates",
  "Execute through Temporal and reconcile provider proof",
];

const safeguards = [
  {
    title: "Invoice scoped",
    description: "No detached payment recovery",
    icon: ReceiptTextIcon,
  },
  {
    title: "Policy first",
    description: "Opt-out and dispute precedence",
    icon: ShieldCheckIcon,
  },
  {
    title: "Evidence labelled",
    description: "Simulation never counts as verified revenue",
    icon: ScanSearchIcon,
  },
];

export default function HomePage() {
  return (
    <main className="min-h-svh bg-background text-foreground">
      <nav
        className="mx-auto flex w-full max-w-6xl items-center justify-between gap-4 px-5 py-5 md:px-8"
        aria-label="Public navigation"
      >
        <Link href="/" aria-label="RecoveryOS home">
          <Brand />
        </Link>
        <div className="flex items-center gap-3">
          <Badge variant="outline">Razorpay test mode</Badge>
          <span className="hidden text-xs text-muted-foreground sm:inline">
            Independent hackathon demo
          </span>
        </div>
      </nav>

      <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-5 pb-8 md:px-8 md:pb-12">
        <section className="grid items-center gap-6 py-6 lg:grid-cols-[minmax(0,1fr)_25rem] lg:py-12">
          <div className="flex max-w-2xl flex-col items-start gap-5">
            <Badge variant="secondary">Provider-connected revenue recovery</Badge>
            <div className="flex flex-col gap-3">
              <h1 className="max-w-xl text-4xl leading-tight font-semibold tracking-tight text-balance md:text-5xl">
                From failed invoice to an auditable next action.
              </h1>
              <p className="max-w-xl text-base leading-7 text-muted-foreground md:text-lg">
                RecoveryOS explains subscription failures, ranks the next best
                action with a trained recovery model, and keeps deterministic
                safety rules around every consequential provider action.
              </p>
            </div>
            <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row">
              <Button
                size="lg"
                render={<Link href="/login" />}
                nativeButton={false}
              >
                Open RecoveryOS
                <ArrowRightIcon data-icon="inline-end" />
              </Button>
              <Button
                size="lg"
                variant="outline"
                render={<Link href="/dashboard" />}
                nativeButton={false}
              >
                View Control Tower
              </Button>
            </div>
            <p className="flex items-start gap-2 text-sm text-muted-foreground">
              <CheckCircle2Icon className="mt-0.5 size-4 shrink-0" />
              <span>
                Razorpay stays in test mode. Payment, A2A, and calling controls
                remain independently server-side gated.
              </span>
            </p>
          </div>

          <Card>
            <CardHeader>
              <CardTitle>One auditable recovery loop</CardTitle>
              <CardDescription>From webhook to verified outcome</CardDescription>
              <CardAction>
                <Badge variant="outline">Live workflow</Badge>
              </CardAction>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              <ol className="flex flex-col gap-3" aria-label="Recovery workflow">
                {recoveryFlow.map((stop, index) => (
                  <li className="flex items-center gap-3" key={stop}>
                    <Badge variant="secondary">
                      {String(index + 1).padStart(2, "0")}
                    </Badge>
                    <span className="text-sm">{stop}</span>
                  </li>
                ))}
              </ol>
            </CardContent>
            <CardFooter className="justify-between gap-3">
              <Badge variant="outline">Razorpay test mode</Badge>
              <span className="text-xs text-muted-foreground">
                Provider proof remains authoritative
              </span>
            </CardFooter>
          </Card>
        </section>

        <Card size="sm">
          <CardHeader>
            <CardTitle>Built-in safeguards</CardTitle>
            <CardDescription>
              Recovery decisions stay constrained and inspectable.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4 md:grid-cols-3">
            {safeguards.map(({ title, description, icon: Icon }) => (
              <div className="flex items-start gap-3" key={title}>
                <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
                  <Icon className="size-4" aria-hidden="true" />
                </div>
                <div className="flex flex-col gap-1">
                  <strong className="text-sm font-medium">{title}</strong>
                  <span className="text-xs leading-5 text-muted-foreground">
                    {description}
                  </span>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>

        <footer className="flex flex-col justify-between gap-2 py-2 text-xs text-muted-foreground sm:flex-row">
          <span>RecoveryOS</span>
          <span>No Razorpay affiliation or endorsement implied.</span>
        </footer>
      </div>
    </main>
  );
}
