import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CardUpdateCheckout } from "./CardUpdateCheckout";

vi.mock("next/script", () => ({
  default: ({ onLoad }: { onLoad?: () => void }) => (
    <button type="button" onClick={onLoad}>
      load checkout
    </button>
  ),
}));

describe("CardUpdateCheckout", () => {
  it("opens Razorpay with the exact subscription card-change contract", () => {
    const open = vi.fn();
    const on = vi.fn();
    const constructor = vi.fn(function (options: Record<string, unknown>) {
      return { open, on, options };
    });
    window.Razorpay = constructor as unknown as NonNullable<Window["Razorpay"]>;

    render(
      <CardUpdateCheckout
        caseId="case_123"
        keyId="rzp_test_public"
        subscriptionId="sub_123"
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "load checkout" }));
    fireEvent.click(
      screen.getByRole("button", { name: "Open secure Checkout" }),
    );

    expect(constructor).toHaveBeenCalledWith(
      expect.objectContaining({
        key: "rzp_test_public",
        subscription_id: "sub_123",
        subscription_card_change: true,
      }),
    );
    expect(open).toHaveBeenCalledOnce();
  });

  it("does not open Checkout for an incomplete link", () => {
    render(<CardUpdateCheckout caseId="" keyId="" subscriptionId="sub_123" />);

    expect(
      screen.getByText("This card-update link is incomplete"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Loading secure Checkout" }),
    ).toBeDisabled();
  });
});
