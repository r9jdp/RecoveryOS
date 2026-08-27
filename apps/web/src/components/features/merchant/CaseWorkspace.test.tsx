import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CaseWorkspace } from "./CaseWorkspace";

describe("CaseWorkspace", () => {
  it("shows evidence, policy reasoning, and a safe optimistic command result", async () => {
    render(<CaseWorkspace caseId="case_fitbox_aug_2026" />);

    expect(
      await screen.findByRole("heading", {
        name: /Aarav Sharma · FitBox Annual/,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Recommended recovery action" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Standalone collection is blocked while gateway retries are active",
      ),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Approve recovery" }));
    expect(
      screen.getByRole("button", { name: "Approve recovery" }),
    ).toBeDisabled();
    expect(
      await screen.findAllByText(
        "The command was accepted by the mock provider. No external action was taken.",
      ),
    ).toHaveLength(2);
  });
});
