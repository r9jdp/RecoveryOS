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
if [[ "$repo_root" != /* || "$repo_root" == "/" || "$config_root" != /* || "$config_root" == "/" || "$state_root" != /* || "$state_root" == "/" ]]; then
  echo "Release, configuration, and state roots must be specific absolute paths." >&2
  exit 64
fi
compose_env="${config_root}/${deployment_env}/compose.env"
state_dir="${state_root}/${deployment_env}"
current_tag_file="${state_dir}/current-tag"
base_compose="${repo_root}/infra/compose/compose.base.yml"
overlay_compose="${repo_root}/infra/compose/compose.${deployment_env}.yml"
edge_compose="${repo_root}/infra/compose/compose.edge.yml"

install -d -m 0750 "$state_dir"
exec 9>"${state_dir}/deploy.lock"
if ! flock --exclusive --timeout 60 9; then
  echo "Another ${deployment_env} deploy or rollback holds the deployment lock." >&2
  exit 1
fi

bash "${repo_root}/deploy/scripts/preflight.sh" "$deployment_env" "$image_tag"

previous_tag=""
if [[ -r "$current_tag_file" ]]; then
  previous_tag="$(tr -d '[:space:]' <"$current_tag_file")"
fi

compose_stack() {
  local selected_tag="$1"
  shift
  IMAGE_TAG="$selected_tag" \
    API_ENV_FILE="${config_root}/${deployment_env}/api.env" \
    WORKER_ENV_FILE="${config_root}/${deployment_env}/worker.env" \
    CUSTOMER_AGENT_ENV_FILE="${config_root}/${deployment_env}/customer-agent.env" \
    docker compose \
    --env-file "$compose_env" \
    --file "$base_compose" \
    --file "$overlay_compose" \
    "$@"
}

rollback_on_error() {
  exit_code=$?
  trap - ERR
  echo "Deployment of ${image_tag} failed. The database will not be downgraded." >&2
  if [[ -n "$previous_tag" && "$previous_tag" != "$image_tag" ]]; then
    echo "Restoring application containers at ${previous_tag}." >&2
    compose_stack "$previous_tag" pull
    compose_stack "$previous_tag" up --detach --remove-orphans --wait
    if [[ -n "$api_base_url" ]]; then
      bash "${repo_root}/deploy/scripts/smoke.sh" \
        "$api_base_url" "$agent_base_url" "$previous_tag" || true
    fi
  else
    echo "No distinct previous image tag is recorded; manual recovery is required." >&2
  fi
  exit "$exit_code"
}
trap rollback_on_error ERR

CADDY_ENV_FILE="${config_root}/edge/caddy.env" \
  docker compose --file "$edge_compose" up --detach --wait

compose_stack "$image_tag" pull

# Source inspection rejects contract-phase destructive DDL. A database backup
# is mandatory before Alembic runs and is independently restore-testable.
python3 "${repo_root}/scripts/deployment/check_migrations.py"
backup_path="$(bash "${repo_root}/deploy/scripts/backup.sh" "$deployment_env")"
echo "Pre-migration backup created: ${backup_path}"

heads="$(compose_stack "$image_tag" run --rm \
  --env-from-file "${config_root}/${deployment_env}/migration.env" api \
  python -m alembic -c /workspace/services/api/alembic.ini heads)"
head_count="$(grep -c '(head)' <<<"$heads" || true)"
if [[ "$head_count" -ne 1 ]]; then
  echo "Exactly one Alembic head is required; found ${head_count}." >&2
  exit 1
fi

compose_stack "$image_tag" run --rm \
  --env-from-file "${config_root}/${deployment_env}/migration.env" api \
  python -m alembic -c /workspace/services/api/alembic.ini upgrade head

compose_stack "$image_tag" up --detach --remove-orphans --wait
bash "${repo_root}/deploy/scripts/smoke.sh" \
  "$api_base_url" "$agent_base_url" "$image_tag"

if [[ -n "$previous_tag" && "$previous_tag" != "$image_tag" ]]; then
  previous_tmp="$(mktemp "${state_dir}/.previous-tag.XXXXXX")"
  printf '%s\n' "$previous_tag" >"$previous_tmp"
  chmod 0640 "$previous_tmp"
  mv -- "$previous_tmp" "${state_dir}/previous-tag"
fi
current_tmp="$(mktemp "${state_dir}/.current-tag.XXXXXX")"
printf '%s\n' "$image_tag" >"$current_tmp"
chmod 0640 "$current_tmp"
mv -- "$current_tmp" "$current_tag_file"
printf '%s\n' "$backup_path" >"${state_dir}/last-pre-migration-backup"
chmod 0640 "${state_dir}/last-pre-migration-backup"
trap - ERR

echo "Deployed ${deployment_env} at image tag ${image_tag}."
