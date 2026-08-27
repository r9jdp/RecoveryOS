"use client";

import { useEffect, useState } from "react";

import { PageHeader } from "@/components/layout";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  Input,
  Select,
} from "@/components/ui";
import {
  getPolicySettings,
  updatePolicySettings,
} from "@/lib/api/recovery-client";
import { merchantDashboard } from "@/lib/merchant-demo";
import { formatPaise, humanize } from "@/lib/recovery-format";
import type { PolicySettings, RecoveryAction } from "@/types/recovery";

import { ConfirmDialog } from "./ConfirmDialog";
import styles from "./merchant.module.css";

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
    <div className={styles.pageStack}>
      <PageHeader
        eyebrow="Platform safety"
        title="Recovery policy"
        description="Configure operator approval, contact limits, quiet hours, and the global recovery kill switch."
        action={
          <Badge
            tone={settings.recovery_kill_switch ? "danger" : "success"}
            showDot
          >
            {settings.recovery_kill_switch
              ? "Recovery paused"
              : "Recovery active"}
          </Badge>
        }
      />
      {notice && (
        <Alert tone="success" title="Policy updated">
          {notice}
        </Alert>
      )}
      {readWarning && (
        <Alert tone="info" title="Fallback policy data">
          {readWarning}
        </Alert>
      )}
      {error && (
        <Alert tone="danger" title="Policy update failed">
          {error} Existing settings remain active.
        </Alert>
      )}
      {settings.recovery_kill_switch && (
        <Alert tone="danger" title="Global kill switch is on">
          New provider actions are blocked. Existing cases remain visible and
          payment reconciliation continues.
        </Alert>
      )}
      <h2 className={styles.srOnly}>Policy controls</h2>
      <div className={styles.settingsGrid}>
        <Card>
          <CardHeader
            title="Contact safeguards"
            description="Merchant timezone and customer-contact boundaries."
          />
          <CardBody className={styles.formGrid}>
            <Select
              label="Merchant timezone"
              value={settings.timezone}
              onChange={(event) =>
                setSettings((current) => ({
                  ...current,
                  timezone: event.target.value,
                }))
              }
            >
              <option value="Asia/Kolkata">Asia/Kolkata</option>
            </Select>
            <div className={styles.fieldPair}>
              <Input
                label="Quiet hours begin"
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
              <Input
                label="Quiet hours end"
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
            </div>
            <Input
              label="Maximum contacts in 7 days"
              type="number"
              min={1}
              max={7}
              value={settings.max_contacts_per_7_days ?? ""}
              hint="Leave empty to disable the rolling contact cap."
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
            <Input
              label="Require approval above (paise)"
              type="number"
              min={0}
              step={100}
              value={settings.require_approval_above_paise ?? ""}
              hint={
                settings.require_approval_above_paise === null
                  ? "Amount-based approval is disabled."
                  : `Currently ${formatPaise(settings.require_approval_above_paise)}`
              }
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
            <fieldset className={styles.checkboxGroup}>
              <legend>Always require approval for</legend>
              <p className={styles.quiet}>
                These actions enter the approval queue regardless of amount.
              </p>
              {approvalActions.map(({ action, label }) => (
                <label className={styles.checkboxRow} key={action}>
                  <input
                    type="checkbox"
                    checked={settings.require_approval_actions.includes(action)}
                    onChange={(event) =>
                      setSettings((current) => ({
                        ...current,
                        require_approval_actions: event.target.checked
                          ? [...current.require_approval_actions, action]
                          : current.require_approval_actions.filter(
                              (candidate) => candidate !== action,
                            ),
                      }))
                    }
                  />
                  <span>
                    <strong>{label}</strong>
                    <small>{humanize(action)}</small>
                  </span>
                </label>
              ))}
            </fieldset>
            <div>
              <Button
                loading={busy}
                onClick={() =>
                  persist(
                    settings,
                    source === "api"
                      ? "Contact and approval safeguards were saved."
                      : "Contact and approval safeguards were saved in simulated mode.",
                  )
                }
              >
                Save policy
              </Button>
            </div>
          </CardBody>
        </Card>
        <Card className={styles.dangerCard}>
          <CardHeader
            title="Global recovery kill switch"
            description="Emergency control for all new payment, voice, and customer-agent actions."
            action={
              <Badge
                tone={settings.recovery_kill_switch ? "danger" : "neutral"}
              >
                {settings.recovery_kill_switch ? "ON" : "OFF"}
              </Badge>
            }
          />
          <CardBody className={styles.stack}>
            <p className={styles.cardCopy}>
              Reconciliation stays active so authoritative late payments can
              still close cases safely.
            </p>
            <Button
              variant={settings.recovery_kill_switch ? "secondary" : "danger"}
              onClick={() =>
                settings.recovery_kill_switch
                  ? persist(
                      { ...settings, recovery_kill_switch: false },
                      "Recovery actions were resumed.",
                    )
                  : setKillConfirm(true)
              }
            >
              {settings.recovery_kill_switch
                ? "Resume recovery actions"
                : "Pause all recovery actions"}
            </Button>
          </CardBody>
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
