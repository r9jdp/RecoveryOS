import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DemoGuide } from "./DemoGuide";

const navigation = vi.hoisted(() => ({
  pathname: "/dashboard",
  push: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => navigation.pathname,
  useRouter: () => ({ push: navigation.push }),
}));

beforeEach(() => {
  navigation.pathname = "/dashboard";
  navigation.push.mockReset();
  window.sessionStorage.clear();
});

afterEach(cleanup);

describe("DemoGuide", () => {
  it("presents a five-minute mock-only route and tracks the current stop", async () => {
    render(<DemoGuide />);

    await waitFor(() => expect(screen.getByText("1/5")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /5-min demo/i }));

    expect(
      screen.getByRole("dialog", { name: "FitBox judge route" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("External actions stay locked"),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Current stop")).toHaveLength(1);
    expect(
      screen.getByRole("link", { name: "Inspect the decision" }),
    ).toHaveAttribute("href", "/cases/case_fitbox_aug_2026");
  });

  it("resets only walkthrough progress and returns to the seeded dashboard", async () => {
    window.sessionStorage.setItem(
      "recoveryos-fitbox-demo-progress-v1",
      JSON.stringify(["control-tower", "fitbox-case"]),
    );
    render(<DemoGuide />);
    fireEvent.click(screen.getByRole("button", { name: /5-min demo/i }));
    fireEvent.click(screen.getByRole("button", { name: "Reset guided demo" }));

    expect(navigation.push).toHaveBeenCalledWith("/dashboard");
    expect(
      screen.getByText(
        "Guided demo progress reset. Case data and provider safety settings were not changed.",
      ),
    ).toBeInTheDocument();
  });
});
