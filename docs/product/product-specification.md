# Product specification

Version: Phase 5 submission candidate, 2026-08-28.

## Problem and outcome

A failed subscription renewal is not one state: the payment attempt, invoice, subscription,
customer contact, recovery case, and revenue evidence can move independently. RecoveryOS creates one
invoice-scoped case, explains the failure, chooses one bounded action, applies deterministic merchant
policy, waits for authoritative provider evidence, and stops duplicate or unsafe work.

The target outcome is recovered arrears with an auditable explanation and zero duplicate financial
or contact action. Subscription reactivation is recorded separately and is not implied by arrears
collection.

## Primary persona and seeded scenario

The primary user is a merchant operations reviewer. The seeded FitBox scenario contains Aarav's Pro
Fitness Plan, a ₹1,499 renewal (`149900` paise), an authentication failure, voice consent, and an
available mock customer agent. Authentication is a shared demo placeholder; the server currently
selects `merchant_fitbox`, so this is not a production multi-tenant system.

## Product surfaces

| Route             | Purpose                                                                          |
| ----------------- | -------------------------------------------------------------------------------- |
| `/login`          | deterministic demo entry                                                         |
| `/dashboard`      | revenue, diagnosis, active-case, policy, timeline and case-table control tower   |
| `/cases/[caseId]` | diagnosis, evidence, policy, alternatives, payment surface and audit workspace   |
| `/approvals`      | human review queue                                                               |
| `/settings`       | quiet hours, contact limits, approval threshold/actions and merchant kill switch |
| `/lab`            | versioned RecoveryBench simulated evaluation                                     |
| `/voice`          | browser rehearsal and guarded operator-call controls                             |
| `/a2a/[taskId]`   | exact-scope customer approval                                                    |
| `/design-system`  | visual and component review surface                                              |

The frontend falls back explicitly to deterministic fixtures when configured API reads fail. That
fallback is labelled and must never be mistaken for provider-verified state.

## Decision contract

Actions are limited to:

```text
WAIT_FOR_GATEWAY_RETRY
OPEN_CUSTOMER_PAYMENT_SURFACE
START_VOICE
SEND_TO_CUSTOMER_AGENT
ESCALATE_TO_HUMAN
STOP
```

Customer payment surfaces are limited to subscription card update, subscription invoice link, and
a halted-only standard Payment Link. Policy may allow, block, delay, or require manual approval.
Kill switches, terminal/captured state, suppressions, recovery deadline, active gateway retries,
contact limits, quiet hours, and human-approval rules are evaluated before execution.

## Functional requirements and current status

| Requirement               | Implemented behavior                                                   |
| ------------------------- | ---------------------------------------------------------------------- |
| One case per failed cycle | database uniqueness and idempotent webhook processing                  |
| Explainable diagnosis     | deterministic Razorpay field mapping with stored evidence              |
| Safe recommendation       | fixed action vocabulary, expected value/utility, rejected alternatives |
| Provider-owned payment    | no generic retry/charge API; customer-present surfaces only            |
| Payment truth             | verified webhook plus authoritative fetch; no browser truth            |
| Duplicate safety          | inbox/outbox, signal, callback, mandate and revenue deduplication      |
| Customer safety           | opt-out, wrong-person, dispute and already-paid precedence             |
| Merchant control          | approvals, settings, kill switch, stop and escalation                  |
| Durable recovery          | Temporal timers/signals/cancellation and replay tests; mock activities |
| Evaluation                | fixed-seed paired cohorts, calibrated model, simulated metrics         |

## Evidence and metrics

Money is integer paise. Verified recovered revenue accepts authoritative provider evidence only.
Synthetic incremental recovery is a separate simulated metric. The checked-in RecoveryBench report
contains 240 evaluation cases from a 1,200-case paired dataset, PR-AUC, Brier score, calibration,
top-decile lift, amount-weighted lift, and recovery by action.

## Non-goals and release blockers

This release does not support live payments, anonymous real actions, debt collection, discounts,
stored payment credentials, autonomous LLM execution, production authentication, or production
multi-tenancy. A public mock demo must disable Razorpay, voice, A2A delegation, and real mandate
signing. Production additionally requires durable customer-agent tasks, CSRF/origin hardening,
privacy and retention controls, India telephony/DLT review, monitored hosted infrastructure, and
provider production approval.

The provider adapters are not yet composed into the Temporal worker entry point, and the approved
A2A mandate is not yet bridged from customer-agent polling through verification into a workflow
signal. Those code-integration gaps must close before a hosted real-provider journey can be claimed.
