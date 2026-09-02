"""
The sync job used by the startup and scheduled (cron) runs.

The Sync Data button only refreshes the JSON datasets, because it should stay
fast. Unattended runs have no such constraint and would otherwise leave the
billing report CSVs permanently stale, so they also pull those.
"""

from __future__ import annotations

import logging
from typing import Callable

from .csv_report_fetcher import fetch_latest
from .data_collector import data_collector

logger = logging.getLogger(__name__)


async def run_full_sync(log_fn: Callable[[str, str], None]) -> None:
    """Refresh every JSON dataset, then ingest the latest billing report CSVs."""
    await data_collector.sync_all(log_fn=log_fn)
    try:
        result = await fetch_latest(log_fn)
    except Exception as e:
        # A CSV failure must not mark the whole scheduled sync as failed.
        logger.exception("Scheduled billing report CSV fetch failed")
        log_fn("error", f"Billing report CSV fetch failed: {e}")
        return
    if result and result.get("errors"):
        log_fn("warn", f"Billing report CSV fetch finished with {len(result['errors'])} error(s)")
