import { recoveryBenchFixture } from "./fixture";
import type { LabReport, LabReportResult } from "./types";
import { demoDataEnabled, recoveryLabApiOrigin } from "@/lib/runtime-config";

export async function getLabReport(
  signal?: AbortSignal,
): Promise<LabReportResult> {
  const baseUrl = recoveryLabApiOrigin();
  if (!baseUrl) {
    if (demoDataEnabled()) {
      return { data: recoveryBenchFixture, source: "mock" };
    }
    throw new Error(
      "Recovery Lab requires NEXT_PUBLIC_API_BASE_URL. Bundled reports are disabled in live mode.",
    );
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
    if (!demoDataEnabled()) {
      throw new Error(
        `The live Recovery Lab report could not be loaded: ${error instanceof Error ? error.message : "unknown error"}`,
      );
    }
    return {
      data: recoveryBenchFixture,
      source: "mock",
      warning: `The live report is unavailable (${error instanceof Error ? error.message : "unknown error"}); the versioned bundled report is shown.`,
    };
  }
}
