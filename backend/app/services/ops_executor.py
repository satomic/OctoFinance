"""
Operations executor - handles execution of AI-recommended actions.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ..config import config

if TYPE_CHECKING:
    from .api_manager import APIManager
    from .data_collector import DataCollector


class OpsExecutor:
    """Executes AI-recommended operational actions."""

    def __init__(self):
        self._api_manager: APIManager | None = None
        self._data_collector: DataCollector | None = None

    def set_api_manager(self, api_manager: APIManager):
        """Set the API manager for GitHub API calls."""
        self._api_manager = api_manager

    def set_data_collector(self, collector: DataCollector):
        """Set the data collector for reading seat data."""
        self._data_collector = collector

    async def execute_recommendation(self, recommendation_id: str) -> dict:
        """Execute a pending recommendation by its ID."""
        rec_file = config.data_dir / "recommendations.json"
        if not rec_file.exists():
            return {"error": "No recommendations found"}

        recs = json.loads(rec_file.read_text(encoding="utf-8"))
        target = None
        for r in recs:
            if r.get("id") == recommendation_id:
                target = r
                break

        if not target:
            return {"error": f"Recommendation {recommendation_id} not found"}

        if target.get("status") != "pending":
            return {"error": f"Recommendation is already {target.get('status')}"}

        result = {"recommendation_id": recommendation_id, "action": target["type"]}

        if target["type"] == "remove_seats":
            if not self._api_manager:
                return {"error": "No API manager available. Cannot execute action."}
            api = self._api_manager.get_api_for_org(target["org"])
            if not api:
                return {"error": f"No API client for org '{target['org']}'."}

            org = target["org"]
            usernames = target["affected_users"]

            # Load seat data to determine org-level vs team-level assignment
            seat_map: dict[str, dict | None] = {}
            if self._data_collector:
                seats_data = self._data_collector.load_latest("seats", org)
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

            api_results: list[dict] = []
            if org_level_users:
                r = await api.remove_copilot_seats(org, org_level_users)
                api_results.append({"method": "org_level", "usernames": org_level_users, "result": r})
            for username, team_slug in team_removals:
                r = await api.remove_team_membership(org, team_slug, username)
                api_results.append({"method": "team_level", "username": username, "team": team_slug, "result": r})

            target["status"] = "executed"
            target["executed_at"] = datetime.now(timezone.utc).isoformat()
            target["execution_result"] = api_results
            result["api_result"] = api_results
        else:
            target["status"] = "executed"
            target["executed_at"] = datetime.now(timezone.utc).isoformat()

        # Save updated recommendations
        rec_file.write_text(json.dumps(recs, indent=2, default=str), encoding="utf-8")
        result["status"] = "executed"
        return result

    async def reject_recommendation(self, recommendation_id: str) -> dict:
        """Reject a pending recommendation."""
        rec_file = config.data_dir / "recommendations.json"
        if not rec_file.exists():
            return {"error": "No recommendations found"}

        recs = json.loads(rec_file.read_text(encoding="utf-8"))
        for r in recs:
            if r.get("id") == recommendation_id:
                r["status"] = "rejected"
                r["rejected_at"] = datetime.now(timezone.utc).isoformat()
                rec_file.write_text(json.dumps(recs, indent=2, default=str), encoding="utf-8")
                return {"recommendation_id": recommendation_id, "status": "rejected"}

        return {"error": f"Recommendation {recommendation_id} not found"}

    def get_pending_recommendations(self) -> list:
        """Get all pending recommendations."""
        rec_file = config.data_dir / "recommendations.json"
        if not rec_file.exists():
            return []
        recs = json.loads(rec_file.read_text(encoding="utf-8"))
        return [r for r in recs if r.get("status") == "pending"]


ops_executor = OpsExecutor()
