"""
Budget provisioning against the real GitHub Billing Budgets API.

This is what turns an approved budget request into an actual per-user Copilot
AI-credit budget on GitHub (`budget_scope: "user"`), instead of a number that
only lives inside OctoFinance.

It also reads back the budgets that apply to a given user so the personal
dashboard can show real numbers:

- the user's individual budget (`user` scope) with its live `consumed_amount`
- the universal fallback budget (`multi_user_customer` scope) when the user has
  no individual budget
- every cost center the user belongs to, plus that cost center's budget
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from .api_manager import api_manager
from .data_collector import data_collector

logger = logging.getLogger(__name__)

SCOPE_USER = "user"
SCOPE_UNIVERSAL = "multi_user_customer"
SCOPE_COST_CENTER = "cost_center"

AI_CREDITS_SKU = "ai_credits"
BUDGET_TYPE = "BundlePricing"


def _f(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def current_month_range() -> tuple[str, str]:
    """First and last day of the current UTC month as ``YYYY-MM-DD`` strings.

    Copilot budgets reset per billing cycle, so this is the window that matters
    when answering "how much of my budget is left this month?".
    """
    today = datetime.now(timezone.utc).date()
    start = today.replace(day=1)
    next_month = (
        start.replace(year=start.year + 1, month=1)
        if start.month == 12
        else start.replace(month=start.month + 1)
    )
    return start.isoformat(), (next_month - timedelta(days=1)).isoformat()


# ---------------------------------------------------------------------------
# Entity resolution
# ---------------------------------------------------------------------------

def list_billing_entities() -> list[dict]:
    """All entities that can hold Copilot budgets, enterprises first.

    Enterprise-level budgets cover every org underneath, so they are preferred
    when provisioning a user budget.
    """
    entities: list[dict] = [
        {"entity_type": "enterprise", "entity_name": e["slug"], "label": e.get("name") or e["slug"]}
        for e in api_manager.get_all_enterprises()
    ]
    entities += [
        {"entity_type": "organization", "entity_name": o["login"], "label": o["login"]}
        for o in api_manager.get_all_orgs()
    ]
    return entities


def _user_orgs(login: str) -> list[str]:
    """Orgs where the user currently holds a Copilot seat."""
    target = login.lower()
    orgs: list[str] = []
    seats_dir = data_collector.data_dir / "seats"
    if not seats_dir.exists():
        return orgs
    for path in sorted(seats_dir.glob("*_latest.json")):
        org = path.name[: -len("_latest.json")]
        data = data_collector.load_latest("seats", org)
        if not data:
            continue
        for seat in data.get("seats", []):
            assignee = seat.get("assignee") or {}
            if str(assignee.get("login", "")).lower() == target:
                orgs.append(org)
                break
    return orgs


def resolve_entity_for_user(login: str, preferred_org: str = "") -> dict | None:
    """Pick the entity whose budgets should hold this user's personal budget.

    Copilot AI-credit budgets are administered at the **enterprise** level
    whenever an enterprise exists, so enterprises always win. Organization-level
    budgets are only used when no enterprise is configured at all (many orgs
    reject `/organizations/{org}/settings/billing/budgets` with a 400).

    Order of preference:
      1. The enterprise sharing a PAT with ``preferred_org`` / the user's orgs.
      2. The first discovered enterprise.
      3. An organization, as a last resort.
    """
    enterprises = api_manager.get_all_enterprises()
    all_orgs = {o["login"]: o for o in api_manager.get_all_orgs()}

    def _enterprise_of(org_name: str) -> dict | None:
        info = all_orgs.get(org_name) or {}
        # Orgs and enterprises discovered through the same PAT belong together;
        # the org's `enterprise` label is often just "Independent"/"Unknown".
        pat_id = info.get("pat_id")
        ent_label = info.get("enterprise")
        for e in enterprises:
            if ent_label and ent_label not in ("Independent", "Unknown") and (
                e["slug"] == ent_label or e.get("name") == ent_label
            ):
                return {"entity_type": "enterprise", "entity_name": e["slug"]}
        if pat_id:
            for e in enterprises:
                if e.get("pat_id") == pat_id:
                    return {"entity_type": "enterprise", "entity_name": e["slug"]}
        return None

    candidates: list[str] = []
    if preferred_org.strip():
        candidates.append(preferred_org.strip())
    candidates += _user_orgs(login)

    for org in candidates:
        ent = _enterprise_of(org)
        if ent:
            return ent

    if enterprises:
        return {"entity_type": "enterprise", "entity_name": enterprises[0]["slug"]}

    for org in candidates:
        if org in all_orgs:
            return {"entity_type": "organization", "entity_name": org}
    if all_orgs:
        return {"entity_type": "organization", "entity_name": next(iter(all_orgs))}
    return None


def _get_api(entity_type: str, entity_name: str):
    if entity_type == "enterprise":
        return api_manager.get_api_for_enterprise(entity_name)
    return api_manager.get_api_for_org(entity_name)


# ---------------------------------------------------------------------------
# Reading budgets
# ---------------------------------------------------------------------------

async def fetch_budgets(entity_type: str, entity_name: str, scope: str = "") -> list[dict]:
    """Live-fetch budgets for an entity. Returns [] when unavailable."""
    api = _get_api(entity_type, entity_name)
    if api is None:
        return []
    try:
        return await api.get_all_budgets_paginated(
            entity_type=entity_type, entity_name=entity_name, scope=scope
        )
    except Exception as exc:  # noqa: BLE001 - never break the dashboard on API errors
        logger.warning("[budget] Live budget fetch failed for %s/%s: %s", entity_type, entity_name, exc)
        return []


def cached_budgets(entity_name: str) -> list[dict]:
    """Budgets from the last sync (data/budgets/{slug}_latest.json)."""
    data = data_collector.load_latest("budgets", entity_name)
    if not data:
        return []
    return data.get("budgets", []) or []


def _normalize(budget: dict, entity_type: str, entity_name: str) -> dict:
    skus = budget.get("budget_product_skus")
    if not skus:
        single = budget.get("budget_product_sku")
        skus = [single] if single else []
    alerting = budget.get("budget_alerting") or {}
    amount = _f(budget.get("budget_amount"))
    consumed_raw = budget.get("consumed_amount")
    consumed = _f(consumed_raw) if consumed_raw is not None else None
    return {
        "id": budget.get("id", ""),
        "scope": budget.get("budget_scope", ""),
        "entity_type": entity_type,
        "entity_name": entity_name,
        "target_name": budget.get("budget_entity_name", "") or "",
        "skus": [s for s in skus if s],
        "amount": amount,
        "consumed_amount": consumed,
        "remaining_amount": round(amount - consumed, 4) if consumed is not None else None,
        "usage_pct": round(consumed / amount * 100, 1) if consumed is not None and amount > 0 else None,
        "prevent_further_usage": bool(budget.get("prevent_further_usage", False)),
        "will_alert": bool(alerting.get("will_alert", False)),
    }


def user_cost_centers(login: str) -> list[dict]:
    """Every enterprise cost center the given user is a member of."""
    target = login.lower()
    results: list[dict] = []
    cc_dir = data_collector.data_dir / "cost_centers"
    if not cc_dir.exists():
        return results

    for path in sorted(cc_dir.glob("*_latest.json")):
        slug = path.name[: -len("_latest.json")]
        data = data_collector.load_latest("cost_centers", slug)
        if not data:
            continue
        for cc in data.get("cost_centers", []):
            if str(cc.get("state", "active")).lower() not in ("active", ""):
                continue
            member = next(
                (m for m in cc.get("members", []) if str(m.get("login", "")).lower() == target),
                None,
            )
            if member is None:
                continue
            results.append({
                "id": cc.get("id", ""),
                "name": cc.get("name", ""),
                "enterprise": slug,
                "enterprise_name": data.get("enterprise_name", slug),
                "state": cc.get("state", ""),
                "ai_credit_pool_enabled": bool(cc.get("ai_credit_pool_enabled", False)),
                "member_count": cc.get("member_count", len(cc.get("members", []) or [])),
                "membership_source": member.get("source_type", ""),
                "membership_source_name": member.get("source_name", ""),
                "resources": cc.get("resources", []) or [],
                "budget": None,
            })
    return results


def _match_cost_center_budget(budgets: list[dict], cc: dict) -> dict | None:
    """Cost center budgets reference the cost center by name or by id."""
    name = (cc.get("name") or "").lower()
    cc_id = (cc.get("id") or "").lower()
    for b in budgets:
        if b.get("budget_scope") != SCOPE_COST_CENTER:
            continue
        target = str(b.get("budget_entity_name", "")).lower()
        if target and target in (name, cc_id):
            return b
    return None


async def get_user_budget_context(login: str, live: bool = False) -> dict:
    """Everything budget-related that applies to one user.

    Returns the individual budget, the universal fallback, and each cost center
    the user belongs to together with that cost center's budget.
    """
    target = login.lower()
    cost_centers = user_cost_centers(login)

    # Which entities do we need budgets from?
    entities: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for cc in cost_centers:
        key = ("enterprise", cc["enterprise"])
        if key not in seen:
            seen.add(key)
            entities.append({"entity_type": "enterprise", "entity_name": cc["enterprise"]})
    primary = resolve_entity_for_user(login)
    if primary and (primary["entity_type"], primary["entity_name"]) not in seen:
        seen.add((primary["entity_type"], primary["entity_name"]))
        entities.append(primary)

    per_entity: dict[str, list[dict]] = {}
    for ent in entities:
        raw = (
            await fetch_budgets(ent["entity_type"], ent["entity_name"])
            if live
            else cached_budgets(ent["entity_name"])
        )
        if live and not raw:
            raw = cached_budgets(ent["entity_name"])
        per_entity[ent["entity_name"]] = raw

    personal: dict | None = None
    universal: dict | None = None
    for ent in entities:
        for b in per_entity.get(ent["entity_name"], []):
            scope = b.get("budget_scope")
            if scope == SCOPE_USER:
                owner = str(b.get("user") or b.get("budget_entity_name") or "").lower()
                if owner == target and personal is None:
                    personal = _normalize(b, ent["entity_type"], ent["entity_name"])
            elif scope == SCOPE_UNIVERSAL and universal is None:
                universal = _normalize(b, ent["entity_type"], ent["entity_name"])

    for cc in cost_centers:
        match = _match_cost_center_budget(per_entity.get(cc["enterprise"], []), cc)
        if match:
            cc["budget"] = _normalize(match, "enterprise", cc["enterprise"])

    # The effective limit is the individual budget when present, else universal
    effective = personal or universal
    return {
        "live": live,
        "personal_budget": personal,
        "universal_budget": universal,
        "effective_budget": effective,
        "effective_source": "personal" if personal else ("universal" if universal else None),
        "cost_centers": cost_centers,
        "entities": entities,
    }


# ---------------------------------------------------------------------------
# Writing budgets (approval provisioning)
# ---------------------------------------------------------------------------

async def provision_user_budget(
    login: str,
    amount: float,
    *,
    preferred_org: str = "",
    prevent_further_usage: bool = True,
    enable_alerts: bool = False,
) -> dict:
    """Create or update the real GitHub `user`-scope AI-credit budget.

    Returns a result dict describing what happened, always safe to persist:
    ``{"status": "created"|"updated"|"failed"|"skipped", ...}``.
    """
    entity = resolve_entity_for_user(login, preferred_org=preferred_org)
    if entity is None:
        return {
            "status": "failed",
            "error": "No GitHub enterprise or organization is configured, so no budget could be created.",
            "synced_at": _now(),
        }

    entity_type = entity["entity_type"]
    entity_name = entity["entity_name"]
    api = _get_api(entity_type, entity_name)
    if api is None:
        return {
            "status": "failed",
            "entity_type": entity_type,
            "entity_name": entity_name,
            "error": f"No PAT with access to {entity_type} '{entity_name}'.",
            "synced_at": _now(),
        }

    # Does this user already have an individual budget here?
    existing_id = ""
    try:
        for b in await api.get_all_budgets_paginated(
            entity_type=entity_type, entity_name=entity_name, scope=SCOPE_USER
        ):
            owner = str(b.get("user") or b.get("budget_entity_name") or "").lower()
            if owner == login.lower():
                existing_id = b.get("id", "")
                break
    except Exception as exc:  # noqa: BLE001
        logger.warning("[budget] Could not list existing budgets: %s", exc)

    amount = round(float(amount), 2)

    if existing_id:
        result = await api.update_budget(
            entity_type=entity_type,
            entity_name=entity_name,
            budget_id=existing_id,
            budget_data={
                "budget_amount": amount,
                "prevent_further_usage": prevent_further_usage,
            },
        )
        if result and "error" in result:
            return {
                "status": "failed", "entity_type": entity_type, "entity_name": entity_name,
                "budget_id": existing_id, "amount": amount,
                "error": _error_text(result), "synced_at": _now(),
            }
        logger.info("[budget] Updated GitHub budget %s for %s -> $%s", existing_id, login, amount)
        return {
            "status": "updated", "entity_type": entity_type, "entity_name": entity_name,
            "budget_id": existing_id, "amount": amount, "scope": SCOPE_USER,
            "synced_at": _now(),
        }

    budget_data = {
        "budget_type": BUDGET_TYPE,
        "budget_product_sku": AI_CREDITS_SKU,
        "budget_scope": SCOPE_USER,
        "budget_entity_name": login,
        "budget_amount": amount,
        "prevent_further_usage": prevent_further_usage,
        "user": login,
        "consumed_amount": 0,
        "budget_alerting": {
            "will_alert": enable_alerts,
            "alert_recipients": [login] if enable_alerts else [],
        },
    }
    result = await api.create_budget(
        entity_type=entity_type, entity_name=entity_name, budget_data=budget_data
    )
    if result and "error" in result:
        return {
            "status": "failed", "entity_type": entity_type, "entity_name": entity_name,
            "amount": amount, "error": _error_text(result), "synced_at": _now(),
        }

    budget_id = ""
    if isinstance(result, dict):
        budget_id = (result.get("budget") or {}).get("id") or result.get("id") or ""
    logger.info("[budget] Created GitHub budget %s for %s -> $%s", budget_id, login, amount)
    return {
        "status": "created", "entity_type": entity_type, "entity_name": entity_name,
        "budget_id": budget_id, "amount": amount, "scope": SCOPE_USER,
        "synced_at": _now(),
    }


def _error_text(result: dict) -> str:
    response = result.get("response") or {}
    message = response.get("message") if isinstance(response, dict) else None
    errors = response.get("errors") if isinstance(response, dict) else None
    parts = [str(message)] if message else []
    if isinstance(errors, list):
        parts += [str(e.get("message") or e) for e in errors]
    if not parts:
        parts = [str(result.get("error", "Unknown error"))]
    status = result.get("status_code")
    text = "; ".join(p for p in parts if p)
    return f"{text} (HTTP {status})" if status else text
