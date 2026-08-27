# Implementation status

This file distinguishes implemented code from gates that require external infrastructure or real
provider credentials. Dates use Asia/Kolkata time.

## Frozen baselines

| Milestone | Commit/tag | Local gate | External gate |
| --- | --- | --- | --- |
| Phase 0 foundation | `83366ea` / `phase-0-code-complete` | contracts, design system, containers, Terraform validation | OCI capacity, Neon branches, Temporal Cloud, DNS, Vercel |
| Phase 1 vertical slice | `17fe5f7` / `phase-1-code-complete` | API, migration, PostgreSQL, Temporal replay, browser flow, duplicate-revenue gate | hosted Playwright run |

Phase 2 worktrees start only from `phase-1-code-complete`:

- `codex/p2-razorpay` — Razorpay adapter and webhook ingestion.
- `codex/p2-safety` — policy controls and deterministic failure simulator.
- `codex/p2-merchant-ui` — complete merchant controls and safety UX.

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

## External prerequisites

As of 2026-08-27, the installed Vercel token is invalid, and OCI CLI credentials are unavailable.
Neon, Temporal Cloud, DNS, Razorpay test credentials, Twilio, and ElevenLabs credentials are not
present in the workspace. Mock mode therefore remains the safe default, and no real payment or call
action is enabled.
