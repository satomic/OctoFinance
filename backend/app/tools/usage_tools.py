"""
Copilot usage analysis tools for the AI engine.
Provides tools to read cached usage data and fetch live usage metrics reports.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from copilot import define_tool

from ..services.data_collector import DataCollector

if TYPE_CHECKING:
    from ..services.api_manager import APIManager


# ---------------------------------------------------------------------------
# Param models
# ---------------------------------------------------------------------------

class GetUsageReportParams(BaseModel):
    org: str = Field(default="", description="Organization name. Leave empty for all orgs.")


class GetUsersUsageReportParams(BaseModel):
    org: str = Field(default="", description="Organization name. Leave empty for all orgs.")


class GetMetricsDetailParams(BaseModel):
    org: str = Field(default="", description="Organization name. Leave empty for all orgs.")


class FetchOrgUsageReportParams(BaseModel):
    org: str = Field(description="Organization name (required).")
    day: str = Field(
        default="",
        description="Specific day in YYYY-MM-DD format. Leave empty to get latest 28-day report.",
    )


class FetchOrgUsersUsageReportParams(BaseModel):
    org: str = Field(description="Organization name (required).")
    day: str = Field(
        default="",
        description="Specific day in YYYY-MM-DD format. Leave empty to get latest 28-day report.",
    )


class GetUserPremiumUsageParams(BaseModel):
    user: str = Field(default="", description="Username to filter. Leave empty for all users.")
    org: str = Field(default="", description="Organization name to filter. Leave empty for all orgs.")


class GetPremiumRequestUsageParams(BaseModel):
    org: str = Field(default="", description="Organization name. Leave empty for all orgs.")


class FetchPremiumRequestUsageParams(BaseModel):
    org: str = Field(description="Organization name (required).")
    year: int = Field(default=0, description="Year (e.g. 2026). Leave 0 for current year.")
    month: int = Field(default=0, description="Month (1-12). Leave 0 for current month.")


# ---------------------------------------------------------------------------
# Tool factory
# ---------------------------------------------------------------------------

def create_usage_tools(
    collector: DataCollector,
    api_manager: APIManager | None = None,
) -> list:
    """Create usage tools bound to a DataCollector and optional APIManager for live fetches."""

    # --- Cached data tools ---

    @define_tool(
        description=(
            "Get the org-level Copilot usage report from cached data (synced during last Sync Data). "
            "Contains aggregated usage statistics, feature adoption metrics, and engagement data "
            "for the latest 28-day period."
        )
    )
    def get_usage_report(params: GetUsageReportParams) -> str:
        if params.org:
            data = collector.load_latest("usage", params.org)
            if not data:
                return json.dumps({"error": f"No usage report for org '{params.org}'. Try fetch_org_usage_report to get live data."})
            return json.dumps(data, default=str)
        else:
            all_data = collector.load_all_latest("usage")
            if not all_data:
                return json.dumps({"error": "No usage report data found. Try fetch_org_usage_report to get live data."})
            return json.dumps(all_data, default=str)

    @define_tool(
        description=(
            "Get the user-level Copilot usage report from cached data (synced during last Sync Data). "
            "Contains per-user engagement statistics, feature usage patterns, and adoption metrics "
            "for the latest 28-day period."
        )
    )
    def get_users_usage_report(params: GetUsersUsageReportParams) -> str:
        if params.org:
            data = collector.load_latest("usage_users", params.org)
            if not data:
                return json.dumps({"error": f"No user-level usage report for org '{params.org}'. Try fetch_org_users_usage_report to get live data."})
            return json.dumps(data, default=str)
        else:
            all_data = collector.load_all_latest("usage_users")
            if not all_data:
                return json.dumps({"error": "No user-level usage data found. Try fetch_org_users_usage_report to get live data."})
            return json.dumps(all_data, default=str)

    @define_tool(
        description=(
            "Get detailed Copilot metrics (legacy API) including IDE code completions, chat usage, "
            "PR summaries, and per-editor/model breakdown."
        )
    )
    def get_metrics_detail(params: GetMetricsDetailParams) -> str:
        if params.org:
            data = collector.load_latest("metrics", params.org)
            if not data:
                return json.dumps({"error": f"No metrics data for org '{params.org}'."})
            return json.dumps(data, default=str)
        else:
            all_data = collector.load_all_latest("metrics")
            if not all_data:
                return json.dumps({"error": "No metrics data found."})
            return json.dumps(all_data, default=str)

    @define_tool(
        description=(
            "Get Copilot premium request usage from cached data (synced during last Sync Data). "
            "Shows per-model breakdown of premium request consumption including model names, "
            "request counts, pricing, gross/discount/net amounts. Essential for cost analysis."
        )
    )
    def get_premium_request_usage(params: GetPremiumRequestUsageParams) -> str:
        if params.org:
            data = collector.load_latest("premium_requests", params.org)
            if not data:
                return json.dumps({"error": f"No premium request data for org '{params.org}'. Try fetch_premium_request_usage to get live data."})
            return json.dumps(data, default=str)
        else:
            all_data = collector.load_all_latest("premium_requests")
            if not all_data:
                return json.dumps({"error": "No premium request data found. Try fetch_premium_request_usage to get live data."})
            return json.dumps(all_data, default=str)

    @define_tool(
        description=(
            "Get per-user premium request usage from uploaded CSV data. "
            "This data comes from CSV files manually exported from GitHub UI and uploaded by the admin. "
            "Shows each user's daily premium request consumption broken down by AI model, "
            "including request counts, costs, quota usage percentage, and active days. "
            "Can filter by username or organization. Use this to answer questions about "
            "individual user's premium request spending and model preferences."
        )
    )
    def get_user_premium_usage(params: GetUserPremiumUsageParams) -> str:
        import csv as csv_mod
        # Check both primary and fallback (global) data dirs for CSV files
        csv_dirs = [collector.data_dir / "premium_usage_csv"]
        if collector._fallback_dir:
            csv_dirs.append(collector._fallback_dir / "premium_usage_csv")
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
            return json.dumps({"error": "No per-user premium usage CSV data found. Please upload a premium request usage CSV from the Dashboard page."})

        # Filter
        if params.org:
            records = [r for r in records if r.get("organization", "") == params.org]
        if params.user:
            records = [r for r in records if r.get("username", "") == params.user]

        if not records:
            return json.dumps({"error": f"No records found matching user='{params.user}', org='{params.org}'."})

        # Aggregate per user
        from collections import defaultdict as dd
        user_map: dict[str, dict] = dd(lambda: {
            "total_requests": 0, "total_cost": 0.0,
            "models": dd(float), "days": set(), "org": "", "quota": 0,
        })
        for r in records:
            user = r.get("username", "")
            u = user_map[user]
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
                "user": username,
                "org": info["org"],
                "total_requests": round(info["total_requests"], 2),
                "total_cost": round(info["total_cost"], 4),
                "quota": info["quota"],
                "usage_pct": round(info["total_requests"] / info["quota"] * 100, 1) if info["quota"] > 0 else 0,
                "days_active": len(info["days"]),
                "date_range": {"start": min(info["days"]), "end": max(info["days"])} if info["days"] else None,
                "models": {m: round(q, 2) for m, q in sorted(info["models"].items(), key=lambda x: -x[1])},
            })

        return json.dumps({"users": result, "total_records": len(records)}, default=str)

    tools = [get_usage_report, get_users_usage_report, get_metrics_detail, get_premium_request_usage, get_user_premium_usage]

    # --- Live fetch tools (require api_manager) ---

    if api_manager:
        @define_tool(
            description=(
                "Fetch LIVE org-level Copilot usage report directly from GitHub API. "
                "Provide a specific day (YYYY-MM-DD) to get a 1-day report, or leave day empty "
                "for the latest 28-day report. The report contains aggregated usage statistics "
                "for various Copilot features, user engagement data, and feature adoption metrics. "
                "Data available from Oct 10, 2025 onward."
            )
        )
        def fetch_org_usage_report(params: FetchOrgUsageReportParams) -> str:
            api = api_manager.get_api_for_org(params.org)
            if not api:
                return json.dumps({"error": f"No API client for org '{params.org}'."})

            loop = asyncio.get_event_loop()
            if params.day:
                result = loop.run_until_complete(
                    api.get_org_usage_report_1day(params.org, params.day)
                )
            else:
                result = loop.run_until_complete(
                    api.get_org_usage_report_28day(params.org)
                )

            if not result:
                return json.dumps({"error": f"No usage report available for org '{params.org}'.", "hint": "Ensure the org has the Copilot usage metrics policy enabled."})

            # Cache the result
            collector._save_json("usage", params.org, result)
            return json.dumps(result, default=str)

        @define_tool(
            description=(
                "Fetch LIVE user-level Copilot usage report directly from GitHub API. "
                "Provide a specific day (YYYY-MM-DD) to get a 1-day report, or leave day empty "
                "for the latest 28-day report. Contains per-user engagement statistics, "
                "individual feature usage patterns, and adoption metrics broken down by user. "
                "Data available from Oct 10, 2025 onward."
            )
        )
        def fetch_org_users_usage_report(params: FetchOrgUsersUsageReportParams) -> str:
            api = api_manager.get_api_for_org(params.org)
            if not api:
                return json.dumps({"error": f"No API client for org '{params.org}'."})

            loop = asyncio.get_event_loop()
            if params.day:
                result = loop.run_until_complete(
                    api.get_org_users_usage_report_1day(params.org, params.day)
                )
            else:
                result = loop.run_until_complete(
                    api.get_org_users_usage_report_28day(params.org)
                )

            if not result:
                return json.dumps({"error": f"No user-level usage report available for org '{params.org}'.", "hint": "Ensure the org has the Copilot usage metrics policy enabled."})

            # Cache the result
            collector._save_json("usage_users", params.org, result)
            return json.dumps(result, default=str)

        @define_tool(
            description=(
                "Fetch LIVE Copilot premium request usage directly from GitHub API. "
                "Shows per-model breakdown of premium request consumption including "
                "model names (GPT-5.2, Claude Opus 4.6, etc.), request counts, "
                "pricing ($0.04/request), gross/discount/net amounts. "
                "Optionally specify year and month to query historical data (up to 24 months)."
            )
        )
        def fetch_premium_request_usage(params: FetchPremiumRequestUsageParams) -> str:
            api = api_manager.get_api_for_org(params.org)
            if not api:
                return json.dumps({"error": f"No API client for org '{params.org}'."})

            loop = asyncio.get_event_loop()
            result = loop.run_until_complete(
                api.get_premium_request_usage(
                    params.org,
                    year=params.year if params.year else None,
                    month=params.month if params.month else None,
                )
            )

            if not result:
                return json.dumps({"error": f"No premium request data for org '{params.org}'.", "hint": "Ensure the PAT has 'Administration' org permission (read)."})

            # Cache the result
            collector._save_json("premium_requests", params.org, result)
            return json.dumps(result, default=str)

        tools.extend([fetch_org_usage_report, fetch_org_users_usage_report, fetch_premium_request_usage])

    return tools
