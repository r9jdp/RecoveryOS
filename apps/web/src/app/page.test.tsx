import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import HomePage from "./page";

afterEach(cleanup);

describe("public RecoveryOS entry", () => {
  it("routes judges through the seeded mock-first FitBox demo", () => {
    render(<HomePage />);

    expect(
      screen.getByRole("heading", {
        level: 1,
        name: "From failed invoice to an auditable next action.",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Open the FitBox demo/i }),
    ).toHaveAttribute("href", "/login");
    expect(
      screen.getByRole("link", { name: "View seeded Control Tower" }),
    ).toHaveAttribute("href", "/dashboard");
    expect(
      screen.getByText("Default evidence · no external action"),
    ).toBeInTheDocument();
  });
});
