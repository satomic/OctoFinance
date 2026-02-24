"""
Copilot seat management tools for the AI engine.
These tools are registered with CopilotSession so the AI can analyze seat data.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from copilot import define_tool

from ..services.data_collector import DataCollector

if TYPE_CHECKING:
    from ..services.api_manager import APIManager


class GetAllSeatsParams(BaseModel):
    org: str = Field(default="", description="Organization name. Leave empty to get seats for all discovered orgs.")


class FindInactiveUsersParams(BaseModel):
    org: str = Field(default="", description="Organization name. Leave empty for all orgs.")
    days: int = Field(default=30, description="Number of days of inactivity to consider a user inactive.")


class RemoveUserSeatParams(BaseModel):
    org: str = Field(description="Organization name")
    usernames: list[str] = Field(description="List of GitHub usernames to remove from Copilot")


class AddTeamMemberParams(BaseModel):
    org: str = Field(description="Organization name")
    team_slug: str = Field(description="Team slug (e.g. 'level1-team1')")
    username: str = Field(description="GitHub username to add to the team")
    role: str = Field(default="member", description="Role in the team: 'member' (default) or 'maintainer'")


def create_seat_tools(collector: DataCollector, api_manager: APIManager | None = None) -> list:
    """Create seat tools bound to a specific DataCollector and optional APIManager."""

    @define_tool(description="Get all Copilot seat assignments. Returns user list with activity info, assigned teams, and last active dates.")
    def get_all_seats(params: GetAllSeatsParams) -> str:
        if params.org:
            data = collector.load_latest("seats", params.org)
            if not data:
                return json.dumps({"error": f"No seat data found for org '{params.org}'. Try syncing first."})
            return json.dumps(data, default=str)
        else:
            all_data = collector.load_all_latest("seats")
            if not all_data:
                return json.dumps({"error": "No seat data found. Try syncing first."})
            return json.dumps(all_data, default=str)

    @define_tool(description="Find Copilot users who have been inactive for N days. Returns list of inactive users with their last activity date and cost impact.")
    def find_inactive_users(params: FindInactiveUsersParams) -> str:
        orgs_to_check = [params.org] if params.org else list(collector.load_all_latest("seats").keys())
        now = datetime.now(timezone.utc)
        inactive_users = []

        for org in orgs_to_check:
            seats_data = collector.load_latest("seats", org)
            billing_data = collector.load_latest("billing", org)
            price_per_seat = 19.0  # default
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
                    days_inactive = 999  # never used

                if days_inactive >= params.days:
                    assignee = seat.get("assignee", {})
                    inactive_users.append({
                        "org": org,
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
            "threshold_days": params.days,
        })

    @define_tool(description="Remove Copilot seats for specified users. Automatically detects whether a user was assigned at org level or team level and uses the correct removal method. This is a destructive operation - use only after admin confirmation.")
    async def remove_user_seat(params: RemoveUserSeatParams) -> str:
        if not api_manager:
            return json.dumps({"error": "No API manager available. Cannot perform seat removal."})
        api = api_manager.get_api_for_org(params.org)
        if not api:
            return json.dumps({"error": f"No API client available for org '{params.org}'."})

        # Load current seat data to determine assignment type per user
        seats_data = collector.load_latest("seats", params.org)
        seat_map: dict[str, dict | None] = {}
        if seats_data:
            for seat in seats_data.get("seats", []):
                login = (seat.get("assignee") or {}).get("login", "")
                if login:
                    seat_map[login.lower()] = seat.get("assigning_team")

        # Split users into org-level and team-level groups
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

        return json.dumps(results, default=str)

    @define_tool(description="Add a user to an organization team. This grants the user team-level Copilot access if the team has Copilot enabled. Use this to assign Copilot seats via team membership.")
    async def add_team_member(params: AddTeamMemberParams) -> str:
        if not api_manager:
            return json.dumps({"error": "No API manager available."})
        api = api_manager.get_api_for_org(params.org)
        if not api:
            return json.dumps({"error": f"No API client available for org '{params.org}'."})
        result = await api.add_team_membership(params.org, params.team_slug, params.username, params.role)
        return json.dumps(result, default=str)

    return [get_all_seats, find_inactive_users, remove_user_seat, add_team_member]
