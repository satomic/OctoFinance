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

    # --- Premium request detail ---
    pr_detail_map: dict[str, dict] = defaultdict(lambda: {
        "gross_qty": 0, "discount_qty": 0, "net_qty": 0,
        "gross_amount": 0.0, "net_amount": 0.0,
    })
    for org_name in selected:
        pr = data_collector.load_latest("premium_requests", org_name)
        if not pr:
            continue
        for item in pr.get("usageItems", []):
            m = item.get("model", "unknown")
            pr_detail_map[m]["gross_qty"] += item.get("grossQuantity", 0)
            pr_detail_map[m]["discount_qty"] += item.get("discountQuantity", 0)
            pr_detail_map[m]["net_qty"] += item.get("netQuantity", 0)
            pr_detail_map[m]["gross_amount"] += item.get("grossAmount", 0.0)
            pr_detail_map[m]["net_amount"] += item.get("netAmount", 0.0)

    premium_detail = [{"model": k, **v} for k, v in sorted(pr_detail_map.items(), key=lambda x: -x[1]["gross_qty"])]

    # Merge premium totals into model_usage
    for entry in model_usage:
        pd = pr_detail_map.pop(entry["model"], None)
        entry["premium_requests"] = pd["gross_qty"] if pd else 0
    for m, pd in pr_detail_map.items():
        if pd["gross_qty"] > 0:
            model_usage.append({"model": m, "interactions": 0, "code_gen": 0, "code_accept": 0,
                                "loc_suggested": 0, "loc_accepted": 0, "premium_requests": pd["gross_qty"]})

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
        "premium_detail": premium_detail,
        "chat_stats": chat_stats,
        "top_users": top_users,
        "orgs": all_org_names,
        "date_range": {"start": date_start, "end": date_end},
    }
