#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
config_root="$(mktemp -d)"
state_root="$(mktemp -d)"
cleanup() {
  if [[ "$config_root" == /tmp/* && "$state_root" == /tmp/* ]]; then
    rm -rf -- "$config_root" "$state_root"
  fi
}
trap cleanup EXIT

mkdir -p "${config_root}/staging"
printf '%s\n' \
  'DATABASE_URL=postgresql+psycopg://recovery:recovery@host.docker.internal:55432/recovery_os' \
  >"${config_root}/staging/migration.env"
chmod 0600 "${config_root}/staging/migration.env"

export RECOVERYOS_RELEASE_ROOT="$repo_root"
export RECOVERYOS_CONFIG_ROOT="$config_root"
export RECOVERYOS_STATE_ROOT="$state_root"
backup_output="$(bash "${repo_root}/deploy/scripts/backup.sh" staging)"
backup_path="$(tail -n 1 <<<"$backup_output")"
test -s "$backup_path"
test -s "${backup_path}.sha256"
bash "${repo_root}/deploy/scripts/verify-restore.sh" "$backup_path"
