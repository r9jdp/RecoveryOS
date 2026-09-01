import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { VoiceConsole } from "./VoiceConsole";

const liveCases = [{ id: "case-1", label: "Live Customer · Live Plan", eligible: true }];

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("VoiceConsole", () => {
  it("uses the text fallback and renders the safety-first result", async () => {
    const submitTranscript = vi.fn().mockResolvedValue({
      detected_intent: "OPT_OUT",
      disposition: "OPT_OUT",
      contact_must_end: true,
      suppression_persisted: true,
    });
    render(
      <VoiceConsole
        initialCases={liveCases}
        initialTimeline={[]}
        submitTranscript={submitTranscript}
      />,
    );
    fireEvent.change(screen.getByLabelText("Transcript fallback"), {
      target: { value: "Stop calling, I will pay tomorrow" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Analyze transcript" }));
    expect(await screen.findByText("Detected: OPT OUT")).toBeInTheDocument();
    expect(screen.getByText(/Contact must end now/)).toBeInTheDocument();
    expect(submitTranscript).toHaveBeenCalledWith(
      "browser-rehearsal-case-1",
      "Stop calling, I will pay tomorrow",
    );
  });

  it("keeps the real-call action gated behind explicit operator confirmation", () => {
    render(<VoiceConsole initialCases={liveCases} initialTimeline={[]} />);
    const button = screen.getByRole("button", {
      name: "Request guarded test call",
    });
    expect(button).toBeDisabled();
    fireEvent.click(
      screen.getByRole("checkbox", {
        name: /authorized operator using an allowlisted/i,
      }),
    );
    expect(button).toBeEnabled();
  });

  it("falls back accessibly when MediaRecorder is unavailable", () => {
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: undefined,
    });
    render(<VoiceConsole initialCases={liveCases} initialTimeline={[]} />);
    fireEvent.click(screen.getByRole("button", { name: "Record sample" }));
    expect(screen.getByRole("alert")).toHaveTextContent(
      /Microphone capture is unavailable/,
    );
    expect(screen.getByLabelText("Transcript fallback")).toBeInTheDocument();
  });

  it("starts and stops a local MediaRecorder without uploading audio", async () => {
    const stopTrack = vi.fn();
    const stream = {
      getTracks: () => [{ stop: stopTrack }],
    } as unknown as MediaStream;
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
    });
    class FakeMediaRecorder {
      stream = stream;
      mimeType = "audio/webm";
      ondataavailable: ((event: { data: Blob }) => void) | null = null;
      onstop: (() => void) | null = null;
      start = vi.fn();
      stop = () => {
        this.ondataavailable?.({ data: new Blob(["voice"]) });
        this.onstop?.();
      };
    }
    vi.stubGlobal("MediaRecorder", FakeMediaRecorder);
    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL: vi.fn(() => "blob:voice"),
      revokeObjectURL: vi.fn(),
    });
    render(<VoiceConsole initialCases={liveCases} initialTimeline={[]} />);
    fireEvent.click(screen.getByRole("button", { name: "Record sample" }));
    expect(
      await screen.findByRole("button", { name: "Stop recording" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Stop recording" }));
    expect(
      await screen.findByLabelText("Recorded voice sample"),
    ).toBeInTheDocument();
    expect(stopTrack).toHaveBeenCalled();
  });
});
