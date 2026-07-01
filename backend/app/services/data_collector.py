"""
Data collector service - fetches data from GitHub API and saves as JSON files.
Supports per-session data directories with fallback to global directory.
Uses APIManager to route API calls to the correct PAT.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from ..config import COPILOT_PRICING, config

if TYPE_CHECKING:
    from .api_manager import APIManager
    from .github_api import GitHubAPI

# Type alias for the optional log callback: log_fn(level, message)
LogFn = Callable[[str, str], None] | None


def enterprise_pseudo_org(slug: str) -> str:
    """Return the pseudo-org key used to store enterprise-level Copilot data.

    Used for enterprises that have no organizations (Copilot granted purely via
    enterprise teams, or organization scanning was disabled for the owning PAT).
    Storing enterprise data under this key lets it flow through the existing
    org-keyed dashboard aggregation (seats/billing/usage/usage_users/ai_credits)
    without any changes to that logic.
    """
    return f"{slug}-enterprise"


# ---------------------------------------------------------------------------
# `_latest.json` merge strategies
#
# GitHub's Copilot usage-metrics/legacy-metrics endpoints always return a
# rolling window (the latest 28 days for usage reports, the default window for
# legacy metrics) — never the full history. If every sync simply overwrote
# `_latest.json` with the freshly fetched payload, the dashboard could never
# show data older than ~28 days even when synced daily for months.
#
# To fix this, categories with day-level granularity merge the newly fetched
# data into whatever was previously stored in `_latest.json`: days present in
# the new payload always win (freshest data), while days no longer covered by
# the new rolling window are preserved from the previous file. This lets
# `_latest.json` grow into a full history over time through incremental syncs.
# ---------------------------------------------------------------------------

def _merge_usage_report(old_data: dict | list | None, new_data: dict | list) -> dict | list:
    """Merge an org/enterprise-level 28-day usage report (category 'usage').

    Each payload has a ``records`` list (normally a single record) with a
    ``day_totals`` array — one entry per day in the report window. Merges
    `day_totals` across old and new data keyed by ``day``; new data wins on
    overlapping days, older days are preserved.
    """
    if not isinstance(new_data, dict):
        return new_data
    if not isinstance(old_data, dict) or not old_data.get("records"):
        return new_data

    def collect(data: dict) -> tuple[dict[str, dict], dict]:
        days: dict[str, dict] = {}
        meta: dict = {}
        for rec in data.get("records", []) or []:
            meta = {k: v for k, v in rec.items() if k != "day_totals"}
            for dt in rec.get("day_totals", []) or []:
                day = dt.get("day")
                if day:
                    days[day] = dt
        return days, meta

    old_days, old_meta = collect(old_data)
    new_days, new_meta = collect(new_data)
    if not old_days:
        return new_data

    merged_days = {**old_days, **new_days}
    sorted_keys = sorted(merged_days.keys())

    merged_record = {**old_meta, **new_meta}
    merged_record["day_totals"] = [merged_days[d] for d in sorted_keys]
    if sorted_keys:
        merged_record["report_start_day"] = sorted_keys[0]
        merged_record["report_end_day"] = sorted_keys[-1]

    merged = {**old_data, **new_data}
    merged["records"] = [merged_record]
    merged["total_records"] = 1
    if sorted_keys:
        merged["report_start_day"] = sorted_keys[0]
        merged["report_end_day"] = sorted_keys[-1]
    return merged


def _merge_usage_users_report(old_data: dict | list | None, new_data: dict | list) -> dict | list:
    """Merge a user-level 28-day usage report (category 'usage_users').

    Records are flat (day, user) rows. Merges old and new records keyed by
    ``(day, user_login or user_id)``; new data wins on overlapping keys, older
    (day, user) rows outside the new rolling window are preserved.
    """
    if not isinstance(new_data, dict):
        return new_data
    if not isinstance(old_data, dict) or not old_data.get("records"):
        return new_data

    def rec_key(rec: dict) -> tuple:
        return (rec.get("day", ""), rec.get("user_login") or rec.get("user_id") or "")

    merged_map: dict[tuple, dict] = {}
    for rec in old_data.get("records", []) or []:
        merged_map[rec_key(rec)] = rec
    for rec in new_data.get("records", []) or []:
        merged_map[rec_key(rec)] = rec

    merged_records = sorted(
        merged_map.values(),
        key=lambda r: (r.get("day", ""), r.get("user_login", "")),
    )
    days = [r.get("day") for r in merged_records if r.get("day")]

    merged = {**old_data, **new_data}
    merged["records"] = merged_records
    merged["total_records"] = len(merged_records)
    if days:
        merged["report_start_day"] = min(days)
        merged["report_end_day"] = max(days)
    return merged


def _merge_metrics_list(old_data: dict | list | None, new_data: dict | list) -> dict | list:
    """Merge legacy Copilot metrics entries (category 'metrics').

    The legacy `/copilot/metrics` endpoint returns a list of daily entries,
    each with a top-level ``date`` key, and (like the usage-report endpoints)
    only covers a rolling window by default. Merges old and new entries keyed
    by ``date``; new data wins on overlapping dates, older dates are preserved.
    """
    if not isinstance(new_data, list):
        return new_data
    if not isinstance(old_data, list) or not old_data:
        return new_data

    merged: dict[str, dict] = {}
    for entry in old_data:
        if isinstance(entry, dict) and entry.get("date"):
            merged[entry["date"]] = entry
    for entry in new_data:
        if isinstance(entry, dict) and entry.get("date"):
            merged[entry["date"]] = entry
    if not merged:
        return new_data
    return [merged[d] for d in sorted(merged.keys())]


# Maps category -> merge function used when updating `_latest.json`. Categories
# not listed here (billing, seats, enterprise, cost_centers, budgets, ai_credits)
# represent current point-in-time state and are overwritten as before.
_LATEST_MERGE_STRATEGIES: dict[str, Callable[[dict | list | None, dict | list], dict | list]] = {
    "usage": _merge_usage_report,
    "usage_users": _merge_usage_users_report,
    "metrics": _merge_metrics_list,
}


class DataCollector:
    """Collects Copilot data from GitHub API and stores as JSON files.

    Args:
        data_dir: Primary directory for reading/writing data.
        fallback_dir: Optional fallback directory for reads when primary has no data.
        api_manager: Optional APIManager for routing API calls per org.
    """

    def __init__(
        self,
        data_dir: Path | None = None,
        fallback_dir: Path | None = None,
        api_manager: APIManager | None = None,
    ):
        self._data_dir = data_dir or config.data_dir
        self._fallback_dir = fallback_dir
        self._api_manager = api_manager

    @property
    def data_dir(self) -> Path:
        return self._data_dir

    def set_api_manager(self, api_manager: APIManager):
        """Set the API manager (useful for deferred initialization)."""
        self._api_manager = api_manager

    def _get_api_for_org(self, org: str) -> GitHubAPI | None:
        """Get the GitHubAPI instance for an org via api_manager."""
        if self._api_manager:
            return self._api_manager.get_api_for_org(org)
        return None

    def _save_json(self, category: str, org: str, data: dict | list) -> Path:
        """Save data to a JSON file. Returns the file path.

        Writes an immutable timestamped snapshot containing exactly the
        newly-fetched payload, then updates `_latest.json` separately: for
        categories with a registered merge strategy (see
        `_LATEST_MERGE_STRATEGIES`), the new data is merged with whatever was
        previously in `_latest.json` instead of overwriting it, so historical
        days aren't lost when the GitHub API only ever returns a rolling
        window. Other categories are overwritten as before (they represent
        current point-in-time state, e.g. billing/seats snapshots).
        """
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filepath = self._data_dir / category / f"{org}_{ts}.json"
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

        # Update the "latest" copy, merging with prior history where applicable
        latest = self._data_dir / category / f"{org}_latest.json"
        to_write = data
        merge_fn = _LATEST_MERGE_STRATEGIES.get(category)
        if merge_fn is not None:
            old_data = None
            if latest.exists():
                try:
                    old_data = json.loads(latest.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    old_data = None
            try:
                to_write = merge_fn(old_data, data)
            except Exception:
                # If merging fails for any reason, fall back to the raw new
                # data rather than losing the sync entirely.
                to_write = data

        latest.write_text(json.dumps(to_write, indent=2, default=str), encoding="utf-8")
        return filepath

    def load_latest(self, category: str, org: str) -> dict | list | None:
        """Load the latest data file. Checks primary dir first, then fallback."""
        filepath = self._data_dir / category / f"{org}_latest.json"
        if filepath.exists():
            return json.loads(filepath.read_text(encoding="utf-8"))

        # Try fallback directory
        if self._fallback_dir:
            fallback_path = self._fallback_dir / category / f"{org}_latest.json"
            if fallback_path.exists():
                return json.loads(fallback_path.read_text(encoding="utf-8"))

        return None

    def load_all_latest(self, category: str) -> dict[str, dict | list]:
        """Load latest data for all orgs. Checks primary dir first, fills from fallback."""
        result = {}

        # Read from primary directory
        category_dir = self._data_dir / category
        if category_dir.exists():
            for f in category_dir.glob("*_latest.json"):
                org = f.name.replace("_latest.json", "")
                result[org] = json.loads(f.read_text(encoding="utf-8"))

        # Fill missing orgs from fallback directory
        if self._fallback_dir:
            fallback_dir = self._fallback_dir / category
            if fallback_dir.exists():
                for f in fallback_dir.glob("*_latest.json"):
                    org = f.name.replace("_latest.json", "")
                    if org not in result:
                        result[org] = json.loads(f.read_text(encoding="utf-8"))

        return result

    async def sync_org(self, org: str, log_fn: LogFn = None) -> dict:
        """Sync all Copilot data for a single org. Returns summary."""
        summary: dict = {"org": org, "synced": [], "errors": []}

        if log_fn:
            log_fn("info", f"Syncing {org}...")

        api = self._get_api_for_org(org)
        if api is None:
            msg = f"No API client available for {org}"
            summary["errors"].append(msg)
            if log_fn:
                log_fn("error", f"  {org}: {msg}")
            return summary

        # Billing
        try:
            billing = await api.get_copilot_billing(org)
            if billing:
                self._save_json("billing", org, billing)
                summary["synced"].append("billing")
                if log_fn:
                    log_fn("info", f"  {org}: billing synced")
        except Exception as e:
            summary["errors"].append(f"billing: {e}")
            if log_fn:
                log_fn("error", f"  {org}: billing error - {e}")

        # Seats
        try:
            seats = await api.get_copilot_seats(org)
            if seats:
                self._save_json("seats", org, seats)
                summary["synced"].append(f"seats ({seats.get('total_seats', 0)} total)")
                if log_fn:
                    log_fn("info", f"  {org}: seats synced ({seats.get('total_seats', 0)} total)")
        except Exception as e:
            summary["errors"].append(f"seats: {e}")
            if log_fn:
                log_fn("error", f"  {org}: seats error - {e}")

        # Usage Report (org-level 28-day)
        try:
            usage_report = await api.get_org_usage_report_28day(org)
            if usage_report:
                self._save_json("usage", org, usage_report)
                n = usage_report.get("total_records", 0)
                summary["synced"].append(f"usage ({n} records)")
                if log_fn:
                    log_fn("info", f"  {org}: usage report synced ({n} records)")
        except Exception as e:
            summary["errors"].append(f"usage: {e}")
            if log_fn:
                log_fn("error", f"  {org}: usage report error - {e}")

        # Usage Users Report (org user-level 28-day)
        try:
            users_report = await api.get_org_users_usage_report_28day(org)
            if users_report:
                self._save_json("usage_users", org, users_report)
                n = users_report.get("total_records", 0)
                summary["synced"].append(f"usage_users ({n} records)")
                if log_fn:
                    log_fn("info", f"  {org}: usage users report synced ({n} records)")
        except Exception as e:
            summary["errors"].append(f"usage_users: {e}")
            if log_fn:
                log_fn("error", f"  {org}: usage users report error - {e}")

        # Metrics
        try:
            metrics = await api.get_copilot_metrics(org)
            if metrics:
                self._save_json("metrics", org, metrics)
                summary["synced"].append(f"metrics ({len(metrics)} entries)")
                if log_fn:
                    log_fn("info", f"  {org}: metrics synced ({len(metrics)} entries)")
        except Exception as e:
            summary["errors"].append(f"metrics: {e}")
            if log_fn:
                log_fn("error", f"  {org}: metrics error - {e}")

        # AI Credit Usage (current month, UBB)
        try:
            ai_credits = await api.get_ai_credit_usage(org)
            if ai_credits:
                self._save_json("ai_credits", org, ai_credits)
                n = len(ai_credits.get("usageItems", []))
                summary["synced"].append(f"ai_credits ({n} items)")
                if log_fn:
                    log_fn("info", f"  {org}: AI credit usage synced ({n} items)")
        except Exception as e:
            summary["errors"].append(f"ai_credits: {e}")
            if log_fn:
                log_fn("error", f"  {org}: AI credit usage error - {e}")

        if log_fn:
            log_fn("info", f"  {org}: done ({len(summary['synced'])} synced, {len(summary['errors'])} errors)")

        return summary

    async def _expand_cost_center_members(
        self, cost_center: dict, api, log_fn: LogFn = None
    ) -> list[dict]:
        """Expand cost center resources into a flat member list.

        - Resource type "User"  → added directly.
        - Resource type "Org"   → all org members fetched and added.
        - Resource type "Team"  → expects "name" as "org/team-slug"; members fetched.
        """
        members: list[dict] = []
        seen_logins: set[str] = set()

        def _add_member(raw: dict, source_type: str, source_name: str):
            login = raw.get("login", "")
            if not login or login in seen_logins:
                return
            seen_logins.add(login)
            members.append({
                "login": login,
                "avatar_url": raw.get("avatar_url", ""),
                "html_url": raw.get("html_url", f"https://github.com/{login}"),
                "source_type": source_type,
                "source_name": source_name,
            })

        for resource in cost_center.get("resources", []):
            rtype = resource.get("type", "")
            rname = resource.get("name", "")

            if rtype == "User":
                _add_member({"login": rname}, "User", rname)

            elif rtype == "Org":
                try:
                    org_members = await api.get_org_members(rname)
                    for m in org_members:
                        _add_member(m, "Org", rname)
                    if log_fn:
                        log_fn("info", f"    Org '{rname}': {len(org_members)} members")
                except Exception as e:
                    if log_fn:
                        log_fn("error", f"    Org '{rname}' members error: {e}")

            elif rtype == "Team":
                # "name" may be "org/team-slug" or just "team-slug"
                parts = rname.split("/", 1)
                if len(parts) == 2:
                    org_name, team_slug = parts
                else:
                    # Fallback: try deriving org from the enterprise cost center context
                    team_slug = parts[0]
                    org_name = ""
                if org_name:
                    try:
                        team_members = await api.get_team_members(org_name, team_slug)
                        for m in team_members:
                            _add_member(m, "Team", rname)
                        if log_fn:
                            log_fn("info", f"    Team '{rname}': {len(team_members)} members")
                    except Exception as e:
                        if log_fn:
                            log_fn("error", f"    Team '{rname}' members error: {e}")

        return members

    async def sync_enterprises(self, log_fn: LogFn = None) -> dict:
        """Sync enterprise list, all cost centers, and budgets."""
        summary: dict = {"synced": [], "errors": []}
        if not self._api_manager:
            return summary

        enterprises = self._api_manager.get_all_enterprises()
        if not enterprises:
            if log_fn:
                log_fn("info", "  No enterprises discovered, skipping enterprise sync")
            return summary

        # Save full enterprise list
        self._save_json("enterprise", "all", enterprises)
        summary["synced"].append(f"enterprises ({len(enterprises)} total)")
        if log_fn:
            log_fn("info", f"  Enterprises synced: {[e['slug'] for e in enterprises]}")

        # Cost centers + budgets
        cc_summary = await self._sync_cost_centers(enterprises, log_fn=log_fn)
        bd_summary = await self._sync_budgets(enterprises, log_fn=log_fn)
        summary["synced"].extend(cc_summary["synced"] + bd_summary["synced"])
        summary["errors"].extend(cc_summary["errors"] + bd_summary["errors"])

        # Enterprise-level Copilot data (seats/usage) for enterprises with no
        # organizations — either genuinely orgless, or organization scanning was
        # disabled for the owning PAT.
        pseudo_orgs = self._api_manager.get_enterprise_pseudo_orgs()
        for ent in pseudo_orgs:
            ent_summary = await self.sync_enterprise_copilot_data(ent, log_fn=log_fn)
            summary["synced"].extend(ent_summary["synced"])
            summary["errors"].extend(ent_summary["errors"])

        return summary

    async def sync_enterprise_copilot_data(self, enterprise: dict, log_fn: LogFn = None) -> dict:
        """Sync enterprise-level Copilot seats/usage data for an enterprise without
        organizations, using the enterprise-scoped Copilot APIs. Data is stored
        under a pseudo-org key (see `enterprise_pseudo_org`) so it flows through
        the existing org-keyed dashboard aggregation unchanged.
        """
        slug = enterprise["slug"]
        summary: dict = {"org": slug, "synced": [], "errors": []}
        if not self._api_manager:
            return summary

        api = self._api_manager.get_api_for_enterprise(slug)
        if api is None:
            msg = f"No API client available for enterprise {slug}"
            summary["errors"].append(msg)
            if log_fn:
                log_fn("error", f"  {slug}: {msg}")
            return summary

        pseudo_org = enterprise_pseudo_org(slug)

        if log_fn:
            log_fn("info", f"Syncing {slug} (enterprise-level, no organizations)...")

        # Seats (across enterprise teams)
        seats = None
        try:
            seats = await api.get_enterprise_billing_seats(slug)
            if seats:
                self._save_json("seats", pseudo_org, seats)
                summary["synced"].append(f"seats ({seats.get('total_seats', 0)} total)")
                if log_fn:
                    log_fn("info", f"  {slug}: enterprise seats synced ({seats.get('total_seats', 0)} total)")
        except Exception as e:
            summary["errors"].append(f"seats: {e}")
            if log_fn:
                log_fn("error", f"  {slug}: enterprise seats error - {e}")

        # Billing overview: there is no enterprise-wide equivalent of
        # /orgs/{org}/copilot/billing, so synthesize a compatible summary from seats.
        if seats:
            try:
                billing = self._build_synthetic_enterprise_billing(seats)
                self._save_json("billing", pseudo_org, billing)
                summary["synced"].append("billing (synthesized from seats)")
            except Exception as e:
                summary["errors"].append(f"billing: {e}")
                if log_fn:
                    log_fn("error", f"  {slug}: billing synthesis error - {e}")

        # Usage Report (enterprise-level 28-day)
        try:
            usage_report = await api.get_enterprise_usage_report_28day(slug)
            if usage_report:
                self._save_json("usage", pseudo_org, usage_report)
                n = usage_report.get("total_records", 0)
                summary["synced"].append(f"usage ({n} records)")
                if log_fn:
                    log_fn("info", f"  {slug}: enterprise usage report synced ({n} records)")
        except Exception as e:
            summary["errors"].append(f"usage: {e}")
            if log_fn:
                log_fn("error", f"  {slug}: enterprise usage report error - {e}")

        # Usage Users Report (enterprise user-level 28-day)
        try:
            users_report = await api.get_enterprise_users_usage_report_28day(slug)
            if users_report:
                self._save_json("usage_users", pseudo_org, users_report)
                n = users_report.get("total_records", 0)
                summary["synced"].append(f"usage_users ({n} records)")
                if log_fn:
                    log_fn("info", f"  {slug}: enterprise usage users report synced ({n} records)")
        except Exception as e:
            summary["errors"].append(f"usage_users: {e}")
            if log_fn:
                log_fn("error", f"  {slug}: enterprise usage users report error - {e}")

        # AI Credit Usage (enterprise-level, UBB)
        try:
            ai_credits = await api.get_enterprise_ai_credit_usage(slug)
            if ai_credits:
                self._save_json("ai_credits", pseudo_org, ai_credits)
                n = len(ai_credits.get("usageItems", []))
                summary["synced"].append(f"ai_credits ({n} items)")
                if log_fn:
                    log_fn("info", f"  {slug}: enterprise AI credit usage synced ({n} items)")
        except Exception as e:
            summary["errors"].append(f"ai_credits: {e}")
            if log_fn:
                log_fn("error", f"  {slug}: enterprise AI credit usage error - {e}")

        if log_fn:
            log_fn("info", f"  {slug}: done ({len(summary['synced'])} synced, {len(summary['errors'])} errors)")

        return summary

    def _build_synthetic_enterprise_billing(self, seats: dict) -> dict:
        """Build an org-billing-shaped summary from enterprise seat data.

        Enterprises without organizations have no equivalent of the
        `/orgs/{org}/copilot/billing` overview endpoint, so we approximate the
        seat_breakdown (active/inactive counts, plan type) from the raw seats list
        to keep the existing billing-based dashboard/KPI logic working unchanged.
        """
        seat_list = seats.get("seats", [])
        total = seats.get("total_seats", len(seat_list))
        active_cutoff = datetime.now(timezone.utc) - timedelta(days=28)

        active = 0
        pending_cancellation = 0
        plan_counts: dict[str, int] = {}
        for s in seat_list:
            plan = s.get("plan_type") or "unknown"
            plan_counts[plan] = plan_counts.get(plan, 0) + 1
            if s.get("pending_cancellation_date"):
                pending_cancellation += 1
            last_activity = s.get("last_activity_at")
            if last_activity:
                try:
                    dt = datetime.fromisoformat(last_activity.replace("Z", "+00:00"))
                    if dt >= active_cutoff:
                        active += 1
                except ValueError:
                    pass

        plan_type = max(plan_counts, key=plan_counts.get) if plan_counts else "enterprise"
        if plan_type not in COPILOT_PRICING:
            plan_type = "enterprise" if "enterprise" in COPILOT_PRICING else "business"

        return {
            "seat_breakdown": {
                "total": total,
                "added_this_cycle": 0,
                "pending_cancellation": pending_cancellation,
                "pending_invitation": 0,
                "active_this_cycle": active,
                "inactive_this_cycle": total - active,
            },
            "public_code_suggestions": "unconfigured",
            "plan_type": plan_type,
            "_detected_plan_type": plan_type,
            "_detected_price_per_seat": COPILOT_PRICING.get(plan_type, COPILOT_PRICING.get("business", 19.0)),
            "_synthetic": True,
            "_source": "enterprise_seats_aggregate",
        }

    async def sync_dataset(self, dataset: str, log_fn: LogFn = None) -> dict:
        """Sync a single enterprise-scoped dataset only ('cost_centers' or 'budgets').

        Always refreshes the enterprise list first (needed by the dashboards),
        then syncs the requested dataset for every discovered enterprise.
        """
        summary: dict = {"synced": [], "errors": []}
        if not self._api_manager:
            return summary

        enterprises = self._api_manager.get_all_enterprises()
        if not enterprises:
            if log_fn:
                log_fn("info", "  No enterprises discovered, skipping sync")
            return summary

        # Keep the enterprise list fresh so dashboards have their selector data
        self._save_json("enterprise", "all", enterprises)

        if dataset == "cost_centers":
            if log_fn:
                log_fn("info", "Syncing cost center data...")
            result = await self._sync_cost_centers(enterprises, log_fn=log_fn)
        elif dataset == "budgets":
            if log_fn:
                log_fn("info", "Syncing budget data...")
            result = await self._sync_budgets(enterprises, log_fn=log_fn)
        else:
            summary["errors"].append(f"Unknown dataset '{dataset}'")
            if log_fn:
                log_fn("error", f"  Unknown dataset '{dataset}'")
            return summary

        summary["synced"].extend(result["synced"])
        summary["errors"].extend(result["errors"])
        return summary

    async def _sync_cost_centers(self, enterprises: list[dict], log_fn: LogFn = None) -> dict:
        """Sync cost centers (with member expansion) for the given enterprises."""
        summary: dict = {"synced": [], "errors": []}

        for ent in enterprises:
            slug = ent["slug"]
            api = self._api_manager.get_api_for_enterprise(slug)
            if not api:
                summary["errors"].append(f"cost_centers/{slug}: no API client")
                continue
            try:
                raw_cost_centers = await api.get_enterprise_cost_centers(slug)
                if log_fn:
                    log_fn("info", f"  {slug}: {len(raw_cost_centers)} cost centers, expanding members...")

                expanded = []
                total_members = 0
                for cc in raw_cost_centers:
                    members = await self._expand_cost_center_members(cc, api, log_fn=log_fn)
                    expanded.append({
                        **cc,
                        "members": members,
                        "member_count": len(members),
                    })
                    total_members += len(members)

                self._save_json("cost_centers", slug, {
                    "enterprise": slug,
                    "enterprise_name": ent.get("name", ""),
                    "cost_centers": expanded,
                    "total": len(expanded),
                    "total_unique_members": len({
                        m["login"]
                        for cc in expanded
                        for m in cc["members"]
                    }),
                })
                summary["synced"].append(
                    f"cost_centers/{slug} ({len(expanded)} centers, {total_members} member assignments)"
                )
                if log_fn:
                    log_fn("info", f"  {slug}: cost centers synced ({len(expanded)} centers, {total_members} member assignments)")
            except Exception as e:
                summary["errors"].append(f"cost_centers/{slug}: {e}")
                if log_fn:
                    log_fn("error", f"  {slug}: cost centers error - {e}")

        return summary

    async def sync_cost_centers_for_enterprise(self, enterprise: dict, log_fn: LogFn = None) -> dict:
        """Refresh cached cost center data for a single enterprise."""
        return await self._sync_cost_centers([enterprise], log_fn=log_fn)

    async def _sync_budgets(self, enterprises: list[dict], log_fn: LogFn = None) -> dict:
        """Sync billing budgets (UBB) for the given enterprises."""
        summary: dict = {"synced": [], "errors": []}

        for ent in enterprises:
            slug = ent["slug"]
            api = self._api_manager.get_api_for_enterprise(slug)
            if not api:
                summary["errors"].append(f"budgets/{slug}: no API client")
                continue
            try:
                budgets = await api.get_all_budgets_paginated("enterprise", slug)
                self._save_json("budgets", slug, {
                    "enterprise": slug,
                    "enterprise_name": ent.get("name", ""),
                    "budgets": budgets,
                    "total": len(budgets),
                })
                summary["synced"].append(f"budgets/{slug} ({len(budgets)} budgets)")
                if log_fn:
                    log_fn("info", f"  {slug}: budgets synced ({len(budgets)} budgets)")
            except Exception as e:
                summary["errors"].append(f"budgets/{slug}: {e}")
                if log_fn:
                    log_fn("error", f"  {slug}: budgets error - {e}")

        return summary

    async def sync_all(self, log_fn: LogFn = None) -> list[dict]:
        """Sync data for all discovered orgs and enterprises via api_manager."""
        if not self._api_manager:
            return []

        org_logins = self._api_manager.get_all_org_logins()
        if log_fn:
            log_fn("info", f"Starting sync for {len(org_logins)} org(s): {', '.join(org_logins)}")

        results = []
        for org_name in org_logins:
            result = await self.sync_org(org_name, log_fn=log_fn)
            results.append(result)

        # Sync enterprise data (enterprises + cost centers)
        if log_fn:
            log_fn("info", "Syncing enterprise and cost center data...")
        enterprise_summary = await self.sync_enterprises(log_fn=log_fn)
        results.append({"org": "__enterprise__", **enterprise_summary})

        if log_fn:
            total_synced = sum(len(r["synced"]) for r in results)
            total_errors = sum(len(r["errors"]) for r in results)
            log_fn("info", f"Sync complete: {total_synced} datasets synced, {total_errors} errors")

        return results


def create_session_collector(
    session_dir: Path,
    api_manager: APIManager | None = None,
) -> DataCollector:
    """Create a DataCollector scoped to a session directory, with fallback to global."""
    return DataCollector(
        data_dir=session_dir,
        fallback_dir=config.data_dir,
        api_manager=api_manager,
    )


# Global instance (used by sidebar/overview endpoints and startup sync)
data_collector = DataCollector()
