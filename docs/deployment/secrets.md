# Server-side secret layout

Secrets are installed on the OCI host after provisioning. They are never built
into images, passed as Docker build arguments, committed, or exposed through
`NEXT_PUBLIC_*` variables.

## Host paths

```text
/etc/recoveryos/
├── edge/caddy.env
├── staging/compose.env
├── staging/api.env
├── staging/worker.env
├── staging/customer-agent.env
├── staging/migration.env
├── production/compose.env
├── production/api.env
├── production/worker.env
├── production/customer-agent.env
└── production/migration.env
```

`caddy.env` contains only the ACME email and four domain names. Each
`compose.env` contains non-secret Compose interpolation such as `STACK_SLUG`,
`DEPLOYMENT_ENV`, `GHCR_OWNER`, and `GHCR_REPOSITORY`. Each service env file
contains only the minimum credentials that service needs. In particular, the
customer agent must not receive Razorpay, Twilio, or ElevenLabs secrets, and the
API must not receive the mandate signing private key. The migration file
overrides `DATABASE_URL` with the direct Neon URL only for the one-shot Alembic
container; it is not loaded into the long-running API.

The coordinator owns the canonical environment-variable contract. Do not create
ad-hoc names here; reconcile database, Temporal, payment, A2A, voice, and signing
variables with that contract before the first deploy.

## Installation

Create files without echoing values into shell history:

```bash
sudo install -d -m 0750 -o root -g recoveryos /etc/recoveryos/{edge,staging,production}
sudo install -m 0600 -o recoveryos -g recoveryos /dev/null /etc/recoveryos/edge/caddy.env
sudo install -m 0600 -o recoveryos -g recoveryos /dev/null /etc/recoveryos/staging/compose.env
sudo install -m 0600 -o recoveryos -g recoveryos /dev/null /etc/recoveryos/staging/api.env
sudo install -m 0600 -o recoveryos -g recoveryos /dev/null /etc/recoveryos/staging/worker.env
sudo install -m 0600 -o recoveryos -g recoveryos /dev/null /etc/recoveryos/staging/customer-agent.env
sudo install -m 0600 -o recoveryos -g recoveryos /dev/null /etc/recoveryos/staging/migration.env
sudo install -m 0600 -o recoveryos -g recoveryos /dev/null /etc/recoveryos/production/compose.env
sudo install -m 0600 -o recoveryos -g recoveryos /dev/null /etc/recoveryos/production/api.env
sudo install -m 0600 -o recoveryos -g recoveryos /dev/null /etc/recoveryos/production/worker.env
sudo install -m 0600 -o recoveryos -g recoveryos /dev/null /etc/recoveryos/production/customer-agent.env
sudo install -m 0600 -o recoveryos -g recoveryos /dev/null /etc/recoveryos/production/migration.env
sudoedit -u recoveryos /etc/recoveryos/staging/api.env
```

Repeat `sudoedit` for each file. Do not paste secret values into tickets, agent
prompts, screenshots, or command arguments.

## Operational notes

- Docker Compose environment values are visible to the Docker daemon and users
  with Docker access. The dedicated deploy user is therefore privileged and must
  be tightly controlled.
- Use separate provider keys per environment and minimum provider scopes.
- Rotate a credential immediately if it appears in a log or shell transcript.
- After rotation, force-recreate affected containers and verify the revoked value
  no longer authenticates.
- Health endpoints return only `probe_failed`; they do not return exception text,
  hosts, namespaces, or credentials.
- Back up secret files only into an encrypted secret manager. Do not include them
  in VM snapshots intended for sharing.
