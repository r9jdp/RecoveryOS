# Temporal Cloud setup

Temporal Cloud is used so the worker remains durable while the OCI VM hosts the
long-running process. Credits or promotional access are not a permanent free
tier; record the account's expiry and decommission date before development.

## Manual provisioning

1. Create two namespaces in the Singapore region (or the nearest region allowed
   by the account): one for staging and one for production.
2. Create a separate scoped API key for each namespace.
3. Store each address, namespace, and API key only in its matching VM secret
   file.
4. Use different task queues, for example `recovery-os-staging` and
   `recovery-os-production`.
5. Set TLS on for every cloud connection.

Required runtime values are conceptually:

```text
TEMPORAL_ADDRESS=<account endpoint>:7233
TEMPORAL_NAMESPACE=<environment namespace>
TEMPORAL_TASK_QUEUE=<environment task queue>
TEMPORAL_TLS=true
TEMPORAL_API_KEY=<scoped secret>
```

The coordinator owns the canonical root environment contract; these deployment
templates must be reconciled with it before integration.

## Validation

- API `/health/ready` connects to the selected namespace.
- The worker logs a successful poll on exactly the expected task queue.
- A seeded workflow started in staging never appears in production.
- Revoking the staging key makes staging not-ready but leaves production healthy.
- Credentials are redacted from logs and never returned by health responses.

## Cost and exit gate

Set provider budget alerts and record a calendar date before promotional credit
expires. At that date, either fund Temporal Cloud, migrate deliberately to a
supported self-hosted topology, or shut it down. An unnoticed conversion to paid
usage is a NO-GO condition for the free-only plan.
