# RecoveryOS

RecoveryOS is an auditable, test-mode recovery orchestrator for failed Razorpay subscription
billing cycles. It diagnoses the failure, applies merchant safety policy, coordinates durable
recovery work, and accepts only authoritative provider evidence before recognizing revenue.

> [!IMPORTANT]
> RecoveryOS is an independent hackathon demonstration. It is not affiliated with or endorsed by
> Razorpay. Mock providers are the default; no live money or customer contact is enabled.

## Current status

There is no public live URL yet. The local mock experience is deterministic; hosted and real-
provider gates require infrastructure and credentials that are not present in this workspace.

| Area              | Available locally                                                                                    | Still gated                                               |
| ----------------- | ---------------------------------------------------------------------------------------------------- | --------------------------------------------------------- |
| Merchant product  | Signed demo session, Control Tower, case workspace, approvals, policy controls, guided FitBox demo  | Production identity, RBAC and multi-tenancy                |
| Recovery workflow | Persisted policy gates, Temporal replay/reconciliation, duplicate-safe revenue accounting           | Temporal Cloud deployment                                  |
| Razorpay          | Signed webhook inbox/outbox, reconciliation, invoice/card-update surfaces, halted-only Payment Links | Hosted test-mode smoke and production review               |
| A2A               | Durable hosted task store, exact-scope mandates, replay protection and authoritative receipts       | Hosted origins and production identity/key rotation        |
| Voice             | Browser rehearsal, consent/limit gates, Twilio and ElevenLabs adapters                               | One allowlisted credentialed test call and telecom review |
| RecoveryBench     | Fixed-seed paired simulation, versioned CatBoost artifact and `/lab` report                          | Production outcome validation                              |

Evidence is always labelled `SIMULATED` or `RAZORPAY TEST VERIFIED`; synthetic results never count
as verified merchant revenue. See the [implementation status](docs/development/implementation-status.md)
and [Phase 5 audit](docs/audit/phase-5-final-audit.md) for the exact verified boundary.

## Five-minute local demo

Prerequisites: Node.js 22 LTS, pnpm 10.15.1, Python 3.12, `uv`, and Docker.

```powershell
pnpm install --frozen-lockfile
uv sync --all-groups
pnpm infra

$env:DATABASE_URL = "postgresql+psycopg://recovery:recovery@localhost:55432/recovery_os"
$env:TEMPORAL_ADDRESS = "localhost:7233"
$env:TEMPORAL_NAMESPACE = "default"
$env:TEMPORAL_TASK_QUEUE = "recovery-os"

pnpm migrate
pnpm seed
```

Start each process in a separate terminal with the same server-side environment:

```powershell
pnpm dev:api
pnpm dev:worker
pnpm dev:customer-agent
pnpm dev:web
```

Open [http://localhost:3000](http://localhost:3000), choose **Open the FitBox demo**, and follow the
in-product guide. The seeded operator values are `demo@recoveryos.dev` and `recovery-demo`.
The walkthrough is also documented in the [five-minute demo script](docs/demo/five-minute-demo.md).

Keep `PAYMENT_PROVIDER=mock`, `A2A_ENABLED=false`, `VOICE_PROVIDER=mock`, and
`VOICE_REAL_CALLS_ENABLED=false` unless you are deliberately running a server-side provider test.

## Architecture

```text
Next.js merchant UI
        │
        ▼
FastAPI ── PostgreSQL inbox/outbox and audit state
        │
        ▼
Temporal workflow ── activity-side payment / A2A / voice / scoring adapters
        │
        ▼
Signed webhooks and authoritative reconciliation ── revenue recognition
```

The governing rule is: **the model recommends, policy authorizes, deterministic code executes,
provider evidence confirms, and the audit timeline records.** Money is always integer paise;
browser callbacks never prove payment.

## Documentation

- [Submission dossier](docs/submission/release-dossier.md)
- [Product specification](docs/product/product-specification.md)
- [System architecture](docs/architecture/system-architecture.md) and [data flows](docs/architecture/data-flows.md)
- [Razorpay-inspired design system](docs/design/design-system.md)
- [API and webhook setup](docs/contracts/api-webhook-setup.md)
- [RecoveryBench model card](docs/model/recoverybench-model-card.md)
- [Threat model](docs/security/threat-model.md)
- [Failure-demo checklist](docs/demo/failure-demo-checklist.md)
- [Staged deployment](docs/runbooks/staged-deployment.md) and [database recovery](docs/runbooks/database-backup-restore.md)
- [Independent-project disclaimer](docs/submission/disclaimer.md)

## Validation

Run the narrowest tests while iterating, then the complete local gate:

```powershell
pnpm lint
pnpm format:check
pnpm typecheck
pnpm test
pnpm e2e
pnpm e2e:service
pnpm build
pnpm generate:openapi
git diff --exit-code -- packages/contracts/openapi.json
```

RecoveryBench can be regenerated deterministically with:

```powershell
uv run python -m ml.recoverybench.build --seed 20260827 --case-count 1200
```

## Development model

Work proceeds in frozen phases with one coordinator and independent agent worktrees. Shared schemas,
migrations, generated clients, root manifests, CI, and environment contracts are single-writer
files. See [parallel agent development](docs/development/parallel-agents.md) and [AGENTS.md](AGENTS.md).

## License

No open-source license has been selected. All rights remain reserved until a license is added.
