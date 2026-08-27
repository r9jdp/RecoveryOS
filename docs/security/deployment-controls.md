# Deployment security and budget controls

## Enforced controls

- Only ports 80/443 and restricted operator SSH enter OCI; PostgreSQL, Temporal, API, worker, and
  customer-agent ports are not published.
- Caddy terminates TLS. HAProxy is the sole application-stack member of the edge network and applies
  per-client request limits, mutation limits, one-MiB request bodies, bounded timeouts, and a global
  connection ceiling.
- Containers run read-only, drop Linux capabilities, disallow privilege escalation, use tmpfs, cap
  PIDs/memory/CPU, and rotate JSON logs.
- API, worker, and customer-agent images use immutable tags. Provider secrets are runtime-only and
  separated by service.
- Public demo preflight requires mock payment/voice/A2A, disables real mandate signing, rejects
  provider secrets, and preserves the ten-call/day ceiling even though calling is off.
- Deploy and rollback operations are serialized. Migrations are expand/contract checked,
  backup-first, single-head, and never automatically downgraded.

## Resource budget

| Service | Staging memory / CPU | Production memory / CPU |
| --- | ---: | ---: |
| API | 768 MiB / 0.75 | 1 GiB / 1.00 |
| Worker | 1 GiB / 1.00 | 1.5 GiB / 1.50 |
| Customer agent | 512 MiB / 0.50 | 768 MiB / 0.75 |
| HAProxy gateway | 128 MiB / 0.25 | 128 MiB / 0.25 |

Terraform rejects more than four A1 OCPUs, 24 GiB RAM, or a 200-GiB boot volume. Operators must
still account for aggregate tenancy use before `terraform apply`; a validation bound is not a billing
guarantee.

Provider budgets remain server-side: mock is default, Razorpay requires test mode, real voice needs
the explicit flag plus operator token and allowlist, calls are one concurrent/three minutes/ten per
day, and A2A real signing is independently disabled. Do not place any provider or operator secret in
`NEXT_PUBLIC_*` variables.

## Known production blocker

Rate limiting protects capacity but does not authenticate a merchant. The current shared demo scope
must not be promoted to production. Before production, the coordinator must add authenticated,
server-side operator sessions, merchant authorization on every mutation, CSRF/origin protections,
durable customer-agent task storage, and an audited emergency access path. Keep real provider flags
off until those controls pass E2E and threat-model review.
