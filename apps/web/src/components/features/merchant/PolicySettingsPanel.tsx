"use client";

import { useEffect, useState } from "react";
import {
  CircleAlert,
  CircleCheck,
  Info,
  Pause,
  Play,
  Save,
  ShieldAlert,
  ShieldCheck,
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
import { Checkbox } from "@/components/shadcn/checkbox";
import {
  Field,
  FieldContent,
  FieldDescription,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from "@/components/shadcn/field";
import { Input } from "@/components/shadcn/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/shadcn/select";
import { Spinner } from "@/components/shadcn/spinner";
import {
  getPolicySettings,
  updatePolicySettings,
} from "@/lib/api/recovery-client";
import { merchantDashboard } from "@/lib/merchant-demo";
import { formatPaise, humanize } from "@/lib/recovery-format";
import type { PolicySettings, RecoveryAction } from "@/types/recovery";

import { ConfirmDialog } from "./ConfirmDialog";

const approvalActions: Array<{ action: RecoveryAction; label: string }> = [
  {
    action: "OPEN_CUSTOMER_PAYMENT_SURFACE",
    label: "Open a customer payment surface",
  },
  { action: "START_VOICE", label: "Start voice outreach" },
  {
    action: "SEND_TO_CUSTOMER_AGENT",
    label: "Send to the customer agent",
  },
];

const timezoneItems = [{ label: "Asia/Kolkata", value: "Asia/Kolkata" }];

export function PolicySettingsPanel({
  saveSettings = updatePolicySettings,
}: {
  saveSettings?: (settings: PolicySettings) => Promise<PolicySettings>;
}) {
  const [settings, setSettings] = useState<PolicySettings>(
    merchantDashboard.policy_settings,
  );
  const [killConfirm, setKillConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [readWarning, setReadWarning] = useState<string | null>(null);
  const [source, setSource] = useState<"api" | "mock">("mock");

  useEffect(() => {
    const controller = new AbortController();
    getPolicySettings(controller.signal)
      .then((result) => {
        setSettings(result.data);
        setSource(result.source);
        setReadWarning(result.warning ?? null);
      })
      .catch((caught: unknown) => {
        if (caught instanceof DOMException && caught.name === "AbortError")
          return;
        setReadWarning("Policy settings could not be refreshed.");
      });
    return () => controller.abort();
  }, []);

  async function persist(next: PolicySettings, message: string) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const saved = await saveSettings(next);
      setSettings(saved);
      setSource(process.env.NEXT_PUBLIC_API_BASE_URL?.trim() ? "api" : "mock");
      setReadWarning(null);
      setNotice(message);
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "Settings could not be saved.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-5">
      <header className="flex flex-col gap-4 border-b border-border pb-5 sm:flex-row sm:items-end sm:justify-between">
        <div className="flex flex-col gap-2">
          <p className="text-sm font-medium tracking-wide text-info uppercase">
            Platform safety
          </p>
          <h1 className="font-heading text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">
            Recovery policy
          </h1>
          <p className="max-w-2xl text-base leading-6 text-muted-foreground">
            Configure operator approval, contact limits, quiet hours, and the
            global recovery kill switch.
          </p>
        </div>
        <Badge
          variant={settings.recovery_kill_switch ? "destructive" : "success"}
        >
          {settings.recovery_kill_switch ? (
            <ShieldAlert data-icon="inline-start" />
          ) : (
            <ShieldCheck data-icon="inline-start" />
          )}
          {settings.recovery_kill_switch
            ? "Recovery paused"
            : "Recovery active"}
        </Badge>
      </header>

      <div className="flex flex-col gap-2" aria-live="polite">
        {notice && (
          <Alert variant="success">
            <CircleCheck />
            <AlertTitle>Policy updated</AlertTitle>
            <AlertDescription>{notice}</AlertDescription>
          </Alert>
        )}
        {readWarning && (
          <Alert variant="warning">
            <Info />
            <AlertTitle>Fallback policy data</AlertTitle>
            <AlertDescription>{readWarning}</AlertDescription>
          </Alert>
        )}
        {error && (
          <Alert variant="destructive">
            <CircleAlert />
            <AlertTitle>Policy update failed</AlertTitle>
            <AlertDescription>
              {error} Existing settings remain active.
            </AlertDescription>
          </Alert>
        )}
        {settings.recovery_kill_switch && (
          <Alert variant="destructive">
            <ShieldAlert />
            <AlertTitle>Global kill switch is on</AlertTitle>
            <AlertDescription>
              New provider actions are blocked. Existing cases remain visible
              and payment reconciliation continues.
            </AlertDescription>
          </Alert>
        )}
      </div>

      <h2 className="sr-only">Policy controls</h2>
      <div className="grid items-start gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader className="border-b border-border">
            <CardTitle>Contact window and limits</CardTitle>
            <CardDescription>
              Set when RecoveryOS may contact a customer and how often.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-6">
            <FieldGroup className="grid gap-5 md:grid-cols-2">
              <Field>
                <FieldLabel htmlFor="policy-timezone">
                  Merchant timezone
                </FieldLabel>
                <Select
                  items={timezoneItems}
                  value={settings.timezone}
                  onValueChange={(value) => {
                    if (!value) return;
                    setSettings((current) => ({
                      ...current,
                      timezone: value,
                    }));
                  }}
                >
                  <SelectTrigger id="policy-timezone" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectGroup>
                      {timezoneItems.map((item) => (
                        <SelectItem key={item.value} value={item.value}>
                          {item.label}
                        </SelectItem>
                      ))}
                    </SelectGroup>
                  </SelectContent>
                </Select>
              </Field>

              <Field>
                <FieldLabel htmlFor="max-contacts">
                  Maximum contacts in 7 days
                </FieldLabel>
                <Input
                  id="max-contacts"
                  type="number"
                  min={1}
                  max={7}
                  value={settings.max_contacts_per_7_days ?? ""}
                  onChange={(event) =>
                    setSettings((current) => ({
                      ...current,
                      max_contacts_per_7_days:
                        event.target.value === ""
                          ? null
                          : Number(event.target.value),
                    }))
                  }
                />
                <FieldDescription>
                  Leave empty to disable the rolling contact cap.
                </FieldDescription>
              </Field>
            </FieldGroup>

            <FieldSet>
              <FieldLegend>Quiet hours</FieldLegend>
              <FieldDescription>
                Block customer outreach during this local time window.
              </FieldDescription>
              <FieldGroup className="grid gap-5 sm:grid-cols-2">
                <Field>
                  <FieldLabel htmlFor="quiet-hours-start">
                    Quiet hours begin
                  </FieldLabel>
                  <Input
                    id="quiet-hours-start"
                    type="time"
                    value={settings.quiet_hours_start ?? ""}
                    onChange={(event) =>
                      setSettings((current) => ({
                        ...current,
                        quiet_hours_start: event.target.value || null,
                        quiet_hours_end: event.target.value
                          ? (current.quiet_hours_end ?? "09:00")
                          : null,
                      }))
                    }
                  />
                </Field>
                <Field>
                  <FieldLabel htmlFor="quiet-hours-end">
                    Quiet hours end
                  </FieldLabel>
                  <Input
                    id="quiet-hours-end"
                    type="time"
                    value={settings.quiet_hours_end ?? ""}
                    onChange={(event) =>
                      setSettings((current) => ({
                        ...current,
                        quiet_hours_start: event.target.value
                          ? (current.quiet_hours_start ?? "20:00")
                          : null,
                        quiet_hours_end: event.target.value || null,
                      }))
                    }
                  />
                </Field>
              </FieldGroup>
            </FieldSet>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="border-b border-border">
            <CardTitle>Approval rules</CardTitle>
            <CardDescription>
              Decide which recovery actions need a human decision before they
              run.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor="approval-threshold">
                  Require approval above (paise)
                </FieldLabel>
                <Input
                  id="approval-threshold"
                  type="number"
                  min={0}
                  step={100}
                  value={settings.require_approval_above_paise ?? ""}
                  onChange={(event) =>
                    setSettings((current) => ({
                      ...current,
                      require_approval_above_paise:
                        event.target.value === ""
                          ? null
                          : Number(event.target.value),
                    }))
                  }
                />
                <FieldDescription>
                  {settings.require_approval_above_paise === null
                    ? "Amount-based approval is disabled."
                    : `Currently ${formatPaise(settings.require_approval_above_paise)}`}
                </FieldDescription>
              </Field>

              <FieldSet>
                <FieldLegend>Always require approval for</FieldLegend>
                <FieldDescription>
                  These actions enter the approval queue regardless of amount.
                </FieldDescription>
                <FieldGroup data-slot="checkbox-group" className="grid gap-2">
                  {approvalActions.map(({ action, label }) => {
                    const id = `approval-action-${action}`;
                    return (
                      <Field orientation="horizontal" key={action}>
                        <Checkbox
                          id={id}
                          checked={settings.require_approval_actions.includes(
                            action,
                          )}
                          onCheckedChange={(checked) =>
                            setSettings((current) => ({
                              ...current,
                              require_approval_actions: checked
                                ? [...current.require_approval_actions, action]
                                : current.require_approval_actions.filter(
                                    (candidate) => candidate !== action,
                                  ),
                            }))
                          }
                        />
                        <FieldContent>
                          <FieldLabel htmlFor={id}>{label}</FieldLabel>
                          <FieldDescription>
                            {humanize(action)}
                          </FieldDescription>
                        </FieldContent>
                      </Field>
                    );
                  })}
                </FieldGroup>
              </FieldSet>
            </FieldGroup>
          </CardContent>
          <CardFooter className="flex-col items-stretch gap-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-sm leading-5 text-muted-foreground">
              Saving applies both the contact safeguards and approval rules.
            </p>
            <Button
              aria-busy={busy}
              aria-label="Save policy"
              disabled={busy}
              onClick={() =>
                persist(
                  settings,
                  source === "api"
                    ? "Contact and approval safeguards were saved."
                    : "Contact and approval safeguards were saved in local demo mode.",
                )
              }
            >
              {busy ? (
                <Spinner data-icon="inline-start" />
              ) : (
                <Save data-icon="inline-start" />
              )}
              Save all policy settings
            </Button>
          </CardFooter>
        </Card>
      </div>

      <Card>
        <CardHeader className="border-b border-border">
          <CardTitle>Emergency kill switch</CardTitle>
          <CardDescription>
            Immediately block all new payment, voice, and customer-agent actions
            when recovery operations must pause.
          </CardDescription>
          <CardAction>
            <Badge
              variant={
                settings.recovery_kill_switch ? "destructive" : "success"
              }
            >
              {settings.recovery_kill_switch ? "ON" : "OFF"}
            </Badge>
          </CardAction>
        </CardHeader>
        <CardContent className="grid gap-4 lg:grid-cols-2">
          <p className="text-base leading-6 text-muted-foreground">
            The kill switch blocks new provider actions only. Cases remain
            visible, and RecoveryOS continues watching for authoritative late
            payment events.
          </p>
          <Alert
            variant={settings.recovery_kill_switch ? "destructive" : "warning"}
          >
            <ShieldAlert />
            <AlertTitle>Payment verification stays active</AlertTitle>
            <AlertDescription>
              Pausing recovery never disables webhook ingestion or payment
              reconciliation.
            </AlertDescription>
          </Alert>
        </CardContent>
        <CardFooter className="justify-end">
          <Button
            className="w-full sm:w-auto"
            variant={settings.recovery_kill_switch ? "outline" : "destructive"}
            disabled={busy}
            onClick={() =>
              settings.recovery_kill_switch
                ? persist(
                    { ...settings, recovery_kill_switch: false },
                    "Recovery actions were resumed.",
                  )
                : setKillConfirm(true)
            }
          >
            {settings.recovery_kill_switch ? (
              <Play data-icon="inline-start" />
            ) : (
              <Pause data-icon="inline-start" />
            )}
            {settings.recovery_kill_switch
              ? "Resume recovery actions"
              : "Pause all recovery actions"}
          </Button>
        </CardFooter>
      </Card>

      <ConfirmDialog
        open={killConfirm}
        danger
        busy={busy}
        title="Pause all recovery actions?"
        description="This blocks new payment surfaces, voice calls, and customer-agent requests for every merchant case."
        confirmationText="Authoritative webhook ingestion and payment reconciliation remain enabled."
        confirmLabel="Turn on kill switch"
        onCancel={() => setKillConfirm(false)}
        onConfirm={async () => {
          await persist(
            { ...settings, recovery_kill_switch: true },
            "All new recovery actions were paused.",
          );
          setKillConfirm(false);
        }}
      />
    </div>
  );
}
