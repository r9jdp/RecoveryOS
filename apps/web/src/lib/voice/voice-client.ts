import { operatorMutationHeaders } from "@/lib/operator-session";

export interface BrowserTranscriptResult {
  detected_intent: string;
  disposition: string;
  contact_must_end: boolean;
  suppression_persisted: boolean;
}

export interface StartVoiceResult {
  attempt_id: string;
  provider: string;
  status: "SUBMITTED" | "REJECTED" | "UNCERTAIN";
  reason_code: string;
  provider_call_id: string | null;
  retry_permitted: false;
}

export interface VoiceTimelineItem {
  id: string;
  case_id: string;
  status: string;
  disposition: string | null;
  transcript: string | null;
  detected_intent: string | null;
  confidence_basis_points: number | null;
  duration_seconds: number | null;
  disclosure_delivered_at: string | null;
  created_at: string;
}

function apiOrigin(): string {
  return (process.env.NEXT_PUBLIC_API_BASE_URL ?? "").replace(/\/$/, "");
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as {
      detail?: { message?: string; code?: string } | string;
    } | null;
    const detail = payload?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : (detail?.message ??
          detail?.code ??
          `Request failed (${response.status})`);
    throw new Error(message);
  }
  return (await response.json()) as T;
}

export async function submitBrowserTranscript(
  attemptId: string,
  transcript: string,
): Promise<BrowserTranscriptResult> {
  const response = await fetch(
    `${apiOrigin()}/v1/voice/contacts/${encodeURIComponent(attemptId)}/browser-transcript`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Voice-Event-Id": crypto.randomUUID(),
      },
      body: JSON.stringify({ transcript, confidence_basis_points: 10_000 }),
    },
  );
  return parseResponse<BrowserTranscriptResult>(response);
}

export async function startRealVoiceContact(
  caseId: string,
): Promise<StartVoiceResult> {
  const response = await fetch(`${apiOrigin()}/v1/voice/contacts`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...operatorMutationHeaders(),
    },
    credentials: "include",
    body: JSON.stringify({
      case_id: caseId,
      idempotency_key: `voice:${caseId}:${crypto.randomUUID()}`,
      max_duration_seconds: 180,
    }),
  });
  return parseResponse<StartVoiceResult>(response);
}

export async function fetchVoiceTimeline(
  caseId: string,
): Promise<VoiceTimelineItem[]> {
  const response = await fetch(
    `${apiOrigin()}/v1/voice/cases/${encodeURIComponent(caseId)}/timeline`,
    { cache: "no-store" },
  );
  const payload = await parseResponse<{ items: VoiceTimelineItem[] }>(response);
  return payload.items;
}
