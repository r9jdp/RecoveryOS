#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: bash deploy/scripts/verify-restore.sh <backup.dump>" >&2
  exit 64
fi

backup_file="$1"
if [[ ! -f "$backup_file" || -L "$backup_file" ]]; then
  echo "Backup must be a regular file, not a symlink: ${backup_file}" >&2
  exit 1
fi
backup_file="$(cd "$(dirname "$backup_file")" && pwd -P)/$(basename "$backup_file")"
checksum_file="${backup_file}.sha256"
if [[ ! -f "$checksum_file" ]]; then
  echo "Checksum sidecar is missing: ${checksum_file}" >&2
  exit 1
fi

(
  cd "$(dirname "$backup_file")"
  sha256sum --check "$(basename "$checksum_file")"
)

container_name="recoveryos-restore-verify-$$"
password="local-restore-verification-only"
cleanup() {
  if [[ "$container_name" == recoveryos-restore-verify-* ]]; then
    docker rm --force "$container_name" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

docker run --detach --rm \
  --name "$container_name" \
  --tmpfs /var/lib/postgresql/data:rw,noexec,nosuid,size=768m \
  --env POSTGRES_PASSWORD="$password" \
  --env POSTGRES_DB=recoveryos_restore_verify \
  postgres:17-alpine@sha256:18cfe3ef5e6815560c98237d6216d1e5119702fb0f3894c8785dd58b8bbe5d73 >/dev/null

for _ in {1..30}; do
  if docker exec "$container_name" pg_isready \
    --username postgres --dbname recoveryos_restore_verify >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker exec "$container_name" pg_isready \
  --username postgres --dbname recoveryos_restore_verify >/dev/null

docker cp "$backup_file" "${container_name}:/tmp/recoveryos.dump"
docker exec --env PGPASSWORD="$password" "$container_name" \
  pg_restore --exit-on-error --no-owner --no-acl \
  --username postgres --dbname recoveryos_restore_verify /tmp/recoveryos.dump

revision="$(docker exec --env PGPASSWORD="$password" "$container_name" \
  psql --username postgres --dbname recoveryos_restore_verify \
  --tuples-only --no-align --command 'SELECT version_num FROM alembic_version LIMIT 1')"
table_count="$(docker exec --env PGPASSWORD="$password" "$container_name" \
  psql --username postgres --dbname recoveryos_restore_verify \
  --tuples-only --no-align --command \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")"

if [[ -z "$revision" || ! "$table_count" =~ ^[0-9]+$ || "$table_count" -lt 2 ]]; then
  echo "Restore verification failed structural checks." >&2
  exit 1
fi
echo "Restore verified in an ephemeral database at revision ${revision} (${table_count} public tables)."
