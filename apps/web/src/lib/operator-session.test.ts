import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createOperatorSession,
  operatorMutationHeaders,
} from "./operator-session";

afterEach(() => {
  window.sessionStorage.clear();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("operator session", () => {
  it("keeps fixture-only development available without an API origin", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "");
    vi.stubEnv("NEXT_PUBLIC_DATA_MODE", "demo");

    await expect(
      createOperatorSession("demo@recoveryos.dev", "recovery-demo"),
    ).resolves.toBe("fixture");
    expect(operatorMutationHeaders()).toEqual({});
  });

  it("does not invent an operator session in live mode", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "");
    vi.stubEnv("NEXT_PUBLIC_DATA_MODE", "live");

    await expect(
      createOperatorSession("demo@recoveryos.dev", "recovery-demo"),
    ).rejects.toThrow("Operator login requires NEXT_PUBLIC_API_BASE_URL");
    expect(operatorMutationHeaders()).toEqual({});
  });

  it("stores only the CSRF token while the signed session remains HttpOnly", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.example.test/");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          operator: "demo-operator",
          csrf_token: "csrf-from-api",
          expires_at_epoch: 2_000_000_000,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      createOperatorSession("demo@recoveryos.dev", "operator-password"),
    ).resolves.toBe("api");

    expect(fetchMock).toHaveBeenCalledWith(
      "https://api.example.test/v1/operator/session",
      expect.objectContaining({
        method: "POST",
        credentials: "include",
        body: JSON.stringify({
          email: "demo@recoveryos.dev",
          password: "operator-password",
        }),
      }),
    );
    expect(operatorMutationHeaders()).toEqual({
      "X-RecoveryOS-CSRF-Token": "csrf-from-api",
    });
    expect(window.sessionStorage.length).toBe(1);
  });

  it("does not invent a session when the API rejects credentials", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.example.test");
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(
            JSON.stringify({ error: { message: "Credentials rejected." } }),
            { status: 401, headers: { "Content-Type": "application/json" } },
          ),
        ),
    );

    await expect(
      createOperatorSession("demo@recoveryos.dev", "wrong"),
    ).rejects.toThrow("Credentials rejected.");
    expect(operatorMutationHeaders()).toEqual({});
  });
});
