# RecoveryOS agent contract

## Repository invariants

- Python targets 3.12 and Node targets the active 22 LTS line.
- Money is stored and transported as integer paise. Never use floating point for money.
- Mock providers are the default; real Razorpay and telephony actions require explicit server-side flags.
- Business decisions live in Python domain modules, never in React components.
- External and non-deterministic calls live in Temporal activities, never workflow code.
- Browser callbacks are not authoritative proof of payment.
- Every provider boundary must be idempotent or explicitly reconcile uncertain submission.

## Shared-file ownership

During parallel phases, only the coordinator edits root manifests, lockfiles, OpenAPI output,
database migrations, CI, shared environment contracts, and README navigation. Implementation
agents must record requested shared changes in their handoff.

## Required validation

Run the narrowest relevant unit tests while iterating, then run root lint, typecheck, test, and
build commands before a phase is tagged. UI changes also require desktop/mobile screenshots and
an accessibility pass.

