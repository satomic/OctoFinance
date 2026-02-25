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

    tools = [get_usage_report, get_users_usage_report, get_metrics_detail, get_premium_request_usage]

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
