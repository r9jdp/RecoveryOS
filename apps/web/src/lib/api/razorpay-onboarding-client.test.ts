import { afterEach, describe, expect, it, vi } from "vitest";

import { syncRazorpayTestSubscription } from "./razorpay-onboarding-client";

const input = {
  subscription_id: "sub_test_001",
  customer_external_id: "customer-001",
  customer_display_name: "Test Customer",
  preferred_language: "en-IN",
};

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    headers: { "Content-Type": "application/json" },
    status,
  });
}

function syncResponse() {
  return {
    mode: "razorpay_test",
    merchant_id: "merchant_001",
    customer: {
      id: "customer_local_001",
      external_id: "customer-001",
      created: true,
    },
    subscription: {
      id: "subscription_local_001",
      provider_subscription_id: "sub_test_001",
      provider_plan_id: "plan_test_001",
      plan_name: "RecoveryOS Test Plan",
      amount_paise: 149900,
      currency: "INR",
      subscription_state: "ACTIVE",
      authorization_url: "https://rzp.io/i/authorization-test",
      created: true,
    },
    invoices: [
      {
        id: "invoice_local_001",
        provider_invoice_id: "inv_test_001",
        billing_cycle_key: "razorpay:inv_test_001",
        amount_paise: 149900,
        amount_paid_paise: 0,
        currency: "INR",
        invoice_state: "issued",
        payment_url: "https://rzp.io/i/invoice-test",
        created: true,
      },
    ],
  };
}

afterEach(() => {
  window.sessionStorage.clear();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("Razorpay subscription onboarding client", () => {
  it("syncs through the configured hosted API with the operator session", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.example.test/");
    vi.stubEnv("NEXT_PUBLIC_DATA_MODE", "live");
    window.sessionStorage.setItem("recoveryos-operator-csrf", "csrf-token");
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(syncResponse()));
    vi.stubGlobal("fetch", fetchMock);

    const result = await syncRazorpayTestSubscription(input);

    expect(result.subscription.provider_plan_id).toBe("plan_test_001");
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock).toHaveBeenCalledWith(
      "https://api.example.test/v1/razorpay/test-onboarding/subscriptions/sub_test_001/sync",
      expect.objectContaining({
        credentials: "include",
        method: "POST",
        headers: expect.objectContaining({
          "Content-Type": "application/json",
          "X-RecoveryOS-CSRF-Token": "csrf-token",
        }),
      }),
    );
    const request = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(JSON.parse(String(request.body))).toEqual({
      customer_external_id: "customer-001",
      customer_display_name: "Test Customer",
      preferred_language: "en-IN",
    });
  });

  it("surfaces structured API validation errors", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.example.test");
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          jsonResponse(
            { detail: [{ msg: "Subscription does not exist" }] },
            422,
          ),
        ),
    );

    await expect(syncRazorpayTestSubscription(input)).rejects.toThrow(
      "Subscription does not exist",
    );
  });

  it("rejects unsafe provider URLs instead of rendering them", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.example.test");
    const response = syncResponse();
    response.invoices[0]!.payment_url = "javascript:alert(1)";
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(response)));

    await expect(syncRazorpayTestSubscription(input)).rejects.toThrow(
      "invalid invoice 1 payment URL",
    );
  });

  it("rejects incomplete provider data instead of rendering blank values", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.example.test");
    const response = syncResponse();
    response.subscription.provider_plan_id = "";
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(response)));

    await expect(syncRazorpayTestSubscription(input)).rejects.toThrow(
      "incomplete provider data (provider plan ID)",
    );
  });
});
