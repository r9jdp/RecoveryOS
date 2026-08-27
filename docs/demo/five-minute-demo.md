# Five-minute demo script

This script is deterministic and safe in mock mode. Do not enter real provider credentials or use a
real phone number. Reset with `pnpm reset`, then start local infrastructure, API, worker,
customer-agent, and web processes as described in [API setup](../contracts/api-webhook-setup.md).

## 0:00–0:40 — Frame the problem

Open `/login`, enter the demo, and land on `/dashboard`.

Say: “A failed renewal is not just a failed payment. Payment, subscription, customer intent, and
revenue evidence can disagree. RecoveryOS keeps those states separate and chooses a safe next step.”

Point out the FitBox ₹1,499 at-risk case and the `SIMULATED`/mock evidence label.

## 0:40–1:45 — Explain one decision

Open the FitBox case workspace. Show:

- the failed invoice/billing-cycle identity;
- `AUTHENTICATION_REQUIRED` evidence;
- the bounded card-update/invoice recovery recommendation;
- policy reasons and rejected gateway retry;
- independent payment and subscription states;
- the audit timeline.

Say: “The model recommends. The policy engine authorizes. No React component decides whether money
or contact is allowed.”

## 1:45–2:25 — Merchant control and safety

Open Settings/Approvals. Show quiet hours, contact cap, approval threshold/actions, and the kill
switch. Return to the case and briefly show dispute, already-paid, wrong-person, and opt-out actions.
Do not mutate the primary case yet.

Say: “Customer safety outranks recovery utility, and already-paid triggers reconciliation rather
than another collection attempt.”

## 2:25–3:05 — Voice and A2A

Open `/voice`. Submit “Please stop calling me” in browser rehearsal and show `OPT_OUT`, contact-must-
end behavior, and the real-call gate. Explain that actual Twilio calling is disabled by default and
would also require operator authorization, allowlist, consent, time, concurrency and daily limits.

For A2A, open a seeded/local task at `/a2a/{taskId}` if the task service is running. Show the exact
merchant, ₹1,499 amount, case, surface and confirmation checkbox. Explain that approval produces a
short-lived Ed25519 mandate and that the database consumes its nonce once. Do not claim the browser
approval itself completed a payment.

## 3:05–3:45 — Close the recovery loop

Back in the case, approve the mock customer-present surface, then use the seeded mock-success path
or the judge journey. Show the case as recovered, cancellation of pending work, and one recognized
revenue entry even when the success event is delivered twice.

Say: “Only authoritative backend evidence closes the financial loop. Duplicate delivery converges
to one outcome and one revenue record.”

## 3:45–4:30 — RecoveryBench

Open `/lab`. Show the 1,200 fixed-seed paired cases, CatBoost/isotonic version and checksum, PR-AUC,
Brier score, calibration, lift, and action table.

Say: “These metrics are simulated incremental recovery. They never modify merchant revenue, and the
production loop still works with a deterministic fallback if the model is missing.”

## 4:30–5:00 — Reliability and honest close

Show the timeline or failure checklist and summarize duplicate/out-of-order webhook, late success,
mandate replay, voice callback duplication, timeout, circuit-breaker, backup/restore, and deployment
gates.

Close with: “The complete mock path is local and deterministic. Hosted Razorpay test verification,
one allowlisted real call, and public URLs remain credential-dependent gates; no live URL or
production readiness is claimed.”

## Presenter fallback

If the API is unavailable, the web app displays the bundled FitBox fixtures with a clear fallback
warning. Use that to continue the product tour, but skip any claim about persisted mutations. The
checked-in screenshots under `apps/web/public/evidence/phase-4/` provide desktop/mobile backup
evidence.
