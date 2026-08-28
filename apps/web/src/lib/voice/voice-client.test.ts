import { afterEach, describe, expect, it, vi } from "vitest";

import { startRealVoiceContact } from "./voice-client";

afterEach(() => {
  window.sessionStorage.clear();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("hosted voice authorization", () => {
  it("uses the signed operator session and CSRF token without a raw voice token", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.recovery.test/");
    window.sessionStorage.setItem(
      "recoveryos-operator-csrf",
      "hosted-voice-csrf",
    );
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          attempt_id: "voice:case-1:request-1",
          provider: "twilio",
          status: "SUBMITTED",
          reason_code: "SUBMITTED",
          provider_call_id: "CA123",
          retry_permitted: false,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(startRealVoiceContact("case-1")).resolves.toMatchObject({
      status: "SUBMITTED",
    });

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("https://api.recovery.test/v1/voice/contacts");
    expect(init.credentials).toBe("include");
    expect(init.headers).toEqual({
      "Content-Type": "application/json",
      "X-RecoveryOS-CSRF-Token": "hosted-voice-csrf",
    });
    expect(
      Object.keys(init.headers as Record<string, string>).some((header) =>
        header.toLowerCase().includes("operator-token"),
      ),
    ).toBe(false);
  });
});
