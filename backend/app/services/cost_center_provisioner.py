"""
Cost center membership provisioning.

Regular users can request to be assigned to an enterprise cost center; when an
administrator approves, this module applies the change against the real GitHub
Billing Cost Centers API.

Two GitHub behaviours shape this module:

1. **A user belongs to at most one cost center.** Adding a user to a cost
   center moves them out of whichever one they were in before — GitHub reports
   this in the ``reassigned_resources`` field of the add response. The request
   is therefore a single choice, not a multi-select.
2. **Inherited membership cannot be changed per user.** A user who lands in a
   cost center because their whole organization or team is a resource of it is
   reported as read-only; only a direct ``User`` resource can be moved.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from .api_manager import api_manager
from .data_collector import data_collector

logger = logging.getLogger(__name__)

SOURCE_USER = "User"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _enterprise_slugs() -> list[str]:
    """Enterprises we have synced cost center data for."""
    slugs: list[str] = [e["slug"] for e in api_manager.get_all_enterprises()]
    cc_dir = data_collector.data_dir / "cost_centers"
    if cc_dir.exists():
        for path in cc_dir.glob("*_latest.json"):
            slug = path.name[: -len("_latest.json")]
            if slug not in slugs:
                slugs.append(slug)
    return slugs


def list_cost_centers_for_user(login: str) -> dict:
    """Every selectable cost center, flagged with this user's membership.

    Returns ``{"enterprises": [...], "cost_centers": [...]}`` where each cost
    center carries:

    - ``is_member``    — the user currently appears in it (any source)
    - ``is_direct``    — membership comes from a `User` resource, so it is editable
    - ``locked``       — membership is inherited (Org/Team) and cannot be changed
    - ``source``/``source_name`` — how the membership was granted
    """
    target = login.lower()
    cost_centers: list[dict] = []
    enterprises: list[dict] = []

    for slug in _enterprise_slugs():
        data = data_collector.load_latest("cost_centers", slug)
        if not data:
            continue
        enterprises.append({"slug": slug, "name": data.get("enterprise_name", slug)})

        for cc in data.get("cost_centers", []):
            if str(cc.get("state", "active")).lower() not in ("active", ""):
                continue

            member = next(
                (m for m in cc.get("members", []) if str(m.get("login", "")).lower() == target),
                None,
            )
            direct = any(
                r.get("type") == SOURCE_USER and str(r.get("name", "")).lower() == target
                for r in cc.get("resources", []) or []
            )
            source = (member or {}).get("source_type", "")
            cost_centers.append({
                "id": cc.get("id", ""),
                "name": cc.get("name", ""),
                "enterprise": slug,
                "enterprise_name": data.get("enterprise_name", slug),
                "state": cc.get("state", ""),
                "ai_credit_pool_enabled": bool(cc.get("ai_credit_pool_enabled", False)),
                "member_count": cc.get("member_count", len(cc.get("members", []) or [])),
                "is_member": member is not None,
                "is_direct": direct,
                # Inherited membership can't be revoked for a single user
                "locked": member is not None and not direct,
                "source": source,
                "source_name": (member or {}).get("source_name", ""),
            })

    cost_centers.sort(key=lambda c: (c["enterprise"], c["name"].lower()))
    return {"enterprises": enterprises, "cost_centers": cost_centers}


def current_assignment(login: str) -> dict | None:
    """The cost center the user is directly assigned to, if any."""
    for c in list_cost_centers_for_user(login)["cost_centers"]:
        if c["is_direct"]:
            return c
    return None


def diff_membership(login: str, target_id: str) -> dict:
    """Work out the move implied by choosing ``target_id``.

    ``target_id`` is a single cost center id, or ``""`` to be unassigned.
    Inherited (org/team) memberships are never touched.
    """
    snapshot = list_cost_centers_for_user(login)
    by_id = {c["id"]: c for c in snapshot["cost_centers"]}
    current = next((c for c in snapshot["cost_centers"] if c["is_direct"]), None)
    target = by_id.get(target_id) if target_id else None

    if target_id and target is None:
        return {"add": [], "remove": [], "current": current, "target": None,
                "invalid": True, "all": snapshot["cost_centers"]}

    same = current is not None and target is not None and current["id"] == target["id"]
    return {
        # GitHub moves the user automatically, so an explicit remove is only
        # needed when the user is leaving without joining another cost center.
        "add": [] if same or target is None else [target],
        "remove": [] if same or target is not None or current is None else [current],
        "current": current,
        "target": target,
        "invalid": False,
        "all": snapshot["cost_centers"],
    }


async def apply_membership_change(login: str, target_id: str) -> dict:
    """Apply an approved cost center assignment to GitHub.

    Returns a result dict that is always safe to persist:
    ``{"status": "applied"|"failed"|"noop", "added": [...], "removed": [...], ...}``
    """
    plan = diff_membership(login, target_id)
    if plan.get("invalid"):
        return {
            "status": "failed", "added": [], "removed": [],
            "errors": [{"error": f"Cost center '{target_id}' not found."}],
            "error": f"Cost center '{target_id}' not found.",
            "synced_at": _now(),
        }

    to_add, to_remove = plan["add"], plan["remove"]
    if not to_add and not to_remove:
        return {
            "status": "noop", "added": [], "removed": [], "errors": [],
            "message": "Assignment already matches the request.",
            "synced_at": _now(),
        }

    added: list[dict] = []
    removed: list[dict] = []
    reassigned: list[dict] = []
    errors: list[dict] = []

    def _entry(cc: dict) -> dict:
        return {"id": cc["id"], "name": cc["name"], "enterprise": cc["enterprise"]}

    for cc in to_add:
        api = api_manager.get_api_for_enterprise(cc["enterprise"])
        if api is None:
            errors.append({"cost_center": cc["name"], "id": cc["id"], "action": "add",
                           "error": f"No PAT with access to enterprise '{cc['enterprise']}'."})
            continue
        try:
            resp = await api.add_cost_center_resources(
                enterprise=cc["enterprise"], cost_center_id=cc["id"], users=[login]
            )
            added.append(_entry(cc))
            # GitHub reports which cost center the user was moved out of
            for r in (resp or {}).get("reassigned_resources", []) or []:
                reassigned.append(r if isinstance(r, dict) else {"resource": r})
            logger.info("[cost-center] Assigned %s to %s", login, cc["name"])
        except Exception as exc:  # noqa: BLE001
            errors.append({"cost_center": cc["name"], "id": cc["id"], "action": "add", "error": str(exc)})
            logger.warning("[cost-center] Assign %s to %s failed: %s", login, cc["name"], exc)

    for cc in to_remove:
        api = api_manager.get_api_for_enterprise(cc["enterprise"])
        if api is None:
            errors.append({"cost_center": cc["name"], "id": cc["id"], "action": "remove",
                           "error": f"No PAT with access to enterprise '{cc['enterprise']}'."})
            continue
        try:
            await api.remove_cost_center_resources(
                enterprise=cc["enterprise"], cost_center_id=cc["id"], users=[login]
            )
            removed.append(_entry(cc))
            logger.info("[cost-center] Unassigned %s from %s", login, cc["name"])
        except Exception as exc:  # noqa: BLE001
            errors.append({"cost_center": cc["name"], "id": cc["id"], "action": "remove", "error": str(exc)})
            logger.warning("[cost-center] Unassign %s from %s failed: %s", login, cc["name"], exc)

    # The previous assignment is implicitly dropped by GitHub when moving
    previous = plan["current"]
    if added and previous and previous["id"] != added[0]["id"]:
        removed.append(_entry(previous))

    if errors and not (added or removed):
        status = "failed"
    elif errors:
        status = "partial"
    else:
        status = "applied"

    return {
        "status": status,
        "added": added,
        "removed": removed,
        "reassigned": reassigned,
        "errors": errors,
        "error": "; ".join(f"{e.get('cost_center', '?')}: {e['error']}" for e in errors) or None,
        "synced_at": _now(),
    }
