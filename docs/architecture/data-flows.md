# Critical data flows

## Failed payment to authoritative recovery contract

```mermaid
sequenceDiagram
    participant R as Razorpay test mode
    participant A as FastAPI API
    participant D as PostgreSQL
    participant W as Temporal worker
    participant T as Case workflow
    participant U as Merchant UI

    R->>A: webhook + raw body + signature + event ID
    A->>A: verify HMAC before JSON parsing
    A->>D: atomically insert inbox and outbox
    A-->>R: 202 accepted, duplicate flag if applicable
    W->>D: claim unpublished outbox message
    W->>T: start or signal recovery-case:{case_id}
    T->>W: diagnosis, scoring, policy and provider activities
    W->>D: persist decisions and audit evidence
    U->>A: approve bounded customer-present surface
    A->>R: create/fetch test-mode surface with idempotency
    R->>A: payment success webhook
    W->>R: authoritative payment fetch
    W->>D: recognize event once and preserve lifecycle axes
    W->>T: authoritative payment signal
    T->>W: cancel outstanding recovery action
    U->>A: read recovered case and timeline
```

Duplicates return the existing inbox/outbox identifiers. Out-of-order failures cannot regress a
captured payment. `WAIT_FOR_GATEWAY_RETRY` never charges a failed payment ID; Razorpay owns pending
subscription retries. A standard Payment Link is blocked while those retries are active.

## Exact A2A authorization

```mermaid
sequenceDiagram
    participant R as Recovery agent
    participant C as Customer agent
    participant B as Customer browser
    participant V as Mandate verifier
    participant D as PostgreSQL nonce store
    participant P as Payment activity

    R->>C: SendMessage with recovery.request.v1
    C-->>R: TASK_STATE_AUTH_REQUIRED
    B->>C: review exact merchant, case, amount and surface
    B->>C: approve exact scope
    C-->>R: Ed25519 recovery.mandate.v1 artifact
    R->>V: verify pinned key, time and full scope
    V->>D: atomic consume nonce
    D-->>V: consumed once or replay rejected
    V->>P: verified mandate for already-bound surface
    P-->>R: provider result, not payment truth
    R->>C: recovery.receipt.v1 after authoritative result
```

The mandate authorizes one exact payment surface; it does not authorize an LLM to charge. The
customer still completes the provider-owned surface. The customer-agent task store is process-local
in this release, so multi-instance hosting is a production blocker; nonce replay protection is
durable in PostgreSQL.

## Guarded voice contact

```mermaid
flowchart TD
    Request[Operator starts contact] --> Gates{All server gates pass?}
    Gates -->|No| Reject[Persist/reply with structured rejection]
    Gates -->|Yes| Reserve[Persist RESERVED idempotency record]
    Reserve --> Submit[Submit once to Twilio]
    Submit -->|certain| Call[Signed TwiML registers ElevenLabs]
    Submit -->|uncertain| Reconcile[Do not retry; reconcile by call ID]
    Call --> Disclosure[AI disclosure before case detail]
    Disclosure --> Intent{Safety-first intent}
    Intent -->|opt-out| Suppress[Persist suppression and end call]
    Intent -->|wrong person / dispute / already paid| Stop[End or escalate]
    Intent -->|safe| Bounded[Offer bounded recovery next step]
```

Real calling requires all of: Twilio provider selection, explicit real-call flag, operator token,
allowlisted destination token, recorded consent, allowed local time, kill switch off, one-call
concurrency, ten-call daily budget, and a duration no greater than 180 seconds. Browser text/audio
rehearsal remains available in mock mode.

These diagrams describe the implemented boundaries and their required composition. In the current
runtime, webhook reconciliation and merchant-triggered Razorpay surfaces are integrated, while the
Temporal action service remains mock-backed. A2A delegation, customer approval, mandate
verification, and nonce consumption pass component/E2E tests, but the approved-task-to-workflow
bridge is not yet wired.
