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
  plan_name: string;
  failure_explanation: string;
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

export interface LanguageInterpretation {
  task_id: string;
  intent: "APPROVE" | "REJECT" | "ASK_QUESTION" | "UNCLEAR";
  confidence_basis_points: number;
  explanation: string;
  authorization_effect: "NONE";
  requires_explicit_approval: true;
  authoritative_scope: {
    merchant_id: string;
    case_id: string;
    exact_amount_paise: number;
    currency: string;
    payment_surface_type: string;
    payment_surface_reference: string;
    expires_at: string;
  };
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

export async function interpretCustomerLanguage(
  origin: string,
  taskId: string,
  text: string,
): Promise<LanguageInterpretation> {
  const response = await fetch(
    `${origin.replace(/\/$/, "")}/v1/tasks/${encodeURIComponent(taskId)}/interpretation`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, channel: "TEXT" }),
    },
  );
  if (!response.ok) throw await customerAgentError(response);
  return (await response.json()) as LanguageInterpretation;
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
