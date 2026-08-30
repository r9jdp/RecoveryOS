import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ControlTower } from "./ControlTower";

afterEach(cleanup);

describe("ControlTower", () => {
  it("renders the deterministic dashboard fallback with explicit provenance", async () => {
    render(<ControlTower />);

    expect(
      await screen.findByRole("heading", { name: "Control Tower" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("₹1,499")).toHaveLength(2);
    expect(screen.getAllByText("Seeded demo data").length).toBeGreaterThan(0);
    expect(
      screen.getByRole("link", { name: /REC-FITBOX-AUG-2026/i }),
    ).toHaveAttribute("href", "/cases/case_fitbox_aug_2026");
  });

  it("filters the case table by outcome and resets an empty result", async () => {
    render(<ControlTower />);
    await screen.findByRole("heading", { name: "Control Tower" });

    fireEvent.change(
      screen.getByRole("combobox", { name: "Filter by outcome" }),
      {
        target: { value: "RECOVERED" },
      },
    );
    expect(
      screen.getByRole("heading", { name: "No matching cases" }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Clear filter" }));
    expect(
      screen.getByRole("link", { name: /REC-FITBOX-AUG-2026/i }),
    ).toBeInTheDocument();
  });
});
