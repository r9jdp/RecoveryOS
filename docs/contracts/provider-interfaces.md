# Provider interface contracts

Provider ports live under `services/api/app/providers`. Application services
and Temporal activities depend on these ports; adapters depend on vendor SDKs.
Temporal workflow code must never invoke a provider directly.

## `PaymentProvider`

Capabilities are limited to opening a customer-present payment surface and
fetching authoritative state. There is intentionally no generic charge or retry
method. Razorpay owns retries while a subscription is pending.

The customer callback URL is navigation only. A provider webhook followed by an
authoritative fetch determines payment, arrears, and subscription states.

## `VoiceProvider`

The caller persists a `VoiceContactAttempt` before invoking `start_contact`.
`UNCERTAIN` submission is never retried blindly because the first request may
have placed a real call. Reconciliation uses `fetch_contact`; cancellation is
best effort and is always followed by persisted suppression when appropriate.

## `RecoveryScorer`

The scorer returns both expected gross recovery and expected utility. The
application owns policy and action execution. A missing model must fall back to
a deterministic scorer; it must not stop the recovery loop.

## `CustomerAgentClient`

The client transports A2A 1.0 JSON-RPC messages and durable task state. A
`recovery.request.v2` binds the task to the persisted `recovery_action_id`, the exact
`failed_invoice_id`, amount, currency, and payment surface. Reusing an idempotency key with a
different request is a conflict. Live service calls carry the server-only
`CUSTOMER_AGENT_S2S_BEARER_TOKEN`; the customer-agent rejects an unauthenticated request before
parsing JSON and advertises the HTTP Bearer scheme in its Agent Card.

`AUTH_REQUIRED` is not authorization. Customer approval routes use a stateless, task-scoped HMAC
capability delivered in the approval URL fragment. The browser removes it from the visible URL and
forwards it in `Authorization: Bearer`; it is never sent as an API query parameter. Approval still
requires an explicit decision matching the stored request. Optional OpenAI language interpretation
is advisory: it receives customer text plus display-only case context, returns structured intent
with `authorization_effect=NONE`, and cannot approve, sign, or execute a payment.

The capability and service signature are application authorization controls, not proof of a
legally verified customer identity and not a Razorpay/RBI payment mandate. The current operator
workspace receives the capability through restricted workflow audit data for manual delivery and
testing; anyone with that audit access can exercise it. Production customer-consent claims require
a direct authenticated customer-delivery channel and removal of the raw capability from
merchant-visible audit data.

Only a verified, exact, unexpired `recovery.mandate.v2` artifact whose nonce/claim is atomically
consumed can authorize use of the already-bound action and invoice. The customer still completes
the provider-owned payment surface. After authoritative recovery, the client sends a pinned-key
Ed25519 `recovery.receipt.v2` carrying the same `recovery_action_id` and `failed_invoice_id`; a
missing, changed-scope, or replay-conflicting receipt cannot complete the customer task.

All provider calls carry an idempotency key when the vendor operation supports
one. Provider results preserve the vendor reference needed for reconciliation
but exclude raw credentials and sensitive customer data.
