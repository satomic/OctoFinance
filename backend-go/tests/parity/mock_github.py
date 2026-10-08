#!/usr/bin/env python3
"""A stateful mock of the GitHub REST API endpoints OctoFinance uses.

Serves discovery, Copilot seats/billing/usage/metrics/AI credits, cost
centers, budgets, enterprise teams and billing report exports from a data/
snapshot, and applies writes (budgets, cost center resources, seats, teams)
to in-memory state. Every request is recorded; GET /__calls returns them and
POST /__reset clears the log.
MOCK_DROP_FIRST=N closes the first N connections without a response, like a
flaky network (connection reset / EOF), to test retry and recovery.

usage: mock_github.py <port> <data-dir>
"""
import csv
import io
import json
import os
import re
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

PORT = int(sys.argv[1])
DATA = sys.argv[2]
BASE = f"http://127.0.0.1:{PORT}"
LOCK = threading.RLock()
CALLS = []
DROPS_LEFT = [int(os.environ.get("MOCK_DROP_FIRST", "0") or 0)]


def load(path, default=None):
    try:
        with open(os.path.join(DATA, path), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


PATS = (load("pats.json", {}) or {}).get("pats", [])
LOGIN = (PATS[0].get("user_login") if PATS else "") or "satomic"
ORGS = (PATS[0].get("orgs") if PATS else []) or []
ENTERPRISES = [e["slug"] for e in (load("enterprise/all_latest.json", []) or [])] or ["satomic"]


def scope_files(cat):
    out = {}
    d = os.path.join(DATA, cat)
    if os.path.isdir(d):
        for name in os.listdir(d):
            if name.endswith("_latest.json"):
                out[name[: -len("_latest.json")]] = load(f"{cat}/{name}")
    return out


SEATS = scope_files("seats")
BILLING = scope_files("billing")
USAGE = scope_files("usage")
USAGE_USERS = scope_files("usage_users")
METRICS = scope_files("metrics")
AI_CREDITS = scope_files("ai_credits")
COST_CENTERS = {}
for ent, snap in scope_files("cost_centers").items():
    centers = []
    for cc in snap.get("cost_centers", []):
        cc = {k: v for k, v in cc.items() if k not in ("members", "member_count")}
        centers.append(cc)
    COST_CENTERS[ent] = centers
BUDGETS = {ent: snap.get("budgets", []) for ent, snap in scope_files("budgets").items()}
TEAMS = {ent: snap.get("teams", []) for ent, snap in scope_files("enterprise_teams").items()}
ORG_MEMBERS = {}
for ent, snap in scope_files("cost_centers").items():
    for cc in snap.get("cost_centers", []):
        for m in cc.get("members", []):
            if m.get("source_type") == "Org":
                ORG_MEMBERS.setdefault(m["source_name"], []).append(
                    {"login": m["login"], "avatar_url": m.get("avatar_url", ""), "html_url": m.get("html_url", "")})
REPORTS = {}


def csv_text(path):
    try:
        with open(os.path.join(DATA, path), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def paginate(items, qs):
    page = int(qs.get("page", ["1"])[0])
    per = int(qs.get("per_page", ["30"])[0])
    return items[(page - 1) * per: page * per]


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def send(self, status, body=None, ctype="application/json"):
        data = b"" if body is None else (body if isinstance(body, bytes) else
                                          (body.encode() if isinstance(body, str) else json.dumps(body).encode()))
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        try:
            return json.loads(raw) if raw else None
        except ValueError:
            return raw.decode(errors="replace")

    def handle_any(self, method):
        with LOCK:
            drop = DROPS_LEFT[0] > 0
            if drop:
                DROPS_LEFT[0] -= 1
        if drop:  # simulate a dropped connection: no status line, just close
            self.close_connection = True
            self.connection.shutdown(2)
            return
        u = urlparse(self.path)
        path, qs = u.path, parse_qs(u.query)
        body = self.body() if method in ("POST", "PATCH", "PUT", "DELETE") else None
        with LOCK:
            if path == "/__calls":
                return self.send(200, CALLS)
            if path == "/__reset":
                CALLS.clear()
                return self.send(200, {"ok": True})
            CALLS.append({"method": method, "path": path, "query": u.query, "body": body})
            try:
                status, resp, ctype = self.route(method, path, qs, body)
            except Exception as e:  # noqa
                status, resp, ctype = 500, {"message": f"mock error: {e}"}, "application/json"
        self.send(status, resp, ctype)

    def do_GET(self): self.handle_any("GET")
    def do_POST(self): self.handle_any("POST")
    def do_PATCH(self): self.handle_any("PATCH")
    def do_PUT(self): self.handle_any("PUT")
    def do_DELETE(self): self.handle_any("DELETE")

    # ------------------------------------------------------------------
    def route(self, method, path, qs, body):
        J = "application/json"
        nf = (404, {"message": "Not Found"}, J)
        m = lambda pat: re.fullmatch(pat, path)

        if path == "/user":
            return 200, {"login": LOGIN, "id": 9782493, "name": LOGIN,
                         "avatar_url": f"https://avatars.githubusercontent.com/u/9782493?v=4"}, J
        if path == "/user/orgs":
            return 200, paginate([{"login": o, "id": i + 1, "avatar_url": ""} for i, o in enumerate(ORGS)], qs), J
        if path == "/user/enterprise-memberships":
            return 200, paginate([{"enterprise": {"slug": s, "name": s, "id": i + 1}, "role": "admin"}
                                  for i, s in enumerate(ENTERPRISES)], qs), J
        if r := m(r"/orgs/([^/]+)"):
            return 200, {"login": r[1], "company": ""}, J
        if r := m(r"/orgs/([^/]+)/members"):
            return 200, paginate(ORG_MEMBERS.get(r[1], []), qs), J
        if r := m(r"/orgs/([^/]+)/teams/([^/]+)/members"):
            return 200, [], J
        if r := m(r"/orgs/([^/]+)/teams/([^/]+)/memberships/([^/]+)"):
            if method == "PUT":
                return 200, {"state": "active", "role": (body or {}).get("role", "member")}, J
            if method == "DELETE":
                return 204, None, J
        if r := m(r"/orgs/([^/]+)/copilot/billing"):
            b = BILLING.get(r[1])
            if not b or b.get("_synthetic"):
                return nf
            return 200, {k: v for k, v in b.items() if not k.startswith("_")}, J
        if r := m(r"/orgs/([^/]+)/copilot/billing/seats"):
            s = SEATS.get(r[1])
            if s is None:
                return nf
            return 200, {"total_seats": s.get("total_seats", 0), "seats": paginate(s.get("seats", []), qs)}, J
        if r := m(r"/orgs/([^/]+)/copilot/billing/selected_users"):
            names = (body or {}).get("selected_usernames", [])
            key = "seats_cancelled" if method == "DELETE" else "seats_created"
            return 200 if method == "DELETE" else 201, {key: len(names)}, J
        if r := m(r"/enterprises/([^/]+)/copilot/billing/seats"):
            s = SEATS.get(f"{r[1]}-enterprise")
            if s is None:
                return nf
            return 200, {"total_seats": s.get("total_seats", 0), "seats": paginate(s.get("seats", []), qs)}, J
        if r := m(r"/orgs/([^/]+)/copilot/metrics"):
            return (200, METRICS[r[1]], J) if r[1] in METRICS else nf
        if r := m(r"/(orgs|enterprises)/([^/]+)/copilot/metrics/reports/([a-z0-9-]+)(/latest)?"):
            scope = r[2] if r[1] == "orgs" else f"{r[2]}-enterprise"
            kind = "users" if r[3].startswith("users") else "org"
            src = (USAGE_USERS if kind == "users" else USAGE).get(scope)
            if not src:
                return nf
            meta = {"download_links": [f"{BASE}/__download/{kind}/{scope}"]}
            for k in ("report_start_day", "report_end_day"):
                if k in src:
                    meta[k] = src[k]
            if "day" in qs:
                meta = {"download_links": meta["download_links"], "report_day": qs["day"][0]}
            return 200, meta, J
        if r := m(r"/__download/(users|org)/([^/]+)"):
            src = (USAGE_USERS if r[1] == "users" else USAGE).get(r[2]) or {}
            return 200, "\n".join(json.dumps(x) for x in src.get("records", [])), "application/x-ndjson"
        if r := m(r"/organizations/([^/]+)/settings/billing/ai_credit/usage"):
            return (200, AI_CREDITS[r[1]], J) if r[1] in AI_CREDITS else nf
        if r := m(r"/enterprises/([^/]+)/settings/billing/ai_credit/usage"):
            k = f"{r[1]}-enterprise"
            return (200, AI_CREDITS[k], J) if k in AI_CREDITS else nf

        # cost centers
        if r := m(r"/enterprises/([^/]+)/settings/billing/cost-centers"):
            centers = COST_CENTERS.setdefault(r[1], [])
            if method == "POST":
                cc = {"id": str(uuid.uuid4()), "name": (body or {}).get("name", ""), "state": "active",
                      "ai_credit_pool_enabled": (body or {}).get("ai_credit_pool_enabled", False), "resources": []}
                centers.append(cc)
                return 201, cc, J
            state = qs.get("state", ["active"])[0]
            return 200, {"costCenters": paginate([c for c in centers if c.get("state", "active") == state], qs)}, J
        if r := m(r"/enterprises/([^/]+)/settings/billing/cost-centers/([^/]+)"):
            centers = COST_CENTERS.setdefault(r[1], [])
            cc = next((c for c in centers if c["id"] == r[2]), None)
            if cc is None:
                return nf
            if method == "PATCH":
                cc.update({k: v for k, v in (body or {}).items() if k in ("name", "ai_credit_pool_enabled")})
            elif method == "DELETE":
                cc["state"] = "archived"
                return 200, {"message": "Cost center successfully deleted.", "id": cc["id"], "costCenterState": "Archived"}, J
            return 200, cc, J
        if r := m(r"/enterprises/([^/]+)/settings/billing/cost-centers/([^/]+)/resource"):
            centers = COST_CENTERS.setdefault(r[1], [])
            cc = next((c for c in centers if c["id"] == r[2]), None)
            if cc is None:
                return nf
            b = body or {}
            res = [("User", u) for u in b.get("users", [])] + [("Org", o) for o in b.get("organizations", [])] + \
                  [("Repo", x) for x in b.get("repositories", [])]
            reassigned = []
            if method == "POST":
                for t, n in res:
                    for other in centers:
                        if other is not cc and t == "User" and any(x["type"] == t and x["name"] == n for x in other["resources"]):
                            other["resources"] = [x for x in other["resources"] if not (x["type"] == t and x["name"] == n)]
                            reassigned.append({"resource_type": t, "name": n, "previous_cost_center": other["name"]})
                    if not any(x["type"] == t and x["name"] == n for x in cc["resources"]):
                        cc["resources"].append({"type": t, "name": n})
                return 200, {"message": "Resources successfully added to the cost center.", "reassigned_resources": reassigned}, J
            cc["resources"] = [x for x in cc["resources"] if (x["type"], x["name"]) not in res]
            return 200, {"message": "Resources successfully removed from the cost center."}, J

        # budgets
        if r := m(r"/(enterprises|organizations)/([^/]+)/settings/billing/budgets"):
            budgets = BUDGETS.setdefault(r[2], [])
            if method == "POST":
                b = dict(body or {})
                b["id"] = str(uuid.uuid4())
                budgets.append(b)
                return 200, {"message": "Budget successfully created.", "budget": b}, J
            scope = qs.get("scope", [None])[0]
            items = [b for b in budgets if not scope or b.get("budget_scope") == scope]
            page = int(qs.get("page", ["1"])[0]); per = int(qs.get("per_page", ["10"])[0])
            chunk = items[(page - 1) * per: page * per]
            return 200, {"budgets": chunk, "total_count": len(items), "has_next_page": page * per < len(items)}, J
        if r := m(r"/(enterprises|organizations)/([^/]+)/settings/billing/budgets/([^/]+)"):
            budgets = BUDGETS.setdefault(r[2], [])
            b = next((x for x in budgets if x.get("id") == r[3]), None)
            if b is None:
                return nf
            if method == "PATCH":
                b.update(body or {})
                return 200, {"message": "Budget successfully updated.", "budget": b}, J
            if method == "DELETE":
                budgets.remove(b)
                return 200, {"message": "Budget successfully deleted.", "id": r[3]}, J
            return 200, b, J

        # enterprise teams
        if r := m(r"/enterprises/([^/]+)/teams"):
            teams = TEAMS.setdefault(r[1], [])
            if method == "POST":
                t = dict(body or {})
                t.update({"id": len(teams) + 1000, "slug": "ent:" + t.get("name", "team").lower().replace(" ", "-"),
                          "members": [], "organizations": []})
                teams.append(t)
                return 201, {k: v for k, v in t.items() if k not in ("members", "organizations")}, J
            return 200, paginate([{k: v for k, v in t.items() if k not in ("members", "organizations", "member_count")}
                                  for t in teams], qs), J
        if r := m(r"/enterprises/([^/]+)/teams/([^/]+)"):
            teams = TEAMS.setdefault(r[1], [])
            t = next((x for x in teams if x["slug"] == r[2]), None)
            if t is None:
                return nf
            if method == "PATCH":
                t.update(body or {})
            elif method == "DELETE":
                teams.remove(t)
                return 204, None, J
            return 200, {k: v for k, v in t.items() if k not in ("members", "organizations", "member_count")}, J
        if r := m(r"/enterprises/([^/]+)/teams/([^/]+)/memberships(/add|/remove)?"):
            teams = TEAMS.setdefault(r[1], [])
            t = next((x for x in teams if x["slug"] == r[2]), None)
            if t is None:
                return nf
            if method == "POST":
                users = (body or {}).get("usernames", [])
                if r[3] == "/remove":
                    t["members"] = [x for x in t["members"] if x["login"] not in users]
                else:
                    t["members"] += [{"login": u, "avatar_url": "", "html_url": ""} for u in users
                                     if u not in {x["login"] for x in t["members"]}]
                return 200, t["members"], J
            return 200, paginate(t.get("members", []), qs), J
        if r := m(r"/enterprises/([^/]+)/teams/([^/]+)/organizations(/add|/remove)?"):
            teams = TEAMS.setdefault(r[1], [])
            t = next((x for x in teams if x["slug"] == r[2]), None)
            if t is None:
                return nf
            if method == "POST":
                orgs = (body or {}).get("organization_slugs", [])
                if r[3] == "/remove":
                    t["organizations"] = [o for o in t["organizations"] if o not in orgs]
                else:
                    t["organizations"] += [o for o in orgs if o not in t["organizations"]]
                return 200, [{"login": o} for o in t["organizations"]], J
            return 200, paginate([{"login": o} for o in t.get("organizations", [])], qs), J
        if r := m(r"/enterprises/([^/]+)/organizations"):
            return 200, paginate([{"login": o} for o in ORGS], qs), J

        # billing report exports
        if r := m(r"/enterprises/([^/]+)/settings/billing/reports"):
            if method == "POST":
                rid = str(uuid.uuid4())
                rt = (body or {}).get("report_type")
                src = "ai_usage_csv/ai_usage_latest.csv" if rt == "ai_credit" else "usage_report_csv/usage_report_latest.csv"
                REPORTS[rid] = {"id": rid, "report_type": rt, "start_date": (body or {}).get("start_date"),
                                "end_date": (body or {}).get("end_date"), "status": "completed",
                                "download_urls": [f"{BASE}/__csv/{rid}"], "_src": src}
                return 201, {k: v for k, v in REPORTS[rid].items() if k not in ("_src", "download_urls")} | {"status": "processing"}, J
            return 200, {"usage_report_exports": [{k: v for k, v in x.items() if not k.startswith("_") and k != "download_urls"}
                                                  for x in REPORTS.values()]}, J
        if r := m(r"/enterprises/([^/]+)/settings/billing/reports/([^/]+)"):
            rep = REPORTS.get(r[2])
            return (200, {k: v for k, v in rep.items() if not k.startswith("_")}, J) if rep else nf
        if r := m(r"/__csv/([^/]+)"):
            rep = REPORTS.get(r[1])
            return (200, csv_text(rep["_src"]), "text/csv") if rep else nf
        return nf


if __name__ == "__main__":
    print(f"mock github on {BASE} (user={LOGIN}, orgs={ORGS}, enterprises={ENTERPRISES})", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
