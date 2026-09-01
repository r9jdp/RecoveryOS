import type { components } from "./schema";
import caseDetailFixtureJson from "../../../../../packages/contracts/fixtures/case-detail.json";
import dashboardFixtureJson from "../../../../../packages/contracts/fixtures/dashboard.json";
import type {
  CaseCommand,
  CaseDetailFixture,
  CommandResult,
  ApprovalItem,
  DashboardCase,
  DashboardFixture,
  FixtureResult,
  PolicySettings,
  PaymentSurfaceType,
  RecoveryAction,
  SafetyDisposition,
  SafetyDispositionResult,
} from "@/types/recovery";
import { buildApprovalItems } from "@/lib/merchant-demo";
import { operatorMutationHeaders } from "@/lib/operator-session";
import {
  demoDataEnabled,
  recoveryApiOrigin,
  requireRecoveryApiOrigin,
} from "@/lib/runtime-config";

type ApiSchemas = components["schemas"];
type LiveDashboard = ApiSchemas["DashboardResponse"];
type LiveCaseList = ApiSchemas["CaseListResponse"];
type LiveCaseDetail = ApiSchemas["CaseDetailResponse"];
type LiveTimeline = ApiSchemas["TimelineResponse"];
type LivePolicySettings = ApiSchemas["PolicySettingsResponse"];
type LiveApprovalQueue = ApiSchemas["ApprovalQueueResponse"];

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
    credentials: "include",
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

function liveReadError(error: unknown, resource: string): Error {
  const reason =
    error instanceof Error ? error.message : "The API is unavailable.";
  return new Error(`${resource} could not be loaded: ${reason}`);
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

const recoveryActions = new Set<RecoveryAction>([
  "WAIT_FOR_GATEWAY_RETRY",
  "OPEN_CUSTOMER_PAYMENT_SURFACE",
  "START_VOICE",
  "SEND_TO_CUSTOMER_AGENT",
  "ESCALATE_TO_HUMAN",
  "STOP",
]);

const paymentSurfaces = new Set<PaymentSurfaceType>([
  "SUBSCRIPTION_CARD_UPDATE",
  "SUBSCRIPTION_INVOICE_LINK",
  "STANDARD_PAYMENT_LINK",
]);

function recoveryAction(value: unknown): RecoveryAction | null {
  return typeof value === "string" && recoveryActions.has(value as RecoveryAction)
    ? (value as RecoveryAction)
    : null;
}

function paymentSurface(value: unknown): PaymentSurfaceType | null {
  return typeof value === "string" && paymentSurfaces.has(value as PaymentSurfaceType)
    ? (value as PaymentSurfaceType)
    : null;
}

function stringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function liveRecommendationFromTimeline(timeline: LiveTimeline) {
  const event = [...timeline.items]
    .reverse()
    .find((item) => item.event_type === "ACTION_RECOMMENDED");
  if (!event || !isRecord(event.payload)) return null;
  const payload = event.payload;
  const candidates = Array.isArray(payload.ranked_candidates)
    ? payload.ranked_candidates.filter(isRecord)
    : [];
  const selected = candidates.find((candidate) => candidate.selected === true);
  if (!selected) return null;
  const action = recoveryAction(selected.action_type);
  if (!action) return null;
  const model = isRecord(selected.model)
    ? selected.model
    : isRecord(payload.selected_model)
      ? payload.selected_model
      : {};
  const policy = isRecord(selected.policy) ? selected.policy : {};
  const probability: number | null =
    typeof selected.recovery_probability === "number"
      ? selected.recovery_probability
      : null;
  const rejected = candidates.flatMap((candidate) => {
    if (candidate.selected === true) return [];
    const rejectedAction = recoveryAction(candidate.action_type);
    if (!rejectedAction) return [];
    return [
      {
        action: rejectedAction,
        payment_surface_type:
          paymentSurface(candidate.payment_surface_type) ?? undefined,
        reason_code:
          typeof candidate.rejection_code === "string"
            ? candidate.rejection_code
            : "NOT_SELECTED",
        reason:
          typeof candidate.rejection_reason === "string"
            ? candidate.rejection_reason
            : "A higher-utility policy-eligible action was selected.",
      },
    ];
  });
  const scoringMode: CaseDetailFixture["recommendation"]["scoring_mode"] =
    model.scoring_mode === "CHECKSUM_VERIFIED_MODEL" ||
    model.scoring_mode === "TRAINED_MODEL" ||
    model.scoring_mode === "CUSTOM_SCORER" ||
    model.scoring_mode === "DETERMINISTIC_FALLBACK"
      ? model.scoring_mode
      : undefined;
  return {
    action,
    payment_surface_type: paymentSurface(selected.payment_surface_type),
    predicted_recovery_probability: probability,
    expected_recovered_paise:
      typeof selected.expected_recovered_paise === "number"
        ? selected.expected_recovered_paise
        : null,
    expected_utility_paise:
      typeof selected.expected_utility_paise === "number"
        ? selected.expected_utility_paise
        : null,
    confidence: probability,
    model_name: typeof model.name === "string" ? model.name : undefined,
    model_version: typeof model.version === "string" ? model.version : undefined,
    artifact_checksum:
      typeof model.artifact_checksum === "string" || model.artifact_checksum === null
        ? model.artifact_checksum
        : undefined,
    scoring_mode: scoringMode,
    reason_codes: [
      scoringMode === "CHECKSUM_VERIFIED_MODEL" ||
      scoringMode === "TRAINED_MODEL" ||
      scoringMode === "CUSTOM_SCORER"
        ? "MODEL_MAX_POLICY_ELIGIBLE_EXPECTED_UTILITY"
        : "DETERMINISTIC_FALLBACK",
      ...stringList(policy.reason_codes),
    ],
    reasons: [...stringList(selected.explanation), ...stringList(policy.reasons)],
    rejected_alternatives: rejected,
  };
}

function normalizePolicySettings(
  settings: LivePolicySettings | PolicySettings,
): PolicySettings {
  return {
    timezone: settings.timezone,
    quiet_hours_start: settings.quiet_hours_start ?? null,
    quiet_hours_end: settings.quiet_hours_end ?? null,
    max_contacts_per_7_days: settings.max_contacts_per_7_days ?? null,
    require_approval_above_paise: settings.require_approval_above_paise ?? null,
    require_approval_actions: settings.require_approval_actions ?? [],
    recovery_kill_switch: settings.recovery_kill_switch ?? false,
  };
}

function normalizeDashboardCase(
  item: ApiSchemas["CaseSummaryResponse"],
): DashboardCase {
  return {
    id: item.id,
    merchant_id: item.merchant_id,
    failed_invoice_id: item.failed_invoice_id ?? "not-correlated",
    billing_cycle_key: item.billing_cycle_key ?? "not-correlated",
    customer_display_name: item.customer_display_name ?? "Unknown customer",
    plan_name: item.plan_name ?? "Unknown plan",
    amount_at_risk_paise: item.amount_at_risk_paise,
    case_outcome: item.case_outcome,
    payment_state: item.payment_state,
    subscription_state: item.subscription_state,
    contact_disposition: item.contact_disposition,
    revenue_attribution: item.revenue_attribution,
    diagnosis: item.diagnosis,
    recommended_action: item.recommended_action ?? "ESCALATE_TO_HUMAN",
    payment_surface_type: item.payment_surface_type ?? null,
    updated_at: item.updated_at,
  };
}

function composeDashboard(
  dashboard: LiveDashboard,
  caseList: LiveCaseList,
  policySettings: LivePolicySettings,
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
  const recoveryByChannel = Array.isArray(dashboard.recovery_by_channel)
    ? dashboard.recovery_by_channel
    : [];
  const channelFacts = new Map(
    recoveryByChannel.map((item) => [item.channel, item]),
  );
  return {
    fixture_version: "screens.v1",
    screen: "/dashboard",
    evidence_kind: dashboard.evidence_kind,
    currency: dashboard.currency,
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
    recovery_by_channel: channels.map((channel) => {
      const facts = channelFacts.get(channel);
      const matchingCases = cases.filter((item) => {
        if (channel === "VOICE") return item.recommended_action === "START_VOICE";
        if (channel === "CUSTOMER_AGENT") {
          return item.recommended_action === "SEND_TO_CUSTOMER_AGENT";
        }
        return item.payment_surface_type === channel;
      });
      return {
        channel,
        case_count: facts?.case_count ?? matchingCases.length,
        recovered_paise: facts?.recovered_paise ?? 0,
      };
    }),
    policy_settings: normalizePolicySettings(policySettings),
    cases,
    recent_events: dashboard.recent_events.map((event) => ({
      ...event,
      payload: {},
    })),
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
  const rankedRecommendation = liveRecommendationFromTimeline(timeline);
  const evidenceKind =
    timeline.items.find(
      (event) => event.evidence_kind === "RAZORPAY_TEST_VERIFIED",
    )?.evidence_kind ??
    timeline.items[0]?.evidence_kind ??
    (recoveryCase.revenue_attribution === "RAZORPAY_TEST_VERIFIED"
      ? "RAZORPAY_TEST_VERIFIED"
      : "SYSTEM_DERIVED");
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
      currency: detail.subscription.currency,
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
    recommendation: rankedRecommendation ?? {
      action: action?.action_type ?? "STOP",
      payment_surface_type: action?.payment_surface_type ?? null,
      predicted_recovery_probability: null,
      expected_recovered_paise: null,
      expected_utility_paise: null,
      confidence: null,
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
      payload: isRecord(event.payload) ? event.payload : {},
    })),
  };
}

export async function getDashboard(
  signal?: AbortSignal,
): Promise<FixtureResult<DashboardFixture>> {
  const baseUrl = recoveryApiOrigin();
  if (!baseUrl) {
    if (demoDataEnabled()) return fallbackFixture(dashboardFixture);
    return Promise.reject(
      new Error(
        "The Control Tower requires NEXT_PUBLIC_API_BASE_URL. Demo data is disabled in live mode.",
      ),
    );
  }
  try {
    const [dashboard, cases, policySettings] = await Promise.all([
      fetchJson<LiveDashboard>(`${baseUrl}/v1/dashboard/metrics`, { signal }),
      fetchJson<LiveCaseList>(`${baseUrl}/v1/recovery-cases?limit=100`, {
        signal,
      }),
      fetchJson<LivePolicySettings>(`${baseUrl}/v1/policy-settings`, { signal }),
    ]);
    return {
      data: composeDashboard(dashboard, cases, policySettings),
      source: "api",
    };
  } catch (error) {
    if (isAbortError(error)) throw error;
    if (!demoDataEnabled())
      throw liveReadError(error, "Live Control Tower data");
    return fallbackFixture(
      dashboardFixture,
      fallbackWarning(error, "Live Control Tower data"),
    );
  }
}

export async function getApprovalQueue(
  signal?: AbortSignal,
): Promise<FixtureResult<ApprovalItem[]>> {
  const baseUrl = recoveryApiOrigin();
  if (!baseUrl) {
    if (demoDataEnabled()) {
      return {
        data: buildApprovalItems(dashboardFixture),
        source: "mock",
      };
    }
    return Promise.reject(
      new Error(
        "The approval queue requires NEXT_PUBLIC_API_BASE_URL. Demo data is disabled in live mode.",
      ),
    );
  }
  try {
    const response = await fetchJson<LiveApprovalQueue>(
      `${baseUrl}/v1/approval-queue`,
      { signal },
    );
    return {
      data: response.items.map((item) => ({
        ...item,
        deadline: item.deadline,
      })),
      source: "api",
    };
  } catch (error) {
    if (isAbortError(error)) throw error;
    if (demoDataEnabled()) {
      return {
        data: buildApprovalItems(dashboardFixture),
        source: "mock",
        warning: fallbackWarning(error, "Live approval queue"),
      };
    }
    throw liveReadError(error, "Live approval queue");
  }
}

export async function getCaseDetail(
  caseId: string,
  signal?: AbortSignal,
): Promise<FixtureResult<CaseDetailFixture>> {
  const baseUrl = recoveryApiOrigin();
  if (!baseUrl) {
    if (!demoDataEnabled()) {
      return Promise.reject(
        new Error(
          "Case details require NEXT_PUBLIC_API_BASE_URL. Demo data is disabled in live mode.",
        ),
      );
    }
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
    if (!demoDataEnabled()) throw liveReadError(error, `Live case ${caseId}`);
    return fallbackFixture(
      caseDetailFixture,
      `${fallbackWarning(error, `Live case ${caseId}`)} The FitBox reference case is shown.`,
    );
  }
}

export async function getPolicySettings(
  signal?: AbortSignal,
): Promise<FixtureResult<PolicySettings>> {
  const baseUrl = recoveryApiOrigin();
  if (!baseUrl) {
    if (demoDataEnabled())
      return fallbackFixture(dashboardFixture.policy_settings);
    return Promise.reject(
      new Error(
        "Policy settings require NEXT_PUBLIC_API_BASE_URL. Demo data is disabled in live mode.",
      ),
    );
  }
  try {
    const settings = await fetchJson<PolicySettings>(
      `${baseUrl}/v1/policy-settings`,
      { signal },
    );
    return { data: normalizePolicySettings(settings), source: "api" };
  } catch (error) {
    if (isAbortError(error)) throw error;
    if (!demoDataEnabled()) throw liveReadError(error, "Live policy settings");
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
  const baseUrl = recoveryApiOrigin();
  if (!baseUrl) {
    if (!demoDataEnabled()) requireRecoveryApiOrigin("Recovery commands");
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
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        ...operatorMutationHeaders(),
      },
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
  const baseUrl = recoveryApiOrigin();
  if (!baseUrl) {
    if (!demoDataEnabled()) requireRecoveryApiOrigin("Safety dispositions");
    await new Promise((resolve) => window.setTimeout(resolve, 350));
    return {
      disposition,
      message: `${disposition.replaceAll("_", " ")} recorded in local demo mode. No provider action was taken.`,
      occurred_at: new Date().toISOString(),
      source: "mock",
      status: "ACCEPTED",
    };
  }

  const response = await fetch(
    `${baseUrl}/v1/recovery-cases/${encodeURIComponent(caseId)}/safety-dispositions`,
    {
      body: JSON.stringify({ disposition }),
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        ...operatorMutationHeaders(),
      },
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
  const baseUrl = recoveryApiOrigin();
  if (!baseUrl) {
    if (!demoDataEnabled()) requireRecoveryApiOrigin("Policy updates");
    await new Promise((resolve) => window.setTimeout(resolve, 350));
    return structuredClone(settings);
  }
  const response = await fetch(`${baseUrl}/v1/policy-settings`, {
    body: JSON.stringify(settings),
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...operatorMutationHeaders(),
    },
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
