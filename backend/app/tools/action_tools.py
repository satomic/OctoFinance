"""
Operational action tools for the AI engine.
These tools perform actual operations (seat removal, reminders, etc.)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from copilot import define_tool

from ..config import config
from ..services.data_collector import DataCollector

if TYPE_CHECKING:
    from ..services.api_manager import APIManager


class BatchRemoveSeatsParams(BaseModel):
    org: str = Field(description="Organization name")
    usernames: list[str] = Field(description="List of GitHub usernames to remove")
    reason: str = Field(default="inactive", description="Reason for removal")


class RecordRecommendationParams(BaseModel):
    org: str = Field(description="Organization name")
    recommendation_type: str = Field(description="Type: 'remove_seats', 'send_reminder', 'upgrade_plan', 'downgrade_plan'")
    affected_users: list[str] = Field(default_factory=list, description="Users affected by recommendation")
    description: str = Field(description="Human-readable description of the recommendation")
    estimated_monthly_savings: float = Field(default=0, description="Estimated monthly cost savings in USD")


class GetRecommendationsParams(BaseModel):
    status: str = Field(default="pending", description="Filter by status: 'pending', 'approved', 'rejected', 'executed', or 'all'")


def _append_audit_log(entry: dict):
    """Append an entry to the audit log file."""
    log_file = config.data_dir / "audit_log.json"
    existing = []
    if log_file.exists():
        existing = json.loads(log_file.read_text(encoding="utf-8"))
    existing.append(entry)
    log_file.write_text(json.dumps(existing, indent=2, default=str), encoding="utf-8")


def create_action_tools(api_manager: APIManager | None = None, collector: DataCollector | None = None) -> list:
    """Create action tools. Uses api_manager for GitHub API calls."""

    @define_tool(description="Batch remove Copilot seats for multiple users. Automatically detects org-level vs team-level assignment and uses the correct removal method. Records the action in audit log. Requires admin confirmation before execution.")
    async def batch_remove_seats(params: BatchRemoveSeatsParams) -> str:
        if not api_manager:
            return json.dumps({"error": "No API manager available. Cannot perform seat removal."})
        api = api_manager.get_api_for_org(params.org)
        if not api:
            return json.dumps({"error": f"No API client available for org '{params.org}'."})

        # Load seat data to determine assignment type per user
        seat_map: dict[str, dict | None] = {}
        if collector:
            seats_data = collector.load_latest("seats", params.org)
            if seats_data:
                for seat in seats_data.get("seats", []):
                    login = (seat.get("assignee") or {}).get("login", "")
                    if login:
                        seat_map[login.lower()] = seat.get("assigning_team")

        # Split users by assignment type
        org_level_users: list[str] = []
        team_removals: list[tuple[str, str]] = []  # (username, team_slug)
        for username in params.usernames:
            team = seat_map.get(username.lower())
            if team and team.get("slug"):
                team_removals.append((username, team["slug"]))
            else:
                org_level_users.append(username)

        results: list[dict] = []

        # Remove org-level users in batch
        if org_level_users:
            result = await api.remove_copilot_seats(params.org, org_level_users)
            results.append({
                "method": "org_level",
                "usernames": org_level_users,
                "result": result,
            })

        # Remove team-level users one by one
        for username, team_slug in team_removals:
            result = await api.remove_team_membership(params.org, team_slug, username)
            results.append({
                "method": "team_level",
                "username": username,
                "team": team_slug,
                "result": result,
            })

        # Record in audit log
        audit_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": "batch_remove_seats",
            "org": params.org,
            "usernames": params.usernames,
            "reason": params.reason,
            "results": results,
        }
        _append_audit_log(audit_entry)

        return json.dumps({
            "action": "batch_remove_seats",
            "org": params.org,
            "users_removed": params.usernames,
            "count": len(params.usernames),
            "results": results,
        }, default=str)

    @define_tool(description="Record an AI-generated recommendation for admin review. Recommendations are stored and shown in the Action Panel for confirmation.")
    def record_recommendation(params: RecordRecommendationParams) -> str:
        rec = {
            "id": datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "org": params.org,
            "type": params.recommendation_type,
            "affected_users": params.affected_users,
            "description": params.description,
            "estimated_monthly_savings": params.estimated_monthly_savings,
            "status": "pending",
        }

        # Save to recommendations file (global)
        rec_file = config.data_dir / "recommendations.json"
        existing = []
        if rec_file.exists():
            existing = json.loads(rec_file.read_text(encoding="utf-8"))
        existing.append(rec)
        rec_file.write_text(json.dumps(existing, indent=2, default=str), encoding="utf-8")

        return json.dumps({"recorded": True, "recommendation": rec})

    @define_tool(description="Get recorded recommendations. Can filter by status (pending/approved/rejected/executed/all).")
    def get_recommendations(params: GetRecommendationsParams) -> str:
        rec_file = config.data_dir / "recommendations.json"
        if not rec_file.exists():
            return json.dumps({"recommendations": [], "count": 0})

        recs = json.loads(rec_file.read_text(encoding="utf-8"))
        if params.status != "all":
            recs = [r for r in recs if r.get("status") == params.status]

        return json.dumps({"recommendations": recs, "count": len(recs)})

    return [batch_remove_seats, record_recommendation, get_recommendations]
