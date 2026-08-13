"""
GitHub Enterprise Teams tools for the AI engine.

Enterprise teams group users at the enterprise level, independently of
organizations, and can be granted Copilot Business licenses directly.

No Copilot dataset (seats, usage reports, metrics, AI credit CSVs) carries an
enterprise-team field, so team attribution is resolved by joining the synced
team rosters against those datasets on the user login. The roster is refreshed
during Sync Data and cached as `enterprise_teams/{slug}_latest.json`.

Read tools require a classic PAT with `read:enterprise`; write tools require
`admin:enterprise`. Fine-grained tokens are not supported by these endpoints.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from copilot import define_tool

if TYPE_CHECKING:
    from ..services.api_manager import APIManager
    from ..services.data_collector import DataCollector


# ---------------------------------------------------------------------------
# Pydantic param models
# ---------------------------------------------------------------------------

class ListEnterpriseTeamsParams(BaseModel):
    enterprise: str = Field(
        default="",
        description="Enterprise slug. Leave empty to auto-detect from synced data.",
    )
    live: bool = Field(
        default=False,
        description="Fetch from the GitHub API instead of the local cache (slower, always current).",
    )


class GetEnterpriseTeamParams(BaseModel):
    enterprise: str = Field(
        default="",
        description="Enterprise slug. Leave empty to auto-detect from synced data.",
    )
    team_slug: str = Field(
        description="Enterprise team slug, including the 'ent:' prefix (e.g. 'ent:platform'). Team name is also accepted.",
    )


class GetUserEnterpriseTeamsParams(BaseModel):
    enterprise: str = Field(
        default="",
        description="Enterprise slug. Leave empty to auto-detect from synced data.",
    )
    username: str = Field(description="GitHub username to look up")


class EnterpriseTeamCopilotUsageParams(BaseModel):
    enterprise: str = Field(
        default="",
        description="Enterprise slug. Leave empty to auto-detect from synced data.",
    )
    team_slug: str = Field(
        default="",
        description="Enterprise team slug to analyze. Leave empty to report on every team.",
    )


class CreateEnterpriseTeamParams(BaseModel):
    enterprise: str = Field(
        default="",
        description="Enterprise slug. Leave empty to auto-detect from synced data.",
    )
    name: str = Field(description="Name for the new enterprise team")
    description: str = Field(default="", description="Optional description for the team")
    organization_selection_type: str = Field(
        default="disabled",
        description=(
            "Which organizations the team is assigned to: 'disabled' (none, the default), "
            "'selected' (specific orgs, assign them afterwards with add_enterprise_team_organizations), "
            "or 'all' (every current and future org in the enterprise)."
        ),
    )
    group_id: str = Field(
        default="",
        description="Optional IdP group ID to sync membership from (SCIM/EMU enterprises only).",
    )
    notification_setting: str = Field(
        default="notifications_enabled",
        description="'notifications_enabled' or 'notifications_disabled'",
    )


class UpdateEnterpriseTeamParams(BaseModel):
    enterprise: str = Field(
        default="",
        description="Enterprise slug. Leave empty to auto-detect from synced data.",
    )
    team_slug: str = Field(
        description="Enterprise team slug, including the 'ent:' prefix (e.g. 'ent:platform').",
    )
    name: str = Field(default="", description="New name for the team. Leave empty to keep the current name.")
    description: str = Field(default="", description="New description. Leave empty to keep the current one.")
    organization_selection_type: str = Field(
        default="",
        description="New organization assignment mode: 'disabled', 'selected' or 'all'. Leave empty to keep it.",
    )
    notification_setting: str = Field(
        default="",
        description="'notifications_enabled' or 'notifications_disabled'. Leave empty to keep it.",
    )


class DeleteEnterpriseTeamParams(BaseModel):
    enterprise: str = Field(
        default="",
        description="Enterprise slug. Leave empty to auto-detect from synced data.",
    )
    team_slug: str = Field(
        description="Enterprise team slug to delete, including the 'ent:' prefix.",
    )


class ModifyEnterpriseTeamOrgsParams(BaseModel):
    enterprise: str = Field(
        default="",
        description="Enterprise slug. Leave empty to auto-detect from synced data.",
    )
    team_slug: str = Field(
        description="Enterprise team slug, including the 'ent:' prefix (e.g. 'ent:platform').",
    )
    organizations: list[str] = Field(
        default_factory=list,
        description="Organization login/slug names to assign or unassign",
    )


class ModifyEnterpriseTeamMembersParams(BaseModel):
    enterprise: str = Field(
        default="",
        description="Enterprise slug. Leave empty to auto-detect from synced data.",
    )
    team_slug: str = Field(
        description="Enterprise team slug, including the 'ent:' prefix (e.g. 'ent:platform').",
    )
    usernames: list[str] = Field(
        default_factory=list,
        description="GitHub usernames to add or remove",
    )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_enterprise_team_tools(
    api_manager: APIManager | None = None,
    collector: DataCollector | None = None,
) -> list:
    """Create enterprise team tools bound to the given APIManager and DataCollector."""

    def _load_enterprises() -> list[dict]:
        if collector is None:
            return []
        data = collector.load_latest("enterprise", "all")
        return data if isinstance(data, list) else []

    def _resolve_enterprise(requested: str) -> str | None:
        if requested:
            return requested
        if api_manager:
            enterprises = api_manager.get_all_enterprises()
            if len(enterprises) == 1:
                return enterprises[0]["slug"]
            if len(enterprises) > 1:
                return None
        enterprises = _load_enterprises()
        if len(enterprises) == 1:
            return enterprises[0]["slug"]
        return None

    def _enterprise_error(_requested: str) -> str:
        enterprises = _load_enterprises()
        if api_manager:
            enterprises = api_manager.get_all_enterprises() or enterprises
        if enterprises:
            return json.dumps({
                "error": (
                    "Multiple enterprises available. Please specify the enterprise slug. "
                    f"Available: {[e['slug'] for e in enterprises]}"
                )
            })
        return json.dumps({
            "error": (
                "No enterprise data found. Run Sync Data first so enterprise "
                "information can be discovered, or provide the enterprise slug explicitly."
            )
        })

    def _load_team_data(enterprise: str) -> dict | None:
        if collector is None:
            return None
        data = collector.load_latest("enterprise_teams", enterprise)
        return data if isinstance(data, dict) else None

    def _find_team(team_data: dict, team_slug: str) -> dict | None:
        wanted = team_slug.strip().lower()
        for team in team_data.get("teams", []):
            if team.get("slug", "").lower() == wanted or team.get("name", "").lower() == wanted:
                return team
        return None

    def _no_cache_error(enterprise: str) -> str:
        return json.dumps({
            "error": (
                f"No enterprise team data cached for '{enterprise}'. "
                "Run Sync Data (or the 'enterprise_teams' dataset sync) first."
            )
        })

    def _get_api(enterprise: str):
        if not api_manager:
            return None
        return api_manager.get_api_for_enterprise(enterprise)

    def _write_error(resp, subject: str) -> str | None:
        """Map the failure responses these endpoints return into an LLM-readable error."""
        if resp.status_code == 404:
            return json.dumps({"error": f"{subject} not found."})
        if resp.status_code in (401, 403):
            return json.dumps({
                "error": (
                    "Forbidden — enterprise team writes need a classic PAT with the "
                    "admin:enterprise scope. Fine-grained and GitHub App tokens are rejected."
                )
            })
        if resp.status_code == 422:
            return json.dumps({"error": f"Validation failed: {resp.text}"})
        return None

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    @define_tool(
        description=(
            "List all enterprise teams with member counts and assigned organizations. "
            "Enterprise teams group users at the enterprise level, independently of "
            "organizations, and can hold Copilot Business licenses directly. "
            "Reads from synced data by default; set live=true to query the GitHub API. "
            "Leave enterprise empty to auto-detect from synced data."
        )
    )
    async def list_enterprise_teams(params: ListEnterpriseTeamsParams) -> str:
        enterprise = _resolve_enterprise(params.enterprise)
        if not enterprise:
            return _enterprise_error(params.enterprise)

        if params.live:
            api = _get_api(enterprise)
            if not api:
                return json.dumps({"error": f"No API client found for enterprise '{enterprise}'."})
            teams = await api.get_enterprise_teams(enterprise)
            return json.dumps({"enterprise": enterprise, "teams": teams, "total": len(teams), "source": "live"})

        team_data = _load_team_data(enterprise)
        if not team_data:
            return _no_cache_error(enterprise)

        summary = [
            {
                "slug": t.get("slug", ""),
                "name": t.get("name", ""),
                "description": t.get("description", ""),
                "member_count": t.get("member_count", 0),
                "organizations": t.get("organizations", []),
                "organization_selection_type": t.get("organization_selection_type", ""),
                "idp_group": t.get("group_name") or None,
            }
            for t in team_data.get("teams", [])
        ]
        return json.dumps({
            "enterprise": enterprise,
            "teams": summary,
            "total": len(summary),
            "total_unique_members": team_data.get("total_unique_members", 0),
            "source": "synced_cache",
        })

    @define_tool(
        description=(
            "Get one enterprise team's full detail from synced data, including the "
            "member roster and the organizations the team is assigned to. "
            "Accepts the team slug (with 'ent:' prefix) or the team name."
        )
    )
    def get_enterprise_team(params: GetEnterpriseTeamParams) -> str:
        enterprise = _resolve_enterprise(params.enterprise)
        if not enterprise:
            return _enterprise_error(params.enterprise)

        team_data = _load_team_data(enterprise)
        if not team_data:
            return _no_cache_error(enterprise)

        team = _find_team(team_data, params.team_slug)
        if not team:
            return json.dumps({
                "error": f"Enterprise team '{params.team_slug}' not found in '{enterprise}'.",
                "available_teams": [t.get("slug", "") for t in team_data.get("teams", [])],
            })
        return json.dumps({"enterprise": enterprise, "team": team})

    @define_tool(
        description=(
            "Look up which enterprise teams a specific user belongs to. "
            "Use this to attribute a user's Copilot seat, usage or AI credit spend "
            "to an enterprise team, since none of those datasets carry a team field."
        )
    )
    def get_user_enterprise_teams(params: GetUserEnterpriseTeamsParams) -> str:
        enterprise = _resolve_enterprise(params.enterprise)
        if not enterprise:
            return _enterprise_error(params.enterprise)

        team_data = _load_team_data(enterprise)
        if not team_data:
            return _no_cache_error(enterprise)

        login = params.username.strip().lower()
        slugs = team_data.get("member_index", {}).get(login, [])
        by_slug = {t.get("slug", ""): t for t in team_data.get("teams", [])}
        return json.dumps({
            "enterprise": enterprise,
            "username": params.username,
            "teams": [
                {"slug": s, "name": by_slug.get(s, {}).get("name", s)}
                for s in slugs
            ],
            "total": len(slugs),
        })

    @define_tool(
        description=(
            "Analyze Copilot adoption and cost per enterprise team. For each team, joins "
            "the member roster against Copilot seats and the user-level usage report to "
            "report seat count, members without a seat, active members, interactions and "
            "estimated seat cost. Also reports seat holders not covered by any enterprise team. "
            "Leave team_slug empty to analyze all teams."
        )
    )
    def get_enterprise_team_copilot_usage(params: EnterpriseTeamCopilotUsageParams) -> str:
        enterprise = _resolve_enterprise(params.enterprise)
        if not enterprise:
            return _enterprise_error(params.enterprise)
        if collector is None:
            return json.dumps({"error": "No data collector available."})

        team_data = _load_team_data(enterprise)
        if not team_data:
            return _no_cache_error(enterprise)

        # Build seat + usage indexes across every org that has synced data.
        seat_index: dict[str, dict] = {}
        for org, seats_data in collector.load_all_latest("seats").items():
            if not isinstance(seats_data, dict):
                continue
            for seat in seats_data.get("seats", []):
                login = (seat.get("assignee") or {}).get("login", "")
                if not login:
                    continue
                entry = seat_index.setdefault(login.lower(), {"orgs": [], "last_activity_at": ""})
                if org not in entry["orgs"]:
                    entry["orgs"].append(org)
                last = seat.get("last_activity_at") or ""
                if last > entry["last_activity_at"]:
                    entry["last_activity_at"] = last

        usage_index: dict[str, int] = {}
        for _org, report in collector.load_all_latest("usage_users").items():
            if not isinstance(report, dict):
                continue
            for rec in report.get("records", []) or []:
                login = (rec.get("user_login") or "").lower()
                if login:
                    usage_index[login] = usage_index.get(login, 0) + int(
                        rec.get("user_initiated_interaction_count") or 0
                    )

        from ..config import COPILOT_PRICING
        price = COPILOT_PRICING.get("business", 19.0)

        teams = team_data.get("teams", [])
        if params.team_slug:
            team = _find_team(team_data, params.team_slug)
            if not team:
                return json.dumps({
                    "error": f"Enterprise team '{params.team_slug}' not found in '{enterprise}'.",
                    "available_teams": [t.get("slug", "") for t in teams],
                })
            teams = [team]

        results = []
        for team in teams:
            logins = [m.get("login", "") for m in team.get("members", []) if m.get("login")]
            with_seat = [ln for ln in logins if ln.lower() in seat_index]
            without_seat = [ln for ln in logins if ln.lower() not in seat_index]
            interactions = sum(usage_index.get(ln.lower(), 0) for ln in logins)
            active = [ln for ln in logins if usage_index.get(ln.lower(), 0) > 0]
            results.append({
                "slug": team.get("slug", ""),
                "name": team.get("name", ""),
                "organizations": team.get("organizations", []),
                "member_count": len(logins),
                "seat_count": len(with_seat),
                "members_without_seat": without_seat,
                "active_member_count": len(active),
                "inactive_with_seat": [ln for ln in with_seat if usage_index.get(ln.lower(), 0) == 0],
                "total_interactions": interactions,
                "estimated_monthly_seat_cost": round(len(with_seat) * price, 2),
            })

        all_team_logins = {
            m.get("login", "").lower()
            for t in team_data.get("teams", [])
            for m in t.get("members", [])
            if m.get("login")
        }
        uncovered = sorted(ln for ln in seat_index if ln not in all_team_logins)

        return json.dumps({
            "enterprise": enterprise,
            "price_per_seat": price,
            "teams": results,
            "seat_users_without_enterprise_team": uncovered,
            "seat_users_without_enterprise_team_count": len(uncovered),
            "note": (
                "Team members without a Copilot seat may be unaffiliated enterprise "
                "users who belong to no organization, so they never appear in org seat data."
            ),
        })

    @define_tool(
        description=(
            "Create a new enterprise team. Enterprise teams group users at the enterprise "
            "level and can be granted Copilot Business licenses directly, including users "
            "who belong to no organization. Returns the created team with its 'ent:'-prefixed slug. "
            "This is a write operation — confirm the name before executing. "
            "Requires a classic PAT with the admin:enterprise scope. "
            "Run Sync Data afterwards to refresh the local cache."
        )
    )
    async def create_enterprise_team(params: CreateEnterpriseTeamParams) -> str:
        enterprise = _resolve_enterprise(params.enterprise)
        if not enterprise:
            return _enterprise_error(params.enterprise)
        if not params.name.strip():
            return json.dumps({"error": "A team name is required."})

        api = _get_api(enterprise)
        if not api:
            return json.dumps({"error": f"No API client found for enterprise '{enterprise}'."})

        body: dict = {"name": params.name.strip()}
        if params.description:
            body["description"] = params.description
        if params.organization_selection_type:
            body["organization_selection_type"] = params.organization_selection_type
        if params.group_id:
            body["group_id"] = params.group_id
        if params.notification_setting:
            body["notification_setting"] = params.notification_setting

        resp = await api.client.post(f"/enterprises/{enterprise}/teams", json=body)
        err = _write_error(resp, f"enterprise '{enterprise}'")
        if err:
            return err
        resp.raise_for_status()
        return json.dumps({"success": True, "enterprise": enterprise, "team": resp.json()})

    @define_tool(
        description=(
            "Rename an enterprise team or change its description, organization assignment mode "
            "or notification setting. Only the fields you provide are changed. "
            "This is a write operation — confirm the changes before executing. "
            "Requires a classic PAT with the admin:enterprise scope."
        )
    )
    async def update_enterprise_team(params: UpdateEnterpriseTeamParams) -> str:
        enterprise = _resolve_enterprise(params.enterprise)
        if not enterprise:
            return _enterprise_error(params.enterprise)

        api = _get_api(enterprise)
        if not api:
            return json.dumps({"error": f"No API client found for enterprise '{enterprise}'."})

        body: dict = {}
        if params.name:
            body["name"] = params.name
        if params.description:
            body["description"] = params.description
        if params.organization_selection_type:
            body["organization_selection_type"] = params.organization_selection_type
        if params.notification_setting:
            body["notification_setting"] = params.notification_setting
        if not body:
            return json.dumps({"error": "Provide at least one field to update."})

        resp = await api.client.patch(f"/enterprises/{enterprise}/teams/{params.team_slug}", json=body)
        err = _write_error(resp, f"enterprise team '{params.team_slug}'")
        if err:
            return err
        resp.raise_for_status()
        return json.dumps({"success": True, "enterprise": enterprise, "team": resp.json()})

    @define_tool(
        description=(
            "Delete an enterprise team. Members lose any access the team granted, including "
            "Copilot licenses assigned through it, and all of the team's IdP mappings are removed. "
            "This is a destructive operation — confirm the team slug before executing. "
            "Requires a classic PAT with the admin:enterprise scope."
        )
    )
    async def delete_enterprise_team(params: DeleteEnterpriseTeamParams) -> str:
        enterprise = _resolve_enterprise(params.enterprise)
        if not enterprise:
            return _enterprise_error(params.enterprise)

        api = _get_api(enterprise)
        if not api:
            return json.dumps({"error": f"No API client found for enterprise '{enterprise}'."})

        resp = await api.client.delete(f"/enterprises/{enterprise}/teams/{params.team_slug}")
        err = _write_error(resp, f"enterprise team '{params.team_slug}'")
        if err:
            return err
        resp.raise_for_status()
        return json.dumps({"success": True, "enterprise": enterprise, "deleted_team": params.team_slug})

    @define_tool(
        description=(
            "Assign an enterprise team to one or more organizations, granting its members "
            "membership in those organizations. The team must use organization_selection_type='selected'. "
            "This is a write operation — confirm the organizations before executing. "
            "Requires a classic PAT with the admin:enterprise scope."
        )
    )
    async def add_enterprise_team_organizations(params: ModifyEnterpriseTeamOrgsParams) -> str:
        enterprise = _resolve_enterprise(params.enterprise)
        if not enterprise:
            return _enterprise_error(params.enterprise)
        if not params.organizations:
            return json.dumps({"error": "Provide at least one organization."})

        api = _get_api(enterprise)
        if not api:
            return json.dumps({"error": f"No API client found for enterprise '{enterprise}'."})

        resp = await api.client.post(
            f"/enterprises/{enterprise}/teams/{params.team_slug}/organizations/add",
            json={"organization_slugs": params.organizations},
        )
        err = _write_error(resp, f"enterprise team '{params.team_slug}'")
        if err:
            return err
        resp.raise_for_status()
        return json.dumps({
            "success": True,
            "enterprise": enterprise,
            "team_slug": params.team_slug,
            "assigned_organizations": params.organizations,
        })

    @define_tool(
        description=(
            "Unassign an enterprise team from one or more organizations. Members lose the "
            "organization membership the team granted them. "
            "This is a destructive operation — confirm the organizations before executing. "
            "Requires a classic PAT with the admin:enterprise scope."
        )
    )
    async def remove_enterprise_team_organizations(params: ModifyEnterpriseTeamOrgsParams) -> str:
        enterprise = _resolve_enterprise(params.enterprise)
        if not enterprise:
            return _enterprise_error(params.enterprise)
        if not params.organizations:
            return json.dumps({"error": "Provide at least one organization."})

        api = _get_api(enterprise)
        if not api:
            return json.dumps({"error": f"No API client found for enterprise '{enterprise}'."})

        resp = await api.client.post(
            f"/enterprises/{enterprise}/teams/{params.team_slug}/organizations/remove",
            json={"organization_slugs": params.organizations},
        )
        err = _write_error(resp, f"enterprise team '{params.team_slug}'")
        if err:
            return err
        resp.raise_for_status()
        return json.dumps({
            "success": True,
            "enterprise": enterprise,
            "team_slug": params.team_slug,
            "unassigned_organizations": params.organizations,
        })

    @define_tool(
        description=(
            "Add users to an enterprise team. Grants whatever access the team carries, "
            "including Copilot Business if the team is licensed. "
            "This is a write operation — confirm the team and usernames before executing. "
            "Requires a classic PAT with the admin:enterprise scope."
        )
    )
    async def add_enterprise_team_members(params: ModifyEnterpriseTeamMembersParams) -> str:
        enterprise = _resolve_enterprise(params.enterprise)
        if not enterprise:
            return _enterprise_error(params.enterprise)
        if not params.usernames:
            return json.dumps({"error": "Provide at least one username."})

        api = _get_api(enterprise)
        if not api:
            return json.dumps({"error": f"No API client found for enterprise '{enterprise}'."})

        resp = await api.client.post(
            f"/enterprises/{enterprise}/teams/{params.team_slug}/memberships/add",
            json={"usernames": params.usernames},
        )
        err = _write_error(resp, f"enterprise team '{params.team_slug}'")
        if err:
            return err
        resp.raise_for_status()
        return json.dumps({
            "success": True,
            "enterprise": enterprise,
            "team_slug": params.team_slug,
            "added": params.usernames,
        })

    @define_tool(
        description=(
            "Remove users from an enterprise team. If the team grants Copilot, the removed "
            "users lose that access unless another team or organization grants it. "
            "This is a destructive operation — confirm the team and usernames before executing. "
            "Requires a classic PAT with the admin:enterprise scope."
        )
    )
    async def remove_enterprise_team_members(params: ModifyEnterpriseTeamMembersParams) -> str:
        enterprise = _resolve_enterprise(params.enterprise)
        if not enterprise:
            return _enterprise_error(params.enterprise)
        if not params.usernames:
            return json.dumps({"error": "Provide at least one username."})

        api = _get_api(enterprise)
        if not api:
            return json.dumps({"error": f"No API client found for enterprise '{enterprise}'."})

        resp = await api.client.post(
            f"/enterprises/{enterprise}/teams/{params.team_slug}/memberships/remove",
            json={"usernames": params.usernames},
        )
        err = _write_error(resp, f"enterprise team '{params.team_slug}'")
        if err:
            return err
        resp.raise_for_status()
        return json.dumps({
            "success": True,
            "enterprise": enterprise,
            "team_slug": params.team_slug,
            "removed": params.usernames,
        })

    return [
        list_enterprise_teams,
        get_enterprise_team,
        get_user_enterprise_teams,
        get_enterprise_team_copilot_usage,
        create_enterprise_team,
        update_enterprise_team,
        delete_enterprise_team,
        add_enterprise_team_organizations,
        remove_enterprise_team_organizations,
        add_enterprise_team_members,
        remove_enterprise_team_members,
    ]
