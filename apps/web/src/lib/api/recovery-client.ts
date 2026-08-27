import type { components } from "./schema";
import caseDetailFixtureJson from "../../../../../packages/contracts/fixtures/case-detail.json";
import dashboardFixtureJson from "../../../../../packages/contracts/fixtures/dashboard.json";
import type {
  CaseCommand,
  CaseDetailFixture,
  CommandResult,
  DashboardCase,
  DashboardFixture,
  FixtureResult,
  PolicySettings,
  SafetyDisposition,
  SafetyDispositionResult,
} from "@/types/recovery";

type ApiSchemas = components["schemas"];
type LiveDashboard = ApiSchemas["DashboardResponse"];
type LiveCaseList = ApiSchemas["CaseListResponse"];
type LiveCaseDetail = ApiSchemas["CaseDetailResponse"];
type LiveTimeline = ApiSchemas["TimelineResponse"];

const rawDashboardFixture = dashboardFixtureJson as DashboardFixture;
const dashboardFixture: DashboardFixture = {
  ...rawDashboardFixture,
  policy_settings: {
    ...rawDashboardFixture.policy_settings,
    require_approval_actions:
      rawDashboardFixture.policy_settings.require_approval_actions ?? [],
  },
};
const caseDetailFixture = caseDetailFixtureJson as CaseDetailFixture;

function apiBaseUrl(): string | null {
  const configured = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
  return configured ? configured.replace(/\/$/, "") : null;
}

function fallbackFixture<T>(fixture: T, warning?: string): FixtureResult<T> {
  return {
    data: structuredClone(fixture),
    source: "mock",
    warning:
      warning ??
      "Showing the deterministic FitBox demo fixture. No provider action will run.",
  };
}

interface ApiErrorPayload {
  error?: { message?: string };
  detail?: string | Array<{ msg?: string }>;
  message?: string;
}

async function apiErrorMessage(
  response: Response,
  fallback: string,
): Promise<string> {
  const payload = (await response
    .json()
    .catch(() => null)) as ApiErrorPayload | null;
  if (payload?.error?.message) return payload.error.message;
  if (payload?.message) return payload.message;
  if (typeof payload?.detail === "string") return payload.detail;
  const validationMessage = Array.isArray(payload?.detail)
    ? payload.detail.find((item) => item.msg)?.msg
    : null;
  return validationMessage ?? fallback;
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: { Accept: "application/json", ...init?.headers },
  });
  if (!response.ok) {
    throw new Error(
      await apiErrorMessage(
        response,
        `API request failed with status ${response.status}.`,
      ),
    );
  }
  return (await response.json()) as T;
}

function fallbackWarning(error: unknown, resource: string): string {
  const reason =
    error instanceof Error ? error.message : "The API is unavailable.";
  return `${resource} could not be loaded (${reason}); deterministic FitBox demo data is shown instead.`;
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

function normalizePolicySettings(settings: PolicySettings): PolicySettings {
  return {
    ...settings,
    require_approval_actions: settings.require_approval_actions ?? [],
  };
}

function normalizeDashboardCase(
  item: ApiSchemas["CaseSummaryResponse"],
): DashboardCase {
  const fallback = dashboardFixture.cases.find(
    (candidate) => candidate.id === item.id,
  );
  return {
    id: item.id,
    merchant_id: item.merchant_id,
    failed_invoice_id:
      item.failed_invoice_id ?? fallback?.failed_invoice_id ?? "not-correlated",
    billing_cycle_key:
      item.billing_cycle_key ?? fallback?.billing_cycle_key ?? "not-correlated",
    customer_display_name:
      item.customer_display_name ??
      fallback?.customer_display_name ??
      "Unknown customer",
    plan_name: item.plan_name ?? fallback?.plan_name ?? "Unknown plan",
    amount_at_risk_paise: item.amount_at_risk_paise,
    case_outcome: item.case_outcome,
    payment_state: item.payment_state,
    subscription_state: item.subscription_state,
    contact_disposition: item.contact_disposition,
    revenue_attribution: item.revenue_attribution,
    diagnosis: item.diagnosis,
    recommended_action:
      item.recommended_action ??
      fallback?.recommended_action ??
      "ESCALATE_TO_HUMAN",
    payment_surface_type: item.payment_surface_type ?? null,
    updated_at: item.updated_at,
  };
}

function composeDashboard(
  dashboard: LiveDashboard,
  caseList: LiveCaseList,
): DashboardFixture {
  const cases = caseList.items.map(normalizeDashboardCase);
  const channels: DashboardFixture["recovery_by_channel"][number]["channel"][] =
    [
      "SUBSCRIPTION_CARD_UPDATE",
      "SUBSCRIPTION_INVOICE_LINK",
      "STANDARD_PAYMENT_LINK",
      "VOICE",
      "CUSTOMER_AGENT",
    ];
  return {
    fixture_version: "screens.v1",
    screen: "/dashboard",
    evidence_kind: dashboard.evidence_kind,
    currency: "INR",
    metrics: {
      revenue_at_risk_paise: dashboard.metrics.revenue_at_risk_paise,
      verified_recovered_revenue_paise:
        dashboard.metrics.verified_recovered_revenue_paise,
      simulated_incremental_recovery_paise:
        dashboard.metrics.simulated_incremental_recovery_paise,
      net_recovered_value_paise: dashboard.metrics.net_recovered_value_paise,
      active_cases: dashboard.metrics.active_cases,
      recovery_rate_basis_points: dashboard.metrics.recovery_rate_basis_points,
      human_review_count: dashboard.metrics.human_review_count,
      policy_blocked_actions: dashboard.metrics.policy_blocked_actions,
    },
    diagnosis_distribution: dashboard.diagnosis_distribution,
    recovery_by_channel: channels.map((channel) => ({
      channel,
      case_count: cases.filter((item) => {
        if (channel === "VOICE")
          return item.recommended_action === "START_VOICE";
        if (channel === "CUSTOMER_AGENT")
          return item.recommended_action === "SEND_TO_CUSTOMER_AGENT";
        return item.payment_surface_type === channel;
      }).length,
      recovered_paise: 0,
    })),
    policy_settings: structuredClone(dashboardFixture.policy_settings),
    cases,
    recent_events: dashboard.recent_events,
  };
}

function composeCaseDetail(
  detail: LiveCaseDetail,
  timeline: LiveTimeline,
): CaseDetailFixture {
  const recoveryCase = detail.case;
  const failure = detail.payment_failure;
  const action = detail.latest_action;
  const policy = detail.latest_policy;
  const evidenceKind =
    timeline.items.find(
      (event) => event.evidence_kind === "RAZORPAY_TEST_VERIFIED",
    )?.evidence_kind ??
    timeline.items[0]?.evidence_kind ??
    (recoveryCase.revenue_attribution === "RAZORPAY_TEST_VERIFIED"
      ? "RAZORPAY_TEST_VERIFIED"
      : "SIMULATED");
  return {
    fixture_version: "screens.v1",
    screen: `/cases/${recoveryCase.id}`,
    case: {
      id: recoveryCase.id,
      key: {
        merchant_id: recoveryCase.merchant_id,
        failed_invoice_id: recoveryCase.failed_invoice_id ?? "not-correlated",
        billing_cycle_key: recoveryCase.billing_cycle_key ?? "not-correlated",
      },
      customer_id: recoveryCase.customer_id,
      subscription_id: recoveryCase.subscription_id,
      failed_payment_id: recoveryCase.failed_payment_id ?? "not-correlated",
      case_outcome: recoveryCase.case_outcome,
      payment_state: recoveryCase.payment_state,
      subscription_state: recoveryCase.subscription_state,
      contact_disposition: recoveryCase.contact_disposition,
      revenue_attribution: recoveryCase.revenue_attribution,
      case_recovered: recoveryCase.case_recovered,
      arrears_collected_paise: recoveryCase.arrears_collected_paise,
      subscription_reactivated: recoveryCase.subscription_reactivated,
      diagnosis: recoveryCase.diagnosis,
      amount_at_risk_paise: recoveryCase.amount_at_risk_paise,
      opened_at: recoveryCase.opened_at,
      recovery_deadline: recoveryCase.recovery_deadline,
    },
    customer: {
      id: detail.customer.id,
      display_name: detail.customer.display_name,
      preferred_language: detail.customer.preferred_language,
      voice_consent: Boolean(detail.customer.voice_consent_at),
      opted_out_at: detail.customer.opted_out_at,
      customer_agent_available: detail.customer.customer_agent_available,
    },
    subscription: {
      id: detail.subscription.id,
      plan_name: detail.subscription.plan_name,
      amount_paise: detail.subscription.amount_paise,
      currency: "INR",
      subscription_state: detail.subscription.subscription_state,
    },
    payment_failure: {
      payment_id:
        failure?.provider_payment_id ??
        failure?.id ??
        recoveryCase.failed_payment_id ??
        "not-correlated",
      invoice_id:
        detail.invoice?.provider_invoice_id ??
        recoveryCase.failed_invoice_id ??
        "not-correlated",
      method: failure?.method ?? "unknown",
      error_source: failure?.error_source ?? "unknown",
      error_step: failure?.error_step ?? "unknown",
      error_reason: failure?.error_reason ?? failure?.error_code ?? "unknown",
      occurred_at: failure?.occurred_at ?? recoveryCase.opened_at,
    },
    evidence: failure
      ? [
          {
            kind: evidenceKind,
            field: "error_reason",
            value: failure.error_reason ?? failure.error_code ?? "unknown",
            source_event: "payment.failed",
          },
        ]
      : [],
    recommendation: {
      action: action?.action_type ?? "STOP",
      payment_surface_type: action?.payment_surface_type ?? null,
      predicted_recovery_probability: 0,
      expected_recovered_paise: 0,
      expected_utility_paise: 0,
      confidence: 0,
      reason_codes: [action ? "LIVE_ACTION_LOADED" : "NO_LIVE_ACTION"],
      reasons: [
        action
          ? `Live action is ${action.status.toLowerCase().replaceAll("_", " ")}.`
          : "No live recovery action is currently recommended.",
      ],
      rejected_alternatives: [],
    },
    policy: policy
      ? {
          disposition: policy.disposition,
          decision_code: policy.decision_code,
          reason_codes: policy.reason_codes,
          reasons: policy.reasons,
          policy_version: policy.policy_version,
        }
      : {
          disposition: "BLOCK",
          decision_code: "POLICY_NOT_AVAILABLE",
          reason_codes: ["POLICY_NOT_AVAILABLE"],
          reasons: ["No live policy decision is available for this case."],
          policy_version: "unavailable",
        },
    payment_surface: {
      type: action?.payment_surface_type ?? null,
      status: action?.status ?? "NOT_CREATED",
      provider_reference: action?.external_reference ?? null,
      customer_url: action?.customer_url ?? null,
      authoritative_payment_state: recoveryCase.payment_state,
      arrears_collected_paise: recoveryCase.arrears_collected_paise,
      subscription_reactivated: recoveryCase.subscription_reactivated,
    },
    available_commands: detail.available_commands,
    timeline: timeline.items.map((event) => ({
      id: event.id,
      event_type: event.event_type,
      source: event.source,
      evidence_kind: event.evidence_kind,
      occurred_at: event.occurred_at,
      correlation_id: event.correlation_id,
    })),
  };
}

export async function getDashboard(
  signal?: AbortSignal,
): Promise<FixtureResult<DashboardFixture>> {
  const baseUrl = apiBaseUrl();
  if (!baseUrl) return fallbackFixture(dashboardFixture);
  try {
    const [dashboard, cases] = await Promise.all([
      fetchJson<LiveDashboard>(`${baseUrl}/v1/dashboard/metrics`, { signal }),
      fetchJson<LiveCaseList>(`${baseUrl}/v1/recovery-cases?limit=100`, {
        signal,
      }),
    ]);
    return { data: composeDashboard(dashboard, cases), source: "api" };
  } catch (error) {
    if (isAbortError(error)) throw error;
    return fallbackFixture(
      dashboardFixture,
      fallbackWarning(error, "Live Control Tower data"),
    );
  }
}

export async function getCaseDetail(
  caseId: string,
  signal?: AbortSignal,
): Promise<FixtureResult<CaseDetailFixture>> {
  const baseUrl = apiBaseUrl();
  if (!baseUrl) {
    return fallbackFixture(
      caseDetailFixture,
      caseDetailFixture.case.id === caseId
        ? undefined
        : `Case ${caseId} is not present in the bundled fixture; the FitBox reference case is shown.`,
    );
  }
  try {
    const encodedCaseId = encodeURIComponent(caseId);
    const [detail, timeline] = await Promise.all([
      fetchJson<LiveCaseDetail>(
        `${baseUrl}/v1/recovery-cases/${encodedCaseId}`,
        {
          signal,
        },
      ),
      fetchJson<LiveTimeline>(
        `${baseUrl}/v1/recovery-cases/${encodedCaseId}/timeline`,
        { signal },
      ),
    ]);
    return { data: composeCaseDetail(detail, timeline), source: "api" };
  } catch (error) {
    if (isAbortError(error)) throw error;
    return fallbackFixture(
      caseDetailFixture,
      `${fallbackWarning(error, `Live case ${caseId}`)} The FitBox reference case is shown.`,
    );
  }
}

export async function getPolicySettings(
  signal?: AbortSignal,
): Promise<FixtureResult<PolicySettings>> {
  const baseUrl = apiBaseUrl();
  if (!baseUrl) return fallbackFixture(dashboardFixture.policy_settings);
  try {
    const settings = await fetchJson<PolicySettings>(
      `${baseUrl}/v1/policy-settings`,
      { signal },
    );
    return { data: normalizePolicySettings(settings), source: "api" };
  } catch (error) {
    if (isAbortError(error)) throw error;
    return fallbackFixture(
      dashboardFixture.policy_settings,
      fallbackWarning(error, "Live policy settings"),
    );
  }
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

  if (!response.ok)
    throw new Error(
      await apiErrorMessage(
        response,
        `Command failed with status ${response.status}.`,
      ),
    );

  const payload = (await response.json()) as Partial<CommandResult>;
  return {
    command,
    message: payload.message ?? "Command accepted.",
    occurred_at: payload.occurred_at ?? new Date().toISOString(),
    source: "api",
    status: "ACCEPTED",
  };
}

export async function executeSafetyDisposition(
  caseId: string,
  disposition: SafetyDisposition,
): Promise<SafetyDispositionResult> {
  const baseUrl = apiBaseUrl();
  if (!baseUrl) {
    await new Promise((resolve) => window.setTimeout(resolve, 350));
    return {
      disposition,
      message: `${disposition.replaceAll("_", " ")} recorded in simulated mode. No provider action was taken.`,
      occurred_at: new Date().toISOString(),
      source: "mock",
      status: "ACCEPTED",
    };
  }

  const response = await fetch(
    `${baseUrl}/v1/recovery-cases/${encodeURIComponent(caseId)}/safety-dispositions`,
    {
      body: JSON.stringify({ disposition }),
      headers: { "Content-Type": "application/json" },
      method: "POST",
    },
  );
  if (!response.ok)
    throw new Error(
      await apiErrorMessage(
        response,
        `Safety disposition failed with status ${response.status}.`,
      ),
    );
  const payload = (await response.json()) as Partial<SafetyDispositionResult>;
  return {
    disposition,
    message: payload.message ?? "Safety disposition recorded.",
    occurred_at: payload.occurred_at ?? new Date().toISOString(),
    source: "api",
    status: "ACCEPTED",
  };
}

export async function updatePolicySettings(
  settings: PolicySettings,
): Promise<PolicySettings> {
  const baseUrl = apiBaseUrl();
  if (!baseUrl) {
    await new Promise((resolve) => window.setTimeout(resolve, 350));
    return structuredClone(settings);
  }
  const response = await fetch(`${baseUrl}/v1/policy-settings`, {
    body: JSON.stringify(settings),
    headers: { "Content-Type": "application/json" },
    method: "PUT",
  });
  if (!response.ok)
    throw new Error(
      await apiErrorMessage(
        response,
        `Policy update failed with status ${response.status}.`,
      ),
    );
  return normalizePolicySettings((await response.json()) as PolicySettings);
}
