import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { CaseDetailFixture } from "@/types/recovery";

import { CaseWorkspace, customerAgentApprovalHref } from "./CaseWorkspace";

afterEach(cleanup);

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

  it("requires confirmation before persisting an opt-out safety flow", async () => {
    render(<CaseWorkspace caseId="case_fitbox_aug_2026" />);
    await screen.findByRole("heading", {
      name: /Aarav Sharma · FitBox Annual/,
    });

    fireEvent.click(screen.getByRole("button", { name: "Record opt-out" }));
    expect(
      screen.getByRole("alertdialog", {
        name: "Suppress all customer outreach?",
      }),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Confirm safety disposition" }),
    );

    expect(
      await screen.findAllByText(/MARK OPT OUT recorded in local demo mode/i),
    ).toHaveLength(2);
    expect(screen.getByText("Stopped")).toBeInTheDocument();
  });

  it("records a wrong-person disposition and updates visible contact state", async () => {
    render(<CaseWorkspace caseId="case_fitbox_aug_2026" />);
    await screen.findByRole("heading", {
      name: /Aarav Sharma · FitBox Annual/,
    });

    fireEvent.click(screen.getByRole("button", { name: "Mark wrong person" }));
    expect(
      screen.getByRole("alertdialog", {
        name: "Record a wrong-person contact?",
      }),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Confirm safety disposition" }),
    );

    expect(await screen.findByText("Wrong Person")).toBeInTheDocument();
    expect(screen.getByText("Stopped")).toBeInTheDocument();
  });

  it("uses the audited approval capability and preserves the mock task fallback", () => {
    const event = {
      id: "audit-a2a",
      event_type: "A2A_AUTHORIZATION_STARTED",
      source: "worker",
      evidence_kind: "SIMULATED" as const,
      occurred_at: "2026-09-01T00:00:00Z",
      correlation_id: "a2a-start",
      payload: {
        remote_task_id: "task:customer-1",
        approval_path: "/a2a/task%3Acustomer-1#token=capability-token",
      },
    } satisfies CaseDetailFixture["timeline"][number];

    expect(customerAgentApprovalHref([event])).toBe(
      "/a2a/task%3Acustomer-1#token=capability-token",
    );
    expect(
      customerAgentApprovalHref([
        { ...event, payload: { remote_task_id: "mock-a2a:case-1" } },
      ]),
    ).toBe("/a2a/mock-a2a%3Acase-1");
  });
});
