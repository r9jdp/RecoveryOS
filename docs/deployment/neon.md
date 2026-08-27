# Neon PostgreSQL setup

Neon is a managed external dependency; the repository does not create an account
or project. Create it manually in the intended organization.

## Required isolation

1. Create one project for RecoveryOS.
2. Create branches named `staging` and `production` from the same initial schema.
3. Create a distinct application role for each branch.
4. Create a distinct migration role with only the privileges Alembic requires.
5. Copy each branch's pooled application URL and direct migration URL into the
   corresponding host secret file. Do not put either URL in Vercel.

The application should use the pooled URL with TLS required. Deployment
migrations should use the direct URL. The coordinator owns the final environment
variable names and must map both values before enabling the migration step.

## Validation

From a protected administrator environment, not a browser shell:

```bash
psql "PRODUCTION_DIRECT_URL" -c "select current_database(), current_user"
psql "STAGING_DIRECT_URL" -c "select current_database(), current_user"
```

The database or branch identifiers and users must differ. Then deploy staging
and verify `/health/ready` performs `SELECT 1` successfully.

Neon may suspend inactive compute. A first readiness request can therefore be
slower than a warm request; deployment smoke checks retry for up to one minute.
Do not weaken readiness to liveness to hide an authentication or schema problem.

## Backup and recovery

- Record the provider's current retention/restore limits for the selected free
  plan before relying on them.
- Export a sanitized demo database before the final submission.
- Test restore into a new branch, run migrations, and point staging at the
  restored branch before declaring the recovery gate complete.
- Never restore production data into public staging.
