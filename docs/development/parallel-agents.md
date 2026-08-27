# Parallel agent playbook

Every phase starts from a coordinator-created `phase-N-start` tag. Each implementation agent gets
a separate `codex/pN-*` branch and an isolated worktree. Only the coordinator updates shared
contracts and regenerates derived files.

## Prompt contract

Each task prompt must include the baseline tag, allowed paths, read-only dependencies, frozen
interfaces, deliverables, tests, forbidden files, and handoff expectations. An agent must stop and
request an interface change rather than silently editing a coordinator-owned file.

## Handoff contract

Include the commit hash, files changed, commands and results, requested dependencies/migrations,
limitations, integration steps, API examples for backend work, and screenshots for UI work.

## Phase integration

The coordinator merges in the documented order, generates OpenAPI and migrations once, runs the
complete phase gate, records any deferred gap, and creates `phase-N-complete`. No later phase starts
from an implementation branch.

## Integration sequence

| Phase | Parallel workstreams | Frozen input | Integration output |
| --- | --- | --- | --- |
| 0 | domain contracts; hosting; design system | repository root | contracts, deployment foundation, UI primitives |
| 1 | core API; Temporal workflow; merchant vertical slice | Phase 0 | mock-provider recovery loop |
| 2 | Razorpay adapter; policy/simulator; merchant UX | Phase 1 | test-mode payment integration and controls |
| 3 | RecoveryBench; A2A; voice | Phase 2 | three isolated provider-backed hero features |
| 4 | reliability; E2E/accessibility; deployment security | Phase 3 | deterministic failure handling and release safety |
| 5 | product polish; documentation; audit | Phase 4 | submission-ready release candidate |

The three workstreams inside a row may run concurrently. A row never consumes another workstream's
unmerged branch; it consumes only the phase-start tag. The coordinator is the single writer for
root manifests, lockfiles, shared schemas, migrations, generated clients, CI, and environment
contracts.

## Code-complete versus hosted-complete

Cloud provisioning and real-provider smoke tests require external accounts, credentials, capacity,
consented phone numbers, or DNS. When those prerequisites are unavailable, the coordinator creates
an explicit `phase-N-code-complete` tag after all local and container gates pass and records the
hosted gate as pending. It must not create `phase-N-complete` or substitute a sleeping worker. Later
code work may use the code-complete tag only when the deferred hosted dependency cannot change a
frozen application interface.

Current execution status and exact baselines are recorded in
[`implementation-status.md`](implementation-status.md).
