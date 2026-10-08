#!/usr/bin/env bash
# Rebuild and restart only the Go backend of a run (keeps its data dir).
#   restart_go.sh <name> <backend-go dir>
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd); NAME=$1; GODIR=$2; ROOT=${PARITY_RUNS:-/tmp/octofinance-parity}/$NAME
read PYPORT GOPORT PYMOCK GOMOCK < "$ROOT/ports"
[ -f "$ROOT/go.pid" ] && kill "$(cat "$ROOT/go.pid")" 2>/dev/null || true
sleep 1
go build -C "$GODIR" -o "$ROOT/go/octo" ./cmd/octofinance
OCTOFINANCE_GITHUB_API_BASE="http://127.0.0.1:$GOMOCK" OCTOFINANCE_DATA_DIR="$ROOT/go/data" OCTOFINANCE_FRONTEND_DIST="$(cd "$HERE/../../.." && pwd)/frontend/dist" HOST=127.0.0.1 PORT="$GOPORT" python3 "$HERE/daemon.py" "$ROOT/go.pid" "$ROOT/go.log" "$ROOT/go" -- "$ROOT/go/octo"
for i in $(seq 1 90); do curl -s -o /dev/null "http://127.0.0.1:$GOPORT/api/auth/status" && break; sleep 1; done
echo "go restarted on $GOPORT"
