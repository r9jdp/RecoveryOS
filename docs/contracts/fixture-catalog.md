# Contract fixture catalog

Fixtures are deterministic examples, not copied production events. They contain
no real customer data or credentials.

## Razorpay webhook matrix

`services/api/tests/fixtures/razorpay/manifest.json` declares the expected event
and state mapping for:

- `payment.failed`
- `subscription.pending`
- `subscription.halted`
- `subscription.charged`
- `payment.captured`
- `payment_link.paid`

The provider event ID is intentionally metadata beside each payload because in
production it arrives in the `X-Razorpay-Event-Id` header. Deduplication scope is
merchant/account plus that header. Raw-body signature verification occurs before
JSON normalization.

`subscription.pending.json` intentionally contains no payment or invoice. It
tests abstention: consumers may update a known subscription state but must not
infer a failure diagnosis or create an invoice-scoped case without correlation
evidence.

## Frontend screen fixtures

Version `screens.v1` includes:

| File | Route/use |
| --- | --- |
| `dashboard.json` | `/dashboard` Control Tower |
| `case-detail.json` | `/cases/[caseId]` workspace |
| `ml-lab.json` | `/lab` evaluation report |
| `customer-voice.json` | Browser voice/text fallback |
| `customer-agent.json` | Customer A2A approval screen |

Frontend work can consume these JSON files while OpenAPI generation is pending.
The files use domain enum wire values and integer paise. When generated API types
become available, the coordinator should validate these fixtures against the
corresponding response schemas without changing their semantic content.

