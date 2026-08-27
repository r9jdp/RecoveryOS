#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "Usage: bash deploy/scripts/monitor.sh <api-base-url> [customer-agent-base-url]" >&2
  exit 64
fi

api_base_url="${1%/}"
agent_base_url="${2:-}"
agent_base_url="${agent_base_url%/}"
failures=0

probe() {
  local name="$1"
  local url="$2"
  if curl --fail --silent --show-error \
    --connect-timeout 5 --max-time 10 \
    --retry 2 --retry-delay 2 \
    --header 'Accept: application/json' \
    "$url" >/dev/null; then
    echo "UP ${name} ${url}"
  else
    echo "DOWN ${name} ${url}" >&2
    failures=$((failures + 1))
  fi
}

probe api-live "${api_base_url}/health/live"
probe api-ready "${api_base_url}/health/ready"
if [[ -n "$agent_base_url" ]]; then
  probe agent-live "${agent_base_url}/health/live"
  probe agent-card "${agent_base_url}/.well-known/agent-card.json"
fi

if (( failures > 0 )); then
  echo "${failures} uptime probe(s) failed." >&2
  exit 1
fi
