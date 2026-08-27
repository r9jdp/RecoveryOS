# API error, pagination, and filtering conventions

Status: frozen for Phase 0 on 2026-08-27.

## Structured errors

Every non-2xx API response uses one envelope. The HTTP status communicates the
transport category; `error.code` is the stable application contract.

```json
{
  "error": {
    "code": "CASE_ALREADY_RECOVERED",
    "message": "This recovery case is already terminal.",
    "field": null,
    "metadata": {"case_id": "case_fitbox_aug_2026"}
  },
  "request_id": "req_01J6B7A6QY",
  "correlation_id": "corr_fitbox_001"
}
```

Rules:

- Codes use uppercase `SNAKE_CASE` and are never reused with a different meaning.
- Messages are safe for an operator; do not include provider secrets or raw PII.
- Validation errors set `field` to a JSON-pointer-like path when possible.
- `metadata` contains only documented, non-secret diagnostic fields.
- Accept `X-Request-Id` when valid or generate one. Propagate a single
  `correlation_id` through API, outbox, workflow, provider, and audit events.
- Expected conflicts use errors, not silent `200` responses. Duplicate webhook
  delivery is the exception: after durable deduplication it is acknowledged.

Initial common codes:

```text
VALIDATION_FAILED
RESOURCE_NOT_FOUND
VERSION_CONFLICT
IDEMPOTENCY_CONFLICT
CASE_ALREADY_RECOVERED
CASE_RECOVERY_WINDOW_EXPIRED
POLICY_BLOCKED
MANUAL_APPROVAL_REQUIRED
PROVIDER_UNAVAILABLE
PROVIDER_STATE_UNCERTAIN
WEBHOOK_SIGNATURE_INVALID
WEBHOOK_EVENT_DUPLICATE
PAYMENT_STATE_CHANGED
```

## Cursor pagination

List endpoints accept:

```text
limit=25                 # default 25, minimum 1, maximum 100
cursor=<opaque-token>    # absent on the first page
sort=-opened_at          # endpoint-specific allowlist; '-' means descending
```

Response:

```json
{
  "items": [],
  "page": {
    "next_cursor": null,
    "has_more": false,
    "limit": 25
  }
}
```

Cursors are opaque, versioned, and URL-safe. They encode a stable tie-breaker
such as `(opened_at, id)`. Invalid or expired cursors return
`VALIDATION_FAILED`; clients must not inspect cursor contents.

## Filtering

Filters use explicit repeated query parameters rather than a free-form query
language. Examples:

```text
case_outcome=OPEN&case_outcome=ESCALATED
diagnosis=AUTHENTICATION_REQUIRED
subscription_state=PENDING
opened_from=2026-08-27T00:00:00Z
opened_to=2026-08-28T00:00:00Z
```

Unknown filters, sort fields, and enum values fail with `VALIDATION_FAILED`.
Merchant scope comes from server-side authorization, never from a browser-sent
merchant ID alone. All dates are ISO 8601 UTC.

