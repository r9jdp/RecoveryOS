# Health endpoint contract

The API exposes three unversioned endpoints:

| Endpoint        | Meaning                                                    | Dependencies         | Failure status          |
| --------------- | ---------------------------------------------------------- | -------------------- | ----------------------- |
| `/health`       | Compatibility alias for liveness                           | None                 | N/A                     |
| `/health/live`  | Python process can serve HTTP                              | None                 | Container/runtime error |
| `/health/ready` | PostgreSQL query and Temporal namespace connection succeed | PostgreSQL, Temporal | HTTP 503                |

HAProxy/Caddy and the API/customer-agent container restart checks use liveness so a temporary
managed-service outage does not cause restart loops. Deployment smoke checks use readiness so a
release cannot be declared healthy while its database, workflow service, or durable task store is
unusable. The worker container is the exception: its loopback-only check uses active readiness to
avoid treating an idle Python PID as a healthy Temporal poller.

The FastAPI application factory must include the router once:

```python
from app.health import health_router

app.include_router(health_router)
```

Readiness needs `psycopg`, `temporalio`, `DATABASE_URL`, `TEMPORAL_ADDRESS`, and
`TEMPORAL_NAMESPACE`. Temporal Cloud also needs `TEMPORAL_TLS=true` and its scoped
API key. The probe timeout defaults to three seconds and can be changed with
`HEALTHCHECK_TIMEOUT_SECONDS`.

Example unavailable response:

```json
{
  "status": "not_ready",
  "service": "recoveryos-api",
  "version": "sha-abcdef0",
  "timestamp": "2026-08-27T10:00:00+00:00",
  "components": [
    { "name": "database", "status": "ok", "latency_ms": 42 },
    {
      "name": "temporal",
      "status": "unavailable",
      "latency_ms": 3001,
      "reason": "probe_failed"
    }
  ]
}
```

## Customer-agent and worker

The customer agent exposes `/health/live` plus `/health/ready`. Readiness checks its selected task
store and reports only the store kind (`memory` or `sql`); hosted modes select SQL so a missing
migration or unavailable database returns HTTP 503 without exposing the database URL.

The worker has no public HTTP surface. It binds a small health server to
`127.0.0.1:8001` inside its container:

| Endpoint        | Meaning                                                                   | Failure status          |
| --------------- | ------------------------------------------------------------------------- | ----------------------- |
| `/health/live`  | worker process and loopback health server can respond                     | Container/runtime error |
| `/health/ready` | Temporal worker is running and the Temporal service health probe succeeds | HTTP 503                |

The hosting platform must probe `/health/ready`, so a worker that has stopped polling or cannot
reach Temporal is unhealthy even if its process still exists. Responses use
sanitized `not_polling` or `probe_failed` reasons; provider credentials and connection details are
never returned.
