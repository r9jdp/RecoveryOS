import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ControlTower } from "./ControlTower";

describe("ControlTower", () => {
  it("renders the deterministic dashboard fallback with explicit provenance", async () => {
    render(<ControlTower />);

    expect(
      await screen.findByRole("heading", { name: "Control Tower" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("₹1,499")).toHaveLength(2);
    expect(screen.getAllByText("Simulated").length).toBeGreaterThan(0);
    expect(
      screen.getByRole("link", { name: /REC-FITBOX-AUG-2026/i }),
    ).toHaveAttribute("href", "/cases/case_fitbox_aug_2026");
  });
});
