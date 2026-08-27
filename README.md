# RecoveryOS

> **Interoperable AI revenue recovery for failed Razorpay subscription payments.**

RecoveryOS detects failed subscription payments, diagnoses the likely cause, selects a safe recovery action, and closes the loop through retry, a Razorpay Payment Link, a browser-based voice flow, an external customer payment agent using A2A, or human escalation.

This repository is intended for the Razorpay Buildathon **AI Revenue Recovery** track.

> [!IMPORTANT]
> RecoveryOS is a **test-mode hackathon project**. It must not process live money or contact real customers until production security, compliance, privacy, and operational reviews are completed.

---

## 1. Product summary

A subscription payment can fail because of insufficient funds, an authentication issue, an expired payment instrument, a temporary bank problem, a merchant integration problem, or customer intent.

Most systems only record that the payment failed. RecoveryOS completes the full recovery loop:

```text
Detect failure
    ↓
Diagnose root cause
    ↓
Rank safe recovery actions
    ↓
Apply merchant policies
    ↓
Execute through retry, Payment Link, voice, A2A, or human review
    ↓
Verify the final Razorpay webhook
    ↓
Stop all pending actions
    ↓
Measure recovered and incremental revenue
```

### Primary use case

The first version supports **failed subscription renewals only**.

Example:

1. A ₹1,499 subscription renewal fails.
2. RecoveryOS receives the Razorpay webhook.
3. The system diagnoses an authentication failure.
4. Automatic retry is rejected because customer action is required.
5. RecoveryOS recommends a customer-present Payment Link or an A2A handoff.
6. The customer approves and pays.
7. A verified Razorpay webhook closes the case.
8. All scheduled calls and retries are cancelled.
9. The dashboard adds ₹1,499 to verified recovered revenue.

### Core product principle

> The model recommends. The policy engine authorizes. Deterministic code executes. Razorpay webhooks confirm. The audit log records.

---

## 2. Goals and non-goals

### Goals

* Recover failed subscription payments in Razorpay test mode.
* Explain why a payment failed and why an action was selected.
* Enforce consent, retry limits, quiet hours, approval requirements, and stopping rules.
* Support normal Payment Link recovery.
* Support browser-based Hinglish/English voice recovery.
* Support a separate mock customer payment agent through A2A.
* Require a short-lived, signed, one-time recovery mandate before agent-initiated payment.
* Handle duplicate and out-of-order webhook events safely.
* Measure gross recovery, incremental recovery, and net recovered value.
* Provide a polished merchant control plane and clear customer approval experience.

### Non-goals for the first release

* Real telephony.
* Live payments.
* Loan or debt-collection workflows.
* Abandoned-cart recovery.
* B2B receivables.
* Full fraud detection.
* Full AP2 compliance.
* Autonomous discounts.
* Storing card numbers, CVV, UPI PIN, OTP, or banking credentials.
* Allowing an LLM to execute financial actions directly.

---

## 3. Actors

| Actor                  | Responsibility                                                                           |
| ---------------------- | ---------------------------------------------------------------------------------------- |
| Merchant operator      | Configures policies, reviews cases, approves sensitive actions, and monitors recovery    |
| RecoveryOS             | Diagnoses failures, ranks actions, runs workflows, and records evidence                  |
| Customer               | Pays, rejects, opts out, disputes the amount, promises to pay later, or requests support |
| Customer payment agent | Reviews an A2A recovery request and obtains customer authorization                       |
| Razorpay               | Creates the test-mode payment surface and provides authoritative payment events          |
| Human reviewer         | Handles disputes, unclear cases, merchant errors, and policy exceptions                  |

---

## 4. Complete user flow

### 4.1 Merchant setup

The merchant opens RecoveryOS and:

1. Uses a seeded demo workspace.
2. Adds Razorpay test credentials.
3. Configures:

   * Maximum payment retries.
   * Maximum voice contacts per seven days.
   * Allowed contact hours.
   * Recovery channels.
   * Cases requiring manual approval.
   * Recovery-window duration.
4. Loads seeded subscriptions and customers.
5. Optionally registers a customer A2A agent URL.

For the hackathon MVP, authentication can use one seeded merchant account. Keep `merchant_id` in all domain records so proper multi-tenancy can be added later.

### 4.2 Failure ingestion

A failure enters through either:

* A Razorpay test webhook.
* The built-in failure simulator.

The API must:

1. Read the raw request body.
2. Verify the webhook signature.
3. Read the event ID.
4. Reject or ignore a duplicate event.
5. Store the raw event and normalized fields.
6. Create or update a recovery case.
7. Start or signal the case’s Temporal workflow.
8. Append an immutable audit event.

### 4.3 Diagnosis

The diagnosis engine first uses deterministic mappings from available Razorpay error fields.

Examples:

| Diagnosis                  | Meaning                                         | Default safe direction                      |
| -------------------------- | ----------------------------------------------- | ------------------------------------------- |
| `TRANSIENT_RETRYABLE`      | Temporary issuer, network, or processor problem | Retry later                                 |
| `INSUFFICIENT_FUNDS`       | Customer may need time                          | Pay later, promise-to-pay, or delayed retry |
| `AUTHENTICATION_REQUIRED`  | OTP, 3DS, or customer-present action needed     | Payment Link or A2A                         |
| `INSTRUMENT_INVALID`       | Expired, blocked, or invalid payment method     | Ask for another method                      |
| `MERCHANT_ERROR`           | Integration or configuration problem            | Alert merchant; do not contact customer     |
| `RISK_OR_COMPLIANCE_BLOCK` | Payment cannot safely continue                  | Stop or human review                        |
| `UNKNOWN`                  | Evidence is incomplete or conflicting           | Abstain or escalate                         |

A classifier may be used only when the structured fields are missing, generic, or contradictory.

### 4.4 Action ranking

RecoveryOS can choose only from this fixed action set:

```text
RETRY_LATER
SEND_PAYMENT_LINK
START_VOICE
SEND_TO_CUSTOMER_AGENT
ESCALATE_TO_HUMAN
STOP
```

For every action, the decision service returns:

```json
{
  "action": "SEND_PAYMENT_LINK",
  "predicted_recovery_probability": 0.71,
  "expected_value_paise": 104929,
  "confidence": 0.84,
  "reasons": [
    "Customer-present authentication is required",
    "No customer contact in the previous seven days",
    "A Payment Link resolves the original authentication failure"
  ],
  "rejected_alternatives": [
    {
      "action": "RETRY_LATER",
      "reason": "The authentication problem would remain unresolved"
    }
  ]
}
```

### 4.5 Policy evaluation

The policy engine evaluates the recommendation before execution.

Minimum rules:

* Do not contact an opted-out customer.
* Do not act after verified payment success.
* Do not contact outside configured hours.
* Do not exceed retry or contact limits.
* Do not retry a hard decline using the same instrument.
* Do not offer an unapproved discount.
* Do not execute a payment without valid authorization.
* Do not accept a mandate for a different amount or merchant.
* Do not reuse a consumed mandate.
* Escalate amount disputes.
* Stop immediately for a wrong-person response.
* Stop when the recovery window expires.

Policy output:

```json
{
  "allowed": true,
  "requires_human_approval": false,
  "decision_code": "POLICY_ALLOWED",
  "reasons": [
    "Customer has voice consent",
    "Contact count is below the configured limit"
  ]
}
```

### 4.6 Channel-specific flows

#### A. Retry later

1. Workflow schedules a durable timer.
2. Before retrying, RecoveryOS rechecks:

   * Current payment status.
   * Opt-out status.
   * Retry count.
   * Recovery-window expiry.
3. If still permitted, it initiates the configured retry or sends a new payment request.
4. The system waits for the authoritative webhook.
5. On success, all other pending actions are cancelled.

#### B. Payment Link recovery

1. Backend creates a Razorpay test Payment Link.
2. The link is associated with the recovery case.
3. Customer opens the trusted Razorpay payment surface.
4. Customer completes or rejects payment.
5. RecoveryOS does not trust frontend success alone.
6. A verified success webhook marks the case `RECOVERED`.
7. Pending calls, reminders, A2A tasks, and retries are cancelled.

#### C. Browser voice recovery

The first release uses a browser-based recovery console, not a real phone call.

Flow:

1. Operator or demo customer starts a voice session.
2. Browser records audio or accepts text in fallback mode.
3. ASR produces a transcript.
4. Intent classifier predicts one of:

```text
PAY_NOW
SEND_LINK
CHANGE_METHOD
SEND_TO_AGENT
PAY_LATER
PROMISE_TO_PAY
ALREADY_PAID
AMOUNT_DISPUTE
WRONG_PERSON
OPT_OUT
REQUEST_HUMAN
UNCLEAR
```

5. Policy engine checks the proposed response.
6. RecoveryOS creates a Payment Link, starts A2A, records a promise date, escalates, or stops.
7. Sensitive payment details are never requested in the conversation.

Safety-critical intents—`OPT_OUT`, `WRONG_PERSON`, `AMOUNT_DISPUTE`, and `ALREADY_PAID`—must prefer recall and escalation over aggressive automation.

#### D. A2A recovery

Two independent services are required:

* **Recovery Agent:** exposed by RecoveryOS.
* **Mock Customer Payment Agent:** separate service and process.

Flow:

1. RecoveryOS discovers the customer agent through its Agent Card.
2. RecoveryOS sends a structured recovery task.
3. Customer agent displays:

   * Merchant.
   * Subscription.
   * Exact amount.
   * Reason.
   * Expiry.
4. Task enters an authorization-required state.
5. Customer approves, rejects, or selects pay later.
6. On approval, customer agent returns a signed Recovery Mandate.
7. RecoveryOS verifies signature, expiry, nonce, amount, merchant, case, and request hash.
8. RecoveryOS creates a Razorpay payment surface.
9. A verified webhook confirms payment.
10. The A2A task completes with a receipt.

#### E. Human escalation

Escalate when:

* The amount is disputed.
* The payment appears already paid but cannot be verified.
* Diagnosis is unknown with low confidence.
* A merchant integration error is detected.
* The customer requests a person.
* Policies conflict.
* The model abstains.
* The maximum automated attempts are exhausted.

### 4.7 Final outcomes

Terminal case states:

```text
RECOVERED
ALREADY_PAID
OPTED_OUT
DISPUTED
ESCALATED
EXHAUSTED
CANCELLED
```

`RECOVERED` is allowed only after authoritative payment verification.

---

## 5. Recovery state machine

```mermaid
stateDiagram-v2
    [*] --> AT_RISK
    AT_RISK --> DIAGNOSED
    DIAGNOSED --> ACTION_PROPOSED
    ACTION_PROPOSED --> AWAITING_APPROVAL
    ACTION_PROPOSED --> ACTION_SCHEDULED
    ACTION_PROPOSED --> AWAITING_CUSTOMER
    ACTION_PROPOSED --> AWAITING_AGENT
    AWAITING_APPROVAL --> ACTION_SCHEDULED
    AWAITING_CUSTOMER --> PAYMENT_PENDING
    AWAITING_CUSTOMER --> AWAITING_AGENT
    AWAITING_AGENT --> AWAITING_AUTHORIZATION
    AWAITING_AUTHORIZATION --> PAYMENT_PENDING
    ACTION_SCHEDULED --> PAYMENT_PENDING
    PAYMENT_PENDING --> RECOVERED
    PAYMENT_PENDING --> DIAGNOSED
    AT_RISK --> ALREADY_PAID
    AWAITING_CUSTOMER --> OPTED_OUT
    AWAITING_CUSTOMER --> DISPUTED
    DIAGNOSED --> ESCALATED
    ACTION_PROPOSED --> EXHAUSTED
    ACTION_PROPOSED --> CANCELLED
```

Store case state and action state separately. A case can have many historical actions, but only one active workflow decision at a time.

---

## 6. System architecture

```mermaid
flowchart TD
    WEB[Next.js Web App]
    API[FastAPI API]
    DB[(PostgreSQL)]
    TEMP[Temporal Service]
    WORKER[Temporal Worker]
    DECISION[Diagnosis + Decision Service]
    POLICY[Policy Engine]
    RZP[Razorpay Test APIs]
    A2AR[Recovery A2A Agent]
    A2AC[Mock Customer Agent]
    VOICE[Voice / Intent Adapter]
    SIM[RecoveryBench Simulator]

    WEB --> API
    API --> DB
    API --> TEMP
    TEMP --> WORKER
    WORKER --> DECISION
    WORKER --> POLICY
    WORKER --> RZP
    RZP --> API
    WORKER --> A2AR
    A2AR <--> A2AC
    WEB --> VOICE
    VOICE --> API
    SIM --> API
    DECISION --> DB
    POLICY --> DB
```

### Architectural boundaries

* **API layer:** HTTP, validation, authentication placeholder, webhook intake.
* **Domain layer:** case transitions, money rules, policy contracts.
* **Workflow layer:** timers, retries, waiting, signals, cancellation.
* **Adapter layer:** Razorpay, A2A, ASR, intent model, notification mock.
* **ML layer:** feature generation, training, inference, calibration, evaluation.
* **UI layer:** merchant control plane and customer experiences.

Do not call external services directly from Temporal workflow code. Put network calls and non-deterministic work in Temporal activities.

---

## 7. Recommended tech stack

| Area                    | Technology                                                             |
| ----------------------- | ---------------------------------------------------------------------- |
| Frontend                | Next.js App Router, TypeScript                                         |
| UI                      | Tailwind CSS, shadcn/ui                                                |
| Forms and validation    | React Hook Form, Zod                                                   |
| Server-state management | TanStack Query                                                         |
| Charts                  | Recharts                                                               |
| Backend                 | FastAPI, Python, Pydantic                                              |
| ORM and migrations      | SQLAlchemy 2, Alembic                                                  |
| Database                | PostgreSQL                                                             |
| Durable workflows       | Temporal Python SDK (`temporalio`)                                     |
| Payments                | Razorpay test APIs and Python SDK (`razorpay`)                         |
| A2A                     | Official Python SDK (`a2a-sdk`)                                        |
| ML                      | pandas, scikit-learn, CatBoost                                         |
| Voice ASR               | Adapter interface; AI4Bharat IndicConformer as advanced implementation |
| Hinglish intent         | Adapter interface; MuRIL fine-tuning as advanced implementation        |
| Testing                 | pytest, Playwright                                                     |
| Local infrastructure    | Docker Compose                                                         |
| Observability           | Structured JSON logs; OpenTelemetry as a stretch goal                  |

### Important implementation choice

Start with deterministic mocks behind interfaces:

```text
ASRProvider
IntentClassifier
RecoveryScorer
RazorpayGateway
CustomerAgentClient
```

This allows the full workflow to run before large models or external services are integrated.

---

## 8. Required product screens

Build three merchant screens and two customer-facing screens.

### 8.1 `/dashboard` — Recovery Control Tower

Required:

* Revenue at risk.
* Verified recovered revenue.
* Incremental recovered revenue.
* Net recovered value.
* Active cases.
* Recovery rate.
* Human-review count.
* Policy-blocked actions.
* Cases grouped by diagnosis.
* Recovery grouped by channel.
* Filterable case table.
* Recent audit events.
* Policy settings drawer or tab.

### 8.2 `/cases/[caseId]` — Recovery Case Workspace

Required:

* Customer and subscription summary.
* Payment failure fields.
* Root-cause diagnosis.
* Recovery probability.
* Recommended action.
* Reasons and rejected alternatives.
* Policy decision.
* Full event timeline.
* Voice transcript and detected intent.
* A2A task trace.
* Mandate verification state.
* Razorpay Payment Link/payment state.
* Buttons:

  * Approve.
  * Reject.
  * Retry.
  * Stop.
  * Escalate.
  * Mark dispute.

This is the main judge-facing screen.

### 8.3 `/lab` — Model and Evaluation Lab

Required:

* Generate synthetic cases.
* Select dataset size and random seed.
* Run baseline policy.
* Run RecoveryOS policy.
* Compare recovered amounts.
* Show precision, recall, F1, PR-AUC, and calibration.
* Show recovery by diagnosis and action.
* Show treatment-versus-control results.
* Inject failures:

  * Duplicate webhook.
  * Out-of-order webhook.
  * Expired mandate.
  * Replayed mandate.
  * Changed amount.
  * A2A timeout.
  * Late payment success.

### 8.4 `/recover/[caseId]/voice` — Voice Recovery Console

Required:

* Start/stop recording.
* Text-input fallback.
* Live or completed transcript.
* Detected language.
* Detected intent.
* Confidence.
* Extracted promise-to-pay date.
* Available safe actions.
* Payment Link.
* Send-to-agent.
* Human-support.
* Stop/opt-out.

### 8.5 `/agent/tasks/[taskId]` — Customer Agent Approval

Required:

* Merchant identity.
* Subscription.
* Exact amount.
* Reason for recovery.
* Authorization expiry.
* Approve.
* Reject.
* Pay later.
* Mandate-generation status.
* Payment status.
* Final receipt.

---

## 9. Suggested repository structure

```text
recovery-os/
├── apps/
│   ├── web/                       # Next.js frontend
│   ├── api/                       # FastAPI application
│   ├── worker/                    # Temporal worker entry point
│   └── customer-agent/            # Separate mock A2A customer agent
├── packages/
│   ├── domain/                    # Domain models, enums, policies
│   ├── payment-adapters/          # Razorpay and mock gateways
│   ├── a2a-adapters/              # Agent Card, task, and client logic
│   ├── voice-adapters/            # ASR and intent interfaces
│   └── shared-schemas/            # JSON Schema/OpenAPI-derived types
├── ml/
│   ├── data/                      # Generated data; large files ignored
│   ├── recovery_bench/            # Synthetic data generator
│   ├── features/
│   ├── training/
│   ├── evaluation/
│   └── artifacts/                 # Local model artifacts
├── infra/
│   ├── docker-compose.yml
│   ├── temporal/
│   └── migrations/
├── tests/
│   ├── integration/
│   ├── contract/
│   └── e2e/
├── docs/
│   ├── architecture.md
│   ├── api.md
│   └── demo-script.md
├── .env.example
├── Makefile
├── pyproject.toml
├── pnpm-workspace.yaml
└── README.md
```

A simpler structure is acceptable, but keep domain logic separate from frameworks and external adapters.

---

## 10. Minimum domain model

### `Merchant`

* `id`
* `name`
* `timezone`
* `currency`
* `policy_config`
* `created_at`

### `Customer`

* `id`
* `merchant_id`
* `display_name`
* `preferred_language`
* `voice_consent`
* `contact_preferences`
* `a2a_agent_url`
* `opted_out_at`

### `Subscription`

* `id`
* `merchant_id`
* `customer_id`
* `razorpay_subscription_id`
* `plan_name`
* `amount_paise`
* `currency`
* `status`

### `PaymentAttempt`

* `id`
* `recovery_case_id`
* `razorpay_payment_id`
* `amount_paise`
* `method`
* `status`
* `error_source`
* `error_step`
* `error_reason`
* `attempt_number`
* `occurred_at`

### `RecoveryCase`

* `id`
* `merchant_id`
* `customer_id`
* `subscription_id`
* `status`
* `diagnosis`
* `amount_at_risk_paise`
* `opened_at`
* `recovery_deadline`
* `recovered_at`
* `recovered_amount_paise`
* `experiment_group`

### `RecoveryAction`

* `id`
* `case_id`
* `action_type`
* `status`
* `scheduled_for`
* `model_probability`
* `expected_value_paise`
* `policy_decision_id`
* `external_reference`
* `created_at`
* `completed_at`

### `RecoveryEvent`

Append-only timeline event:

* `id`
* `case_id`
* `event_type`
* `source`
* `payload`
* `occurred_at`
* `correlation_id`

### `WebhookEvent`

* `event_id`
* `event_type`
* `signature_valid`
* `payload_hash`
* `processed_at`
* `processing_result`

### `PolicyDecision`

* `id`
* `case_id`
* `action_id`
* `allowed`
* `requires_human_approval`
* `decision_code`
* `reasons`
* `policy_version`

### `A2ATask`

* `id`
* `case_id`
* `remote_agent_url`
* `remote_task_id`
* `state`
* `request_payload`
* `response_payload`
* `updated_at`

### `RecoveryMandate`

* `id`
* `case_id`
* `task_id`
* `merchant_id`
* `customer_id`
* `exact_amount_paise`
* `currency`
* `allowed_action`
* `request_hash`
* `nonce`
* `issued_at`
* `expires_at`
* `signer_key_id`
* `signature`
* `consumed_at`

### `ModelPrediction`

* `id`
* `case_id`
* `model_name`
* `model_version`
* `input_hash`
* `prediction`
* `probability`
* `explanation`
* `created_at`

All monetary values must be stored as integer paise. All timestamps must be UTC.

---

## 11. API surface

The exact schemas should be generated through FastAPI/OpenAPI.

### Health and setup

```text
GET  /health
GET  /api/v1/config
POST /api/v1/demo/reset
POST /api/v1/demo/seed
```

### Razorpay and simulation

```text
POST /api/v1/webhooks/razorpay
POST /api/v1/simulations/payment-failure
POST /api/v1/simulations/payment-success
POST /api/v1/simulations/failure-injection
```

### Recovery cases

```text
GET  /api/v1/recovery-cases
GET  /api/v1/recovery-cases/{case_id}
GET  /api/v1/recovery-cases/{case_id}/timeline
POST /api/v1/recovery-cases/{case_id}/diagnose
POST /api/v1/recovery-cases/{case_id}/propose-action
POST /api/v1/recovery-cases/{case_id}/approve
POST /api/v1/recovery-cases/{case_id}/reject
POST /api/v1/recovery-cases/{case_id}/retry
POST /api/v1/recovery-cases/{case_id}/stop
POST /api/v1/recovery-cases/{case_id}/escalate
```

### Payments

```text
POST /api/v1/recovery-cases/{case_id}/payment-links
GET  /api/v1/recovery-cases/{case_id}/payment-status
```

### Voice

```text
POST /api/v1/voice/sessions
POST /api/v1/voice/sessions/{session_id}/audio
POST /api/v1/voice/sessions/{session_id}/text
GET  /api/v1/voice/sessions/{session_id}
```

### A2A

```text
GET  /.well-known/agent-card.json
POST /api/v1/a2a/recovery-tasks
GET  /api/v1/a2a/recovery-tasks/{task_id}
POST /api/v1/a2a/recovery-tasks/{task_id}/mandates
```

The customer-agent service must expose its own Agent Card and task endpoint on a separate port or origin.

### Metrics and evaluation

```text
GET  /api/v1/metrics/overview
GET  /api/v1/metrics/recovery
POST /api/v1/experiments/run
GET  /api/v1/experiments/{experiment_id}
```

---

## 12. Temporal workflow design

Create one durable workflow per recovery case.

### Workflow ID

```text
recovery-case:{case_id}
```

### Signals

```text
payment_event
customer_intent
human_decision
a2a_task_update
mandate_received
customer_opt_out
cancel_case
```

### Queries

```text
current_state
active_action
next_scheduled_action
case_summary
```

### Activities

```text
normalize_payment_event
diagnose_failure
score_recovery_actions
evaluate_policy
create_payment_link
start_voice_session
send_a2a_task
verify_recovery_mandate
fetch_authoritative_payment_status
persist_audit_event
calculate_case_metrics
```

### Workflow rules

* Workflow code must remain deterministic.
* All external API calls must occur inside activities.
* Every activity must have explicit timeout and retry policy.
* Payment-creation activities must use an application-level idempotency key.
* Success signals cancel outstanding timers and pending actions.
* Duplicate signals must not create duplicate financial or contact actions.

---

## 13. A2A and Recovery Mandate

Use the official A2A Python SDK for the Recovery Agent and mock Customer Agent.

### Recovery Agent skills

```text
review_failed_subscription
offer_recovery_options
request_payment_authorization
create_recovery_payment
report_recovery_status
```

### Customer Agent skills

```text
review_payment_request
request_user_authorization
approve_exact_payment
reject_payment
promise_to_pay
```

### Recovery Mandate example

```json
{
  "mandate_id": "mandate_738",
  "case_id": "case_902",
  "task_id": "task_441",
  "merchant_id": "merchant_fitbox",
  "customer_id": "customer_772",
  "exact_amount_paise": 149900,
  "currency": "INR",
  "allowed_action": "ONE_TIME_RECOVERY_PAYMENT",
  "request_hash": "sha256:...",
  "nonce": "random-one-time-value",
  "issued_at": "2026-08-27T10:00:00Z",
  "expires_at": "2026-08-27T10:10:00Z",
  "signer_key_id": "customer-agent-key-1",
  "signature": "base64..."
}
```

Use Ed25519 signatures for the hackathon implementation.

Reject a mandate when:

* Signature is invalid.
* It is expired.
* The nonce was already consumed.
* Amount or currency changed.
* Merchant, customer, case, or task does not match.
* Request hash differs.
* Action is not permitted by policy.
* The case is already recovered or closed.

Describe this as an **AP2-inspired bounded recovery mandate**, not full AP2 compliance.

---

## 14. Decision and ML plan

### Stage 1: deterministic MVP

Implement first:

* Error-to-diagnosis rule map.
* Heuristic action ranking.
* Policy engine.
* Deterministic synthetic customer simulator.
* Fixed-seed evaluation.

This stage must complete the full payment loop before model training begins.

### Stage 2: recoverability model

Train a calibrated CatBoost classifier:

```text
Target: recovered within 72 hours
```

Candidate features:

* Amount.
* Payment method.
* Error source, step, and reason.
* Attempt number.
* Subscription age.
* Previous payment success rate.
* Previous failures.
* Hours since failure.
* Contacts in the previous seven days.
* Preferred language.
* Voice consent.
* Customer-agent availability.
* Last recovery action.
* Time since last contact.

Report:

* PR-AUC.
* Brier score.
* Calibration plot.
* Top-decile lift.
* Amount-weighted lift.

### Stage 3: action-effect models

Train one calibrated outcome model per action:

```text
P(recovery | case features, action)
```

Calculate:

```text
Expected utility
= probability of incremental recovery × amount
- action cost
- customer-friction penalty
- risk penalty
```

The policy engine still has final authority.

### Stage 4: voice intent

Initial implementation:

* Text-input fallback.
* Rule-based intent adapter.
* Confidence threshold and `UNCLEAR` state.

Advanced implementation:

* IndicConformer ASR.
* Fine-tuned MuRIL intent classifier.
* Promise-to-pay date and amount extraction.
* Evaluation on clean and noisy Hinglish/English speech.

### RecoveryBench synthetic data

Create a deterministic synthetic dataset generator with hidden customer states:

```text
TEMPORARY_LIQUIDITY_PROBLEM
EXPIRED_PAYMENT_METHOD
AUTHENTICATION_PROBLEM
TEMPORARY_BANK_FAILURE
BUYER_REMORSE
FORGOTTEN_RENEWAL
AMOUNT_DISPUTE
ALREADY_PAID_ELSEWHERE
MERCHANT_TECHNICAL_ERROR
```

Each hidden state must respond differently to each action. Do not use an LLM to create financial outcome labels.

---

## 15. Recovery metrics

### Business metrics

```text
Gross recovered revenue
Incremental recovered revenue
Net recovered value
Revenue still at risk
Recovery rate
Time to recovery
Contacts per recovered payment
Opt-out rate
Complaint rate
Human-review rate
```

Definitions:

```text
Incremental recovered revenue
= treatment recovered revenue - baseline recovered revenue
```

```text
Net recovered value
= incremental recovered revenue - intervention costs
```

### Safety and reliability metrics

```text
Duplicate financial actions
Policy violation count
Mandate replay rejection rate
Changed-amount rejection rate
Webhook deduplication rate
Audit-log completeness
A2A timeout recovery rate
```

### Model metrics

```text
Diagnosis macro F1
Safety-critical intent recall
Recoverability PR-AUC
Brier score
Calibration error
Recovery lift
Amount-weighted lift
```

---

## 16. Security and correctness requirements

* Use Razorpay **test mode only**.
* Verify webhook signatures using the raw body.
* Store and deduplicate the Razorpay event ID.
* Expect duplicate and out-of-order webhook delivery.
* Treat a verified backend webhook or authoritative API status as payment truth.
* Never store card number, CVV, UPI PIN, OTP, or banking password.
* Store money as integer paise.
* Use application idempotency keys for every external action.
* Encrypt secrets and never expose them to the browser.
* Do not log secrets or full sensitive payloads.
* Sign recovery mandates and consume each nonce once.
* Add rate limits to public webhook, voice, and A2A endpoints.
* Keep an append-only recovery event timeline.
* Version policies and model artifacts.
* Require manual review for disputes and low-confidence cases.
* Provide a kill switch that blocks all new recovery actions.
* Add `DEMO_MODE` and `RAZORPAY_TEST_MODE_REQUIRED` safeguards.

---

## 17. Environment variables

Create `.env.example` with at least:

```bash
# Application
APP_ENV=development
DEMO_MODE=true
API_HOST=0.0.0.0
API_PORT=8000
WEB_ORIGIN=http://localhost:3000
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000

# Database
DATABASE_URL=postgresql+psycopg://recovery:recovery@localhost:5432/recovery_os

# Temporal
TEMPORAL_ADDRESS=localhost:7233
TEMPORAL_NAMESPACE=default
TEMPORAL_TASK_QUEUE=recovery-os

# Razorpay test mode
RAZORPAY_KEY_ID=
RAZORPAY_KEY_SECRET=
RAZORPAY_WEBHOOK_SECRET=
RAZORPAY_TEST_MODE_REQUIRED=true

# A2A
RECOVERY_AGENT_BASE_URL=http://localhost:8000
CUSTOMER_AGENT_BASE_URL=http://localhost:8010
MANDATE_SIGNING_PRIVATE_KEY=
MANDATE_VERIFY_PUBLIC_KEY=
MANDATE_KEY_ID=customer-agent-key-1

# Models
MODEL_DIR=./ml/artifacts
RECOVERY_MODEL_VERSION=rules-v1
INTENT_MODEL_VERSION=rules-v1

# Optional LLM wording adapter
LLM_PROVIDER=mock
LLM_API_KEY=

# Logging
LOG_LEVEL=INFO
```

Never commit real secrets.

---

## 18. Local development

### Prerequisites

* A currently supported Node.js LTS release.
* Python 3.12 or newer.
* `pnpm`.
* Docker with Docker Compose.
* Razorpay test credentials.

### Expected commands

The coding agent should implement these root commands:

```bash
make bootstrap      # install JS and Python dependencies
make infra          # start PostgreSQL, Temporal, and Temporal UI
make migrate        # apply Alembic migrations
make seed           # create demo merchant, customers, and subscriptions
make dev            # run web, API, worker, and customer agent
make test           # run unit and integration tests
make e2e            # run Playwright
make generate-data  # generate RecoveryBench
make train           # train CatBoost models
make evaluate       # generate evaluation report
make reset           # clear and reseed local data
```

Suggested development URLs:

```text
Web app:             http://localhost:3000
API docs:            http://localhost:8000/docs
Recovery Agent Card: http://localhost:8000/.well-known/agent-card.json
Customer Agent:      http://localhost:8010
Temporal UI:         http://localhost:8233
```

---

## 19. Testing strategy

### Unit tests

* Diagnosis mappings.
* Policy rules.
* State transitions.
* Expected-value calculation.
* Money arithmetic.
* Recovery Mandate signing and verification.
* Nonce replay prevention.
* Webhook deduplication.
* Model feature generation.

### Integration tests

* Failure webhook creates one case.
* Duplicate webhook does not create a second case.
* Case workflow survives API restart.
* Payment Link adapter stores external reference.
* Success webhook closes the workflow.
* Success cancels scheduled actions.
* Expired mandate is rejected.
* A2A timeout activates fallback.

### Contract tests

* Recovery Agent Card is valid.
* Customer Agent Card is valid.
* A2A task payloads conform to selected SDK schemas.
* OpenAPI schemas remain compatible with the frontend client.

### End-to-end tests

* Seed failure → view case → approve Payment Link → simulate success → verify dashboard.
* Voice text fallback → `SEND_TO_AGENT` → customer approval → mandate → payment success.
* Amount dispute → automation blocked → human escalation.
* Opt-out → all future actions cancelled.
* Duplicate success event → recovered amount counted once.

---

## 20. Failure demonstrations

The completed project must provide one-click failure injection for:

### Duplicate webhook

Expected:

```text
First event processed
Second event marked DUPLICATE_EVENT_IGNORED
No duplicate revenue
No duplicate action
```

### Out-of-order webhook

Expected:

* State converges to authoritative payment status.
* Invalid backwards transition is not applied.
* Event remains visible in the audit timeline.

### Replayed mandate

Expected:

* First valid use consumes the nonce.
* Second use is rejected.
* No second payment request is created.

### Changed amount

Expected:

* Request hash or amount check fails.
* Payment is blocked.
* Fresh approval is required.

### Customer opt-out

Expected:

* Scheduled contacts are cancelled.
* New contact actions are blocked.
* Case becomes `OPTED_OUT`.

### A2A agent timeout

Expected:

* Task records timeout.
* RecoveryOS offers Payment Link or human fallback.
* Case does not remain stuck.

### Late payment success

Expected:

* Pending retries and outreach are cancelled.
* Case closes once.
* Recovery amount is counted once.

---

## 21. Development order

Do not start with large ML models or A2A. Complete each phase before moving forward.

### Phase 0 — Scaffolding

* Create monorepo.
* Add Next.js, FastAPI, PostgreSQL, Temporal, and Docker Compose.
* Add shared enums and schemas.
* Add CI for linting and tests.

### Phase 1 — Core recovery loop

* Seed merchant, customer, subscription, and failed payment.
* Create recovery case.
* Implement diagnosis rules.
* Implement policy engine.
* Start Temporal workflow.
* Create mock/Razorpay Payment Link.
* Process success webhook.
* Close case and cancel pending work.
* Implement duplicate webhook protection.

**Phase 1 acceptance:** a failed subscription becomes a verified recovered case end to end.

### Phase 2 — Merchant product

* Build Control Tower.
* Build Case Workspace.
* Build timeline.
* Add policy settings.
* Add human approval and escalation.

### Phase 3 — RecoveryBench and ML

* Generate deterministic synthetic data.
* Implement baseline policy.
* Train calibrated CatBoost model.
* Add action ranking and explanations.
* Build Evaluation Lab.

### Phase 4 — Voice

* Build browser voice screen.
* Add text fallback.
* Add intent adapter.
* Add promise-to-pay and opt-out flows.
* Integrate ASR/model later without changing domain contracts.

### Phase 5 — A2A

* Build separate customer-agent service.
* Publish both Agent Cards.
* Add task lifecycle.
* Add customer approval screen.
* Add signed one-time Recovery Mandate.
* Complete payment and receipt flow.

### Phase 6 — Hardening and demo

* Add all failure injections.
* Add E2E tests.
* Improve loading, empty, error, and recovery states.
* Add demo seed and reset button.
* Record benchmark results.
* Prepare five-minute demo.

---

## 22. MVP acceptance criteria

The MVP is complete when all statements below are true:

* [ ] A simulated or Razorpay test failure creates exactly one recovery case.
* [ ] The case receives an explainable diagnosis.
* [ ] RecoveryOS recommends one bounded action.
* [ ] The policy engine can allow, block, or require approval.
* [ ] A test Payment Link can be created.
* [ ] A verified success event marks the case recovered.
* [ ] Pending actions are cancelled after success.
* [ ] Duplicate webhooks do not duplicate state or revenue.
* [ ] The Control Tower and Case Workspace are functional.
* [ ] Every case has a complete audit timeline.
* [ ] At least 100 synthetic cases can be processed as a batch.
* [ ] Baseline and RecoveryOS results can be compared.

The full hackathon version is complete when:

* [ ] Browser voice recovery handles all defined intents.
* [ ] A separate A2A customer agent can approve or reject a task.
* [ ] A signed mandate is verified and cannot be replayed.
* [ ] The Evaluation Lab injects all required failure cases.
* [ ] Incremental and net recovered value are displayed.
* [ ] The demo can run from a single reset-and-seed command.

---

## 23. Demo scenario

Use this default seeded scenario:

```text
Merchant: FitBox
Customer: Aarav
Subscription: Pro Fitness Plan
Amount: ₹1,499
Failure: incorrect OTP / authentication required
Preferred language: Hinglish
Voice consent: yes
Customer A2A agent: available
```

Demo:

1. Open Control Tower and show ₹1,499 at risk.
2. Open the case.
3. Show diagnosis: customer-present authentication required.
4. Show why silent retry was rejected.
5. Start browser voice flow.
6. Enter or speak: “Mere payment agent ko request bhej do.”
7. Show `SEND_TO_AGENT`.
8. Open A2A trace.
9. Approve exact ₹1,499 in the customer-agent screen.
10. Show signed mandate verification.
11. Create Razorpay test payment.
12. Simulate or complete payment success.
13. Show verified webhook and `RECOVERED`.
14. Show scheduled work cancelled.
15. Replay the mandate and show rejection.
16. Show the dashboard counting revenue only once.

---

## 24. Engineering rules for coding agents

* Implement vertical slices, not disconnected screens.
* Do not add a feature unless it supports detection, diagnosis, recovery, verification, safety, or measurement.
* Keep domain decisions in testable Python modules.
* Do not put business rules inside React components.
* Do not put external API calls inside Temporal workflow code.
* Generate TypeScript API types from OpenAPI where practical.
* Use feature flags for voice, A2A, and real Razorpay adapters.
* Provide mock adapters for every external dependency.
* Make every endpoint return structured error codes.
* Record correlation IDs across API, workflow, A2A, and webhook events.
* Prefer abstention to an unsafe automated action.
* Never use floating-point numbers for money.
* Never mark a payment successful from browser state alone.
* Keep the repository runnable without paid AI APIs.
* Ensure the happy path and every failure demo are reproducible from seeded data.

---

## 25. Reference documentation

* Razorpay Buildathon: `https://razorpay.com/buildathon/`
* Razorpay API reference: `https://razorpay.com/docs/api/`
* Razorpay Payment Links APIs: `https://razorpay.com/docs/payments/payment-links/apis/`
* Razorpay webhook validation: `https://razorpay.com/docs/webhooks/validate-test/`
* Razorpay Python SDK: `https://github.com/razorpay/razorpay-python`
* A2A protocol and Python SDK: `https://a2a-protocol.org/latest/`
* Temporal Python SDK: `https://docs.temporal.io/develop/python`
* Next.js App Router: `https://nextjs.org/docs/app`
* CatBoost: `https://catboost.ai/`

---

## License

Choose a license before publishing. MIT is a reasonable default for a public hackathon repository unless team or Buildathon requirements specify otherwise.
