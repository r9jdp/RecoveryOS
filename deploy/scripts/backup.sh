#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: bash deploy/scripts/backup.sh <staging|production>" >&2
  exit 64
fi
deployment_env="$1"
case "$deployment_env" in
  staging|production) ;;
  *) echo "Deployment environment must be staging or production." >&2; exit 64 ;;
esac

repo_root="${RECOVERYOS_RELEASE_ROOT:-/opt/recoveryos/current}"
config_root="${RECOVERYOS_CONFIG_ROOT:-/etc/recoveryos}"
state_root="${RECOVERYOS_STATE_ROOT:-/var/lib/recoveryos}"
if [[ "$repo_root" != /* || "$repo_root" == "/" || "$config_root" != /* || "$config_root" == "/" || "$state_root" != /* || "$state_root" == "/" ]]; then
  echo "Release, configuration, and state roots must be specific absolute paths." >&2
  exit 64
fi
migration_env="${config_root}/${deployment_env}/migration.env"
backup_dir="${state_root}/${deployment_env}/backups"

if [[ ! -f "$migration_env" || -L "$migration_env" ]]; then
  echo "Migration environment must be a regular protected file: ${migration_env}" >&2
  exit 1
fi
for command_name in docker python3 sha256sum date install; do
  command -v "$command_name" >/dev/null || {
    echo "Missing required command: ${command_name}" >&2
    exit 1
  }
done

install -d -m 0750 "$backup_dir"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)-$$"
backup_name="recoveryos-${deployment_env}-${timestamp}.dump"
temporary_name=".${backup_name}.partial"
temporary_env="$(mktemp "${backup_dir}/.pg-env.XXXXXX")"
cleanup() {
  rm -f -- "$temporary_env" "${backup_dir}/${temporary_name}"
}
trap cleanup EXIT
python3 "${repo_root}/scripts/deployment/write_pg_env.py" \
  "$migration_env" "$temporary_env"

docker run --rm \
  --env-file "$temporary_env" \
  --volume "${backup_dir}:/backup" \
  --entrypoint pg_dump \
  postgres:17-alpine@sha256:18cfe3ef5e6815560c98237d6216d1e5119702fb0f3894c8785dd58b8bbe5d73 \
  --format=custom --compress=9 --no-owner --no-acl \
  --file "/backup/${temporary_name}"

docker run --rm \
  --volume "${backup_dir}:/backup" \
  --entrypoint chown \
  postgres:17-alpine@sha256:18cfe3ef5e6815560c98237d6216d1e5119702fb0f3894c8785dd58b8bbe5d73 \
  "$(id -u):$(id -g)" "/backup/${temporary_name}"

docker run --rm \
  --volume "${backup_dir}:/backup:ro" \
  --entrypoint pg_restore \
  postgres:17-alpine@sha256:18cfe3ef5e6815560c98237d6216d1e5119702fb0f3894c8785dd58b8bbe5d73 \
  --list "/backup/${temporary_name}" >/dev/null

mv -- "${backup_dir}/${temporary_name}" "${backup_dir}/${backup_name}"
chmod 0640 "${backup_dir}/${backup_name}"
(
  cd "$backup_dir"
  sha256sum "$backup_name" >"${backup_name}.sha256"
)
chmod 0640 "${backup_dir}/${backup_name}.sha256"
trap - EXIT
rm -f -- "$temporary_env"
printf '%s\n' "${backup_dir}/${backup_name}"
