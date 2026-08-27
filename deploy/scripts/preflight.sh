#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: bash deploy/scripts/preflight.sh <staging|production>" >&2
  exit 64
fi

deployment_env="$1"
case "$deployment_env" in
  staging|production) ;;
  *) echo "Deployment environment must be staging or production." >&2; exit 64 ;;
esac

config_root="${RECOVERYOS_CONFIG_ROOT:-/etc/recoveryos}"
compose_env="${config_root}/${deployment_env}/compose.env"
api_env="${config_root}/${deployment_env}/api.env"
worker_env="${config_root}/${deployment_env}/worker.env"
customer_agent_env="${config_root}/${deployment_env}/customer-agent.env"
migration_env="${config_root}/${deployment_env}/migration.env"
caddy_env="${config_root}/edge/caddy.env"

for command_name in docker curl; do
  command -v "$command_name" >/dev/null || {
    echo "Missing required command: ${command_name}" >&2
    exit 1
  }
done

docker compose version >/dev/null
docker info >/dev/null

architecture="$(uname -m)"
if [[ "$architecture" != "aarch64" && "$architecture" != "arm64" ]]; then
  echo "Expected an ARM64 host, found ${architecture}." >&2
  exit 1
fi

for protected_file in \
  "$compose_env" \
  "$api_env" \
  "$worker_env" \
  "$customer_agent_env" \
  "$migration_env" \
  "$caddy_env"; do
  if [[ ! -r "$protected_file" ]]; then
    echo "Required configuration file is not readable: ${protected_file}" >&2
    exit 1
  fi

  permissions="$(stat -c '%a' "$protected_file")"
  if [[ "$permissions" != "600" && "$permissions" != "400" ]]; then
    echo "Refusing configuration file with permissions ${permissions}: ${protected_file}" >&2
    exit 1
  fi
done

available_kib="$(df --output=avail /var/lib/docker | tail -n 1 | tr -d ' ')"
minimum_kib=$((8 * 1024 * 1024))
if (( available_kib < minimum_kib )); then
  echo "At least 8 GiB of free Docker storage is required." >&2
  exit 1
fi

echo "Preflight passed for ${deployment_env}."
