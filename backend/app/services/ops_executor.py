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


class OpsExecutor:
    """Executes AI-recommended operational actions."""

    def __init__(self):
        self._api_manager: APIManager | None = None

    def set_api_manager(self, api_manager: APIManager):
        """Set the API manager for GitHub API calls."""
        self._api_manager = api_manager

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
            api_result = await api.remove_copilot_seats(
                target["org"], target["affected_users"]
            )
            target["status"] = "executed"
            target["executed_at"] = datetime.now(timezone.utc).isoformat()
            target["execution_result"] = api_result
            result["api_result"] = api_result
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
