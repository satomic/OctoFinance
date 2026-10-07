"""
Every GitHub user known to OctoFinance, for the frontend's demo mode.

Demo mode replaces user names with aliases while presenting to outsiders. It
runs entirely in the browser, but it needs to know which strings are user
logins: the same `login` field also holds organization names, so guessing
from field names would hide organizations too. This collects the logins (and
display names, where known) from every synced dataset.
"""

from __future__ import annotations

from ..services.auth_store import auth_store
from ..services.csv_store import CSV_TYPE_AI, CSV_TYPE_USAGE, load_all_csv_records
from ..services.data_collector import data_collector
from ..services.pat_manager import pat_manager
from .cost_center_owners import load_owners


def _from_dict_of_snapshots(category: str, collect) -> None:
    for snapshot in data_collector.load_all_latest(category).values():
        if isinstance(snapshot, dict):
            collect(snapshot)


def build_roster() -> list[dict]:
    """Sorted ``[{login, name}]`` for every user found in the synced data."""
    users: dict[str, dict] = {}

    def add(login, name: str = "") -> None:
        if not isinstance(login, str) or not login.strip():
            return
        login = login.strip()
        entry = users.setdefault(login.lower(), {"login": login, "name": ""})
        if name and isinstance(name, str) and name.strip() and name.strip() != login:
            entry["name"] = name.strip()

    def seats(snapshot: dict) -> None:
        for seat in snapshot.get("seats", []):
            add((seat.get("assignee") or {}).get("login"))

    def usage_users(snapshot: dict) -> None:
        for record in snapshot.get("records", []):
            add(record.get("user_login"))

    def teams(snapshot: dict) -> None:
        for team in snapshot.get("teams", []):
            for member in team.get("members", []):
                add(member.get("login"), member.get("name", ""))

    def cost_centers(snapshot: dict) -> None:
        for center in snapshot.get("cost_centers", []):
            for member in center.get("members", []):
                add(member.get("login") if isinstance(member, dict) else member)
            for resource in center.get("resources", []):
                if resource.get("type") == "User":
                    add(resource.get("name"))

    def budgets(snapshot: dict) -> None:
        for budget in snapshot.get("budgets", []):
            if budget.get("budget_scope") == "user":
                add(budget.get("budget_entity_name"))
                add(budget.get("user"))

    _from_dict_of_snapshots("seats", seats)
    _from_dict_of_snapshots("usage_users", usage_users)
    _from_dict_of_snapshots("enterprise_teams", teams)
    _from_dict_of_snapshots("cost_centers", cost_centers)
    _from_dict_of_snapshots("budgets", budgets)

    for csv_type in (CSV_TYPE_AI, CSV_TYPE_USAGE):
        for record in load_all_csv_records(csv_type):
            add(record.get("username"))

    from ..routers.budget_requests import _load as load_requests
    for request in load_requests():
        add(request.get("user_login"), request.get("user_name", ""))
        add(request.get("reviewed_by"))
        for entry in request.get("history", []):
            add(entry.get("by"))

    for centers in load_owners().values():
        for owners in centers.values():
            for login, grant in owners.items():
                add(login)
                add((grant or {}).get("granted_by"))

    for pat in pat_manager.get_all():
        add(pat.get("user_login"))
    for login in auth_store.get_oauth_config().get("admins", []):
        add(login)

    # The local administrator is not a GitHub user (often just "admin"); aliasing
    # it would rewrite that word everywhere in chat replies and logs.
    local_admin = ((auth_store.load_credentials() or {}).get("username") or "").lower()
    users.pop(local_admin, None)

    return sorted(users.values(), key=lambda entry: entry["login"].lower())
