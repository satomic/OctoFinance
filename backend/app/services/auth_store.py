"""
Authentication store for OctoFinance.

Persists everything as JSON under ``data/``:

- ``auth.json``            local super-admin credentials (username + hash)
- ``oauth.json``           GitHub OAuth App configuration + admin allow-list
- ``auth_sessions.json``   active login sessions (survive backend restarts)

Two login methods are supported:

1. Local username/password (the original super admin).
2. GitHub OAuth (SSO). A GitHub user is treated as an administrator when their
   login appears in the configured admin allow-list, or when they own one of
   the configured PATs (PAT owners are, by definition, Copilot admins).
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
import time
from typing import Any

from ..config import DATA_DIR

AUTH_FILE = DATA_DIR / "auth.json"
OAUTH_FILE = DATA_DIR / "oauth.json"
SESSIONS_FILE = DATA_DIR / "auth_sessions.json"
STATES_FILE = DATA_DIR / "auth_oauth_states.json"

SESSION_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 days
OAUTH_STATE_TTL_SECONDS = 60 * 10  # 10 minutes

DEFAULT_OAUTH: dict[str, Any] = {
    "client_id": "",
    "client_secret": "",
    # Optional. When empty the callback URL is derived from the incoming request.
    "callback_url": "",
    # GitHub logins that get the full admin experience when logging in via SSO.
    "admins": [],
    # When True, any GitHub user may log in. When False only admins + users
    # that already hold a Copilot seat / appear in usage data may log in.
    "allow_all_users": True,
}


def _read_json(path, fallback):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        pass
    return fallback


def _write_json(path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


class AuthStore:
    """JSON-backed credential, OAuth-config and session storage."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sessions: dict[str, dict] = {}
        self._sessions_mtime: float = 0.0
        self._oauth_states: dict[str, float] = {}
        self._load_sessions()

    # ------------------------------------------------------------------
    # Local credentials
    # ------------------------------------------------------------------

    def load_credentials(self) -> dict | None:
        data = _read_json(AUTH_FILE, None)
        return data if isinstance(data, dict) else None

    @staticmethod
    def hash_password(password: str, salt: bytes) -> str:
        return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000).hex()

    def save_credentials(self, username: str, password: str) -> None:
        salt = os.urandom(32)
        _write_json(AUTH_FILE, {
            "username": username,
            "password_hash": self.hash_password(password, salt),
            "salt": salt.hex(),
        })

    def verify_password(self, password: str, stored_hash: str, salt_hex: str) -> bool:
        return secrets.compare_digest(
            self.hash_password(password, bytes.fromhex(salt_hex)), stored_hash
        )

    # ------------------------------------------------------------------
    # GitHub OAuth configuration
    # ------------------------------------------------------------------

    def get_oauth_config(self) -> dict:
        """OAuth config: file values win, environment variables are the fallback."""
        cfg = {**DEFAULT_OAUTH, **(_read_json(OAUTH_FILE, {}) or {})}
        if not cfg.get("client_id"):
            cfg["client_id"] = os.getenv("GITHUB_OAUTH_CLIENT_ID", "")
        if not cfg.get("client_secret"):
            cfg["client_secret"] = os.getenv("GITHUB_OAUTH_CLIENT_SECRET", "")
        if not cfg.get("callback_url"):
            cfg["callback_url"] = os.getenv("GITHUB_OAUTH_CALLBACK_URL", "")
        cfg["admins"] = [str(a).strip() for a in cfg.get("admins") or [] if str(a).strip()]
        return cfg

    def save_oauth_config(self, **kwargs) -> dict:
        cfg = {**DEFAULT_OAUTH, **(_read_json(OAUTH_FILE, {}) or {})}
        for key, value in kwargs.items():
            if value is None or key not in DEFAULT_OAUTH:
                continue
            if key == "admins":
                cfg[key] = [str(v).strip() for v in value if str(v).strip()]
            elif key == "allow_all_users":
                cfg[key] = bool(value)
            else:
                cfg[key] = str(value).strip()
        _write_json(OAUTH_FILE, cfg)
        return self.get_oauth_config()

    def is_github_enabled(self) -> bool:
        cfg = self.get_oauth_config()
        return bool(cfg.get("client_id") and cfg.get("client_secret"))

    def is_admin_login(self, login: str) -> bool:
        """True when a GitHub login should receive the administrator experience."""
        if not login:
            return False
        target = login.strip().lower()
        cfg = self.get_oauth_config()
        if any(a.lower() == target for a in cfg.get("admins", [])):
            return True
        # PAT owners are Copilot admins by definition.
        try:
            from .api_manager import api_manager

            for user in api_manager.get_discovered_users().values():
                if str(user.get("login", "")).lower() == target:
                    return True
        except Exception:
            pass
        return False

    # ------------------------------------------------------------------
    # OAuth state (CSRF protection)
    # ------------------------------------------------------------------

    def _load_states(self) -> dict[str, float]:
        raw = _read_json(STATES_FILE, {})
        if not isinstance(raw, dict):
            return {}
        now = time.time()
        return {
            s: float(t) for s, t in raw.items()
            if isinstance(t, (int, float)) and now - float(t) < OAUTH_STATE_TTL_SECONDS
        }

    def create_oauth_state(self, redirect_to: str = "/") -> str:
        state = secrets.token_urlsafe(24)
        with self._lock:
            # Merge with on-disk states so multiple workers share the same set
            states = {**self._load_states(), **self._oauth_states}
            now = time.time()
            states = {s: t for s, t in states.items() if now - t < OAUTH_STATE_TTL_SECONDS}
            states[state] = now
            self._oauth_states = states
            _write_json(STATES_FILE, states)
        return state

    def consume_oauth_state(self, state: str) -> bool:
        if not state:
            return False
        with self._lock:
            states = {**self._load_states(), **self._oauth_states}
            found = states.pop(state, None) is not None
            self._oauth_states = states
            _write_json(STATES_FILE, states)
            return found

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------

    def _load_sessions(self) -> None:
        raw = _read_json(SESSIONS_FILE, {})
        if not isinstance(raw, dict):
            raw = {}
        now = time.time()
        self._sessions = {
            token: info
            for token, info in raw.items()
            if isinstance(info, dict) and now - float(info.get("created_at", 0)) < SESSION_TTL_SECONDS
        }
        try:
            self._sessions_mtime = SESSIONS_FILE.stat().st_mtime
        except OSError:
            self._sessions_mtime = 0.0

    def _refresh_sessions_if_stale(self) -> None:
        """Re-read sessions from disk when another process has written them.

        Without this, running more than one uvicorn/gunicorn worker means a
        session created in one worker is invisible to all the others.
        """
        try:
            mtime = SESSIONS_FILE.stat().st_mtime
        except OSError:
            return
        if mtime != self._sessions_mtime:
            self._load_sessions()

    def _persist_sessions(self) -> None:
        _write_json(SESSIONS_FILE, self._sessions)
        try:
            self._sessions_mtime = SESSIONS_FILE.stat().st_mtime
        except OSError:
            self._sessions_mtime = 0.0

    def create_session(
        self,
        *,
        login: str,
        name: str = "",
        avatar_url: str = "",
        auth_type: str = "local",
        is_admin: bool = False,
        github_id: int | None = None,
    ) -> str:
        token = secrets.token_hex(32)
        with self._lock:
            self._sessions[token] = {
                "login": login,
                "name": name or login,
                "avatar_url": avatar_url,
                "auth_type": auth_type,
                "is_admin": is_admin,
                "github_id": github_id,
                "created_at": time.time(),
            }
            self._persist_sessions()
        return token

    def get_session(self, token: str | None) -> dict | None:
        if not token:
            return None
        with self._lock:
            info = self._sessions.get(token)
            if info is None:
                # Another worker/process may have created it — re-read from disk
                self._refresh_sessions_if_stale()
                info = self._sessions.get(token)
            if not info:
                return None
            if time.time() - float(info.get("created_at", 0)) >= SESSION_TTL_SECONDS:
                self._sessions.pop(token, None)
                self._persist_sessions()
                return None
        # Admin status for SSO users is re-evaluated on every request so that
        # allow-list changes take effect without forcing a re-login.
        if info.get("auth_type") == "github":
            info = {**info, "is_admin": self.is_admin_login(info.get("login", ""))}
        return info

    def destroy_session(self, token: str | None) -> None:
        if not token:
            return
        with self._lock:
            if self._sessions.pop(token, None) is not None:
                self._persist_sessions()


auth_store = AuthStore()
