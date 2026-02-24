"""
API Manager - manages multiple GitHubAPI instances (one per PAT)
and provides aggregated org discovery with enterprise grouping.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..config import config
from .github_api import GitHubAPI
from .pat_manager import pat_manager


class APIManager:
    """Manages GitHubAPI instances for all configured PATs."""

    def __init__(self):
        self._instances: dict[str, GitHubAPI] = {}  # pat_id -> GitHubAPI
        self._org_to_pat: dict[str, str] = {}  # org_login -> pat_id
        self._all_orgs: list[dict] = []  # aggregated org list with enterprise info
        self._discovered_users: dict[str, dict] = {}  # pat_id -> user info

    async def rebuild(self):
        """Reload all PATs, create API instances, run discovery for each."""
        # Close existing clients
        for api in self._instances.values():
            await api.close()

        self._instances.clear()
        self._org_to_pat.clear()
        self._all_orgs.clear()
        self._discovered_users.clear()

        pats = pat_manager.get_all()
        if not pats:
            print("[APIManager] No PATs configured, skipping discovery.")
            return

        for pat in pats:
            pat_id = pat["id"]
            token = pat["token"]
            api = GitHubAPI(token=token, base_url=config.github_api_base)
            self._instances[pat_id] = api

            try:
                # Discover user
                user = await api.discover_user()
                self._discovered_users[pat_id] = user
                print(f"[APIManager] PAT '{pat['label']}' authenticated as: {user.get('login', 'unknown')}")

                # Update PAT metadata
                pat_manager.update(
                    pat_id,
                    user_login=user.get("login", ""),
                    user_avatar=user.get("avatar_url", ""),
                )

                # Discover orgs
                orgs = await api.discover_orgs()
                org_logins = [o["login"] for o in orgs]
                pat_manager.update(pat_id, orgs=org_logins)
                print(f"[APIManager] PAT '{pat['label']}' has {len(orgs)} orgs: {org_logins}")

                # Map orgs to this PAT (first PAT wins if org appears in multiple)
                for org_info in orgs:
                    org_login = org_info["login"]
                    if org_login not in self._org_to_pat:
                        self._org_to_pat[org_login] = pat_id

                # Get org details for enterprise detection
                for org_info in orgs:
                    org_login = org_info["login"]
                    try:
                        detail = await api.get_org_detail(org_login)
                        enterprise_name = detail.get("company", "").strip() or "Independent"
                        org_entry = {
                            **org_info,
                            "enterprise": enterprise_name,
                            "pat_id": pat_id,
                            "pat_label": pat["label"],
                            "pat_user": user.get("login", ""),
                        }
                        # Avoid duplicates (first PAT wins)
                        if not any(o["login"] == org_login for o in self._all_orgs):
                            self._all_orgs.append(org_entry)
                    except Exception as e:
                        print(f"[APIManager] Failed to get detail for {org_login}: {e}")
                        if not any(o["login"] == org_login for o in self._all_orgs):
                            self._all_orgs.append({
                                **org_info,
                                "enterprise": "Unknown",
                                "pat_id": pat_id,
                                "pat_label": pat["label"],
                                "pat_user": user.get("login", ""),
                            })

                # Update last_synced_at
                pat_manager.update(
                    pat_id,
                    last_synced_at=datetime.now(timezone.utc).isoformat(),
                )

            except Exception as e:
                print(f"[APIManager] Failed to discover for PAT '{pat['label']}': {e}")

    async def add_and_discover(self, pat_id: str) -> dict:
        """Add a single PAT's API instance and run discovery. Returns user info."""
        pat = pat_manager.find_by_id(pat_id)
        if not pat:
            raise ValueError(f"PAT {pat_id} not found")

        api = GitHubAPI(token=pat["token"], base_url=config.github_api_base)

        # Validate token
        try:
            user = await api.discover_user()
        except Exception:
            await api.close()
            raise ValueError("Invalid token: could not authenticate with GitHub")

        self._instances[pat_id] = api
        self._discovered_users[pat_id] = user

        # Update PAT metadata
        pat_manager.update(
            pat_id,
            user_login=user.get("login", ""),
            user_avatar=user.get("avatar_url", ""),
        )

        # Discover orgs
        try:
            orgs = await api.discover_orgs()
        except Exception:
            orgs = []

        org_logins = [o["login"] for o in orgs]
        pat_manager.update(pat_id, orgs=org_logins)

        for org_info in orgs:
            org_login = org_info["login"]
            if org_login not in self._org_to_pat:
                self._org_to_pat[org_login] = pat_id

            try:
                detail = await api.get_org_detail(org_login)
                enterprise_name = detail.get("company", "").strip() or "Independent"
            except Exception:
                enterprise_name = "Unknown"

            org_entry = {
                **org_info,
                "enterprise": enterprise_name,
                "pat_id": pat_id,
                "pat_label": pat["label"],
                "pat_user": user.get("login", ""),
            }
            if not any(o["login"] == org_login for o in self._all_orgs):
                self._all_orgs.append(org_entry)

        pat_manager.update(
            pat_id,
            last_synced_at=datetime.now(timezone.utc).isoformat(),
        )

        return user

    async def remove_api(self, pat_id: str):
        """Remove a PAT's API instance and clean up org mappings."""
        api = self._instances.pop(pat_id, None)
        if api:
            await api.close()

        self._discovered_users.pop(pat_id, None)

        # Remove orgs belonging to this PAT
        self._all_orgs = [o for o in self._all_orgs if o.get("pat_id") != pat_id]

        # Rebuild org_to_pat mapping
        self._org_to_pat = {
            o["login"]: o["pat_id"] for o in self._all_orgs
        }

    def get_api_for_org(self, org: str) -> GitHubAPI | None:
        """Get the API client that has access to this org."""
        pat_id = self._org_to_pat.get(org)
        if pat_id:
            return self._instances.get(pat_id)
        # Fallback: return first available API
        if self._instances:
            return next(iter(self._instances.values()))
        return None

    def get_all_orgs(self) -> list[dict]:
        """Return all discovered orgs with enterprise grouping info."""
        return list(self._all_orgs)

    def get_discovered_users(self) -> dict[str, dict]:
        """Return all discovered users keyed by pat_id."""
        return dict(self._discovered_users)

    def get_all_org_logins(self) -> list[str]:
        """Return flat list of all org logins."""
        return [o["login"] for o in self._all_orgs]

    async def close_all(self):
        """Close all API clients."""
        for api in self._instances.values():
            await api.close()
        self._instances.clear()


# Global instance
api_manager = APIManager()
