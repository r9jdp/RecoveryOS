# Failure demonstration checklist

Run in mock mode from a reset seed. Record the command, result, timestamp, commit, and evidence class.
Never use browser state as financial proof.

| Scenario                             | Trigger or evidence                     | Required result                                                                   |
| ------------------------------------ | --------------------------------------- | --------------------------------------------------------------------------------- |
| Duplicate Razorpay webhook           | ingestion/outbox reliability tests      | one inbox/outbox identity; duplicate acknowledged; one action/revenue record      |
| Out-of-order failure after capture   | payment projection/reconciliation tests | captured state does not regress; stale event remains auditable                    |
| Late payment success                 | workflow/payment reliability tests      | cancel outreach/timers; recover once; count revenue once                          |
| Changed provider state               | authoritative reconciliation test       | hinted success rejected when fetch disagrees; no accounting mutation              |
| Temporal retryable timeout           | worker reliability tests                | bounded retry succeeds or exhausts predictably                                    |
| Uncertain provider submit            | Razorpay/voice reliability tests        | submit once; open circuit/fallback reason; reconcile instead of retry             |
| Replayed A2A mandate                 | mandate E2E/reliability tests           | first valid nonce consumed; replay rejected; no second surface                    |
| Changed mandate scope                | A2A tests                               | amount, merchant, case, task or surface mismatch rejected                         |
| A2A timeout                          | circuit-breaker test                    | structured fallback; case not falsely authorized                                  |
| Voice busy/no-answer                 | voice projection tests                  | terminal disposition recorded; no blind retry                                     |
| Duplicate Twilio/ElevenLabs callback | voice reliability tests                 | receipt deduplicated; one state transition/suppression                            |
| Opt-out                              | browser safety path and voice test      | suppression persists; active contact ends; future outreach blocked                |
| Dispute/already paid/wrong person    | Playwright safety paths                 | automation stops or reconciles/escalates; no new collection                       |
| Kill switch                          | settings/judge journey                  | new recovery actions blocked; reconciliation still available                      |
| Stale database writer                | optimistic concurrency test             | compare-and-swap conflict; later state preserved                                  |
| Migration/deploy failure             | deployment hardening tests              | backup first; destructive change blocked; images roll back, DB does not downgrade |
| Backup corruption                    | restore verifier/checksum tests         | restore rejected before use                                                       |

## Automated local gate

```powershell
uv run pytest services/api/tests/reliability services/worker/tests/reliability
uv run pytest tests/deployment tests/e2e/test_reset_reseed.py
pnpm e2e
```

The full browser suite contains 24 checks across desktop/mobile judge, safety, network, keyboard,
accessibility, and visual paths. The native accessibility checks are targeted structural/keyboard
gates, not a claim of complete WCAG conformance.

## Release evidence gate

- Run the full suite twice after reset and compare deterministic results.
- Confirm there is no duplicate call, payment action, mandate consumption, or revenue entry.
- Confirm screenshots show `SIMULATED` unless a credentialed Razorpay test reconciliation was
  actually completed.
- Do not label any item `RAZORPAY TEST VERIFIED` until the hosted test-mode webhook plus
  authoritative-fetch path succeeds.
- Do not run real-call demonstrations without an allowlisted, pre-consented, team-owned number and
  the documented operator controls.
