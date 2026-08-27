# Real-service Playwright gate

Run the full FitBox gate from the repository root:

```bash
node scripts/e2e/run-service-stack.mjs
```

The runner allocates unused host ports and creates a unique Docker Compose
project. Its PostgreSQL volume is new for every run, then removed during clean
teardown. It never attaches to or resets the developer Compose project.

The gate performs the following checks without `page.route` or other network
interception:

- starts isolated PostgreSQL and Temporal services;
- applies Alembic migrations and reset-seeds FitBox;
- starts FastAPI, the Temporal worker, the customer-agent service, and Next;
- proves the Control Tower and case workspace loaded from the real API rather
  than the bundled fallback fixture;
- sends approval through the merchant UI and verifies the owning Temporal
  workflow received it;
- executes only the mock payment provider, then verifies database/workflow
  convergence and one revenue row after a duplicate success;
- checks the customer-agent SQL-backed readiness endpoint and published Agent Card;
- drives a second Temporal workflow through a real hosted A2A request, exact-scope
  customer approval, Ed25519 verification with a pinned test key, atomic SQL nonce
  consumption, mock payment-surface execution, fresh-client task retrieval, and
  deterministic replay rejection.

The A2A path uses the repository's deterministic mock signing key and mock
payment provider; no real payment or telephony action is enabled. All
real-provider flags are forced off. Set
`RECOVERYOS_SERVICE_E2E_KEEP_STACK=1` only for local diagnosis; the unique
Compose project name is printed so it can be removed explicitly afterward.

The coordinator should expose this runner through a root script (suggested
name: `e2e:service`) and call that script from the hosted/CI acceptance job.
