"""
Session Manager - Persistent session storage for chat conversations.
Manages session folders under data/sessions/ with JSONL message logs.
"""

import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data"
SESSIONS_DIR = DATA_DIR / "sessions"
INDEX_FILE = SESSIONS_DIR / "index.json"


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

    def create_session(self, session_id: str | None = None, title: str = "New Session") -> dict:
        """Create a new session folder and register it in the index."""
        if session_id is None:
            session_id = self.generate_session_id()

        session_dir = SESSIONS_DIR / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now(timezone.utc).isoformat()
        metadata = {
            "session_id": session_id,
            "title": title,
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
        self._update_index_entry(
            session_id,
            message_count=len(messages),
            updated_at=now,
        )
        # Also update metadata.json
        meta_path = session_dir / "metadata.json"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                meta["message_count"] = len(messages)
                meta["updated_at"] = now
                meta_path.write_text(
                    json.dumps(meta, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception:
                pass

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
        """Update a session's title."""
        session_dir = SESSIONS_DIR / session_id
        meta_path = session_dir / "metadata.json"
        if not meta_path.exists():
            return None

        now = datetime.now(timezone.utc).isoformat()
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["title"] = title
        meta["updated_at"] = now
        meta_path.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        self._update_index_entry(session_id, title=title, updated_at=now)
        return meta

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
