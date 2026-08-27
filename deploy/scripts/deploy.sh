#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  echo "Usage: bash deploy/scripts/deploy.sh <staging|production> <image-tag> <api-base-url> [customer-agent-base-url]" >&2
}

if [[ $# -lt 3 || $# -gt 4 ]]; then
  usage
  exit 64
fi

deployment_env="$1"
image_tag="$2"
api_base_url="$3"
agent_base_url="${4:-}"

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
state_root="${RECOVERYOS_STATE_ROOT:-/var/lib/recoveryos}"
compose_env="${config_root}/${deployment_env}/compose.env"
state_dir="${state_root}/${deployment_env}"
current_tag_file="${state_dir}/current-tag"

base_compose="${repo_root}/infra/compose/compose.base.yml"
overlay_compose="${repo_root}/infra/compose/compose.${deployment_env}.yml"
edge_compose="${repo_root}/infra/compose/compose.edge.yml"

bash "${repo_root}/deploy/scripts/preflight.sh" "$deployment_env"

previous_tag=""
if [[ -r "$current_tag_file" ]]; then
  previous_tag="$(tr -d '[:space:]' < "$current_tag_file")"
fi

compose_stack() {
  IMAGE_TAG="$1" \
    API_ENV_FILE="${config_root}/${deployment_env}/api.env" \
    WORKER_ENV_FILE="${config_root}/${deployment_env}/worker.env" \
    CUSTOMER_AGENT_ENV_FILE="${config_root}/${deployment_env}/customer-agent.env" \
    docker compose \
    --env-file "$compose_env" \
    --file "$base_compose" \
    --file "$overlay_compose" \
    "${@:2}"
}

rollback_on_error() {
  exit_code=$?
  trap - ERR
  echo "Deployment of ${image_tag} failed." >&2
  if [[ -n "$previous_tag" && "$previous_tag" != "$image_tag" ]]; then
    echo "Restoring application containers at ${previous_tag}." >&2
    compose_stack "$previous_tag" pull
    compose_stack "$previous_tag" up --detach --remove-orphans --wait
  else
    echo "No distinct previous image tag is recorded; manual recovery is required." >&2
  fi
  exit "$exit_code"
}
trap rollback_on_error ERR

# The edge proxy is shared by staging and production and is safe to reconcile.
CADDY_ENV_FILE="${config_root}/edge/caddy.env" \
  docker compose --file "$edge_compose" up --detach --wait

compose_stack "$image_tag" pull

# Migrations must follow an expand/contract policy so the previous image remains
# rollback-compatible. The coordinator owns the migration layout and command.
compose_stack "$image_tag" run --rm \
  --env-from-file "${config_root}/${deployment_env}/migration.env" api \
  python -m alembic -c /workspace/services/api/alembic.ini upgrade head

compose_stack "$image_tag" up --detach --remove-orphans --wait
bash "${repo_root}/deploy/scripts/smoke.sh" "$api_base_url" "$agent_base_url"

install -d -m 0750 "$state_dir"
if [[ -n "$previous_tag" && "$previous_tag" != "$image_tag" ]]; then
  printf '%s\n' "$previous_tag" | install -m 0640 /dev/stdin "${state_dir}/previous-tag"
fi
printf '%s\n' "$image_tag" | install -m 0640 /dev/stdin "$current_tag_file"
trap - ERR

echo "Deployed ${deployment_env} at image tag ${image_tag}."
