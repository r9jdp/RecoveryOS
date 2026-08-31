import {
  demoDataEnabled,
  recoveryApiOrigin,
  requireRecoveryApiOrigin,
} from "@/lib/runtime-config";

const CSRF_STORAGE_KEY = "recoveryos-operator-csrf";

interface SessionResponse {
  csrf_token: string;
  expires_at_epoch: number;
  operator: string;
}

interface ApiErrorPayload {
  error?: { message?: string };
  detail?: string;
}

export async function createOperatorSession(
  email: string,
  password: string,
): Promise<"api" | "fixture"> {
  const baseUrl = recoveryApiOrigin();
  if (!baseUrl) {
    if (demoDataEnabled()) return "fixture";
    requireRecoveryApiOrigin("Operator login");
  }

  const response = await fetch(`${baseUrl!}/v1/operator/session`, {
    method: "POST",
    credentials: "include",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ email, password }),
  });
  if (!response.ok) {
    const payload = (await response
      .json()
      .catch(() => null)) as ApiErrorPayload | null;
    throw new Error(
      payload?.error?.message ??
        payload?.detail ??
        "The operator session could not be created.",
    );
  }
  const session = (await response.json()) as SessionResponse;
  window.sessionStorage.setItem(CSRF_STORAGE_KEY, session.csrf_token);
  return "api";
}

export function operatorMutationHeaders(): Record<string, string> {
  if (typeof window === "undefined") return {};
  const csrfToken = window.sessionStorage.getItem(CSRF_STORAGE_KEY);
  return csrfToken ? { "X-RecoveryOS-CSRF-Token": csrfToken } : {};
}
