# Implementation status

This file distinguishes implemented code from gates that require external infrastructure or real
provider credentials. Dates use Asia/Kolkata time.

## Frozen baselines

| Milestone | Commit/tag | Local gate | External gate |
| --- | --- | --- | --- |
| Phase 0 foundation | `83366ea` / `phase-0-code-complete` | contracts, design system, containers, Terraform validation | OCI capacity, Neon branches, Temporal Cloud, DNS, Vercel |
| Phase 1 vertical slice | `17fe5f7` / `phase-1-code-complete` | API, migration, PostgreSQL, Temporal replay, browser flow, duplicate-revenue gate | hosted Playwright run |
| Phase 2 payment integration | `1e83c04` / `phase-2-code-complete` | Razorpay inbox/outbox, reconciliation, safety policy, merchant UX, live browser flow | hosted Razorpay test-mode webhook/payment smoke |

Phase 3 worktrees start only from `phase-2-code-complete`:

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

## External prerequisites

As of 2026-08-27, the installed Vercel token is invalid, and OCI CLI credentials are unavailable.
Neon, Temporal Cloud, DNS, Razorpay test credentials, Twilio, and ElevenLabs credentials are not
present in the workspace. Mock mode therefore remains the safe default, and no real payment or call
action is enabled.
