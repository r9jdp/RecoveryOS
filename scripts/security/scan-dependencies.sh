#!/usr/bin/env bash
set -Eeuo pipefail

dry_run=false
if [[ "${1:-}" == "--dry-run" ]]; then
  dry_run=true
elif [[ $# -ne 0 ]]; then
  echo "Usage: bash scripts/security/scan-dependencies.sh [--dry-run]" >&2
  exit 64
fi

commands=(uv pnpm pip-audit)
for command_name in "${commands[@]}"; do
  if ! command -v "$command_name" >/dev/null; then
    if "$dry_run"; then
      echo "DRY-RUN missing optional CI command: ${command_name}"
    else
      echo "Missing security scanner: ${command_name}" >&2
      exit 1
    fi
  fi
done

if "$dry_run"; then
  echo "DRY-RUN uv lock --check"
  echo "DRY-RUN uv export --frozen --no-dev --no-emit-project"
  echo "DRY-RUN pip-audit --require-hashes --disable-pip"
  echo "DRY-RUN pnpm audit --prod --audit-level high"
  exit 0
fi

requirements_file="$(mktemp)"
trap 'rm -f -- "$requirements_file"' EXIT
uv lock --check
uv export --frozen --no-dev --no-emit-project \
  --format requirements-txt --output-file "$requirements_file"
pip-audit --require-hashes --disable-pip --requirement "$requirements_file"
pnpm audit --prod --audit-level high
