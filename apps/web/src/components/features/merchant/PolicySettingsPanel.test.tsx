import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PolicySettingsPanel } from "./PolicySettingsPanel";

afterEach(cleanup);

describe("PolicySettingsPanel", () => {
  it("persists action-based approval requirements", async () => {
    const saveSettings = vi.fn(async (settings) => settings);
    render(<PolicySettingsPanel saveSettings={saveSettings} />);

    fireEvent.click(
      screen.getByRole("checkbox", { name: /Start voice outreach/i }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Save policy" }));
    await screen.findByText(/safeguards were saved/i);
    expect(saveSettings).toHaveBeenCalledWith(
      expect.objectContaining({ require_approval_actions: ["START_VOICE"] }),
    );
  });

  it("requires explicit confirmation before enabling the kill switch", async () => {
    const saveSettings = vi.fn(async (settings) => settings);
    render(<PolicySettingsPanel saveSettings={saveSettings} />);

    fireEvent.click(
      screen.getByRole("button", { name: "Pause all recovery actions" }),
    );
    expect(
      screen.getByRole("alertdialog", { name: "Pause all recovery actions?" }),
    ).toBeInTheDocument();
    expect(saveSettings).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", { name: "Turn on kill switch" }),
    );

    expect(
      await screen.findByText("Global kill switch is on"),
    ).toBeInTheDocument();
    expect(saveSettings).toHaveBeenCalledWith(
      expect.objectContaining({ recovery_kill_switch: true }),
    );
  });

  it("preserves active settings and exposes an API error", async () => {
    render(
      <PolicySettingsPanel
        saveSettings={vi.fn().mockRejectedValue(new Error("Version conflict"))}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Save policy" }));
    expect(await screen.findByText(/Version conflict/)).toBeInTheDocument();
    expect(screen.getByText("Recovery active")).toBeInTheDocument();
  });
});
