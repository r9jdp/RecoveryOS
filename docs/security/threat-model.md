# Security and threat model

Scope: hackathon test/demo deployment through Phase 4. This is a design review, not a claim of
production certification.

## Assets and trust boundaries

Protected assets are provider credentials, webhook secrets, mandate signing keys, customer contact
consent/suppressions, exact payment scope, recovery accounting, audit history, and deployment access.
Browsers, public webhooks, A2A peers, telephony callbacks, provider APIs, CI, the OCI host, Neon, and
Temporal Cloud cross separate trust boundaries.

## Threats and implemented controls

| Threat                        | Current control                                                                                    | Residual risk / next gate                                      |
| ----------------------------- | -------------------------------------------------------------------------------------------------- | -------------------------------------------------------------- |
| Forged or changed webhook     | raw-body HMAC before parsing; server secret; authoritative fetch                                   | provider credentials and hosted smoke not yet validated        |
| Duplicate/out-of-order event  | unique inbox ID, outbox, state clocks, reconciliation, revenue uniqueness                          | monitor poison/retry backlog in hosting                        |
| Browser claims payment        | browser callback never authoritative                                                               | keep provider reconciliation available during outages          |
| Double collection             | pending-retry Payment Link block, exact invoice correlation, idempotency                           | operator/auth controls required for production                 |
| Mandate tampering/replay      | Ed25519 pinned key, canonical JSON, exact scope/time checks, atomic nonce consumption              | rotate keys; make customer-agent tasks durable                 |
| LLM/agent executes payment    | mandate only authorizes a pre-bound surface; deterministic provider code executes                  | protocol and policy audit before new agent skills              |
| Unauthorized real call        | explicit flag, operator token, allowlist token, consent, quiet hours, kill switch and budgets      | shared demo auth is insufficient for public real calls         |
| Opt-out ignored               | safety intent precedence, durable suppression, immediate cancel, independent contact axis          | retention/deletion and cross-channel suppression policy needed |
| Uncertain external submission | persist before submit, one attempt, circuit breaker and reconciliation                             | operational alerting and manual runbook required               |
| Secret exposure               | server-only env files, no build args, repository/browser scan, Gitleaks/Trivy gates                | external secret manager and rotation drill required            |
| Resource abuse                | HAProxy per-IP rates, 1 MiB bodies, timeouts, container limits                                     | rate limiting is not authentication; distributed abuse remains |
| Unsafe deploy/migration       | immutable images, serialized deploy, backup first, destructive-DDL check, smoke and image rollback | checker is not a substitute for human migration review         |
| Database loss/corruption      | checksummed dump and isolated restore verification                                                 | encrypted off-host retention and Neon recovery exercise needed |

## Fail-closed defaults

`PAYMENT_PROVIDER=mock`, `VOICE_PROVIDER=mock`, `VOICE_REAL_CALLS_ENABLED=false`,
`A2A_ENABLED=false`, and `CUSTOMER_AGENT_REAL_SIGNING_ENABLED=false` are the safe defaults. The
public-demo preflight also requires test-mode enforcement, empties provider secrets, and rejects any
real-provider configuration. Creation circuit breakers do not block reads, cancellation, or
reconciliation.

## Data minimization

RecoveryOS stores merchant/customer identifiers, payment/invoice/subscription references, integer
amounts, status evidence, audit payloads, consent/suppression facts, and optional transcripts. It must
never store card number, CVV, UPI PIN, OTP, or banking credentials. Avoid full provider payloads and
transcripts in CI/logs. Retention and data-subject workflows are not implemented and block production.

## Production blockers

Before any production launch, add authenticated server-side sessions, merchant authorization on
every read/mutation, CSRF/origin protections, durable customer-agent task storage, formal privacy and
retention controls, encrypted managed secret storage, key rotation, audit access controls, alerting,
incident response, India telecom/DLT and consent review, and Razorpay production review. Complete an
independent penetration test and accounting reconciliation exercise after those changes.
