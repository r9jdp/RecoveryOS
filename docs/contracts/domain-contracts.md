# RecoveryOS domain contracts

Status: frozen for Phase 0 on 2026-08-27.

## Case identity

A recovery case represents one merchant's failed subscription invoice or, when
Razorpay has not supplied an invoice ID, one explicit billing cycle. Persistence
must enforce one of these uniqueness constraints:

```text
(merchant_id, failed_invoice_id) where failed_invoice_id is not null
(merchant_id, subscription_id, billing_cycle_key) where failed_invoice_id is null
```

`payment_id` is not the case key. A billing cycle can produce several attempts,
and a retry can succeed under a different payment ID. `subscription.pending`
may not include enough evidence to identify an invoice or payment; consumers
must correlate it to an existing case or retain it as an unmatched inbox event.
They must not manufacture identifiers.

## Independent state axes

| Axis | Purpose |
| --- | --- |
| `case_outcome` | Whether RecoveryOS is still working the case and its terminal result |
| `payment_state` | Latest authoritative state of the relevant payment |
| `subscription_state` | Latest authoritative Razorpay subscription lifecycle state |
| `contact_disposition` | Latest customer-contact outcome or suppression signal |
| `revenue_attribution` | Evidence class supporting recognized recovery revenue |

These axes are intentionally not collapsed. A late `payment.captured` can coexist
with `OPTED_OUT`; the payment closes financial work, while the opt-out continues
to suppress outreach. A captured payment can collect arrears while the
subscription remains pending or halted. Accordingly, store these facts
separately:

```text
case_recovered
arrears_collected_paise
subscription_reactivated
```

Revenue is idempotent on `(merchant_id, provider_event_id)` and is recognized
only from a provider event plus authoritative reconciliation. Browser callbacks
are never evidence of payment success. Simulator output uses `SIMULATED`; it
must never contribute to verified merchant revenue.

## Action vocabulary

The fixed action values are:

```text
WAIT_FOR_GATEWAY_RETRY
OPEN_CUSTOMER_PAYMENT_SURFACE
START_VOICE
SEND_TO_CUSTOMER_AGENT
ESCALATE_TO_HUMAN
STOP
```

`WAIT_FOR_GATEWAY_RETRY` means Razorpay owns the retry. RecoveryOS schedules a
reconciliation timer; it does not charge a failed payment ID. Opening a customer
surface requires exactly one subtype:

```text
SUBSCRIPTION_CARD_UPDATE
SUBSCRIPTION_INVOICE_LINK
STANDARD_PAYMENT_LINK
```

Prefer subscription-native surfaces. A `STANDARD_PAYMENT_LINK` is a separate
payment and is allowed only after policy confirms the subscription is halted and
automatic retries cannot race it. The adapter must disable partial collection
and provider notifications, bound expiry to the recovery deadline, use a unique
deterministic reference of at most 40 characters, and include the case and
invoice IDs in notes. Payment-Link success still requires reconciliation of the
original subscription invoice and subscription state.

## Money and time

- Monetary values are integer paise; floats are forbidden.
- Persist timestamps as timezone-aware UTC instants.
- Probabilities are decimal values in `[0, 1]`; they are not money.
- Use `expected_recovered_paise` for probability-weighted gross recovery.
- Use `expected_utility_paise` after costs, friction, and risk penalties.

The FitBox example is internally consistent:

```text
0.71 × 149900 paise = 106429 paise expected recovered
106429 - 1500 paise costs/penalties = 104929 paise expected utility
```

