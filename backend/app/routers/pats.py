"""
PAT management router - CRUD for GitHub Personal Access Tokens.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services.api_manager import api_manager
from ..services.data_collector import data_collector
from ..services.pat_manager import pat_manager
from ..services.sync_manager import sync_manager

router = APIRouter(tags=["pats"])


class AddPATRequest(BaseModel):
    label: str
    token: str
    enterprise_slugs: list[str] = []


class UpdatePATRequest(BaseModel):
    label: str


class UpdateSettingsRequest(BaseModel):
    auto_sync_on_startup: bool | None = None
    sync_cron: str | None = None


@router.get("/pats")
async def list_pats():
    """List all configured PATs (tokens masked)."""
    return {"pats": pat_manager.get_all_masked()}


@router.post("/pats")
async def add_pat(request: AddPATRequest):
    """Add a new PAT, validate it, discover orgs. Data sync runs in background."""
    token = request.token.strip()
    label = request.label.strip()

    if not token:
        raise HTTPException(status_code=400, detail="Token is required")

    # Normalize enterprise slugs (strip whitespace, remove empties)
    enterprise_slugs = [s.strip() for s in request.enterprise_slugs if s.strip()]

    # Add to persistent storage
    try:
        pat = pat_manager.add(label, token, enterprise_slugs=enterprise_slugs)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Discover user and orgs via API
    try:
        user = await api_manager.add_and_discover(pat["id"])
    except ValueError as e:
        # Invalid token - remove the PAT we just added
        pat_manager.remove(pat["id"])
        raise HTTPException(status_code=400, detail=str(e))

    # Kick off background sync for newly discovered orgs
    updated_pat = pat_manager.find_by_id(pat["id"])
    if updated_pat and updated_pat.get("orgs"):
        orgs_to_sync = list(updated_pat["orgs"])

        async def _sync_new_orgs(log_fn):
            for org in orgs_to_sync:
                await data_collector.sync_org(org, log_fn=log_fn)

        sync_manager.run_in_background(_sync_new_orgs)

    # Return masked PAT info immediately (sync continues in background)
    masked = pat_manager.get_all_masked()
    new_masked = next((p for p in masked if p["id"] == pat["id"]), None)

    return {
        "pat": new_masked,
        "user": user.get("login", ""),
    }


@router.put("/pats/{pat_id}")
async def update_pat(pat_id: str, request: UpdatePATRequest):
    """Update a PAT's label."""
    result = pat_manager.update(pat_id, label=request.label.strip())
    if not result:
        raise HTTPException(status_code=404, detail="PAT not found")
    # Return masked version
    masked = pat_manager.get_all_masked()
    updated = next((p for p in masked if p["id"] == pat_id), None)
    return {"pat": updated}


@router.delete("/pats/{pat_id}")
async def delete_pat(pat_id: str):
    """Remove a PAT and clean up its API instance."""
    if not pat_manager.find_by_id(pat_id):
        raise HTTPException(status_code=404, detail="PAT not found")

    # Remove API instance
    await api_manager.remove_api(pat_id)

    # Remove from persistent storage
    pat_manager.remove(pat_id)

    return {"deleted": True, "pat_id": pat_id}


# ------------------------------------------------------------------
# App settings
# ------------------------------------------------------------------

@router.get("/settings")
async def get_settings():
    """Get app settings (sync config, etc.)."""
    return pat_manager.get_settings()


@router.put("/settings")
async def update_settings(request: UpdateSettingsRequest):
    """Update app settings. Re-schedules cron sync if sync_cron changed."""
    kwargs = {}
    if request.auto_sync_on_startup is not None:
        kwargs["auto_sync_on_startup"] = request.auto_sync_on_startup
    if request.sync_cron is not None:
        kwargs["sync_cron"] = request.sync_cron

    settings = pat_manager.update_settings(**kwargs)

    # Re-schedule cron if sync_cron was updated
    if request.sync_cron is not None:
        sync_manager.stop_cron_scheduler()
        if request.sync_cron.strip():
            sync_manager.start_cron_scheduler(
                request.sync_cron.strip(),
                lambda log_fn: data_collector.sync_all(log_fn=log_fn),
            )

    return settings
