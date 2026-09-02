import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/font/google", () => ({
  IBM_Plex_Mono: () => ({ variable: "font-plex-mono" }),
  IBM_Plex_Sans: () => ({ variable: "font-plex-sans" }),
  Newsreader: () => ({ variable: "font-newsreader" }),
}));

import HomePage from "./page";

afterEach(cleanup);

describe("public RecoveryOS entry", () => {
  it("routes visitors through an anonymized recovery case", () => {
    render(<HomePage />);

    expect(
      screen.getByRole("heading", {
        level: 1,
        name: "Recover the payment. Preserve the evidence.",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Explore the recovery workspace/i }),
    ).toHaveAttribute("href", "/login");
    expect(
      screen.getByRole("link", { name: "View Control Tower" }),
    ).toHaveAttribute("href", "/dashboard");

    expect(
      screen.getByRole("heading", {
        level: 2,
        name: "Account 2847 · Annual subscription",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("RCV-2026-0842")).toBeInTheDocument();
    expect(screen.getByText("₹2,400")).toBeInTheDocument();
  });

  it("presents deterministic recovery as an accessible ordered workflow", () => {
    render(<HomePage />);

    expect(
      screen.getByRole("navigation", { name: "Public navigation" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "RecoveryOS home" }),
    ).toHaveAttribute("href", "/");
    expect(
      screen.getByText("Actions remain policy-gated and provider-verified"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Only Razorpay-confirmed payment changes recovered revenue.",
      ),
    ).toBeInTheDocument();

    const workflow = screen.getByRole("list", { name: "Recovery workflow" });
    expect(within(workflow).getAllByRole("listitem")).toHaveLength(4);

    const auditRecords = screen.getByRole("list", {
      name: "Audit record categories",
    });
    expect(within(auditRecords).getAllByRole("listitem")).toHaveLength(4);
  });
});
