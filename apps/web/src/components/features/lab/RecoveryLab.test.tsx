import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { recoveryBenchFixture } from "@/lib/lab";

import { RecoveryLabView } from "./RecoveryLab";

describe("RecoveryLabView", () => {
  it("shows the evaluation boundary and renders integrity evidence", () => {
    render(<RecoveryLabView report={recoveryBenchFixture} source="mock" />);

    expect(
      screen.getByRole("heading", { name: "RecoveryBench ML Lab" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Evaluation cohort").length).toBeGreaterThan(0);
    expect(
      screen.getByText(/isolated from the merchant ledger/i),
    ).toBeInTheDocument();
    expect(screen.getByText("recoverybench.v1")).toBeInTheDocument();
    expect(screen.getByText("240 eval cases")).toBeInTheDocument();
    expect(screen.getByRole("table")).toHaveAccessibleName(
      "RecoveryBench evaluation grouped by candidate action",
    );
    expect(screen.getByText("Wait For Gateway Retry")).toBeInTheDocument();
  });
});
