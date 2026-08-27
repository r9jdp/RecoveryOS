import { afterEach, describe, expect, it, vi } from "vitest";

import { runFailureSimulation } from "./client";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("runFailureSimulation", () => {
  it("fails closed when the API origin is unavailable", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "");

    await expect(
      runFailureSimulation({
        scenario: "DUPLICATE_WEBHOOK",
        seed: 20_260_827,
        amount_paise: 149_900,
        evidence_kind: "SIMULATED",
      }),
    ).rejects.toThrow(/API is not connected/i);
  });

  it("posts a simulated-only request to the frozen endpoint", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.example.test/");
    const responseBody = {
      scenario: "DUPLICATE_WEBHOOK",
      seed: 20_260_827,
      case_id: "case_stable",
      payment_id: "pay_stable",
      amount_paise: 149_900,
      deliveries: [],
      expected_final_payment_state: "FAILED",
      expected_revenue_entries: 0,
    } as const;
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(responseBody), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      runFailureSimulation({
        scenario: "DUPLICATE_WEBHOOK",
        seed: 20_260_827,
        amount_paise: 149_900,
        evidence_kind: "SIMULATED",
      }),
    ).resolves.toEqual(responseBody);
    expect(fetchMock).toHaveBeenCalledWith(
      "https://api.example.test/v1/simulations/failure-injection",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          scenario: "DUPLICATE_WEBHOOK",
          seed: 20_260_827,
          amount_paise: 149_900,
          evidence_kind: "SIMULATED",
        }),
      }),
    );
  });
});
