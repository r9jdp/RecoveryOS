#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -lt 3 || $# -gt 4 ]]; then
  echo "Usage: bash scripts/security/scan-images.sh <ghcr-owner> <repository> <image-tag> [--dry-run]" >&2
  exit 64
fi
owner="$1"
repository="$2"
image_tag="$3"
dry_run="${4:-}"
if [[ ! "$owner" =~ ^[A-Za-z0-9._-]+$ || ! "$repository" =~ ^[A-Za-z0-9._-]+$ || ! "$image_tag" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "Image coordinates contain unsupported characters." >&2
  exit 64
fi
if [[ -n "$dry_run" && "$dry_run" != "--dry-run" ]]; then
  echo "The only optional argument is --dry-run." >&2
  exit 64
fi

prefix="ghcr.io/${owner}/${repository}"
for service in api worker customer-agent; do
  image="${prefix}-${service}:${image_tag}"
  if [[ "$dry_run" == "--dry-run" ]]; then
    echo "DRY-RUN trivy image ${image}"
  else
    command -v trivy >/dev/null || {
      echo "Missing security scanner: trivy" >&2
      exit 1
    }
    trivy image --exit-code 1 --ignore-unfixed \
      --severity HIGH,CRITICAL --scanners vuln,secret "$image"
  fi
done

foundation_images=(
  "haproxy:3.2.22-alpine@sha256:79799e8b2977e60802774fa53d29e6b54e045402cdd8a8b9fe43923e7095a047"
  "caddy:2-alpine@sha256:5f5c8640aae01df9654968d946d8f1a56c497f1dd5c5cda4cf95ab7c14d58648"
  "postgres:17-alpine@sha256:18cfe3ef5e6815560c98237d6216d1e5119702fb0f3894c8785dd58b8bbe5d73"
)
for image in "${foundation_images[@]}"; do
  if [[ "$dry_run" == "--dry-run" ]]; then
    echo "DRY-RUN trivy image ${image}"
  else
    trivy image --exit-code 1 --ignore-unfixed \
      --severity HIGH,CRITICAL --scanners vuln,secret "$image"
  fi
done
