import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ApprovalSummary } from "@/lib/a2a/client";

import { CustomerApproval, formatPaise } from "./CustomerApproval";

afterEach(cleanup);

const summary: ApprovalSummary = {
  task_id: "task-1",
  state: "TASK_STATE_AUTH_REQUIRED",
  merchant_id: "merchant-1",
  case_id: "case-1",
  exact_amount_paise: 149900,
  currency: "INR",
  payment_surface_type: "SUBSCRIPTION_INVOICE_LINK",
  payment_surface_reference: "inv_123",
  expires_at: "2026-08-28T11:00:00Z",
  merchant_display_name: "FitBox",
  plan_name: "FitBox Annual",
  failure_explanation:
    "The payment needs customer authentication before it can continue.",
};

describe("CustomerApproval", () => {
  it("shows an accessible loading state while fetching", () => {
    render(
      <CustomerApproval
        taskId="task-1"
        customerAgentOrigin="https://customer.example"
        loadApproval={() => new Promise(() => undefined)}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "Loading secure authorization",
    );
  });

  it("requires explicit confirmation and sends the exact scope", async () => {
    const submitApproval = vi.fn().mockResolvedValue({
      id: "task-1",
      status: { state: "TASK_STATE_WORKING" },
    });
    render(
      <CustomerApproval
        taskId="task-1"
        customerAgentOrigin="https://customer.example"
        loadApproval={vi.fn().mockResolvedValue(summary)}
        submitApproval={submitApproval}
      />,
    );

    expect(
      await screen.findByRole("heading", {
        name: "Review recovery authorization",
      }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("₹1,499.00").length).toBeGreaterThan(0);
    expect(screen.getAllByText("FitBox Annual").length).toBeGreaterThan(0);
    expect(
      screen.getByText(
        "The payment needs customer authentication before it can continue.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("inv_123")).toBeInTheDocument();
    expect(
      screen.getByText(/customer agent never executes a payment/i),
    ).toBeInTheDocument();

    const approve = screen.getByRole("button", {
      name: "Approve exact surface",
    });
    expect(approve).toBeDisabled();
    fireEvent.click(
      screen.getByRole("checkbox", {
        name: /I approve this exact ₹1,499.00 payment surface/i,
      }),
    );
    expect(approve).toBeEnabled();
    fireEvent.click(approve);

    expect(
      await screen.findByRole("heading", { name: "Authorization recorded" }),
    ).toBeInTheDocument();
    expect(submitApproval).toHaveBeenCalledWith("task-1", {
      decision: "APPROVE",
      merchant_id: "merchant-1",
      case_id: "case-1",
      exact_amount_paise: 149900,
      payment_surface_reference: "inv_123",
    });
  });

  it("keeps the exact request visible when submission fails", async () => {
    render(
      <CustomerApproval
        taskId="task-1"
        customerAgentOrigin="https://customer.example"
        loadApproval={vi.fn().mockResolvedValue(summary)}
        submitApproval={vi.fn().mockRejectedValue(new Error("Request expired"))}
      />,
    );
    await screen.findByRole("heading", {
      name: "Review recovery authorization",
    });
    fireEvent.click(screen.getByRole("button", { name: "Decline" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Request expired",
    );
    expect(screen.getByText("inv_123")).toBeInTheDocument();
  });

  it("shows model interpretation without authorizing the payment surface", async () => {
    const interpretLanguage = vi.fn().mockResolvedValue({
      task_id: "task-1",
      intent: "APPROVE",
      confidence_basis_points: 9200,
      explanation: "The customer clearly wants to continue.",
      authorization_effect: "NONE",
      requires_explicit_approval: true,
      authoritative_scope: {
        merchant_id: "merchant-1",
        case_id: "case-1",
        exact_amount_paise: 149900,
        currency: "INR",
        payment_surface_type: "SUBSCRIPTION_INVOICE_LINK",
        payment_surface_reference: "inv_123",
        expires_at: "2026-08-28T11:00:00Z",
      },
    });
    const submitApproval = vi.fn();
    render(
      <CustomerApproval
        taskId="task-1"
        customerAgentOrigin="https://customer.example"
        loadApproval={vi.fn().mockResolvedValue(summary)}
        submitApproval={submitApproval}
        interpretLanguage={interpretLanguage}
      />,
    );

    const message = await screen.findByRole("textbox", {
      name: "Message for the customer agent",
    });
    fireEvent.change(message, { target: { value: "Yes, I want to continue" } });
    fireEvent.click(screen.getByRole("button", { name: "Ask customer agent" }));

    expect(await screen.findByRole("status")).toHaveTextContent(
      "The customer clearly wants to continue",
    );
    expect(
      screen.getByRole("button", { name: "Approve exact surface" }),
    ).toBeDisabled();
    expect(submitApproval).not.toHaveBeenCalled();
  });

  it("provides an error state and retry action", async () => {
    const loadApproval = vi
      .fn()
      .mockRejectedValueOnce(new Error("Task not found"))
      .mockResolvedValueOnce(summary);
    render(
      <CustomerApproval
        taskId="task-1"
        customerAgentOrigin="https://customer.example"
        loadApproval={loadApproval}
      />,
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Task not found",
    );
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(loadApproval).toHaveBeenCalledTimes(2));
    expect(
      await screen.findByRole("heading", {
        name: "Review recovery authorization",
      }),
    ).toBeInTheDocument();
  });

  it("formats paise without floating-point money arithmetic", () => {
    expect(formatPaise(100, "INR")).toBe("₹1.00");
    expect(formatPaise(10000000, "INR")).toBe("₹1,00,000.00");
    expect(formatPaise(149901, "USD")).toBe("USD 1,499.01");
  });
});
