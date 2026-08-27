# Build, deploy, smoke, and rollback

All release images are immutable Git-derived tags. Never deploy `latest`. The hardened operational
contract is also summarized in [staged deployment](../runbooks/staged-deployment.md); destructive
database recovery follows [database backup and restore](../runbooks/database-backup-restore.md).

## 1. Build and publish ARM64 images

The coordinator-owned deployment workflow grants `contents: read` and `packages: write`,
authenticates to GHCR, and invokes the same build script shown here:

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

The API image includes Alembic configuration at `/workspace/services/api/alembic.ini`.
Migrations must follow expand/contract compatibility: the prior image must remain usable after an
upgrade or automatic image rollback is unsafe. The deploy script creates and validates a backup,
rejects common destructive upgrade operations, and requires exactly one Alembic head before upgrade.

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

## GitHub Actions status

`.github/workflows/deploy.yml` currently:

- is manually dispatched and serializes by target environment;
- reruns lint, types, unit, build, Playwright, repository, dependency, and history gates;
- builds and pushes immutable ARM64 images with `deploy/scripts/build-and-push.sh`;
- scans all three images with Trivy before deployment;
- deploys and smokes staging over a scoped SSH action; and
- promotes the same commit to a protected production environment only when requested.

The workflow does not currently run a separate hosted Playwright job after staging deployment, and
image signing/attestation is not configured. Treat both as open release hardening work; do not claim
the staging-hosted E2E gate from the pre-deploy local Playwright run.
