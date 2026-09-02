import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { RazorpaySubscriptionSyncResult } from "@/lib/api/razorpay-onboarding-client";

import { RazorpaySetupPanel } from "./RazorpaySetupPanel";

const result: RazorpaySubscriptionSyncResult = {
  mode: "razorpay_test",
  merchant_id: "merchant_001",
  customer: {
    id: "customer_local_001",
    external_id: "customer-001",
    created: true,
  },
  subscription: {
    id: "subscription_local_001",
    provider_subscription_id: "sub_test_001",
    provider_plan_id: "plan_test_001",
    plan_name: "RecoveryOS Test Plan",
    amount_paise: 149900,
    currency: "INR",
    subscription_state: "ACTIVE",
    authorization_url: "https://rzp.io/i/authorization-test",
    created: true,
  },
  invoices: [
    {
      id: "invoice_local_001",
      provider_invoice_id: "inv_test_001",
      billing_cycle_key: "razorpay:inv_test_001",
      amount_paise: 149900,
      amount_paid_paise: 0,
      currency: "INR",
      invoice_state: "issued",
      payment_url: "https://rzp.io/i/invoice-test",
      created: true,
    },
  ],
};

afterEach(cleanup);

function completeForm() {
  fireEvent.change(screen.getByLabelText("Razorpay subscription ID"), {
    target: { value: "sub_test_001" },
  });
  fireEvent.change(screen.getByLabelText("Your customer reference"), {
    target: { value: "customer-001" },
  });
  fireEvent.change(screen.getByLabelText("Customer display name"), {
    target: { value: "Test Customer" },
  });
}

describe("RazorpaySetupPanel", () => {
  it("shows only the real identifiers and URLs returned by the API", async () => {
    const syncSubscription = vi.fn().mockResolvedValue(result);
    render(<RazorpaySetupPanel syncSubscription={syncSubscription} />);
    completeForm();

    fireEvent.click(
      screen.getByRole("button", { name: "Connect subscription" }),
    );

    expect(
      await screen.findByText("Razorpay subscription connected"),
    ).toBeInTheDocument();
    expect(screen.getByText("plan_test_001")).toBeInTheDocument();
    expect(screen.getByText("sub_test_001")).toBeInTheDocument();
    expect(screen.getByText("inv_test_001")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Open authorization link" }),
    ).toHaveAttribute("href", result.subscription.authorization_url);
    expect(
      screen.getByRole("button", { name: "Open invoice" }),
    ).toHaveAttribute("href", result.invoices[0]!.payment_url);
    expect(syncSubscription).toHaveBeenCalledWith(
      expect.objectContaining({ subscription_id: "sub_test_001" }),
    );
  });

  it("shows an explicit hosted API error and no fake result", async () => {
    render(
      <RazorpaySetupPanel
        syncSubscription={vi
          .fn()
          .mockRejectedValue(new Error("Razorpay subscription was not found"))}
      />,
    );
    completeForm();

    fireEvent.click(
      screen.getByRole("button", { name: "Connect subscription" }),
    );

    expect(
      await screen.findByText("Razorpay subscription was not found"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Real Razorpay Test data connected"),
    ).not.toBeInTheDocument();
  });

  it("does not submit a malformed subscription ID", () => {
    const syncSubscription = vi.fn().mockResolvedValue(result);
    render(<RazorpaySetupPanel syncSubscription={syncSubscription} />);
    completeForm();
    fireEvent.change(screen.getByLabelText("Razorpay subscription ID"), {
      target: { value: "not-a-subscription" },
    });

    expect(
      screen.getByRole("button", { name: "Connect subscription" }),
    ).toBeDisabled();
    expect(syncSubscription).not.toHaveBeenCalled();
  });
});
