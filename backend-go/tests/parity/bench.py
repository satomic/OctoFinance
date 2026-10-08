#!/usr/bin/env python3
"""Load-test the same endpoints on the Python and Go backends of a run.

usage: bench.py <run> [concurrency] [requests-per-endpoint]
"""
import os, statistics, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
RUNS = os.environ.get("PARITY_RUNS", "/tmp/octofinance-parity")
run = sys.argv[1]
conc = int(sys.argv[2]) if len(sys.argv) > 2 else 16
n = int(sys.argv[3]) if len(sys.argv) > 3 else 200
py, go = open(f"{RUNS}/{run}/ports").read().split()[:2]

ENDPOINTS = [
    ("admin", "/api/data/dashboard"),
    ("admin", "/api/data/csv-dashboard"),
    ("admin", "/api/data/cost-center-dashboard"),
    ("admin", "/api/data/enterprise-teams-dashboard"),
    ("admin", "/api/data/overview"),
    ("user", "/api/me/dashboard"),
]


def one(port, path, token):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                 headers={"Cookie": f"octofinance_session=parity-{token}"})
    t = time.perf_counter()
    with urllib.request.urlopen(req, timeout=120) as r:
        r.read()
        assert r.status == 200
    return (time.perf_counter() - t) * 1000


def bench(port, path, token):
    for _ in range(3):
        one(port, path, token)  # warm-up
    t0 = time.perf_counter()
    with ThreadPoolExecutor(conc) as ex:
        lat = list(ex.map(lambda _: one(port, path, token), range(n)))
    wall = time.perf_counter() - t0
    lat.sort()
    return n / wall, statistics.median(lat), lat[int(len(lat) * 0.95) - 1]


print(f"concurrency={conc}, requests per endpoint={n}")
print(f"{'endpoint':40} {'backend':7} {'req/s':>8} {'p50 ms':>8} {'p95 ms':>8}")
for token, path in ENDPOINTS:
    res = {}
    for name, port in (("python", py), ("go", go)):
        res[name] = bench(port, path, token)
        rps, p50, p95 = res[name]
        print(f"{path:40} {name:7} {rps:8.1f} {p50:8.1f} {p95:8.1f}")
    print(f"{'':40} speed-up x{res['go'][0] / res['python'][0]:.1f} throughput")
