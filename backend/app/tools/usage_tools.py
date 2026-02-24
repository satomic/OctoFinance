"""
Copilot usage analysis tools for the AI engine.
"""

import json
from pydantic import BaseModel, Field

from copilot import define_tool

from ..services.data_collector import DataCollector


class GetUsageSummaryParams(BaseModel):
    org: str = Field(default="", description="Organization name. Leave empty for all orgs.")


class GetMetricsDetailParams(BaseModel):
    org: str = Field(default="", description="Organization name. Leave empty for all orgs.")


def _summarize_usage(org: str, usage_data: list) -> str:
    if not usage_data:
        return json.dumps({"org": org, "error": "empty usage data"})

    total_suggestions = sum(d.get("total_suggestions_count", 0) for d in usage_data)
    total_acceptances = sum(d.get("total_acceptances_count", 0) for d in usage_data)
    total_lines_suggested = sum(d.get("total_lines_suggested", 0) for d in usage_data)
    total_lines_accepted = sum(d.get("total_lines_accepted", 0) for d in usage_data)
    max_active_users = max((d.get("total_active_users", 0) for d in usage_data), default=0)
    acceptance_rate = (total_acceptances / total_suggestions * 100) if total_suggestions > 0 else 0

    # Language breakdown
    lang_stats = {}
    for day in usage_data:
        for b in day.get("breakdown", []):
            lang = b.get("language", "unknown")
            if lang not in lang_stats:
                lang_stats[lang] = {"suggestions": 0, "acceptances": 0, "active_users": 0}
            lang_stats[lang]["suggestions"] += b.get("suggestions_count", 0)
            lang_stats[lang]["acceptances"] += b.get("acceptances_count", 0)
            lang_stats[lang]["active_users"] = max(lang_stats[lang]["active_users"], b.get("active_users", 0))

    return json.dumps({
        "org": org,
        "period_days": len(usage_data),
        "total_suggestions": total_suggestions,
        "total_acceptances": total_acceptances,
        "acceptance_rate_pct": round(acceptance_rate, 1),
        "total_lines_suggested": total_lines_suggested,
        "total_lines_accepted": total_lines_accepted,
        "max_active_users": max_active_users,
        "language_breakdown": lang_stats,
    })


def create_usage_tools(collector: DataCollector) -> list:
    """Create usage tools bound to a specific DataCollector instance."""

    @define_tool(description="Get Copilot usage summary including total suggestions, acceptances, active users, and breakdown by language/editor.")
    def get_usage_summary(params: GetUsageSummaryParams) -> str:
        if params.org:
            data = collector.load_latest("usage", params.org)
            if not data:
                return json.dumps({"error": f"No usage data for org '{params.org}'."})
            return _summarize_usage(params.org, data)
        else:
            all_data = collector.load_all_latest("usage")
            if not all_data:
                return json.dumps({"error": "No usage data found."})
            summaries = {}
            for org, data in all_data.items():
                summaries[org] = json.loads(_summarize_usage(org, data))
            return json.dumps(summaries)

    @define_tool(description="Get detailed Copilot metrics including IDE code completions, chat usage, PR summaries, and per-editor/model breakdown.")
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

    return [get_usage_summary, get_metrics_detail]
