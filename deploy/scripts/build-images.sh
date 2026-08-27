#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  echo "Usage: bash deploy/scripts/build-images.sh <ghcr-owner> <repository> <image-tag> [--load]" >&2
}

if [[ $# -lt 3 || $# -gt 4 ]]; then
  usage
  exit 64
fi

ghcr_owner="$1"
repository="$2"
image_tag="$3"
output_mode="${4:---push}"

if [[ ! "$ghcr_owner" =~ ^[A-Za-z0-9._-]+$ || ! "$repository" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "GHCR owner and repository contain unsupported characters." >&2
  exit 64
fi

if [[ ! "$image_tag" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "Image tag contains unsupported characters." >&2
  exit 64
fi

if [[ "$output_mode" != "--push" && "$output_mode" != "--load" ]]; then
  usage
  exit 64
fi

git_sha="$(git rev-parse HEAD)"
created_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
image_prefix="ghcr.io/${ghcr_owner}/${repository}"

common_args=(
  --platform linux/arm64
  --label "org.opencontainers.image.revision=${git_sha}"
  --label "org.opencontainers.image.created=${created_at}"
  --label "org.opencontainers.image.source=https://github.com/${ghcr_owner}/${repository}"
  "$output_mode"
)

docker buildx inspect --bootstrap >/dev/null

docker buildx build "${common_args[@]}" \
  --file services/api/Dockerfile \
  --tag "${image_prefix}-api:${image_tag}" .

docker buildx build "${common_args[@]}" \
  --file services/worker/Dockerfile \
  --tag "${image_prefix}-worker:${image_tag}" .

docker buildx build "${common_args[@]}" \
  --file services/customer-agent/Dockerfile \
  --tag "${image_prefix}-customer-agent:${image_tag}" .
