"""
Data query router - provides read access to collected data.
Supports enterprise grouping for org display.
"""

from collections import defaultdict

from fastapi import APIRouter, Query

from ..services.api_manager import api_manager
from ..services.data_collector import data_collector

router = APIRouter(tags=["data"])


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
    """Get a quick overview across all organizations."""
    all_orgs = api_manager.get_all_orgs()
    total_seats = 0
    total_active = 0
    total_cost = 0.0
    total_waste = 0.0
    orgs_with_copilot = 0

    for org_info in all_orgs:
        org_name = org_info["login"]
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


@router.get("/data/dashboard")
async def get_dashboard(orgs: str = Query(default="")):
    """Aggregated dashboard data for visualization.

    Query param ``orgs`` is a comma-separated list of org logins to include.
    Empty means all orgs with Copilot billing data.
    """
    all_orgs = api_manager.get_all_orgs()
    all_org_names = [o["login"] for o in all_orgs]
    selected = [o.strip() for o in orgs.split(",") if o.strip()] if orgs.strip() else all_org_names

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

    # --- Aggregate usage data ---
    daily_map: dict[str, dict] = {}  # day -> aggregated
    feature_map: dict[str, dict] = defaultdict(lambda: {"interactions": 0, "code_gen": 0, "code_accept": 0})
    model_map: dict[str, dict] = defaultdict(lambda: {"interactions": 0, "code_gen": 0})
    ide_map: dict[str, dict] = defaultdict(lambda: {"interactions": 0, "code_gen": 0})
    date_start = ""
    date_end = ""

    for org_name in selected:
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
                    daily_map[day] = {"day": day, "dau": 0, "wau": 0, "mau": 0, "interactions": 0}
                daily_map[day]["dau"] += dt.get("daily_active_users", 0)
                daily_map[day]["wau"] += dt.get("weekly_active_users", 0)
                daily_map[day]["mau"] += dt.get("monthly_active_users", 0)
                daily_map[day]["interactions"] += dt.get("user_initiated_interaction_count", 0)

                for fb in dt.get("totals_by_feature", []):
                    f = fb.get("feature", "unknown")
                    feature_map[f]["interactions"] += fb.get("user_initiated_interaction_count", 0)
                    feature_map[f]["code_gen"] += fb.get("code_generation_activity_count", 0)
                    feature_map[f]["code_accept"] += fb.get("code_acceptance_activity_count", 0)

                for mb in dt.get("totals_by_model_feature", []):
                    m = mb.get("model", "unknown")
                    model_map[m]["interactions"] += mb.get("user_initiated_interaction_count", 0)
                    model_map[m]["code_gen"] += mb.get("code_generation_activity_count", 0)

                for ib in dt.get("totals_by_ide", []):
                    ide = ib.get("ide", "unknown")
                    ide_map[ide]["interactions"] += ib.get("user_initiated_interaction_count", 0)
                    ide_map[ide]["code_gen"] += ib.get("code_generation_activity_count", 0)

    daily_trend = sorted(daily_map.values(), key=lambda x: x["day"])

    feature_usage = [{"feature": k, **v} for k, v in sorted(feature_map.items(), key=lambda x: -x[1]["interactions"])]
    model_usage = [{"model": k, **v} for k, v in sorted(model_map.items(), key=lambda x: -x[1]["interactions"])]
    ide_usage = [{"ide": k, **v} for k, v in sorted(ide_map.items(), key=lambda x: -x[1]["interactions"])]

    # --- Merge premium request data into model_usage ---
    pr_map: dict[str, float] = defaultdict(float)
    for org_name in selected:
        pr = data_collector.load_latest("premium_requests", org_name)
        if not pr:
            continue
        for item in pr.get("usageItems", []):
            pr_map[item.get("model", "unknown")] += item.get("grossQuantity", 0)

    for entry in model_usage:
        entry["premium_requests"] = pr_map.pop(entry["model"], 0)
    # Add models that only appear in premium requests
    for m, qty in pr_map.items():
        if qty > 0:
            model_usage.append({"model": m, "interactions": 0, "code_gen": 0, "premium_requests": qty})

    # --- Top users from usage_users ---
    user_agg: dict[str, dict] = defaultdict(lambda: {"interactions": 0, "code_gen": 0, "days_active": 0})
    for org_name in selected:
        uu = data_collector.load_latest("usage_users", org_name)
        if not uu:
            continue
        for rec in uu.get("records", []):
            login = rec.get("user_login", "")
            if not login:
                continue
            user_agg[login]["interactions"] += rec.get("user_initiated_interaction_count", 0)
            user_agg[login]["code_gen"] += rec.get("code_generation_activity_count", 0)
            user_agg[login]["days_active"] += 1

    top_users = sorted(
        [{"user": k, **v} for k, v in user_agg.items()],
        key=lambda x: -x["interactions"],
    )[:20]

    return {
        "kpi": kpi,
        "daily_trend": daily_trend,
        "feature_usage": feature_usage,
        "model_usage": model_usage,
        "ide_usage": ide_usage,
        "top_users": top_users,
        "orgs": all_org_names,
        "date_range": {"start": date_start, "end": date_end},
    }
