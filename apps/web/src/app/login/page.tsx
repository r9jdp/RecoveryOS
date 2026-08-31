"use client";

import { CircleAlertIcon, ShieldCheckIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Brand } from "@/components/layout";
import { Alert, AlertDescription, AlertTitle } from "@/components/shadcn/alert";
import { Badge } from "@/components/shadcn/badge";
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
  "Invoice-scoped recovery",
  "Policy-first decisions",
  "Complete audit trail",
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
      <div className="mx-auto flex min-h-svh w-full max-w-5xl flex-col px-5 py-5 md:px-8">
        <header className="flex items-center justify-between gap-4">
          <Link href="/" aria-label="RecoveryOS home">
            <Brand />
          </Link>
          <Badge variant="outline">Razorpay test mode</Badge>
        </header>

        <section className="grid flex-1 items-center gap-8 py-8 lg:grid-cols-[minmax(0,1fr)_24rem] lg:gap-14">
          <div className="flex max-w-xl flex-col items-start gap-5">
            <Badge variant="secondary">Auditable revenue recovery</Badge>
            <div className="flex flex-col gap-3">
              <h1
                id="login-hero-title"
                className="text-4xl leading-tight font-semibold tracking-tight text-balance md:text-5xl"
              >
                Recover the payment. Preserve the trust.
              </h1>
              <p className="max-w-lg text-base leading-7 text-muted-foreground">
                Understand every failed subscription, choose the safest recovery
                path, and keep humans in control of consequential actions.
              </p>
            </div>
            <div
              className="flex flex-wrap gap-2"
              aria-label="Product safeguards"
            >
              {safeguards.map((safeguard) => (
                <Badge key={safeguard} variant="outline">
                  {safeguard}
                </Badge>
              ))}
            </div>
            <p className="text-xs text-muted-foreground">
              Independent hackathon demo · not affiliated with Razorpay.
            </p>
          </div>

          <Card aria-labelledby="login-heading">
            <CardHeader>
              <CardTitle id="login-heading">
                Sign in to RecoveryOS
              </CardTitle>
              <CardDescription>
                Use the server-configured operator account. Consequential
                actions require this signed session and a matching CSRF token.
              </CardDescription>
              <CardAction>
                <Badge variant="secondary">{demoMode ? "Demo" : "Operator"}</Badge>
              </CardAction>
            </CardHeader>
            <CardContent>
              <form className="flex flex-col gap-4" onSubmit={submit}>
                <FieldGroup className="gap-4">
                  <Field>
                    <FieldLabel htmlFor="operator-email">Work email</FieldLabel>
                    <Input
                      id="operator-email"
                      name="email"
                      type="email"
                      autoComplete="email"
                      defaultValue={demoMode ? "demo@recoveryos.dev" : undefined}
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
                  <AlertTitle>Server-side safeguards remain active</AlertTitle>
                  <AlertDescription>
                    The API issues an HttpOnly operator session. Real payment
                    and calling controls remain independently server-side gated.
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
        </section>
      </div>
    </main>
  );
}
