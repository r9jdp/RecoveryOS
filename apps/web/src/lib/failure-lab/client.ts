import type { components } from "@/lib/api/schema";

export type FailureSimulationRequest =
  components["schemas"]["FailureSimulationRequest"];
export type FailureSimulationResponse =
  components["schemas"]["FailureSimulationResponse"];

export type FailureScenario = FailureSimulationRequest["scenario"];

function apiBaseUrl(): string | null {
  const configured = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
  return configured ? configured.replace(/\/$/, "") : null;
}

interface ApiErrorPayload {
  error?: { message?: string };
  detail?: string | Array<{ msg?: string }>;
  message?: string;
}

async function errorMessage(response: Response): Promise<string> {
  const payload = (await response
    .json()
    .catch(() => null)) as ApiErrorPayload | null;
  if (payload?.error?.message) return payload.error.message;
  if (payload?.message) return payload.message;
  if (typeof payload?.detail === "string") return payload.detail;
  if (Array.isArray(payload?.detail)) {
    const validationMessage = payload.detail.find((item) => item.msg)?.msg;
    if (validationMessage) return validationMessage;
  }
  return `Failure simulator returned status ${response.status}.`;
}

export async function runFailureSimulation(
  request: FailureSimulationRequest,
  signal?: AbortSignal,
): Promise<FailureSimulationResponse> {
  const baseUrl = apiBaseUrl();
  if (!baseUrl) {
    throw new Error(
      "The failure simulator API is not connected. Start the API and set NEXT_PUBLIC_API_BASE_URL to run this contract lab.",
    );
  }

  const response = await fetch(`${baseUrl}/v1/simulations/failure-injection`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(request),
    signal,
  });

  if (!response.ok) throw new Error(await errorMessage(response));
  return (await response.json()) as FailureSimulationResponse;
}
