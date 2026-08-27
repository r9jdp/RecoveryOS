# Database backup and restore verification

RecoveryOS takes a custom-format PostgreSQL backup immediately before every Alembic upgrade. The
backup command reads `DATABASE_URL` from the protected migration environment without sourcing it as
shell code. A short-lived PostgreSQL 17 client container receives the URL through a mode-0600
temporary env file, and both the temporary file and partial dump are removed on failure.

## Create a backup

```bash
bash deploy/scripts/backup.sh staging
```

The script writes a `.dump` plus `.dump.sha256` beneath
`/var/lib/recoveryos/staging/backups`. It validates the archive catalog with `pg_restore --list`
before atomically publishing the filename. Copy both files to encrypted off-host storage with a
retention policy approved for customer/payment metadata. A backup that exists only on the app VM is
not disaster recovery.

## Prove restoration

Run after every schema release and at least monthly:

```bash
bash deploy/scripts/verify-restore.sh \
  /var/lib/recoveryos/staging/backups/recoveryos-staging-TIMESTAMP.dump
```

The verifier checks the checksum, starts a uniquely named PostgreSQL 17 container with tmpfs-only
storage and no host port, restores with `--exit-on-error`, and requires a valid Alembic revision and
public schema. Its cleanup trap removes the exact `recoveryos-restore-verify-*` container. It never
connects to staging or production.

## Production recovery decision

Production restoration is intentionally not scripted because it is destructive. A database owner
must first:

1. Disable public mutations and workers while preserving evidence.
2. Confirm the exact affected database/branch and incident timestamp.
3. Prefer the managed Neon point-in-time/branch recovery mechanism when available.
4. Restore the dump into a new, empty database or Neon branch; never restore over the live URL.
5. Run migration revision, row-count, idempotency, and payment/revenue reconciliation checks.
6. Point a temporary app stack at the restored branch and run the hosted smoke/E2E suite.
7. Switch application configuration only after two-person review and preserve the old branch.

Do not use a browser callback, webhook count, or UI total as proof that recovered payment accounting
is correct. Reconcile authoritative provider objects and the idempotent revenue ledger.
