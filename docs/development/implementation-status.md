# Implementation status

This file distinguishes implemented code from gates that require external infrastructure or real
provider credentials. Dates use Asia/Kolkata time.

## Frozen baselines

| Milestone | Commit/tag | Local gate | External gate |
| --- | --- | --- | --- |
| Phase 0 foundation | `83366ea` / `phase-0-code-complete` | contracts, design system, containers, Terraform validation | OCI capacity, Neon branches, Temporal Cloud, DNS, Vercel |
| Phase 1 vertical slice | `17fe5f7` / `phase-1-code-complete` | API, migration, PostgreSQL, Temporal replay, browser flow, duplicate-revenue gate | hosted Playwright run |
| Phase 2 payment integration | `1e83c04` / `phase-2-code-complete` | Razorpay inbox/outbox, reconciliation, safety policy, merchant UX, live browser flow | hosted Razorpay test-mode webhook/payment smoke |
| Phase 3 hero features | `04e250a` / `phase-3-code-complete` | RecoveryBench, signed A2A authorization, guarded voice, combined browser and container gate | hosted A2A origin plus one credentialed allowlisted Twilio/ElevenLabs call |
| Phase 4 hardening | `00191bb` / `phase-4-code-complete` | deterministic failure injection, 24-check browser QA, backup/restore, edge limits, security and staged-deploy gates | credentialed staging/production deploy, public monitoring, and Trivy registry scan |

Phase 3 worktrees started only from `phase-2-code-complete` and were merged through their frozen
provider interfaces:

- `codex/p3-recoverybench` — deterministic evaluation and ML Lab.
- `codex/p3-a2a` — signed A2A customer-agent mandates.
- `codex/p3-voice` — browser voice plus guarded Twilio/ElevenLabs adapters.

## Verified Phase 1 gate

- PostgreSQL 17, Temporal 1.29.1, and Temporal UI start locally through Compose.
- Alembic upgrades, downgrades, and reports no schema drift.
- The FitBox seed creates one invoice-scoped recovery case.
- The merchant UI loads through the generated fixture/API boundary on desktop and mobile.
- Approving the recommended card-update surface persists an audit event.
- Applying the same mock payment-success event twice returns `newly_recognized=true` and then
  `false`; the database contains one ₹1,499 revenue-recognition row.
- The worker image connects to Temporal and becomes healthy.
- Lint, formatting, type checks, 49 Python tests, 5 web tests, and the production frontend build
  pass.

## Verified Phase 2 code gate

- Raw Razorpay request bodies are HMAC-verified before parsing, duplicate provider event IDs create
  one inbox/outbox pair, and API acknowledgement is independent from asynchronous processing.
- The worker drains unpublished messages, starts or signals `recovery-case:{case_id}`, and marks
  inbox/outbox completion only after the Temporal handoff succeeds.
- `payment.failed` creates one trusted invoice-scoped case; captured events require an authoritative
  provider fetch and recognize Razorpay test revenue once without conflating arrears collection and
  subscription reactivation.
- Pending subscription retries block standalone Payment Links; invoice links and card-update
  surfaces preserve subscription/invoice correlation.
- Merchant policy settings persist quiet hours, contact limits, amount/action approval rules, and a
  kill switch while webhook reconciliation remains enabled.
- The live frontend uses dashboard, case, timeline, policy, approval, and safety APIs, with explicit
  deterministic fixture fallback when the API is unavailable.
- Desktop and 390×844 browser checks passed for live data, approvals, policy controls, the kill
  switch, mobile navigation, and wrong-person suppression. The browser pass found and verified a
  fix preventing read-only policy metadata from leaking into strict update requests.
- PostgreSQL migration downgrade/upgrade/drift checks, 121 Python tests, 17 web tests, strict lint,
  formatting and type checks, the production frontend build, and API/worker Docker builds pass.

## Verified Phase 3 code gate

- RecoveryBench generates 1,200 fixed-seed paired cases and publishes a versioned, checksummed
  CatBoost/isotonic artifact plus PR-AUC, Brier, calibration, top-decile, amount-weighted, and
  action-level reports. All evaluation revenue is labelled simulated and cannot mutate merchant
  revenue; production scoring safely falls back when the artifact is absent.
- The separate customer-agent service implements A2A 1.0 Agent Cards and PascalCase JSON-RPC
  lifecycle methods. Exact customer approval returns an Ed25519 `recovery.mandate.v1` artifact;
  pinned-key verification rejects tampering, expiry, scope changes, and replay. PostgreSQL nonce
  consumption uses one `INSERT ... ON CONFLICT DO NOTHING RETURNING` serialization point.
- The recovery-agent origin exposes a fail-closed delegation endpoint. A2A remains disabled by
  default, and mandate-verifier construction is activity-side so signature verification and nonce
  writes never enter deterministic workflow code.
- Browser voice rehearsal detects safety intents with opt-out precedence. Real Twilio calls require
  the explicit server flag, operator token, pre-consented allowlist, HTTPS origin, and complete
  credentials. Recording stays disabled, one active call and ten calls/day are enforced, duration
  is capped at 180 seconds, and uncertain submission is never automatically retried.
- Voice attempts, callback receipts, suppressions, and A2A nonce consumption are covered by a
  reversible migration chain with a clean Alembic drift check. Persisted Twilio call SIDs are used
  to end calls after process restarts when an opt-out arrives.
- The combined live browser gate passed for API connectivity, `/lab`, `/voice`, and an actual local
  A2A authorization task at desktop and 390×844 mobile sizes. It verified exact-scope approval
  gating, safety-first transcript analysis, no horizontal overflow, labelled controls, and zero
  browser console errors without placing a call or payment.
- Strict Ruff/Mypy/format checks, 175 Python tests, 27 web tests, the production Next.js build,
  PostgreSQL downgrade/upgrade/reset, and Phase 3 API/worker/customer-agent Docker builds pass.

## Verified Phase 4 code gate

- Process-stable Razorpay and Twilio circuit breakers fail closed on uncertain submission while
  keeping authoritative reads, cancellation, and reconciliation available. Structured reason
  codes reach the existing provider boundaries, and workflow code is statically guarded from HTTP
  or provider integration imports.
- Deterministic failure suites cover duplicate, stale, out-of-order, late-success, and changed-state
  Razorpay delivery; Temporal timeouts and bounded retries; invalid A2A mandates; Twilio busy,
  no-answer, callback duplication, and uncertain submission; ElevenLabs reconciliation; and stale
  database writers through compare-and-swap.
- The mock-only Playwright suite passes all 24 desktop/mobile checks, including the five-minute judge
  flow, customer-safety paths, exact A2A scope and replay rejection, voice no-auto-retry behavior,
  network/loading/error states, keyboard-only operation, focus restoration, semantic control labels,
  and 1440×960 plus 390×844 visual baselines.
- A separate in-app browser pass confirmed deterministic API fallback, operator controls, zero
  horizontal overflow, no unlabelled mobile buttons, and zero console errors. Six frozen visual
  baselines and six README-ready screenshots are checked in.
- Deployment preflight now serializes releases, creates a mandatory pre-migration backup, rejects
  destructive migration upgrades, validates one Alembic head, smokes exact image versions, and
  performs image-only rollback without attempting an unsafe database downgrade.
- A real local PostgreSQL dump, checksum, and ephemeral restore verified revision
  `27b4eb4b36a1` with 18 public tables. HAProxy/Caddy validation, staging/production Compose config,
  public-demo provider safety, repository secret scanning, Gitleaks history scanning, and Node and
  Python dependency audits pass.
- CI now runs E2E and security gates; the deployment workflow builds immutable ARM64 images, scans
  service images, deploys staging first, and only then permits a protected production promotion.
  Scheduled public health probes are ready once repository URL variables exist.
- Strict lint/format/type checks, 205 Python tests, 27 web tests, 24 Playwright checks, OpenAPI drift,
  the production Next.js build, and API/worker/customer-agent Docker builds pass.

## External prerequisites

As of 2026-08-28, the installed Vercel token is invalid, and OCI CLI credentials are unavailable.
Neon, Temporal Cloud, DNS, Razorpay test credentials, Twilio, and ElevenLabs credentials are not
present in the workspace. Mock mode therefore remains the safe default, and no real payment or call
action is enabled.
