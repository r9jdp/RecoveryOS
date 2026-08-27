# Staged deployment and rollback

This runbook is the production release contract. Release images use immutable Git-derived tags;
`latest` is never accepted. Staging and production run as separate Compose projects behind the
shared Caddy edge. HAProxy is the only application-stack service attached to the edge network, so
the API and customer-agent containers cannot be addressed from the host or public network.

## Safety boundary

HAProxy 3.2.22 is pinned to an official image tag and manifest digest and enforces the following per forwarded client
IP before requests reach Python:

| Surface        | All requests | Mutations | Maximum body |
| -------------- | -----------: | --------: | -----------: |
| Recovery API   |   240/minute | 60/minute |        1 MiB |
| Customer agent |   120/minute | 30/minute |        1 MiB |

These are abuse/load-shedding controls, not user authentication. Production launch remains blocked
until the application has durable authenticated operator sessions and merchant authorization.

## Host preparation

The release checkout must be `/opt/recoveryos/current`, state must be under
`/var/lib/recoveryos`, and protected configuration must be under `/etc/recoveryos`. All environment
files must be regular non-symlink files with mode `0600` or `0400`.

Before a public mock-demo deploy, export the explicit safety-gate switch:

```bash
export RECOVERYOS_PUBLIC_DEMO=true
```

This makes preflight reject real Razorpay, voice, A2A, or mandate-signing configuration and reject
provider secrets in public-demo service files. It is intentionally separate from application
environment files, so a real-provider staging smoke test cannot be mislabeled as a public demo.

## Release sequence

Deploy staging from the exact release checkout:

```bash
export RECOVERYOS_RELEASE_ROOT=/opt/recoveryos/current
bash deploy/scripts/deploy.sh \
  staging sha-COMMIT \
  https://staging-api.example.com \
  https://staging-agent.example.com
```

The script acquires an environment-specific file lock and then:

1. Validates the ARM64 host, protected files, disk budget, migration source, Compose files, and
   HAProxy configuration.
2. Reconciles the shared Caddy edge and pulls immutable application images.
3. Creates and validates a PostgreSQL custom-format backup.
4. Rejects multiple Alembic heads and runs the upgrade exactly once.
5. Replaces app containers, waits for Docker health, then tests public liveness/readiness, the
   deployed API version, customer-agent liveness, and the Agent Card.
6. Atomically records current, previous, and pre-migration-backup state.

Only after hosted staging E2E passes should the same command target production. CI must serialize
each environment and require a protected production approval.

## Rollback

Restore the recorded prior immutable image without changing database state:

```bash
bash deploy/scripts/rollback.sh \
  production "" \
  https://api.example.com \
  https://agent.example.com
```

Or provide an explicitly reviewed tag in argument two. Rollback is safe only when migrations follow
expand/contract compatibility. The deployment checker rejects common destructive upgrade operations,
but review remains mandatory. Never run `alembic downgrade` as an incident response shortcut.

If old application images cannot run against the upgraded schema, stop the app and follow
`docs/runbooks/database-backup-restore.md` with a database owner. Do not automate production restore.

## Post-deploy evidence

Capture without dumping environments or Docker inspection output:

```bash
docker compose -f infra/compose/compose.edge.yml ps
bash deploy/scripts/smoke.sh \
  https://api.example.com \
  https://agent.example.com \
  sha-COMMIT
```

Record the immutable tag, migration revision, backup path/checksum, smoke result, and operator. Do
not paste provider payloads, environment contents, transcripts, or customer identifiers into CI.

## CI wiring status

`.github/workflows/deploy.yml` runs the full local validation gate, builds and scans immutable ARM64
images, deploys/smokes staging, and promotes the same commit only through the production environment.
Repository operators must configure protected environment approval, a scoped SSH deploy key, and
environment-specific public origins. A separate hosted Playwright run after staging is not yet wired;
it remains a manual release gate. Run `RECOVERYOS_PUBLIC_DEMO=true` only for the public mock demo.
