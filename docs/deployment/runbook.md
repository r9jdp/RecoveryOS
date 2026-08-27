# Build, deploy, smoke, and rollback

All release images are immutable Git-derived tags. Never deploy `latest`.

## 1. Build and publish ARM64 images

The CI workflow owned by the coordinator should grant `contents: read` and
`packages: write`, authenticate to GHCR, and invoke:

```bash
echo "$GHCR_TOKEN" | docker login ghcr.io -u "$GHCR_USER" --password-stdin
bash deploy/scripts/build-and-push.sh OWNER recoveryos "sha-${GITHUB_SHA}"
```

The script builds `linux/arm64` API, worker, and customer-agent images. On a local
non-ARM workstation, Docker Buildx may use emulation; CI is the source of release
artifacts. Never pass provider credentials to `docker build`.

On the VM, authenticate with a separate token that has read-only package access:

```bash
read -rsp "GHCR token: " GHCR_READ_TOKEN
printf '%s' "$GHCR_READ_TOKEN" | docker login ghcr.io -u GITHUB_USER --password-stdin
unset GHCR_READ_TOKEN
```

## 2. Install a release checkout

Place a clean checkout at `/opt/recoveryos/current`. The deploy user must be able
to read it but secrets must remain under `/etc/recoveryos`:

```bash
sudo install -d -m 0755 -o recoveryos -g recoveryos /opt/recoveryos/current
git clone --depth 1 https://github.com/OWNER/recoveryos.git /opt/recoveryos/current
```

For private repositories, use a read-only deploy key. Verify the checked-out
commit matches the image labels before deployment.

## 3. Validate Compose without starting containers

```bash
IMAGE_TAG=sha-COMMIT \
API_ENV_FILE=/etc/recoveryos/staging/api.env \
WORKER_ENV_FILE=/etc/recoveryos/staging/worker.env \
CUSTOMER_AGENT_ENV_FILE=/etc/recoveryos/staging/customer-agent.env \
docker compose \
  --env-file /etc/recoveryos/staging/compose.env \
  -f infra/compose/compose.base.yml \
  -f infra/compose/compose.staging.yml config --quiet

CADDY_ENV_FILE=/etc/recoveryos/edge/caddy.env \
docker compose -f infra/compose/compose.edge.yml config --quiet
bash deploy/scripts/preflight.sh staging
```

Run the equivalent config check for production. The edge stack creates the
shared `recoveryos-edge` network; both application stacks attach with unique DNS
aliases, so they can coexist without binding application ports on the host.

## 4. Deploy staging

```bash
bash deploy/scripts/deploy.sh \
  staging sha-COMMIT \
  https://staging-api.example.com \
  https://staging-agent.example.com
```

The deploy sequence is:

1. Host/configuration preflight.
2. Reconcile the shared Caddy edge.
3. Pull all images by immutable tag.
4. Run Alembic before application replacement.
5. Start containers and wait for Docker health.
6. Probe API liveness/readiness and agent liveness/Agent Card through HTTPS.
7. Record the successful tag for rollback.

The coordinator must place Alembic configuration at
`/workspace/services/api/alembic.ini` or update the single migration invocation
in `deploy.sh`. Migrations must follow expand/contract compatibility: the prior
image must remain usable after an upgrade or automatic image rollback is unsafe.

After staging passes its hosted E2E suite, run the same command for production
with production origins.

## 5. Rollback

Automatic rollback restores the previous application images when migration,
startup, or smoke checks fail. It does not and must not automatically downgrade
the database.

To restore a known image explicitly:

```bash
bash deploy/scripts/rollback.sh \
  production sha-PREVIOUS \
  https://api.example.com \
  https://agent.example.com
```

If a migration is not backward-compatible, stop and use the documented database
restore procedure rather than running an Alembic downgrade under pressure.

## 6. Operational checks

```bash
docker compose -f infra/compose/compose.edge.yml ps
IMAGE_TAG=sha-COMMIT \
API_ENV_FILE=/etc/recoveryos/production/api.env \
WORKER_ENV_FILE=/etc/recoveryos/production/worker.env \
CUSTOMER_AGENT_ENV_FILE=/etc/recoveryos/production/customer-agent.env \
docker compose \
  --env-file /etc/recoveryos/production/compose.env \
  -f infra/compose/compose.base.yml \
  -f infra/compose/compose.production.yml ps
curl -fsS https://api.example.com/health/ready
```

Inspect logs with explicit service names and short time windows. Never paste full
environment output or `docker inspect` into shared logs because it can expose
runtime secrets.

## GitHub Actions integration request

The coordinator owns CI files. The release workflow must:

- Trigger only from protected release commits/tags.
- Run tests before image publication.
- Build with `deploy/scripts/build-and-push.sh`.
- Sign or attest images when repository policy supports it.
- SSH to the VM using a scoped deploy key.
- Deploy staging, run hosted smoke/E2E, then require approval for production.
- Serialize deployments per environment.
- Retain the prior immutable tag for rollback.
