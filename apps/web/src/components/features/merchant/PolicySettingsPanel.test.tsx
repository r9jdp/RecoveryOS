import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PolicySettingsPanel } from "./PolicySettingsPanel";

beforeEach(() => vi.stubEnv("NEXT_PUBLIC_DATA_MODE", "demo"));
afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
});

describe("PolicySettingsPanel", () => {
  it("persists action-based approval requirements", async () => {
    const saveSettings = vi.fn(async (settings) => settings);
    render(<PolicySettingsPanel saveSettings={saveSettings} />);

    fireEvent.click(
      await screen.findByRole("checkbox", { name: /Start voice outreach/i }),
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
      await screen.findByRole("button", {
        name: "Pause all recovery actions",
      }),
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
    fireEvent.click(
      await screen.findByRole("button", { name: "Save policy" }),
    );
    expect(await screen.findByText(/Version conflict/)).toBeInTheDocument();
    expect(screen.getByText("Recovery active")).toBeInTheDocument();
  });

  it("round-trips disabled nullable policy controls", async () => {
    const saveSettings = vi.fn(async (settings) => settings);
    render(<PolicySettingsPanel saveSettings={saveSettings} />);

    fireEvent.change(await screen.findByLabelText(/Quiet hours begin/), {
      target: { value: "" },
    });
    fireEvent.change(screen.getByLabelText(/Maximum contacts in 7 days/), {
      target: { value: "" },
    });
    fireEvent.change(
      screen.getByLabelText(/Require approval above \(paise\)/),
      {
        target: { value: "" },
      },
    );
    fireEvent.click(screen.getByRole("button", { name: "Save policy" }));

    await screen.findByText(/safeguards were saved/i);
    expect(saveSettings).toHaveBeenCalledWith(
      expect.objectContaining({
        quiet_hours_start: null,
        quiet_hours_end: null,
        max_contacts_per_7_days: null,
        require_approval_above_paise: null,
      }),
    );
  });
});
