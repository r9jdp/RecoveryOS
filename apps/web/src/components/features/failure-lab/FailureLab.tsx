"use client";

import { useEffect, useId, useRef, useState } from "react";

import { PageHeader } from "@/components/layout";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  Input,
  MetricCard,
  Skeleton,
} from "@/components/ui";
import {
  type FailureScenario,
  type FailureSimulationRequest,
  type FailureSimulationResponse,
  runFailureSimulation,
} from "@/lib/failure-lab";
import { formatPaise, humanize } from "@/lib/recovery-format";

import styles from "./failure-lab.module.css";

interface ScenarioOption {
  id: FailureScenario;
  label: string;
  summary: string;
  contract: string;
}

const scenarios: ScenarioOption[] = [
  {
    id: "DUPLICATE_WEBHOOK",
    label: "Duplicate webhook",
    summary: "Deliver the same provider event twice with unique delivery IDs.",
    contract: "One durable effect; duplicate revenue remains impossible.",
  },
  {
    id: "OUT_OF_ORDER_WEBHOOK",
    label: "Out-of-order webhook",
    summary: "Deliver capture before an older failed-payment observation.",
    contract: "The stale failure cannot regress authoritative capture.",
  },
  {
    id: "LATE_SUCCESS",
    label: "Late payment success",
    summary: "Deliver capture after the failure has already opened recovery.",
    contract: "The case converges and recognizes recovered revenue once.",
  },
  {
    id: "CHANGED_AUTHORITATIVE_PAYMENT_STATE",
    label: "Changed payment state",
    summary: "Observe failure while the authoritative fetch reports capture.",
    contract: "Authoritative provider state wins over the stale observation.",
  },
];

export interface FailureLabProps {
  simulate?: (
    request: FailureSimulationRequest,
    signal?: AbortSignal,
  ) => Promise<FailureSimulationResponse>;
}

function Result({ result }: { result: FailureSimulationResponse }) {
  return (
    <section className={styles.results} aria-labelledby="simulation-result">
      <div className={styles.resultHeading}>
        <div>
          <p className={styles.eyebrow}>Contract rehearsal</p>
          <h2 id="simulation-result">Expected convergence</h2>
        </div>
        <Badge tone="warning" showDot>
          Projected result
        </Badge>
      </div>

      <div className={styles.metricGrid}>
        <MetricCard
          className={styles.metricCard}
          label="Final payment state"
          value={humanize(result.expected_final_payment_state)}
          delta="Authoritative state after every delivery"
        />
        <MetricCard
          className={styles.metricCard}
          label="Revenue entries"
          value={String(result.expected_revenue_entries)}
          delta="Idempotent ledger rows expected"
        />
        <MetricCard
          className={styles.metricCard}
          label="Amount under test"
          value={formatPaise(result.amount_paise)}
          delta="Transported as integer paise"
        />
      </div>

      <Alert tone="success" title="Safe expected result">
        The backend projection expects{" "}
        {humanize(result.expected_final_payment_state)} with{" "}
        {result.expected_revenue_entries} recovered-revenue{" "}
        {result.expected_revenue_entries === 1 ? "entry" : "entries"}. This lab
        produces an expected result only; it does not mutate a case or contact a
        provider.
      </Alert>

      <Card>
        <CardHeader
          title="Delivery evidence"
          description={`${result.deliveries.length} delivery${result.deliveries.length === 1 ? "" : "ies"} for ${result.case_id}. Provider and delivery identifiers remain visible for the deduplication audit.`}
          action={<Badge tone="neutral">Replay key {result.seed}</Badge>}
        />
        <CardBody>
          <ol
            className={styles.deliveryList}
            aria-label="Rehearsal delivery sequence"
          >
            {result.deliveries.map((delivery, index) => {
              const diverged =
                delivery.observed_payment_state !==
                delivery.authoritative_payment_state;
              return (
                <li className={styles.delivery} key={delivery.delivery_id}>
                  <span className={styles.deliveryIndex} aria-hidden="true">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <div className={styles.deliveryBody}>
                    <div className={styles.deliveryHeader}>
                      <div>
                        <h3>{delivery.event_type}</h3>
                        <p>
                          Delivered{" "}
                          {new Date(delivery.delivered_at).toLocaleString(
                            "en-IN",
                            { dateStyle: "medium", timeStyle: "medium" },
                          )}
                        </p>
                      </div>
                      <Badge tone="warning">Rehearsal event</Badge>
                    </div>
                    <dl className={styles.deliveryDetails}>
                      <div>
                        <dt>Provider event</dt>
                        <dd>{delivery.provider_event_id}</dd>
                      </div>
                      <div>
                        <dt>Delivery ID</dt>
                        <dd>{delivery.delivery_id}</dd>
                      </div>
                      <div>
                        <dt>Observed state</dt>
                        <dd>{humanize(delivery.observed_payment_state)}</dd>
                      </div>
                      <div>
                        <dt>Authoritative state</dt>
                        <dd>
                          {humanize(delivery.authoritative_payment_state)}
                          {diverged && (
                            <span className={styles.stateNote}>
                              Provider fetch wins
                            </span>
                          )}
                        </dd>
                      </div>
                    </dl>
                  </div>
                </li>
              );
            })}
          </ol>
        </CardBody>
      </Card>
    </section>
  );
}

export function FailureLab({
  simulate = runFailureSimulation,
}: FailureLabProps) {
  const groupHintId = useId();
  const resultRef = useRef<HTMLDivElement>(null);
  const requestRef = useRef<AbortController | null>(null);
  const [scenario, setScenario] =
    useState<FailureScenario>("DUPLICATE_WEBHOOK");
  const [seed, setSeed] = useState("20260827");
  const [amountPaise, setAmountPaise] = useState("149900");
  const [result, setResult] = useState<FailureSimulationResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(
    () => () => {
      requestRef.current?.abort();
    },
    [],
  );

  const selected = scenarios.find((item) => item.id === scenario)!;
  const parsedSeed = Number(seed);
  const parsedAmount = Number(amountPaise);
  const seedError =
    seed.length > 0 && !Number.isSafeInteger(parsedSeed)
      ? "Reproducibility key must be a whole number."
      : undefined;
  const amountError =
    amountPaise.length > 0 &&
    (!Number.isSafeInteger(parsedAmount) || parsedAmount <= 0)
      ? "Amount must be a positive whole number of paise."
      : undefined;
  const invalid = Boolean(seedError || amountError || !seed || !amountPaise);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (invalid) return;
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const next = await simulate(
        {
          scenario,
          seed: parsedSeed,
          amount_paise: parsedAmount,
          evidence_kind: "SIMULATED",
        },
        controller.signal,
      );
      if (controller.signal.aborted) return;
      setResult(next);
      requestAnimationFrame(() =>
        resultRef.current?.focus({ preventScroll: true }),
      );
    } catch (caught) {
      if (controller.signal.aborted) return;
      setError(
        caught instanceof Error
          ? caught.message
          : "The failure rehearsal could not be generated.",
      );
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }

  return (
    <div className={styles.page}>
      <PageHeader
        eyebrow="Safety verification"
        title="Failure Injection Lab"
        description="Replay edge-case delivery patterns against fixed backend safety contracts. Each run shows how RecoveryOS deduplicates events and converges to provider-authoritative state."
        action={<Badge tone="warning">Controlled rehearsal</Badge>}
      />

      <Alert tone="info" title="Rehearsal boundary">
        This lab validates processing behavior in isolation. Provider-confirmed
        payment state still comes only from validated Razorpay test-mode
        webhooks and an authoritative fetch.
      </Alert>

      <div className={styles.workspace}>
        <Card className={styles.controlsCard}>
          <CardHeader
            title="Choose a failure contract"
            description="The API returns the delivery sequence and expected convergence. The browser never decides payment state."
          />
          <CardBody>
            <form className={styles.form} onSubmit={submit}>
              <fieldset
                className={styles.scenarioFieldset}
                aria-describedby={groupHintId}
              >
                <legend>Failure scenario</legend>
                <p id={groupHintId} className={styles.fieldHint}>
                  Use arrow keys to move between scenarios.
                </p>
                <div className={styles.scenarioGrid}>
                  {scenarios.map((option) => (
                    <label className={styles.scenarioOption} key={option.id}>
                      <input
                        type="radio"
                        name="failure-scenario"
                        value={option.id}
                        checked={scenario === option.id}
                        onChange={() => setScenario(option.id)}
                      />
                      <span className={styles.scenarioContent}>
                        <strong>{option.label}</strong>
                        <span>{option.summary}</span>
                        <small>{option.contract}</small>
                      </span>
                    </label>
                  ))}
                </div>
              </fieldset>

              <div className={styles.inputGrid}>
                <Input
                  label="Reproducibility key"
                  hint="Repeating the same scenario with this key preserves IDs and timing."
                  error={seedError}
                  inputMode="numeric"
                  required
                  value={seed}
                  onChange={(event) => setSeed(event.target.value)}
                />
                <Input
                  label="Amount (paise)"
                  hint={
                    Number.isSafeInteger(parsedAmount) && parsedAmount > 0
                      ? `${formatPaise(parsedAmount)} under test`
                      : "Integer paise only."
                  }
                  error={amountError}
                  inputMode="numeric"
                  required
                  value={amountPaise}
                  onChange={(event) => setAmountPaise(event.target.value)}
                />
              </div>

              <div className={styles.selectedContract}>
                <span>Contract under test</span>
                <strong>{selected.contract}</strong>
              </div>
              <Button
                type="submit"
                loading={loading}
                disabled={invalid}
                fullWidth
              >
                Rehearse {selected.label.toLowerCase()}
              </Button>
            </form>
          </CardBody>
        </Card>

        <div className={styles.output} ref={resultRef} tabIndex={-1}>
          {loading && (
            <div
              className={styles.loading}
              aria-busy="true"
              aria-label="Generating failure rehearsal"
            >
              <Skeleton width="12rem" />
              <Skeleton height="8rem" />
              <Skeleton height="14rem" />
            </div>
          )}
          {error && (
            <Alert tone="danger" title="Rehearsal unavailable">
              {error} No fallback result is invented, so the evidence boundary
              remains explicit.
            </Alert>
          )}
          {!loading && !error && !result && (
            <EmptyState
              title="Ready for a controlled rehearsal"
              description="Choose a contract and rehearse it to inspect provider event IDs, delivery order, observed state, and authoritative convergence."
            />
          )}
          {result && <Result result={result} />}
        </div>
      </div>
    </div>
  );
}
