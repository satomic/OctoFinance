#!/usr/bin/env python3
"""Diff the JSON/CSV/JSONL files of a run's py/data vs go/data.
usage: datadiff.py <run> [subpath-glob ...]   (default: everything except logs)"""
import glob, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
RUNS = os.environ.get("PARITY_RUNS", "/tmp/octofinance-parity"); sys.path.insert(0, HERE)
from parity import diff
run = sys.argv[1]; pats = sys.argv[2:] or ["**/*"]
root = os.path.join(RUNS, run)
a, b = os.path.join(root, "py/data"), os.path.join(root, "go/data")
files = set()
for base in (a, b):
    for pat in pats:
        for f in glob.glob(os.path.join(base, pat), recursive=True):
            rel = os.path.relpath(f, base)
            if os.path.isfile(f) and not rel.startswith("logs") and not rel.endswith((".lock", ".pid")) and "auth_sessions" not in rel:
                files.add(rel)
bad = 0
for rel in sorted(files):
    fa, fb = os.path.join(a, rel), os.path.join(b, rel)
    if not os.path.exists(fa) or not os.path.exists(fb):
        print(f"ONLY {'go' if os.path.exists(fb) else 'py'}: {rel}"); bad += 1; continue
    if rel.endswith(".json"):
        try:
            ja, jb = json.load(open(fa)), json.load(open(fb))
        except ValueError as e:
            print(f"BAD  {rel}: {e}"); bad += 1; continue
        d = diff(ja, jb)
    elif rel.endswith(".jsonl"):
        la = [json.loads(l) for l in open(fa) if l.strip()]; lb = [json.loads(l) for l in open(fb) if l.strip()]
        d = diff(la, lb)
    else:
        d = [] if open(fa, "rb").read().replace(b"\r\n", b"\n") == open(fb, "rb").read().replace(b"\r\n", b"\n") else ["content differs"]
    if d:
        bad += 1; print(f"DIFF {rel}"); [print("     " + x) for x in d[:15]]
print(f"{len(files)} files compared, {bad} differ")
