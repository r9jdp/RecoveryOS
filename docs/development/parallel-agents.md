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

