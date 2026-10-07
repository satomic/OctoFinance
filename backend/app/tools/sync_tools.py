"""
Data sync tool for the AI engine.

Most read tools (and name resolution in some write tools, e.g.
create_cost_center_budget) work from the cache written by Sync Data. Without a
way to refresh it, anything created live during a chat stays invisible to those
tools until an admin clicks Sync Data. This tool runs the same sync the button
does, through the shared SyncManager, so progress shows in the Console and a
sync never runs twice at once.
"""

import json
import time

from pydantic import BaseModel, Field

from copilot import define_tool

from ..services.data_collector import data_collector
from ..services.sync_manager import sync_manager

DATASETS = ("cost_centers", "budgets", "enterprise_teams")

# A narrow dataset sync takes seconds; a full sync can take minutes on large estates.
WAIT_TIMEOUT_SECONDS = 600
# A sync started elsewhere (startup, cron) may include a billing CSV fetch that
# runs for many minutes, so chat only waits this long for it before refreshing
# the requested enterprise dataset itself.
BUSY_WAIT_SECONDS = 60


class SyncDataParams(BaseModel):
    dataset: str = Field(
        default="all",
        description=(
            "What to refresh: 'cost_centers', 'budgets' or 'enterprise_teams' for a fast "
            "enterprise-scoped refresh, or 'all' for the full Sync Data (every org's seats, "
            "usage, billing and AI credits, plus all enterprise data). Prefer the narrowest "
            "dataset that covers what changed."
        ),
    )
    org: str = Field(
        default="",
        description="Only with dataset='all': sync just this organization instead of everything.",
    )


def create_sync_tools() -> list:
    """Create the sync tool. Syncs the global cache, exactly like the Sync Data button."""

    @define_tool(
        description=(
            "Refresh OctoFinance's cached GitHub data (the same as the Sync Data button) and wait "
            "for it to finish. Call this when cached data is missing or stale, in particular right "
            "after a live write such as create_cost_center, add_cost_center_resources or "
            "create_enterprise_team, before using a tool that reads the cache (for example "
            "create_cost_center_budget, get_synced_enterprise_data, get_all_budgets summaries). "
            "Does not fetch billing report CSVs."
        )
    )
    async def sync_data(params: SyncDataParams) -> str:
        dataset = (params.dataset or "all").strip().lower()
        org = params.org.strip()
        if dataset != "all" and dataset not in DATASETS:
            return json.dumps({
                "error": f"Unknown dataset '{params.dataset}'. Use 'all' or one of {list(DATASETS)}."
            })
        if org and dataset != "all":
            return json.dumps({"error": "'org' can only be combined with dataset='all'."})

        if sync_manager.is_syncing:
            finished = await sync_manager.wait_until_idle(BUSY_WAIT_SECONDS)
            if not finished and dataset in DATASETS:
                # The other sync is probably busy with CSVs. An enterprise dataset refresh
                # is a cheap, idempotent read + cache write, so do it directly.
                started_at = time.monotonic()
                sync_manager.log("info", f"[chat] Refreshing {dataset} while another sync is running")
                summary = await data_collector.sync_dataset(dataset, log_fn=sync_manager.log)
                return _result("completed", dataset, org, started_at, [summary])
            return json.dumps({
                "status": "already_running",
                "finished": finished,
                "message": (
                    "Another sync was already running"
                    + (" and has now finished. " if finished else " and is still in progress. ")
                    + "It may have started before your latest change; if the data you need is "
                    "still missing, call sync_data again."
                ),
            })

        summaries: list[dict] = []

        async def _do_sync(log_fn):
            if dataset in DATASETS:
                summaries.append(await data_collector.sync_dataset(dataset, log_fn=log_fn))
            elif org:
                summaries.append(await data_collector.sync_org(org, log_fn=log_fn))
            else:
                summaries.extend(await data_collector.sync_all(log_fn=log_fn))

        started_at = time.monotonic()
        if not sync_manager.run_in_background(_do_sync, trigger="chat"):
            return json.dumps({"status": "already_running", "message": "Another sync just started; try again shortly."})
        finished = await sync_manager.wait_until_idle(WAIT_TIMEOUT_SECONDS)
        return _result("completed" if finished else "still_running", dataset, org, started_at, summaries)

    return [sync_data]


def _result(status: str, dataset: str, org: str, started_at: float, summaries: list[dict]) -> str:
    synced = [item for s in summaries for item in s.get("synced", [])]
    errors = [item for s in summaries for item in s.get("errors", [])]
    return json.dumps({
        "status": status,
        "dataset": dataset,
        "org": org or None,
        "duration_seconds": round(time.monotonic() - started_at, 1),
        "synced_count": len(synced),
        "synced": synced[:50],
        "errors": errors[:20],
        "error_count": len(errors),
    }, default=str)
