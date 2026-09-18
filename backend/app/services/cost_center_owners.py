"""Local cost center ownership, independent of synced GitHub data."""

import fcntl
import json
import os
import tempfile
from datetime import datetime, timezone

from ..config import DATA_DIR
from .data_collector import data_collector

OWNERS_FILE = DATA_DIR / "cc_owners.json"


def load_owners() -> dict:
    if not OWNERS_FILE.exists():
        return {}
    with OWNERS_FILE.open(encoding="utf-8") as stream:
        return json.load(stream)


def owner_logins(enterprise: str, cost_center_id: str) -> list[str]:
    return sorted(load_owners().get(enterprise, {}).get(cost_center_id, {}))


def set_owner(enterprise: str, cost_center_id: str, login: str, enabled: bool, actor: str) -> None:
    OWNERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with OWNERS_FILE.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        owners = load_owners()
        members = owners.setdefault(enterprise, {}).setdefault(cost_center_id, {})
        if enabled:
            members[login.lower()] = {
                "granted_by": actor,
                "granted_at": datetime.now(timezone.utc).isoformat(),
            }
        else:
            members.pop(login.lower(), None)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=OWNERS_FILE.parent, delete=False) as stream:
            temporary_path = stream.name
            json.dump(owners, stream, indent=2)
        try:
            os.replace(temporary_path, OWNERS_FILE)
        finally:
            if os.path.exists(temporary_path):
                os.unlink(temporary_path)


def owned_cost_centers(login: str) -> list[dict]:
    result = []
    for enterprise, centers in load_owners().items():
        snapshot = data_collector.load_latest("cost_centers", enterprise) or {}
        for center in snapshot.get("cost_centers", []):
            if center.get("state", "active") != "active":
                continue
            if login.lower() not in centers.get(str(center.get("id", "")), {}):
                continue
            if not any(member.get("login", "").lower() == login.lower() for member in center.get("members", [])):
                continue
            result.append({"enterprise": enterprise, "id": str(center["id"]), "name": center["name"]})
    return sorted(result, key=lambda center: (center["enterprise"], center["name"].lower()))