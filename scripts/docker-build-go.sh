#!/usr/bin/env bash
#
# Build the OctoFinance Go backend Docker image locally (Dockerfile-go).
# The Python backend image is built by ./scripts/docker-build.sh.
#
# Usage:
#   ./scripts/docker-build-go.sh                 # build octofinance-go:dev for the local arch
#   ./scripts/docker-build-go.sh v2.1.0          # build octofinance-go:v2.1.0
#   PLATFORM=linux/amd64 ./scripts/docker-build-go.sh   # cross-build for another arch
#
set -euo pipefail

cd "$(dirname "$0")/.."

IMAGE_NAME="${IMAGE_NAME:-octofinance-go}"
TAG="${1:-dev}"
PLATFORM="${PLATFORM:-}"

args=(build -t "${IMAGE_NAME}:${TAG}" -f Dockerfile-go .)
if [[ -n "$PLATFORM" ]]; then
    args=(buildx build --platform "$PLATFORM" -t "${IMAGE_NAME}:${TAG}" --load -f Dockerfile-go .)
fi

echo ">>> docker ${args[*]}"
docker "${args[@]}"

echo ""
echo "Built ${IMAGE_NAME}:${TAG}"
echo "Run it with:"
echo "  docker run -d --name octofinance -p 8000:8000 -v \$(pwd)/data:/app/data ${IMAGE_NAME}:${TAG}"
