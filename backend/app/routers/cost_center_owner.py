"""Admin ownership assignment and authenticated, center-scoped owner views."""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from ..services.api_manager import api_manager
from ..services.budget_provisioner import AI_CREDITS_SKU, BUDGET_TYPE, SCOPE_USER, _normalize, cached_budgets
from ..services.cost_center_owners import load_owners, owned_cost_centers, owner_logins, set_owner
from ..services.csv_store import CSV_TYPE_AI, CSV_TYPE_USAGE, load_all_csv_records
from ..services.data_collector import data_collector
from ..services.report_generator import _build_ai_usage_section, _build_usage_section
from .auth import require_user
from .data import _append_audit_log
from .me import resolve_period

router = APIRouter(tags=["cost-center-owner"])


class OwnerAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enterprise: str
    cost_center_id: str
    login: str
    enabled: bool


class OwnerSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enterprise: str
    cost_center_id: str
    ai_credit_pool_enabled: bool


class OwnerUserBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enterprise: str
    cost_center_id: str
    login: str = Field(min_length=1)
    amount: float = Field(gt=0, multiple_of=0.01, allow_inf_nan=False)
    prevent_further_usage: bool = True


def individual_credit_budgets(budgets: list[dict], login: str) -> list[dict]:
    matches = []
    for budget in budgets:
        skus = budget.get("budget_product_skus") or [budget.get("budget_product_sku")]
        if (budget.get("budget_scope") == SCOPE_USER
                and budget.get("budget_type") == BUDGET_TYPE
                and set(skus) == {AI_CREDITS_SKU}
                and str(budget.get("user") or budget.get("budget_entity_name") or "").lower() == login.lower()):
            matches.append(budget)
    return matches


async def read_individual_budgets(enterprise: str) -> list[dict]:
    api = api_manager.get_api_for_enterprise(enterprise)
    if api is None:
        raise HTTPException(503, detail={"code": "budgets_unavailable"})
    try:
        return await api.get_all_budgets_paginated("enterprise", enterprise, scope=SCOPE_USER, strict=True)
    except Exception:
        raise HTTPException(502, detail={"code": "budgets_unavailable"}) from None


async def verify_budget_write(request: Request, enterprise: str, cost_center_id: str, login: str) -> dict:
    user = require_owner(request, enterprise, cost_center_id)
    center = get_center(enterprise, cost_center_id)
    if not any(member.get("login", "").lower() == login.lower() for member in center.get("members", [])):
        raise HTTPException(403, detail={"code": "budget_member_only"})
    try:
        latest = await live_center(enterprise, cost_center_id)
    except HTTPException:
        raise HTTPException(503, detail={"code": "cap_unknown"}) from None
    if latest.get("state") != "active":
        raise HTTPException(403, detail={"code": "budget_member_only"})
    if latest.get("ai_credit_pool_enabled") is not True:
        code = "cap_off" if latest.get("ai_credit_pool_enabled") is False else "cap_unknown"
        raise HTTPException(403, detail={"code": code})
    api = api_manager.get_api_for_enterprise(enterprise)
    if api is None:
        raise HTTPException(503, detail={"code": "budget_member_unverified"})
    members = set()
    try:
        for resource in latest.get("resources", []):
            name = resource.get("name", "")
            resource_type = resource.get("type")
            if resource_type == "User":
                members.add(name.lower())
            elif resource_type == "Team":
                if "/" in name:
                    org, team = name.split("/", 1)
                    roster = await api.get_team_members(org, team)
                else:
                    roster = await api.get_enterprise_team_members(enterprise, name)
                members.update(member.get("login", "").lower() for member in roster)
            elif resource_type == "Org":
                roster = await api.get_org_members(name)
                members.update(member.get("login", "").lower() for member in roster)
    except Exception:
        raise HTTPException(503, detail={"code": "budget_member_unverified"}) from None
    if login.lower() not in members or user["login"].lower() not in members:
        raise HTTPException(403, detail={"code": "budget_member_only"})
    require_owner(request, enterprise, cost_center_id)
    return user


def current_user(request: Request, admin: bool = False) -> dict:
    user = require_user(request)
    if not user:
        raise HTTPException(401, "Authentication required")
    if admin and not user.get("is_admin"):
        raise HTTPException(403, "Administrator access required")
    return user


def get_center(enterprise: str, cost_center_id: str) -> dict:
    snapshot = data_collector.load_latest("cost_centers", enterprise) or {}
    center = next((center for center in snapshot.get("cost_centers", []) if str(center.get("id")) == cost_center_id), None)
    if center is None:
        raise HTTPException(404, "Cost center not found")
    return center


def require_owner(request: Request, enterprise: str, cost_center_id: str) -> dict:
    user = current_user(request)
    if not any(center["enterprise"] == enterprise and center["id"] == cost_center_id for center in owned_cost_centers(user["login"])):
        raise HTTPException(403, "You do not own this cost center")
    return user


def scoped_records(records: list[dict], enterprise: str, center: dict, start: str, end: str) -> tuple[list[dict], bool]:
    matching_enterprises = {
        slug for slug, snapshot in data_collector.load_all_latest("cost_centers").items()
        if any(item.get("name") == center["name"] for item in snapshot.get("cost_centers", []))
    }
    ambiguous = len(matching_enterprises) > 1
    result = []
    for record in records:
        record_enterprise = record.get("enterprise") or record.get("enterprise_slug")
        if record_enterprise and record_enterprise.lower() != enterprise.lower():
            continue
        if not record_enterprise and ambiguous:
            continue
        if record.get("cost_center_id"):
            if str(record["cost_center_id"]) != str(center["id"]):
                continue
        elif record.get("cost_center_name") != center["name"]:
            continue
        day = record.get("date", "")
        if (start and day < start) or (end and day > end):
            continue
        result.append({**record, "username": record.get("username", "").lower()})
    return result, ambiguous


async def live_center(enterprise: str, cost_center_id: str) -> dict:
    api = api_manager.get_api_for_enterprise(enterprise)
    if api is None:
        raise HTTPException(503, "No GitHub API client available")
    try:
        return await api.get_cost_center(enterprise, cost_center_id)
    except Exception:
        raise HTTPException(502, "Unable to read current credit state from GitHub") from None


@router.get("/data/cost-center-owners")
async def list_owners(request: Request, enterprise: str):
    current_user(request, admin=True)
    return {"owners": {center_id: sorted(members) for center_id, members in load_owners().get(enterprise, {}).items()}}


@router.put("/data/cost-center-owner")
async def assign_owner(params: OwnerAssignment, request: Request):
    user = current_user(request, admin=True)
    center = get_center(params.enterprise, params.cost_center_id)
    login = params.login.strip().lower()
    if params.enabled and (center.get("state", "active") != "active" or not any(member.get("login", "").lower() == login for member in center.get("members", []))):
        raise HTTPException(400, "Owner must be a member of this active cost center")
    set_owner(params.enterprise, params.cost_center_id, login, params.enabled, user["login"])
    _append_audit_log({"timestamp": datetime.now(timezone.utc).isoformat(), "action": "set_cost_center_owner", "actor": user["login"], **params.model_dump()})
    return {"owners": owner_logins(params.enterprise, params.cost_center_id)}


@router.get("/me/owned-cost-centers")
async def my_owned_centers(request: Request):
    user = current_user(request)
    return {"cost_centers": owned_cost_centers(user["login"])}


@router.get("/me/owned-cost-center")
async def owner_dashboard(request: Request, enterprise: str, cost_center_id: str, period: str = "all", live: bool = True):
    require_owner(request, enterprise, cost_center_id)
    center = dict(get_center(enterprise, cost_center_id))
    credit_status = "cached"
    credit_error = None
    checked_at = None
    cap_verified = False
    if live:
        try:
            latest = await live_center(enterprise, cost_center_id)
            if latest.get("state", "active") != "active":
                raise HTTPException(403, "Cost center is no longer active")
            center.update({key: latest[key] for key in ("ai_credit_pool_enabled", "ai_credit_pool_state") if key in latest})
            cap_verified = isinstance(latest.get("ai_credit_pool_enabled"), bool)
            credit_status = "live"
            checked_at = datetime.now(timezone.utc).isoformat()
        except HTTPException as error:
            if error.status_code == 403:
                raise
            credit_status = "unavailable"
            credit_error = error.detail
    mode, start, end = resolve_period(period, "", "")
    ai_records, ambiguous = scoped_records(load_all_csv_records(CSV_TYPE_AI), enterprise, center, start, end)
    usage_records, usage_ambiguous = scoped_records(load_all_csv_records(CSV_TYPE_USAGE), enterprise, center, start, end)
    budget_status = "live"
    try:
        budgets = await read_individual_budgets(enterprise)
    except HTTPException:
        budgets = cached_budgets(enterprise)
        budget_status = "unavailable"
    read_only_reason = (
        "cap_unknown" if not cap_verified
        else "cap_off" if center.get("ai_credit_pool_enabled") is not True
        else "budgets_unavailable" if budget_status != "live"
        else None
    )
    user_budgets = []
    seen = set()
    for member in center.get("members", []):
        login = member.get("login", "")
        if not login or login.lower() in seen:
            continue
        seen.add(login.lower())
        matches = individual_credit_budgets(budgets, login)
        user_budgets.append({
            "login": login,
            "budgets": [_normalize(budget, "enterprise", enterprise) for budget in matches],
            "can_edit": read_only_reason is None and len(matches) <= 1,
        })
    require_owner(request, enterprise, cost_center_id)
    return {
        "enterprise": enterprise,
        "cost_center": center,
        "period": {"mode": mode, "start": start, "end": end},
        "ai_usage": _build_ai_usage_section(ai_records),
        "usage": _build_usage_section(usage_records),
        "ambiguous_billing_scope": ambiguous or usage_ambiguous,
        "credit_status": credit_status,
        "credit_error": credit_error,
        "credit_checked_at": checked_at,
        "cap_verified": cap_verified,
        "budget_status": budget_status,
        "budget_read_only_reason": read_only_reason,
        "user_budgets": user_budgets,
    }


@router.put("/me/owned-cost-center/user-budget")
async def save_owner_user_budget(params: OwnerUserBudget, request: Request):
    login = params.login.strip().lower()
    await verify_budget_write(request, params.enterprise, params.cost_center_id, login)
    budgets = await read_individual_budgets(params.enterprise)
    matches = individual_credit_budgets(budgets, login)
    if len(matches) > 1 or (matches and not matches[0].get("id")):
        raise HTTPException(409, detail={"code": "budget_ambiguous"})
    user = await verify_budget_write(request, params.enterprise, params.cost_center_id, login)
    api = api_manager.get_api_for_enterprise(params.enterprise)
    if api is None:
        raise HTTPException(503, detail={"code": "budgets_unavailable"})
    fields = {"budget_amount": params.amount, "prevent_further_usage": params.prevent_further_usage}
    try:
        if matches:
            result = await api.update_budget(
                entity_type="enterprise", entity_name=params.enterprise,
                budget_id=matches[0]["id"], budget_data=fields,
            )
        else:
            result = await api.create_budget(
                entity_type="enterprise", entity_name=params.enterprise,
                budget_data={
                    **fields, "budget_type": BUDGET_TYPE, "budget_product_sku": AI_CREDITS_SKU,
                    "budget_scope": SCOPE_USER, "budget_entity_name": login, "user": login,
                    "consumed_amount": 0, "budget_alerting": {"will_alert": False, "alert_recipients": []},
                },
            )
        if not isinstance(result, dict) or result.get("error"):
            raise ValueError("Budget write failed")
    except Exception:
        raise HTTPException(502, detail={"code": "budget_write_failed"}) from None
    action = "updated" if matches else "created"
    _append_audit_log({
        "timestamp": datetime.now(timezone.utc).isoformat(), "action": "owner_set_individual_budget",
        "actor": user["login"], **params.model_dump(), "login": login, "result": action,
        "budget_id": matches[0]["id"] if matches else (result.get("budget") or result).get("id"),
    })
    return {"ok": True, "status": action}


@router.put("/me/owned-cost-center/settings")
async def update_owner_settings(params: OwnerSettings, request: Request):
    current_user(request)
    raise HTTPException(403, detail={"code": "cap_admin_only"})