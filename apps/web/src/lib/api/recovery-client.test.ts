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
    vi.stubEnv("NEXT_PUBLIC_DATA_MODE", "demo");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new Error("gateway offline")),
    );

    const result = await getDashboard();

    expect(result.source).toBe("mock");
    expect(result.warning).toMatch(/gateway offline/i);
    expect(result.data.cases[0]?.id).toBe("case_fitbox_aug_2026");
  });

  it("fails visibly when live dashboard reads fail", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.example.test");
    vi.stubEnv("NEXT_PUBLIC_DATA_MODE", "live");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new Error("gateway offline")),
    );

    await expect(getDashboard()).rejects.toThrow(
      "Live Control Tower data could not be loaded: gateway offline",
    );
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
          recovery_by_channel: [
            {
              case_count: 1,
              channel: "SUBSCRIPTION_CARD_UPDATE",
              recovered_paise: 149900,
            },
          ],
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
      )
      .mockResolvedValueOnce(
        jsonResponse({
          max_contacts_per_7_days: 3,
          quiet_hours_end: "09:00",
          quiet_hours_start: "20:00",
          recovery_kill_switch: false,
          require_approval_above_paise: 100000,
          require_approval_actions: ["START_VOICE"],
          timezone: "Asia/Kolkata",
          updated_at: "2026-08-28T00:00:00Z",
          version: 3,
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
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "https://api.example.test/v1/policy-settings",
      expect.any(Object),
    );
    expect(result.source).toBe("api");
    expect(result.data.cases[0]?.customer_display_name).toBe("Live Customer");
    expect(result.data.evidence_kind).toBe("RAZORPAY_TEST_VERIFIED");
    expect(result.data.policy_settings.require_approval_above_paise).toBe(
      100000,
    );
    expect(result.data.recovery_by_channel[0]).toEqual({
      case_count: 1,
      channel: "SUBSCRIPTION_CARD_UPDATE",
      recovered_paise: 149900,
    });
  });

  it("supports the deployed dashboard contract without recovery channel facts", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.example.test");
    vi.stubEnv("NEXT_PUBLIC_DATA_MODE", "live");
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(
          jsonResponse({
            currency: "INR",
            diagnosis_distribution: [],
            evidence_kind: "RAZORPAY_TEST_VERIFIED",
            metrics: {
              active_cases: 0,
              human_review_count: 0,
              net_recovered_value_paise: 0,
              policy_blocked_actions: 0,
              recovered_cases: 0,
              recovery_rate_basis_points: 0,
              revenue_at_risk_paise: 0,
              simulated_incremental_recovery_paise: 0,
              total_cases: 0,
              verified_recovered_revenue_paise: 0,
            },
            recent_events: [],
          }),
        )
        .mockResolvedValueOnce(
          jsonResponse({
            items: [],
            page: { has_more: false, limit: 100, next_cursor: null },
          }),
        )
        .mockResolvedValueOnce(
          jsonResponse({
            max_contacts_per_7_days: 3,
            quiet_hours_end: "09:00",
            quiet_hours_start: "20:00",
            recovery_kill_switch: false,
            require_approval_above_paise: 100000,
            require_approval_actions: [],
            timezone: "Asia/Kolkata",
            updated_at: "2026-08-28T00:00:00Z",
            version: 1,
          }),
        ),
    );

    const result = await getDashboard();

    expect(result.source).toBe("api");
    expect(result.data.recovery_by_channel).toHaveLength(5);
    expect(result.data.recovery_by_channel).toEqual(
      expect.arrayContaining([
        {
          case_count: 0,
          channel: "SUBSCRIPTION_CARD_UPDATE",
          recovered_paise: 0,
        },
      ]),
    );
  });

  it("composes a live case with its persisted model ranking", async () => {
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
            {
              case_id: "case_live",
              correlation_id: "corr_live",
              evidence_kind: "SIMULATED",
              event_type: "ACTION_RECOMMENDED",
              id: "event_decision",
              occurred_at: "2026-08-28T09:00:02Z",
              payload: {
                ranked_candidates: [
                  {
                    action_type: "ESCALATE_TO_HUMAN",
                    payment_surface_type: null,
                    recovery_probability: 0.61,
                    expected_recovered_paise: 152500,
                    expected_utility_paise: 151000,
                    explanation: ["Calibrated CatBoost recoverability estimate."],
                    model: {
                      name: "recoverybench-catboost",
                      version: "recoverybench.v1",
                      artifact_checksum: "checksum-1",
                      scoring_mode: "CHECKSUM_VERIFIED_MODEL",
                    },
                    policy: {
                      reason_codes: ["WITHIN_RECOVERY_WINDOW"],
                      reasons: ["The case is inside its recovery window."],
                    },
                    selected: true,
                  },
                  {
                    action_type: "STOP",
                    payment_surface_type: null,
                    recovery_probability: 0.2,
                    expected_recovered_paise: 50000,
                    expected_utility_paise: 50000,
                    explanation: [],
                    model: {
                      name: "recoverybench-catboost",
                      version: "recoverybench.v1",
                      scoring_mode: "CHECKSUM_VERIFIED_MODEL",
                    },
                    policy: { reason_codes: [], reasons: [] },
                    selected: false,
                    rejection_code: "LOWER_EXPECTED_UTILITY",
                    rejection_reason: "Lower expected utility.",
                  },
                ],
              },
              recorded_at: "2026-08-28T09:00:03Z",
              source: "decision-engine",
            },
          ],
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    const result = await getCaseDetail("case_live");

    expect(result.source).toBe("api");
    expect(result.data.customer.display_name).toBe("Live Customer");
    expect(result.data.recommendation.predicted_recovery_probability).toBe(0.61);
    expect(result.data.recommendation.model_name).toBe("recoverybench-catboost");
    expect(result.data.recommendation.scoring_mode).toBe(
      "CHECKSUM_VERIFIED_MODEL",
    );
    expect(result.data.recommendation.rejected_alternatives).toHaveLength(1);
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
