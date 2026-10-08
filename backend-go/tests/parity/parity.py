#!/usr/bin/env python3
"""Diff Python vs Go backend responses for the same request.

usage: parity.py <run-name> [--user] [--method POST --body JSON] PATH [PATH ...]

Fetches each PATH from both backends of a run (see start.sh) with the
injected admin session (or the regular-user session with --user) and reports
structural differences. Numbers compare with a 1e-6 relative tolerance;
volatile keys (timestamps, ids generated per request) are ignored.
"""
import argparse
import json
import math
import os
import sys
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
RUNS = os.environ.get("PARITY_RUNS", "/tmp/octofinance-parity")
VOLATILE = {
    "checked_at", "timestamp", "generated_at", "synced_at", "started_at", "finished_at",
    "created_at", "updated_at", "last_used_at", "job_id", "id_generated", "backend", "update", "last_synced_at", "last_success_at",
}


def fetch(port, path, token, method="GET", body=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method)
    req.add_header("Cookie", f"octofinance_session={token}")
    data = None
    if body is not None:
        data = body.encode()
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data=data, timeout=300) as r:
            return r.status, r.headers.get("content-type", ""), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("content-type", ""), e.read()


def diff(a, b, path="$", out=None, limit=40):
    if out is None:
        out = []
    if len(out) >= limit:
        return out
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k in VOLATILE:
                continue
            if k not in a:
                out.append(f"{path}.{k}: missing in python (go={short(b[k])})")
            elif k not in b:
                out.append(f"{path}.{k}: missing in go (py={short(a[k])})")
            else:
                diff(a[k], b[k], f"{path}.{k}", out, limit)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append(f"{path}: list length py={len(a)} go={len(b)}")
        for i, (x, y) in enumerate(zip(a, b)):
            diff(x, y, f"{path}[{i}]", out, limit)
    elif isinstance(a, bool) or isinstance(b, bool):
        if a is not b:
            out.append(f"{path}: py={short(a)} go={short(b)}")
    elif isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if not math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-6):
            out.append(f"{path}: py={a} go={b}")
    elif a != b:
        out.append(f"{path}: py={short(a)} go={short(b)}")
    return out


def short(v):
    s = json.dumps(v, ensure_ascii=False, default=str)
    return s if len(s) < 160 else s[:157] + "..."


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--user", action="store_true", help="use the regular-user session")
    ap.add_argument("--method", default="GET")
    ap.add_argument("--body")
    ap.add_argument("--show", action="store_true", help="print both bodies")
    args = ap.parse_args()
    with open(os.path.join(RUNS, args.run, "ports")) as f:
        py_port, go_port = f.read().split()[:2]
    token = "parity-user" if args.user else "parity-admin"
    failures = 0
    for p in args.paths:
        sa, ta, ba = fetch(py_port, p, token, args.method, args.body)
        sb, tb, bb = fetch(go_port, p, token, args.method, args.body)
        problems = []
        if sa != sb:
            problems.append(f"status py={sa} go={sb}")
        if "json" in ta and "json" in tb:
            try:
                ja, jb = json.loads(ba), json.loads(bb)
                problems += diff(ja, jb)
            except ValueError as e:
                problems.append(f"invalid json: {e}")
        else:
            if ta.split(";")[0] != tb.split(";")[0]:
                problems.append(f"content-type py={ta} go={tb}")
            if abs(len(ba) - len(bb)) > max(64, len(ba) * 0.01):
                problems.append(f"body size py={len(ba)} go={len(bb)}")
        tag = "OK  " if not problems else "DIFF"
        print(f"{tag} {args.method} {p}  (py {sa} {len(ba)}B / go {sb} {len(bb)}B)")
        for line in problems:
            print("     " + line)
        if args.show:
            print("  py:", ba[:2000].decode(errors="replace"))
            print("  go:", bb[:2000].decode(errors="replace"))
        failures += bool(problems)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
