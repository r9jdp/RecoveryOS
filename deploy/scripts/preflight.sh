#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  echo "Usage: bash deploy/scripts/preflight.sh <staging|production> [image-tag]" >&2
}

if [[ $# -lt 1 || $# -gt 2 ]]; then
  usage
  exit 64
fi

deployment_env="$1"
image_tag="${2:-preflight}"
case "$deployment_env" in
  staging|production) ;;
  *) usage; exit 64 ;;
esac
if [[ ! "$image_tag" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "Image tag contains unsupported characters." >&2
  exit 64
fi

repo_root="${RECOVERYOS_RELEASE_ROOT:-/opt/recoveryos/current}"
config_root="${RECOVERYOS_CONFIG_ROOT:-/etc/recoveryos}"
if [[ "$repo_root" != /* || "$repo_root" == "/" || "$config_root" != /* || "$config_root" == "/" ]]; then
  echo "Release and configuration roots must be specific absolute paths." >&2
  exit 64
fi
compose_env="${config_root}/${deployment_env}/compose.env"
api_env="${config_root}/${deployment_env}/api.env"
worker_env="${config_root}/${deployment_env}/worker.env"
customer_agent_env="${config_root}/${deployment_env}/customer-agent.env"
migration_env="${config_root}/${deployment_env}/migration.env"
caddy_env="${config_root}/edge/caddy.env"
base_compose="${repo_root}/infra/compose/compose.base.yml"
overlay_compose="${repo_root}/infra/compose/compose.${deployment_env}.yml"
edge_compose="${repo_root}/infra/compose/compose.edge.yml"

for command_name in docker curl python3 df stat uname sha256sum flock; do
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

for required_file in "$base_compose" "$overlay_compose" "$edge_compose"; do
  if [[ ! -r "$required_file" ]]; then
    echo "Required release file is not readable: ${required_file}" >&2
    exit 1
  fi
done

for protected_file in \
  "$compose_env" \
  "$api_env" \
  "$worker_env" \
  "$customer_agent_env" \
  "$migration_env" \
  "$caddy_env"; do
  if [[ ! -f "$protected_file" || -L "$protected_file" || ! -r "$protected_file" ]]; then
    echo "Required configuration must be a readable regular file, not a symlink: ${protected_file}" >&2
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

python3 "${repo_root}/scripts/deployment/check_migrations.py"

if [[ "${RECOVERYOS_PUBLIC_DEMO:-false}" == "true" ]]; then
  python3 "${repo_root}/scripts/deployment/validate_public_demo.py" \
    "$api_env" "$customer_agent_env"
fi

IMAGE_TAG="$image_tag" \
  API_ENV_FILE="$api_env" \
  WORKER_ENV_FILE="$worker_env" \
  CUSTOMER_AGENT_ENV_FILE="$customer_agent_env" \
  docker compose \
  --env-file "$compose_env" \
  --file "$base_compose" \
  --file "$overlay_compose" config --quiet

CADDY_ENV_FILE="$caddy_env" \
  docker compose --file "$edge_compose" config --quiet

docker run --rm \
  --volume "${repo_root}/infra/haproxy/haproxy.cfg:/usr/local/etc/haproxy/haproxy.cfg:ro" \
  haproxy:3.2.22-alpine@sha256:79799e8b2977e60802774fa53d29e6b54e045402cdd8a8b9fe43923e7095a047 \
  haproxy -c -f /usr/local/etc/haproxy/haproxy.cfg >/dev/null

echo "Preflight passed for ${deployment_env} at immutable tag ${image_tag}."
