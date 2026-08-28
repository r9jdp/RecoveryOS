# RecoveryOS submission dossier

Status: Phase 5 continuation candidate, integrated locally on 2026-08-28; the final combined code
gate and all credential-dependent hosted gates remain to be recorded.

RecoveryOS is an auditable, test-mode recovery orchestrator for failed Razorpay subscription
billing cycles. It combines deterministic diagnosis, merchant policy, durable Temporal workflows,
customer-present payment surfaces, a separately hosted A2A authorization agent, guarded voice, and
a simulated evaluation lab. The core rule is simple: the model recommends, policy authorizes,
deterministic code executes, provider evidence confirms, and the timeline records.

## What is demonstrable now

| Capability                     | Evidence                                                                                                | Boundary                                                               |
| ------------------------------ | ------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| FitBox recovery vertical slice | seeded API, Control Tower, Case Workspace, mock payment success                                         | `SIMULATED`; no money moves                                            |
| Razorpay adapter               | signed durable ingress, test-key enforcement, authoritative reconciliation, uncertain-link lifecycle    | hosted test-mode smoke needs credentials                               |
| Durable orchestration          | production activity composition, one workflow per case, persisted policy timing, replay/cancellation    | hosted namespace needs credentials                                     |
| A2A authorization              | A2A 1.0 JSON-RPC, durable SQL tasks, exact-scope signed mandate, atomic replay rejection, final receipt | hosted cross-origin flow still needs deployed origins and credentials  |
| Operator safety                | signed HttpOnly session, matching CSRF token, hosted-mode enforcement                                   | shared demo identity is not production multi-tenant authorization      |
| Voice safety                   | browser rehearsal, all intents, signed callbacks, persisted attempts, strict real-call gates            | real call needs allowlisted consent plus Twilio/ElevenLabs credentials |
| RecoveryBench                  | 1,200 fixed-seed paired cases, versioned CatBoost/isotonic artifact, composed worker scorer             | all reported incremental metrics remain simulated                      |
| Reliability                    | unit/contract/replay/UI suites plus real-service and failure-lab paths                                  | final combined rerun and public deployment remain open                 |

Mock activity services remain the default. `RECOVERY_ACTIVITY_MODE=production` composes the
SQL-backed runtime, selected payment provider, and RecoveryBench scorer. Independently,
`A2A_ENABLED=true` selects the live customer-agent client/verifier, and recovered cases use the
configured voice cancellation boundary. Merchant commands signal the case workflow instead of
opening a second provider path. The real-service gate exercises PostgreSQL, Temporal, the API,
worker, web app, and SQL-backed customer agent locally. This is integration evidence, not a claim
that any hosted or credentialed provider journey has run.

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
off. Hosted staging/production require the signed operator session and CSRF contract, but that shared
demo identity is not production authentication or merchant authorization. Production remains blocked
on multi-user identity and multi-tenancy authorization, privacy/retention, managed key rotation and
monitoring, India telecom and consent review, and Razorpay production approval.

See the [independent-project disclaimer](./disclaimer.md) before publishing screenshots or video.
