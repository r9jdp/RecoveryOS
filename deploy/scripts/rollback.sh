#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  echo "Usage: bash deploy/scripts/rollback.sh <staging|production> [image-tag] [api-base-url] [customer-agent-base-url]" >&2
}

if [[ $# -lt 1 || $# -gt 4 ]]; then
  usage
  exit 64
fi

deployment_env="$1"
requested_tag="${2:-}"
api_base_url="${3:-}"
agent_base_url="${4:-}"
case "$deployment_env" in
  staging|production) ;;
  *) usage; exit 64 ;;
esac

repo_root="${RECOVERYOS_RELEASE_ROOT:-/opt/recoveryos/current}"
config_root="${RECOVERYOS_CONFIG_ROOT:-/etc/recoveryos}"
state_root="${RECOVERYOS_STATE_ROOT:-/var/lib/recoveryos}"
if [[ "$repo_root" != /* || "$repo_root" == "/" || "$config_root" != /* || "$config_root" == "/" || "$state_root" != /* || "$state_root" == "/" ]]; then
  echo "Release, configuration, and state roots must be specific absolute paths." >&2
  exit 64
fi
state_dir="${state_root}/${deployment_env}"
compose_env="${config_root}/${deployment_env}/compose.env"
rollback_tag_file="${state_dir}/previous-tag"
current_tag_file="${state_dir}/current-tag"

install -d -m 0750 "$state_dir"
exec 9>"${state_dir}/deploy.lock"
if ! flock --exclusive --timeout 60 9; then
  echo "Another ${deployment_env} deploy or rollback holds the deployment lock." >&2
  exit 1
fi

if [[ -z "$requested_tag" ]]; then
  if [[ ! -r "$rollback_tag_file" ]]; then
    echo "No previous-tag file exists; provide an explicit immutable image tag." >&2
    exit 1
  fi
  requested_tag="$(tr -d '[:space:]' <"$rollback_tag_file")"
fi
if [[ ! "$requested_tag" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "Image tag contains unsupported characters." >&2
  exit 64
fi

compose_stack() {
  IMAGE_TAG="$requested_tag" \
    API_ENV_FILE="${config_root}/${deployment_env}/api.env" \
    WORKER_ENV_FILE="${config_root}/${deployment_env}/worker.env" \
    CUSTOMER_AGENT_ENV_FILE="${config_root}/${deployment_env}/customer-agent.env" \
    docker compose \
    --env-file "$compose_env" \
    --file "${repo_root}/infra/compose/compose.base.yml" \
    --file "${repo_root}/infra/compose/compose.${deployment_env}.yml" \
    "$@"
}

compose_stack pull
compose_stack up --detach --remove-orphans --wait

if [[ -n "$api_base_url" ]]; then
  bash "${repo_root}/deploy/scripts/smoke.sh" \
    "$api_base_url" "$agent_base_url" "$requested_tag"
fi

old_current=""
if [[ -r "$current_tag_file" ]]; then
  old_current="$(tr -d '[:space:]' <"$current_tag_file")"
fi
current_tmp="$(mktemp "${state_dir}/.current-tag.XXXXXX")"
printf '%s\n' "$requested_tag" >"$current_tmp"
chmod 0640 "$current_tmp"
mv -- "$current_tmp" "$current_tag_file"
if [[ -n "$old_current" && "$old_current" != "$requested_tag" ]]; then
  previous_tmp="$(mktemp "${state_dir}/.previous-tag.XXXXXX")"
  printf '%s\n' "$old_current" >"$previous_tmp"
  chmod 0640 "$previous_tmp"
  mv -- "$previous_tmp" "$rollback_tag_file"
fi

echo "Rolled back ${deployment_env} to image tag ${requested_tag}; database state was unchanged."
