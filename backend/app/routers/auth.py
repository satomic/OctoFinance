"""
Authentication for OctoFinance.

Two login paths:
  * Local username/password (super admin) — credentials in data/auth.json
  * GitHub OAuth SSO — app config in data/oauth.json

Sessions are JSON-persisted (data/auth_sessions.json) so a backend restart does
not log everybody out.
"""

from __future__ import annotations

import logging
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Cookie, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from ..services.auth_store import auth_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

SESSION_COOKIE = "octofinance_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 7  # 7 days

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"

# Paths that do NOT require authentication
AUTH_PUBLIC_PATHS = {
    "/api/auth/status",
    "/api/auth/setup",
    "/api/auth/login",
    "/api/auth/github/login",
    "/api/auth/github/callback",
}

# Paths available to any authenticated user (admins and regular GitHub users).
# Everything else under /api is admin-only.
NON_ADMIN_PATH_PREFIXES = (
    "/api/auth/",
    "/api/me/",
    "/api/budget-requests",
)

# Admin-only endpoints that live under an otherwise non-admin prefix.
ADMIN_ONLY_PATHS = {
    "/api/auth/github/config",
}


# ---------------------------------------------------------------------------
# Helpers used by the app middleware
# ---------------------------------------------------------------------------

def get_current_user(session_token: str | None) -> dict | None:
    """Return the session payload for a token, or None when not logged in."""
    return auth_store.get_session(session_token)


def is_authenticated(session_token: str | None) -> bool:
    return auth_store.get_session(session_token) is not None


def is_admin(session_token: str | None) -> bool:
    session = auth_store.get_session(session_token)
    return bool(session and session.get("is_admin"))


def require_user(request: Request) -> dict | None:
    """Fetch the current user from a FastAPI request object."""
    return auth_store.get_session(request.cookies.get(SESSION_COOKIE))


def _forwarded_origin(request: Request) -> str:
    """Origin of the incoming request, honouring reverse-proxy headers.

    Behind nginx / Cloudflare / a tunnel, ``request.base_url`` reports the
    internal scheme+host, which breaks both the OAuth redirect_uri and the
    Secure-cookie decision. ``X-Forwarded-Proto`` / ``X-Forwarded-Host`` win
    when present.
    """
    headers = request.headers
    proto = (headers.get("x-forwarded-proto") or "").split(",")[0].strip()
    host = (headers.get("x-forwarded-host") or "").split(",")[0].strip()
    if not proto:
        proto = request.url.scheme
    if not host:
        host = headers.get("host") or request.url.netloc
    return f"{proto}://{host}"


def _is_secure_request(request: Request) -> bool:
    return _forwarded_origin(request).startswith("https://")


def _set_session_cookie(response: Response, token: str, request: Request | None = None) -> None:
    # Mark the cookie Secure when the site is served over HTTPS, otherwise the
    # browser may refuse it (and it should never travel in clear text anyway).
    secure = _is_secure_request(request) if request is not None else False
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        secure=secure,
        max_age=SESSION_MAX_AGE,
        path="/",
    )


def _public_user(session: dict | None) -> dict | None:
    if not session:
        return None
    return {
        "login": session.get("login", ""),
        "name": session.get("name", ""),
        "avatar_url": session.get("avatar_url", ""),
        "auth_type": session.get("auth_type", "local"),
        "is_admin": bool(session.get("is_admin")),
        "github_id": session.get("github_id"),
    }


def _callback_url(request: Request) -> str:
    """Resolve the OAuth callback URL (explicit config wins)."""
    configured = auth_store.get_oauth_config().get("callback_url", "").strip()
    if configured:
        return configured
    return f"{_forwarded_origin(request)}/api/auth/github/callback"


# ---------------------------------------------------------------------------
# Param models
# ---------------------------------------------------------------------------

class SetupParams(BaseModel):
    username: str
    password: str


class LoginParams(BaseModel):
    username: str
    password: str


class OAuthConfigParams(BaseModel):
    client_id: str | None = None
    client_secret: str | None = None
    callback_url: str | None = None
    admins: list[str] | None = None
    allow_all_users: bool | None = None


# ---------------------------------------------------------------------------
# Status / local login
# ---------------------------------------------------------------------------

@router.get("/status")
async def auth_status(request: Request, octofinance_session: str | None = Cookie(default=None)):
    """Auth state for the login gate: setup needed, current user, SSO availability."""
    from ..config import APP_VERSION
    from ..services.update_checker import update_checker

    session = auth_store.get_session(octofinance_session)
    if octofinance_session and session is None:
        # A cookie was presented but no matching session exists. Usually means
        # the session was created by a different worker/process, or the server
        # was restarted with a non-persistent data directory.
        logger.warning(
            "[auth] Session cookie presented but not found (host=%s). "
            "If OctoFinance runs with multiple workers, ensure they share the "
            "same data directory.",
            request.headers.get("host", "?"),
        )

    return {
        "setup_required": auth_store.load_credentials() is None,
        "authenticated": session is not None,
        "user": _public_user(session),
        "is_admin": bool(session and session.get("is_admin")),
        "github_enabled": auth_store.is_github_enabled(),
        "version": APP_VERSION,
        "update": update_checker.state,
    }


@router.post("/setup")
async def auth_setup(params: SetupParams, request: Request, response: Response):
    """Create initial local credentials. Only works if none exist yet."""
    if auth_store.load_credentials() is not None:
        return {"error": "Credentials already configured. Use login instead."}

    username = params.username.strip()
    if not username or not params.password.strip():
        return {"error": "Username and password are required."}

    auth_store.save_credentials(username, params.password)
    token = auth_store.create_session(
        login=username, name=username, auth_type="local", is_admin=True
    )
    _set_session_cookie(response, token, request)
    return {"ok": True}


@router.post("/login")
async def auth_login(params: LoginParams, request: Request, response: Response):
    """Verify local credentials and create a session."""
    auth_data = auth_store.load_credentials()
    if auth_data is None:
        return {"error": "No credentials configured. Please set up first."}

    if params.username.strip() != auth_data["username"] or not auth_store.verify_password(
        params.password, auth_data["password_hash"], auth_data["salt"]
    ):
        return {"error": "Invalid username or password."}

    token = auth_store.create_session(
        login=auth_data["username"],
        name=auth_data["username"],
        auth_type="local",
        is_admin=True,
    )
    _set_session_cookie(response, token, request)
    return {"ok": True}


@router.post("/logout")
async def auth_logout(response: Response, octofinance_session: str | None = Cookie(default=None)):
    """Clear session."""
    auth_store.destroy_session(octofinance_session)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


# ---------------------------------------------------------------------------
# GitHub OAuth (SSO)
# ---------------------------------------------------------------------------

@router.get("/github/login")
async def github_login(request: Request):
    """Redirect the browser to GitHub's OAuth consent screen."""
    cfg = auth_store.get_oauth_config()
    if not cfg.get("client_id") or not cfg.get("client_secret"):
        return RedirectResponse(url="/?auth_error=github_not_configured", status_code=302)

    state = auth_store.create_oauth_state()
    redirect_uri = _callback_url(request)
    origin = _forwarded_origin(request)
    if not redirect_uri.startswith(origin):
        logger.warning(
            "[auth] OAuth callback origin (%s) differs from the browsing origin (%s). "
            "The session cookie will be stored on the callback origin, so the user must "
            "browse OctoFinance on that same origin. Fix the 'Callback URL' in "
            "Settings -> GitHub SSO, or leave it blank to auto-detect.",
            redirect_uri, origin,
        )
    logger.info("[auth] GitHub login start: origin=%s redirect_uri=%s", origin, redirect_uri)

    params = {
        "client_id": cfg["client_id"],
        "redirect_uri": redirect_uri,
        "scope": "read:user user:email",
        "state": state,
        "allow_signup": "false",
    }
    return RedirectResponse(url=f"{GITHUB_AUTHORIZE_URL}?{urlencode(params)}", status_code=302)


@router.get("/github/callback")
async def github_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    """Exchange the OAuth code for a token, resolve the user, and start a session."""
    if error:
        return RedirectResponse(url=f"/?auth_error={error}", status_code=302)
    if not code:
        return RedirectResponse(url="/?auth_error=missing_code", status_code=302)
    if not auth_store.consume_oauth_state(state):
        return RedirectResponse(url="/?auth_error=invalid_state", status_code=302)

    cfg = auth_store.get_oauth_config()
    if not cfg.get("client_id") or not cfg.get("client_secret"):
        return RedirectResponse(url="/?auth_error=github_not_configured", status_code=302)

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            token_resp = await client.post(
                GITHUB_TOKEN_URL,
                headers={"Accept": "application/json"},
                data={
                    "client_id": cfg["client_id"],
                    "client_secret": cfg["client_secret"],
                    "code": code,
                    "redirect_uri": _callback_url(request),
                },
            )
            token_resp.raise_for_status()
            token_data = token_resp.json()
            access_token = token_data.get("access_token")
            if not access_token:
                logger.warning("GitHub OAuth token exchange failed: %s", token_data.get("error"))
                return RedirectResponse(url="/?auth_error=token_exchange_failed", status_code=302)

            user_resp = await client.get(
                GITHUB_USER_URL,
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {access_token}",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            user_resp.raise_for_status()
            gh_user = user_resp.json()
    except httpx.HTTPError as exc:
        logger.error("GitHub OAuth error: %s", exc)
        return RedirectResponse(url="/?auth_error=github_api_error", status_code=302)

    login = gh_user.get("login", "")
    if not login:
        return RedirectResponse(url="/?auth_error=no_login", status_code=302)

    admin = auth_store.is_admin_login(login)
    if not admin and not cfg.get("allow_all_users", True):
        return RedirectResponse(url="/?auth_error=not_allowed", status_code=302)

    token = auth_store.create_session(
        login=login,
        name=gh_user.get("name") or login,
        avatar_url=gh_user.get("avatar_url", ""),
        auth_type="github",
        is_admin=admin,
        github_id=gh_user.get("id"),
    )
    secure = _is_secure_request(request)
    logger.info(
        "[auth] GitHub login OK: user=%s admin=%s origin=%s secure_cookie=%s",
        login, admin, _forwarded_origin(request), secure,
    )
    response = RedirectResponse(url="/?login=github", status_code=302)
    _set_session_cookie(response, token, request)
    return response


# ---------------------------------------------------------------------------
# OAuth configuration (admin only — enforced by the app middleware)
# ---------------------------------------------------------------------------

@router.get("/github/config")
async def get_github_config():
    """Return OAuth settings with the client secret masked."""
    cfg = auth_store.get_oauth_config()
    secret = cfg.get("client_secret", "")
    return {
        "client_id": cfg.get("client_id", ""),
        "client_secret_set": bool(secret),
        "client_secret_masked": f"{'*' * 8}{secret[-4:]}" if secret else "",
        "callback_url": cfg.get("callback_url", ""),
        "admins": cfg.get("admins", []),
        "allow_all_users": cfg.get("allow_all_users", True),
        "enabled": auth_store.is_github_enabled(),
    }


@router.put("/github/config")
async def update_github_config(params: OAuthConfigParams):
    """Update OAuth settings. Blank client_secret keeps the stored value."""
    updates = params.model_dump(exclude_none=True)
    if not updates.get("client_secret"):
        updates.pop("client_secret", None)
    auth_store.save_oauth_config(**updates)
    return await get_github_config()
