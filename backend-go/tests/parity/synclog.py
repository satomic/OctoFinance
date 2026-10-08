#!/usr/bin/env python3
"""Capture /api/sync-stream on both backends while triggering a sync; diff the log lines.
usage: synclog.py <run> <sync-path> [seconds]"""
import json, sys, threading, time, urllib.request, os, re
HERE=os.path.dirname(os.path.abspath(__file__))
RUNS = os.environ.get("PARITY_RUNS", "/tmp/octofinance-parity")
run, path = sys.argv[1], sys.argv[2]; secs=float(sys.argv[3]) if len(sys.argv)>3 else 30
py, go = open(f"{RUNS}/{run}/ports").read().split()[:2]
out={'py':[], 'go':[]}
def listen(side, port):
    req=urllib.request.Request(f"http://127.0.0.1:{port}/api/sync-stream", headers={"Cookie":"octofinance_session=parity-admin"})
    with urllib.request.urlopen(req, timeout=secs+30) as r:
        end=time.time()+secs
        for line in r:
            if time.time()>end: break
            line=line.decode().strip()
            if line.startswith("data: "):
                ev=json.loads(line[6:])
                if ev.get('type')=='sync_complete' or ev.get('type')=='sync_log':
                    out[side].append((ev.get('type'), ev.get('level'), ev.get('message') or json.dumps({k:v for k,v in ev.items() if k not in ('timestamp',)})))
                if ev.get('type')=='sync_complete': break
ts=[threading.Thread(target=listen,args=(s,p)) for s,p in (('py',py),('go',go))]
[t.start() for t in ts]; time.sleep(1.5)
for p in (py,go):
    urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{p}{path}", method="POST", headers={"Cookie":"octofinance_session=parity-admin"}))
[t.join() for t in ts]
import difflib
norm=lambda l:[f"{t}|{lv}|{re.sub(r'pat_[0-9a-f]{8}','pat_X',m)}" for t,lv,m in l]
d=list(difflib.unified_diff(norm(out['py']),norm(out['go']),'py','go',lineterm='',n=0))
print(f"py {len(out['py'])} lines, go {len(out['go'])} lines")
print("\n".join(d) if d else "IDENTICAL")
