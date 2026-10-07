"""Saved AI chat prompts, so admins can reuse their routine analysis questions.

Each prompt belongs to the admin who saved it. A shared prompt is also visible
(read-only) to every other admin.
"""

import fcntl
import json
import os
import tempfile
import uuid
from datetime import datetime, timezone

from ..config import DATA_DIR

PROMPTS_FILE = DATA_DIR / "saved_prompts.json"

MAX_TITLE_LENGTH = 80
MAX_PROMPT_LENGTH = 8000


class PromptNotFound(Exception):
    pass


class PromptForbidden(Exception):
    pass


def _load() -> list[dict]:
    if not PROMPTS_FILE.exists():
        return []
    with PROMPTS_FILE.open(encoding="utf-8") as stream:
        return json.load(stream).get("prompts", [])


def _save(prompts: list[dict]) -> None:
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=PROMPTS_FILE.parent, delete=False) as stream:
        temporary_path = stream.name
        json.dump({"prompts": prompts}, stream, indent=2, ensure_ascii=False)
    try:
        os.replace(temporary_path, PROMPTS_FILE)
    finally:
        if os.path.exists(temporary_path):
            os.unlink(temporary_path)


def _locked(mutate):
    """Run ``mutate(prompts)`` under the file lock and persist the list it edits."""
    PROMPTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with PROMPTS_FILE.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        prompts = _load()
        result = mutate(prompts)
        _save(prompts)
        return result


def _clean(title: str, prompt: str) -> tuple[str, str]:
    title, prompt = title.strip(), prompt.strip()
    if not prompt:
        raise ValueError("Prompt text is required")
    if len(prompt) > MAX_PROMPT_LENGTH:
        raise ValueError(f"Prompt text must be at most {MAX_PROMPT_LENGTH} characters")
    if not title:
        title = " ".join(prompt.split())[:MAX_TITLE_LENGTH]
    if len(title) > MAX_TITLE_LENGTH:
        raise ValueError(f"Title must be at most {MAX_TITLE_LENGTH} characters")
    return title, prompt


def _view(entry: dict, login: str) -> dict:
    return {**entry, "is_owner": entry["owner"].lower() == login.lower()}


def list_prompts(login: str) -> list[dict]:
    """The admin's own prompts plus prompts other admins shared, most recently used first."""
    visible = [
        _view(entry, login)
        for entry in _load()
        if entry.get("shared") or entry["owner"].lower() == login.lower()
    ]
    return sorted(
        visible,
        key=lambda entry: (entry.get("last_used_at") or "", entry.get("updated_at") or ""),
        reverse=True,
    )


def create_prompt(login: str, title: str, prompt: str, shared: bool = False) -> dict:
    title, prompt = _clean(title, prompt)
    now = datetime.now(timezone.utc).isoformat()
    entry = {
        "id": uuid.uuid4().hex[:12],
        "title": title,
        "prompt": prompt,
        "owner": login,
        "shared": shared,
        "use_count": 0,
        "created_at": now,
        "updated_at": now,
        "last_used_at": None,
    }
    _locked(lambda prompts: prompts.append(entry))
    return _view(entry, login)


def _find(prompts: list[dict], prompt_id: str) -> dict:
    for entry in prompts:
        if entry["id"] == prompt_id:
            return entry
    raise PromptNotFound(prompt_id)


def _owned(prompts: list[dict], prompt_id: str, login: str) -> dict:
    entry = _find(prompts, prompt_id)
    if entry["owner"].lower() != login.lower():
        raise PromptForbidden(prompt_id)
    return entry


def update_prompt(
    login: str,
    prompt_id: str,
    title: str | None = None,
    prompt: str | None = None,
    shared: bool | None = None,
) -> dict:
    def mutate(prompts: list[dict]) -> dict:
        entry = _owned(prompts, prompt_id, login)
        new_title, new_prompt = _clean(
            entry["title"] if title is None else title,
            entry["prompt"] if prompt is None else prompt,
        )
        entry.update(title=new_title, prompt=new_prompt, updated_at=datetime.now(timezone.utc).isoformat())
        if shared is not None:
            entry["shared"] = shared
        return entry

    return _view(_locked(mutate), login)


def delete_prompt(login: str, prompt_id: str) -> None:
    def mutate(prompts: list[dict]) -> None:
        prompts.remove(_owned(prompts, prompt_id, login))

    _locked(mutate)


def mark_used(login: str, prompt_id: str) -> dict:
    """Bump usage stats; any admin who can see the prompt may use it."""
    def mutate(prompts: list[dict]) -> dict:
        entry = _find(prompts, prompt_id)
        if not entry.get("shared") and entry["owner"].lower() != login.lower():
            raise PromptNotFound(prompt_id)
        entry["use_count"] = entry.get("use_count", 0) + 1
        entry["last_used_at"] = datetime.now(timezone.utc).isoformat()
        return entry

    return _view(_locked(mutate), login)
