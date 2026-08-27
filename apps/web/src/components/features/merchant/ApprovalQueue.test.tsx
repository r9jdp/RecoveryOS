import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApprovalQueue } from "./ApprovalQueue";

afterEach(cleanup);

describe("ApprovalQueue", () => {
  it("filters items and confirms the exact surface before approval", async () => {
    const runApproval = vi.fn().mockResolvedValue({
      command: "APPROVE",
      message: "Approved",
      occurred_at: "2026-08-27T10:00:00Z",
      source: "mock",
      status: "ACCEPTED",
    });
    render(<ApprovalQueue runApproval={runApproval} />);

    fireEvent.change(
      screen.getByRole("searchbox", { name: "Filter approval queue" }),
      {
        target: { value: "missing customer" },
      },
    );
    expect(
      screen.getByRole("heading", { name: "No matching approvals" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Clear filter" }));
    fireEvent.click(screen.getByRole("button", { name: "Review" }));

    expect(
      screen.getByRole("alertdialog", {
        name: "Approve this recovery surface?",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/browser callback never proves payment/i),
    ).toBeInTheDocument();
    const confirm = screen.getByRole("button", {
      name: "Approve exact surface",
    });
    const cancel = screen.getByRole("button", { name: "Cancel" });
    expect(confirm).toHaveFocus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(cancel).toHaveFocus();
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(confirm).toHaveFocus();
    fireEvent.click(confirm);

    expect(
      await screen.findByRole("heading", { name: "Approval queue is clear" }),
    ).toBeInTheDocument();
    expect(runApproval).toHaveBeenCalledWith("case_fitbox_aug_2026");
  });

  it("keeps a case pending and explains a failed approval", async () => {
    render(
      <ApprovalQueue
        runApproval={vi.fn().mockRejectedValue(new Error("Policy changed"))}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    fireEvent.click(
      screen.getByRole("button", { name: "Approve exact surface" }),
    );

    expect(await screen.findByText(/Policy changed/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Review" })).toBeInTheDocument();
  });
});
