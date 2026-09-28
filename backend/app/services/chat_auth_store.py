"""
Credentials for the AI chat engine (Copilot CLI), managed from Settings.

Kept apart from the data-sync PATs (``pats.json``): chat needs a fine-grained
token of a user with a Copilot seat, while data sync usually runs on an
admin's classic PAT. Stored in ``data/copilot_chat.json`` and never returned
to the browser unmasked.
"""

from __future__ import annotations

import json
import threading

from ..config import DATA_DIR
from .github_host import normalize_host

CHAT_AUTH_FILE = DATA_DIR / "copilot_chat.json"


def mask_token(token: str) -> str:
    return f"{token[:4]}***{token[-4:]}" if len(token) > 8 else "***"


class ChatAuthStore:
    def __init__(self):
        self._lock = threading.Lock()

    def get(self) -> dict:
        """``{"token": str, "host": str}``; empty host means "detect automatically"."""
        try:
            raw = json.loads(CHAT_AUTH_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        return {"token": str(raw.get("token") or ""), "host": str(raw.get("host") or "")}

    def save(self, *, token: str | None = None, host: str | None = None, clear_token: bool = False) -> dict:
        """Update the stored values. ``None`` keeps a field; raises ValueError for a bad host."""
        with self._lock:
            cfg = self.get()
            if clear_token:
                cfg["token"] = ""
            elif token is not None and token.strip():
                cfg["token"] = token.strip()
            if host is not None:
                cfg["host"] = normalize_host(host) if host.strip() else ""
            CHAT_AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
            CHAT_AUTH_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
            return cfg


chat_auth_store = ChatAuthStore()
