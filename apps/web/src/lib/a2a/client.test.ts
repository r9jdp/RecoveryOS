import { afterEach, describe, expect, it, vi } from "vitest";

import {
  interpretCustomerLanguage,
  loadApprovalSummary,
  submitApprovalDecision,
} from "./client";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("customer approval capability", () => {
  it("forwards the bearer capability to summary, decision, and interpretation calls", async () => {
    const fetchMock = vi.fn().mockImplementation(
      async () =>
        new Response("{}", {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await loadApprovalSummary(
      "https://customer.example/",
      "task-1",
      "capability-token",
    );
    await submitApprovalDecision(
      "https://customer.example/",
      "task-1",
      {
        decision: "REJECT",
        merchant_id: "merchant-1",
        case_id: "case-1",
        exact_amount_paise: 149_900,
        payment_surface_reference: "inv_123",
      },
      "capability-token",
    );
    await interpretCustomerLanguage(
      "https://customer.example/",
      "task-1",
      "Why did this fail?",
      "capability-token",
    );

    expect(fetchMock).toHaveBeenCalledTimes(3);
    for (const [, init] of fetchMock.mock.calls as Array<
      [string, RequestInit]
    >) {
      expect(init.headers).toMatchObject({
        Authorization: "Bearer capability-token",
      });
    }
  });
});
