"""
Data sync router - triggers data collection from GitHub API.
"""

from fastapi import APIRouter, Query

from ..services.api_manager import api_manager
from ..services.data_collector import DataCollector, data_collector, create_session_collector
from ..services.session_manager import SESSIONS_DIR

router = APIRouter(tags=["sync"])


def _get_collectors(session_id: str | None) -> list[DataCollector]:
    """Return the list of collectors to sync into.
    Always includes the global collector; adds a session collector when session_id is given."""
    collectors = [data_collector]
    if session_id:
        session_dir = SESSIONS_DIR / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        collectors.append(create_session_collector(session_dir, api_manager=api_manager))
    return collectors


@router.post("/sync")
async def sync_all(session_id: str | None = Query(default=None)):
    """Trigger a full data sync for all discovered organizations.
    If session_id is provided, also sync into that session's directory."""
    collectors = _get_collectors(session_id)
    results = []
    for collector in collectors:
        result = await collector.sync_all()
        if not results:
            results = result  # Return the first (global) result
    return {"status": "completed", "results": results}


@router.post("/sync/{org}")
async def sync_org(org: str, session_id: str | None = Query(default=None)):
    """Trigger data sync for a specific organization.
    If session_id is provided, also sync into that session's directory."""
    collectors = _get_collectors(session_id)
    result = None
    for collector in collectors:
        r = await collector.sync_org(org)
        if result is None:
            result = r  # Return the first (global) result
    return {"status": "completed", "result": result}


@router.get("/sync/status")
async def sync_status():
    """Get current discovery and sync status."""
    all_orgs = api_manager.get_all_orgs()
    orgs_with_data = []
    for org_info in all_orgs:
        org_name = org_info["login"]
        has_seats = data_collector.load_latest("seats", org_name) is not None
        has_billing = data_collector.load_latest("billing", org_name) is not None
        has_usage = data_collector.load_latest("usage", org_name) is not None
        has_metrics = data_collector.load_latest("metrics", org_name) is not None
        orgs_with_data.append({
            "org": org_name,
            "has_seats": has_seats,
            "has_billing": has_billing,
            "has_usage": has_usage,
            "has_metrics": has_metrics,
        })

    users = api_manager.get_discovered_users()
    user_logins = [u.get("login", "") for u in users.values()]

    return {
        "users": user_logins,
        "total_orgs": len(all_orgs),
        "orgs": orgs_with_data,
    }
