#!/usr/bin/env bash
# Start an isolated Python + Go backend pair on copies of the real data/.
#   start.sh <name> <py_port> <go_port> <backend-go dir>
# Sessions (cookies) are injected: admin token "parity-admin", user token "parity-user" (login from $PARITY_USER).
set -euo pipefail
NAME=$1; PYPORT=$2; GOPORT=$3; GODIR=$4
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../../.." && pwd)
ROOT=${PARITY_RUNS:-/tmp/octofinance-parity}/$NAME
"$HERE/stop.sh" "$NAME" >/dev/null 2>&1 || true
for port in $PYPORT $GOPORT $((PYPORT+500)) $((GOPORT+500)); do for pid in $(lsof -ti tcp:$port -sTCP:LISTEN 2>/dev/null); do kill $pid; done; done; sleep 1
rm -rf "$ROOT"; mkdir -p "$ROOT/py" "$ROOT/go"
rsync -a --exclude __pycache__ "$REPO/backend/" "$ROOT/py/backend/"
# test-only: let the Python copy talk to the mock GitHub API
python3 - "$ROOT/py/backend/app/services/github_host.py" <<'PY'
import sys
p = sys.argv[1]; s = open(p).read()
s = s.replace('def api_base_url(host: str | None) -> str:\n', 'def api_base_url(host: str | None) -> str:\n    import os\n    if os.environ.get("OCTOFINANCE_GITHUB_API_BASE"):\n        return os.environ["OCTOFINANCE_GITHUB_API_BASE"].rstrip("/")\n', 1)
open(p, "w").write(s)
PY
rsync -a --exclude logs "$REPO/data/" "$ROOT/py/data/"
rsync -a --exclude logs "$REPO/data/" "$ROOT/go/data/"
USER_LOGIN=${PARITY_USER:-}
mkdir -p "$ROOT/py/frontend" && cp -R "$REPO/frontend/dist" "$ROOT/py/frontend/dist"
if [ -n "${FRESH_AUTH:-}" ]; then rm -f "$ROOT/py/data/auth.json" "$ROOT/go/data/auth.json"; fi
for d in "$ROOT/py/data" "$ROOT/go/data"; do
  python3 - "$d" "$USER_LOGIN" <<'PY'
import json, sys, time
d, user = sys.argv[1], sys.argv[2]
p = f"{d}/auth_sessions.json"
s = {}
s["parity-admin"] = {"login": "admin", "name": "admin", "avatar_url": "", "auth_type": "local", "is_admin": True, "github_id": None, "created_at": time.time()}
if user:
    s["parity-user"] = {"login": user, "name": user, "avatar_url": "", "auth_type": "github", "is_admin": False, "github_id": 1, "created_at": time.time()}
json.dump(s, open(p, "w"), indent=2)
pj = json.load(open(f"{d}/pats.json"))
if isinstance(pj, dict):
    pj.setdefault("settings", {})["auto_sync_on_startup"] = False
    pj["settings"]["sync_cron"] = ""
    json.dump(pj, open(f"{d}/pats.json", "w"), indent=2)
PY
done
PYMOCK=$((PYPORT+500)); GOMOCK=$((GOPORT+500))
D="python3 $HERE/daemon.py"
$D "$ROOT/mock_py.pid" "$ROOT/mock_py.log" "$ROOT" -- python3 "$HERE/mock_github.py" "$PYMOCK" "$ROOT/py/data"
$D "$ROOT/mock_go.pid" "$ROOT/mock_go.log" "$ROOT" -- python3 "$HERE/mock_github.py" "$GOMOCK" "$ROOT/go/data"
sleep 1

(cd "$ROOT/go" && go build -C "$GODIR" -o "$ROOT/go/octo" ./cmd/octofinance)
OCTOFINANCE_GITHUB_API_BASE="http://127.0.0.1:$PYMOCK" $D "$ROOT/py.pid" "$ROOT/py.log" "$ROOT/py/backend" -- "$REPO/.venv/bin/uvicorn" app.main:app --host 127.0.0.1 --port "$PYPORT"
OCTOFINANCE_GITHUB_API_BASE="http://127.0.0.1:$GOMOCK" OCTOFINANCE_DATA_DIR="$ROOT/go/data" OCTOFINANCE_FRONTEND_DIST="$REPO/frontend/dist" HOST=127.0.0.1 PORT="$GOPORT" $D "$ROOT/go.pid" "$ROOT/go.log" "$ROOT/go" -- "$ROOT/go/octo"
for port in "$PYPORT" "$GOPORT"; do
  for i in $(seq 1 90); do curl -s -o /dev/null "http://127.0.0.1:$port/api/auth/status" && break; sleep 1; done
done
echo "$PYPORT $GOPORT $PYMOCK $GOMOCK" > "$ROOT/ports"
echo "ready: py=$PYPORT go=$GOPORT root=$ROOT"
