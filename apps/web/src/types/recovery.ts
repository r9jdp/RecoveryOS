export type EvidenceKind = "SIMULATED" | "RAZORPAY_TEST_VERIFIED";

export type CaseOutcome =
  | "OPEN"
  | "RECOVERED"
  | "PARTIALLY_RECOVERED"
  | "ESCALATED"
  | "DISPUTED"
  | "STOPPED"
  | "EXPIRED";

export type PaymentState =
  "UNKNOWN" | "FAILED" | "PENDING" | "AUTHORIZED" | "CAPTURED" | "REFUNDED";

export type SubscriptionState =
  | "UNKNOWN"
  | "CREATED"
  | "AUTHENTICATED"
  | "ACTIVE"
  | "PENDING"
  | "HALTED"
  | "PAUSED"
  | "CANCELLED"
  | "COMPLETED";

export type ContactDisposition =
  | "NOT_CONTACTED"
  | "CONTACT_SCHEDULED"
  | "NO_ANSWER"
  | "BUSY"
  | "ENGAGED"
  | "PROMISE_TO_PAY"
  | "OPTED_OUT"
  | "WRONG_PERSON"
  | "DISPUTE"
  | "ALREADY_PAID";

export type RevenueAttribution =
  "NONE" | "SIMULATED" | "RAZORPAY_TEST_VERIFIED" | "VERIFIED_EXTERNAL";

export type Diagnosis =
  | "TRANSIENT_RETRYABLE"
  | "INSUFFICIENT_FUNDS"
  | "AUTHENTICATION_REQUIRED"
  | "INSTRUMENT_INVALID"
  | "MERCHANT_ERROR"
  | "RISK_OR_COMPLIANCE_BLOCK"
  | "UNKNOWN";

export type RecoveryAction =
  | "WAIT_FOR_GATEWAY_RETRY"
  | "OPEN_CUSTOMER_PAYMENT_SURFACE"
  | "START_VOICE"
  | "SEND_TO_CUSTOMER_AGENT"
  | "ESCALATE_TO_HUMAN"
  | "STOP";

export type PaymentSurfaceType =
  | "SUBSCRIPTION_CARD_UPDATE"
  | "SUBSCRIPTION_INVOICE_LINK"
  | "STANDARD_PAYMENT_LINK";

export type CaseCommand = "APPROVE" | "REJECT" | "STOP" | "ESCALATE_TO_HUMAN";

export type SafetyDisposition =
  | "MARK_DISPUTE"
  | "MARK_OPT_OUT"
  | "MARK_WRONG_PERSON"
  | "MARK_ALREADY_PAID"
  | "ESCALATE_TO_HUMAN";

export interface ApprovalItem {
  case_id: string;
  customer_display_name: string;
  plan_name: string;
  amount_at_risk_paise: number;
  recommended_action: RecoveryAction;
  payment_surface_type: PaymentSurfaceType | null;
  policy_reason: string;
  deadline: string | null;
  evidence_kind: EvidenceKind;
  provider: "RAZORPAY_TEST" | "MOCK";
}

export interface PolicySettings {
  timezone: string;
  quiet_hours_start: string | null;
  quiet_hours_end: string | null;
  max_contacts_per_7_days: number | null;
  require_approval_above_paise: number | null;
  require_approval_actions: RecoveryAction[];
  recovery_kill_switch: boolean;
}

export interface DashboardCase {
  id: string;
  merchant_id: string;
  failed_invoice_id: string;
  billing_cycle_key: string;
  customer_display_name: string;
  plan_name: string;
  amount_at_risk_paise: number;
  case_outcome: CaseOutcome;
  payment_state: PaymentState;
  subscription_state: SubscriptionState;
  contact_disposition: ContactDisposition;
  revenue_attribution: RevenueAttribution;
  diagnosis: Diagnosis;
  recommended_action: RecoveryAction;
  payment_surface_type: PaymentSurfaceType | null;
  updated_at: string;
}

export interface DashboardFixture {
  fixture_version: "screens.v1";
  screen: "/dashboard";
  evidence_kind: EvidenceKind;
  currency: "INR";
  metrics: {
    revenue_at_risk_paise: number;
    verified_recovered_revenue_paise: number;
    simulated_incremental_recovery_paise: number;
    net_recovered_value_paise: number;
    active_cases: number;
    recovery_rate_basis_points: number;
    human_review_count: number;
    policy_blocked_actions: number;
  };
  diagnosis_distribution: Array<{ diagnosis: Diagnosis; case_count: number }>;
  recovery_by_channel: Array<{
    channel: PaymentSurfaceType | "VOICE" | "CUSTOMER_AGENT";
    recovered_paise: number;
    case_count: number;
  }>;
  policy_settings: PolicySettings;
  cases: DashboardCase[];
  recent_events: Array<{
    id: string;
    case_id: string;
    event_type: string;
    occurred_at: string;
    correlation_id: string;
  }>;
}

export interface CaseDetailFixture {
  fixture_version: "screens.v1";
  screen: string;
  case: {
    id: string;
    key: {
      merchant_id: string;
      failed_invoice_id: string;
      billing_cycle_key: string;
    };
    customer_id: string;
    subscription_id: string;
    failed_payment_id: string;
    case_outcome: CaseOutcome;
    payment_state: PaymentState;
    subscription_state: SubscriptionState;
    contact_disposition: ContactDisposition;
    revenue_attribution: RevenueAttribution;
    case_recovered: boolean;
    arrears_collected_paise: number;
    subscription_reactivated: boolean;
    diagnosis: Diagnosis;
    amount_at_risk_paise: number;
    opened_at: string;
    recovery_deadline: string;
  };
  customer: {
    id: string;
    display_name: string;
    preferred_language: string;
    voice_consent: boolean;
    opted_out_at: string | null;
    customer_agent_available: boolean;
  };
  subscription: {
    id: string;
    plan_name: string;
    amount_paise: number;
    currency: "INR";
    subscription_state: SubscriptionState;
  };
  payment_failure: {
    payment_id: string;
    invoice_id: string;
    method: string;
    error_source: string;
    error_step: string;
    error_reason: string;
    occurred_at: string;
  };
  evidence: Array<{
    kind: EvidenceKind;
    field: string;
    value: string;
    source_event: string;
  }>;
  recommendation: {
    action: RecoveryAction;
    payment_surface_type: PaymentSurfaceType | null;
    predicted_recovery_probability: number;
    expected_recovered_paise: number;
    expected_utility_paise: number;
    confidence: number;
    reason_codes: string[];
    reasons: string[];
    rejected_alternatives: Array<{
      action: RecoveryAction;
      payment_surface_type?: PaymentSurfaceType;
      reason_code: string;
      reason: string;
    }>;
  };
  policy: {
    disposition: "ALLOW" | "BLOCK" | "DELAY" | "REQUIRE_MANUAL_APPROVAL";
    decision_code: string;
    reason_codes: string[];
    reasons: string[];
    policy_version: string;
  };
  payment_surface: {
    type: PaymentSurfaceType | null;
    status: string;
    provider_reference: string | null;
    customer_url: string | null;
    authoritative_payment_state: PaymentState;
    arrears_collected_paise: number;
    subscription_reactivated: boolean;
  };
  available_commands: string[];
  timeline: Array<{
    id: string;
    event_type: string;
    source: string;
    evidence_kind: EvidenceKind;
    occurred_at: string;
    correlation_id: string;
  }>;
}

export interface FixtureResult<T> {
  data: T;
  source: "api" | "mock";
  warning?: string;
}

export interface CommandResult {
  command: CaseCommand;
  status: "ACCEPTED";
  occurred_at: string;
  source: "api" | "mock";
  message: string;
}

export interface SafetyDispositionResult {
  disposition: SafetyDisposition;
  status: "ACCEPTED";
  occurred_at: string;
  source: "api" | "mock";
  message: string;
}
