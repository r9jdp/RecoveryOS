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

Mock mode is the default and uses a deterministic development-only key. A hosted non-mock process
must set the real-signing flag and inject the seed from server-side secret storage.

## Lifecycle

1. `recovery.request.v1` creates an idempotent task in `TASK_STATE_AUTH_REQUIRED`.
2. The approval page repeats the exact merchant, case, amount in paise, currency, and payment surface.
3. Approval emits a signed, bounded `recovery.mandate.v1` artifact and moves the task to `WORKING`.
4. RecoveryOS verifies the pinned key and full scope, then atomically consumes the nonce.
5. A scoped `recovery.receipt.v1` message completes the task with the provider result.

The mock task store is process-local. Hosted multi-instance operation requires a durable task store;
nonce replay protection is already defined at the RecoveryOS API boundary using the coordinator-owned
`a2a_mandate_nonce_consumptions` PostgreSQL table.
