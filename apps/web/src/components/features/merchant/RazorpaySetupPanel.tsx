"use client";

import Link from "next/link";
import { useState } from "react";
import type { FormEvent } from "react";
import {
  CheckCircle2,
  CircleAlert,
  ExternalLink,
  RefreshCw,
} from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/shadcn/alert";
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
import {
  Field,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
  FieldSet,
} from "@/components/shadcn/field";
import { Input } from "@/components/shadcn/input";
import { Spinner } from "@/components/shadcn/spinner";
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/shadcn/table";
import {
  syncRazorpayTestSubscription,
  type RazorpaySubscriptionSyncInput,
  type RazorpaySubscriptionSyncResult,
} from "@/lib/api/razorpay-onboarding-client";
import { formatPaise, humanize } from "@/lib/recovery-format";

const emptyInput: RazorpaySubscriptionSyncInput = {
  subscription_id: "",
  customer_external_id: "",
  customer_display_name: "",
  preferred_language: "en-IN",
};

type SyncSubscription = (
  input: RazorpaySubscriptionSyncInput,
) => Promise<RazorpaySubscriptionSyncResult>;

function ProviderLink({ href, label }: { href: string | null; label: string }) {
  if (!href)
    return <Badge variant="outline">Not available from Razorpay</Badge>;
  return (
    <Button
      size="sm"
      variant="outline"
      render={<a href={href} target="_blank" rel="noreferrer" />}
      nativeButton={false}
    >
      {label}
      <ExternalLink data-icon="inline-end" />
    </Button>
  );
}

export function RazorpaySetupPanel({
  syncSubscription = syncRazorpayTestSubscription,
}: {
  syncSubscription?: SyncSubscription;
}) {
  const [input, setInput] = useState(emptyInput);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<RazorpaySubscriptionSyncResult | null>(
    null,
  );
  const subscriptionInvalid =
    input.subscription_id.length > 0 &&
    !/^sub_[A-Za-z0-9_-]+$/.test(input.subscription_id);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setResult(null);
    if (
      subscriptionInvalid ||
      !input.subscription_id.trim() ||
      !input.customer_external_id.trim() ||
      !input.customer_display_name.trim()
    ) {
      setError("Enter the Razorpay subscription and customer identity fields.");
      return;
    }
    setBusy(true);
    try {
      setResult(
        await syncSubscription({
          ...input,
          subscription_id: input.subscription_id.trim(),
          customer_external_id: input.customer_external_id.trim(),
          customer_display_name: input.customer_display_name.trim(),
          preferred_language: input.preferred_language.trim() || "en-IN",
        }),
      );
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "The Razorpay subscription could not be imported.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-5">
      <header className="flex flex-col gap-2 border-b border-border pb-5">
        <p className="font-mono text-xs font-medium tracking-[0.1em] text-info uppercase">
          Provider setup
        </p>
        <h1 className="font-heading text-3xl font-normal tracking-[-0.025em] sm:text-4xl">
          Connect a Razorpay Test subscription
        </h1>
        <p className="max-w-3xl text-base leading-6 text-muted-foreground">
          Import the real plan, subscription, and invoice identifiers that
          RecoveryOS will correlate with signed Razorpay webhooks.
        </p>
      </header>

      <Alert variant="info">
        <CircleAlert />
        <AlertTitle>This does not create or charge a payment</AlertTitle>
        <AlertDescription>
          Create the test plan and subscription in Razorpay first, then paste
          its <code>sub_...</code> ID here. RecoveryOS only reads and stores the
          provider-owned state.
        </AlertDescription>
      </Alert>

      <Card>
        <CardHeader>
          <CardTitle>Subscription identity</CardTitle>
          <CardDescription>
            Add the customer reference used by your product so the real Razorpay
            subscription can be correlated with RecoveryOS records.
          </CardDescription>
          <CardAction>
            <Badge variant="info">Razorpay Test</Badge>
          </CardAction>
        </CardHeader>
        <form onSubmit={submit}>
          <CardContent>
            <FieldSet disabled={busy}>
              <FieldGroup>
                <Field data-invalid={subscriptionInvalid || undefined}>
                  <FieldLabel htmlFor="razorpay-subscription-id">
                    Razorpay subscription ID
                  </FieldLabel>
                  <Input
                    id="razorpay-subscription-id"
                    value={input.subscription_id}
                    onChange={(event) =>
                      setInput((current) => ({
                        ...current,
                        subscription_id: event.target.value,
                      }))
                    }
                    placeholder="sub_..."
                    autoComplete="off"
                    aria-invalid={subscriptionInvalid || undefined}
                    required
                  />
                  <FieldDescription>
                    Found in Razorpay Dashboard → Subscriptions or returned by
                    the Subscriptions API.
                  </FieldDescription>
                  {subscriptionInvalid ? (
                    <FieldError>
                      Use a valid Razorpay <code>sub_...</code> ID.
                    </FieldError>
                  ) : null}
                </Field>

                <div className="grid gap-5 md:grid-cols-2">
                  <Field>
                    <FieldLabel htmlFor="customer-external-id">
                      Your customer reference
                    </FieldLabel>
                    <Input
                      id="customer-external-id"
                      value={input.customer_external_id}
                      onChange={(event) =>
                        setInput((current) => ({
                          ...current,
                          customer_external_id: event.target.value,
                        }))
                      }
                      placeholder="customer-42"
                      autoComplete="off"
                      required
                    />
                    <FieldDescription>
                      A stable ID from your own product or CRM.
                    </FieldDescription>
                  </Field>

                  <Field>
                    <FieldLabel htmlFor="customer-display-name">
                      Customer display name
                    </FieldLabel>
                    <Input
                      id="customer-display-name"
                      value={input.customer_display_name}
                      onChange={(event) =>
                        setInput((current) => ({
                          ...current,
                          customer_display_name: event.target.value,
                        }))
                      }
                      placeholder="Name shown to operators"
                      autoComplete="off"
                      required
                    />
                  </Field>
                </div>

                <Field>
                  <FieldLabel htmlFor="preferred-language">
                    Preferred language
                  </FieldLabel>
                  <Input
                    id="preferred-language"
                    value={input.preferred_language}
                    onChange={(event) =>
                      setInput((current) => ({
                        ...current,
                        preferred_language: event.target.value,
                      }))
                    }
                    placeholder="en-IN"
                    autoComplete="off"
                    required
                  />
                </Field>
              </FieldGroup>
            </FieldSet>

            {error ? (
              <Alert variant="destructive" className="mt-5">
                <CircleAlert />
                <AlertTitle>Subscription was not connected</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            ) : null}
          </CardContent>
          <CardFooter className="justify-end">
            <Button type="submit" disabled={busy || subscriptionInvalid}>
              {busy ? (
                <Spinner data-icon="inline-start" />
              ) : (
                <RefreshCw data-icon="inline-start" />
              )}
              {busy ? "Reading Razorpay…" : "Connect subscription"}
            </Button>
          </CardFooter>
        </form>
      </Card>

      {result ? (
        <section
          className="flex flex-col gap-4"
          aria-labelledby="razorpay-sync-result"
        >
          <Alert variant="success">
            <CheckCircle2 />
            <AlertTitle id="razorpay-sync-result">
              Razorpay subscription connected
            </AlertTitle>
            <AlertDescription>
              RecoveryOS persisted the provider identifiers returned by the
              hosted API. Plan, subscription, and customer records are ready for
              recovery operations.
            </AlertDescription>
          </Alert>

          <div className="grid items-stretch gap-px border border-border bg-border lg:grid-cols-3">
            <Card className="border-0" size="sm">
              <CardHeader>
                <CardTitle>Plan</CardTitle>
                <CardDescription>
                  Provider-owned plan details read from Razorpay.
                </CardDescription>
                <CardAction>
                  <Badge variant="info">Test mode</Badge>
                </CardAction>
              </CardHeader>
              <CardContent>
                <dl className="flex flex-col gap-3">
                  <div className="flex flex-col gap-1">
                    <dt className="font-mono text-xs tracking-[0.06em] text-muted-foreground uppercase">
                      Name
                    </dt>
                    <dd className="font-medium">
                      {result.subscription.plan_name}
                    </dd>
                  </div>
                  <div className="flex flex-col gap-1">
                    <dt className="font-mono text-xs tracking-[0.06em] text-muted-foreground uppercase">
                      Razorpay plan ID
                    </dt>
                    <dd className="break-all font-mono text-sm">
                      {result.subscription.provider_plan_id}
                    </dd>
                  </div>
                  <div className="flex flex-col gap-1">
                    <dt className="font-mono text-xs tracking-[0.06em] text-muted-foreground uppercase">
                      Amount
                    </dt>
                    <dd className="font-medium tabular-nums">
                      {formatPaise(result.subscription.amount_paise)} ·{" "}
                      {result.subscription.currency}
                    </dd>
                  </div>
                </dl>
              </CardContent>
            </Card>

            <Card className="border-0" size="sm">
              <CardHeader>
                <CardTitle>Subscription</CardTitle>
                <CardDescription>
                  The exact subscription RecoveryOS will correlate.
                </CardDescription>
                <CardAction>
                  <Badge variant="warning">
                    {humanize(result.subscription.subscription_state)}
                  </Badge>
                </CardAction>
              </CardHeader>
              <CardContent>
                <dl className="flex flex-col gap-3">
                  <div className="flex flex-col gap-1">
                    <dt className="font-mono text-xs tracking-[0.06em] text-muted-foreground uppercase">
                      Razorpay subscription ID
                    </dt>
                    <dd className="break-all font-mono text-sm">
                      {result.subscription.provider_subscription_id}
                    </dd>
                  </div>
                  <div className="flex flex-col gap-1">
                    <dt className="font-mono text-xs tracking-[0.06em] text-muted-foreground uppercase">
                      RecoveryOS record ID
                    </dt>
                    <dd className="break-all font-mono text-sm">
                      {result.subscription.id}
                    </dd>
                  </div>
                </dl>
              </CardContent>
              <CardFooter>
                <ProviderLink
                  href={result.subscription.authorization_url}
                  label="Open authorization link"
                />
              </CardFooter>
            </Card>

            <Card className="border-0" size="sm">
              <CardHeader>
                <CardTitle>Local correlation</CardTitle>
                <CardDescription>
                  Database records linked to signed webhook events.
                </CardDescription>
                <CardAction>
                  <Badge
                    variant={result.customer.created ? "success" : "secondary"}
                  >
                    {result.customer.created ? "Created" : "Updated"}
                  </Badge>
                </CardAction>
              </CardHeader>
              <CardContent>
                <dl className="flex flex-col gap-3">
                  <div className="flex flex-col gap-1">
                    <dt className="font-mono text-xs tracking-[0.06em] text-muted-foreground uppercase">
                      Merchant ID
                    </dt>
                    <dd className="break-all font-mono text-sm">
                      {result.merchant_id}
                    </dd>
                  </div>
                  <div className="flex flex-col gap-1">
                    <dt className="font-mono text-xs tracking-[0.06em] text-muted-foreground uppercase">
                      Customer reference
                    </dt>
                    <dd className="break-all font-mono text-sm">
                      {result.customer.external_id}
                    </dd>
                  </div>
                  <div className="flex flex-col gap-1">
                    <dt className="font-mono text-xs tracking-[0.06em] text-muted-foreground uppercase">
                      Customer record ID
                    </dt>
                    <dd className="break-all font-mono text-sm">
                      {result.customer.id}
                    </dd>
                  </div>
                </dl>
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle>Invoices returned by Razorpay</CardTitle>
              <CardDescription>
                Amounts, statuses, and payment URLs come from the hosted API
                response for this subscription.
              </CardDescription>
              <CardAction>
                <Badge variant="secondary">
                  {result.invoices.length} invoices
                </Badge>
              </CardAction>
            </CardHeader>
            <CardContent className="px-0">
              {result.invoices.length > 0 ? (
                <Table>
                  <TableCaption className="sr-only">
                    Razorpay Test invoices synced for the selected subscription.
                  </TableCaption>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="pl-(--card-spacing)">
                        Invoice
                      </TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Amount</TableHead>
                      <TableHead>Paid</TableHead>
                      <TableHead className="pr-(--card-spacing) text-right">
                        Razorpay payment URL
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {result.invoices.map((invoice) => (
                      <TableRow key={invoice.provider_invoice_id}>
                        <TableCell className="pl-(--card-spacing)">
                          <p className="font-mono text-sm">
                            {invoice.provider_invoice_id}
                          </p>
                          <p className="mt-1 font-mono text-xs text-muted-foreground">
                            {invoice.billing_cycle_key}
                          </p>
                        </TableCell>
                        <TableCell>
                          <Badge variant="outline">
                            {humanize(invoice.invoice_state)}
                          </Badge>
                        </TableCell>
                        <TableCell className="font-medium tabular-nums">
                          {formatPaise(invoice.amount_paise)}
                        </TableCell>
                        <TableCell className="tabular-nums text-muted-foreground">
                          {formatPaise(invoice.amount_paid_paise)}
                        </TableCell>
                        <TableCell className="pr-(--card-spacing) text-right">
                          <ProviderLink
                            href={invoice.payment_url}
                            label="Open invoice"
                          />
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              ) : (
                <Alert variant="info" className="mx-(--card-spacing)">
                  <CircleAlert />
                  <AlertTitle>No invoices returned</AlertTitle>
                  <AlertDescription>
                    Razorpay did not return an invoice for this subscription.
                    RecoveryOS did not invent one.
                  </AlertDescription>
                </Alert>
              )}
            </CardContent>
            <CardFooter className="flex-col items-start gap-3 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-sm leading-5 text-muted-foreground">
                This setup never creates a standalone Payment Link. That action
                remains limited to an approved halted-subscription recovery.
              </p>
              <Button
                variant="outline"
                render={<Link href="/dashboard" />}
                nativeButton={false}
              >
                Open Control Tower
              </Button>
            </CardFooter>
          </Card>
        </section>
      ) : null}
    </div>
  );
}
