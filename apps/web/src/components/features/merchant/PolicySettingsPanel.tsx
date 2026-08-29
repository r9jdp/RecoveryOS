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
  FieldTitle,
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
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-4">
      <header className="flex flex-col gap-3 border-b border-border pb-4 sm:flex-row sm:items-end sm:justify-between">
        <div className="space-y-1">
          <p className="text-xs font-medium tracking-wide text-info uppercase">
            Platform safety
          </p>
          <h1 className="font-heading text-2xl font-semibold tracking-tight text-foreground">
            Recovery policy
          </h1>
          <p className="max-w-2xl text-sm text-muted-foreground">
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

      <div className="space-y-2" aria-live="polite">
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
      <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1.55fr)_minmax(18rem,0.75fr)]">
        <Card>
          <CardHeader className="border-b border-border">
            <CardTitle>Contact safeguards</CardTitle>
            <CardDescription>
              Merchant timezone and customer-contact boundaries.
            </CardDescription>
          </CardHeader>
          <CardContent className="pt-1">
            <FieldGroup className="grid gap-4 md:grid-cols-2">
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

              <FieldGroup className="grid gap-3 sm:grid-cols-2">
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

              <FieldSet className="rounded-lg border bg-muted/20 p-3 md:col-span-2">
                <FieldLegend variant="label">
                  Always require approval for
                </FieldLegend>
                <FieldDescription>
                  These actions enter the approval queue regardless of amount.
                </FieldDescription>
                <FieldGroup
                  data-slot="checkbox-group"
                  className="grid gap-1 md:grid-cols-3"
                >
                  {approvalActions.map(({ action, label }) => {
                    const id = `approval-action-${action}`;
                    return (
                      <FieldLabel htmlFor={id} key={action}>
                        <Field orientation="horizontal">
                          <Checkbox
                            id={id}
                            checked={settings.require_approval_actions.includes(
                              action,
                            )}
                            onCheckedChange={(checked) =>
                              setSettings((current) => ({
                                ...current,
                                require_approval_actions: checked
                                  ? [
                                      ...current.require_approval_actions,
                                      action,
                                    ]
                                  : current.require_approval_actions.filter(
                                      (candidate) => candidate !== action,
                                    ),
                              }))
                            }
                          />
                          <FieldContent>
                            <FieldTitle>{label}</FieldTitle>
                            <FieldDescription>
                              {humanize(action)}
                            </FieldDescription>
                          </FieldContent>
                        </Field>
                      </FieldLabel>
                    );
                  })}
                </FieldGroup>
              </FieldSet>
            </FieldGroup>
          </CardContent>
          <CardFooter className="justify-end bg-transparent">
            <Button
              aria-busy={busy}
              aria-label="Save policy"
              disabled={busy}
              onClick={() =>
                persist(
                  settings,
                  source === "api"
                    ? "Contact and approval safeguards were saved."
                    : "Contact and approval safeguards were saved in simulated mode.",
                )
              }
            >
              {busy ? (
                <Spinner data-icon="inline-start" />
              ) : (
                <Save data-icon="inline-start" />
              )}
              Save policy
            </Button>
          </CardFooter>
        </Card>

        <Card size="sm">
          <CardHeader className="border-b border-border">
            <CardTitle>Global recovery kill switch</CardTitle>
            <CardDescription>
              Emergency control for all new payment, voice, and customer-agent
              actions.
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
          <CardContent className="space-y-3 pt-1">
            <p className="text-sm leading-relaxed text-muted-foreground">
              Reconciliation stays active so authoritative late payments can
              still close cases safely.
            </p>
            <div className="rounded-lg border border-border bg-muted/20 p-3 text-xs leading-relaxed text-muted-foreground">
              Pausing blocks new actions only. It does not hide cases or stop
              payment verification.
            </div>
          </CardContent>
          <CardFooter className="bg-transparent">
            <Button
              className="w-full"
              variant={
                settings.recovery_kill_switch ? "outline" : "destructive"
              }
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
      </div>

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
