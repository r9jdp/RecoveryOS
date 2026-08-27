import { afterEach, describe, expect, it, vi } from "vitest";

import {
  getCaseDetail,
  getDashboard,
  getPolicySettings,
  updatePolicySettings,
} from "./recovery-client";

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    headers: { "Content-Type": "application/json" },
    status,
  });
}

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("Recovery API live composition", () => {
  it("falls back to bundled dashboard data when configured reads fail", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.example.test");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new Error("gateway offline")),
    );

    const result = await getDashboard();

    expect(result.source).toBe("mock");
    expect(result.warning).toMatch(/gateway offline/i);
    expect(result.data.cases[0]?.id).toBe("case_fitbox_aug_2026");
  });

  it("composes Control Tower data from live metrics and cases", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.example.test/");
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({
          currency: "INR",
          diagnosis_distribution: [
            { case_count: 1, diagnosis: "AUTHENTICATION_REQUIRED" },
          ],
          evidence_kind: "RAZORPAY_TEST_VERIFIED",
          metrics: {
            active_cases: 1,
            human_review_count: 1,
            net_recovered_value_paise: 0,
            policy_blocked_actions: 0,
            recovered_cases: 0,
            recovery_rate_basis_points: 0,
            revenue_at_risk_paise: 149900,
            simulated_incremental_recovery_paise: 0,
            total_cases: 1,
            verified_recovered_revenue_paise: 0,
          },
          recent_events: [],
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          items: [
            {
              amount_at_risk_paise: 149900,
              billing_cycle_key: "2026-08",
              case_outcome: "OPEN",
              contact_disposition: "NOT_CONTACTED",
              customer_display_name: "Live Customer",
              diagnosis: "AUTHENTICATION_REQUIRED",
              failed_invoice_id: "inv_live",
              id: "case_live",
              merchant_id: "merchant_fitbox",
              payment_state: "FAILED",
              payment_surface_type: "SUBSCRIPTION_CARD_UPDATE",
              plan_name: "Live Plan",
              recommended_action: "OPEN_CUSTOMER_PAYMENT_SURFACE",
              revenue_attribution: "NONE",
              subscription_state: "PENDING",
              updated_at: "2026-08-28T10:00:00Z",
            },
          ],
          page: { has_more: false, limit: 100, next_cursor: null },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    const result = await getDashboard();

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "https://api.example.test/v1/dashboard/metrics",
      expect.any(Object),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "https://api.example.test/v1/recovery-cases?limit=100",
      expect.any(Object),
    );
    expect(result.source).toBe("api");
    expect(result.data.cases[0]?.customer_display_name).toBe("Live Customer");
    expect(result.data.evidence_kind).toBe("RAZORPAY_TEST_VERIFIED");
  });

  it("composes a live case from detail and timeline without FitBox scoring", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.example.test");
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({
          available_commands: ["STOP"],
          case: {
            amount_at_risk_paise: 250000,
            arrears_collected_paise: 0,
            billing_cycle_key: "2026-08",
            case_outcome: "OPEN",
            case_recovered: false,
            contact_disposition: "NOT_CONTACTED",
            customer_id: "customer_live",
            diagnosis: "INSUFFICIENT_FUNDS",
            failed_invoice_id: "inv_live",
            failed_payment_id: "pay_live",
            id: "case_live",
            merchant_id: "merchant_fitbox",
            opened_at: "2026-08-28T09:00:00Z",
            payment_state: "FAILED",
            recovered_at: null,
            recovery_deadline: "2026-08-31T09:00:00Z",
            revenue_attribution: "NONE",
            subscription_id: "sub_live",
            subscription_reactivated: false,
            subscription_state: "HALTED",
            updated_at: "2026-08-28T10:00:00Z",
            version: 1,
          },
          customer: {
            customer_agent_available: false,
            display_name: "Live Customer",
            id: "customer_live",
            opted_out_at: null,
            preferred_language: "English",
            voice_consent_at: null,
          },
          invoice: {
            amount_paid_paise: 0,
            amount_paise: 250000,
            billing_cycle_key: "2026-08",
            currency: "INR",
            id: "invoice_live",
            invoice_state: "issued",
            provider_invoice_id: "inv_live",
          },
          latest_action: null,
          latest_policy: null,
          payment_failure: {
            amount_paise: 250000,
            currency: "INR",
            error_code: "BAD_REQUEST_ERROR",
            error_reason: "insufficient_funds",
            error_source: "customer",
            error_step: "payment_authorization",
            id: "attempt_live",
            method: "card",
            occurred_at: "2026-08-28T09:00:00Z",
            payment_state: "FAILED",
            provider_payment_id: "pay_live",
          },
          subscription: {
            amount_paise: 250000,
            currency: "INR",
            id: "sub_live",
            plan_name: "Live Plan",
            provider_subscription_id: "sub_provider_live",
            subscription_state: "HALTED",
          },
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          items: [
            {
              case_id: "case_live",
              correlation_id: "corr_live",
              evidence_kind: "RAZORPAY_TEST_VERIFIED",
              event_type: "PAYMENT_FAILED",
              id: "event_live",
              occurred_at: "2026-08-28T09:00:00Z",
              payload: {},
              recorded_at: "2026-08-28T09:00:01Z",
              source: "razorpay",
            },
          ],
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    const result = await getCaseDetail("case_live");

    expect(result.source).toBe("api");
    expect(result.data.customer.display_name).toBe("Live Customer");
    expect(result.data.recommendation.predicted_recovery_probability).toBe(0);
    expect(result.data.recommendation.reason_codes).toEqual(["NO_LIVE_ACTION"]);
    expect(result.data.timeline[0]?.source).toBe("razorpay");
  });

  it("loads action approval settings and preserves structured API errors", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.example.test");
    const liveSettings = {
      max_contacts_per_7_days: null,
      quiet_hours_end: null,
      quiet_hours_start: null,
      recovery_kill_switch: false,
      require_approval_above_paise: null,
      require_approval_actions: ["START_VOICE"],
      timezone: "Asia/Kolkata",
      updated_at: "2026-08-28T00:00:00Z",
      version: 3,
    } as const;
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(liveSettings))
      .mockResolvedValueOnce(
        jsonResponse({ error: { message: "Policy version changed" } }, 409),
      );
    vi.stubGlobal("fetch", fetchMock);

    const read = await getPolicySettings();
    expect(read.data.require_approval_actions).toEqual(["START_VOICE"]);
    expect(read.data.quiet_hours_start).toBeNull();
    expect(read.data.max_contacts_per_7_days).toBeNull();
    expect(read.data.require_approval_above_paise).toBeNull();
    await expect(updatePolicySettings(read.data)).rejects.toThrow(
      "Policy version changed",
    );
    const sentBody = JSON.parse(
      String((fetchMock.mock.calls[1]?.[1] as RequestInit | undefined)?.body),
    ) as Record<string, unknown>;
    expect(sentBody).not.toHaveProperty("version");
    expect(sentBody).not.toHaveProperty("updated_at");
  });
});
