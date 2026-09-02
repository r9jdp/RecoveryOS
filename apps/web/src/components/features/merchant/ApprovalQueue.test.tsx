import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApprovalQueue } from "./ApprovalQueue";

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_DATA_MODE", "demo");
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "");
});

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
});

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
      await screen.findByRole("searchbox", { name: "Filter approval queue" }),
      {
        target: { value: "missing customer" },
      },
    );
    expect(
      screen.getByRole("heading", { name: "No matching approvals" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Clear filter" }));
    fireEvent.click(await screen.findByRole("button", { name: "Review" }));

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
    await waitFor(() => expect(confirm).toHaveFocus());
    expect(cancel).toBeInTheDocument();
    // JSDOM does not perform the browser's default Tab focus movement. The
    // complete focus loop is covered by accessibility-keyboard.pw.ts.
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
    fireEvent.click(await screen.findByRole("button", { name: "Review" }));
    fireEvent.click(
      screen.getByRole("button", { name: "Approve exact surface" }),
    );

    expect(await screen.findByText(/Policy changed/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Review" })).toBeInTheDocument();
  });
});
