import type { operations } from "./schema";
import caseDetailFixtureJson from "../../../../../packages/contracts/fixtures/case-detail.json";
import dashboardFixtureJson from "../../../../../packages/contracts/fixtures/dashboard.json";
import type {
  CaseCommand,
  CaseDetailFixture,
  CommandResult,
  DashboardFixture,
  FixtureResult,
} from "@/types/recovery";

type DemoFixtureName =
  operations["getDemoFixture"]["parameters"]["path"]["fixture_name"];

const dashboardFixture = dashboardFixtureJson as DashboardFixture;
const caseDetailFixture = caseDetailFixtureJson as CaseDetailFixture;

function apiBaseUrl(): string | null {
  const configured = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
  return configured ? configured.replace(/\/$/, "") : null;
}

function fallbackFixture<T>(fixture: T): FixtureResult<T> {
  return {
    data: structuredClone(fixture),
    source: "mock",
    warning:
      "Showing the deterministic FitBox demo fixture. No provider action will run.",
  };
}

async function fetchFixture<T>(
  name: DemoFixtureName,
  fallback: T,
  signal?: AbortSignal,
): Promise<FixtureResult<T>> {
  const baseUrl = apiBaseUrl();
  if (!baseUrl) {
    return fallbackFixture(fallback);
  }

  try {
    const response = await fetch(`${baseUrl}/v1/demo/fixtures/${name}`, {
      headers: { Accept: "application/json" },
      signal,
    });

    if (!response.ok) {
      const result = fallbackFixture(fallback);
      result.warning = `API fixture request returned ${response.status}; deterministic demo data is shown instead.`;
      return result;
    }

    return { data: (await response.json()) as T, source: "api" };
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    const result = fallbackFixture(fallback);
    result.warning =
      "The API is unavailable; deterministic demo data is shown instead.";
    return result;
  }
}

export function getDashboard(
  signal?: AbortSignal,
): Promise<FixtureResult<DashboardFixture>> {
  return fetchFixture("dashboard", dashboardFixture, signal);
}

export async function getCaseDetail(
  caseId: string,
  signal?: AbortSignal,
): Promise<FixtureResult<CaseDetailFixture>> {
  const result = await fetchFixture("case-detail", caseDetailFixture, signal);
  if (result.data.case.id !== caseId) {
    return {
      ...result,
      warning: `Case ${caseId} is not present in the frozen fixture; the FitBox reference case is shown.`,
    };
  }
  return result;
}

export async function executeCaseCommand(
  caseId: string,
  command: CaseCommand,
): Promise<CommandResult> {
  const baseUrl = apiBaseUrl();
  if (!baseUrl) {
    await new Promise((resolve) => window.setTimeout(resolve, 450));
    return {
      command,
      message:
        "The command was accepted by the mock provider. No external action was taken.",
      occurred_at: new Date().toISOString(),
      source: "mock",
      status: "ACCEPTED",
    };
  }

  const response = await fetch(
    `${baseUrl}/v1/recovery-cases/${encodeURIComponent(caseId)}/commands`,
    {
      body: JSON.stringify({ command }),
      headers: { "Content-Type": "application/json" },
      method: "POST",
    },
  );

  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as {
      error?: { message?: string };
    } | null;
    throw new Error(
      payload?.error?.message ??
        `Command failed with status ${response.status}.`,
    );
  }

  const payload = (await response.json()) as Partial<CommandResult>;
  return {
    command,
    message: payload.message ?? "Command accepted.",
    occurred_at: payload.occurred_at ?? new Date().toISOString(),
    source: "api",
    status: "ACCEPTED",
  };
}
