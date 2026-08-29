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
import { Separator } from "@/components/shadcn/separator";

const demoStops = [
  "See the ₹1,499 FitBox failure",
  "Inspect diagnosis and policy evidence",
  "Approve one mock-only recovery surface",
  "Close with deterministic RecoveryBench results",
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
            <Badge variant="secondary">Mock-first revenue recovery</Badge>
            <div className="flex flex-col gap-3">
              <h1 className="max-w-xl text-4xl leading-tight font-semibold tracking-tight text-balance md:text-5xl">
                From failed invoice to an auditable next action.
              </h1>
              <p className="max-w-xl text-base leading-7 text-muted-foreground md:text-lg">
                RecoveryOS explains subscription failures, applies deterministic
                safety policy, and keeps a human in control of every
                consequential recovery action.
              </p>
            </div>
            <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row">
              <Button
                size="lg"
                render={<Link href="/login" />}
                nativeButton={false}
              >
                Open the FitBox demo
                <ArrowRightIcon data-icon="inline-end" />
              </Button>
              <Button
                size="lg"
                variant="outline"
                render={<Link href="/dashboard" />}
                nativeButton={false}
              >
                View seeded Control Tower
              </Button>
            </div>
            <p className="flex items-start gap-2 text-sm text-muted-foreground">
              <CheckCircle2Icon className="mt-0.5 size-4 shrink-0" />
              <span>
                Demo access is prefilled. Real payment and calling controls
                remain server-side gated.
              </span>
            </p>
          </div>

          <Card>
            <CardHeader>
              <CardTitle>FitBox Annual</CardTitle>
              <CardDescription>Seeded judge scenario</CardDescription>
              <CardAction>
                <Badge variant="outline">5:00 route</Badge>
              </CardAction>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              <div className="flex items-end justify-between gap-4">
                <div className="flex flex-col gap-1">
                  <span className="text-xs text-muted-foreground">
                    Revenue at risk
                  </span>
                  <strong className="text-3xl font-semibold tracking-tight">
                    ₹1,499
                  </strong>
                </div>
                <Badge variant="secondary">Authentication required</Badge>
              </div>
              <Separator />
              <ol className="flex flex-col gap-3" aria-label="FitBox demo path">
                {demoStops.map((stop, index) => (
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
              <Badge variant="outline">Simulated</Badge>
              <span className="text-xs text-muted-foreground">
                Default evidence · no external action
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
