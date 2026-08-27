# RecoveryOS customer authorization agent

This is a separate A2A 1.0 service that collects explicit customer approval for one exact
recovery surface. It returns an Ed25519-signed `recovery.mandate.v1` DataPart; it never calls a
payment provider or treats a browser callback as proof of payment.

## Local process

From this directory, with the repository environment installed:

```powershell
uv run uvicorn app.main:app --host 0.0.0.0 --port 8010
```

The Dockerfile uses the same `app.main:app` entry point. Its public service endpoints are:

- `GET /.well-known/agent-card.json`
- `POST /rpc` for `SendMessage`, `GetTask`, and `CancelTask`
- `GET /v1/tasks/{task_id}/approval`
- `POST /v1/tasks/{task_id}/approval`
- `GET /health/live` and `GET /health/ready`

The wire shape follows the current [A2A specification](https://github.com/a2aproject/A2A/blob/main/docs/specification.md), including PascalCase JSON-RPC methods and the standard Agent Card URI.

## Server-only configuration

| Variable | Purpose |
| --- | --- |
| `CUSTOMER_AGENT_ORIGIN` | Public HTTPS origin advertised in the Agent Card |
| `CUSTOMER_AGENT_WEB_ORIGIN` | Browser origin allowed to use the approval API |
| `CUSTOMER_AGENT_SIGNER_KEY_ID` | Stable identifier pinned by the RecoveryOS verifier |
| `CUSTOMER_AGENT_ED25519_PRIVATE_KEY` | Base64url-encoded 32-byte Ed25519 seed |
| `CUSTOMER_AGENT_REAL_SIGNING_ENABLED` | Requires the configured private key when true |
| `CUSTOMER_AGENT_REQUEST_TTL_SECONDS` | Maximum signed-mandate lifetime, default 900 seconds |
| `CUSTOMER_AGENT_TASK_STORE` | `memory` by default; set `sql` explicitly for hosted durability |
| `CUSTOMER_AGENT_DATABASE_URL` | Server-only PostgreSQL URL required when the task store is `sql` |

Mock mode is the default and uses a deterministic development-only key. A hosted non-mock process
must set the real-signing flag, inject the seed from server-side secret storage, select the SQL
task store, and apply the coordinator-owned database migration. Readiness reports only the store
kind and availability; it never includes the connection URL.

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

1. `recovery.request.v1` creates an idempotent task in `TASK_STATE_AUTH_REQUIRED`.
2. The approval page repeats the exact merchant, case, amount in paise, currency, and payment surface.
3. Approval emits a signed, bounded `recovery.mandate.v1` artifact and moves the task to `WORKING`.
4. RecoveryOS verifies the pinned key and full scope, then atomically consumes the nonce.
5. A scoped `recovery.receipt.v1` message completes the task with the provider result.

The mock task store is process-local. Hosted multi-instance operation uses the durable task store;
nonce replay protection remains at the RecoveryOS API boundary using the coordinator-owned
`a2a_mandate_nonce_consumptions` PostgreSQL table.
