import { execFileSync } from "node:child_process";
import path from "node:path";

import { expect, test } from "@playwright/test";

interface ServiceSnapshot {
  database: {
    action_external_reference: string | null;
    action_status: string | null;
    arrears_collected_paise: number;
    case_outcome: string;
    event_types: string[];
    payment_state: string;
    revenue_attribution: string;
    revenue_recognition_count: number;
  };
  temporal: {
    action_status: string | null;
    approval_received: boolean | null;
    duplicate_signal_count: number;
    execution_status: string;
    outcome: string | null;
    payment_state: string;
    phase: string;
  };
}

const apiOrigin = requiredEnv("RECOVERYOS_SERVICE_API_ORIGIN");
const customerAgentOrigin = requiredEnv(
  "RECOVERYOS_SERVICE_CUSTOMER_AGENT_ORIGIN",
);
const repositoryRoot = path.resolve(__dirname, "../../..");
const uv = process.platform === "win32" ? "uv.exe" : "uv";

function requiredEnv(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required`);
  return value.replace(/\/$/, "");
}

function serviceState(command: "snapshot"): unknown {
  const output = execFileSync(
    uv,
    ["run", "python", "scripts/e2e/service_state.py", command],
    {
      cwd: repositoryRoot,
      encoding: "utf8",
      env: process.env,
      timeout: 45_000,
    },
  );
  return JSON.parse(output.trim()) as unknown;
}

async function snapshotEventually(
  predicate: (snapshot: ServiceSnapshot) => boolean,
): Promise<ServiceSnapshot> {
  let latest: ServiceSnapshot | null = null;
  try {
    await expect
      .poll(
        () => {
          latest = serviceState("snapshot") as ServiceSnapshot;
          return predicate(latest);
        },
        { timeout: 30_000 },
      )
      .toBe(true);
  } catch (error) {
    throw new Error(
      `service state did not converge; latest=${JSON.stringify(latest)}`,
      { cause: error },
    );
  }
  if (!latest) throw new Error("service state was not returned");
  return latest;
}

test("real services recover FitBox without fixture or network mocks", async ({
  page,
  request,
}) => {
  const apiResponses: string[] = [];
  page.on("response", (response) => {
    if (response.url().startsWith(apiOrigin)) apiResponses.push(response.url());
  });

  await page.goto("/dashboard");
  await expect(page.getByText("API connected", { exact: true })).toBeVisible();
  await expect(page.getByText(/deterministic FitBox demo data/i)).toHaveCount(
    0,
  );
  await expect(page.getByText(/could not be loaded/i)).toHaveCount(0);
  await expect(page.getByText("Aarav Sharma", { exact: true })).toBeVisible();
  expect(
    apiResponses.some((url) => url.includes("/v1/dashboard/metrics")),
  ).toBe(true);
  expect(
    apiResponses.some((url) => url.includes("/v1/recovery-cases?limit=100")),
  ).toBe(true);

  await page.goto("/cases/case_fitbox_aug_2026");
  await expect(page.getByText("API connected", { exact: true })).toBeVisible();
  await expect(page.getByText(/could not be loaded/i)).toHaveCount(0);
  await page.getByRole("button", { name: "Approve recovery" }).click();

  const approved = await snapshotEventually(
    (value) =>
      value.temporal.approval_received === true &&
      value.temporal.action_status === "SUCCEEDED" &&
      value.database.action_status === "SUCCEEDED",
  );
  expect(approved.database.action_external_reference).toMatch(/^mock_surface_/);
  expect(approved.database.event_types).toContain("ACTION_APPROVED");
  expect(approved.database.event_types).toContain("APPROVAL_RECORDED");

  const successPayload = {
    provider_event_id: "service-e2e-payment-captured-001",
    amount_paise: 149_900,
    occurred_at: new Date().toISOString(),
    subscription_reactivated: true,
  };
  const first = await request.post(
    `${apiOrigin}/v1/mock/recovery-cases/case_fitbox_aug_2026/payment-success`,
    { data: successPayload },
  );
  expect(first.ok()).toBe(true);
  expect((await first.json()).newly_recognized).toBe(true);

  const duplicate = await request.post(
    `${apiOrigin}/v1/mock/recovery-cases/case_fitbox_aug_2026/payment-success`,
    { data: successPayload },
  );
  expect(duplicate.ok()).toBe(true);
  expect((await duplicate.json()).newly_recognized).toBe(false);

  const recovered = await snapshotEventually(
    (value) =>
      value.database.case_outcome === "RECOVERED" &&
      value.database.payment_state === "CAPTURED" &&
      value.database.revenue_recognition_count === 1 &&
      value.temporal.outcome === "RECOVERED" &&
      value.temporal.payment_state === "CAPTURED",
  );
  expect(recovered.database.arrears_collected_paise).toBe(149_900);
  expect(recovered.database.revenue_attribution).toBe("SIMULATED");

  await page.reload();
  await expect(page.getByText("API connected", { exact: true })).toBeVisible();
  await expect(
    page.getByText("Captured", { exact: true }).first(),
  ).toBeVisible();
  await expect(page.getByText(/could not be loaded/i)).toHaveCount(0);

  const agentHealth = await request.get(`${customerAgentOrigin}/health/ready`);
  expect(agentHealth.ok()).toBe(true);
  await expect(agentHealth.json()).resolves.toMatchObject({
    mode: "mock",
    status: "ready",
  });
  const agentCard = await request.get(
    `${customerAgentOrigin}/.well-known/agent-card.json`,
  );
  expect(agentCard.ok()).toBe(true);
  const card = (await agentCard.json()) as Record<string, unknown>;
  expect(card).toMatchObject({
    name: "RecoveryOS Customer Authorization Agent",
    supportedInterfaces: [
      {
        protocolBinding: "JSONRPC",
        protocolVersion: "1.0",
        url: `${customerAgentOrigin}/rpc`,
      },
    ],
  });
});
