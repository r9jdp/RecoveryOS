# RecoveryOS Phase 5 final audit

Audit date: 2026-08-28 (Asia/Kolkata)

Audited baseline: `phase-5-start` / `cc0f911891b40520b3db55c2bd329d6754c3cf80`

Audit branch: `codex/p5-audit`

Audit mode: read-only first; this report is the only tracked file changed

## Executive verdict

**Do not tag the audited baseline as final code-complete.** The repository has strong isolated
domain, provider, safety, UI, migration, and failure-injection tests, but two P0 integration gaps
mean the implemented services do not yet form the claimed recovery system:

1. Merchant commands and real provider calls bypass Temporal while the deployed Temporal worker
   always registers mock activity services.
2. The A2A signature/nonce verifier is not connected to a runtime endpoint or activity, while the
   workflow accepts a caller-supplied `verified` boolean.

The audit found **2 P0, 7 P1, 6 P2, and 2 P3 findings**. The code gate cannot pass until both P0s
and the payment/auth/accounting/telephony P1s are fixed and exercised through a real local
cross-service E2E path. External credentials are not needed to fix or validate those items.

Credential-dependent hosted gates remain separately blocked: OCI, Neon, Temporal Cloud, DNS,
Vercel, Razorpay test mode, Twilio, and ElevenLabs are not configured in this environment. Those
external blockers do not excuse the code-level findings below.

## Severity convention

- **P0:** blocks the core recovery/security contract or makes the claimed end-to-end system false.
- **P1:** blocks a required submission, hosted smoke, safety, payment, or accounting gate.
- **P2:** material correctness, resilience, documentation, or developer-experience gap.
- **P3:** low-risk maintainability or observability debt.

## Ranked findings

| ID   | Rank | Finding                                                                                 | Gate impact                             |
| ---- | ---- | --------------------------------------------------------------------------------------- | --------------------------------------- |
| F-01 | P0   | API/provider state and Temporal state are split; deployed activities are always mocks   | Core recovery orchestration             |
| F-02 | P0   | A2A verifier/nonce consumer is orphaned and the workflow trusts `verified` input        | Mandate authorization and replay safety |
| F-03 | P1   | Razorpay card-update surface returns a frontend route that does not exist               | Preferred pending-subscription recovery |
| F-04 | P1   | Demo login is cosmetic and Razorpay test payment actions have no operator authorization | Anonymous-action safety contract        |
| F-05 | P1   | Dashboard gross, incremental, net, and at-risk accounting formulas are incorrect        | Revenue claims and judging evidence     |
| F-06 | P1   | Authoritative payment success does not end an active Twilio call                        | Telephony stopping rule                 |
| F-07 | P1   | Deployment smoke checks the wrong Agent Card field and deterministically rolls back     | Hosted staging/production deploy        |
| F-08 | P1   | All three documented RecoveryBench root commands fail                                   | Batch evaluation and fresh setup        |
| F-09 | P1   | Playwright is UI-only and mocks every API/A2A/voice boundary                            | Hosted E2E confidence                   |
| F-10 | P2   | Public root is a stale Phase 0 page with no demo-login path                             | Five-minute judge entry                 |
| F-11 | P2   | Customer-agent task state is process-local and invalid JSON-RPC methods become HTTP 422 | A2A durability/protocol behavior        |
| F-12 | P2   | Handwritten frontend policy types reject backend-supported nullable controls            | Cross-service schema consistency        |
| F-13 | P2   | README API/setup/license content is stale relative to the built application             | Submission documentation                |
| F-14 | P2   | Windows checkout line endings break the format and Bash security/deploy gates           | Fresh Windows setup                     |
| F-15 | P2   | Failure injection is not exposed as the promised complete one-click lab/demo surface    | Failure demonstration                   |
| F-16 | P3   | Worker health checks only PID 1, not Temporal polling/activity readiness                | Deployment observability                |
| F-17 | P3   | Test suite emits a Starlette `httpx` deprecation warning                                | Dependency maintenance                  |

## Detailed findings and required fixes

### F-01 — P0 — Temporal is not the runtime coordinator

Evidence:

- `services/worker/app/main.py:9` imports `MockRecoveryActivityServices`; line 19 constructs it
  unconditionally. No production activity-service implementation is selected for Razorpay, A2A,
  voice, SQL audit persistence, or authoritative reconciliation.
- `services/api/app/api/router.py:424-478` handles approve/reject/stop/escalate commands by mutating
  application state directly. `services/api/app/api/router.py:557-589` does the same for the
  action-specific endpoints. These paths have no Temporal client or signal call.
- `services/api/app/services/cases.py:289-368` opens the configured payment provider directly and
  commits the action/audit record.
- Separately, `services/worker/app/workflow.py:494-580` executes and cancels its own activity-side
  action. With the deployed worker, that activity produces a `mock:` reference even when the API
  uses Razorpay.

Impact: a Razorpay failure can start a workflow that waits for approval while a UI approval opens a
provider surface in the database without signaling that workflow. The workflow and read model can
diverge, time out independently, or represent different action/provider references. This also
prevents Temporal from owning A2A and voice cancellation as designed.

Required fix:

1. Implement a production `RecoveryActivityServices` adapter that uses the SQL repositories and
   frozen provider ports.
2. Make merchant commands signal the single `recovery-case:{case_id}` workflow; let activities own
   provider effects and persist their results. The API should return/query the durable command
   result rather than execute a second path.
3. Select mock versus production services from validated server configuration, keeping mock as the
   default.
4. Add a Compose-backed test proving one API approval creates exactly one activity/provider action,
   one persisted reference, and one workflow transition.

### F-02 — P0 — A2A verification is not connected to execution

Evidence:

- `services/api/app/integrations/a2a/factory.py:34-42` constructs the pinned-key, SQL nonce-backed
  verifier and describes it as activity-side. Repository search found no runtime caller; only tests
  call `verify_and_consume`.
- `services/worker/app/contracts.py:233-241` puts `verified: bool` in `MandateSignal`.
- `services/worker/app/workflow.py:451-479` trusts that boolean, checks only amount/expiry/deadline,
  and forwards the unverified artifact to payment-surface execution. It does not check signer,
  merchant, customer, case, task, currency, surface type/reference, authorized action, or consume a
  nonce.
- `services/api/app/a2a/router.py:109-166` delegates Send/Get/Cancel tasks only. It has no mandate
  acceptance boundary. `services/api/app/integrations/a2a/client.py:42-64` likewise has no verified
  mandate or final receipt operation.

Impact: the cryptographic library is good in isolation, but the production path neither uses it nor
completes the A2A lifecycle. A trusted internal caller could assert `verified=true`; an untrusted
caller has no supported safe route at all. The signed one-time mandate hero gate is therefore not
implemented end to end.

Required fix:

1. Remove caller-controlled verification truth from the workflow contract.
2. Add a Temporal activity that takes the signed artifact and expected case/payment-surface scope,
   calls `MandateVerifier.verify_and_consume`, and returns a narrow typed verification result.
3. Execute the exact payment surface only from that activity result, then send an authoritative
   payment receipt to the same A2A task.
4. Add PostgreSQL-backed tests for valid use, concurrent replay, changed scope, expiry, and receipt;
   add a workflow replay test with only the typed result recorded in history.

### F-03 — P1 — Card-update recovery URL is dead

`services/api/app/integrations/razorpay/client.py:176-205` validates Checkout options but discards
them and returns
`/payments/razorpay/card-update?case_id=...&subscription_id=...` on the RecoveryOS frontend origin.
The production Next build exposes `/`, `/a2a/[taskId]`, `/approvals`, `/cases/[caseId]`,
`/dashboard`, `/design-system`, `/lab`, `/login`, `/settings`, and `/voice`; there is no payment
route. The preferred pending-subscription card-update action therefore opens a 404.

Required fix: implement the route as a customer-present Razorpay Checkout using only public test
configuration and server-issued exact case/subscription context, or return a real provider-owned
surface. Never treat the browser completion callback as payment truth. Add a production-build route
test and Razorpay test-mode smoke.

### F-04 — P1 — Razorpay test actions are anonymously triggerable

`apps/web/src/app/login/page.tsx:15-20` writes only a sessionStorage marker; no route or server
authorizes it. `.env.example:8` defines `OPERATOR_DEMO_TOKEN`, but it has no runtime consumer.
`services/api/app/api/router.py:73-76` hard-codes the merchant, and approval endpoints at lines
424-452 and 557-570 have no authentication dependency or operator token. Once
`PAYMENT_PROVIDER=razorpay` is enabled for the hosted test smoke, an anonymous caller who knows a
case/action ID can create a payment surface.

The public mock deployment gate correctly forces real providers off, and real voice has a separate
operator token. That does not satisfy the stated rule that anonymous visitors cannot trigger
payment actions in Razorpay test mode.

Required fix: add server-side operator authentication/authorization to all merchant mutations and
hide/disable provider actions for anonymous viewers. Treat the seeded login as an actual signed
server session. Keep webhook and reconciliation endpoints independently available.

### F-05 — P1 — Dashboard revenue formulas are mislabeled

`services/api/app/repositories/cases.py:346-388`:

- sums full `amount_at_risk_paise` only for `OPEN` cases, omitting the remaining balance of
  `PARTIALLY_RECOVERED` cases;
- calls all case-level simulated arrears `simulated_incremental_recovery_paise` without subtracting
  the paired baseline;
- defines `net_recovered_value_paise` as verified plus simulated gross recovery, with no
  intervention-cost subtraction; and
- aggregates by one mutable case attribution rather than immutable recognition records, which can
  misclassify a case containing more than one evidence class.

These conflict with the README definitions of incremental recovery and net recovered value and can
overstate judging evidence.

Required fix: compute verified gross revenue from immutable `revenue_recognition` rows; keep
RecoveryBench paired incremental metrics in a separately labelled simulated metric; subtract
versioned intervention costs for net; and calculate at-risk as remaining arrears across open and
partially recovered cases. Add mixed-evidence and partial-recovery accounting tests.

### F-06 — P1 — Payment success does not stop an active call

`services/api/app/webhooks/processor.py:765-785` cancels nonterminal `RecoveryActionRecord` rows
after authoritative success, but it never selects active `VoiceContactAttemptRecord` rows or calls
`VoiceProvider.cancel_contact`. The workflow cancellation path cannot compensate because F-01
registers mock activities. Voice opt-out itself is correctly persisted and cancels by attempt/SID
in `services/api/app/voice/service.py:283-312`; the missing path is cross-service payment success.

Required fix: make authoritative success signal the workflow, cancel the active voice provider via
an idempotent activity using the persisted call SID, mark the attempt terminal, and test duplicate
success plus process restart.

### F-07 — P1 — Hosted smoke rejects the valid Agent Card

`deploy/scripts/smoke.sh:63-66` asserts a top-level `payload.url`. The customer Agent Card contract
stores the endpoint at `supportedInterfaces[0].url`
(`services/customer-agent/app/cards.py:15-20`), and its protocol test enforces that shape. Any deploy
that supplies `AGENT_BASE_URL` will fail smoke and trigger image rollback.

Required fix: validate `supportedInterfaces`, protocol binding/version, HTTPS URL, and expected
origin. Add a smoke-contract unit test against `customer_agent_card()` and run it before SSH deploy.

### F-08 — P1 — RecoveryBench root commands are broken

`package.json:32-34` points to nonexistent modules:

- `ml.recovery_bench.generate`
- `ml.training.train`
- `ml.evaluation.evaluate`

All three commands were executed and failed with `ModuleNotFoundError`. The implemented CLI is
`ml.recoverybench.build` (`ml/recoverybench/build.py:11-29`).

Required fix: either expose separate stable generate/train/evaluate entry points or update the root
scripts and README to a single `python -m ml.recoverybench.build` flow. Add the commands to CI and
verify deterministic artifacts without overwriting checked-in output unless explicitly requested.

### F-09 — P1 — Playwright never tests the service graph

`apps/web/e2e/playwright.config.ts:59-69` starts only Next and maps API/agent origins to fake paths
on the same dev server. `apps/web/e2e/support/fixtures.ts:21-62` and the safety suites fulfill
merchant, voice, and A2A mutations with `page.route`. The 24 passing checks are useful UI,
accessibility, and failure-state tests, but they cannot detect F-01, F-02, F-03, F-06, or F-07.

Required fix: retain the fast mocked project and add one Compose-backed Playwright project with
PostgreSQL, Temporal, API, worker, and customer-agent. It must reset/seed, approve one action, verify
one workflow/provider reference, consume/reject an A2A replay, reconcile success, and prove call or
outreach cancellation.

### F-10 — P2 — Public root is stale

`apps/web/src/app/page.tsx:20-23` says the “Phase 0 foundation” is online and links only to the design
system. The public URL does not lead a judge to `/login` or the seeded scenario. Make `/` the
judge-friendly entry/redirect and expose visible reset/status controls with simulated/test-verified
labels.

### F-11 — P2 — Customer-agent lifecycle is not durable/fully JSON-RPC-safe

`services/customer-agent/app/main.py:32-35` always uses `InMemoryTaskStore`, whose own docstring at
`services/customer-agent/app/store.py:19-25` says it is process-local. A restart loses task IDs,
idempotency, approvals, artifacts, and receipt state. Also,
`services/customer-agent/app/models.py:42-46` restricts methods in the FastAPI request model, so an
unknown method is rejected by FastAPI as HTTP 422 before the handler can return JSON-RPC `-32601`.

Use a durable store for hosted mode and accept/validate the JSON-RPC envelope inside the handler so
protocol errors remain JSON-RPC responses. The mock in-memory implementation can remain the local
default.

### F-12 — P2 — Nullable policy contract is narrowed in TypeScript

The API permits null quiet hours, contact limits, and approval thresholds
(`services/api/app/api/schemas.py:261-268`). The handwritten `PolicySettings` interface makes all of
them non-null (`apps/web/src/types/recovery.ts:85-93`), and the normalizer passes them through
unchanged (`apps/web/src/lib/api/recovery-client.ts:96-105`). A valid backend response can therefore
produce invalid input values and “Invalid amount” UI.

Generate/use the OpenAPI policy type directly or explicitly normalize null into a UI representation
that can round-trip “disabled.” Add a null-policy contract test.

### F-13 — P2 — Submission documentation does not match the product

README route examples at `README.md:827-850` document voice sessions, recovery-task endpoints, and
experiment endpoints that are not in the OpenAPI or built services. `README.md:1504-1506` still says
to choose a license; no license file exists. The README has no live URL and is still the long product
spec rather than a concise submission guide.

Update the API/setup commands from generated OpenAPI and actual customer-agent routes, choose/add
the license, and clearly separate local mock, Razorpay test, and credentialed voice gates.

### F-14 — P2 — Windows line endings break required local gates

This fresh Windows worktree has `core.autocrlf=true`, no `.gitattributes`, index LF, and working-tree
CRLF. `pnpm format:check` reports all 104 web files, while `bash scripts/security/scan-dependencies.sh`
fails at `set -Eeuo pipefail` because of `\r`. Linux CI checkouts are not affected, but the project
documents PowerShell local commands and the repository contract requires local validation.

Add a `.gitattributes` contract (at minimum LF for `*.sh`, source, JSON/YAML, and generated schema),
then renormalize once. Keep Prettier `endOfLine` explicit. Validate bootstrap/gates in Windows CI or
document WSL as a prerequisite.

### F-15 — P2 — Failure injection is not a complete demo surface

The backend exposes four Razorpay-oriented simulations, and Phase 4 has good deterministic tests for
other providers. `/lab` contains evaluation reports only; repository search found no UI caller for
`/v1/simulations/failure-injection`, nor one-click A2A/voice failure controls. Add safe, simulated
operator controls for each required demo and show deterministic expected/actual results without
mutating verified revenue.

### F-16 — P3 — Worker health is process-only

`infra/compose/compose.base.yml:54-59` checks only `os.kill(1, 0)`. A running but non-polling worker
can remain healthy. Add a heartbeat/readiness mechanism covering Temporal task polling and, when
enabled, durable outbox progress.

### F-17 — P3 — Test deprecation warning

The Python suite passes with one Starlette warning that `httpx` through `starlette.testclient` is
deprecated. Track the compatible FastAPI/Starlette migration before it becomes a hard failure.

## Acceptance-criteria audit

| Criterion                                       | Status                      | Evidence / reason                                                                 |
| ----------------------------------------------- | --------------------------- | --------------------------------------------------------------------------------- |
| Failure creates exactly one invoice-scoped case | Pass in isolation           | Webhook dedupe/outbox and case constraints/tests pass                             |
| Explainable diagnosis and bounded action        | Pass in isolation           | Domain/API tests and UI render the fixed enums/reasons                            |
| Policy allow/block/delay/approval               | Pass in isolation           | Policy suites pass; merchant settings persist                                     |
| Subscription-native payment surface             | **Fail**                    | Invoice-link adapter is covered; preferred card-update URL is missing (F-03)      |
| Verified success recovers once                  | Pass at SQL webhook layer   | Authoritative fetch and immutable recognition dedupe pass                         |
| Success cancels all pending work                | **Partial**                 | DB action rows cancel; active voice/provider work does not (F-06)                 |
| Control Tower and Case Workspace                | Pass                        | Unit, desktop/mobile Playwright, build routes pass                                |
| Complete audit timeline                         | **Partial**                 | API actions persist; Temporal mock audit events are process memory under F-01     |
| At least 100 deterministic synthetic cases      | Pass in code                | 100-case repeat hash matched; checked-in report uses 1,200 total / 240 evaluation |
| Batch commands work from README                 | **Fail**                    | All three root commands fail (F-08)                                               |
| Baseline/treatment comparison                   | Pass in Lab artifact        | Paired simulated metrics/checksum present; dashboard formulas still fail F-05     |
| Browser voice intents                           | Pass in mock/browser mode   | Safety precedence and UI tests pass                                               |
| Real guarded call                               | External gate plus code gap | Credentials absent; success cancellation is missing (F-06)                        |
| Separate A2A approval/rejection                 | Pass only within process    | Customer-agent tests pass; store is volatile (F-11)                               |
| Signed mandate verified and replay-safe         | **Fail end to end**         | Verifier unit tests pass; runtime is absent (F-02)                                |
| Complete failure demo                           | **Partial**                 | Deterministic suites pass; no complete one-click demo surface (F-15)              |
| Incremental/net recovered value is correct      | **Fail**                    | Dashboard formulas violate their definitions (F-05)                               |
| Single reset-and-seed demo                      | Partial                     | `pnpm reset` has coverage; root entry and service-backed judge E2E are missing    |

## Cross-service and protocol review

- **OpenAPI:** regeneration produced the same SHA-256
  `21C36DA9A94B667DCC88E0C577548CEDF70865E95D585CEB1991762887953D29` and no Git diff.
- **Generated TypeScript client:** regeneration produced no semantic Git diff; original bytes were
  restored after the line-ending-only diagnostic rewrite.
- **Migrations:** exactly one head, `27b4eb4b36a1`; the live local PostgreSQL database reports that
  head and `alembic check` reports no upgrade operations.
- **Money:** persisted and transport money fields reviewed are integer paise; no floating-point
  storage was found. Model probability/confidence floats are non-money.
- **Mandate schemas:** signer and verifier models align on the signed fields and canonical JSON;
  pinned-key, exact-scope, expiry, and concurrent replay tests pass. Runtime linkage fails F-02.
- **Voice schemas:** handwritten web response shapes match the current Pydantic response fields.
  Policy settings have the nullable mismatch in F-12.
- **A2A protocol:** Agent Cards and Send/Get/Cancel happy paths pass; invalid method behavior and
  durability fail F-11. The README's `request_hash` field is not implemented; exact signed scope is
  present, but documentation should either remove the field or implement it consistently.

## Temporal determinism review

- Workflow code uses `workflow.now`, durable wait conditions, typed signals, bounded activity
  timeouts, and a single-attempt provider-submission retry policy.
- Static inspection found no HTTP/provider/database imports or wall-clock/random calls in
  `services/worker/app/workflow.py`.
- Replay, duplicate-signal, late-success, opt-out, timeout, and uncertain-submission tests pass.
- Determinism itself passes; **runtime ownership does not**. F-01 and F-02 must be fixed without
  moving external calls or signature/SQL work into workflow code.

## Payment and revenue review

Passes:

- raw-body Razorpay HMAC validation, event-ID inbox dedupe, transactional outbox, and acknowledge-first
  ingestion;
- invoice/subscription/payment correlation and authoritative capture fetch;
- halted-only Payment Link guard, no partial payment, no provider notifications, bounded expiry,
  and stable reference IDs;
- duplicate/out-of-order/late capture convergence and one recognition per processed payment path.

Fails/risks: F-01, F-03, F-04, and F-05. Browser state is not used as payment truth.

## Telephony safety review

Passes in code/tests: real calls default off, explicit provider flag, operator token, server-side
allowlist, persisted consent, quiet hours, kill switch, one-active-call database index, ten/day
check, 180-second cap, recording-off constraints, signed Twilio/ElevenLabs callbacks, safety-first
intent precedence, immediate opt-out suppression, persisted call SID cancellation, and no automatic
retry after uncertain submission.

Fails/risks: F-01 and F-06. No credentialed call was placed in this audit; that remains an external
gate and must use only an allowlisted, pre-consented, team-owned number.

## Security and deployment review

Passes:

- current tracked source plus built browser assets pass the high-confidence secret scan;
- Gitleaks 8.30.1 scanned 62 commits / about 2.78 MB and found no leaks;
- `pnpm audit --prod --audit-level high` found no known production vulnerabilities;
- immutable image tags, ARM64 builds, pre-migration backup, destructive-migration source guard,
  one-head requirement, image-only rollback, protected environment files, read-only containers,
  dropped capabilities, resource limits, Caddy HTTPS/security headers, and HAProxy rate limits are
  present;
- repository tests covering deployment hardening and backup/restore pass as part of the 205-test
  Python suite.

Gaps:

- hosted deploy cannot pass until F-07 is fixed;
- local `pip-audit` was unavailable, though CI installs pinned `pip-audit==2.10.1`; rerun the CI
  dependency and Trivy image gates on the final merge;
- local staging/production Compose config requires protected server env files and therefore was not
  materialized in this read-only audit;
- the Windows CRLF problem in F-14 breaks local Bash gates even though Linux CI is expected to pass.

## Route and link audit

- All relative Markdown links in README and `docs/**` resolve to existing local paths.
- The production Next build succeeds and reports the routes listed in F-03.
- Eight principal external references were probed: Razorpay home/buildathon/API, A2A, Temporal,
  Next.js, and CatBoost returned HTTP 200. Razorpay Newsroom brand assets returned HTTP 403 to the
  automated client; this is consistent with access/bot protection and was not classified as a
  broken link.
- Missing/stale routes and entry points are covered by F-03, F-10, and F-13.

## Fresh-environment and validation record

Toolchain observed: Node `v22.18.0`, pnpm `10.15.1`, Python `3.12.10`, uv `0.8.15`.

| Command/check                          | Result                                                                                 |
| -------------------------------------- | -------------------------------------------------------------------------------------- |
| `pnpm install --frozen-lockfile`       | Pass; 527 packages from locked graph                                                   |
| `uv sync --frozen --all-groups`        | Pass                                                                                   |
| `pnpm lint`                            | Pass; ESLint and Ruff                                                                  |
| `pnpm format:check`                    | **Fail on Windows checkout**; 104 web files due CRLF (F-14)                            |
| `pnpm typecheck`                       | Pass; TypeScript and 173 Mypy source files                                             |
| `pnpm test`                            | Pass; 27 web tests and 205 Python tests, one warning                                   |
| `pnpm build`                           | Pass; 11 application routes                                                            |
| `pnpm e2e`                             | Pass; 24 desktop/mobile mocked Playwright checks (F-09 caveat)                         |
| OpenAPI export + generated client      | Pass; no semantic drift                                                                |
| Migration safety/head/current/check    | Pass; 4 migrations, one head, no drift                                                 |
| Repository/browser secret scan         | Pass                                                                                   |
| Gitleaks history scan                  | Pass; 62 commits, no leaks                                                             |
| `pnpm audit --prod --audit-level high` | Pass; no known vulnerabilities                                                         |
| 100-case deterministic generation      | Pass; repeated hash `5208ce90ffde9c466eae6cb2d5902c3016ee1dcb22061f4366f97a9b53e34e23` |
| RecoveryBench artifact checksum        | Pass; manifest and files match `f20ccfe...cb20cbf8`                                    |
| `pnpm generate:data`                   | **Fail**; nonexistent module (F-08)                                                    |
| `pnpm train`                           | **Fail**; nonexistent module (F-08)                                                    |
| `pnpm evaluate`                        | **Fail**; nonexistent module (F-08)                                                    |
| Bash dependency gate on Windows        | **Fail before scan**; CRLF (F-14); Node audit run separately                           |

The worktree was clean after all mutating generators/build tools were restored byte-for-byte. Test
caches, virtual environments, Node modules, `.next`, and Playwright diagnostics are ignored and are
not part of this audit commit.

## External credential and hosting gates

No relevant credential variables were present for OCI, Vercel, hosted PostgreSQL, Temporal Cloud,
Razorpay, Twilio, or ElevenLabs. Therefore the following remain **not executed**, not failed:

- public Vercel frontend plus OCI/Caddy origins;
- Neon staging/production branches and restore on the hosted database;
- Temporal Cloud namespace/task-queue connectivity;
- Razorpay signed test webhook, card update/invoice/payment-link payment smoke;
- hosted A2A origin callback/receipt flow;
- one real allowlisted Twilio/ElevenLabs call;
- staging-first GHCR/Trivy deploy, production promotion, and public monitoring.

Mock mode remains the correct default. Real provider enablement must wait until the code-level P0/P1
items pass locally, then use test/allowlisted credentials only.

## Final gate recommendation

The final code gate **cannot pass yet, even without external credentials**; credentials are not the
current blocker. Fix F-01 through F-09 first, then rerun:

1. frozen install, lint, normalized format, typecheck, unit/integration tests, and production build;
2. OpenAPI/client and Alembic drift gates;
3. a new Compose-backed service E2E that proves Temporal, A2A, payment, and cancellation ownership;
4. deployment smoke against the real Agent Card shape; and
5. security/dependency/container scans on the exact immutable image commit.

After those code gates pass, the project can be called **local/mock code-complete** without external
credentials. The public submission and credentialed Razorpay/A2A/telephony gates remain explicitly
separate and must not be represented as verified until executed.

---

## Remediation appendix — 2026-08-28 continuation

This appendix is a post-audit implementation review. It does not alter the findings or verdict for
the audited `phase-5-start` baseline. The statuses below describe the continuation branch after the
listed remediation work; a clean, combined final gate still has to be recorded after all branches are
integrated.

| Finding | Continuation status              | Remediation evidence                                                                                                                                                                                                        |
| ------- | -------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| F-01    | Remediated in code               | `956c0c4` routes merchant commands through the case workflow; `196d4bc` binds provider submission to the durable action; production mode composes SQL/provider activities while mock remains default.                       |
| F-02    | Remediated in code               | `5b0cae0` replaces the trusted boolean with activity verification and atomic nonce consumption; `bd19a74` adds exact authoritative `recovery.receipt.v1` delivery.                                                          |
| F-03    | Remediated in code               | `e50f532` adds the card-update Checkout route/configuration and safe test-mode path.                                                                                                                                        |
| F-04    | Remediated for hosted demo scope | `bba3e89` adds the server guard; `9df3e7d` and `ac15233` add a signed HttpOnly operator session, matching CSRF token, hosted enforcement, and malformed-cookie rejection. Production identity/multi-tenancy remains open.   |
| F-05    | Remediated in code               | `56650eb` separates verified and simulated recovery; `1d53555` derives verified gross and remaining at risk from immutable recognition records using integer paise.                                                         |
| F-06    | Remediated in code               | `35987e1`, `2377b9f`, and `fbeb6be` cancel outreach after authoritative recovery and preserve an uncertain/fail-closed result when cancellation cannot be confirmed.                                                        |
| F-07    | Remediated in code               | `87c080b` validates the actual A2A Agent Card interface in deployment smoke.                                                                                                                                                |
| F-08    | Remediated in code               | `3d90100` points the root RecoveryBench commands at the existing generator, trainer, and evaluator modules.                                                                                                                 |
| F-09    | Core concern remediated          | `7146ff1` and `cf16886` add the Compose-backed real-service Playwright gate; `ce9111d` and `df81d73` exercise persisted policy, SQL-backed A2A mandate, and receipt lifecycle. Credentialed hosted paths remain unexecuted. |
| F-10    | Remediated in code               | `5688e27` replaces the stale root with a judge-oriented entry and seeded demo guide.                                                                                                                                        |
| F-11    | Remediated in code               | `9adf351` and `8cf7bdc` add the SQL task store and migration; invalid methods use JSON-RPC errors and hosted modes select durable storage.                                                                                  |
| F-12    | Remediated in code               | `9aac1f1` aligns nullable disabled policy controls across the web/API contract.                                                                                                                                             |
| F-13    | Remediated in documentation      | `ae9d37a` replaces the stale README; this documentation continuation aligns architecture, operations, product, security, and release evidence with the integrated runtime.                                                  |
| F-14    | Remediated in repository policy  | `e50f532` adds explicit LF normalization for source/deployment files; the final frozen Windows/Linux gates must confirm the checkout.                                                                                       |
| F-15    | Remediated in product            | `8a742b2` adds the deterministic Failure Lab route for duplicate, out-of-order, late-success, and changed-state scenarios.                                                                                                  |
| F-16    | Remediated in code/deployment    | `b884b29` and `e4dde57` add loopback worker readiness based on active polling plus Temporal health and use it in Docker/Compose.                                                                                            |
| F-17    | Recheck at final gate            | No release claim depends on the warning; the final combined test record must state whether it remains.                                                                                                                      |

Additional post-audit payment hardening persists action/policy authorization before Temporal
dispatch (`752d457`, `28a092b`), reconciles replacement captures without reusing a failed payment ID
(`cab15a2`), and converges uncertain standard Payment Link submission by unique reference without a
blind retry (`dde510c`, `d2dec75`). `ba7ac69` classifies ambiguous transport, 5xx, malformed, and
incomplete provider responses as uncertain. `d3e6cfc` signs authoritative A2A receipts and verifies
the pinned recovery-agent key before task completion. `c8fd446` proves the hosted cross-origin
operator cookie/CSRF session in the real-service browser gate. `8769ff3` requires SQL-backed
customer-agent readiness through Compose, edge routing, deploy smoke, and monitoring. `2b6bff1`
makes the fixed-seed RecoveryBench CatBoost artifact byte-reproducible. RecoveryBench is composed
through the production worker scorer, and hosted customer-agent task state is SQL-backed.

The original external-gate conclusion is unchanged: no public URL or credentialed OCI, Neon,
Temporal Cloud, Razorpay, Twilio, or ElevenLabs success is claimed. The continuation can only be
called locally code-complete after the combined lint, format, typecheck, test, build, migration,
OpenAPI, service-E2E, and security gates pass on the integrated commit.

### Continuation closure

An independent re-audit of the integrated continuation found no P0 issue and one final P1: the
hosted Voice Console did not send the operator cookie/CSRF proof to its cross-origin API action.
`80aeee9` closed that gap without exposing the raw voice token and added browser/API tests for
session success plus anonymous, missing-CSRF, and wrong-CSRF rejection. `28a430f` publishes the
resulting OpenAPI and generated TypeScript contract.

The final local gate then passed with 336 Python tests, 43 web tests, 31 mock Playwright checks, one
Compose-backed service E2E, 12 product routes, 199-file Mypy coverage, and zero OpenAPI/client drift.
Repository/browser secret scanning, Gitleaks across 139 commits, migration/deployment checks, HAProxy
validation, and pnpm/Python production dependency audits also pass. The Python audit initially found
four advisories in `cryptography` 46.0.7; `f2cecce` upgrades it to 50.0.1 and the repeated hashed audit
reports no known vulnerabilities.

Accordingly, the continuation is locally/mock code-complete with no open P0/P1 finding. Trivy and all
public-hosting, Razorpay, A2A-origin, and allowlisted telephony demonstrations remain external gates
and are not represented as complete.
