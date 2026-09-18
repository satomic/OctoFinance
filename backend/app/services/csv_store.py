"""
Storage and ingestion for GitHub billing usage report CSVs.

Two CSV flavours are supported, and both are the *detailed* (per-user, per-row)
exports — never the summarized rollup, because every dashboard built on this
data aggregates per user, per org and per cost center:

- ``ai_usage``     — per-user, per-model AI credit consumption (has a ``model``
                     column). GitHub report type: ``ai_credit``.
- ``usage_report`` — per-user, per-SKU billed usage. GitHub report type:
                     ``detailed``.

Each flavour is kept in a single ``{type}_latest.csv``, mirroring how the JSON
datasets are stored as ``{org}_latest.json``. Ingestion merges **by date**: an
export is authoritative for every day it covers, so all stored rows for those
days are replaced by the incoming ones. That way a restated day (GitHub revising
usage after the fact) corrects itself instead of accumulating stale duplicates.

The same path is used whether the CSV was uploaded by hand from the billing UI
or pulled through the billing reports API.
"""

from __future__ import annotations

import csv
import io
import logging
import math
from pathlib import Path

from .data_collector import data_collector

logger = logging.getLogger(__name__)

CSV_TYPE_AI = "ai_usage"
CSV_TYPE_USAGE = "usage_report"

AI_USAGE_METRIC_FIELDS = ("input", "output", "cache_read", "cache_write")


def add_ai_usage_metrics(total: dict, record: dict) -> None:
    """Accumulate reported values, preserving unknown fields as None."""
    for field in AI_USAGE_METRIC_FIELDS:
        total.setdefault(field, None)
        try:
            value = float(record.get(field))
        except (TypeError, ValueError):
            continue
        if math.isfinite(value) and value >= 0:
            total[field] = (total[field] or 0) + value


# GitHub billing report type backing each CSV flavour. Both are row-level
# detail reports; "summarized" is deliberately not offered.
REPORT_TYPE_BY_CSV_TYPE = {
    CSV_TYPE_AI: "ai_credit",
    CSV_TYPE_USAGE: "detailed",
}

# Detail reports are capped at 31 days of history by GitHub.
MAX_REPORT_DAYS = 31


def get_csv_dir(csv_type: str = CSV_TYPE_AI) -> Path:
    if csv_type == CSV_TYPE_USAGE:
        return data_collector.data_dir / "usage_report_csv"
    return data_collector.data_dir / "ai_usage_csv"


def latest_csv_path(csv_type: str = CSV_TYPE_AI) -> Path:
    return get_csv_dir(csv_type) / f"{csv_type}_latest.csv"


def detect_csv_type(fieldnames: list[str]) -> str | None:
    """Detect whether a CSV is an AI usage report or a usage report based on columns.

    - AI Usage report (UBB): has a per-model breakdown, identified by a ``model``
      column alongside ``username``/``organization``.
    - Usage report: aggregated by ``product``/``sku``/``unit_type`` with no ``model`` column.
    """
    cols = set(fieldnames)
    if "model" in cols and "username" in cols and "organization" in cols:
        return CSV_TYPE_AI
    if "product" in cols and "sku" in cols and "unit_type" in cols:
        return CSV_TYPE_USAGE
    return None


def _read_csv(path: Path) -> tuple[list[str], list[dict]]:
    """Read one CSV into (fieldnames, rows). Missing or unreadable files are empty."""
    if not path.exists():
        return [], []
    try:
        with open(path, encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            fields = list(reader.fieldnames or [])
            return fields, [row for row in reader]
    except (OSError, csv.Error) as e:
        logger.warning("Could not read %s: %s", path, e)
        return [], []


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    """Write rows atomically so a crash can't truncate the single source of truth."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".csv.tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, restval="", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)


def _union_fields(base: list[str], extra: list[str]) -> list[str]:
    """Column union, preserving the existing order and appending anything new.

    The API export carries columns the older UI export did not (input, output,
    cache_read, cache_write), so merged files must widen rather than drop them.
    """
    merged = list(base)
    for f in extra:
        if f not in merged:
            merged.append(f)
    return merged


def _merge_by_date(
    old_fields: list[str], old_rows: list[dict],
    new_fields: list[str], new_rows: list[dict],
) -> tuple[list[str], list[dict], int]:
    """Replace every stored row whose date the incoming data covers.

    Returns (fieldnames, merged rows, number of superseded rows).
    """
    covered = {r.get("date") for r in new_rows if r.get("date")}
    kept = [r for r in old_rows if r.get("date") not in covered]
    superseded = len(old_rows) - len(kept)
    fields = _union_fields(old_fields, new_fields) if old_fields else list(new_fields)
    merged = sorted(kept + new_rows, key=lambda r: (r.get("date") or "", r.get("username") or ""))
    return fields, merged, superseded


def ensure_migrated(csv_type: str) -> int:
    """Fold pre-`_latest` per-upload CSVs into the single latest file.

    Older versions wrote one timestamped file per upload. Those are merged
    oldest-first (so newer exports win per date) and then removed, leaving the
    one file this module now maintains. Returns the number of files folded in.
    """
    csv_dir = get_csv_dir(csv_type)
    if not csv_dir.exists():
        return 0
    latest = latest_csv_path(csv_type)
    legacy = sorted(
        (p for p in csv_dir.glob("*.csv") if p != latest),
        key=lambda p: (p.stat().st_mtime, p.name),
    )
    if not legacy:
        return 0

    fields, rows = _read_csv(latest)
    for path in legacy:
        f, r = _read_csv(path)
        if not r:
            continue
        fields, rows, _ = _merge_by_date(fields, rows, f, r)

    _write_csv(latest, fields, rows)
    for path in legacy:
        path.unlink(missing_ok=True)
    logger.info("[csv_store] merged %d legacy %s file(s) into %s (%d rows)",
                len(legacy), csv_type, latest.name, len(rows))
    return len(legacy)


def load_all_csv_records(csv_type: str = CSV_TYPE_AI) -> list[dict]:
    """Load every stored record for the given CSV type."""
    ensure_migrated(csv_type)
    return _read_csv(latest_csv_path(csv_type))[1]


def _dedup_key(csv_type: str, row: dict) -> str:
    if csv_type == CSV_TYPE_AI:
        return f"{row.get('date')}|{row.get('username')}|{row.get('model')}|{row.get('organization')}"
    return f"{row.get('date')}|{row.get('username')}|{row.get('sku')}|{row.get('organization')}"


def ingest_csv_text(text: str) -> dict:
    """Validate and merge one CSV document into the type's ``_latest.csv``.

    The incoming export wins for every date it covers. Returns
    ``{status, csv_type, date_range, total_rows, new_rows, ...}`` or
    ``{error: ...}``.
    """
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    if not reader.fieldnames:
        return {"error": "CSV file has no headers."}

    csv_type = detect_csv_type(list(reader.fieldnames))
    if csv_type is None:
        return {"error": "Unrecognised CSV format. Expected an AI usage CSV (with a 'model' column) "
                         "or a usage report CSV (with 'product' and 'sku' columns)."}

    rows = list(reader)
    if not rows:
        return {"error": "CSV file is empty."}

    dates = [r.get("date", "") for r in rows if r.get("date")]
    date_min = min(dates) if dates else "unknown"
    date_max = max(dates) if dates else "unknown"

    ensure_migrated(csv_type)
    latest = latest_csv_path(csv_type)
    old_fields, old_rows = _read_csv(latest)
    old_keys = {_dedup_key(csv_type, r) for r in old_rows}

    fields, merged, superseded = _merge_by_date(
        old_fields, old_rows, list(reader.fieldnames), rows
    )
    _write_csv(latest, fields, merged)

    new_rows = sum(1 for r in rows if _dedup_key(csv_type, r) not in old_keys)
    unchanged = new_rows == 0 and superseded == len(rows)

    return {
        "status": "no_new_data" if unchanged else "ok",
        "csv_type": csv_type,
        "date_range": {"start": date_min, "end": date_max},
        "total_rows": len(rows),
        "new_rows": new_rows,
        "replaced_rows": superseded,
        "stored_rows": len(merged),
        "file_saved": latest.name,
    }


def scan_csv_type(csv_type: str) -> dict:
    """Summarise what has been ingested for one CSV type."""
    records = load_all_csv_records(csv_type)
    all_dates: list[str] = []
    all_orgs: set[str] = set()
    all_users: set[str] = set()
    for row in records:
        d = row.get("date", "")
        if d:
            all_dates.append(d)
        if row.get("organization"):
            all_orgs.add(row["organization"])
        if row.get("username"):
            all_users.add(row["username"])
    return {
        "has_data": bool(records),
        "latest_date": max(all_dates) if all_dates else None,
        "earliest_date": min(all_dates) if all_dates else None,
        "file_count": 1 if records else 0,
        "total_records": len(records),
        "orgs": sorted(all_orgs),
        "user_count": len(all_users),
    }
