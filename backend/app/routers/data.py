"""
Data query router - provides read access to collected data.
Supports enterprise grouping for org display.
"""

import csv
import io
import json
import shutil
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Query, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..config import COPILOT_PRICING
from ..services.api_manager import api_manager
from ..services.budget_provisioner import current_month_range, fetch_budgets
from ..services.data_collector import data_collector, enterprise_pseudo_org
from ..services.report_generator import generate_report_zip

router = APIRouter(tags=["data"])


class AssignCostCenterUsersRequest(BaseModel):
    """Request to assign one or more GitHub users to an enterprise cost center."""

    enterprise: str = Field(default="")
    cost_center_id: str
    users: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Enterprise team filtering
#
# No Copilot dataset carries an enterprise-team field, so filtering by team is
# done by resolving the team to its member logins and matching every dataset on
# the user login.
# ---------------------------------------------------------------------------

# Sentinel slug for "users that belong to no enterprise team at all".
NO_ENTERPRISE_TEAM = "__no_team__"


class _UsersWithoutTeam:
    """Membership test matching any user that is in no enterprise team.

    Implements `__contains__` so it can be dropped in wherever a set of member
    logins is expected, without inverting every call site.
    """

    def __init__(self, team_logins: set[str]):
        self._team_logins = team_logins

    def __contains__(self, login: str) -> bool:
        return login not in self._team_logins


MemberFilter = set[str] | _UsersWithoutTeam


def _enterprise_team_options() -> list[dict]:
    """List every synced enterprise team, for filter dropdowns."""
    options: list[dict] = []
    for _enterprise, data in data_collector.load_all_latest("enterprise_teams").items():
        if not isinstance(data, dict):
            continue
        for team in data.get("teams", []):
            slug = team.get("slug", "")
            if slug:
                options.append({
                    "slug": slug,
                    "name": team.get("name", slug),
                    "enterprise": data.get("enterprise", ""),
                    "member_count": team.get("member_count", 0),
                })
    options.sort(key=lambda t: t["name"].lower())
    unaffiliated = len(_seat_logins_without_team())
    options.append({
        "slug": NO_ENTERPRISE_TEAM,
        "name": "(No enterprise team)",
        "enterprise": "",
        "member_count": unaffiliated,
    })
    return options


def _seat_logins_without_team() -> set[str]:
    """Copilot seat holders that belong to no enterprise team."""
    team_logins = _all_team_member_logins()
    seat_logins: set[str] = set()
    for _org, seats_data in data_collector.load_all_latest("seats").items():
        if not isinstance(seats_data, dict):
            continue
        for seat in seats_data.get("seats", []):
            login = ((seat.get("assignee") or {}).get("login") or "").lower()
            if login and login not in team_logins:
                seat_logins.add(login)
    return seat_logins


def _all_team_member_logins() -> set[str]:
    """Every login that belongs to at least one enterprise team (lowercased)."""
    logins: set[str] = set()
    for _enterprise, data in data_collector.load_all_latest("enterprise_teams").items():
        if not isinstance(data, dict):
            continue
        for team in data.get("teams", []):
            for m in team.get("members", []) or []:
                if m.get("login"):
                    logins.add(m["login"].lower())
    return logins


def _team_member_logins(team_slug: str) -> MemberFilter | None:
    """Resolve an enterprise team slug to a membership test.

    Returns None when no team is requested, and an empty set when the team
    exists but has no members (which must filter everything out, not nothing).
    """
    if not team_slug.strip():
        return None
    wanted = team_slug.strip().lower()
    if wanted == NO_ENTERPRISE_TEAM:
        return _UsersWithoutTeam(_all_team_member_logins())
    for _enterprise, data in data_collector.load_all_latest("enterprise_teams").items():
        if not isinstance(data, dict):
            continue
        for team in data.get("teams", []):
            if team.get("slug", "").lower() == wanted or team.get("name", "").lower() == wanted:
                return {
                    m.get("login", "").lower()
                    for m in team.get("members", [])
                    if m.get("login")
                }
    return set()


@router.get("/data/orgs")
async def get_orgs():
    """Get all discovered organizations with their Copilot status, grouped by enterprise."""
    all_orgs = api_manager.get_all_orgs()
    orgs_list = []

    for org_info in all_orgs:
        org_name = org_info["login"]
        billing = data_collector.load_latest("billing", org_name)

        org_data = {
            "login": org_name,
            "avatar_url": org_info.get("avatar_url"),
            "description": org_info.get("description"),
            "has_copilot": billing is not None,
            "enterprise": org_info.get("enterprise", "Independent"),
            "pat_user": org_info.get("pat_user", ""),
        }

        if billing:
            org_data["plan_type"] = billing.get("_detected_plan_type", "unknown")
            org_data["price_per_seat"] = billing.get("_detected_price_per_seat", 0)
            seat_breakdown = billing.get("seat_breakdown", {})
            org_data["total_seats"] = seat_breakdown.get("total", 0)
            org_data["active_seats"] = seat_breakdown.get("active_this_cycle", 0)

        orgs_list.append(org_data)

    # Group by enterprise
    groups: dict[str, list] = defaultdict(list)
    for org in orgs_list:
        groups[org.get("enterprise", "Independent")].append(org)

    enterprises = [
        {"name": name, "orgs": orgs}
        for name, orgs in sorted(groups.items(), key=lambda x: (x[0] == "Independent", x[0]))
    ]

    return {"enterprises": enterprises, "orgs": orgs_list, "total": len(orgs_list)}


@router.get("/data/overview")
async def get_overview():
    """Get a quick overview across all organizations.

    Also folds in enterprise-level Copilot data for enterprises that have no
    organizations (Copilot granted via enterprise teams, or organization
    scanning disabled for the owning PAT), so KPIs stay accurate even when
    the organizations list itself is empty.
    """
    all_orgs = api_manager.get_all_orgs()
    pseudo_orgs = api_manager.get_enterprise_pseudo_orgs()
    org_keys = [o["login"] for o in all_orgs] + [enterprise_pseudo_org(e["slug"]) for e in pseudo_orgs]
    total_seats = 0
    total_active = 0
    total_cost = 0.0
    total_waste = 0.0
    orgs_with_copilot = 0

    for org_name in org_keys:
        billing = data_collector.load_latest("billing", org_name)
        if not billing:
            continue

        orgs_with_copilot += 1
        price = billing.get("_detected_price_per_seat", 19.0)
        sb = billing.get("seat_breakdown", {})
        seats = sb.get("total", 0)
        active = sb.get("active_this_cycle", 0)

        total_seats += seats
        total_active += active
        total_cost += seats * price
        total_waste += (seats - active) * price

    return {
        "total_organizations": len(all_orgs),
        "orgs_with_copilot": orgs_with_copilot,
        "total_seats": total_seats,
        "total_active_seats": total_active,
        "total_inactive_seats": total_seats - total_active,
        "utilization_pct": round(total_active / total_seats * 100, 1) if total_seats > 0 else 0,
        "monthly_cost": total_cost,
        "monthly_waste": total_waste,
        "annual_waste": total_waste * 12,
    }


@router.get("/data/seats/{org}")
async def get_seats(org: str):
    """Get seat data for a specific organization."""
    data = data_collector.load_latest("seats", org)
    if not data:
        return {"error": f"No seat data for {org}"}
    return data


@router.get("/data/billing/{org}")
async def get_billing(org: str):
    """Get billing data for a specific organization."""
    data = data_collector.load_latest("billing", org)
    if not data:
        return {"error": f"No billing data for {org}"}
    return data


def _aggregate_usage_from_users(selected_orgs: list[str], member_filter: MemberFilter) -> dict:
    """Rebuild the Usage Metrics aggregates from user-level records.

    The org-level usage report is pre-aggregated and has no user dimension, so it
    cannot be filtered by enterprise team. The user-level report carries the same
    per-day breakdowns (ide/feature/language/model) per user, which lets the whole
    dashboard be recomputed for an arbitrary subset of users.
    """
    daily_map: dict[str, dict] = {}
    day_users: dict[str, set[str]] = defaultdict(set)
    feature_map: dict[str, dict] = defaultdict(lambda: {
        "interactions": 0, "code_gen": 0, "code_accept": 0, "loc_suggested": 0, "loc_accepted": 0})
    model_map: dict[str, dict] = defaultdict(lambda: {
        "interactions": 0, "code_gen": 0, "code_accept": 0, "loc_suggested": 0, "loc_accepted": 0})
    ide_map: dict[str, dict] = defaultdict(lambda: {
        "interactions": 0, "code_gen": 0, "code_accept": 0, "loc_suggested": 0, "loc_accepted": 0})
    lang_map: dict[str, dict] = defaultdict(lambda: {
        "code_gen": 0, "code_accept": 0, "loc_suggested": 0, "loc_accepted": 0})
    date_start = ""
    date_end = ""

    def accumulate(target: dict, src: dict, with_interactions: bool = True):
        if with_interactions:
            target["interactions"] += src.get("user_initiated_interaction_count", 0) or 0
        target["code_gen"] += src.get("code_generation_activity_count", 0) or 0
        target["code_accept"] += src.get("code_acceptance_activity_count", 0) or 0
        target["loc_suggested"] += (src.get("loc_suggested_to_add_sum", 0) or 0) + (src.get("loc_suggested_to_delete_sum", 0) or 0)
        target["loc_accepted"] += (src.get("loc_added_sum", 0) or 0) + (src.get("loc_deleted_sum", 0) or 0)

    for org_name in selected_orgs:
        report = data_collector.load_latest("usage_users", org_name)
        if not isinstance(report, dict):
            continue
        for rec in report.get("records", []) or []:
            login = (rec.get("user_login") or "").lower()
            if not login or login not in member_filter:
                continue
            day = rec.get("day", "")
            if not day:
                continue
            if not date_start or day < date_start:
                date_start = day
            if not date_end or day > date_end:
                date_end = day

            interactions = rec.get("user_initiated_interaction_count", 0) or 0
            dm = daily_map.setdefault(day, {
                "day": day, "dau": 0, "wau": 0, "mau": 0,
                "chat_users": 0, "agent_users": 0,
                "interactions": 0, "code_gen": 0, "code_accept": 0,
                "loc_suggested": 0, "loc_accepted": 0,
            })
            accumulate(dm, rec)
            if interactions > 0:
                day_users[day].add(login)
            if rec.get("used_chat"):
                dm["chat_users"] += 1
            if rec.get("used_agent"):
                dm["agent_users"] += 1

            for fb in rec.get("totals_by_feature", []) or []:
                accumulate(feature_map[fb.get("feature", "unknown")], fb)
            for mb in rec.get("totals_by_model_feature", []) or []:
                accumulate(model_map[mb.get("model", "unknown")], mb)
            for ib in rec.get("totals_by_ide", []) or []:
                accumulate(ide_map[ib.get("ide", "unknown")], ib)
            for lb in rec.get("totals_by_language_feature", []) or []:
                accumulate(lang_map[lb.get("language", "unknown")], lb, with_interactions=False)

    # Active-user counts are distinct users over trailing windows, which the
    # per-user records support but the org-level report only reports pre-rolled.
    sorted_days = sorted(daily_map)
    for day in sorted_days:
        window_7 = [d for d in sorted_days if d <= day][-7:]
        window_28 = [d for d in sorted_days if d <= day][-28:]
        daily_map[day]["dau"] = len(day_users.get(day, set()))
        daily_map[day]["wau"] = len(set().union(*(day_users[d] for d in window_7)) if window_7 else set())
        daily_map[day]["mau"] = len(set().union(*(day_users[d] for d in window_28)) if window_28 else set())

    return {
        "daily_trend": [daily_map[d] for d in sorted_days],
        "feature_usage": [{"feature": k, **v} for k, v in sorted(feature_map.items(), key=lambda x: -x[1]["interactions"])],
        "model_usage": [{"model": k, **v} for k, v in sorted(model_map.items(), key=lambda x: -x[1]["interactions"])],
        "ide_usage": [{"ide": k, **v} for k, v in sorted(ide_map.items(), key=lambda x: -x[1]["interactions"])],
        "language_usage": [{"language": k, **v} for k, v in sorted(lang_map.items(), key=lambda x: -x[1]["code_gen"])],
        "date_start": date_start,
        "date_end": date_end,
    }


@router.get("/data/dashboard")
async def get_dashboard(
    orgs: str = Query(default=""),
    enterprise_team: str = Query(default="", description="Enterprise team slug to filter members by"),
):
    """Aggregated dashboard data for visualization.

    Query param ``orgs`` is a comma-separated list of org logins to include.
    Empty means all orgs with Copilot billing data. Also includes pseudo-org
    entries for enterprises with no organizations (see `enterprise_pseudo_org`)
    so the dashboard stays populated even when the organizations list is empty.

    When ``enterprise_team`` is set, every section is restricted to that team's
    members and the usage aggregates are recomputed from user-level records.
    """
    all_orgs = api_manager.get_all_orgs()
    pseudo_orgs = api_manager.get_enterprise_pseudo_orgs()
    all_org_names = [o["login"] for o in all_orgs] + [enterprise_pseudo_org(e["slug"]) for e in pseudo_orgs]
    selected = [o.strip() for o in orgs.split(",") if o.strip()] if orgs.strip() else all_org_names
    member_filter = _team_member_logins(enterprise_team)

    # --- KPI from billing ---
    total_seats = 0
    active_seats = 0
    monthly_cost = 0.0
    monthly_waste = 0.0
    available_orgs: list[str] = []

    for org_name in selected:
        billing = data_collector.load_latest("billing", org_name)
        if not billing:
            continue
        available_orgs.append(org_name)
        price = billing.get("_detected_price_per_seat", 19.0)
        sb = billing.get("seat_breakdown", {})
        s = sb.get("total", 0)
        a = sb.get("active_this_cycle", 0)
        total_seats += s
        active_seats += a
        monthly_cost += s * price
        monthly_waste += (s - a) * price

    if member_filter is not None:
        # Billing counters are org-wide, so rebuild the KPIs from the team's own
        # seats. "Active" here means the seat reported activity in the last 30 days.
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        total_seats = 0
        active_seats = 0
        monthly_cost = 0.0
        monthly_waste = 0.0
        for org_name in selected:
            billing = data_collector.load_latest("billing", org_name) or {}
            price = billing.get("_detected_price_per_seat", 19.0)
            seats_data = data_collector.load_latest("seats", org_name)
            if not seats_data:
                continue
            for seat in seats_data.get("seats", []):
                login = ((seat.get("assignee") or {}).get("login") or "").lower()
                if login not in member_filter:
                    continue
                total_seats += 1
                monthly_cost += price
                if (seat.get("last_activity_at") or "") >= cutoff:
                    active_seats += 1
                else:
                    monthly_waste += price

    inactive_seats = total_seats - active_seats
    utilization_pct = round(active_seats / total_seats * 100, 1) if total_seats > 0 else 0

    kpi = {
        "total_seats": total_seats,
        "active_seats": active_seats,
        "inactive_seats": inactive_seats,
        "utilization_pct": utilization_pct,
        "monthly_cost": monthly_cost,
        "monthly_waste": monthly_waste,
    }

    # --- Seat info from billing + seats ---
    seat_info = {
        "breakdown": {"pending_invitation": 0, "pending_cancellation": 0, "added_this_cycle": 0},
        "plans": {},   # plan_type -> count
        "features": {},  # feature -> enabled/disabled
        "seats": [],  # individual seat records
    }
    for org_name in selected:
        billing = data_collector.load_latest("billing", org_name)
        if billing:
            sb = billing.get("seat_breakdown", {})
            seat_info["breakdown"]["pending_invitation"] += sb.get("pending_invitation", 0)
            seat_info["breakdown"]["pending_cancellation"] += sb.get("pending_cancellation", 0)
            seat_info["breakdown"]["added_this_cycle"] += sb.get("added_this_cycle", 0)
            pt = billing.get("_detected_plan_type", billing.get("plan_type", "unknown"))
            seat_info["plans"][pt] = seat_info["plans"].get(pt, 0) + 1
            for feat in ("ide_chat", "cli", "platform_chat", "public_code_suggestions"):
                val = billing.get(feat, "")
                if val:
                    seat_info["features"][feat] = val

        seats_data = data_collector.load_latest("seats", org_name)
        if seats_data:
            for s in seats_data.get("seats", []):
                assignee = s.get("assignee", {})
                if member_filter is not None and (assignee.get("login") or "").lower() not in member_filter:
                    continue
                team = s.get("assigning_team")
                seat_info["seats"].append({
                    "user": assignee.get("login", ""),
                    "avatar": assignee.get("avatar_url", ""),
                    "org": org_name,
                    "plan_type": s.get("plan_type", ""),
                    "created_at": s.get("created_at", ""),
                    "last_activity_at": s.get("last_activity_at"),
                    "last_activity_editor": s.get("last_activity_editor"),
                    "pending_cancellation_date": s.get("pending_cancellation_date"),
                    "team": team.get("name", "") if team else "",
                })

    # --- Aggregate usage data ---
    daily_map: dict[str, dict] = {}
    feature_map: dict[str, dict] = defaultdict(lambda: {
        "interactions": 0, "code_gen": 0, "code_accept": 0,
        "loc_suggested": 0, "loc_accepted": 0,
    })
    model_map: dict[str, dict] = defaultdict(lambda: {
        "interactions": 0, "code_gen": 0, "code_accept": 0,
        "loc_suggested": 0, "loc_accepted": 0,
    })
    ide_map: dict[str, dict] = defaultdict(lambda: {
        "interactions": 0, "code_gen": 0, "code_accept": 0,
        "loc_suggested": 0, "loc_accepted": 0,
    })
    lang_map: dict[str, dict] = defaultdict(lambda: {
        "code_gen": 0, "code_accept": 0,
        "loc_suggested": 0, "loc_accepted": 0,
    })
    date_start = ""
    date_end = ""

    # With a team filter the org-level report is unusable (no user dimension);
    # the aggregates below are rebuilt from user-level records instead.
    for org_name in (selected if member_filter is None else []):
        usage = data_collector.load_latest("usage", org_name)
        if not usage:
            continue

        for rec in usage.get("records", []):
            rs = rec.get("report_start_day", "")
            re_ = rec.get("report_end_day", "")
            if rs and (not date_start or rs < date_start):
                date_start = rs
            if re_ and (not date_end or re_ > date_end):
                date_end = re_

            for dt in rec.get("day_totals", []):
                day = dt.get("day", "")
                if not day:
                    continue
                if day not in daily_map:
                    daily_map[day] = {
                        "day": day, "dau": 0, "wau": 0, "mau": 0,
                        "chat_users": 0, "agent_users": 0,
                        "interactions": 0, "code_gen": 0, "code_accept": 0,
                        "loc_suggested": 0, "loc_accepted": 0,
                    }
                dm = daily_map[day]
                dm["dau"] += dt.get("daily_active_users", 0)
                dm["wau"] += dt.get("weekly_active_users", 0)
                dm["mau"] += dt.get("monthly_active_users", 0)
                dm["chat_users"] += dt.get("monthly_active_chat_users", 0)
                dm["agent_users"] += dt.get("monthly_active_agent_users", 0)
                dm["interactions"] += dt.get("user_initiated_interaction_count", 0)
                dm["code_gen"] += dt.get("code_generation_activity_count", 0)
                dm["code_accept"] += dt.get("code_acceptance_activity_count", 0)
                dm["loc_suggested"] += dt.get("loc_suggested_to_add_sum", 0) + dt.get("loc_suggested_to_delete_sum", 0)
                dm["loc_accepted"] += dt.get("loc_added_sum", 0) + dt.get("loc_deleted_sum", 0)

                for fb in dt.get("totals_by_feature", []):
                    f = fb.get("feature", "unknown")
                    feature_map[f]["interactions"] += fb.get("user_initiated_interaction_count", 0)
                    feature_map[f]["code_gen"] += fb.get("code_generation_activity_count", 0)
                    feature_map[f]["code_accept"] += fb.get("code_acceptance_activity_count", 0)
                    feature_map[f]["loc_suggested"] += fb.get("loc_suggested_to_add_sum", 0) + fb.get("loc_suggested_to_delete_sum", 0)
                    feature_map[f]["loc_accepted"] += fb.get("loc_added_sum", 0) + fb.get("loc_deleted_sum", 0)

                for mb in dt.get("totals_by_model_feature", []):
                    m = mb.get("model", "unknown")
                    model_map[m]["interactions"] += mb.get("user_initiated_interaction_count", 0)
                    model_map[m]["code_gen"] += mb.get("code_generation_activity_count", 0)
                    model_map[m]["code_accept"] += mb.get("code_acceptance_activity_count", 0)
                    model_map[m]["loc_suggested"] += mb.get("loc_suggested_to_add_sum", 0) + mb.get("loc_suggested_to_delete_sum", 0)
                    model_map[m]["loc_accepted"] += mb.get("loc_added_sum", 0) + mb.get("loc_deleted_sum", 0)

                for ib in dt.get("totals_by_ide", []):
                    ide = ib.get("ide", "unknown")
                    ide_map[ide]["interactions"] += ib.get("user_initiated_interaction_count", 0)
                    ide_map[ide]["code_gen"] += ib.get("code_generation_activity_count", 0)
                    ide_map[ide]["code_accept"] += ib.get("code_acceptance_activity_count", 0)
                    ide_map[ide]["loc_suggested"] += ib.get("loc_suggested_to_add_sum", 0) + ib.get("loc_suggested_to_delete_sum", 0)
                    ide_map[ide]["loc_accepted"] += ib.get("loc_added_sum", 0) + ib.get("loc_deleted_sum", 0)

                for lb in dt.get("totals_by_language_feature", []):
                    lang = lb.get("language", "unknown")
                    lang_map[lang]["code_gen"] += lb.get("code_generation_activity_count", 0)
                    lang_map[lang]["code_accept"] += lb.get("code_acceptance_activity_count", 0)
                    lang_map[lang]["loc_suggested"] += lb.get("loc_suggested_to_add_sum", 0) + lb.get("loc_suggested_to_delete_sum", 0)
                    lang_map[lang]["loc_accepted"] += lb.get("loc_added_sum", 0) + lb.get("loc_deleted_sum", 0)

    daily_trend = sorted(daily_map.values(), key=lambda x: x["day"])

    feature_usage = [{"feature": k, **v} for k, v in sorted(feature_map.items(), key=lambda x: -x[1]["interactions"])]
    model_usage = [{"model": k, **v} for k, v in sorted(model_map.items(), key=lambda x: -x[1]["interactions"])]
    ide_usage = [{"ide": k, **v} for k, v in sorted(ide_map.items(), key=lambda x: -x[1]["interactions"])]
    language_usage = [{"language": k, **v} for k, v in sorted(lang_map.items(), key=lambda x: -x[1]["code_gen"])]

    if member_filter is not None:
        rebuilt = _aggregate_usage_from_users(selected, member_filter)
        daily_trend = rebuilt["daily_trend"]
        feature_usage = rebuilt["feature_usage"]
        model_usage = rebuilt["model_usage"]
        ide_usage = rebuilt["ide_usage"]
        language_usage = rebuilt["language_usage"]
        date_start = rebuilt["date_start"]
        date_end = rebuilt["date_end"]

    # --- AI credit detail ---
    pr_detail_map: dict[str, dict] = defaultdict(lambda: {
        "gross_qty": 0, "discount_qty": 0, "net_qty": 0,
        "gross_amount": 0.0, "net_amount": 0.0,
    })
    for org_name in (selected if member_filter is None else []):
        pr = data_collector.load_latest("ai_credits", org_name)
        if not pr:
            continue
        for item in pr.get("usageItems", []):
            m = item.get("model", "unknown")
            pr_detail_map[m]["gross_qty"] += item.get("grossQuantity", 0)
            pr_detail_map[m]["discount_qty"] += item.get("discountQuantity", 0)
            pr_detail_map[m]["net_qty"] += item.get("netQuantity", 0)
            pr_detail_map[m]["gross_amount"] += item.get("grossAmount", 0.0)
            pr_detail_map[m]["net_amount"] += item.get("netAmount", 0.0)

    if member_filter is not None:
        # Cached AI credit data is aggregated per model with no user dimension;
        # the uploaded AI usage CSV is the only per-user source.
        for r in _apply_common_filters(_load_all_csv_records(CSV_TYPE_AI), [], [], "", "", member_filter):
            m = r.get("model", "unknown")
            try:
                pr_detail_map[m]["gross_qty"] += float(r.get("quantity") or 0)
                pr_detail_map[m]["net_qty"] += float(r.get("quantity") or 0)
                pr_detail_map[m]["gross_amount"] += float(r.get("gross_amount") or 0)
                pr_detail_map[m]["net_amount"] += float(r.get("net_amount") or 0)
            except (TypeError, ValueError):
                continue

    ai_credit_detail = [{"model": k, **v} for k, v in sorted(pr_detail_map.items(), key=lambda x: -x[1]["gross_qty"])]

    # Merge AI credit totals into model_usage
    for entry in model_usage:
        pd = pr_detail_map.pop(entry["model"], None)
        entry["ai_credits"] = pd["gross_qty"] if pd else 0
    for m, pd in pr_detail_map.items():
        if pd["gross_qty"] > 0:
            model_usage.append({"model": m, "interactions": 0, "code_gen": 0, "code_accept": 0,
                                "loc_suggested": 0, "loc_accepted": 0, "ai_credits": pd["gross_qty"]})

    # --- Top users from usage_users (enhanced) ---
    user_agg: dict[str, dict] = defaultdict(lambda: {
        "interactions": 0, "code_gen": 0, "code_accept": 0,
        "loc_suggested": 0, "loc_accepted": 0,
        "days_active": 0, "used_agent": False, "used_chat": False,
    })
    for org_name in selected:
        uu = data_collector.load_latest("usage_users", org_name)
        if not uu:
            continue
        for rec in uu.get("records", []):
            login = rec.get("user_login", "")
            if not login:
                continue
            if member_filter is not None and login.lower() not in member_filter:
                continue
            u = user_agg[login]
            u["interactions"] += rec.get("user_initiated_interaction_count", 0)
            u["code_gen"] += rec.get("code_generation_activity_count", 0)
            u["code_accept"] += rec.get("code_acceptance_activity_count", 0)
            u["loc_suggested"] += rec.get("loc_suggested_to_add_sum", 0) + rec.get("loc_suggested_to_delete_sum", 0)
            u["loc_accepted"] += rec.get("loc_added_sum", 0) + rec.get("loc_deleted_sum", 0)
            u["days_active"] += 1
            if rec.get("used_agent"):
                u["used_agent"] = True
            if rec.get("used_chat"):
                u["used_chat"] = True

    top_users = sorted(
        [{"user": k, **v} for k, v in user_agg.items()],
        key=lambda x: -x["interactions"],
    )[:30]

    # --- Metrics data (code completions by language, chat stats) ---
    metrics_lang_map: dict[str, dict] = defaultdict(lambda: {
        "suggestions": 0, "acceptances": 0,
        "lines_suggested": 0, "lines_accepted": 0, "engaged_users": 0,
    })
    chat_stats = {"ide_chats": 0, "ide_copy_events": 0, "ide_insertion_events": 0,
                  "dotcom_chats": 0, "pr_summaries": 0}

    for org_name in selected:
        metrics = data_collector.load_latest("metrics", org_name)
        if not metrics:
            continue
        entries = metrics if isinstance(metrics, list) else [metrics]
        for entry in entries:
            # Code completions
            cc = entry.get("copilot_ide_code_completions", {})
            for editor in cc.get("editors", []):
                for model in editor.get("models", []):
                    for lang in model.get("languages", []):
                        ln = lang.get("name", "unknown")
                        metrics_lang_map[ln]["suggestions"] += lang.get("total_code_suggestions", 0)
                        metrics_lang_map[ln]["acceptances"] += lang.get("total_code_acceptances", 0)
                        metrics_lang_map[ln]["lines_suggested"] += lang.get("total_code_lines_suggested", 0)
                        metrics_lang_map[ln]["lines_accepted"] += lang.get("total_code_lines_accepted", 0)
                        metrics_lang_map[ln]["engaged_users"] += lang.get("total_engaged_users", 0)
            # IDE chat
            ic = entry.get("copilot_ide_chat", {})
            for editor in ic.get("editors", []):
                for model in editor.get("models", []):
                    chat_stats["ide_chats"] += model.get("total_chats", 0)
                    chat_stats["ide_copy_events"] += model.get("total_chat_copy_events", 0)
                    chat_stats["ide_insertion_events"] += model.get("total_chat_insertion_events", 0)
            # Dotcom chat
            dc = entry.get("copilot_dotcom_chat", {})
            for model in dc.get("models", []):
                chat_stats["dotcom_chats"] += model.get("total_chats", 0)
            # PR summaries
            dpr = entry.get("copilot_dotcom_pull_requests", {})
            for repo in dpr.get("repositories", []):
                for model in repo.get("models", []):
                    chat_stats["pr_summaries"] += model.get("total_pr_summaries_created", 0)

    code_completions = [{"language": k, **v} for k, v in sorted(
        metrics_lang_map.items(), key=lambda x: -x[1]["suggestions"]
    )]

    return {
        "kpi": kpi,
        "seat_info": seat_info,
        "daily_trend": daily_trend,
        "feature_usage": feature_usage,
        "model_usage": model_usage,
        "ide_usage": ide_usage,
        "language_usage": language_usage,
        "code_completions": code_completions,
        "ai_credit_detail": ai_credit_detail,
        "chat_stats": chat_stats,
        "top_users": top_users,
        "orgs": all_org_names,
        "enterprise_teams": _enterprise_team_options(),
        "selected_enterprise_team": enterprise_team or None,
        "team_filtered": member_filter is not None,
        "team_member_count": len(member_filter) if isinstance(member_filter, set) else None,
        "date_range": {"start": date_start, "end": date_end},
        "user_ai_usage": _aggregate_user_ai_usage(selected, member_filter),
    }


# ---------------------------------------------------------------------------
# CSV dashboard endpoint (dedicated, separate from main dashboard)
# ---------------------------------------------------------------------------

@router.get("/data/csv-dashboard")
async def get_csv_dashboard(
    orgs: str = Query(default=""),
    cost_centers: str = Query(default=""),
    products: str = Query(default=""),
    skus: str = Query(default=""),
    date_from: str = Query(default=""),
    date_to: str = Query(default=""),
    enterprise_team: str = Query(default="", description="Enterprise team slug to filter members by"),
):
    """Aggregated dashboard data derived entirely from uploaded CSVs."""
    selected_orgs = [o.strip() for o in orgs.split(",") if o.strip()]
    selected_ccs = [c.strip() for c in cost_centers.split(",") if c.strip()]
    selected_products = [p.strip() for p in products.split(",") if p.strip()]
    selected_skus = [s.strip() for s in skus.split(",") if s.strip()]
    member_filter = _team_member_logins(enterprise_team)

    ai_usage = _build_ai_usage_section(selected_orgs, selected_ccs, date_from, date_to, member_filter)
    usage = _build_usage_report_section(selected_orgs, selected_ccs, selected_products, selected_skus, date_from, date_to, member_filter)

    # Gather all filter options from raw data
    all_ai_usage = _load_all_csv_records(CSV_TYPE_AI)
    all_usage = _load_all_csv_records(CSV_TYPE_USAGE)
    all_orgs: set[str] = set()
    all_ccs: set[str] = set()
    all_products: set[str] = set()
    all_skus: set[str] = set()
    for r in all_ai_usage:
        if r.get("organization"):
            all_orgs.add(r["organization"])
        if r.get("cost_center_name"):
            all_ccs.add(r["cost_center_name"])
    for r in all_usage:
        if r.get("organization"):
            all_orgs.add(r["organization"])
        if r.get("cost_center_name"):
            all_ccs.add(r["cost_center_name"])
        if r.get("product"):
            all_products.add(r["product"])
        if r.get("sku"):
            all_skus.add(r["sku"])

    return {
        "ai_usage": ai_usage,
        "usage_report": usage,
        "selected_enterprise_team": enterprise_team or None,
        "filters": {
            "orgs": sorted(all_orgs),
            "cost_centers": sorted(all_ccs),
            "products": sorted(all_products),
            "skus": sorted(all_skus),
            "enterprise_teams": _enterprise_team_options(),
        },
    }


def _apply_common_filters(records: list[dict], selected_orgs: list[str], selected_ccs: list[str],
                           date_from: str, date_to: str,
                           member_filter: MemberFilter | None = None) -> list[dict]:
    result = records
    if selected_orgs:
        result = [r for r in result if r.get("organization", "") in selected_orgs]
    if selected_ccs:
        result = [r for r in result if (r.get("cost_center_name") or "") in selected_ccs]
    if member_filter is not None:
        result = [r for r in result if (r.get("username") or "").lower() in member_filter]
    if date_from:
        result = [r for r in result if r.get("date", "") >= date_from]
    if date_to:
        result = [r for r in result if r.get("date", "") <= date_to]
    return result


def _build_ai_usage_section(selected_orgs: list[str], selected_ccs: list[str],
                                date_from: str, date_to: str,
                                member_filter: MemberFilter | None = None) -> dict:
    """Build aggregated AI usage CSV section for the CSV dashboard."""
    all_records = _load_all_csv_records(CSV_TYPE_AI)
    if not all_records:
        return {"has_data": False, "date_range": {}, "kpi": {}, "daily_trend": [],
                "model_breakdown": [], "org_breakdown": [], "cost_center_breakdown": [], "users": []}

    filtered = _apply_common_filters(all_records, selected_orgs, selected_ccs, date_from, date_to, member_filter)
    if not filtered:
        return {"has_data": False, "date_range": {}, "kpi": {}, "daily_trend": [],
                "model_breakdown": [], "org_breakdown": [], "cost_center_breakdown": [], "users": []}

    dates = [r.get("date", "") for r in filtered if r.get("date")]
    date_range = {"start": min(dates) if dates else "", "end": max(dates) if dates else ""}

    # Per-user aggregation
    user_map: dict[str, dict] = defaultdict(lambda: {
        "requests": 0, "gross_amount": 0.0, "net_amount": 0.0,
        "models": defaultdict(float), "days_active": set(), "org": "",
        "quota": 0, "cost_center": "",
    })
    for r in filtered:
        user = r.get("username", "")
        qty = float(r.get("quantity", 0))
        gross = float(r.get("gross_amount", 0))
        net = float(r.get("net_amount", 0))
        model = r.get("model", "unknown")
        u = user_map[user]
        u["requests"] += qty
        u["gross_amount"] += gross
        u["net_amount"] += net
        u["models"][model] += qty
        u["days_active"].add(r.get("date", ""))
        u["org"] = r.get("organization", "")
        u["cost_center"] = r.get("cost_center_name", "") or ""
        try:
            u["quota"] = int(r.get("total_monthly_quota", 0))
        except (ValueError, TypeError):
            pass

    users = []
    for username, info in sorted(user_map.items(), key=lambda x: -x[1]["requests"]):
        models = [{"model": m, "requests": q} for m, q in sorted(info["models"].items(), key=lambda x: -x[1])]
        users.append({
            "user": username, "org": info["org"], "cost_center": info["cost_center"],
            "requests": round(info["requests"], 2), "gross_amount": round(info["gross_amount"], 4),
            "net_amount": round(info["net_amount"], 4), "days_active": len(info["days_active"]),
            "quota": info["quota"],
            "usage_pct": round(info["requests"] / info["quota"] * 100, 1) if info["quota"] > 0 else 0,
            "models": models,
        })

    # Daily trend
    day_map: dict[str, dict] = defaultdict(lambda: {"requests": 0, "amount": 0.0, "users": set()})
    for r in filtered:
        dm = day_map[r.get("date", "")]
        dm["requests"] += float(r.get("quantity", 0))
        dm["amount"] += float(r.get("gross_amount", 0))
        dm["users"].add(r.get("username", ""))
    daily_trend = [{"day": d, "requests": round(v["requests"], 2), "amount": round(v["amount"], 4),
                    "active_users": len(v["users"])} for d, v in sorted(day_map.items())]

    # Model breakdown
    model_map: dict[str, dict] = defaultdict(lambda: {"requests": 0, "amount": 0.0, "users": set()})
    for r in filtered:
        mm = model_map[r.get("model", "unknown")]
        mm["requests"] += float(r.get("quantity", 0))
        mm["amount"] += float(r.get("gross_amount", 0))
        mm["users"].add(r.get("username", ""))
    model_breakdown = [{"model": m, "requests": round(v["requests"], 2), "amount": round(v["amount"], 4),
                        "user_count": len(v["users"])} for m, v in sorted(model_map.items(), key=lambda x: -x[1]["requests"])]

    # Org breakdown
    org_map: dict[str, dict] = defaultdict(lambda: {"requests": 0, "amount": 0.0, "users": set()})
    for r in filtered:
        om = org_map[r.get("organization", "")]
        om["requests"] += float(r.get("quantity", 0))
        om["amount"] += float(r.get("gross_amount", 0))
        om["users"].add(r.get("username", ""))
    org_breakdown = [{"org": o, "requests": round(v["requests"], 2), "amount": round(v["amount"], 4),
                      "user_count": len(v["users"])} for o, v in sorted(org_map.items(), key=lambda x: -x[1]["requests"])]

    # Cost center breakdown
    cc_map: dict[str, dict] = defaultdict(lambda: {"requests": 0, "amount": 0.0, "users": set()})
    for r in filtered:
        cc = r.get("cost_center_name", "") or "Unknown"
        cm = cc_map[cc]
        cm["requests"] += float(r.get("quantity", 0))
        cm["amount"] += float(r.get("gross_amount", 0))
        cm["users"].add(r.get("username", ""))
    cost_center_breakdown = [{"cost_center": cc, "requests": round(v["requests"], 2), "amount": round(v["amount"], 4),
                               "user_count": len(v["users"])} for cc, v in sorted(cc_map.items(), key=lambda x: -x[1]["requests"])]

    total_requests = sum(u["requests"] for u in users)
    total_cost = sum(u["gross_amount"] for u in users)

    return {
        "has_data": True,
        "date_range": date_range,
        "kpi": {
            "total_requests": round(total_requests, 2),
            "total_cost": round(total_cost, 4),
            "unique_users": len(users),
            "unique_orgs": len(org_breakdown),
        },
        "daily_trend": daily_trend,
        "model_breakdown": model_breakdown,
        "org_breakdown": org_breakdown,
        "cost_center_breakdown": cost_center_breakdown,
        "users": users,
    }


def _build_usage_report_section(selected_orgs: list[str], selected_ccs: list[str],
                                 selected_products: list[str], selected_skus: list[str],
                                 date_from: str, date_to: str,
                                 member_filter: MemberFilter | None = None) -> dict:
    """Build aggregated usage report CSV section for CSV dashboard."""
    all_records = _load_all_csv_records(CSV_TYPE_USAGE)
    if not all_records:
        return {"has_data": False, "date_range": {}, "kpi": {}, "daily_trend": [],
                "product_breakdown": [], "sku_breakdown": [], "org_breakdown": [],
                "cost_center_breakdown": [], "users": []}

    filtered = _apply_common_filters(all_records, selected_orgs, selected_ccs, date_from, date_to, member_filter)
    if selected_products:
        filtered = [r for r in filtered if r.get("product", "") in selected_products]
    if selected_skus:
        filtered = [r for r in filtered if r.get("sku", "") in selected_skus]

    if not filtered:
        return {"has_data": False, "date_range": {}, "kpi": {}, "daily_trend": [],
                "product_breakdown": [], "sku_breakdown": [], "org_breakdown": [],
                "cost_center_breakdown": [], "users": []}

    dates = [r.get("date", "") for r in filtered if r.get("date")]
    date_range = {"start": min(dates) if dates else "", "end": max(dates) if dates else ""}

    # Daily trend
    day_map: dict[str, dict] = defaultdict(lambda: {"gross": 0.0, "net": 0.0, "users": set()})
    for r in filtered:
        dm = day_map[r.get("date", "")]
        dm["gross"] += float(r.get("gross_amount", 0))
        dm["net"] += float(r.get("net_amount", 0))
        dm["users"].add(r.get("username", ""))
    daily_trend = [{"day": d, "gross_amount": round(v["gross"], 4), "net_amount": round(v["net"], 4),
                    "active_users": len(v["users"])} for d, v in sorted(day_map.items())]

    # Product breakdown
    prod_map: dict[str, dict] = defaultdict(lambda: {"gross": 0.0, "net": 0.0, "users": set(), "quantity": 0.0})
    for r in filtered:
        pm = prod_map[r.get("product", "unknown")]
        pm["gross"] += float(r.get("gross_amount", 0))
        pm["net"] += float(r.get("net_amount", 0))
        pm["quantity"] += float(r.get("quantity", 0))
        pm["users"].add(r.get("username", ""))
    product_breakdown = [{"product": p, "gross_amount": round(v["gross"], 4), "net_amount": round(v["net"], 4),
                           "quantity": round(v["quantity"], 4), "user_count": len(v["users"])}
                         for p, v in sorted(prod_map.items(), key=lambda x: -x[1]["gross"])]

    # SKU breakdown
    sku_map: dict[str, dict] = defaultdict(lambda: {"gross": 0.0, "net": 0.0, "users": set(), "quantity": 0.0})
    for r in filtered:
        sm = sku_map[r.get("sku", "unknown")]
        sm["gross"] += float(r.get("gross_amount", 0))
        sm["net"] += float(r.get("net_amount", 0))
        sm["quantity"] += float(r.get("quantity", 0))
        sm["users"].add(r.get("username", ""))
    sku_breakdown = [{"sku": s, "gross_amount": round(v["gross"], 4), "net_amount": round(v["net"], 4),
                      "quantity": round(v["quantity"], 4), "user_count": len(v["users"])}
                     for s, v in sorted(sku_map.items(), key=lambda x: -x[1]["gross"])]

    # Org breakdown
    org_map: dict[str, dict] = defaultdict(lambda: {"gross": 0.0, "net": 0.0, "users": set()})
    for r in filtered:
        om = org_map[r.get("organization", "")]
        om["gross"] += float(r.get("gross_amount", 0))
        om["net"] += float(r.get("net_amount", 0))
        om["users"].add(r.get("username", ""))
    org_breakdown = [{"org": o, "gross_amount": round(v["gross"], 4), "net_amount": round(v["net"], 4),
                      "user_count": len(v["users"])} for o, v in sorted(org_map.items(), key=lambda x: -x[1]["gross"])]

    # Cost center breakdown
    cc_map: dict[str, dict] = defaultdict(lambda: {"gross": 0.0, "net": 0.0, "users": set()})
    for r in filtered:
        cc = r.get("cost_center_name", "") or "Unknown"
        cm = cc_map[cc]
        cm["gross"] += float(r.get("gross_amount", 0))
        cm["net"] += float(r.get("net_amount", 0))
        cm["users"].add(r.get("username", ""))
    cost_center_breakdown = [{"cost_center": cc, "gross_amount": round(v["gross"], 4), "net_amount": round(v["net"], 4),
                               "user_count": len(v["users"])} for cc, v in sorted(cc_map.items(), key=lambda x: -x[1]["gross"])]

    # Per-user aggregation
    user_map: dict[str, dict] = defaultdict(lambda: {
        "gross": 0.0, "net": 0.0, "quantity": 0.0, "org": "", "cost_center": "",
        "skus": defaultdict(float), "days_active": set(),
    })
    for r in filtered:
        user = r.get("username", "")
        um = user_map[user]
        um["gross"] += float(r.get("gross_amount", 0))
        um["net"] += float(r.get("net_amount", 0))
        um["quantity"] += float(r.get("quantity", 0))
        um["org"] = r.get("organization", "")
        um["cost_center"] = r.get("cost_center_name", "") or ""
        um["skus"][r.get("sku", "unknown")] += float(r.get("gross_amount", 0))
        um["days_active"].add(r.get("date", ""))
    users = []
    for username, info in sorted(user_map.items(), key=lambda x: -x[1]["gross"]):
        skus = [{"sku": s, "amount": round(a, 4)} for s, a in sorted(info["skus"].items(), key=lambda x: -x[1])]
        users.append({
            "user": username, "org": info["org"], "cost_center": info["cost_center"],
            "gross_amount": round(info["gross"], 4), "net_amount": round(info["net"], 4),
            "quantity": round(info["quantity"], 4), "days_active": len(info["days_active"]),
            "skus": skus,
        })

    total_gross = sum(float(r.get("gross_amount", 0)) for r in filtered)
    total_net = sum(float(r.get("net_amount", 0)) for r in filtered)
    total_discount = sum(float(r.get("discount_amount", 0)) for r in filtered)

    return {
        "has_data": True,
        "date_range": date_range,
        "kpi": {
            "total_gross": round(total_gross, 4),
            "total_net": round(total_net, 4),
            "total_discount": round(total_discount, 4),
            "unique_users": len(users),
            "unique_orgs": len(org_breakdown),
        },
        "daily_trend": daily_trend,
        "product_breakdown": product_breakdown,
        "sku_breakdown": sku_breakdown,
        "org_breakdown": org_breakdown,
        "cost_center_breakdown": cost_center_breakdown,
        "users": users,
    }


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------

CSV_TYPE_AI = "ai_usage"
CSV_TYPE_USAGE = "usage_report"


def _get_csv_dir(csv_type: str = CSV_TYPE_AI) -> Path:
    if csv_type == CSV_TYPE_USAGE:
        return data_collector.data_dir / "usage_report_csv"
    return data_collector.data_dir / "ai_usage_csv"


def _detect_csv_type(fieldnames: list[str]) -> str | None:
    """Detect whether a CSV is an AI usage report or a usage report based on columns.

    - AI Usage report (UBB): has a per-model breakdown, identified by a ``model``
      column alongside ``username``/``organization``.
    - Usage report: aggregated by ``product``/``sku``/``unit_type`` with no ``model`` column.
    """
    cols = set(fieldnames)
    if "model" in cols and "username" in cols and "organization" in cols:
        return CSV_TYPE_AI
    if "product" in cols and "sku" in cols and "unit_type" in cols:
        return CSV_TYPE_USAGE
    return None


def _load_all_csv_records(csv_type: str = CSV_TYPE_AI) -> list[dict]:
    """Load all CSV records from the given type's directory."""
    csv_dir = _get_csv_dir(csv_type)
    if not csv_dir.exists():
        return []
    records: list[dict] = []
    for f in sorted(csv_dir.glob("*.csv")):
        with open(f, encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                records.append(row)
    return records


def _aggregate_user_ai_usage(selected_orgs: list[str], member_filter: MemberFilter | None = None) -> dict:
    """Aggregate per-user AI usage from uploaded CSV files.

    Returns structure with per-user breakdown, daily trend, model breakdown, etc.
    """
    records = _load_all_csv_records()
    if not records:
        return {"has_data": False, "latest_date": None, "users": [], "daily_trend": [],
                "model_breakdown": [], "org_breakdown": [], "total_requests": 0, "total_cost": 0}

    # Filter by selected orgs
    filtered = [r for r in records if r.get("organization", "") in selected_orgs]
    if member_filter is not None:
        filtered = [r for r in filtered if (r.get("username") or "").lower() in member_filter]
    if not filtered:
        return {"has_data": False, "latest_date": None, "users": [], "daily_trend": [],
                "model_breakdown": [], "org_breakdown": [], "total_requests": 0, "total_cost": 0}

    latest_date = max(r.get("date", "") for r in filtered)

    # Per-user aggregation
    user_map: dict[str, dict] = defaultdict(lambda: {
        "requests": 0, "gross_amount": 0.0, "net_amount": 0.0,
        "models": defaultdict(float), "days_active": set(), "org": "",
        "quota": 0, "cost_center": "",
    })
    for r in filtered:
        user = r.get("username", "")
        qty = float(r.get("quantity", 0))
        gross = float(r.get("gross_amount", 0))
        net = float(r.get("net_amount", 0))
        model = r.get("model", "unknown")
        u = user_map[user]
        u["requests"] += qty
        u["gross_amount"] += gross
        u["net_amount"] += net
        u["models"][model] += qty
        u["days_active"].add(r.get("date", ""))
        u["org"] = r.get("organization", "")
        u["cost_center"] = r.get("cost_center_name", "") or ""
        try:
            u["quota"] = int(r.get("total_monthly_quota", 0))
        except (ValueError, TypeError):
            pass

    users = []
    for username, info in sorted(user_map.items(), key=lambda x: -x[1]["requests"]):
        models = [{"model": m, "requests": q} for m, q in sorted(info["models"].items(), key=lambda x: -x[1])]
        users.append({
            "user": username,
            "org": info["org"],
            "cost_center": info["cost_center"],
            "requests": round(info["requests"], 2),
            "gross_amount": round(info["gross_amount"], 4),
            "net_amount": round(info["net_amount"], 4),
            "days_active": len(info["days_active"]),
            "quota": info["quota"],
            "usage_pct": round(info["requests"] / info["quota"] * 100, 1) if info["quota"] > 0 else 0,
            "models": models,
        })

    # Daily trend
    day_map: dict[str, dict] = defaultdict(lambda: {"requests": 0, "amount": 0.0, "users": set()})
    for r in filtered:
        day = r.get("date", "")
        qty = float(r.get("quantity", 0))
        gross = float(r.get("gross_amount", 0))
        dm = day_map[day]
        dm["requests"] += qty
        dm["amount"] += gross
        dm["users"].add(r.get("username", ""))

    daily_trend = [
        {"day": d, "requests": round(v["requests"], 2), "amount": round(v["amount"], 4), "active_users": len(v["users"])}
        for d, v in sorted(day_map.items())
    ]

    # Model breakdown
    model_map: dict[str, dict] = defaultdict(lambda: {"requests": 0, "amount": 0.0, "users": set()})
    for r in filtered:
        model = r.get("model", "unknown")
        mm = model_map[model]
        mm["requests"] += float(r.get("quantity", 0))
        mm["amount"] += float(r.get("gross_amount", 0))
        mm["users"].add(r.get("username", ""))

    model_breakdown = [
        {"model": m, "requests": round(v["requests"], 2), "amount": round(v["amount"], 4), "user_count": len(v["users"])}
        for m, v in sorted(model_map.items(), key=lambda x: -x[1]["requests"])
    ]

    # Org breakdown
    org_map: dict[str, dict] = defaultdict(lambda: {"requests": 0, "amount": 0.0, "users": set()})
    for r in filtered:
        org = r.get("organization", "")
        om = org_map[org]
        om["requests"] += float(r.get("quantity", 0))
        om["amount"] += float(r.get("gross_amount", 0))
        om["users"].add(r.get("username", ""))

    org_breakdown = [
        {"org": o, "requests": round(v["requests"], 2), "amount": round(v["amount"], 4), "user_count": len(v["users"])}
        for o, v in sorted(org_map.items(), key=lambda x: -x[1]["requests"])
    ]

    # Cost center breakdown
    cc_map: dict[str, dict] = defaultdict(lambda: {"requests": 0, "amount": 0.0, "users": set()})
    for r in filtered:
        cc = r.get("cost_center_name", "") or "Unknown"
        cm = cc_map[cc]
        cm["requests"] += float(r.get("quantity", 0))
        cm["amount"] += float(r.get("gross_amount", 0))
        cm["users"].add(r.get("username", ""))

    cost_center_breakdown = [
        {"cost_center": cc, "requests": round(v["requests"], 2), "amount": round(v["amount"], 4), "user_count": len(v["users"])}
        for cc, v in sorted(cc_map.items(), key=lambda x: -x[1]["requests"])
    ]

    total_requests = sum(u["requests"] for u in users)
    total_cost = sum(u["gross_amount"] for u in users)

    return {
        "has_data": True,
        "latest_date": latest_date,
        "users": users,
        "daily_trend": daily_trend,
        "model_breakdown": model_breakdown,
        "org_breakdown": org_breakdown,
        "cost_center_breakdown": cost_center_breakdown,
        "total_requests": round(total_requests, 2),
        "total_cost": round(total_cost, 4),
    }


# ---------------------------------------------------------------------------
# CSV upload endpoints
# ---------------------------------------------------------------------------

@router.post("/data/upload-csv")
async def upload_csv(file: UploadFile = File(...)):
    """Upload a CSV file – either an AI usage CSV or a usage report CSV.

    The type is auto-detected from the column headers. The file is validated,
    deduplicated against existing data, and saved.
    """
    if not file.filename or not file.filename.endswith(".csv"):
        return {"error": "Only CSV files are accepted."}

    content = await file.read()
    text = content.decode("utf-8-sig")  # handle BOM

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return {"error": "CSV file has no headers."}

    csv_type = _detect_csv_type(list(reader.fieldnames))
    if csv_type is None:
        return {"error": "Unrecognised CSV format. Expected an AI usage CSV (with a 'model' column) "
                         "or a usage report CSV (with 'product' and 'sku' columns)."}

    rows = list(reader)
    if not rows:
        return {"error": "CSV file is empty."}

    dates = [r.get("date", "") for r in rows if r.get("date")]
    date_min = min(dates) if dates else "unknown"
    date_max = max(dates) if dates else "unknown"

    csv_dir = _get_csv_dir(csv_type)
    csv_dir.mkdir(parents=True, exist_ok=True)

    # Build deduplication key per type
    def _key(row: dict) -> str:
        if csv_type == CSV_TYPE_AI:
            return f"{row.get('date')}|{row.get('username')}|{row.get('model')}|{row.get('organization')}"
        return f"{row.get('date')}|{row.get('username')}|{row.get('sku')}|{row.get('organization')}"

    existing_keys: set[str] = set()
    for f in csv_dir.glob("*.csv"):
        with open(f, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                existing_keys.add(_key(row))

    new_rows = [row for row in rows if _key(row) not in existing_keys]

    if not new_rows:
        return {
            "status": "no_new_data",
            "csv_type": csv_type,
            "date_range": {"start": date_min, "end": date_max},
            "total_rows": len(rows),
            "new_rows": 0,
        }

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    prefix = "ai_usage" if csv_type == CSV_TYPE_AI else "usage_report"
    out_path = csv_dir / f"{prefix}_{ts}.csv"
    fieldnames = list(reader.fieldnames)
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(new_rows)

    return {
        "status": "ok",
        "csv_type": csv_type,
        "date_range": {"start": date_min, "end": date_max},
        "total_rows": len(rows),
        "new_rows": len(new_rows),
        "duplicates_skipped": len(rows) - len(new_rows),
        "file_saved": out_path.name,
    }


@router.get("/data/csv-info")
async def get_csv_info():
    """Get info about all uploaded CSV data (both AI usage and usage report)."""
    def _scan(csv_type: str) -> dict:
        csv_dir = _get_csv_dir(csv_type)
        csv_files = sorted(csv_dir.glob("*.csv")) if csv_dir.exists() else []
        total_records = 0
        all_dates: list[str] = []
        all_orgs: set[str] = set()
        all_users: set[str] = set()
        for f in csv_files:
            with open(f, encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    total_records += 1
                    d = row.get("date", "")
                    if d:
                        all_dates.append(d)
                    if row.get("organization"):
                        all_orgs.add(row["organization"])
                    if row.get("username"):
                        all_users.add(row["username"])
        return {
            "has_data": total_records > 0,
            "latest_date": max(all_dates) if all_dates else None,
            "earliest_date": min(all_dates) if all_dates else None,
            "file_count": len(csv_files),
            "total_records": total_records,
            "orgs": sorted(all_orgs),
            "user_count": len(all_users),
        }

    return {
        "ai_usage": _scan(CSV_TYPE_AI),
        "usage_report": _scan(CSV_TYPE_USAGE),
    }


# ---------------------------------------------------------------------------
# Cost center user assignment endpoints
# ---------------------------------------------------------------------------

def _load_enterprise_list() -> list[dict]:
    enterprise_list = data_collector.load_latest("enterprise", "all") or []
    return enterprise_list if isinstance(enterprise_list, list) else []


def _resolve_enterprise(enterprise: str = "") -> tuple[str, dict | None, list[dict]]:
    enterprise_list = _load_enterprise_list()
    if not enterprise_list:
        enterprise_list = api_manager.get_all_enterprises()

    if not enterprise_list:
        return "", None, []

    selected_slug = enterprise if any(e.get("slug") == enterprise for e in enterprise_list) else enterprise_list[0].get("slug", "")
    selected = next((e for e in enterprise_list if e.get("slug") == selected_slug), None)
    return selected_slug, selected, enterprise_list


async def _get_enterprise_org_logins(enterprise_slug: str, enterprise_info: dict | None) -> list[str]:
    api = api_manager.get_api_for_enterprise(enterprise_slug)
    orgs: list[str] = []

    if api:
        live_orgs = await api.get_enterprise_orgs(enterprise_slug)
        orgs = [o.get("login", "") for o in live_orgs if o.get("login")]

    if not orgs:
        pat_id = (enterprise_info or {}).get("pat_id")
        discovered = api_manager.get_all_orgs()
        if pat_id:
            orgs = [o.get("login", "") for o in discovered if o.get("pat_id") == pat_id and o.get("login")]
        elif len(_load_enterprise_list()) <= 1:
            orgs = [o.get("login", "") for o in discovered if o.get("login")]

    # Enterprise with no organizations (Copilot granted via enterprise teams):
    # fall back to the pseudo-org key its seats/usage data was synced under,
    # regardless of how many other enterprises are configured.
    if not orgs and any(e.get("slug") == enterprise_slug for e in api_manager.get_enterprise_pseudo_orgs()):
        orgs = [enterprise_pseudo_org(enterprise_slug)]

    if not orgs and len(_load_enterprise_list()) <= 1:
        orgs = list(data_collector.load_all_latest("seats").keys())

    return sorted(set(orgs), key=str.lower)


def _active_cost_centers(cc_data: dict | None) -> list[dict]:
    if not cc_data:
        return []
    return [cc for cc in cc_data.get("cost_centers", []) if cc.get("state", "active") == "active"]


def _append_audit_log(entry: dict):
    log_file = data_collector.data_dir / "audit_log.json"
    logs = []
    if log_file.exists():
        try:
            logs = json.loads(log_file.read_text(encoding="utf-8"))
        except Exception:
            logs = []
    logs.append(entry)
    log_file.write_text(json.dumps(logs, indent=2, default=str), encoding="utf-8")


@router.get("/data/cost-center-unassigned-users")
async def get_cost_center_unassigned_users(
    enterprise: str = Query(default=""),
    search: str = Query(default=""),
):
    """List Copilot seat users in an enterprise who are not in an active cost center."""
    selected_slug, selected_enterprise, enterprise_list = _resolve_enterprise(enterprise)
    empty = {
        "enterprises": enterprise_list,
        "selected_enterprise": selected_slug or None,
        "enterprise_name": (selected_enterprise or {}).get("name", selected_slug),
        "cost_centers": [],
        "unassigned_users": [],
        "total_unassigned": 0,
        "total_copilot_users": 0,
        "assigned_user_count": 0,
        "orgs": [],
        "no_data": True,
    }
    if not selected_slug:
        return empty

    cc_data = data_collector.load_latest("cost_centers", selected_slug)
    active_ccs = _active_cost_centers(cc_data)
    if not cc_data:
        return empty

    assigned_logins = {
        m.get("login", "").lower()
        for cc in active_ccs
        for m in cc.get("members", [])
        if m.get("login")
    }

    org_logins = await _get_enterprise_org_logins(selected_slug, selected_enterprise)
    seat_users: dict[str, dict] = {}

    for org in org_logins:
        seats_data = data_collector.load_latest("seats", org)
        if not seats_data:
            continue
        for seat in seats_data.get("seats", []):
            assignee = seat.get("assignee") or {}
            login = assignee.get("login", "")
            if not login:
                continue
            key = login.lower()
            entry = seat_users.setdefault(key, {
                "login": login,
                "avatar_url": assignee.get("avatar_url", ""),
                "html_url": assignee.get("html_url", f"https://github.com/{login}"),
                "orgs": [],
                "teams": [],
                "plan_types": [],
                "last_activity_at": seat.get("last_activity_at") or "",
                "last_activity_editor": seat.get("last_activity_editor") or "",
                "seat_count": 0,
            })
            if org not in entry["orgs"]:
                entry["orgs"].append(org)
            team = seat.get("assigning_team") or {}
            team_name = team.get("name") or team.get("slug") or ""
            if team_name and team_name not in entry["teams"]:
                entry["teams"].append(team_name)
            plan_type = seat.get("plan_type") or ""
            if plan_type and plan_type not in entry["plan_types"]:
                entry["plan_types"].append(plan_type)
            last_activity = seat.get("last_activity_at") or ""
            if last_activity and (not entry["last_activity_at"] or last_activity > entry["last_activity_at"]):
                entry["last_activity_at"] = last_activity
                entry["last_activity_editor"] = seat.get("last_activity_editor") or ""
            entry["seat_count"] += 1

    unassigned = [u for key, u in seat_users.items() if key not in assigned_logins]
    search_lower = search.strip().lower()
    if search_lower:
        unassigned = [
            u for u in unassigned
            if search_lower in u["login"].lower()
            or any(search_lower in org.lower() for org in u["orgs"])
            or any(search_lower in team.lower() for team in u["teams"])
        ]

    for user in unassigned:
        user["orgs"].sort(key=str.lower)
        user["teams"].sort(key=str.lower)
        user["plan_types"].sort(key=str.lower)

    cost_centers = [
        {
            "id": cc.get("id", ""),
            "name": cc.get("name", ""),
            "state": cc.get("state", "active"),
            "member_count": cc.get("member_count", 0),
        }
        for cc in active_ccs
        if cc.get("id") and cc.get("name")
    ]

    return {
        "enterprises": enterprise_list,
        "selected_enterprise": selected_slug,
        "enterprise_name": cc_data.get("enterprise_name", selected_slug),
        "cost_centers": sorted(cost_centers, key=lambda c: c["name"].lower()),
        "unassigned_users": sorted(unassigned, key=lambda u: u["login"].lower()),
        "total_unassigned": len(unassigned),
        "total_copilot_users": len(seat_users),
        "assigned_user_count": len({k for k in seat_users.keys() if k in assigned_logins}),
        "orgs": org_logins,
        "no_data": False,
    }


@router.post("/data/cost-center-unassigned-users/assign")
async def assign_cost_center_unassigned_users(request: AssignCostCenterUsersRequest):
    """Assign selected users to an active enterprise cost center via GitHub API."""
    users = sorted({u.strip() for u in request.users if u.strip()}, key=str.lower)
    if not users:
        return {"error": "Select at least one user to assign."}
    if not request.cost_center_id.strip():
        return {"error": "Select a cost center."}

    selected_slug, selected_enterprise, _ = _resolve_enterprise(request.enterprise)
    if not selected_slug or not selected_enterprise:
        return {"error": "No enterprise data found. Run Sync Data first."}

    cc_data = data_collector.load_latest("cost_centers", selected_slug)
    target_cc = next(
        (cc for cc in _active_cost_centers(cc_data) if cc.get("id") == request.cost_center_id),
        None,
    )
    if not target_cc:
        return {"error": f"Active cost center '{request.cost_center_id}' was not found."}

    api = api_manager.get_api_for_enterprise(selected_slug)
    if not api:
        return {"error": f"No API client found for enterprise '{selected_slug}'."}

    try:
        api_result = await api.add_cost_center_resources(selected_slug, request.cost_center_id, users=users)
    except Exception as e:
        return {"error": f"GitHub API assignment failed: {e}"}

    sync_result = await data_collector.sync_cost_centers_for_enterprise(selected_enterprise)
    audit_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": "assign_cost_center_users",
        "enterprise": selected_slug,
        "cost_center_id": request.cost_center_id,
        "cost_center_name": target_cc.get("name", ""),
        "users": users,
        "api_result": api_result,
    }
    _append_audit_log(audit_entry)

    return {
        "status": "ok",
        "enterprise": selected_slug,
        "cost_center": {"id": request.cost_center_id, "name": target_cc.get("name", "")},
        "assigned_users": users,
        "api_result": api_result,
        "sync_result": sync_result,
    }


@router.get("/data/cost-center-report")
async def get_cost_center_report(enterprise: str = Query(default="")):
    """Generate and return a ZIP archive with one HTML report per cost center.

    Each HTML is self-contained (no external deps), includes AI usage
    and usage report analysis filtered to that cost center's members.
    """
    enterprise_list = data_collector.load_latest("enterprise", "all") or []
    if not isinstance(enterprise_list, list):
        enterprise_list = []

    available_slugs = [e["slug"] for e in enterprise_list]
    selected_slug = enterprise if enterprise in available_slugs else (available_slugs[0] if available_slugs else "")

    if not selected_slug:
        return {"error": "No enterprise data found. Run Sync Data first."}

    cc_data = data_collector.load_latest("cost_centers", selected_slug)
    if not cc_data:
        return {"error": f"No cost center data for enterprise '{selected_slug}'. Run Sync Data first."}

    cost_centers    = cc_data.get("cost_centers", [])
    enterprise_name = cc_data.get("enterprise_name", selected_slug)

    all_ai_usage = _load_all_csv_records(CSV_TYPE_AI)
    all_usage   = _load_all_csv_records(CSV_TYPE_USAGE)

    zip_bytes = generate_report_zip(
        enterprise=selected_slug,
        enterprise_name=enterprise_name,
        cost_centers=cost_centers,
        all_ai_usage_records=all_ai_usage,
        all_usage_records=all_usage,
    )

    filename = f"cc-report-{selected_slug}.zip"
    return StreamingResponse(
        io.BytesIO(zip_bytes),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/data/cost-center-dashboard")
async def get_cost_center_dashboard(
    enterprise: str = Query(default=""),
    cost_centers: str = Query(default=""),
    state: str = Query(default="active"),
    search: str = Query(default=""),
):
    """Return cost center dashboard data from synced JSON files.

    Supports filtering by enterprise slug, cost center names (comma-separated),
    state ('active'|'archived'|'all'), and user login search.
    """
    # Collect available enterprises from saved data
    enterprise_list = data_collector.load_latest("enterprise", "all") or []
    if not isinstance(enterprise_list, list):
        enterprise_list = []

    if not enterprise_list:
        return {
            "enterprises": [],
            "selected_enterprise": None,
            "cost_centers": [],
            "total_cost_centers": 0,
            "total_unique_members": 0,
            "user_map": [],
            "no_data": True,
        }

    # Choose which enterprise to show
    available_slugs = [e["slug"] for e in enterprise_list]
    selected_slug = enterprise if enterprise in available_slugs else available_slugs[0]

    cc_data = data_collector.load_latest("cost_centers", selected_slug)
    if not cc_data:
        return {
            "enterprises": enterprise_list,
            "selected_enterprise": selected_slug,
            "cost_centers": [],
            "total_cost_centers": 0,
            "total_unique_members": 0,
            "user_map": [],
            "no_data": True,
        }

    all_ccs: list[dict] = cc_data.get("cost_centers", [])

    # Apply state filter
    if state != "all":
        all_ccs = [cc for cc in all_ccs if cc.get("state", "active") == state]

    # Apply cost center name filter
    cc_filter = [n.strip() for n in cost_centers.split(",") if n.strip()] if cost_centers.strip() else []
    if cc_filter:
        all_ccs = [cc for cc in all_ccs if cc.get("name") in cc_filter]

    # Apply member search filter
    search_lower = search.strip().lower()
    if search_lower:
        filtered = []
        for cc in all_ccs:
            matched_members = [
                m for m in cc.get("members", [])
                if search_lower in m.get("login", "").lower()
            ]
            if matched_members:
                filtered.append({**cc, "members": matched_members, "member_count": len(matched_members)})
        all_ccs = filtered

    # Build user → cost_centers reverse map
    user_cc_map: dict[str, dict] = {}
    for cc in all_ccs:
        for member in cc.get("members", []):
            login = member["login"]
            if login not in user_cc_map:
                user_cc_map[login] = {
                    "login": login,
                    "avatar_url": member.get("avatar_url", ""),
                    "html_url": member.get("html_url", ""),
                    "cost_centers": [],
                }
            user_cc_map[login]["cost_centers"].append({
                "name": cc["name"],
                "id": cc.get("id", ""),
                "source_type": member.get("source_type", ""),
                "source_name": member.get("source_name", ""),
            })

    user_map = sorted(user_cc_map.values(), key=lambda u: u["login"].lower())

    return {
        "enterprises": enterprise_list,
        "selected_enterprise": selected_slug,
        "enterprise_name": cc_data.get("enterprise_name", selected_slug),
        "cost_centers": all_ccs,
        "total_cost_centers": len(all_ccs),
        "total_unique_members": len(user_map),
        "user_map": user_map,
        "no_data": False,
    }


# ---------------------------------------------------------------------------
# Enterprise teams dashboard
# ---------------------------------------------------------------------------

def _aggregate_seats_by_login(org_logins: list[str]) -> dict[str, dict]:
    """Build a `login (lowercase) -> seat summary` map across the given orgs."""
    seat_users: dict[str, dict] = {}
    for org in org_logins:
        seats_data = data_collector.load_latest("seats", org)
        if not seats_data:
            continue
        for seat in seats_data.get("seats", []):
            assignee = seat.get("assignee") or {}
            login = assignee.get("login", "")
            if not login:
                continue
            entry = seat_users.setdefault(login.lower(), {
                "login": login,
                "avatar_url": assignee.get("avatar_url", ""),
                "html_url": assignee.get("html_url", f"https://github.com/{login}"),
                "orgs": [],
                "assigning_teams": [],
                "plan_types": [],
                "last_activity_at": "",
                "last_activity_editor": "",
                "seat_count": 0,
            })
            if org not in entry["orgs"]:
                entry["orgs"].append(org)
            team = seat.get("assigning_team") or {}
            team_label = team.get("name") or team.get("slug") or ""
            if team_label:
                # Enterprise-team-granted seats are the only place GitHub itself
                # reports enterprise team attribution.
                scope = "enterprise" if team.get("type") == "enterprise" else "organization"
                tag = {"name": team_label, "scope": scope}
                if tag not in entry["assigning_teams"]:
                    entry["assigning_teams"].append(tag)
            plan_type = seat.get("plan_type") or ""
            if plan_type and plan_type not in entry["plan_types"]:
                entry["plan_types"].append(plan_type)
            last_activity = seat.get("last_activity_at") or ""
            if last_activity and last_activity > entry["last_activity_at"]:
                entry["last_activity_at"] = last_activity
                entry["last_activity_editor"] = seat.get("last_activity_editor") or ""
            entry["seat_count"] += 1
    return seat_users


def _aggregate_usage_users_by_login(org_logins: list[str]) -> dict[str, dict]:
    """Build a `login (lowercase) -> usage metrics` map from cached usage reports."""
    usage: dict[str, dict] = {}
    for org in org_logins:
        report = data_collector.load_latest("usage_users", org)
        if not isinstance(report, dict):
            continue
        for rec in report.get("records", []) or []:
            login = rec.get("user_login") or ""
            if not login:
                continue
            entry = usage.setdefault(login.lower(), {
                "interactions": 0,
                "code_generations": 0,
                "code_acceptances": 0,
                "loc_added": 0,
                "active_days": set(),
                "last_active_day": "",
            })
            interactions = int(rec.get("user_initiated_interaction_count") or 0)
            entry["interactions"] += interactions
            entry["code_generations"] += int(rec.get("code_generation_activity_count") or 0)
            entry["code_acceptances"] += int(rec.get("code_acceptance_activity_count") or 0)
            entry["loc_added"] += int(rec.get("loc_added_sum") or 0)
            day = rec.get("day") or ""
            if day and interactions > 0:
                entry["active_days"].add(day)
                if day > entry["last_active_day"]:
                    entry["last_active_day"] = day
    for entry in usage.values():
        entry["active_days"] = len(entry["active_days"])
    return usage


def _aggregate_ai_cost_by_login(org_logins: list[str]) -> dict[str, dict]:
    """Build a `login (lowercase) -> AI credit spend` map from uploaded AI usage CSVs."""
    org_set = {o.lower() for o in org_logins}
    result: dict[str, dict] = {}
    for r in _load_all_csv_records(CSV_TYPE_AI):
        username = r.get("username", "")
        if not username:
            continue
        org = (r.get("organization") or "").lower()
        # Records without an organization belong to enterprise-level usage and
        # cannot be attributed to a specific org, so they are always included.
        if org and org_set and org not in org_set:
            continue
        entry = result.setdefault(username.lower(), {
            "requests": 0.0,
            "gross_amount": 0.0,
            "net_amount": 0.0,
            "cost_centers": [],
        })
        try:
            entry["requests"] += float(r.get("quantity") or 0)
            entry["gross_amount"] += float(r.get("gross_amount") or 0)
            entry["net_amount"] += float(r.get("net_amount") or 0)
        except (TypeError, ValueError):
            pass
        cc = r.get("cost_center_name") or ""
        if cc and cc not in entry["cost_centers"]:
            entry["cost_centers"].append(cc)
    return result


@router.get("/data/enterprise-teams-dashboard")
async def get_enterprise_teams_dashboard(
    enterprise: str = Query(default=""),
    teams: str = Query(default="", description="Comma-separated enterprise team slugs"),
    search: str = Query(default="", description="Filter members by login"),
):
    """Enterprise teams dashboard: team roster joined with seat, usage and AI spend data.

    No Copilot dataset carries an enterprise-team field, so team attribution is
    resolved by joining the synced team rosters against every other dataset on
    the user login.
    """
    selected_slug, selected_enterprise, enterprise_list = _resolve_enterprise(enterprise)
    empty = {
        "enterprises": enterprise_list,
        "selected_enterprise": selected_slug or None,
        "enterprise_name": (selected_enterprise or {}).get("name", selected_slug),
        "teams": [],
        "all_teams": [],
        "orgs": [],
        "totals": {},
        "unassigned_seat_users": [],
        "ai_usage_available": False,
        "no_data": True,
    }
    if not selected_slug:
        return empty

    team_data = data_collector.load_latest("enterprise_teams", selected_slug)
    if not isinstance(team_data, dict):
        return empty

    all_teams: list[dict] = team_data.get("teams", []) or []
    org_logins = await _get_enterprise_org_logins(selected_slug, selected_enterprise)
    seat_map = _aggregate_seats_by_login(org_logins)
    usage_map = _aggregate_usage_users_by_login(org_logins)
    ai_map = _aggregate_ai_cost_by_login(org_logins)

    price_per_seat = COPILOT_PRICING.get("business", 19.0)

    def build_member(login: str, avatar_url: str, html_url: str) -> dict:
        key = login.lower()
        seat = seat_map.get(key)
        usage = usage_map.get(key, {})
        ai = ai_map.get(key, {})
        return {
            "login": login,
            "avatar_url": avatar_url or (seat or {}).get("avatar_url", ""),
            "html_url": html_url or f"https://github.com/{login}",
            "has_seat": seat is not None,
            "orgs": (seat or {}).get("orgs", []),
            "plan_types": (seat or {}).get("plan_types", []),
            "assigning_teams": (seat or {}).get("assigning_teams", []),
            "last_activity_at": (seat or {}).get("last_activity_at", ""),
            "last_activity_editor": (seat or {}).get("last_activity_editor", ""),
            "interactions": usage.get("interactions", 0),
            "code_acceptances": usage.get("code_acceptances", 0),
            "loc_added": usage.get("loc_added", 0),
            "active_days": usage.get("active_days", 0),
            "last_active_day": usage.get("last_active_day", ""),
            "ai_requests": round(ai.get("requests", 0.0), 2),
            "ai_net_amount": round(ai.get("net_amount", 0.0), 4),
            "cost_centers": ai.get("cost_centers", []),
        }

    team_filter = {s.strip() for s in teams.split(",") if s.strip()}
    search_lower = search.strip().lower()

    result_teams: list[dict] = []
    for team in all_teams:
        if team_filter and team.get("slug") not in team_filter:
            continue
        members = [
            build_member(m.get("login", ""), m.get("avatar_url", ""), m.get("html_url", ""))
            for m in team.get("members", []) or []
            if m.get("login")
        ]
        if search_lower:
            members = [m for m in members if search_lower in m["login"].lower()]
            if not members:
                continue
        seat_members = [m for m in members if m["has_seat"]]
        result_teams.append({
            "id": team.get("id"),
            "slug": team.get("slug", ""),
            "name": team.get("name", ""),
            "description": team.get("description", ""),
            "html_url": team.get("html_url", ""),
            "group_name": team.get("group_name") or "",
            "organization_selection_type": team.get("organization_selection_type", ""),
            "organizations": team.get("organizations", []),
            "members": sorted(members, key=lambda m: m["login"].lower()),
            "member_count": len(members),
            "seat_count": len(seat_members),
            "no_seat_count": len(members) - len(seat_members),
            "active_member_count": sum(1 for m in members if m["interactions"] > 0),
            "interactions": sum(m["interactions"] for m in members),
            "loc_added": sum(m["loc_added"] for m in members),
            "ai_requests": round(sum(m["ai_requests"] for m in members), 2),
            "ai_net_amount": round(sum(m["ai_net_amount"] for m in members), 4),
            "seat_cost": round(len(seat_members) * price_per_seat, 2),
        })

    result_teams.sort(key=lambda t: (-t["member_count"], t["name"].lower()))

    # Seat holders that no enterprise team covers — the blind spot when using
    # enterprise teams as the primary reporting dimension.
    assigned_logins = {
        m.get("login", "").lower()
        for team in all_teams
        for m in team.get("members", []) or []
        if m.get("login")
    }
    unassigned = [
        build_member(seat["login"], seat.get("avatar_url", ""), seat.get("html_url", ""))
        for key, seat in seat_map.items()
        if key not in assigned_logins
    ]
    if search_lower:
        unassigned = [u for u in unassigned if search_lower in u["login"].lower()]
    unassigned.sort(key=lambda u: u["login"].lower())

    # Team members that hold no Copilot seat at all (includes unaffiliated
    # enterprise users, who never appear in any org's seat data).
    members_without_seat = sum(1 for key in assigned_logins if key not in seat_map)

    totals = {
        "total_teams": len(all_teams),
        "shown_teams": len(result_teams),
        "total_unique_members": len(assigned_logins),
        "members_with_seat": len(assigned_logins & set(seat_map.keys())),
        "members_without_seat": members_without_seat,
        "total_seat_users": len(seat_map),
        "unassigned_seat_users": len(unassigned),
        "coverage_pct": round(len(assigned_logins & set(seat_map.keys())) / len(seat_map) * 100, 1) if seat_map else 0.0,
        "ai_net_amount": round(sum(t["ai_net_amount"] for t in result_teams), 4),
        "seat_cost": round(sum(t["seat_cost"] for t in result_teams), 2),
        "price_per_seat": price_per_seat,
    }

    return {
        "enterprises": enterprise_list,
        "selected_enterprise": selected_slug,
        "enterprise_name": team_data.get("enterprise_name", selected_slug),
        "teams": result_teams,
        "all_teams": [{"slug": t.get("slug", ""), "name": t.get("name", "")} for t in all_teams],
        "orgs": org_logins,
        "totals": totals,
        "unassigned_seat_users": unassigned,
        "ai_usage_available": bool(ai_map),
        "no_data": not all_teams,
    }


@router.get("/data/budgets-dashboard")
async def get_budgets_dashboard(
    enterprise: str = Query(default=""),
    scope: str = Query(default="all"),
    search: str = Query(default=""),
    live: bool = Query(default=False, description="Fetch budgets straight from the GitHub API"),
    period: str = Query(default="all", description="all | current_month"),
):
    """Return budgets dashboard data from synced JSON files.

    Supports filtering by enterprise slug, budget scope, and a text search over
    the budget entity name / SKU / scope.
    """
    enterprise_list = data_collector.load_latest("enterprise", "all") or []
    if not isinstance(enterprise_list, list):
        enterprise_list = []

    empty = {
        "enterprises": enterprise_list,
        "selected_enterprise": None,
        "enterprise_name": "",
        "budgets": [],
        "total_budgets": 0,
        "total_amount": 0,
        "hard_limit_count": 0,
        "alerting_count": 0,
        "scope_breakdown": [],
        "scopes": [],
        "total_consumed": 0,
        "total_remaining": 0,
        "tracked_budgets": 0,
        "live": False,
        "no_data": True,
    }

    if not enterprise_list:
        return empty

    available_slugs = [e["slug"] for e in enterprise_list]
    selected_slug = enterprise if enterprise in available_slugs else available_slugs[0]

    budgets_data = data_collector.load_latest("budgets", selected_slug)
    raw_budgets: list[dict] = (budgets_data or {}).get("budgets", []) or []

    # Live mode goes straight to GitHub so consumed amounts reflect the running
    # billing cycle instead of whatever the last sync captured.
    live_fetched = False
    if live:
        fresh = await fetch_budgets("enterprise", selected_slug)
        if fresh:
            raw_budgets = fresh
            live_fetched = True

    if not raw_budgets:
        return {**empty, "selected_enterprise": selected_slug}

    # Normalize each budget to a stable shape for the frontend
    def _normalize(b: dict) -> dict:
        skus = b.get("budget_product_skus")
        if not skus:
            single = b.get("budget_product_sku")
            skus = [single] if single else []
        alerting = b.get("budget_alerting") or {}
        amount = float(b.get("budget_amount", 0) or 0)
        consumed_raw = b.get("consumed_amount")
        consumed = float(consumed_raw) if consumed_raw is not None else None
        return {
            "id": b.get("id", ""),
            "budget_type": b.get("budget_type", ""),
            "scope": b.get("budget_scope", ""),
            "entity_name": b.get("budget_entity_name", "") or "",
            "skus": [s for s in skus if s],
            "amount": amount,
            "consumed_amount": round(consumed, 4) if consumed is not None else None,
            "remaining_amount": round(amount - consumed, 4) if consumed is not None else None,
            "usage_pct": round(consumed / amount * 100, 1) if consumed is not None and amount > 0 else None,
            "prevent_further_usage": bool(b.get("prevent_further_usage", False)),
            "will_alert": bool(alerting.get("will_alert", False)),
            "alert_recipients": alerting.get("alert_recipients", []) or [],
        }

    budgets = [_normalize(b) for b in raw_budgets]

    # All available scopes (before filtering) for the scope selector
    all_scopes = sorted({b["scope"] for b in budgets if b["scope"]})

    # Apply scope filter
    if scope and scope != "all":
        budgets = [b for b in budgets if b["scope"] == scope]

    # Apply text search over entity name, scope, type, and SKUs
    search_lower = search.strip().lower()
    if search_lower:
        def _matches(b: dict) -> bool:
            haystack = " ".join([
                b["entity_name"], b["scope"], b["budget_type"],
                " ".join(b["skus"]),
            ]).lower()
            return search_lower in haystack
        budgets = [b for b in budgets if _matches(b)]

    # Scope breakdown
    scope_map: dict[str, dict] = defaultdict(lambda: {"count": 0, "amount": 0.0})
    for b in budgets:
        sm = scope_map[b["scope"] or "unknown"]
        sm["count"] += 1
        sm["amount"] += float(b["amount"] or 0)
    scope_breakdown = [
        {"scope": s, "count": v["count"], "amount": round(v["amount"], 2)}
        for s, v in sorted(scope_map.items(), key=lambda x: -x[1]["amount"])
    ]

    total_amount = round(sum(float(b["amount"] or 0) for b in budgets), 2)
    hard_limit_count = sum(1 for b in budgets if b["prevent_further_usage"])
    alerting_count = sum(1 for b in budgets if b["will_alert"])
    total_consumed = round(
        sum(float(b["consumed_amount"] or 0) for b in budgets if b["consumed_amount"] is not None), 4
    )
    tracked = [b for b in budgets if b["consumed_amount"] is not None and b["amount"]]
    total_remaining = round(sum(float(b["remaining_amount"] or 0) for b in tracked), 4)
    month_start, month_end = current_month_range()

    return {
        "enterprises": enterprise_list,
        "selected_enterprise": selected_slug,
        "enterprise_name": (budgets_data or {}).get("enterprise_name", selected_slug),
        "live": live_fetched,
        "period": period,
        "current_month": {"start": month_start, "end": month_end},
        "total_consumed": total_consumed,
        "total_remaining": total_remaining,
        "tracked_budgets": len(tracked),
        "budgets": budgets,
        "total_budgets": len(budgets),
        "total_amount": total_amount,
        "hard_limit_count": hard_limit_count,
        "alerting_count": alerting_count,
        "scope_breakdown": scope_breakdown,
        "scopes": all_scopes,
        "no_data": False,
    }
