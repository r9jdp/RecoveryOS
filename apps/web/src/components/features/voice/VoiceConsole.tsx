"use client";

import { useEffect, useRef, useState } from "react";

import {
  Alert,
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  Timeline,
} from "@/components/ui";
import {
  fetchVoiceTimeline,
  startRealVoiceContact,
  submitBrowserTranscript,
  type BrowserTranscriptResult,
  type StartVoiceResult,
  type VoiceTimelineItem,
} from "@/lib/voice/voice-client";
import { getDashboard } from "@/lib/api/recovery-client";

import styles from "./voice.module.css";

interface VoiceCaseOption {
  id: string;
  label: string;
  eligible: boolean;
}

async function loadLiveVoiceCases(): Promise<VoiceCaseOption[]> {
  const { data } = await getDashboard();
  return data.cases.map((item) => ({
    id: item.id,
    label: `${item.customer_display_name} · ${item.plan_name}`,
    eligible: item.case_outcome === "OPEN" && item.payment_state !== "CAPTURED",
  }));
}

interface VoiceConsoleProps {
  attemptId?: string;
  initialCases?: VoiceCaseOption[];
  initialTimeline?: VoiceTimelineItem[];
  loadCases?: () => Promise<VoiceCaseOption[]>;
  loadTimeline?: (caseId: string) => Promise<VoiceTimelineItem[]>;
  submitTranscript?: (
    attemptId: string,
    transcript: string,
  ) => Promise<BrowserTranscriptResult>;
  startCall?: (caseId: string) => Promise<StartVoiceResult>;
}

export function VoiceConsole({
  attemptId,
  initialCases,
  initialTimeline,
  loadCases = loadLiveVoiceCases,
  loadTimeline = fetchVoiceTimeline,
  submitTranscript = submitBrowserTranscript,
  startCall = startRealVoiceContact,
}: VoiceConsoleProps) {
  const [recording, setRecording] = useState(false);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [transcript, setTranscript] = useState("");
  const [result, setResult] = useState<BrowserTranscriptResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [realCallConfirmed, setRealCallConfirmed] = useState(false);
  const [callResult, setCallResult] = useState<StartVoiceResult | null>(null);
  const [cases, setCases] = useState<VoiceCaseOption[]>(initialCases ?? []);
  const [selectedCaseId, setSelectedCaseId] = useState(
    initialCases?.find((item) => item.eligible)?.id ?? "",
  );
  const [timeline, setTimeline] = useState<VoiceTimelineItem[]>(
    initialTimeline ?? [],
  );
  const [loadingCases, setLoadingCases] = useState(initialCases === undefined);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  useEffect(
    () => () => {
      if (audioUrl) URL.revokeObjectURL(audioUrl);
      recorderRef.current?.stream.getTracks().forEach((track) => track.stop());
    },
    [audioUrl],
  );

  useEffect(() => {
    if (initialCases !== undefined) return;
    let active = true;
    void loadCases()
      .then((items) => {
        if (!active) return;
        setCases(items);
        setSelectedCaseId((current) => current || items.find((item) => item.eligible)?.id || "");
      })
      .catch((reason) => {
        if (!active) return;
        setError(reason instanceof Error ? reason.message : "Recovery cases could not be loaded.");
      })
      .finally(() => {
        if (active) setLoadingCases(false);
      });
    return () => {
      active = false;
    };
  }, [initialCases, loadCases]);

  useEffect(() => {
    if (!selectedCaseId || initialTimeline !== undefined) return;
    let active = true;
    void loadTimeline(selectedCaseId)
      .then((items) => {
        if (active) setTimeline(items);
      })
      .catch((reason) => {
        if (active)
          setError(reason instanceof Error ? reason.message : "Voice history could not be loaded.");
      });
    return () => {
      active = false;
    };
  }, [initialTimeline, loadTimeline, selectedCaseId]);

  async function toggleRecording() {
    setError(null);
    if (recording) {
      recorderRef.current?.stop();
      return;
    }
    if (
      !navigator.mediaDevices?.getUserMedia ||
      typeof MediaRecorder === "undefined"
    ) {
      setError(
        "Microphone capture is unavailable. Use the text rehearsal below.",
      );
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size) chunksRef.current.push(event.data);
      };
      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, {
          type: recorder.mimeType || "audio/webm",
        });
        setAudioUrl((previous) => {
          if (previous) URL.revokeObjectURL(previous);
          return URL.createObjectURL(blob);
        });
        stream.getTracks().forEach((track) => track.stop());
        setRecording(false);
      };
      recorderRef.current = recorder;
      recorder.start();
      setRecording(true);
    } catch {
      setError(
        "Microphone permission was denied. Use the text rehearsal below.",
      );
    }
  }

  async function rehearse() {
    setSubmitting(true);
    setError(null);
    setResult(null);
    try {
      const rehearsalId =
        attemptId ?? `browser-rehearsal-${selectedCaseId || "unassigned"}`;
      setResult(await submitTranscript(rehearsalId, transcript.trim()));
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Transcript analysis failed.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  async function requestRealCall() {
    if (!selectedCaseId) return;
    setSubmitting(true);
    setError(null);
    try {
      const submitted = await startCall(selectedCaseId);
      setCallResult(submitted);
      if (initialTimeline === undefined) {
        setTimeline(await loadTimeline(selectedCaseId));
      }
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Call request failed.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className={styles.page}>
      <header className={styles.hero}>
        <div>
          <p className={styles.eyebrow}>Voice safety lab</p>
          <h1>Rehearse every intent before a real call</h1>
          <p>
            Browser audio stays local. RecoveryOS sends only the transcript you
            explicitly submit; external calls remain server-gated and
            allowlist-only.
          </p>
        </div>
        <Badge tone="info" showDot>
          Provider-gated
        </Badge>
      </header>

      <Alert tone="info" title="AI disclosure is mandatory">
        The assistant identifies itself as an AI before case details and never
        asks for card data. Opt-out, dispute, wrong-person, and already-paid
        intents end outreach immediately.
      </Alert>

      <div className={styles.grid}>
        <Card>
          <CardHeader
            title="Browser rehearsal"
            description="Record a sample, then enter its transcript for deterministic policy analysis."
            action={
              <Badge tone={recording ? "danger" : "neutral"}>
                {recording ? "Recording" : "Ready"}
              </Badge>
            }
          />
          <CardBody className={styles.stack}>
            <div className={styles.recorder} aria-live="polite">
              <span className={styles.mic} aria-hidden="true">
                {recording ? "■" : "●"}
              </span>
              <div>
                <strong>{recording ? "Listening…" : "Microphone off"}</strong>
                <small>Recording is never uploaded automatically.</small>
              </div>
              <Button
                variant={recording ? "danger" : "secondary"}
                onClick={toggleRecording}
              >
                {recording ? "Stop recording" : "Record sample"}
              </Button>
            </div>
            {audioUrl && (
              <audio
                aria-label="Recorded voice sample"
                controls
                src={audioUrl}
              />
            )}
            <label className={styles.field}>
              <span>Transcript fallback</span>
              <small>
                Enter only the words you want RecoveryOS to analyze.
              </small>
              <textarea
                value={transcript}
                onChange={(event) => setTranscript(event.target.value)}
                placeholder="Example: Please stop calling, I will pay tomorrow."
                rows={4}
              />
            </label>
            <Button
              onClick={rehearse}
              loading={submitting}
              disabled={!transcript.trim()}
            >
              Analyze transcript
            </Button>
            {result && (
              <Alert
                tone={result.contact_must_end ? "warning" : "success"}
                title={`Detected: ${result.detected_intent.replaceAll("_", " ")}`}
              >
                {result.contact_must_end
                  ? "Contact must end now; higher-risk safety intent took precedence."
                  : "The rehearsal can continue under the current policy."}
              </Alert>
            )}
            {error && (
              <Alert tone="danger" title="Voice action unavailable">
                {error}
              </Alert>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader
            title="Operator-only real call"
            description="One concurrent call, 180-second maximum, 10 calls/day, recording off."
            action={<Badge tone="warning">Guarded</Badge>}
          />
          <CardBody className={styles.stack}>
            <label className={styles.field}>
              <span>Recovery case</span>
              <small>
                Only an open, unpaid case can be submitted to the guarded call
                path.
              </small>
              <select
                aria-label="Recovery case for voice outreach"
                value={selectedCaseId}
                disabled={loadingCases}
                onChange={(event) => {
                  setSelectedCaseId(event.target.value);
                  setCallResult(null);
                  setTimeline([]);
                }}
              >
                <option value="">
                  {loadingCases ? "Loading cases…" : "Select a recovery case"}
                </option>
                {cases.map((item) => (
                  <option key={item.id} value={item.id} disabled={!item.eligible}>
                    {item.label}{item.eligible ? "" : " · not eligible"}
                  </option>
                ))}
              </select>
            </label>
            <ul className={styles.guardrails}>
              <li>Pre-consented, team-owned destinations only</li>
              <li>
                India quiet hours and global kill switch enforced server-side
              </li>
              <li>
                Uncertain Twilio submission is reconciled, never retried
                automatically
              </li>
            </ul>
            <label className={styles.confirmation}>
              <input
                type="checkbox"
                checked={realCallConfirmed}
                onChange={(event) => setRealCallConfirmed(event.target.checked)}
              />
              <span>
                I am an authorized operator using an allowlisted test number.
              </span>
            </label>
            <Button
              variant="danger"
              onClick={requestRealCall}
              disabled={!realCallConfirmed || !selectedCaseId}
              loading={submitting}
            >
              Request guarded test call
            </Button>
            {callResult && (
              <Alert
                tone={callResult.status === "SUBMITTED" ? "success" : "warning"}
                title={`Call ${callResult.status.toLowerCase()}`}
              >
                {callResult.reason_code.replaceAll("_", " ")}. Automatic retry
                is disabled.
              </Alert>
            )}
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader
          title="Voice disposition timeline"
          description="Transcript, confidence, duration, provider callbacks, and safety decisions remain auditable."
        />
        <CardBody>
          {timeline.length ? (
            <Timeline
              items={timeline.map((item) => ({
                id: item.id,
                title: item.detected_intent
                  ? item.detected_intent.replaceAll("_", " ")
                  : item.status.replaceAll("_", " "),
                timestamp: new Intl.DateTimeFormat("en-IN", {
                  dateStyle: "medium",
                  timeStyle: "short",
                }).format(new Date(item.created_at)),
                description: [
                  item.transcript,
                  item.duration_seconds === null
                    ? null
                    : `${item.duration_seconds}s call`,
                  item.confidence_basis_points === null
                    ? null
                    : `${(item.confidence_basis_points / 100).toFixed(0)}% confidence`,
                ]
                  .filter(Boolean)
                  .join(" · "),
                tone:
                  item.disposition === "OPT_OUT" || item.status === "FAILED"
                    ? "danger"
                    : item.status === "COMPLETED"
                      ? "success"
                      : "info",
              }))}
            />
          ) : (
            <p className={styles.emptyTimeline}>
              {selectedCaseId
                ? "No provider callbacks have been recorded for this case yet."
                : "Select a live recovery case to load its voice history."}
            </p>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
