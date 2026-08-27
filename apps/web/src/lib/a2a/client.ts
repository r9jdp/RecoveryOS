export interface ApprovalSummary {
  task_id: string;
  state: string;
  merchant_id: string;
  case_id: string;
  exact_amount_paise: number;
  currency: string;
  payment_surface_type: string;
  payment_surface_reference: string;
  expires_at: string;
  merchant_display_name: string;
  recovery_reason: string;
}

export type ApprovalChoice = "APPROVE" | "REJECT";

export interface ApprovalSubmission {
  decision: ApprovalChoice;
  merchant_id: string;
  case_id: string;
  exact_amount_paise: number;
  payment_surface_reference: string;
}

export interface ApprovalResult {
  id: string;
  status: { state: string };
}

export async function loadApprovalSummary(
  origin: string,
  taskId: string,
  signal?: AbortSignal,
): Promise<ApprovalSummary> {
  const response = await fetch(
    `${origin.replace(/\/$/, "")}/v1/tasks/${encodeURIComponent(taskId)}/approval`,
    { signal, cache: "no-store" },
  );
  if (!response.ok) throw await customerAgentError(response);
  return (await response.json()) as ApprovalSummary;
}

export async function submitApprovalDecision(
  origin: string,
  taskId: string,
  submission: ApprovalSubmission,
): Promise<ApprovalResult> {
  const response = await fetch(
    `${origin.replace(/\/$/, "")}/v1/tasks/${encodeURIComponent(taskId)}/approval`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(submission),
    },
  );
  if (!response.ok) throw await customerAgentError(response);
  return (await response.json()) as ApprovalResult;
}

async function customerAgentError(response: Response): Promise<Error> {
  const fallback = `Customer agent request failed (${response.status})`;
  try {
    const body = (await response.json()) as { detail?: string };
    return new Error(body.detail || fallback);
  } catch {
    return new Error(fallback);
  }
}
