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

The client transports A2A messages and task state. It does not treat
`AUTH_REQUIRED` as authorization. Only a verified, exact, unexpired, unconsumed
`recovery.mandate.v1` artifact can authorize use of the already-bound payment
surface, and the customer still completes the payment.

All provider calls carry an idempotency key when the vendor operation supports
one. Provider results preserve the vendor reference needed for reconciliation
but exclude raw credentials and sensitive customer data.

