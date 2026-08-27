#!/usr/bin/env bash
set -Eeuo pipefail

dry_run="${1:-}"
if [[ -n "$dry_run" && "$dry_run" != "--dry-run" ]]; then
  echo "Usage: bash scripts/security/security-gate.sh [--dry-run]" >&2
  exit 64
fi

python3 scripts/security/scan_repository.py --browser-dir apps/web/.next/static

if [[ "$dry_run" == "--dry-run" ]]; then
  echo "DRY-RUN gitleaks git --config .gitleaks.toml --redact --no-banner"
  bash scripts/security/scan-dependencies.sh --dry-run
else
  command -v gitleaks >/dev/null || {
    echo "Missing security scanner: gitleaks" >&2
    exit 1
  }
  gitleaks git --config .gitleaks.toml --redact --no-banner
  bash scripts/security/scan-dependencies.sh
fi
