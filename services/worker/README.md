# RecoveryOS Temporal worker

The worker exposes loopback-only health endpoints on port `8001` for its
container health check:

- `GET /health/live` returns `200` while the worker process can serve probes. It
  never calls a downstream dependency.
- `GET /health/ready` returns `200` only after the SDK worker is polling and a
  bounded Temporal service health check succeeds. Before polling, after worker
  shutdown, or while Temporal is unavailable it returns a sanitized `503`.

The endpoint should remain private on the worker host. Mock activity providers remain the default,
and readiness does not require Razorpay, A2A, or telephony credentials.
