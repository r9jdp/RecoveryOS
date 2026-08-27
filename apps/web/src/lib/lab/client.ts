import { recoveryBenchFixture } from "./fixture";
import type { LabReport, LabReportResult } from "./types";

function apiBaseUrl(): string | null {
  const configured = process.env.NEXT_PUBLIC_RECOVERY_API_URL?.trim();
  return configured ? configured.replace(/\/$/, "") : null;
}

export async function getLabReport(
  signal?: AbortSignal,
): Promise<LabReportResult> {
  const baseUrl = apiBaseUrl();
  if (!baseUrl) {
    return { data: recoveryBenchFixture, source: "mock" };
  }
  try {
    const response = await fetch(`${baseUrl}/v1/lab/reports/latest`, {
      signal,
    });
    if (!response.ok) {
      throw new Error(`report endpoint returned ${response.status}`);
    }
    return { data: (await response.json()) as LabReport, source: "api" };
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    return {
      data: recoveryBenchFixture,
      source: "mock",
      warning: `The live report is unavailable (${error instanceof Error ? error.message : "unknown error"}); the versioned bundled report is shown.`,
    };
  }
}
