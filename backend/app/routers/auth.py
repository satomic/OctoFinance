"""
Simple single-user authentication for OctoFinance.
Credentials stored in data/auth.json, sessions kept in memory.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from pathlib import Path

from fastapi import APIRouter, Cookie, Request, Response
from pydantic import BaseModel

from ..config import DATA_DIR

router = APIRouter(prefix="/auth", tags=["auth"])

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_AUTH_FILE = DATA_DIR / "auth.json"

# In-memory session tokens (cleared on server restart)
_active_sessions: set[str] = set()

# Paths that do NOT require authentication
AUTH_PUBLIC_PATHS = {"/api/auth/status", "/api/auth/setup", "/api/auth/login"}


def _load_auth() -> dict | None:
    """Load credentials from auth.json, return None if not set up."""
    if not _AUTH_FILE.exists():
        return None
    try:
        with open(_AUTH_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _save_auth(data: dict) -> None:
    with open(_AUTH_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000).hex()


def _verify_password(password: str, stored_hash: str, salt_hex: str) -> bool:
    salt = bytes.fromhex(salt_hex)
    return _hash_password(password, salt) == stored_hash


def is_authenticated(session_token: str | None) -> bool:
    """Check if a session token is valid."""
    return session_token is not None and session_token in _active_sessions


# ---------------------------------------------------------------------------
# Param models
# ---------------------------------------------------------------------------

class SetupParams(BaseModel):
    username: str
    password: str


class LoginParams(BaseModel):
    username: str
    password: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/status")
async def auth_status(octofinance_session: str | None = Cookie(default=None)):
    """Check if auth is set up and if current request is authenticated."""
    auth_data = _load_auth()
    return {
        "setup_required": auth_data is None,
        "authenticated": is_authenticated(octofinance_session),
    }


@router.post("/setup")
async def auth_setup(params: SetupParams, response: Response):
    """Create initial credentials. Only works if no credentials exist yet."""
    if _load_auth() is not None:
        return {"error": "Credentials already configured. Use login instead."}

    if not params.username.strip() or not params.password.strip():
        return {"error": "Username and password are required."}

    salt = os.urandom(32)
    password_hash = _hash_password(params.password, salt)

    _save_auth({
        "username": params.username.strip(),
        "password_hash": password_hash,
        "salt": salt.hex(),
    })

    # Auto-login after setup
    token = secrets.token_hex(32)
    _active_sessions.add(token)
    response.set_cookie(
        key="octofinance_session",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 7,  # 7 days
    )

    return {"ok": True}


@router.post("/login")
async def auth_login(params: LoginParams, response: Response):
    """Verify credentials and create a session."""
    auth_data = _load_auth()
    if auth_data is None:
        return {"error": "No credentials configured. Please set up first."}

    if params.username.strip() != auth_data["username"]:
        return {"error": "Invalid username or password."}

    if not _verify_password(params.password, auth_data["password_hash"], auth_data["salt"]):
        return {"error": "Invalid username or password."}

    token = secrets.token_hex(32)
    _active_sessions.add(token)
    response.set_cookie(
        key="octofinance_session",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 7,  # 7 days
    )

    return {"ok": True}


@router.post("/logout")
async def auth_logout(response: Response, octofinance_session: str | None = Cookie(default=None)):
    """Clear session."""
    if octofinance_session and octofinance_session in _active_sessions:
        _active_sessions.discard(octofinance_session)
    response.delete_cookie("octofinance_session")
    return {"ok": True}
