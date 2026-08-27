# Health endpoint contract

The API exposes three unversioned endpoints:

| Endpoint | Meaning | Dependencies | Failure status |
| --- | --- | --- | --- |
| `/health` | Compatibility alias for liveness | None | N/A |
| `/health/live` | Python process can serve HTTP | None | Container/runtime error |
| `/health/ready` | PostgreSQL query and Temporal namespace connection succeed | PostgreSQL, Temporal | HTTP 503 |

Caddy and Docker use liveness so a temporary managed-service outage does not
cause restart loops. Deployment smoke checks use readiness so a release cannot be
declared healthy while its database or workflow service is unusable.

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
    {"name": "database", "status": "ok", "latency_ms": 42},
    {"name": "temporal", "status": "unavailable", "latency_ms": 3001, "reason": "probe_failed"}
  ]
}
```

Customer-agent must implement the same liveness path before its container can be
enabled. A worker has no public HTTP surface; its container health check verifies
that PID 1 remains alive, while successful task-queue polling is verified in logs
and the Temporal UI.
