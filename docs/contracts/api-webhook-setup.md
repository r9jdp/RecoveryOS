# API and webhook setup

The canonical machine contract is `packages/contracts/openapi.json`; TypeScript declarations are
generated into `apps/web/src/lib/api/schema.d.ts`. Recovery and customer Agent Cards intentionally
sit outside the recovery OpenAPI contract.

## Local setup

Prerequisites are Node 22, pnpm 10.15.1, Python 3.12, uv, Docker, and Docker Compose. From the
repository root:

```powershell
pnpm bootstrap
pnpm infra
$env:DATABASE_URL = "postgresql+psycopg://recovery:recovery@localhost:55432/recovery_os"
$env:TEMPORAL_ADDRESS = "localhost:7233"
uv run alembic -c services/api/alembic.ini upgrade head
pnpm reset
pnpm dev:api
pnpm dev:worker
pnpm dev:customer-agent
pnpm dev:web
```

Keep the database and Temporal variables in every API/worker/migration terminal; `.env.example` is a
contract template and is not loaded automatically by the processes. The development origins are web `http://localhost:3000`, API/docs
`http://localhost:8000/docs`, customer agent `http://localhost:8010`, and Temporal UI
`http://localhost:8233`. Run each long-lived command in its own terminal. Mock payment and voice are
the default; A2A delegation and real mandate signing are off.

## Recovery API surface

| Group           | Endpoints                                                                                 |
| --------------- | ----------------------------------------------------------------------------------------- |
| Health          | `GET /health`, `/health/live`, `/health/ready`                                            |
| Operator        | `POST /v1/operator/session`                                                               |
| Demo            | `GET /v1/demo/fixtures/{fixture_name}`                                                    |
| Dashboard/cases | `GET /v1/dashboard/metrics`, `/v1/recovery-cases`, case detail and timeline               |
| Decisions       | recommend, approve, reject, command, safety-disposition, stop and escalate case routes    |
| Policy          | `GET` and `PUT /v1/policy-settings`                                                       |
| Mock            | payment-surface and payment-success routes under `/v1/mock/recovery-cases/{case_id}`      |
| Simulation/lab  | `POST /v1/simulations/failure-injection`, `GET /v1/lab/reports/latest` or `/{version}`    |
| Voice           | contact, browser transcript, timeline, intent and signed webhook routes under `/v1/voice` |
| Razorpay        | `POST /v1/webhooks/razorpay`                                                              |

Use `/docs` or the checked-in OpenAPI document for request/response schemas. List pagination uses
`limit` plus an opaque cursor; filtering supports repeated case outcome, diagnosis, and subscription
state parameters plus UTC opened-time bounds. Structured application errors follow
[the API conventions](./api-conventions.md).

## Razorpay test webhook

Set server-side values only:

```text
PAYMENT_PROVIDER=razorpay
RECOVERY_ACTIVITY_MODE=production
RECOVERY_ALLOW_REAL_PAYMENT_ACTIONS=true
RAZORPAY_KEY_ID=rzp_test_...
RAZORPAY_KEY_SECRET=...
RAZORPAY_WEBHOOK_SECRET=...
RAZORPAY_TEST_MODE_REQUIRED=true
```

Consequential non-mock API calls require operator authentication. A server-side smoke runner may
send the configured `OPERATOR_DEMO_TOKEN` in `X-RecoveryOS-Operator-Token`. Browser clients must
instead call `POST /v1/operator/session` with the configured operator email/password. The API
returns the CSRF token and sets the signed `recoveryos_operator_session` HttpOnly cookie; subsequent
consequential requests send the cookie plus `X-RecoveryOS-CSRF-Token`. The raw credential is never
stored in browser-accessible state.

Hosted staging/production set `OPERATOR_AUTH_REQUIRED=true` and `OPERATOR_COOKIE_SECURE=true`.
Non-mock payment mode also turns authorization on regardless of that explicit flag. Use non-default,
server-only values for `OPERATOR_DEMO_TOKEN` and `OPERATOR_SESSION_SECRET`; session/action guards
reject the checked-in local defaults in real-action mode. The current session represents a shared
demo operator, not production identity or tenant authorization.

Configure the provider endpoint as `https://<api-origin>/v1/webhooks/razorpay` for
`payment.failed`, `subscription.pending`, `subscription.halted`, `subscription.charged`,
`payment.captured`, and `payment_link.paid`. Delivery must include `X-Razorpay-Signature` and
`X-Razorpay-Event-Id`.

The API verifies HMAC over the untouched request bytes before JSON parsing, normalizes the event,
and atomically writes webhook inbox and outbox records. It returns HTTP 202 with `accepted`,
`duplicate`, inbox/outbox IDs, and acknowledgement timing. Processing happens asynchronously. A
duplicate is acknowledged using the original durable records. Do not transform, re-serialize, or
log the body before verification.

Captured/payment-link success is not accepted from the browser. The outbox processor fetches
authoritative provider state before changing payment/revenue state. Keep test-mode enforcement on;
the adapter rejects a non-`rzp_test_` key while that gate is true.

## A2A setup

The Recovery Agent exposes `/.well-known/agent-card.json` and `/a2a/rpc`. The separate customer
agent exposes `/.well-known/agent-card.json`, `/rpc`, approval GET/POST routes, and health endpoints.
Both JSON-RPC directions require `A2A-Version: 1.0` and the recovery-mandate extension URI advertised
by their Agent Cards. Enable delegation only after pinning the customer-agent public key in
`CUSTOMER_AGENT_PUBLIC_KEYS_JSON`. Hosted modes set `CUSTOMER_AGENT_TASK_STORE=sql` and require a
server-only `CUSTOMER_AGENT_DATABASE_URL`; memory is the local default. Never share the
customer-agent Ed25519 private seed with the API or worker. The recovery worker verifies and
atomically consumes the exact mandate, then sends an idempotent `recovery.receipt.v1` only after
authoritative payment recovery.

## Contract validation

```powershell
pnpm generate:openapi
git diff --exit-code packages/contracts/openapi.json
pnpm generate:client
pnpm typecheck
```

The final command checks the generated client consumer. Generated files and root manifests are
coordinator-owned.
