"""
Cost center report sharing.

Two routers:
- ``admin_router`` (mounted under /api, protected by the auth middleware):
  manage share configuration per cost center.
- ``public_router`` (mounted at root, NOT protected): serves the shared
  cost-center report page (public or password-protected) without requiring
  an OctoFinance account.

Share configuration is persisted in ``data/cc_shares.json``.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from datetime import datetime, timezone
from html import escape

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from ..config import DATA_DIR
from ..services.data_collector import data_collector
from ..services.report_generator import generate_single_report_html

admin_router = APIRouter(tags=["cc-share"])
public_router = APIRouter(tags=["cc-share-public"])

_SHARES_FILE = DATA_DIR / "cc_shares.json"

# In-memory verified password sessions: entries of f"{token}:{cookie_value}"
_verified_sessions: set[str] = set()


# ---------------------------------------------------------------------------
# Storage helpers
# ---------------------------------------------------------------------------

def _load_shares() -> dict:
    if not _SHARES_FILE.exists():
        return {}
    try:
        with open(_SHARES_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("shares", {}) if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_shares(shares: dict) -> None:
    with open(_SHARES_FILE, "w", encoding="utf-8") as f:
        json.dump({"shares": shares}, f, indent=2, ensure_ascii=False)


def _key(enterprise: str, cc_id: str) -> str:
    return f"{enterprise}::{cc_id}"


def _find_by_token(token: str) -> dict | None:
    for share in _load_shares().values():
        if share.get("token") == token:
            return share
    return None


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000).hex()


def _public_info(share: dict) -> dict:
    """Share info safe to return to the (authenticated) admin frontend."""
    return {
        "cc_id": share["cc_id"],
        "cc_name": share.get("cc_name", ""),
        "token": share["token"],
        "mode": share.get("mode", "public"),
        "url": f"/share/cc/{share['token']}",
        "created_at": share.get("created_at", ""),
        "updated_at": share.get("updated_at", ""),
    }


# ---------------------------------------------------------------------------
# Admin endpoints (authenticated, under /api)
# ---------------------------------------------------------------------------

class ShareConfigParams(BaseModel):
    enterprise: str
    cc_id: str
    cc_name: str = ""
    mode: str = Field(default="public", pattern="^(public|password)$")
    password: str = ""


@admin_router.get("/data/cost-center-shares")
async def list_cost_center_shares(enterprise: str = Query(default="")):
    """List share configs, keyed by cost center id."""
    out = {}
    for share in _load_shares().values():
        if enterprise and share.get("enterprise") != enterprise:
            continue
        out[share["cc_id"]] = _public_info(share)
    return {"shares": out}


@admin_router.post("/data/cost-center-share")
async def upsert_cost_center_share(params: ShareConfigParams):
    """Create or update the share config for one cost center."""
    if not params.enterprise or not params.cc_id:
        return {"error": "enterprise and cc_id are required"}

    shares = _load_shares()
    key = _key(params.enterprise, params.cc_id)
    existing = shares.get(key)
    now = datetime.now(timezone.utc).isoformat()

    share = existing or {
        "enterprise": params.enterprise,
        "cc_id": params.cc_id,
        "token": secrets.token_urlsafe(24),
        "created_at": now,
    }
    share["cc_name"] = params.cc_name or share.get("cc_name", "")
    share["mode"] = params.mode
    share["updated_at"] = now

    if params.mode == "password":
        if params.password:
            salt = os.urandom(32)
            share["password_hash"] = _hash_password(params.password, salt)
            share["salt"] = salt.hex()
            # Invalidate previously verified sessions for this share
            token = share["token"]
            _verified_sessions.difference_update(
                {s for s in _verified_sessions if s.startswith(f"{token}:")}
            )
        elif not share.get("password_hash"):
            return {"error": "Password is required for password-protected sharing"}
    else:
        share.pop("password_hash", None)
        share.pop("salt", None)

    shares[key] = share
    _save_shares(shares)
    return {"share": _public_info(share)}


@admin_router.delete("/data/cost-center-share")
async def delete_cost_center_share(
    enterprise: str = Query(default=""),
    cc_id: str = Query(default=""),
):
    """Disable sharing for one cost center (removes the share link)."""
    shares = _load_shares()
    key = _key(enterprise, cc_id)
    share = shares.pop(key, None)
    if share is None:
        return {"error": "Share not found"}
    token = share.get("token", "")
    _verified_sessions.difference_update(
        {s for s in _verified_sessions if s.startswith(f"{token}:")}
    )
    _save_shares(shares)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Public endpoints (no OctoFinance auth)
# ---------------------------------------------------------------------------

_PAGE_CSS = """
:root{--bg:#0d1117;--card:#161b22;--border:#30363d;--text:#e6edf3;
--muted:#768390;--accent:#539bf5;--red:#e5534b}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
background:var(--bg);color:var(--text);
font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif}
.card{background:var(--card);border:1px solid var(--border);border-radius:12px;
padding:32px;width:380px;max-width:90vw;text-align:center}
.brand{font-size:12px;color:var(--muted);letter-spacing:.4px;margin-bottom:8px}
h1{font-size:18px;margin:0 0 6px}
p{font-size:13px;color:var(--muted);margin:0 0 20px}
input[type=password]{width:100%;padding:10px 12px;border-radius:8px;
border:1px solid var(--border);background:var(--bg);color:var(--text);
font-size:14px;outline:none;margin-bottom:12px}
input[type=password]:focus{border-color:var(--accent)}
button{width:100%;padding:10px;border:none;border-radius:8px;background:var(--accent);
color:#fff;font-size:14px;font-weight:600;cursor:pointer}
button:hover{filter:brightness(1.1)}
.err{color:var(--red);font-size:13px;margin:0 0 12px}
"""


def _password_page(token: str, cc_name: str, error: str = "") -> HTMLResponse:
    err_html = f'<p class="err">{escape(error)}</p>' if error else ""
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Cost Center Report · {escape(cc_name)}</title>
<style>{_PAGE_CSS}</style>
</head>
<body>
<div class="card">
  <div class="brand">OctoFinance · Cost Center Report</div>
  <h1>{escape(cc_name)}</h1>
  <p>This report is password protected.</p>
  {err_html}
  <form method="post" action="/share/cc/{escape(token)}/verify">
    <input type="password" name="password" placeholder="Password" autofocus required>
    <button type="submit">View Report</button>
  </form>
</div>
</body>
</html>"""
    return HTMLResponse(html, status_code=401 if error else 200)


def _error_page(message: str, status: int = 404) -> HTMLResponse:
    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>OctoFinance</title><style>{_PAGE_CSS}</style></head>
<body><div class="card">
  <div class="brand">OctoFinance · Cost Center Report</div>
  <h1>Unavailable</h1><p>{escape(message)}</p>
</div></body></html>"""
    return HTMLResponse(html, status_code=status)


def _cookie_name(token: str) -> str:
    return f"ccshare_{token[:16]}"


def _has_access(share: dict, request: Request) -> bool:
    if share.get("mode", "public") == "public":
        return True
    cookie = request.cookies.get(_cookie_name(share["token"]))
    return bool(cookie) and f"{share['token']}:{cookie}" in _verified_sessions


def _render_shared_report(share: dict, for_download: bool) -> str | None:
    """Build the report HTML for a shared cost center, or None if data is gone."""
    # Local import to avoid a circular import (routers.data imports report_generator)
    from .data import CSV_TYPE_AI, CSV_TYPE_USAGE, _load_all_csv_records

    enterprise = share["enterprise"]
    cc_data = data_collector.load_latest("cost_centers", enterprise)
    if not cc_data:
        return None
    cc = next(
        (c for c in cc_data.get("cost_centers", [])
         if str(c.get("id")) == str(share["cc_id"])),
        None,
    )
    if cc is None:
        return None

    return generate_single_report_html(
        enterprise=enterprise,
        enterprise_name=cc_data.get("enterprise_name", enterprise),
        cc=cc,
        all_ai_usage_records=_load_all_csv_records(CSV_TYPE_AI),
        all_usage_records=_load_all_csv_records(CSV_TYPE_USAGE),
        download_url=None if for_download else f"/share/cc/{share['token']}/download",
    )


@public_router.get("/share/cc/{token}")
async def view_shared_report(token: str, request: Request):
    share = _find_by_token(token)
    if share is None:
        return _error_page("This share link does not exist or has been disabled.")
    if not _has_access(share, request):
        return _password_page(token, share.get("cc_name", "Cost Center"))
    html = _render_shared_report(share, for_download=False)
    if html is None:
        return _error_page("Report data is not available. Please contact the administrator.", 503)
    return HTMLResponse(html)


@public_router.post("/share/cc/{token}/verify")
async def verify_shared_report_password(token: str, password: str = Form(default="")):
    share = _find_by_token(token)
    if share is None:
        return _error_page("This share link does not exist or has been disabled.")
    if share.get("mode") != "password":
        return RedirectResponse(f"/share/cc/{token}", status_code=303)

    salt_hex = share.get("salt", "")
    stored = share.get("password_hash", "")
    ok = bool(salt_hex and stored) and secrets.compare_digest(
        _hash_password(password, bytes.fromhex(salt_hex)), stored
    )
    if not ok:
        return _password_page(token, share.get("cc_name", "Cost Center"), error="Incorrect password.")

    session = secrets.token_hex(16)
    _verified_sessions.add(f"{token}:{session}")
    resp = RedirectResponse(f"/share/cc/{token}", status_code=303)
    resp.set_cookie(
        key=_cookie_name(token),
        value=session,
        httponly=True,
        samesite="lax",
        path=f"/share/cc/{token}",
        max_age=60 * 60 * 24,  # 24 hours
    )
    return resp


@public_router.get("/share/cc/{token}/download")
async def download_shared_report(token: str, request: Request):
    share = _find_by_token(token)
    if share is None:
        return _error_page("This share link does not exist or has been disabled.")
    if not _has_access(share, request):
        return _password_page(token, share.get("cc_name", "Cost Center"))
    html = _render_shared_report(share, for_download=True)
    if html is None:
        return _error_page("Report data is not available. Please contact the administrator.", 503)

    safe_name = (share.get("cc_name") or "cost-center").replace("/", "_").replace("\\", "_").replace(" ", "_")
    ascii_name = safe_name.encode("ascii", "ignore").decode() or "cost-center"
    return HTMLResponse(
        html,
        headers={"Content-Disposition": f'attachment; filename="{ascii_name}-report.html"'},
    )
