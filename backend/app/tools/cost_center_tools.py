"""
GitHub Enterprise Cost Center management tools for the AI engine.
Uses the GitHub Billing Cost Centers REST API (version 2026-03-10).
All endpoints operate at the enterprise level.

Enterprise and cost center data is pre-synced during Sync Data and stored as JSON
files in the data directory. Tools read from this local cache for lookups and
use live API calls only for write operations.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from copilot import define_tool

if TYPE_CHECKING:
    from ..services.api_manager import APIManager
    from ..services.data_collector import DataCollector

# Cost Centers API requires a specific API version
_VERSION_HEADER = {"X-GitHub-Api-Version": "2026-03-10"}


# ---------------------------------------------------------------------------
# Pydantic param models
# ---------------------------------------------------------------------------

class ListCostCentersParams(BaseModel):
    enterprise: str = Field(
        default="",
        description=(
            "Enterprise slug (e.g. 'my-enterprise'). "
            "Leave empty to auto-detect from synced data."
        ),
    )
    state: str = Field(
        default="active",
        description="Filter by state: 'active' (default), 'archived', or 'all'",
    )


class CreateCostCenterParams(BaseModel):
    enterprise: str = Field(
        default="",
        description="Enterprise slug. Leave empty to auto-detect from synced data.",
    )
    name: str = Field(description="Name for the new cost center")


class GetCostCenterParams(BaseModel):
    enterprise: str = Field(
        default="",
        description="Enterprise slug. Leave empty to auto-detect from synced data.",
    )
    cost_center_id: str = Field(description="The unique ID of the cost center")


class UpdateCostCenterParams(BaseModel):
    enterprise: str = Field(
        default="",
        description="Enterprise slug. Leave empty to auto-detect from synced data.",
    )
    cost_center_id: str = Field(description="The unique ID of the cost center")
    name: str = Field(description="New name for the cost center")


class DeleteCostCenterParams(BaseModel):
    enterprise: str = Field(
        default="",
        description="Enterprise slug. Leave empty to auto-detect from synced data.",
    )
    cost_center_id: str = Field(description="The unique ID of the cost center to archive/delete")


class AddCostCenterResourceParams(BaseModel):
    enterprise: str = Field(
        default="",
        description="Enterprise slug. Leave empty to auto-detect from synced data.",
    )
    cost_center_id: str = Field(description="The unique ID of the cost center")
    users: list[str] = Field(
        default_factory=list,
        description="GitHub usernames to assign to this cost center",
    )
    organizations: list[str] = Field(
        default_factory=list,
        description="Organization login names to assign to this cost center",
    )
    repositories: list[str] = Field(
        default_factory=list,
        description="Repositories in 'org/repo' format to assign to this cost center",
    )


class GetSyncedEnterpriseDataParams(BaseModel):
    pass


class RemoveCostCenterResourceParams(BaseModel):
    enterprise: str = Field(
        default="",
        description="Enterprise slug. Leave empty to auto-detect from synced data.",
    )
    cost_center_id: str = Field(description="The unique ID of the cost center")
    users: list[str] = Field(
        default_factory=list,
        description="GitHub usernames to remove from this cost center",
    )
    organizations: list[str] = Field(
        default_factory=list,
        description="Organization login names to remove from this cost center",
    )
    repositories: list[str] = Field(
        default_factory=list,
        description="Repositories in 'org/repo' format to remove from this cost center",
    )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_cost_center_tools(
    api_manager: APIManager | None = None,
    collector: DataCollector | None = None,
) -> list:
    """Create cost center management tools bound to the given APIManager and DataCollector."""

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_enterprises() -> list[dict]:
        """Load synced enterprise list from disk."""
        if collector is None:
            return []
        data = collector.load_latest("enterprise", "all")
        if isinstance(data, list):
            return data
        return []

    def _resolve_enterprise(requested: str) -> str | None:
        """
        Return the enterprise slug to use.
        - If `requested` is non-empty, return it as-is.
        - If empty, try to auto-detect:
            1. Check in-memory api_manager enterprises.
            2. Fall back to synced enterprise data from disk.
        Returns None if enterprise cannot be determined.
        """
        if requested:
            return requested

        # Try in-memory api_manager first
        if api_manager:
            enterprises = api_manager.get_all_enterprises()
            if len(enterprises) == 1:
                return enterprises[0]["slug"]
            if len(enterprises) > 1:
                return None  # ambiguous — caller must specify

        # Fall back to synced data
        enterprises = _load_enterprises()
        if len(enterprises) == 1:
            return enterprises[0]["slug"]
        return None

    def _enterprise_error(requested: str) -> str:
        """Build a helpful error message when enterprise can't be resolved."""
        enterprises = _load_enterprises()
        if api_manager:
            enterprises = api_manager.get_all_enterprises() or enterprises
        if enterprises:
            slugs = [e["slug"] for e in enterprises]
            return json.dumps({
                "error": (
                    "Multiple enterprises available. Please specify the enterprise slug. "
                    f"Available: {slugs}"
                )
            })
        return json.dumps({
            "error": (
                "No enterprise data found. "
                "Please run Sync Data first so enterprise information can be discovered, "
                "or provide the enterprise slug explicitly."
            )
        })

    def _get_api(enterprise: str):
        """Get an API client for the given enterprise slug."""
        if not api_manager:
            return None
        return api_manager.get_api_for_enterprise(enterprise)

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    @define_tool(
        description=(
            "List all synced enterprises and their cost centers from local data. "
            "Use this to discover available enterprise slugs and existing cost centers "
            "without making a live API call. Run Sync Data first to populate this data."
        )
    )
    def get_synced_enterprise_data(_: GetSyncedEnterpriseDataParams) -> str:
        enterprises = _load_enterprises()
        if not enterprises and api_manager:
            enterprises = api_manager.get_all_enterprises()

        if not enterprises:
            return json.dumps({
                "message": "No enterprise data found. Please run Sync Data first.",
                "enterprises": [],
            })

        result = []
        for ent in enterprises:
            slug = ent["slug"]
            cc_data = None
            if collector:
                cc_data = collector.load_latest("cost_centers", slug)
            result.append({
                "slug": slug,
                "name": ent.get("name", ""),
                "role": ent.get("role", ""),
                "cost_centers": cc_data.get("cost_centers", []) if cc_data else [],
                "cost_centers_total": cc_data.get("total", 0) if cc_data else 0,
            })

        return json.dumps({"enterprises": result, "total": len(result)})

    @define_tool(
        description=(
            "List all cost centers for a GitHub Enterprise from live API. "
            "Returns cost center IDs, names, state, and resource assignments. "
            "Use state='active' (default), 'archived', or 'all'. "
            "Leave enterprise empty to auto-detect from synced data."
        )
    )
    async def list_cost_centers(params: ListCostCentersParams) -> str:
        enterprise = _resolve_enterprise(params.enterprise)
        if not enterprise:
            return _enterprise_error(params.enterprise)

        if not api_manager:
            return json.dumps({"error": "No API manager available."})
        api = _get_api(enterprise)
        if not api:
            return json.dumps({"error": f"No API client found for enterprise '{enterprise}'."})

        url = f"/enterprises/{enterprise}/settings/billing/cost-centers"
        query: dict = {}
        if params.state and params.state != "all":
            query["state"] = params.state

        results = []
        page = 1
        while True:
            query["per_page"] = 100
            query["page"] = page
            resp = await api.client.get(url, params=query, headers=_VERSION_HEADER)
            if resp.status_code == 404:
                return json.dumps({"error": "Enterprise not found or Cost Centers API not available."})
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                batch = data
            else:
                batch = data.get("costCenters") or data.get("cost_centers") or []
            if not batch:
                break
            results.extend(batch)
            if len(batch) < 100:
                break
            page += 1

        return json.dumps({"enterprise": enterprise, "cost_centers": results, "total": len(results)})

    @define_tool(
        description=(
            "Create a new cost center for a GitHub Enterprise. "
            "Returns the created cost center object including its ID. "
            "This is a write operation — confirm the name before executing. "
            "Leave enterprise empty to auto-detect from synced data."
        )
    )
    async def create_cost_center(params: CreateCostCenterParams) -> str:
        enterprise = _resolve_enterprise(params.enterprise)
        if not enterprise:
            return _enterprise_error(params.enterprise)

        if not api_manager:
            return json.dumps({"error": "No API manager available."})
        api = _get_api(enterprise)
        if not api:
            return json.dumps({"error": f"No API client found for enterprise '{enterprise}'."})

        resp = await api.client.post(
            f"/enterprises/{enterprise}/settings/billing/cost-centers",
            json={"name": params.name},
            headers=_VERSION_HEADER,
        )
        if resp.status_code == 404:
            return json.dumps({"error": "Enterprise not found or Cost Centers API not available."})
        resp.raise_for_status()
        return json.dumps(resp.json())

    @define_tool(
        description=(
            "Get details for a specific cost center by its ID. "
            "Returns the cost center name, state, and all assigned resources (users, orgs, repos). "
            "Leave enterprise empty to auto-detect from synced data."
        )
    )
    async def get_cost_center(params: GetCostCenterParams) -> str:
        enterprise = _resolve_enterprise(params.enterprise)
        if not enterprise:
            return _enterprise_error(params.enterprise)

        if not api_manager:
            return json.dumps({"error": "No API manager available."})
        api = _get_api(enterprise)
        if not api:
            return json.dumps({"error": f"No API client found for enterprise '{enterprise}'."})

        url = f"/enterprises/{enterprise}/settings/billing/cost-centers/{params.cost_center_id}"
        resp = await api.client.get(url, headers=_VERSION_HEADER)
        if resp.status_code == 404:
            return json.dumps({"error": f"Cost center '{params.cost_center_id}' not found."})
        resp.raise_for_status()
        return json.dumps(resp.json())

    @define_tool(
        description=(
            "Update the name of an existing cost center. "
            "Returns the updated cost center object. "
            "This is a write operation — confirm the new name before executing. "
            "Leave enterprise empty to auto-detect from synced data."
        )
    )
    async def update_cost_center(params: UpdateCostCenterParams) -> str:
        enterprise = _resolve_enterprise(params.enterprise)
        if not enterprise:
            return _enterprise_error(params.enterprise)

        if not api_manager:
            return json.dumps({"error": "No API manager available."})
        api = _get_api(enterprise)
        if not api:
            return json.dumps({"error": f"No API client found for enterprise '{enterprise}'."})

        url = f"/enterprises/{enterprise}/settings/billing/cost-centers/{params.cost_center_id}"
        resp = await api.client.patch(url, json={"name": params.name}, headers=_VERSION_HEADER)
        if resp.status_code == 404:
            return json.dumps({"error": f"Cost center '{params.cost_center_id}' not found."})
        resp.raise_for_status()
        return json.dumps(resp.json())

    @define_tool(
        description=(
            "Delete (archive) a cost center by its ID. "
            "Archived cost centers are hidden from active listings but not permanently removed. "
            "This is a destructive operation — confirm the cost center ID before executing. "
            "Leave enterprise empty to auto-detect from synced data."
        )
    )
    async def delete_cost_center(params: DeleteCostCenterParams) -> str:
        enterprise = _resolve_enterprise(params.enterprise)
        if not enterprise:
            return _enterprise_error(params.enterprise)

        if not api_manager:
            return json.dumps({"error": "No API manager available."})
        api = _get_api(enterprise)
        if not api:
            return json.dumps({"error": f"No API client found for enterprise '{enterprise}'."})

        url = f"/enterprises/{enterprise}/settings/billing/cost-centers/{params.cost_center_id}"
        resp = await api.client.delete(url, headers=_VERSION_HEADER)
        if resp.status_code == 404:
            return json.dumps({"error": f"Cost center '{params.cost_center_id}' not found."})
        resp.raise_for_status()
        return json.dumps({"success": True, "enterprise": enterprise, "cost_center_id": params.cost_center_id})

    @define_tool(
        description=(
            "Add users, organizations, or repositories to a cost center. "
            "Provide at least one of: users (GitHub usernames), organizations (org logins), "
            "or repositories ('org/repo' format). "
            "This is a write operation — confirm the resources before executing. "
            "Leave enterprise empty to auto-detect from synced data."
        )
    )
    async def add_cost_center_resources(params: AddCostCenterResourceParams) -> str:
        enterprise = _resolve_enterprise(params.enterprise)
        if not enterprise:
            return _enterprise_error(params.enterprise)

        if not api_manager:
            return json.dumps({"error": "No API manager available."})
        api = _get_api(enterprise)
        if not api:
            return json.dumps({"error": f"No API client found for enterprise '{enterprise}'."})

        if not params.users and not params.organizations and not params.repositories:
            return json.dumps({"error": "Provide at least one of: users, organizations, repositories."})

        url = f"/enterprises/{enterprise}/settings/billing/cost-centers/{params.cost_center_id}/resource"
        body: dict = {}
        if params.users:
            body["users"] = params.users
        if params.organizations:
            body["organizations"] = params.organizations
        if params.repositories:
            body["repositories"] = params.repositories

        resp = await api.client.post(url, json=body, headers=_VERSION_HEADER)
        if resp.status_code == 404:
            return json.dumps({"error": f"Cost center '{params.cost_center_id}' not found."})
        resp.raise_for_status()
        return json.dumps(resp.json() if resp.content else {"success": True})

    @define_tool(
        description=(
            "Remove users, organizations, or repositories from a cost center. "
            "Provide at least one of: users (GitHub usernames), organizations (org logins), "
            "or repositories ('org/repo' format). "
            "This is a write operation — confirm the resources before executing. "
            "Leave enterprise empty to auto-detect from synced data."
        )
    )
    async def remove_cost_center_resources(params: RemoveCostCenterResourceParams) -> str:
        enterprise = _resolve_enterprise(params.enterprise)
        if not enterprise:
            return _enterprise_error(params.enterprise)

        if not api_manager:
            return json.dumps({"error": "No API manager available."})
        api = _get_api(enterprise)
        if not api:
            return json.dumps({"error": f"No API client found for enterprise '{enterprise}'."})

        if not params.users and not params.organizations and not params.repositories:
            return json.dumps({"error": "Provide at least one of: users, organizations, repositories."})

        url = f"/enterprises/{enterprise}/settings/billing/cost-centers/{params.cost_center_id}/resource"
        body: dict = {}
        if params.users:
            body["users"] = params.users
        if params.organizations:
            body["organizations"] = params.organizations
        if params.repositories:
            body["repositories"] = params.repositories

        resp = await api.client.request("DELETE", url, json=body, headers=_VERSION_HEADER)
        if resp.status_code == 404:
            return json.dumps({"error": f"Cost center '{params.cost_center_id}' not found."})
        resp.raise_for_status()
        return json.dumps(resp.json() if resp.content else {"success": True})

    return [
        get_synced_enterprise_data,
        list_cost_centers,
        create_cost_center,
        get_cost_center,
        update_cost_center,
        delete_cost_center,
        add_cost_center_resources,
        remove_cost_center_resources,
    ]
