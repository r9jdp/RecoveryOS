import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ControlTower } from "./ControlTower";

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_DATA_MODE", "demo");
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "");
});

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
});

describe("ControlTower", () => {
  it("renders the deterministic dashboard fallback with explicit provenance", async () => {
    render(<ControlTower />);

    expect(
      await screen.findByRole("heading", { name: "Control Tower" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("₹1,499")).toHaveLength(2);
    expect(screen.getAllByText("Workflow evidence").length).toBeGreaterThan(0);
    expect(
      screen.getByRole("link", { name: /REC-FITBOX-AUG-2026/i }),
    ).toHaveAttribute("href", "/cases/case_fitbox_aug_2026");
  });

  it("filters the case table and resets an empty result", async () => {
    render(<ControlTower />);
    await screen.findByRole("heading", { name: "Control Tower" });

    fireEvent.change(screen.getByRole("searchbox", { name: "Search cases" }), {
      target: { value: "no matching account" },
    });
    expect(screen.getByText("No matching cases")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(
      screen.getByRole("link", { name: /REC-FITBOX-AUG-2026/i }),
    ).toBeInTheDocument();
  });
});
