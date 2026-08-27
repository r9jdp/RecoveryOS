#!/usr/bin/env bash
set -Eeuo pipefail

# Stable CI entrypoint retained separately from the implementation so the
# coordinator can reference one command while local builds can still use --load.
if [[ $# -ne 3 ]]; then
  echo "Usage: bash deploy/scripts/build-and-push.sh <ghcr-owner> <repository> <image-tag>" >&2
  exit 64
fi

exec bash "$(dirname "$0")/build-images.sh" "$1" "$2" "$3" --push
