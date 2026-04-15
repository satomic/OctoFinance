"""
PAT Manager - handles persistence and CRUD for GitHub Personal Access Tokens.
PATs and app settings are stored in data/pats.json.
"""

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ..config import DATA_DIR


PATS_FILE = DATA_DIR / "pats.json"

DEFAULT_SETTINGS = {
    "auto_sync_on_startup": True,
    "sync_cron": "",
}


class PATManager:
    """Manages GitHub PAT persistence and app settings in data/pats.json."""

    def __init__(self):
        self._pats: list[dict] = []
        self._settings: dict = {**DEFAULT_SETTINGS}

    def load(self) -> list[dict]:
        """Load PATs and settings from file.

        Supports two formats:
        - Legacy: a plain JSON array of PATs
        - Current: ``{"pats": [...], "settings": {...}}``

        Auto-migrates legacy format on first load.
        """
        if PATS_FILE.exists():
            try:
                raw = json.loads(PATS_FILE.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                raw = []
        else:
            raw = []

        # Detect format and normalise
        if isinstance(raw, list):
            # Legacy format – plain array of PATs
            self._pats = raw
            self._settings = {**DEFAULT_SETTINGS}
            if raw:
                # Migrate to new format on disk
                self._save()
                print("[PATManager] Migrated pats.json from legacy array to {pats, settings} format")
        elif isinstance(raw, dict):
            self._pats = raw.get("pats", [])
            saved_settings = raw.get("settings", {})
            self._settings = {**DEFAULT_SETTINGS, **saved_settings}
        else:
            self._pats = []
            self._settings = {**DEFAULT_SETTINGS}

        # Auto-migrate GITHUB_PAT env var if no PATs configured
        env_pat = os.environ.get("GITHUB_PAT", "").strip()
        if not self._pats and env_pat:
            migrated = {
                "id": f"pat_{uuid.uuid4().hex[:8]}",
                "label": "Migrated from GITHUB_PAT env",
                "token": env_pat,
                "user_login": "",
                "user_avatar": "",
                "orgs": [],
                "created_at": datetime.now(timezone.utc).isoformat(),
                "last_synced_at": "",
            }
            self._pats.append(migrated)
            self._save()
            print(f"[PATManager] Auto-migrated GITHUB_PAT env var as PAT '{migrated['id']}'")

        return self._pats

    def _save(self):
        """Write PATs and settings to file."""
        PATS_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "pats": self._pats,
            "settings": self._settings,
        }
        PATS_FILE.write_text(
            json.dumps(data, indent=2, default=str),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def get_settings(self) -> dict:
        """Return a copy of the current settings."""
        return {**self._settings}

    def update_settings(self, **kwargs) -> dict:
        """Update settings and persist. Returns the updated settings."""
        for key in DEFAULT_SETTINGS:
            if key in kwargs:
                self._settings[key] = kwargs[key]
        self._save()
        return {**self._settings}

    def get_all(self) -> list[dict]:
        """Return all PATs (raw, with tokens)."""
        return list(self._pats)

    def get_all_masked(self) -> list[dict]:
        """Return all PATs with tokens masked for API responses."""
        result = []
        for p in self._pats:
            masked = {**p}
            token = masked.get("token", "")
            if len(token) > 8:
                masked["token_masked"] = token[:4] + "***" + token[-4:]
            else:
                masked["token_masked"] = "***"
            del masked["token"]
            result.append(masked)
        return result

    def get_token(self, pat_id: str) -> str | None:
        """Get the raw token for a PAT ID."""
        for p in self._pats:
            if p["id"] == pat_id:
                return p["token"]
        return None

    def add(self, label: str, token: str, enterprise_slugs: list[str] | None = None) -> dict:
        """Add a new PAT entry. Returns the new PAT dict (with token)."""
        # Check for duplicate tokens
        for p in self._pats:
            if p["token"] == token:
                raise ValueError(f"This token is already configured as '{p['label']}'")

        pat = {
            "id": f"pat_{uuid.uuid4().hex[:8]}",
            "label": label or "Untitled",
            "token": token,
            "user_login": "",
            "user_avatar": "",
            "orgs": [],
            "enterprise_slugs": enterprise_slugs or [],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_synced_at": "",
        }
        self._pats.append(pat)
        self._save()
        return pat

    def update(self, pat_id: str, **kwargs) -> dict | None:
        """Update a PAT's metadata (label, user_login, orgs, etc.)."""
        for p in self._pats:
            if p["id"] == pat_id:
                for key, value in kwargs.items():
                    if key != "id" and key != "token":
                        p[key] = value
                self._save()
                return p
        return None

    def remove(self, pat_id: str) -> bool:
        """Remove a PAT by ID. Returns True if found and removed."""
        before = len(self._pats)
        self._pats = [p for p in self._pats if p["id"] != pat_id]
        if len(self._pats) < before:
            self._save()
            return True
        return False

    def find_by_id(self, pat_id: str) -> dict | None:
        """Find a PAT by ID."""
        for p in self._pats:
            if p["id"] == pat_id:
                return p
        return None


# Global instance
pat_manager = PATManager()
