"""
OctoFinance MCP Server — Exposes all 17 FinOps tools via the Model Context Protocol.

Run via stdio transport:
    python -m backend.app.mcp_server

Configure in mcp.json:
    {
      "mcpServers": {
        "octofinance": {
          "command": "python",
          "args": ["-m", "backend.app.mcp_server"]
        }
      }
    }
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .config import config
from .services.api_manager import APIManager, api_manager
from .services.data_collector import DataCollector, data_collector
from .services.pat_manager import pat_manager


# ---------------------------------------------------------------------------
# Server setup with lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def _lifespan(server: FastMCP):
    """Initialize OctoFinance services before serving MCP tools."""
    pats_list = pat_manager.load()
    if pats_list:
        data_collector.set_api_manager(api_manager)
        await api_manager.rebuild()
        orgs = api_manager.get_all_orgs()
        print(f"[OctoFinance MCP] Loaded {len(pats_list)} PAT(s), discovered {len(orgs)} org(s)")
    else:
        print("[OctoFinance MCP] No PATs configured. Add PATs via the web UI first.")
    yield
    await api_manager.close_all()


mcp = FastMCP(
    "OctoFinance",
    description="AI-Powered GitHub Copilot FinOps Platform — seat management, usage analysis, billing, and operational tools",
    lifespan=_lifespan,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_collector = data_collector
_api = api_manager


def _audit_log(entry: dict):
    """Append an entry to the audit log file."""
    log_file = config.data_dir / "audit_log.json"
    existing = []
    if log_file.exists():
        existing = json.loads(log_file.read_text(encoding="utf-8"))
    existing.append(entry)
    log_file.write_text(json.dumps(existing, indent=2, default=str), encoding="utf-8")


# ===================================================================
# SEAT TOOLS (4)
# ===================================================================

@mcp.tool()
def get_all_seats(org: str = "") -> str:
    """Get all Copilot seat assignments. Returns user list with activity info, assigned teams, and last active dates.

    Args:
        org: Organization name. Leave empty to get seats for all discovered orgs.
    """
    if org:
        data = _collector.load_latest("seats", org)
        if not data:
            return json.dumps({"error": f"No seat data found for org '{org}'. Try syncing first."})
        return json.dumps(data, default=str)
    else:
        all_data = _collector.load_all_latest("seats")
        if not all_data:
            return json.dumps({"error": "No seat data found. Try syncing first."})
        return json.dumps(all_data, default=str)


@mcp.tool()
def find_inactive_users(org: str = "", days: int = 30) -> str:
    """Find Copilot users who have been inactive for N days. Returns list of inactive users with their last activity date and cost impact.

    Args:
        org: Organization name. Leave empty for all orgs.
        days: Number of days of inactivity to consider a user inactive.
    """
    orgs_to_check = [org] if org else list(_collector.load_all_latest("seats").keys())
    now = datetime.now(timezone.utc)
    inactive_users = []

    for o in orgs_to_check:
        seats_data = _collector.load_latest("seats", o)
        billing_data = _collector.load_latest("billing", o)
        price_per_seat = 19.0
        if billing_data:
            price_per_seat = billing_data.get("_detected_price_per_seat", 19.0)

        if not seats_data:
            continue

        for seat in seats_data.get("seats", []):
            last_activity = seat.get("last_activity_at")
            if last_activity:
                try:
                    last_dt = datetime.fromisoformat(last_activity.replace("Z", "+00:00"))
                    days_inactive = (now - last_dt).days
                except (ValueError, TypeError):
                    days_inactive = 999
            else:
                days_inactive = 999

            if days_inactive >= days:
                assignee = seat.get("assignee", {})
                inactive_users.append({
                    "org": o,
                    "login": assignee.get("login", "unknown"),
                    "last_activity_at": last_activity,
                    "days_inactive": days_inactive,
                    "last_activity_editor": seat.get("last_activity_editor"),
                    "monthly_cost": price_per_seat,
                    "team": (seat.get("assigning_team") or {}).get("name"),
                })

    inactive_users.sort(key=lambda x: x["days_inactive"], reverse=True)
    total_waste = sum(u["monthly_cost"] for u in inactive_users)

    return json.dumps({
        "inactive_users": inactive_users,
        "total_count": len(inactive_users),
        "total_monthly_waste": total_waste,
        "threshold_days": days,
    })


@mcp.tool()
async def remove_user_seat(org: str, usernames: list[str]) -> str:
    """Remove Copilot seats for specified users. Auto-detects org-level vs team-level assignment. Destructive operation — use after admin confirmation.

    Args:
        org: Organization name.
        usernames: List of GitHub usernames to remove from Copilot.
    """
    api = _api.get_api_for_org(org)
    if not api:
        return json.dumps({"error": f"No API client available for org '{org}'."})

    seats_data = _collector.load_latest("seats", org)
    seat_map: dict[str, dict | None] = {}
    if seats_data:
        for seat in seats_data.get("seats", []):
            login = (seat.get("assignee") or {}).get("login", "")
            if login:
                seat_map[login.lower()] = seat.get("assigning_team")

    org_level_users: list[str] = []
    team_removals: list[tuple[str, str]] = []
    for username in usernames:
        team = seat_map.get(username.lower())
        if team and team.get("slug"):
            team_removals.append((username, team["slug"]))
        else:
            org_level_users.append(username)

    results: list[dict] = []
    if org_level_users:
        result = await api.remove_copilot_seats(org, org_level_users)
        results.append({"method": "org_level", "usernames": org_level_users, "result": result})
    for username, team_slug in team_removals:
        result = await api.remove_team_membership(org, team_slug, username)
        results.append({"method": "team_level", "username": username, "team": team_slug, "result": result})

    return json.dumps(results, default=str)


@mcp.tool()
async def add_team_member(org: str, team_slug: str, username: str, role: str = "member") -> str:
    """Add a user to an organization team. Grants team-level Copilot access if the team has Copilot enabled.

    Args:
        org: Organization name.
        team_slug: Team slug (e.g. 'level1-team1').
        username: GitHub username to add.
        role: Role in team: 'member' (default) or 'maintainer'.
    """
    api = _api.get_api_for_org(org)
    if not api:
        return json.dumps({"error": f"No API client available for org '{org}'."})
    result = await api.add_team_membership(org, team_slug, username, role)
    return json.dumps(result, default=str)


# ===================================================================
# BILLING TOOLS (2)
# ===================================================================

@mcp.tool()
def get_cost_overview(org: str = "") -> str:
    """Get cost overview for Copilot across organizations. Shows total seats, active seats, wasted seats, monthly cost, and estimated waste.

    Args:
        org: Organization name. Leave empty for all orgs.
    """
    orgs_to_check = [org] if org else list(_collector.load_all_latest("billing").keys())
    overview = []

    for o in orgs_to_check:
        billing = _collector.load_latest("billing", o)
        if not billing:
            continue
        price = billing.get("_detected_price_per_seat", 19.0)
        plan_type = billing.get("_detected_plan_type", "business")
        seat_breakdown = billing.get("seat_breakdown", {})
        total = seat_breakdown.get("total", 0)
        active = seat_breakdown.get("active_this_cycle", 0)
        pending_cancel = seat_breakdown.get("pending_cancellation", 0)
        inactive = total - active
        monthly_cost = total * price
        waste_cost = inactive * price

        overview.append({
            "org": o, "plan_type": plan_type, "price_per_seat": price,
            "total_seats": total, "active_seats": active, "inactive_seats": inactive,
            "pending_cancellation": pending_cancel, "monthly_cost": monthly_cost,
            "estimated_monthly_waste": waste_cost,
            "utilization_pct": round(active / total * 100, 1) if total > 0 else 0,
        })

    grand_total_cost = sum(o["monthly_cost"] for o in overview)
    grand_total_waste = sum(o["estimated_monthly_waste"] for o in overview)

    return json.dumps({
        "organizations": overview,
        "grand_total_monthly_cost": grand_total_cost,
        "grand_total_estimated_waste": grand_total_waste,
        "potential_annual_savings": grand_total_waste * 12,
    })


@mcp.tool()
def calculate_roi(org: str = "") -> str:
    """Calculate ROI metrics for Copilot investment. Shows cost per active user, suggestions per dollar, and efficiency metrics.

    Args:
        org: Organization name. Leave empty for all orgs.
    """
    orgs_to_check = [org] if org else list(_collector.load_all_latest("billing").keys())
    roi_data = []

    for o in orgs_to_check:
        billing = _collector.load_latest("billing", o)
        usage_data = _collector.load_latest("usage", o)
        if not billing:
            continue
        price = billing.get("_detected_price_per_seat", 19.0)
        seat_breakdown = billing.get("seat_breakdown", {})
        total = seat_breakdown.get("total", 0)
        active = seat_breakdown.get("active_this_cycle", 0)
        monthly_cost = total * price

        total_suggestions = 0
        total_acceptances = 0
        if usage_data and isinstance(usage_data, list):
            total_suggestions = sum(d.get("total_suggestions_count", 0) for d in usage_data)
            total_acceptances = sum(d.get("total_acceptances_count", 0) for d in usage_data)

        cost_per_active_user = monthly_cost / active if active > 0 else 0
        acceptance_rate = total_acceptances / total_suggestions * 100 if total_suggestions > 0 else 0

        roi_data.append({
            "org": o, "monthly_cost": monthly_cost, "total_seats": total,
            "active_seats": active, "cost_per_active_user": round(cost_per_active_user, 2),
            "total_suggestions": total_suggestions, "total_acceptances": total_acceptances,
            "acceptance_rate_pct": round(acceptance_rate, 1),
            "suggestions_per_dollar": round(total_suggestions / monthly_cost, 1) if monthly_cost > 0 else 0,
        })

    return json.dumps({"roi_by_org": roi_data})


# ===================================================================
# USAGE TOOLS (8)
# ===================================================================

@mcp.tool()
def get_usage_report(org: str = "") -> str:
    """Get the org-level Copilot usage report from cached data. Contains aggregated usage statistics, feature adoption, and engagement data for the latest 28-day period.

    Args:
        org: Organization name. Leave empty for all orgs.
    """
    if org:
        data = _collector.load_latest("usage", org)
        if not data:
            return json.dumps({"error": f"No usage report for org '{org}'. Try fetch_org_usage_report for live data."})
        return json.dumps(data, default=str)
    else:
        all_data = _collector.load_all_latest("usage")
        if not all_data:
            return json.dumps({"error": "No usage report data found. Try fetch_org_usage_report for live data."})
        return json.dumps(all_data, default=str)


@mcp.tool()
def get_users_usage_report(org: str = "") -> str:
    """Get the user-level Copilot usage report from cached data. Contains per-user engagement, feature usage patterns, and adoption metrics for the latest 28-day period.

    Args:
        org: Organization name. Leave empty for all orgs.
    """
    if org:
        data = _collector.load_latest("usage_users", org)
        if not data:
            return json.dumps({"error": f"No user-level usage report for org '{org}'. Try fetch_org_users_usage_report for live data."})
        return json.dumps(data, default=str)
    else:
        all_data = _collector.load_all_latest("usage_users")
        if not all_data:
            return json.dumps({"error": "No user-level usage data found. Try fetch_org_users_usage_report for live data."})
        return json.dumps(all_data, default=str)


@mcp.tool()
def get_metrics_detail(org: str = "") -> str:
    """Get detailed Copilot metrics (legacy API) including IDE code completions, chat usage, PR summaries, and per-editor/model breakdown.

    Args:
        org: Organization name. Leave empty for all orgs.
    """
    if org:
        data = _collector.load_latest("metrics", org)
        if not data:
            return json.dumps({"error": f"No metrics data for org '{org}'."})
        return json.dumps(data, default=str)
    else:
        all_data = _collector.load_all_latest("metrics")
        if not all_data:
            return json.dumps({"error": "No metrics data found."})
        return json.dumps(all_data, default=str)


@mcp.tool()
def get_premium_request_usage(org: str = "") -> str:
    """Get Copilot premium request usage from cached data. Shows per-model breakdown including request counts, pricing, gross/discount/net amounts.

    Args:
        org: Organization name. Leave empty for all orgs.
    """
    if org:
        data = _collector.load_latest("premium_requests", org)
        if not data:
            return json.dumps({"error": f"No premium request data for org '{org}'. Try fetch_premium_request_usage for live data."})
        return json.dumps(data, default=str)
    else:
        all_data = _collector.load_all_latest("premium_requests")
        if not all_data:
            return json.dumps({"error": "No premium request data found. Try fetch_premium_request_usage for live data."})
        return json.dumps(all_data, default=str)


@mcp.tool()
def get_user_premium_usage(user: str = "", org: str = "") -> str:
    """Get per-user premium request usage from uploaded CSV data. Shows each user's daily premium request consumption broken down by AI model, including request counts, costs, and quota usage.

    Args:
        user: Username to filter. Leave empty for all users.
        org: Organization name to filter. Leave empty for all orgs.
    """
    import csv as csv_mod

    csv_dirs = [_collector.data_dir / "premium_usage_csv"]
    if _collector._fallback_dir:
        csv_dirs.append(_collector._fallback_dir / "premium_usage_csv")

    records: list[dict] = []
    seen_files: set[str] = set()
    for csv_dir in csv_dirs:
        if not csv_dir.exists():
            continue
        for f in sorted(csv_dir.glob("*.csv")):
            if f.name in seen_files:
                continue
            seen_files.add(f.name)
            with open(f, encoding="utf-8") as fh:
                for row in csv_mod.DictReader(fh):
                    records.append(row)

    if not records:
        return json.dumps({"error": "No per-user premium usage CSV data found. Upload a CSV via the web UI."})

    if org:
        records = [r for r in records if r.get("organization", "") == org]
    if user:
        records = [r for r in records if r.get("username", "") == user]

    if not records:
        return json.dumps({"error": f"No records found matching user='{user}', org='{org}'."})

    user_map: dict[str, dict] = defaultdict(lambda: {
        "total_requests": 0, "total_cost": 0.0,
        "models": defaultdict(float), "days": set(), "org": "", "quota": 0,
    })
    for r in records:
        u = user_map[r.get("username", "")]
        qty = float(r.get("quantity", 0))
        u["total_requests"] += qty
        u["total_cost"] += float(r.get("gross_amount", 0))
        u["models"][r.get("model", "unknown")] += qty
        u["days"].add(r.get("date", ""))
        u["org"] = r.get("organization", "")
        try:
            u["quota"] = int(r.get("total_monthly_quota", 0))
        except (ValueError, TypeError):
            pass

    result = []
    for username, info in sorted(user_map.items(), key=lambda x: -x[1]["total_requests"]):
        result.append({
            "user": username, "org": info["org"],
            "total_requests": round(info["total_requests"], 2),
            "total_cost": round(info["total_cost"], 4),
            "quota": info["quota"],
            "usage_pct": round(info["total_requests"] / info["quota"] * 100, 1) if info["quota"] > 0 else 0,
            "days_active": len(info["days"]),
            "date_range": {"start": min(info["days"]), "end": max(info["days"])} if info["days"] else None,
            "models": {m: round(q, 2) for m, q in sorted(info["models"].items(), key=lambda x: -x[1])},
        })

    return json.dumps({"users": result, "total_records": len(records)}, default=str)


@mcp.tool()
async def fetch_org_usage_report(org: str, day: str = "") -> str:
    """Fetch LIVE org-level Copilot usage report directly from GitHub API. Provide a specific day (YYYY-MM-DD) for a 1-day report, or leave empty for latest 28-day report.

    Args:
        org: Organization name (required).
        day: Specific day in YYYY-MM-DD format. Leave empty for latest 28-day report.
    """
    api = _api.get_api_for_org(org)
    if not api:
        return json.dumps({"error": f"No API client for org '{org}'."})

    if day:
        result = await api.get_org_usage_report_1day(org, day)
    else:
        result = await api.get_org_usage_report_28day(org)

    if not result:
        return json.dumps({"error": f"No usage report available for org '{org}'.", "hint": "Ensure Copilot usage metrics policy is enabled."})

    _collector._save_json("usage", org, result)
    return json.dumps(result, default=str)


@mcp.tool()
async def fetch_org_users_usage_report(org: str, day: str = "") -> str:
    """Fetch LIVE user-level Copilot usage report directly from GitHub API. Provide a specific day (YYYY-MM-DD) for a 1-day report, or leave empty for latest 28-day report.

    Args:
        org: Organization name (required).
        day: Specific day in YYYY-MM-DD format. Leave empty for latest 28-day report.
    """
    api = _api.get_api_for_org(org)
    if not api:
        return json.dumps({"error": f"No API client for org '{org}'."})

    if day:
        result = await api.get_org_users_usage_report_1day(org, day)
    else:
        result = await api.get_org_users_usage_report_28day(org)

    if not result:
        return json.dumps({"error": f"No user-level usage report for org '{org}'.", "hint": "Ensure Copilot usage metrics policy is enabled."})

    _collector._save_json("usage_users", org, result)
    return json.dumps(result, default=str)


@mcp.tool()
async def fetch_premium_request_usage(org: str, year: int = 0, month: int = 0) -> str:
    """Fetch LIVE Copilot premium request usage from GitHub API. Shows per-model breakdown with pricing. Optionally specify year/month for historical data.

    Args:
        org: Organization name (required).
        year: Year (e.g. 2026). Leave 0 for current year.
        month: Month (1-12). Leave 0 for current month.
    """
    api = _api.get_api_for_org(org)
    if not api:
        return json.dumps({"error": f"No API client for org '{org}'."})

    result = await api.get_premium_request_usage(
        org,
        year=year if year else None,
        month=month if month else None,
    )

    if not result:
        return json.dumps({"error": f"No premium request data for org '{org}'.", "hint": "Ensure PAT has 'Administration' org permission (read)."})

    _collector._save_json("premium_requests", org, result)
    return json.dumps(result, default=str)


# ===================================================================
# ACTION TOOLS (3)
# ===================================================================

@mcp.tool()
async def batch_remove_seats(org: str, usernames: list[str], reason: str = "inactive") -> str:
    """Batch remove Copilot seats for multiple users. Auto-detects org-level vs team-level assignment. Records the action in audit log. Requires admin confirmation.

    Args:
        org: Organization name.
        usernames: List of GitHub usernames to remove.
        reason: Reason for removal.
    """
    api = _api.get_api_for_org(org)
    if not api:
        return json.dumps({"error": f"No API client available for org '{org}'."})

    seat_map: dict[str, dict | None] = {}
    seats_data = _collector.load_latest("seats", org)
    if seats_data:
        for seat in seats_data.get("seats", []):
            login = (seat.get("assignee") or {}).get("login", "")
            if login:
                seat_map[login.lower()] = seat.get("assigning_team")

    org_level_users: list[str] = []
    team_removals: list[tuple[str, str]] = []
    for username in usernames:
        team = seat_map.get(username.lower())
        if team and team.get("slug"):
            team_removals.append((username, team["slug"]))
        else:
            org_level_users.append(username)

    results: list[dict] = []
    if org_level_users:
        result = await api.remove_copilot_seats(org, org_level_users)
        results.append({"method": "org_level", "usernames": org_level_users, "result": result})
    for username, team_slug in team_removals:
        result = await api.remove_team_membership(org, team_slug, username)
        results.append({"method": "team_level", "username": username, "team": team_slug, "result": result})

    _audit_log({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": "batch_remove_seats",
        "org": org, "usernames": usernames, "reason": reason, "results": results,
    })

    return json.dumps({
        "action": "batch_remove_seats", "org": org,
        "users_removed": usernames, "count": len(usernames), "results": results,
    }, default=str)


@mcp.tool()
def record_recommendation(
    org: str,
    recommendation_type: str,
    description: str,
    affected_users: list[str] | None = None,
    estimated_monthly_savings: float = 0,
) -> str:
    """Record an AI-generated recommendation for admin review. Recommendations appear in the Action Panel for confirmation.

    Args:
        org: Organization name.
        recommendation_type: Type: 'remove_seats', 'send_reminder', 'upgrade_plan', 'downgrade_plan'.
        description: Human-readable description of the recommendation.
        affected_users: Users affected by recommendation.
        estimated_monthly_savings: Estimated monthly cost savings in USD.
    """
    rec = {
        "id": datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "org": org,
        "type": recommendation_type,
        "affected_users": affected_users or [],
        "description": description,
        "estimated_monthly_savings": estimated_monthly_savings,
        "status": "pending",
    }

    rec_file = config.data_dir / "recommendations.json"
    existing = []
    if rec_file.exists():
        existing = json.loads(rec_file.read_text(encoding="utf-8"))
    existing.append(rec)
    rec_file.write_text(json.dumps(existing, indent=2, default=str), encoding="utf-8")

    return json.dumps({"recorded": True, "recommendation": rec})


@mcp.tool()
def get_recommendations(status: str = "pending") -> str:
    """Get recorded recommendations. Can filter by status.

    Args:
        status: Filter by status: 'pending', 'approved', 'rejected', 'executed', or 'all'.
    """
    rec_file = config.data_dir / "recommendations.json"
    if not rec_file.exists():
        return json.dumps({"recommendations": [], "count": 0})

    recs = json.loads(rec_file.read_text(encoding="utf-8"))
    if status != "all":
        recs = [r for r in recs if r.get("status") == status]

    return json.dumps({"recommendations": recs, "count": len(recs)})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
