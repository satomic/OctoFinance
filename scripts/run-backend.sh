#!/usr/bin/env bash
#
# Run OctoFinance from source with the backend of your choice.
#
# Usage:
#   ./scripts/run-backend.sh            # Python backend (default)
#   ./scripts/run-backend.sh go         # Go backend
#   OCTOFINANCE_BACKEND=go ./scripts/run-backend.sh
#   PORT=9000 ./scripts/run-backend.sh go
#
# Both backends serve the API (and frontend/dist when built) on $PORT (8000) and
# share the data/ directory at the repository root, so you can switch freely.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
BACKEND="$(echo "${1:-${OCTOFINANCE_BACKEND:-python}}" | tr '[:upper:]' '[:lower:]')"
PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"

case "$BACKEND" in
    go|golang)
        mkdir -p "$ROOT/backend-go/bin"
        echo ">>> Building the Go backend"
        (cd "$ROOT/backend-go" && go build -o bin/octofinance-go ./cmd/octofinance)
        echo ">>> Starting the Go backend on ${HOST}:${PORT}"
        OCTOFINANCE_ROOT="$ROOT" exec "$ROOT/backend-go/bin/octofinance-go" -host "$HOST" -port "$PORT"
        ;;
    python|py)
        PY="${PYTHON:-$ROOT/.venv/bin/uvicorn}"
        [ -x "$PY" ] || PY="uvicorn"
        echo ">>> Starting the Python backend on ${HOST}:${PORT}"
        cd "$ROOT/backend"
        exec "$PY" app.main:app --host "$HOST" --port "$PORT"
        ;;
    *)
        echo "Unknown backend '$BACKEND' (use 'python' or 'go')" >&2
        exit 1
        ;;
esac
