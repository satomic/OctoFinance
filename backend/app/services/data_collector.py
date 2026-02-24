"""
Data collector service - fetches data from GitHub API and saves as JSON files.
Supports per-session data directories with fallback to global directory.
Uses APIManager to route API calls to the correct PAT.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from ..config import config

if TYPE_CHECKING:
    from .api_manager import APIManager
    from .github_api import GitHubAPI


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
        """Save data to a JSON file. Returns the file path."""
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filepath = self._data_dir / category / f"{org}_{ts}.json"
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

        # Also save a "latest" copy for easy access
        latest = self._data_dir / category / f"{org}_latest.json"
        latest.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
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

    async def sync_org(self, org: str) -> dict:
        """Sync all Copilot data for a single org. Returns summary."""
        summary: dict = {"org": org, "synced": [], "errors": []}

        api = self._get_api_for_org(org)
        if api is None:
            summary["errors"].append("No API client available for this org")
            return summary

        # Billing
        try:
            billing = await api.get_copilot_billing(org)
            if billing:
                self._save_json("billing", org, billing)
                summary["synced"].append("billing")
        except Exception as e:
            summary["errors"].append(f"billing: {e}")

        # Seats
        try:
            seats = await api.get_copilot_seats(org)
            if seats:
                self._save_json("seats", org, seats)
                summary["synced"].append(f"seats ({seats.get('total_seats', 0)} total)")
        except Exception as e:
            summary["errors"].append(f"seats: {e}")

        # Usage
        try:
            usage = await api.get_copilot_usage(org)
            if usage:
                self._save_json("usage", org, usage)
                summary["synced"].append(f"usage ({len(usage)} days)")
        except Exception as e:
            summary["errors"].append(f"usage: {e}")

        # Metrics
        try:
            metrics = await api.get_copilot_metrics(org)
            if metrics:
                self._save_json("metrics", org, metrics)
                summary["synced"].append(f"metrics ({len(metrics)} entries)")
        except Exception as e:
            summary["errors"].append(f"metrics: {e}")

        return summary

    async def sync_all(self) -> list[dict]:
        """Sync data for all discovered orgs via api_manager."""
        if not self._api_manager:
            return []

        org_logins = self._api_manager.get_all_org_logins()
        results = []
        for org_name in org_logins:
            result = await self.sync_org(org_name)
            results.append(result)
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
