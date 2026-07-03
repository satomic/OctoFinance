#!/usr/bin/env bash
#
# Build the OctoFinance Docker image locally.
#
# Usage:
#   ./scripts/docker-build.sh                 # build octofinance:dev for the local arch
#   ./scripts/docker-build.sh v2.1.0          # build octofinance:v2.1.0
#   PLATFORM=linux/amd64 ./scripts/docker-build.sh   # cross-build for another arch
#
set -euo pipefail

cd "$(dirname "$0")/.."

IMAGE_NAME="${IMAGE_NAME:-octofinance}"
TAG="${1:-dev}"
PLATFORM="${PLATFORM:-}"

args=(build -t "${IMAGE_NAME}:${TAG}" -f Dockerfile .)
if [[ -n "$PLATFORM" ]]; then
    args=(buildx build --platform "$PLATFORM" -t "${IMAGE_NAME}:${TAG}" --load -f Dockerfile .)
fi

echo ">>> docker ${args[*]}"
docker "${args[@]}"

echo ""
echo "Built ${IMAGE_NAME}:${TAG}"
echo "Run it with:"
echo "  docker run -d --name octofinance -p 8000:8000 -v \$(pwd)/data:/app/data ${IMAGE_NAME}:${TAG}"
