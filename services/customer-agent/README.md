# RecoveryOS customer authorization agent

This is a separate A2A 1.0 service that collects explicit customer approval for one exact
recovery surface. It returns an Ed25519-signed `recovery.mandate.v2` DataPart; it never calls a
payment provider or treats a browser callback as proof of payment.
It only completes a task after verifying an Ed25519-signed `recovery.receipt.v2` from a pinned
RecoveryOS recovery-agent identity.

## Local process

From this directory, with the repository environment installed:

```powershell
uv run uvicorn app.main:app --host 0.0.0.0 --port 8010
```

Its public service endpoints are:

- `GET /.well-known/agent-card.json`
- `POST /rpc` for `SendMessage`, `GetTask`, and `CancelTask`
- `GET /v1/tasks/{task_id}/approval`
- `POST /v1/tasks/{task_id}/approval`
- `POST /v1/tasks/{task_id}/interpretation` for advisory customer-language interpretation
- `GET /health/live` and `GET /health/ready`

The wire shape follows the current [A2A specification](https://github.com/a2aproject/A2A/blob/main/docs/specification.md), including PascalCase JSON-RPC methods and the standard Agent Card URI.

## Server-only configuration

| Variable                                         | Purpose                                                                                                         |
| ------------------------------------------------ | --------------------------------------------------------------------------------------------------------------- |
| `CUSTOMER_AGENT_ORIGIN`                          | Public HTTPS origin advertised in the Agent Card                                                                |
| `CUSTOMER_AGENT_WEB_ORIGIN`                      | Browser origin allowed to use the approval API                                                                  |
| `CUSTOMER_AGENT_SIGNER_KEY_ID`                   | Stable identifier pinned by the RecoveryOS verifier                                                             |
| `CUSTOMER_AGENT_ED25519_PRIVATE_KEY`             | Base64url-encoded 32-byte Ed25519 seed                                                                          |
| `CUSTOMER_AGENT_REAL_SIGNING_ENABLED`            | Requires the configured private key when true                                                                   |
| `CUSTOMER_AGENT_S2S_BEARER_TOKEN`                | Shared server-only bearer credential required with real signing                                                 |
| `CUSTOMER_AGENT_APPROVAL_TOKEN_SECRET`           | High-entropy server secret used to derive task-scoped browser approval capabilities; required with real signing |
| `CUSTOMER_AGENT_REQUEST_TTL_SECONDS`             | Maximum signed-mandate lifetime, default 900 seconds                                                            |
| `CUSTOMER_AGENT_TASK_STORE`                      | `memory` by default; set `sql` explicitly for hosted durability                                                 |
| `CUSTOMER_AGENT_DATABASE_URL`                    | Server-only PostgreSQL URL required when the task store is `sql`                                                |
| `CUSTOMER_AGENT_RECEIPT_VERIFICATION_MODE`       | `mock` locally; hosted environments must use `pinned`                                                           |
| `CUSTOMER_AGENT_RECOVERY_AGENT_PUBLIC_KEYS_JSON` | Server-only JSON map of accepted recovery-agent receipt signer IDs to Ed25519 public keys                       |
| `LLM_PROVIDER`                                   | `disabled` by default; set to `openai` to enable language interpretation                                        |
| `OPENAI_API_KEY`                                 | Server-only OpenAI API key; required when `LLM_PROVIDER=openai`                                                 |
| `OPENAI_MODEL`                                   | Responses API model ID; required when `LLM_PROVIDER=openai`                                                     |
| `CUSTOMER_AGENT_LLM_TIMEOUT_SECONDS`             | Bounded provider timeout, default 8 seconds (range 1–30)                                                        |

The worker uses `RECOVERY_AGENT_RECEIPT_SIGNING_MODE=mock` locally. Hosted workers set it to
`configured`, then provide `RECOVERY_AGENT_RECEIPT_SIGNER_KEY_ID` and the server-only
`RECOVERY_AGENT_RECEIPT_ED25519_PRIVATE_KEY`. The matching public key is pinned in the customer
agent; it is not learned from an incoming message or HTTP header.

Mock mode is the default and uses a deterministic development-only key. A hosted non-mock process
must set the real-signing flag, inject the seed from server-side secret storage, select the SQL
task store, and apply the coordinator-owned database migration. Readiness reports only the store
kind and availability; it never includes the connection URL.

## Customer approval capability

For a protected task, the A2A response returns an approval path shaped like
`/a2a/{task_id}#token=<task-scoped-capability>`. The capability is an HMAC derived from the exact
task identity using `CUSTOMER_AGENT_APPROVAL_TOKEN_SECRET`; it is distinct from the S2S credential
and grants access only to that approval task. The URL fragment is not sent in the HTTP navigation
request.

The customer frontend reads the fragment once, removes it from the visible URL, keeps the token in
memory, and forwards it as `Authorization: Bearer <task-scoped-capability>` to the approval summary,
language interpretation, and explicit decision routes. Those APIs do not accept the capability in
the query string. Access fails after request expiry, and sensitive task details are no longer
available through the approval route after a decision. Do not copy it into general-purpose logs,
persist it in browser storage, or substitute
`CUSTOMER_AGENT_S2S_BEARER_TOKEN`; the latter authenticates trusted service-to-service RPC only.

This capability proves possession of the approval link; the Ed25519 artifact proves that the
configured customer-agent service issued it. Neither proves a legally verified customer identity
or creates a Razorpay/RBI recurring e-mandate. The current RecoveryOS workspace carries the link in
its restricted workflow audit so an operator can deliver/test it, which also means an operator or
audit reader can exercise that capability. A production deployment that needs customer-consent
assurance must replace that handoff with a direct, authenticated customer channel and redact the
raw capability from merchant-visible audit data.

## Advisory language interpretation

`POST /v1/tasks/{task_id}/interpretation` accepts a customer text message or voice transcript and
uses the OpenAI Responses API to return a typed `APPROVE`, `REJECT`, `ASK_QUESTION`, or `UNCLEAR`
intent, integer confidence basis points, and a short plain-language explanation. The request uses
`store: false`, a strict JSON schema, and a bounded HTTP timeout. Exact amount and payment-surface
fields are intentionally excluded from the model input. The model receives only sanitized,
database-derived merchant/plan, normalized case/invoice/subscription state, preferred language,
and due/deadline context. Exact authorization scope is attached to the response only from the
trusted task record as `authoritative_scope`.

Interpretation is advisory: the response always has `authorization_effect: "NONE"` and
`requires_explicit_approval: true`. It does not change task state or create an artifact, even when
the interpreted intent is `APPROVE`. Only the existing exact-scope
`POST /v1/tasks/{task_id}/approval` path can call the Ed25519 signer after explicit confirmation.
If the configured provider times out, rejects the request, or returns invalid structured output,
the endpoint returns an error; it never substitutes a keyword-based approval or another automatic
fallback. With `LLM_PROVIDER=disabled`, the endpoint returns HTTP 503.

## Durable task-store contract

The SQL adapter persists the complete task payload, including signed mandate artifacts, message
history, and payment receipts. `idempotency_key` is database-unique, while a monotonically
increasing `version` provides optimistic concurrency for approval, cancellation, and receipt
updates. The cancellation path retries version conflicts so a simultaneous approval cannot erase a
requested cancellation.

The coordinator migration must create `customer_agent_tasks` with these columns and constraints:

- `task_id VARCHAR(96)` primary key
- `idempotency_key VARCHAR(255)` not null and unique as
  `uq_customer_agent_tasks_idempotency_key`
- `state VARCHAR(64)` not null
- `payload JSON` not null
- `version INTEGER` not null with default `1` and check constraint `version >= 1` named
  `ck_customer_agent_tasks_version_positive`
- `created_at TIMESTAMP WITH TIME ZONE` and `updated_at TIMESTAMP WITH TIME ZONE`, both not null
- composite index `ix_customer_agent_tasks_state_updated` on `(state, updated_at)`

Application startup does not create this table. `/health/ready` returns HTTP 503 with
`store: "sql"` when either the database or the migration is unavailable.

## Lifecycle

1. Authenticated A2A `recovery.request.v2` creates an idempotent task in
   `TASK_STATE_AUTH_REQUIRED`; reuse of its key with changed scope is rejected.
2. The fragment-delivered task capability is removed from the URL and forwarded as an HTTP Bearer
   token; the approval page then repeats the exact merchant, case, amount in paise, currency, and
   payment surface.
3. Approval emits a signed, bounded `recovery.mandate.v2` artifact, including the exact durable
   recovery-action and failed-invoice IDs, and moves the task to `WORKING`.
4. RecoveryOS verifies the pinned key and full scope, then persists an idempotent nonce claim tied
   to that action. Identical Temporal activity retries recover the same claim; changed replay fails.
5. RecoveryOS signs the complete receipt scope—receipt/task/mandate IDs, merchant, case, integer
   amount, currency, captured provider reference, state, and observation time—with Ed25519.
6. The customer agent verifies the pinned signer and exact mandate scope before a
   `recovery.receipt.v2` message can complete the task. Exact replays are idempotent; changed
   payloads using the same receipt/message ID are rejected.

The mock task store is process-local. Hosted multi-instance operation uses the durable task store;
nonce replay protection remains at the RecoveryOS API boundary using the coordinator-owned
`a2a_mandate_nonce_consumptions` PostgreSQL table.
