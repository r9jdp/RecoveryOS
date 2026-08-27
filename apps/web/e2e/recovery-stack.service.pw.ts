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

interface A2AWorkflowStart {
  case_id: string;
  currency: string;
  customer_id: string;
  exact_amount_paise: number;
  merchant_id: string;
  payment_surface_reference: string;
  payment_surface_type: string;
  recovery_deadline: string;
  task_id: string;
  workflow_id: string;
}

interface A2AServiceSnapshot {
  database: {
    action_external_reference: string | null;
    action_status: string | null;
    customer_task_id: string | null;
    customer_task_state: string | null;
    customer_task_version: number | null;
    nonce_consumption_count: number;
  };
  temporal: {
    a2a_state: string | null;
    action: string | null;
    action_status: string | null;
    mandate_received: boolean;
    phase: string;
    provider_reference: string | null;
  };
}

interface A2AReplayResult {
  mandate_id: string | null;
  reason_code: string | null;
  remote_task_id: string;
  task_state: string;
  verification_status: string;
  verified_artifact: Record<string, unknown> | null;
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

function serviceState(
  command:
    "snapshot" | "start-a2a-workflow" | "a2a-snapshot" | "replay-a2a-mandate",
): unknown {
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

const a2aHeaders = {
  "A2A-Version": "1.0",
  "A2A-Extensions": "https://recoveryos.dev/a2a/recovery-mandate/v1",
};

function a2aRpc(id: string, method: string, params: Record<string, unknown>) {
  return { jsonrpc: "2.0", id, method, params };
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

async function a2aSnapshotEventually(
  predicate: (snapshot: A2AServiceSnapshot) => boolean,
): Promise<A2AServiceSnapshot> {
  let latest: A2AServiceSnapshot | null = null;
  try {
    await expect
      .poll(
        () => {
          latest = serviceState("a2a-snapshot") as A2AServiceSnapshot;
          return predicate(latest);
        },
        { timeout: 45_000 },
      )
      .toBe(true);
  } catch (error) {
    throw new Error(
      `A2A service state did not converge; latest=${JSON.stringify(latest)}`,
      { cause: error },
    );
  }
  if (!latest) throw new Error("A2A service state was not returned");
  return latest;
}

test("real services recover FitBox without fixture or network mocks", async ({
  page,
  playwright,
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

  const a2aStart = serviceState("start-a2a-workflow") as A2AWorkflowStart;
  expect(a2aStart.workflow_id).toBe(`recovery-case:${a2aStart.case_id}`);

  const approvalSummary = await request.get(
    `${customerAgentOrigin}/v1/tasks/${a2aStart.task_id}/approval`,
  );
  expect(approvalSummary.ok()).toBe(true);
  await expect(approvalSummary.json()).resolves.toMatchObject({
    task_id: a2aStart.task_id,
    state: "TASK_STATE_AUTH_REQUIRED",
    merchant_id: a2aStart.merchant_id,
    case_id: a2aStart.case_id,
    exact_amount_paise: a2aStart.exact_amount_paise,
    currency: a2aStart.currency,
    payment_surface_type: a2aStart.payment_surface_type,
    payment_surface_reference: a2aStart.payment_surface_reference,
  });

  const customerApproval = await request.post(
    `${customerAgentOrigin}/v1/tasks/${a2aStart.task_id}/approval`,
    {
      data: {
        decision: "APPROVE",
        merchant_id: a2aStart.merchant_id,
        case_id: a2aStart.case_id,
        exact_amount_paise: a2aStart.exact_amount_paise,
        payment_surface_reference: a2aStart.payment_surface_reference,
      },
    },
  );
  expect(customerApproval.ok()).toBe(true);
  const approvedTask = (await customerApproval.json()) as Record<
    string,
    unknown
  >;
  expect(approvedTask).toMatchObject({
    id: a2aStart.task_id,
    status: { state: "TASK_STATE_WORKING" },
  });
  const artifacts = approvedTask.artifacts as Array<{
    parts: Array<{ data: Record<string, unknown> }>;
  }>;
  expect(artifacts[0]?.parts[0]?.data).toMatchObject({
    algorithm: "Ed25519",
    data: {
      protocol_version: "recovery.mandate.v1",
      task_id: a2aStart.task_id,
      merchant_id: a2aStart.merchant_id,
      case_id: a2aStart.case_id,
      customer_id: a2aStart.customer_id,
      exact_amount_paise: a2aStart.exact_amount_paise,
      currency: a2aStart.currency,
      payment_surface_type: a2aStart.payment_surface_type,
      payment_surface_reference: a2aStart.payment_surface_reference,
      authorized_action: "OPEN_EXACT_PAYMENT_SURFACE",
      signer_key_id: "recoveryos-mock-2026-01",
    },
  });

  const verified = await a2aSnapshotEventually(
    (value) =>
      value.temporal.mandate_received &&
      value.temporal.action === "OPEN_CUSTOMER_PAYMENT_SURFACE" &&
      value.temporal.action_status === "SUCCEEDED" &&
      value.database.action_status === "SUCCEEDED" &&
      value.database.nonce_consumption_count === 1,
  );
  expect(verified.database.customer_task_id).toBe(a2aStart.task_id);
  expect(verified.database.customer_task_state).toBe("TASK_STATE_WORKING");
  expect(verified.database.customer_task_version).toBe(2);
  expect(verified.database.action_external_reference).toMatch(/^mock_surface_/);

  const freshAgentClient = await playwright.request.newContext({
    baseURL: customerAgentOrigin,
    extraHTTPHeaders: a2aHeaders,
  });
  try {
    const fetched = await freshAgentClient.post("/rpc", {
      data: a2aRpc("service-e2e-fresh-client", "GetTask", {
        id: a2aStart.task_id,
        historyLength: 1,
      }),
    });
    expect(fetched.ok()).toBe(true);
    await expect(fetched.json()).resolves.toMatchObject({
      jsonrpc: "2.0",
      id: "service-e2e-fresh-client",
      result: {
        id: a2aStart.task_id,
        status: { state: "TASK_STATE_WORKING" },
      },
    });
  } finally {
    await freshAgentClient.dispose();
  }

  const replay = serviceState("replay-a2a-mandate") as A2AReplayResult;
  expect(replay).toMatchObject({
    remote_task_id: a2aStart.task_id,
    task_state: "WORKING",
    verification_status: "REJECTED",
    reason_code: "REPLAYED",
    mandate_id: null,
    verified_artifact: null,
  });
  const afterReplay = serviceState("a2a-snapshot") as A2AServiceSnapshot;
  expect(afterReplay.database.nonce_consumption_count).toBe(1);
});
