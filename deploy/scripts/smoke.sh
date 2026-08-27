#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "Usage: bash deploy/scripts/smoke.sh <api-base-url> [customer-agent-base-url]" >&2
  exit 64
fi

api_base_url="${1%/}"
agent_base_url="${2:-}"
agent_base_url="${agent_base_url%/}"

retry_curl() {
  local url="$1"
  local attempts=20
  local delay_seconds=3

  for ((attempt = 1; attempt <= attempts; attempt++)); do
    if curl --fail --silent --show-error \
      --connect-timeout 3 --max-time 8 \
      "$url" >/dev/null; then
      echo "OK ${url}"
      return 0
    fi
    sleep "$delay_seconds"
  done

  echo "Smoke check failed after ${attempts} attempts: ${url}" >&2
  return 1
}

retry_curl "${api_base_url}/health/live"
retry_curl "${api_base_url}/health/ready"

if [[ -n "$agent_base_url" ]]; then
  retry_curl "${agent_base_url}/health/live"
  retry_curl "${agent_base_url}/.well-known/agent-card.json"
fi
