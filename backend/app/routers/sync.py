"""
Data sync router - triggers data collection from GitHub API.
Supports background sync with real-time SSE log streaming.
"""

import asyncio
import json

from fastapi import APIRouter, Query
from starlette.responses import StreamingResponse

from ..services.api_manager import api_manager
from ..services.data_collector import DataCollector, data_collector, create_session_collector
from ..services.session_manager import SESSIONS_DIR
from ..services.sync_manager import sync_manager

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


@router.get("/sync-stream")
async def sync_stream():
    """SSE endpoint for real-time sync log streaming.
    Stays open and pushes events as syncs occur.
    Note: Uses /sync-stream (not /sync/stream) to avoid route conflict with POST /sync/{org}."""

    async def event_generator():
        queue = sync_manager.subscribe()
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    # Keepalive ping to prevent connection timeout
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            sync_manager.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/sync")
async def sync_all(session_id: str | None = Query(default=None)):
    """Trigger a full data sync for all discovered organizations.
    Returns immediately; sync runs in background with logs streamed via /sync/stream."""
    if sync_manager.is_syncing:
        return {"status": "already_syncing"}

    collectors = _get_collectors(session_id)

    async def _do_sync(log_fn):
        for collector in collectors:
            await collector.sync_all(log_fn=log_fn)

    sync_manager.run_in_background(_do_sync)
    return {"status": "started"}


@router.post("/sync/{org}")
async def sync_org(org: str, session_id: str | None = Query(default=None)):
    """Trigger data sync for a specific organization.
    Returns immediately; sync runs in background."""
    if sync_manager.is_syncing:
        return {"status": "already_syncing"}

    collectors = _get_collectors(session_id)

    async def _do_sync(log_fn):
        for collector in collectors:
            await collector.sync_org(org, log_fn=log_fn)

    sync_manager.run_in_background(_do_sync)
    return {"status": "started"}


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
        has_usage_users = data_collector.load_latest("usage_users", org_name) is not None
        has_metrics = data_collector.load_latest("metrics", org_name) is not None
        has_premium_requests = data_collector.load_latest("premium_requests", org_name) is not None
        orgs_with_data.append({
            "org": org_name,
            "has_seats": has_seats,
            "has_billing": has_billing,
            "has_usage": has_usage,
            "has_usage_users": has_usage_users,
            "has_metrics": has_metrics,
            "has_premium_requests": has_premium_requests,
        })

    users = api_manager.get_discovered_users()
    user_logins = [u.get("login", "") for u in users.values()]

    return {
        "users": user_logins,
        "total_orgs": len(all_orgs),
        "orgs": orgs_with_data,
        "is_syncing": sync_manager.is_syncing,
    }
