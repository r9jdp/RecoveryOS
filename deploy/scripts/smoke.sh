#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -lt 1 || $# -gt 3 ]]; then
  echo "Usage: bash deploy/scripts/smoke.sh <api-base-url> [customer-agent-base-url] [expected-version]" >&2
  exit 64
fi

api_base_url="${1%/}"
agent_base_url="${2:-}"
agent_base_url="${agent_base_url%/}"
expected_version="${3:-}"

validate_origin() {
  local origin="$1"
  if [[ "$origin" =~ ^https://[A-Za-z0-9.-]+(:[0-9]+)?$ ]]; then
    return 0
  fi
  if [[ "${RECOVERYOS_ALLOW_HTTP_SMOKE:-false}" == "true" && "$origin" =~ ^http://(127\.0\.0\.1|localhost)(:[0-9]+)?$ ]]; then
    return 0
  fi
  echo "Smoke origins must be HTTPS (or explicit localhost test mode): ${origin}" >&2
  return 1
}

validate_origin "$api_base_url"
if [[ -n "$agent_base_url" ]]; then
  validate_origin "$agent_base_url"
fi

retry_json() {
  local url="$1"
  local assertion="$2"
  local attempts=20
  local delay_seconds=3
  local response_file
  response_file="$(mktemp)"

  for ((attempt = 1; attempt <= attempts; attempt++)); do
    if curl --fail --silent --show-error \
      --connect-timeout 3 --max-time 8 \
      --header 'Accept: application/json' \
      --output "$response_file" "$url" && \
      python3 - "$response_file" "$assertion" "$expected_version" <<'PY'
import json
import sys

path, assertion, expected_version = sys.argv[1:]
with open(path, encoding="utf-8") as handle:
    payload = json.load(handle)

if assertion == "api-live":
    assert payload.get("status") == "ok"
    assert payload.get("service") == "recoveryos-api"
    if expected_version:
        assert payload.get("version") == expected_version
elif assertion == "api-ready":
    assert payload.get("status") == "ready"
    assert all(item.get("status") == "ok" for item in payload.get("components", []))
elif assertion == "agent-live":
    assert payload.get("status") == "live"
    assert payload.get("service") == "recoveryos-customer-agent"
elif assertion == "agent-card":
    assert payload.get("name")
    interfaces = payload.get("supportedInterfaces", [])
    assert isinstance(interfaces, list) and interfaces
    assert any(
        isinstance(interface, dict)
        and interface.get("url", "").startswith("https://")
        for interface in interfaces
    )
    assert payload.get("skills")
else:
    raise AssertionError(f"unknown assertion: {assertion}")
PY
    then
      echo "OK ${url}"
      rm -f -- "$response_file"
      return 0
    fi
    sleep "$delay_seconds"
  done

  echo "Smoke check failed after ${attempts} attempts: ${url}" >&2
  rm -f -- "$response_file"
  return 1
}

retry_json "${api_base_url}/health/live" api-live
retry_json "${api_base_url}/health/ready" api-ready

if [[ -n "$agent_base_url" ]]; then
  retry_json "${agent_base_url}/health/live" agent-live
  retry_json "${agent_base_url}/.well-known/agent-card.json" agent-card
fi
