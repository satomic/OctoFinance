"""
Storage and ingestion for GitHub billing usage report CSVs.

Two CSV flavours are supported, and both are the *detailed* (per-user, per-row)
exports — never the summarized rollup, because every dashboard built on this
data aggregates per user, per org and per cost center:

- ``ai_usage``     — per-user, per-model AI credit consumption (has a ``model``
                     column). GitHub report type: ``ai_credit``.
- ``usage_report`` — per-user, per-SKU billed usage. GitHub report type:
                     ``detailed``.

The same ingestion path is used whether the CSV was uploaded by hand from the
billing UI export or pulled through the billing reports API, so both sources
land in the same directories and are deduplicated against each other.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from pathlib import Path

from .data_collector import data_collector

CSV_TYPE_AI = "ai_usage"
CSV_TYPE_USAGE = "usage_report"

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


def load_all_csv_records(csv_type: str = CSV_TYPE_AI) -> list[dict]:
    """Load all CSV records from the given type's directory."""
    csv_dir = get_csv_dir(csv_type)
    if not csv_dir.exists():
        return []
    records: list[dict] = []
    for f in sorted(csv_dir.glob("*.csv")):
        with open(f, encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                records.append(row)
    return records


def _dedup_key(csv_type: str, row: dict) -> str:
    if csv_type == CSV_TYPE_AI:
        return f"{row.get('date')}|{row.get('username')}|{row.get('model')}|{row.get('organization')}"
    return f"{row.get('date')}|{row.get('username')}|{row.get('sku')}|{row.get('organization')}"


def ingest_csv_text(text: str) -> dict:
    """Validate, deduplicate and persist one CSV document.

    Returns the same result shape the upload endpoint has always returned:
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

    csv_dir = get_csv_dir(csv_type)
    csv_dir.mkdir(parents=True, exist_ok=True)

    existing_keys: set[str] = set()
    for f in csv_dir.glob("*.csv"):
        with open(f, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                existing_keys.add(_dedup_key(csv_type, row))

    new_rows = [row for row in rows if _dedup_key(csv_type, row) not in existing_keys]

    if not new_rows:
        return {
            "status": "no_new_data",
            "csv_type": csv_type,
            "date_range": {"start": date_min, "end": date_max},
            "total_rows": len(rows),
            "new_rows": 0,
        }

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    out_path = csv_dir / f"{csv_type}_{ts}.csv"
    fieldnames = list(reader.fieldnames)
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(new_rows)

    return {
        "status": "ok",
        "csv_type": csv_type,
        "date_range": {"start": date_min, "end": date_max},
        "total_rows": len(rows),
        "new_rows": len(new_rows),
        "duplicates_skipped": len(rows) - len(new_rows),
        "file_saved": out_path.name,
    }


def scan_csv_type(csv_type: str) -> dict:
    """Summarise what has been ingested for one CSV type."""
    csv_dir = get_csv_dir(csv_type)
    csv_files = sorted(csv_dir.glob("*.csv")) if csv_dir.exists() else []
    total_records = 0
    all_dates: list[str] = []
    all_orgs: set[str] = set()
    all_users: set[str] = set()
    for f in csv_files:
        with open(f, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                total_records += 1
                d = row.get("date", "")
                if d:
                    all_dates.append(d)
                if row.get("organization"):
                    all_orgs.add(row["organization"])
                if row.get("username"):
                    all_users.add(row["username"])
    return {
        "has_data": total_records > 0,
        "latest_date": max(all_dates) if all_dates else None,
        "earliest_date": min(all_dates) if all_dates else None,
        "file_count": len(csv_files),
        "total_records": total_records,
        "orgs": sorted(all_orgs),
        "user_count": len(all_users),
    }
