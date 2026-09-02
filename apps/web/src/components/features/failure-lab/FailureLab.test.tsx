import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { FailureSimulationResponse } from "@/lib/failure-lab";

import { FailureLab } from "./FailureLab";

const result: FailureSimulationResponse = {
  scenario: "OUT_OF_ORDER_WEBHOOK",
  seed: 42,
  case_id: "case_deterministic",
  payment_id: "pay_deterministic",
  amount_paise: 149_900,
  expected_final_payment_state: "CAPTURED",
  expected_revenue_entries: 1,
  deliveries: [
    {
      delivery_id: "delivery_capture",
      provider_event_id: "evt_capture",
      event_type: "payment.captured",
      occurred_at: "2026-08-27T09:45:00Z",
      delivered_at: "2026-08-27T09:45:03Z",
      observed_payment_state: "CAPTURED",
      authoritative_payment_state: "CAPTURED",
      evidence_kind: "SIMULATED",
      payload: {},
    },
    {
      delivery_id: "delivery_failure",
      provider_event_id: "evt_failure",
      event_type: "payment.failed",
      occurred_at: "2026-08-27T09:00:00Z",
      delivered_at: "2026-08-27T09:45:05Z",
      observed_payment_state: "FAILED",
      authoritative_payment_state: "CAPTURED",
      evidence_kind: "SIMULATED",
      payload: {},
    },
  ],
};

afterEach(cleanup);

describe("FailureLab", () => {
  it("exposes all failure contracts as keyboard-native radio controls", () => {
    render(<FailureLab simulate={vi.fn()} />);

    expect(
      screen.getByRole("radio", { name: /Duplicate webhook/i }),
    ).toBeChecked();
    expect(screen.getAllByRole("radio")).toHaveLength(4);
    expect(
      screen.getByText(/Provider-confirmed payment state/i),
    ).toBeInTheDocument();
  });

  it("submits integer paise for a rehearsal and renders convergence", async () => {
    const simulate = vi.fn().mockResolvedValue(result);
    render(<FailureLab simulate={simulate} />);

    fireEvent.click(
      screen.getByRole("radio", { name: /Out-of-order webhook/i }),
    );
    fireEvent.change(screen.getByLabelText(/Reproducibility key/), {
      target: { value: "42" },
    });
    fireEvent.click(
      screen.getByRole("button", {
        name: "Rehearse out-of-order webhook",
      }),
    );

    expect(
      await screen.findByRole("heading", { name: "Expected convergence" }),
    ).toBeInTheDocument();
    expect(simulate).toHaveBeenCalledWith(
      {
        scenario: "OUT_OF_ORDER_WEBHOOK",
        seed: 42,
        amount_paise: 149_900,
        evidence_kind: "SIMULATED",
      },
      expect.any(AbortSignal),
    );
    expect(screen.getByText("Provider fetch wins")).toBeInTheDocument();
    expect(screen.getAllByText("Rehearsal event").length).toBeGreaterThan(0);
    expect(screen.getByText("evt_failure")).toBeInTheDocument();
  });

  it("shows an explicit unavailable state without inventing fallback evidence", async () => {
    render(
      <FailureLab
        simulate={vi.fn().mockRejectedValue(new Error("API offline"))}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Rehearse duplicate webhook" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("API offline");
    expect(
      screen.getByText(/No fallback result is invented/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Expected convergence" }),
    ).not.toBeInTheDocument();
  });

  it("blocks non-integer paise before the API boundary", () => {
    const simulate = vi.fn();
    render(<FailureLab simulate={simulate} />);
    fireEvent.change(screen.getByLabelText(/Amount \(paise\)/), {
      target: { value: "1499.5" },
    });

    expect(screen.getByRole("alert")).toHaveTextContent(
      /positive whole number of paise/i,
    );
    expect(
      screen.getByRole("button", { name: /Rehearse duplicate webhook/i }),
    ).toBeDisabled();
    expect(simulate).not.toHaveBeenCalled();
  });
});
