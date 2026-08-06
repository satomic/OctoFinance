"""
Session Manager - Persistent session storage for chat conversations.
Manages session folders under data/sessions/ with JSONL message logs.
"""

import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data"
SESSIONS_DIR = DATA_DIR / "sessions"
INDEX_FILE = SESSIONS_DIR / "index.json"

# Placeholder used until the first user message gives the session a real name
DEFAULT_SESSION_TITLE = "New Session"
TITLE_MAX_LEN = 48


def derive_title(text: str) -> str:
    """Turn the first user message into a short, readable session title.

    Strips code fences and markdown noise, collapses whitespace, and truncates
    on a word boundary so the sidebar shows a meaningful preview instead of the
    generic placeholder.
    """
    if not text:
        return DEFAULT_SESSION_TITLE

    cleaned = re.sub(r"```.*?```", " ", text, flags=re.S)      # fenced code blocks
    cleaned = re.sub(r"`([^`]*)`", r"\1", cleaned)             # inline code
    cleaned = re.sub(r"^\s*[#>*\-+]+\s*", "", cleaned, flags=re.M)  # md bullets/headings
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    if not cleaned:
        return DEFAULT_SESSION_TITLE
    if len(cleaned) <= TITLE_MAX_LEN:
        return cleaned

    clipped = cleaned[:TITLE_MAX_LEN]
    # Prefer breaking at a space, but only if it keeps most of the text
    # (CJK has no spaces, so fall back to a hard cut).
    space = clipped.rfind(" ")
    if space > TITLE_MAX_LEN * 0.6:
        clipped = clipped[:space]
    return clipped.rstrip() + "..."


class SessionManager:
    """Manages persistent chat sessions stored as file folders."""

    def __init__(self):
        self._ensure_dirs()

    def _ensure_dirs(self):
        """Ensure the sessions directory and index file exist."""
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        if not INDEX_FILE.exists():
            INDEX_FILE.write_text("[]", encoding="utf-8")

    @staticmethod
    def generate_session_id() -> str:
        return uuid.uuid4().hex[:8]

    def _read_index(self) -> list[dict]:
        try:
            return json.loads(INDEX_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError):
            return []

    def _write_index(self, index: list[dict]):
        INDEX_FILE.write_text(
            json.dumps(index, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _update_index_entry(self, session_id: str, **updates):
        """Update a single entry in the index."""
        index = self._read_index()
        for entry in index:
            if entry["session_id"] == session_id:
                entry.update(updates)
                break
        self._write_index(index)

    def create_session(self, session_id: str | None = None, title: str = DEFAULT_SESSION_TITLE) -> dict:
        """Create a new session folder and register it in the index.

        A blank or placeholder title marks the session as *auto-nameable*: the
        first user message will replace it. An explicit title (e.g. one created
        for an approved action) is kept as-is.
        """
        if session_id is None:
            session_id = self.generate_session_id()

        session_dir = SESSIONS_DIR / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        title = (title or "").strip()
        auto_title = not title or title == DEFAULT_SESSION_TITLE
        if not title:
            title = DEFAULT_SESSION_TITLE

        now = datetime.now(timezone.utc).isoformat()
        metadata = {
            "session_id": session_id,
            "title": title,
            "auto_title": auto_title,
            "created_at": now,
            "updated_at": now,
            "message_count": 0,
        }
        (session_dir / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # Append to index
        index = self._read_index()
        # Avoid duplicates
        if not any(e["session_id"] == session_id for e in index):
            index.insert(0, metadata)
            self._write_index(index)

        return metadata

    def list_sessions(self) -> list[dict]:
        """List all sessions, sorted by updated_at descending."""
        index = self._read_index()
        index.sort(key=lambda e: e.get("updated_at", ""), reverse=True)
        return index

    def get_session(self, session_id: str) -> dict | None:
        """Get a single session's metadata."""
        index = self._read_index()
        for entry in index:
            if entry["session_id"] == session_id:
                return entry
        return None

    def session_exists(self, session_id: str) -> bool:
        return (SESSIONS_DIR / session_id / "metadata.json").exists()

    def append_message(self, session_id: str, message: dict):
        """Append a message to the session's messages.jsonl."""
        session_dir = SESSIONS_DIR / session_id
        if not session_dir.exists():
            return

        with open(session_dir / "messages.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(message, ensure_ascii=False) + "\n")

        # Update message count and timestamp in index
        messages = self.load_messages(session_id)
        now = datetime.now(timezone.utc).isoformat()
        updates: dict[str, Any] = {"message_count": len(messages), "updated_at": now}

        # Give the session a real name from its first user message. Sessions
        # created via the sidebar "+" button start as "New Session" and would
        # otherwise keep that placeholder forever.
        if message.get("role") == "user" and self._is_auto_titled(session_id):
            title = derive_title(message.get("content", ""))
            if title != DEFAULT_SESSION_TITLE:
                updates["title"] = title
                updates["auto_title"] = False

        self._update_index_entry(session_id, **updates)

        # Also update metadata.json
        meta_path = session_dir / "metadata.json"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                meta.update(updates)
                meta_path.write_text(
                    json.dumps(meta, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception:
                pass

    def _is_auto_titled(self, session_id: str) -> bool:
        """True when the session still carries a placeholder title.

        Falls back to comparing against the placeholder so sessions created
        before `auto_title` existed are still picked up.
        """
        entry = self.get_session(session_id) or {}
        if "auto_title" in entry:
            return bool(entry["auto_title"])
        return (entry.get("title") or "").strip() in ("", DEFAULT_SESSION_TITLE)

    def append_tool_call(self, session_id: str, tool_call: dict):
        """Append a tool call record to the session's tool_calls.jsonl."""
        session_dir = SESSIONS_DIR / session_id
        if not session_dir.exists():
            return

        with open(session_dir / "tool_calls.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(tool_call, ensure_ascii=False) + "\n")

    def load_messages(self, session_id: str) -> list[dict]:
        """Load all messages from a session's messages.jsonl."""
        msg_file = SESSIONS_DIR / session_id / "messages.jsonl"
        if not msg_file.exists():
            return []

        messages = []
        with open(msg_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        messages.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return messages

    def update_session_title(self, session_id: str, title: str) -> dict | None:
        """Rename a session. A manual rename is never overwritten afterwards."""
        session_dir = SESSIONS_DIR / session_id
        meta_path = session_dir / "metadata.json"
        if not meta_path.exists():
            return None

        now = datetime.now(timezone.utc).isoformat()
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["title"] = title
        meta["auto_title"] = False
        meta["updated_at"] = now
        meta_path.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        self._update_index_entry(session_id, title=title, auto_title=False, updated_at=now)
        return meta

    def backfill_titles(self) -> int:
        """Name any existing session still stuck on the placeholder title.

        Older sessions were only titled when `/chat` auto-created them, so ones
        started from the sidebar "+" button kept "New Session" forever. Returns
        the number of sessions renamed.
        """
        renamed = 0
        for entry in self._read_index():
            session_id = entry.get("session_id", "")
            if not session_id or not self._is_auto_titled(session_id):
                continue

            first_user = next(
                (m for m in self.load_messages(session_id) if m.get("role") == "user"), None
            )
            if not first_user:
                continue
            title = derive_title(first_user.get("content", ""))
            if title == DEFAULT_SESSION_TITLE:
                continue

            self._update_index_entry(session_id, title=title, auto_title=False)
            meta_path = SESSIONS_DIR / session_id / "metadata.json"
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    meta["title"] = title
                    meta["auto_title"] = False
                    meta_path.write_text(
                        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                except Exception:
                    pass
            renamed += 1
        return renamed

    def delete_session(self, session_id: str) -> bool:
        """Delete a session folder and remove from index."""
        session_dir = SESSIONS_DIR / session_id
        if session_dir.exists():
            shutil.rmtree(session_dir)

        index = self._read_index()
        index = [e for e in index if e["session_id"] != session_id]
        self._write_index(index)
        return True


# Global instance
session_manager = SessionManager()
