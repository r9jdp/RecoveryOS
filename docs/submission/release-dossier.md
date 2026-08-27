# RecoveryOS submission dossier

Status: Phase 5 candidate, local code gate complete through Phase 4 on 2026-08-28.

RecoveryOS is an auditable, test-mode recovery orchestrator for failed Razorpay subscription
billing cycles. It combines deterministic diagnosis, merchant policy, durable Temporal workflows,
customer-present payment surfaces, a separately hosted A2A authorization agent, guarded voice, and
a simulated evaluation lab. The core rule is simple: the model recommends, policy authorizes,
deterministic code executes, provider evidence confirms, and the timeline records.

## What is demonstrable now

| Capability                     | Evidence                                                                                     | Boundary                                                               |
| ------------------------------ | -------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| FitBox recovery vertical slice | seeded API, Control Tower, Case Workspace, mock payment success                              | `SIMULATED`; no money moves                                            |
| Razorpay adapter               | raw-body HMAC, durable inbox/outbox, test-key enforcement, reconciliation tests              | hosted test-mode smoke needs credentials                               |
| Durable orchestration          | one Temporal workflow per case, bounded retries, replay tests, cancellation                  | hosted namespace needs credentials                                     |
| A2A authorization              | separate service, A2A 1.0 JSON-RPC, exact-scope mandate and replay E2E tests                 | task-to-verifier runtime bridge is not wired; task storage is local    |
| Voice safety                   | browser rehearsal, all intents, signed callbacks, persisted attempts, strict real-call gates | real call needs allowlisted consent plus Twilio/ElevenLabs credentials |
| RecoveryBench                  | 1,200 fixed-seed paired synthetic cases, versioned CatBoost/isotonic artifact                | simulated; scorer is not wired into the worker entry point             |
| Reliability                    | 205 Python tests, 27 web tests, 24 Playwright checks, backup/restore and deploy gates        | public deployment has not been provisioned                             |

The shipping worker entry point constructs `MockRecoveryActivityServices`. Razorpay, A2A-verifier,
voice, and RecoveryBench boundaries are implemented and independently tested, but a production
activity-service composition that connects all of them to the Temporal workflow is not present. The
submission therefore demonstrates the complete workflow in mock mode and real provider boundaries
as isolated contract/reliability paths, not one hosted real-provider journey.

## Review path

1. Read the [product specification](../product/product-specification.md).
2. Review [architecture](../architecture/system-architecture.md) and
   [critical data flows](../architecture/data-flows.md).
3. Run the [five-minute demo](../demo/five-minute-demo.md).
4. Exercise the [failure checklist](../demo/failure-demo-checklist.md).
5. Review the [model card](../model/recoverybench-model-card.md) and
   [threat model](../security/threat-model.md).
6. For release operations, follow the [staged deployment runbook](../runbooks/staged-deployment.md)
   and [database restore runbook](../runbooks/database-backup-restore.md).

## Evidence taxonomy

- `SIMULATED`: deterministic fixture, mock-provider, or synthetic RecoveryBench evidence. It may
  demonstrate behavior but cannot contribute to verified merchant revenue.
- `RAZORPAY_TEST_VERIFIED`: a valid Razorpay test webhook followed by authoritative provider
  reconciliation. This label is unavailable until the credentialed hosted smoke succeeds.
- Production-verified evidence does not exist in this project.

## External gates still open

No live URL is claimed. As of 2026-08-28 the workspace has no usable Vercel token, OCI CLI
credentials, Neon branches, Temporal Cloud namespaces, DNS, Razorpay test credentials, or
Twilio/ElevenLabs credentials. Mock mode is therefore the default and all real-provider paths are
off. Production remains blocked on authentication, multi-tenancy authorization, durable
customer-agent storage, privacy/retention, India telecom and consent review, and Razorpay production
approval.

See the [independent-project disclaimer](./disclaimer.md) before publishing screenshots or video.
