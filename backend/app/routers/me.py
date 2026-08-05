"""
Personal ("me") data router.

Every endpoint here is scoped to the currently logged-in GitHub user, so a
regular (non-admin) user can see their own Copilot seat, activity, AI credit
consumption and spend — and nothing else.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from ..services.budget_provisioner import current_month_range, get_user_budget_context
from ..services.cost_center_provisioner import list_cost_centers_for_user
from ..services.data_collector import data_collector
from .auth import require_user
from .budget_requests import load_requests_for
from .data import CSV_TYPE_AI, CSV_TYPE_USAGE, _load_all_csv_records

router = APIRouter(prefix="/me", tags=["me"])


def resolve_period(period: str, date_from: str, date_to: str) -> tuple[str, str, str]:
    """Translate the UI period switch into a concrete date window.

    ``current_month`` overrides any explicit range so the toggle always shows
    the live billing cycle, which is what budgets are measured against.
    """
    mode = (period or "all").strip().lower()
    if mode == "current_month":
        start, end = current_month_range()
        return "current_month", start, end
    return "all", date_from, date_to


def _f(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _days_since(iso_ts: str) -> int | None:
    if not iso_ts:
        return None
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0, (datetime.now(timezone.utc) - dt).days)


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def _my_seats(login: str) -> list[dict]:
    """Copilot seats assigned to this user across all synced orgs.

    A user is billed at most one seat per org, so entries are de-duplicated by
    org (GitHub can return both an org-level and a team-level assignment).
    """
    target = login.lower()
    by_org: dict[str, dict] = {}
    seats_dir = data_collector.data_dir / "seats"
    if not seats_dir.exists():
        return []

    for path in sorted(seats_dir.glob("*_latest.json")):
        org = path.name[: -len("_latest.json")]
        data = data_collector.load_latest("seats", org)
        if not data:
            continue
        billing = data_collector.load_latest("billing", org) or {}
        price = _f(billing.get("_detected_price_per_seat")) or 19.0
        plan = billing.get("_detected_plan_type", "unknown")

        for seat in data.get("seats", []):
            assignee = seat.get("assignee") or {}
            if str(assignee.get("login", "")).lower() != target:
                continue
            last_activity = seat.get("last_activity_at") or ""
            assigning_team = seat.get("assigning_team") or {}
            entry = {
                "org": org,
                "plan_type": plan,
                "price_per_seat": price,
                "created_at": seat.get("created_at", ""),
                "last_activity_at": last_activity,
                "last_activity_editor": seat.get("last_activity_editor", ""),
                "days_inactive": _days_since(last_activity),
                "assigning_team": assigning_team.get("name", "") if isinstance(assigning_team, dict) else "",
                "pending_cancellation_date": seat.get("pending_cancellation_date"),
            }
            existing = by_org.get(org)
            if existing is None:
                by_org[org] = entry
            else:
                # Keep the most recent activity and the earliest assignment date
                if entry["last_activity_at"] > existing["last_activity_at"]:
                    existing["last_activity_at"] = entry["last_activity_at"]
                    existing["days_inactive"] = entry["days_inactive"]
                    existing["last_activity_editor"] = entry["last_activity_editor"]
                if entry["created_at"] and (
                    not existing["created_at"] or entry["created_at"] < existing["created_at"]
                ):
                    existing["created_at"] = entry["created_at"]
                if entry["assigning_team"] and not existing["assigning_team"]:
                    existing["assigning_team"] = entry["assigning_team"]

    return [by_org[org] for org in sorted(by_org)]


def _my_activity(login: str, date_from: str = "", date_to: str = "") -> dict:
    """Copilot engagement metrics for this user from the usage report data."""
    target = login.lower()
    usage_dir = data_collector.data_dir / "usage_users"
    daily: dict[str, dict] = defaultdict(
        lambda: {"interactions": 0, "generated": 0, "accepted": 0}
    )
    feature_map: dict[str, dict] = defaultdict(
        lambda: {"interactions": 0, "generated": 0, "accepted": 0}
    )
    language_map: dict[str, dict] = defaultdict(lambda: {"generated": 0, "accepted": 0, "loc_added": 0})
    model_map: dict[str, dict] = defaultdict(lambda: {"generated": 0, "accepted": 0})
    editor_map: dict[str, dict] = defaultdict(lambda: {"interactions": 0, "generated": 0, "accepted": 0})
    orgs: set[str] = set()
    has_data = False

    if usage_dir.exists():
        for path in sorted(usage_dir.glob("*_latest.json")):
            org = path.name[: -len("_latest.json")]
            data = data_collector.load_latest("usage_users", org)
            if not data:
                continue
            for record in data.get("records", []):
                if str(record.get("user_login", "")).lower() != target:
                    continue
                day = record.get("day", "")
                if date_from and day < date_from:
                    continue
                if date_to and day > date_to:
                    continue
                has_data = True
                orgs.add(org)
                d = daily[day]
                d["interactions"] += int(record.get("user_initiated_interaction_count", 0) or 0)
                d["generated"] += int(record.get("code_generation_activity_count", 0) or 0)
                d["accepted"] += int(record.get("code_acceptance_activity_count", 0) or 0)

                for feat in record.get("totals_by_feature", []) or []:
                    fm = feature_map[feat.get("feature", "unknown")]
                    fm["interactions"] += int(feat.get("user_initiated_interaction_count", 0) or 0)
                    fm["generated"] += int(feat.get("code_generation_activity_count", 0) or 0)
                    fm["accepted"] += int(feat.get("code_acceptance_activity_count", 0) or 0)

                for lang in record.get("totals_by_language_feature", []) or []:
                    lm = language_map[lang.get("language", "unknown")]
                    lm["generated"] += int(lang.get("code_generation_activity_count", 0) or 0)
                    lm["accepted"] += int(lang.get("code_acceptance_activity_count", 0) or 0)
                    lm["loc_added"] += int(lang.get("loc_added_sum", 0) or 0)

                for mdl in record.get("totals_by_language_model", []) or []:
                    mm = model_map[mdl.get("model", "unknown")]
                    mm["generated"] += int(mdl.get("code_generation_activity_count", 0) or 0)
                    mm["accepted"] += int(mdl.get("code_acceptance_activity_count", 0) or 0)

                for ide in record.get("totals_by_ide", []) or []:
                    em = editor_map[ide.get("ide", "unknown")]
                    em["interactions"] += int(ide.get("user_initiated_interaction_count", 0) or 0)
                    em["generated"] += int(ide.get("code_generation_activity_count", 0) or 0)
                    em["accepted"] += int(ide.get("code_acceptance_activity_count", 0) or 0)

    daily_trend = [
        {"day": day, **values} for day, values in sorted(daily.items()) if day
    ]
    total_interactions = sum(v["interactions"] for v in daily.values())
    total_generated = sum(v["generated"] for v in daily.values())
    total_accepted = sum(v["accepted"] for v in daily.values())

    def _rank(mapping: dict, key: str) -> list[dict]:
        return [
            {key: name, **values}
            for name, values in sorted(mapping.items(), key=lambda x: -sum(x[1].values()))
        ]

    return {
        "has_data": has_data,
        "orgs": sorted(orgs),
        "kpi": {
            "total_interactions": total_interactions,
            "code_generated": total_generated,
            "code_accepted": total_accepted,
            "acceptance_rate": round(total_accepted / total_generated * 100, 1) if total_generated else 0,
            "active_days": len([d for d, v in daily.items() if d and sum(v.values()) > 0]),
        },
        "daily_trend": daily_trend,
        "feature_breakdown": _rank(feature_map, "feature"),
        "language_breakdown": _rank(language_map, "language"),
        "model_breakdown": _rank(model_map, "model"),
        "editor_breakdown": _rank(editor_map, "ide"),
    }


def _my_ai_usage(login: str, date_from: str, date_to: str) -> dict:
    """AI credit consumption for this user from the uploaded AI usage CSVs."""
    target = login.lower()
    records = [
        r for r in _load_all_csv_records(CSV_TYPE_AI)
        if str(r.get("username", "")).lower() == target
    ]
    if date_from:
        records = [r for r in records if r.get("date", "") >= date_from]
    if date_to:
        records = [r for r in records if r.get("date", "") <= date_to]

    if not records:
        return {"has_data": False, "kpi": {}, "daily_trend": [], "model_breakdown": [], "date_range": {}}

    daily: dict[str, dict] = defaultdict(lambda: {"requests": 0.0, "amount": 0.0})
    models: dict[str, dict] = defaultdict(lambda: {"requests": 0.0, "amount": 0.0})
    quota = 0
    org = ""
    cost_center = ""

    for r in records:
        qty = _f(r.get("quantity"))
        gross = _f(r.get("gross_amount"))
        day = r.get("date", "")
        daily[day]["requests"] += qty
        daily[day]["amount"] += gross
        model = r.get("model", "unknown")
        models[model]["requests"] += qty
        models[model]["amount"] += gross
        org = r.get("organization", "") or org
        cost_center = r.get("cost_center_name", "") or cost_center
        try:
            quota = max(quota, int(_f(r.get("total_monthly_quota"))))
        except (TypeError, ValueError):
            pass

    total_requests = sum(v["requests"] for v in daily.values())
    total_amount = sum(v["amount"] for v in daily.values())
    total_net = sum(_f(r.get("net_amount")) for r in records)
    dates = [r.get("date", "") for r in records if r.get("date")]

    return {
        "has_data": True,
        "org": org,
        "cost_center": cost_center,
        "date_range": {"start": min(dates) if dates else "", "end": max(dates) if dates else ""},
        "kpi": {
            "total_requests": round(total_requests, 2),
            "total_cost": round(total_amount, 4),
            "net_cost": round(total_net, 4),
            "quota": quota,
            "usage_pct": round(total_requests / quota * 100, 1) if quota > 0 else 0,
            "active_days": len([d for d in daily if d]),
            "models_used": len(models),
        },
        "daily_trend": [
            {"day": d, "requests": round(v["requests"], 2), "amount": round(v["amount"], 4)}
            for d, v in sorted(daily.items()) if d
        ],
        "model_breakdown": [
            {"model": m, "requests": round(v["requests"], 2), "amount": round(v["amount"], 4)}
            for m, v in sorted(models.items(), key=lambda x: -x[1]["requests"])
        ],
    }


def _my_spend(login: str, date_from: str, date_to: str) -> dict:
    """Billed spend for this user from the uploaded usage report CSVs."""
    target = login.lower()
    records = [
        r for r in _load_all_csv_records(CSV_TYPE_USAGE)
        if str(r.get("username", "")).lower() == target
    ]
    if date_from:
        records = [r for r in records if r.get("date", "") >= date_from]
    if date_to:
        records = [r for r in records if r.get("date", "") <= date_to]

    if not records:
        return {"has_data": False, "kpi": {}, "daily_trend": [], "sku_breakdown": [], "product_breakdown": []}

    daily: dict[str, dict] = defaultdict(lambda: {"gross": 0.0, "net": 0.0})
    skus: dict[str, dict] = defaultdict(lambda: {"gross": 0.0, "net": 0.0, "quantity": 0.0})
    products: dict[str, dict] = defaultdict(lambda: {"gross": 0.0, "net": 0.0, "quantity": 0.0})

    for r in records:
        day = r.get("date", "")
        gross, net, qty = _f(r.get("gross_amount")), _f(r.get("net_amount")), _f(r.get("quantity"))
        daily[day]["gross"] += gross
        daily[day]["net"] += net
        sm = skus[r.get("sku", "unknown")]
        sm["gross"] += gross
        sm["net"] += net
        sm["quantity"] += qty
        pm = products[r.get("product", "unknown")]
        pm["gross"] += gross
        pm["net"] += net
        pm["quantity"] += qty

    dates = [r.get("date", "") for r in records if r.get("date")]
    return {
        "has_data": True,
        "date_range": {"start": min(dates) if dates else "", "end": max(dates) if dates else ""},
        "kpi": {
            "total_gross": round(sum(v["gross"] for v in daily.values()), 4),
            "total_net": round(sum(v["net"] for v in daily.values()), 4),
            "active_days": len([d for d in daily if d]),
        },
        "daily_trend": [
            {"day": d, "gross_amount": round(v["gross"], 4), "net_amount": round(v["net"], 4)}
            for d, v in sorted(daily.items()) if d
        ],
        "sku_breakdown": [
            {"sku": s, "gross_amount": round(v["gross"], 4), "net_amount": round(v["net"], 4),
             "quantity": round(v["quantity"], 4)}
            for s, v in sorted(skus.items(), key=lambda x: -x[1]["gross"])
        ],
        "product_breakdown": [
            {"product": p, "gross_amount": round(v["gross"], 4), "net_amount": round(v["net"], 4),
             "quantity": round(v["quantity"], 4)}
            for p, v in sorted(products.items(), key=lambda x: -x[1]["gross"])
        ],
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/dashboard")
async def my_dashboard(
    request: Request,
    period: str = Query(default="all", description="all | current_month"),
    date_from: str = Query(default=""),
    date_to: str = Query(default=""),
    live: bool = Query(default=False, description="Fetch budgets straight from the GitHub API"),
):
    """Everything the logged-in user is allowed to see about their own usage.

    ``period=current_month`` narrows every usage figure to the running billing
    cycle, which is the window budgets are actually measured against.
    """
    user = require_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Authentication required"})

    login = user.get("login", "")
    period_mode, range_from, range_to = resolve_period(period, date_from, date_to)

    seats = _my_seats(login)
    activity = _my_activity(login, range_from, range_to)
    ai_usage = _my_ai_usage(login, range_from, range_to)
    spend = _my_spend(login, range_from, range_to)

    # The current-month view drives "how much budget is left", so it always
    # reads budgets straight from GitHub regardless of what the client asked.
    want_live = live or period_mode == "current_month"

    # Real GitHub budgets: individual, universal fallback, and cost centers
    try:
        budget_ctx = await get_user_budget_context(login, live=want_live)
    except Exception as exc:  # noqa: BLE001 - the dashboard must still render
        budget_ctx = {
            "live": False, "personal_budget": None, "universal_budget": None,
            "effective_budget": None, "effective_source": None,
            "cost_centers": [], "entities": [], "error": str(exc),
        }

    budget_requests = sorted(
        load_requests_for(login), key=lambda r: r.get("created_at", ""), reverse=True
    )

    seat_cost = round(sum(_f(s.get("price_per_seat")) for s in seats), 2)
    ai_cost = round(float(ai_usage.get("kpi", {}).get("total_cost", 0) or 0), 4)
    total_spend = round(seat_cost + ai_cost, 4)

    effective = budget_ctx.get("effective_budget") or {}
    budget_amount = _f(effective.get("amount")) if effective else 0.0
    consumed = effective.get("consumed_amount")
    # GitHub reports consumed_amount only for individual budgets; fall back to
    # the AI credit spend we computed for the selected period.
    consumed_value = _f(consumed) if consumed is not None else ai_cost
    remaining = round(budget_amount - consumed_value, 4) if budget_amount > 0 else None

    return {
        "profile": {
            "login": login,
            "name": user.get("name", ""),
            "avatar_url": user.get("avatar_url", ""),
            "auth_type": user.get("auth_type", "local"),
            "is_admin": bool(user.get("is_admin")),
        },
        "period": {
            "mode": period_mode,
            "date_from": range_from,
            "date_to": range_to,
            "label": f"{range_from} ~ {range_to}" if range_from and range_to else "",
        },
        "seats": seats,
        "seat_summary": {
            "seat_count": len(seats),
            "monthly_seat_cost": seat_cost,
            "orgs": [s["org"] for s in seats],
        },
        "activity": activity,
        "ai_usage": ai_usage,
        "spend": spend,
        "budget": {
            "live": bool(budget_ctx.get("live")),
            "personal": budget_ctx.get("personal_budget"),
            "universal": budget_ctx.get("universal_budget"),
            "effective": budget_ctx.get("effective_budget"),
            "effective_source": budget_ctx.get("effective_source"),
            "amount": budget_amount,
            "consumed": round(consumed_value, 4),
            "consumed_source": "github" if consumed is not None else "usage_data",
            "remaining": remaining,
            "usage_pct": round(consumed_value / budget_amount * 100, 1) if budget_amount > 0 else None,
            "error": budget_ctx.get("error"),
        },
        "cost_centers": budget_ctx.get("cost_centers", []),
        "totals": {
            "monthly_seat_cost": seat_cost,
            "ai_credit_cost": ai_cost,
            "estimated_total": total_spend,
            "budget_amount": budget_amount,
            "budget_remaining": remaining,
        },
        "budget_requests": budget_requests,
        "has_any_data": bool(
            seats or activity.get("has_data") or ai_usage.get("has_data")
            or spend.get("has_data") or budget_ctx.get("cost_centers")
            or budget_ctx.get("effective_budget")
        ),
    }


@router.get("/cost-centers")
async def my_cost_centers(request: Request):
    """Cost centers the user can select, flagged with current membership.

    Inherited memberships (via an org or team resource) are returned as
    ``locked`` — they cannot be changed for a single user.
    """
    user = require_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Authentication required"})
    return list_cost_centers_for_user(user.get("login", ""))


@router.get("/budget")
async def my_budget(request: Request, live: bool = Query(default=True)):
    """Live budget snapshot for the current user (individual + cost centers).

    Defaults to hitting the GitHub API so the numbers reflect the current
    billing cycle rather than the last sync.
    """
    user = require_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Authentication required"})

    login = user.get("login", "")
    start, end = current_month_range()
    try:
        ctx = await get_user_budget_context(login, live=live)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "personal_budget": None, "cost_centers": []}

    month_usage = _my_ai_usage(login, start, end)
    return {
        **ctx,
        "current_month": {"start": start, "end": end},
        "current_month_ai_cost": round(float(month_usage.get("kpi", {}).get("total_cost", 0) or 0), 4),
        "current_month_requests": round(float(month_usage.get("kpi", {}).get("total_requests", 0) or 0), 2),
    }
