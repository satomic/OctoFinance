#!/usr/bin/env bash
HERE=$(cd "$(dirname "$0")" && pwd); ROOT=${PARITY_RUNS:-/tmp/octofinance-parity}/$1
if [ -f "$ROOT/ports" ]; then
  for port in $(cat "$ROOT/ports"); do
    for pid in $(lsof -ti tcp:"$port" -sTCP:LISTEN 2>/dev/null); do kill "$pid" 2>/dev/null; done
  done
fi
for f in py.pid go.pid mock_py.pid mock_go.pid; do [ -f "$ROOT/$f" ] && kill "$(cat "$ROOT/$f")" 2>/dev/null; rm -f "$ROOT/$f"; done
pkill -f "$ROOT/" 2>/dev/null || true
sleep 1
echo stopped
