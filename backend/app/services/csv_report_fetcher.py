"""
Pulls billing usage report CSVs from the GitHub billing reports API.

This replaces the manual "request a report in the UI, wait for the email,
download the CSV, upload it here" loop with a single API-driven flow:

    POST   /enterprises/{ent}/settings/billing/reports      -> export id
    GET    /enterprises/{ent}/settings/billing/reports/{id} -> poll until completed
    GET    <signed blob url>                                -> the CSV itself

Only the row-level *detail* report types are requested (``detailed`` and
``ai_credit``); the summarized rollup has no per-user breakdown and cannot feed
the dashboards. Downloaded CSVs go through the exact same ingestion path as a
manual upload, so the two sources deduplicate against each other.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Callable

from .api_manager import api_manager
from .csv_store import (
    CSV_TYPE_AI,
    CSV_TYPE_USAGE,
    MAX_REPORT_DAYS,
    REPORT_TYPE_BY_CSV_TYPE,
    ingest_csv_text,
)
from .pat_manager import DEFAULT_SETTINGS, pat_manager

logger = logging.getLogger(__name__)

ALL_CSV_TYPES = (CSV_TYPE_AI, CSV_TYPE_USAGE)


def _poll_settings() -> tuple[int, int]:
    """Current (poll interval seconds, give-up timeout seconds) for one report.

    Read per run rather than at import so a change in Settings takes effect
    without restarting the backend.
    """
    s = pat_manager.get_settings()

    def _int(key: str) -> int:
        try:
            return int(s.get(key) or DEFAULT_SETTINGS[key])
        except (TypeError, ValueError):
            return int(DEFAULT_SETTINGS[key])

    return _int("csv_fetch_poll_seconds"), _int("csv_fetch_timeout_minutes") * 60

# State of the current/most recent fetch, served by GET /api/data/fetch-csv/status.
# Carries a job_id so a client can tell "the run I started" from a stale result,
# and so a reloaded page can reattach to a run that is still in flight.
_job: dict = {
    "job_id": "",
    "running": False,
    "step": 0,
    "total_steps": 0,
    "phase": "",
    "started_at": None,
    "finished_at": None,
    "date_range": None,
    "enterprises": [],
    "results": [],
    "new_rows": 0,
    "errors": [],
}


def get_job() -> dict:
    return dict(_job)


def begin_job(enterprises: list[str], start_date: str, end_date: str,
              csv_types: list[str]) -> dict:
    """Mark a job as running and return its record.

    Called synchronously by the request handler before the background task is
    scheduled, so a client polling immediately can never observe the previous
    run's state and mistake it for this one's.
    """
    global _job
    _job = {
        "job_id": uuid.uuid4().hex,
        "running": True,
        "step": 0,
        "total_steps": len(enterprises) * len(csv_types),
        "phase": "starting",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "date_range": {"start": start_date, "end": end_date},
        "enterprises": enterprises,
        "results": [],
        "new_rows": 0,
        "errors": [],
    }
    return dict(_job)


def default_date_range() -> tuple[str, str]:
    """Default to the widest window the detail reports allow, ending today (UTC)."""
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=MAX_REPORT_DAYS - 1)
    return start.isoformat(), end.isoformat()


def validate_date_range(start_date: str, end_date: str) -> str | None:
    """Return an error message if the range is unusable, otherwise None."""
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError:
        return "Dates must be in YYYY-MM-DD format."
    if end < start:
        return "end_date must not be earlier than start_date."
    span = (end - start).days + 1
    if span > MAX_REPORT_DAYS:
        return f"Detail reports cover at most {MAX_REPORT_DAYS} days; requested {span}."
    return None


def _matches(report: dict, report_type: str, start_date: str, end_date: str) -> bool:
    return (
        report.get("report_type") == report_type
        and report.get("start_date") == start_date
        and report.get("end_date") == end_date
    )


async def _await_completion(api, enterprise: str, report_id: str, log_fn) -> dict | None:
    """Poll one export until it completes. Returns the completed report or None."""
    interval, timeout = _poll_settings()
    loop = asyncio.get_running_loop()
    started = loop.time()
    deadline = started + timeout
    last_logged = 0
    while loop.time() < deadline:
        await asyncio.sleep(interval)
        report = await api.get_billing_report(enterprise, report_id)
        elapsed = int(loop.time() - started)
        if report is None:
            # Transient read failure; the export itself is still running.
            continue
        status = report.get("status")
        if status == "completed":
            log_fn("info", f"[{enterprise}] report ready after {elapsed}s")
            return report
        if status == "failed":
            log_fn("error", f"[{enterprise}] report {report_id} failed on GitHub's side")
            return None
        if elapsed - last_logged >= 60:
            last_logged = elapsed
            log_fn("info", f"[{enterprise}] still generating ({elapsed}s elapsed)")
    log_fn("error", f"[{enterprise}] report {report_id} still processing after "
                    f"{timeout // 60} min, giving up")
    return None


async def _fetch_one(api, enterprise: str, csv_type: str,
                     start_date: str, end_date: str, log_fn) -> dict:
    report_type = REPORT_TYPE_BY_CSV_TYPE[csv_type]
    log_fn("info", f"[{enterprise}] requesting '{report_type}' report {start_date} ~ {end_date}")

    created = await api.create_billing_report(enterprise, report_type, start_date, end_date)
    report_id = created.get("id")

    if not report_id:
        detail = created.get("error") or "unknown error"
        # Only one export may run at a time per enterprise. If ours matches the
        # one already in flight, adopt it instead of failing the whole run.
        if created.get("status_code") == 409:
            in_flight = [
                r for r in await api.list_billing_reports(enterprise)
                if r.get("status") == "processing"
            ]
            adopted = next(
                (r for r in in_flight if _matches(r, report_type, start_date, end_date)),
                None,
            )
            if adopted:
                report_id = adopted.get("id")
                log_fn("info", f"[{enterprise}] an identical export is already running, "
                               f"waiting on {report_id}")
            else:
                running = ", ".join(f"{r.get('report_type')} ({r.get('id')})" for r in in_flight)
                return {"enterprise": enterprise, "csv_type": csv_type,
                        "error": f"Another export is already in progress: {running or detail}"}
        else:
            return {"enterprise": enterprise, "csv_type": csv_type, "error": detail}

    report = await _await_completion(api, enterprise, report_id, log_fn)
    if not report:
        return {"enterprise": enterprise, "csv_type": csv_type,
                "error": "Report did not complete."}

    urls = report.get("download_urls") or []
    if not urls:
        return {"enterprise": enterprise, "csv_type": csv_type,
                "error": "Report completed but returned no download URLs."}

    parts = await api.download_billing_report_csv(urls)
    if not parts:
        return {"enterprise": enterprise, "csv_type": csv_type,
                "error": "Could not download the report CSV."}

    total_rows = new_rows = replaced_rows = stored_rows = 0
    dates: list[str] = []
    for text in parts:
        result = ingest_csv_text(text)
        if result.get("error"):
            return {"enterprise": enterprise, "csv_type": csv_type, "error": result["error"]}
        total_rows += result.get("total_rows", 0)
        new_rows += result.get("new_rows", 0)
        replaced_rows += result.get("replaced_rows", 0)
        stored_rows = result.get("stored_rows", stored_rows)
        rng = result.get("date_range") or {}
        dates += [d for d in (rng.get("start"), rng.get("end")) if d and d != "unknown"]

    log_fn("info", f"[{enterprise}] {csv_type}: merged {total_rows} rows "
                   f"({new_rows} new, {replaced_rows} superseded), {stored_rows} stored")
    return {
        "enterprise": enterprise,
        "csv_type": csv_type,
        "total_rows": total_rows,
        "new_rows": new_rows,
        "replaced_rows": replaced_rows,
        "stored_rows": stored_rows,
        "date_range": {"start": min(dates), "end": max(dates)} if dates else None,
    }


async def fetch_and_ingest(
    enterprises: list[str],
    start_date: str,
    end_date: str,
    csv_types: list[str],
    log_fn: Callable[[str, str], None],
) -> dict:
    """Fetch the requested detail reports for each enterprise and ingest them."""
    results: list[dict] = []
    try:
        for enterprise in enterprises:
            api = api_manager.get_api_for_enterprise(enterprise)
            if api is None:
                results.append({"enterprise": enterprise,
                                "error": "No PAT configured with access to this enterprise."})
                continue
            # Sequential per enterprise: GitHub allows only one export in flight.
            for csv_type in csv_types:
                _job["phase"] = f"{enterprise}/{csv_type}"
                try:
                    results.append(await _fetch_one(api, enterprise, csv_type,
                                                    start_date, end_date, log_fn))
                except Exception as e:
                    logger.exception("CSV report fetch failed for %s/%s", enterprise, csv_type)
                    results.append({"enterprise": enterprise, "csv_type": csv_type, "error": str(e)})
                _job["step"] += 1
                _job["results"] = list(results)
    finally:
        _job.update({
            "running": False,
            "phase": "done",
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "results": results,
            "new_rows": sum(r.get("new_rows", 0) for r in results),
            "errors": [r for r in results if r.get("error")],
        })
    return dict(_job)


def resolve_enterprises() -> list[str]:
    """Every enterprise the configured PATs can reach."""
    return [e["slug"] for e in api_manager.get_all_enterprises()]


async def fetch_latest(log_fn: Callable[[str, str], None]) -> dict | None:
    """Pull the newest detail reports for every enterprise, using the default window.

    Shared by the Fetch CSV button and the startup/scheduled syncs. Returns None
    when there is no enterprise to fetch for.
    """
    enterprises = resolve_enterprises()
    if not enterprises:
        log_fn("info", "No enterprise configured; skipping billing report CSV fetch")
        return None
    start_date, end_date = default_date_range()
    csv_types = list(ALL_CSV_TYPES)
    begin_job(enterprises, start_date, end_date, csv_types)
    return await fetch_and_ingest(enterprises, start_date, end_date, csv_types, log_fn)
