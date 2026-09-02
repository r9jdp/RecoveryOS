import { describe, expect, it } from "vitest";

import {
  formatBasisPoints,
  formatEvidenceKind,
  formatPaise,
  humanize,
} from "./recovery-format";

describe("recovery formatting", () => {
  it("formats integer paise without converting stored money to floating point", () => {
    expect(formatPaise(149900)).toBe("₹1,499");
    expect(formatPaise(149999)).toBe("₹1,499.99");
    expect(formatPaise(-1500)).toBe("-₹15");
  });

  it("formats basis points and enum labels", () => {
    expect(formatBasisPoints(4310)).toBe("43.10%");
    expect(humanize("SUBSCRIPTION_CARD_UPDATE")).toBe(
      "Subscription Card Update",
    );
    expect(formatEvidenceKind("SIMULATED")).toBe("Recovery evaluation");
    expect(formatEvidenceKind("SYSTEM_DERIVED")).toBe(
      "RecoveryOS system decision",
    );
    expect(formatEvidenceKind("RAZORPAY_TEST_VERIFIED")).toBe(
      "RAZORPAY TEST VERIFIED",
    );
  });
});
