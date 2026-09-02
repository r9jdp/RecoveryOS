"use client";

import { CircleAlertIcon, ShieldCheckIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Brand } from "@/components/layout";
import { Alert, AlertDescription, AlertTitle } from "@/components/shadcn/alert";
import { Button } from "@/components/shadcn/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/shadcn/card";
import { Field, FieldGroup, FieldLabel } from "@/components/shadcn/field";
import { Input } from "@/components/shadcn/input";
import { Spinner } from "@/components/shadcn/spinner";
import { createOperatorSession } from "@/lib/operator-session";
import { demoDataEnabled } from "@/lib/runtime-config";

const safeguards = [
  {
    label: "Invoice scoped",
    detail: "One failed invoice anchors every recovery decision.",
  },
  {
    label: "Policy first",
    detail: "Consent and operator controls remain authoritative.",
  },
  {
    label: "Evidence preserved",
    detail: "Provider proof closes the loop—not a browser callback.",
  },
];

export default function LoginPage() {
  const router = useRouter();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const demoMode = demoDataEnabled();

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
    <main className="min-h-svh bg-background text-foreground">
      <div className="mx-auto flex min-h-svh w-full max-w-[96rem] flex-col border-x border-border">
        <header className="flex h-16 items-center justify-between gap-4 border-b border-border px-5 md:px-8">
          <Link
            className="font-medium no-underline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-ring"
            href="/"
            aria-label="RecoveryOS home"
          >
            <Brand variant="ledger" />
          </Link>
          <span className="flex items-center gap-2 font-mono text-[0.6875rem] tracking-[0.08em] text-foreground uppercase">
            <span
              className="size-2 border-2 border-primary"
              aria-hidden="true"
            />
            Razorpay test mode
          </span>
        </header>

        <section className="grid flex-1 lg:grid-cols-[minmax(0,1.15fr)_minmax(24rem,0.85fr)]">
          <div className="flex min-w-0 flex-col border-b border-border lg:border-r lg:border-b-0">
            <div className="flex flex-1 flex-col items-start justify-center gap-6 px-5 py-12 md:px-10 lg:px-14 lg:py-16">
              <p className="m-0 font-mono text-[0.6875rem] tracking-[0.12em] text-primary uppercase">
                Operator access / audit ledger
              </p>
              <h1
                id="login-hero-title"
                className="max-w-3xl font-heading text-5xl leading-[0.98] font-normal tracking-[-0.045em] text-balance md:text-6xl xl:text-7xl"
              >
                <span className="block">Recover the payment.</span>
                <em className="block font-normal">Preserve the trust.</em>
              </h1>
              <p className="max-w-2xl text-base leading-7 text-muted-foreground md:text-lg md:leading-8">
                Understand every failed subscription, choose the safest recovery
                path, and keep humans in control of consequential actions.
              </p>
              <p className="m-0 font-mono text-[0.6875rem] tracking-[0.08em] text-muted-foreground uppercase">
                Provider evidence · operator-controlled actions
              </p>
            </div>

            <ol
              className="m-0 grid list-none border-t border-border p-0 sm:grid-cols-3"
              aria-label="Product safeguards"
            >
              {safeguards.map((safeguard, index) => (
                <li
                  className="grid gap-2 border-b border-border p-5 last:border-b-0 sm:border-r sm:border-b-0 sm:last:border-r-0"
                  key={safeguard.label}
                >
                  <span className="font-mono text-xs tracking-[0.08em] text-primary">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <strong className="font-heading text-xl font-normal">
                    {safeguard.label}
                  </strong>
                  <span className="text-sm leading-6 text-muted-foreground">
                    {safeguard.detail}
                  </span>
                </li>
              ))}
            </ol>
          </div>

          <div className="flex min-w-0 items-center bg-muted/20 px-5 py-10 md:px-10 lg:px-12">
            <div className="mx-auto grid w-full max-w-md gap-5">
              <p className="m-0 font-mono text-[0.6875rem] tracking-[0.1em] text-primary uppercase">
                Identity checkpoint / 01
              </p>
              <Card className="w-full" aria-labelledby="login-heading">
                <CardHeader>
                  <CardTitle
                    className="font-heading text-2xl font-normal"
                    id="login-heading"
                  >
                    Sign in to RecoveryOS
                  </CardTitle>
                  <CardDescription>
                    Use the server-configured operator account. Consequential
                    actions require this signed session and a matching CSRF
                    token.
                  </CardDescription>
                  <CardAction>
                    <span className="font-mono text-[0.6875rem] tracking-[0.08em] text-muted-foreground uppercase">
                      Operator access
                    </span>
                  </CardAction>
                </CardHeader>
                <CardContent>
                  <form className="flex flex-col gap-4" onSubmit={submit}>
                    <FieldGroup className="gap-4">
                      <Field>
                        <FieldLabel htmlFor="operator-email">
                          Work email
                        </FieldLabel>
                        <Input
                          id="operator-email"
                          name="email"
                          type="email"
                          autoComplete="email"
                          defaultValue={
                            demoMode ? "demo@recoveryos.dev" : undefined
                          }
                          required
                        />
                      </Field>
                      <Field>
                        <FieldLabel htmlFor="operator-password">
                          Access code
                        </FieldLabel>
                        <Input
                          id="operator-password"
                          name="password"
                          type="password"
                          autoComplete="current-password"
                          defaultValue={demoMode ? "recovery-demo" : undefined}
                          required
                        />
                      </Field>
                    </FieldGroup>

                    <Alert>
                      <ShieldCheckIcon aria-hidden="true" />
                      <AlertTitle>
                        Server-side safeguards remain active
                      </AlertTitle>
                      <AlertDescription>
                        The API issues an HttpOnly operator session. Payment and
                        calling controls remain independently server-gated and
                        require explicit deployment authorization.
                      </AlertDescription>
                    </Alert>

                    {error && (
                      <Alert variant="destructive">
                        <CircleAlertIcon aria-hidden="true" />
                        <AlertTitle>Sign-in failed</AlertTitle>
                        <AlertDescription>{error}</AlertDescription>
                      </Alert>
                    )}

                    <Button
                      className="w-full"
                      size="lg"
                      type="submit"
                      disabled={submitting}
                    >
                      {submitting && <Spinner data-icon="inline-start" />}
                      {submitting
                        ? "Opening Control Tower…"
                        : "Enter Control Tower"}
                    </Button>
                  </form>
                </CardContent>
              </Card>
              <p className="m-0 text-center font-mono text-[0.6875rem] leading-5 tracking-[0.04em] text-muted-foreground uppercase">
                Independent RecoveryOS project · not affiliated with Razorpay
              </p>
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}
