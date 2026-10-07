"""
Credential health of the data-sync PATs.

Every sync starts by asking GitHub who each PAT belongs to. An expired, revoked
or blocked token is recorded on the PAT and reported to the UI, so a scheduled
sync that cannot reach GitHub is visible instead of silently leaving the
dashboards stale.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Callable

import httpx

from .github_api import GitHubAPI
from .github_host import DEFAULT_HOST, api_base_url
from .pat_manager import pat_manager

logger = logging.getLogger(__name__)

LogFn = Callable[[str, str], None]

# Warn this many days before a PAT's expiration date
EXPIRY_WARNING_DAYS = 7

# Header GitHub sends on authenticated requests made with an expiring PAT
EXPIRY_HEADER = "github-authentication-token-expiration"

# A single network blip must not raise an "unreachable" alert
NETWORK_ATTEMPTS = 2
NETWORK_RETRY_DELAY = 2.0

# States that stop a PAT from syncing anything
BLOCKING_STATES = ("invalid", "forbidden", "unreachable")


def parse_expiry(value: str | None) -> datetime | None:
    """Parse GitHub's token expiration header, e.g. ``2026-10-20 08:00:00 UTC``."""
    if not value:
        return None
    value = value.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M:%S %Z", "%Y-%m-%d %H:%M:%S"):
        try:
            parsed = datetime.strptime(value, fmt)
        except ValueError:
            continue
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def classify(status: int | None, detail: str = "", expiry: str | None = None,
             now: datetime | None = None) -> dict:
    """Turn a ``GET /user`` outcome into a credential state.

    ``status`` is None when GitHub could not be reached at all.
    """
    now = now or datetime.now(timezone.utc)
    expires_at = parse_expiry(expiry)
    if status is None:
        state = "unreachable"
    elif status == 401:
        state = "invalid"
        detail = detail or "Bad credentials"
    elif status == 403:
        state = "forbidden"
    elif 200 <= status < 300:
        state = "ok"
        if expires_at and expires_at - now <= timedelta(days=EXPIRY_WARNING_DAYS):
            state = "expiring"
    else:
        state = "unreachable"
    return {
        "state": state,
        "status": status,
        "detail": (detail or "").strip()[:300],
        "expires_at": expires_at.isoformat() if expires_at else None,
        "checked_at": now.isoformat(),
    }


async def check_token(token: str, host: str) -> dict:
    """Check one token against its GitHub host."""
    api = GitHubAPI(token=token, base_url=api_base_url(host or DEFAULT_HOST))
    try:
        for attempt in range(NETWORK_ATTEMPTS):
            try:
                resp = await api.client.get("/user")
                break
            except httpx.TransportError as e:
                if attempt + 1 == NETWORK_ATTEMPTS:
                    return classify(None, f"{type(e).__name__}: {e}".rstrip(": "))
                await asyncio.sleep(NETWORK_RETRY_DELAY)
    finally:
        await api.close()
    detail = "" if resp.is_success else GitHubAPI._error_detail(resp)
    result = classify(resp.status_code, detail, resp.headers.get(EXPIRY_HEADER))
    if resp.is_success:
        result["login"] = resp.json().get("login", "")
    return result


def describe(pat: dict, credential: dict) -> str:
    """One log line explaining a credential problem."""
    name = f"PAT '{pat.get('label') or pat.get('user_login') or pat['id']}' ({pat.get('host') or DEFAULT_HOST})"
    state = credential["state"]
    detail = f": {credential['detail']}" if credential.get("detail") else ""
    if state == "invalid":
        return f"{name} was rejected by GitHub (HTTP 401{detail}). The token has expired or been revoked; replace it in Settings > PAT Manager"
    if state == "forbidden":
        return f"{name} is not allowed to call GitHub (HTTP 403{detail}). Check its permissions, SSO authorization and rate limits"
    if state == "unreachable":
        return f"{name} could not reach GitHub{detail}"
    if state == "expiring":
        return f"{name} expires on {credential['expires_at'][:10]}; renew it before then or syncs will fail"
    return f"{name} is valid"


async def check_all(log_fn: LogFn | None = None) -> list[dict]:
    """Check every PAT, store the result on it and log anything that needs attention."""
    results = []
    for pat in pat_manager.get_all():
        credential = await check_token(pat["token"], pat.get("host") or DEFAULT_HOST)
        credential.pop("login", None)
        pat_manager.update(pat["id"], credential=credential)
        results.append({"pat_id": pat["id"], **credential})
        if credential["state"] != "ok":
            level = "error" if credential["state"] in BLOCKING_STATES else "warn"
            message = describe(pat, credential)
            logger.warning("[credentials] %s", message)
            if log_fn:
                log_fn(level, message)
    return results


def record_failure(pat_id: str, error: Exception) -> None:
    """Record a credential failure seen outside a health check (e.g. discovery)."""
    if isinstance(error, httpx.HTTPStatusError):
        resp = error.response
        credential = classify(resp.status_code, GitHubAPI._error_detail(resp), resp.headers.get(EXPIRY_HEADER))
    elif isinstance(error, httpx.HTTPError):
        credential = classify(None, f"{type(error).__name__}: {error}".rstrip(": "))
    else:
        return
    pat_manager.update(pat_id, credential=credential)


def problems() -> list[dict]:
    """PATs whose last check found something the admin must act on."""
    result = []
    for pat in pat_manager.get_all():
        credential = pat.get("credential") or {}
        if credential.get("state") in (*BLOCKING_STATES, "expiring"):
            result.append({
                "pat_id": pat["id"],
                "label": pat.get("label", ""),
                "user_login": pat.get("user_login", ""),
                "host": pat.get("host") or DEFAULT_HOST,
                **credential,
            })
    return result


async def preflight(log_fn: LogFn) -> None:
    """Run before every sync: check credentials, re-discover PATs that now work.

    A PAT whose discovery failed at startup (expired, network down) contributes
    no organizations, so later syncs would quietly cover nothing even after the
    token is fixed. Re-running discovery here recovers from that.
    """
    from .api_manager import api_manager

    results = await check_all(log_fn)
    discovered = api_manager.get_discovered_users()
    undiscovered = [
        r["pat_id"] for r in results
        if r["state"] in ("ok", "expiring") and r["pat_id"] not in discovered
    ]
    if undiscovered:
        log_fn("info", f"Re-discovering organizations for {len(undiscovered)} PAT(s) that were not discovered at startup")
        await api_manager.rebuild()
