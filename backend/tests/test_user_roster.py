import unittest
from unittest.mock import patch

from backend.app.services import user_roster

SNAPSHOTS = {
    "seats": {"org-a": {"seats": [{"assignee": {"login": "Alice"}}, {"assignee": None}]}},
    "usage_users": {"org-a": {"records": [{"user_login": "bob"}]}},
    "enterprise_teams": {"ent": {"teams": [{"members": [{"login": "carol", "name": "Carol C"}]}]}},
    "cost_centers": {"ent": {"cost_centers": [{
        "members": [{"login": "dave"}],
        "resources": [{"type": "User", "name": "erin"}, {"type": "Org", "name": "org-a"}],
    }]}},
    "budgets": {"ent": {"budgets": [
        {"budget_scope": "user", "budget_entity_name": "frank", "user": "frank"},
        {"budget_scope": "cost_center", "budget_entity_name": "Platform"},
    ]}},
}


class UserRosterTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(user_roster.data_collector, "load_all_latest", side_effect=lambda c: SNAPSHOTS.get(c, {})))
        self.enterContext(patch.object(user_roster, "load_all_csv_records", return_value=[{"username": "grace"}, {"username": ""}]))
        self.enterContext(patch("backend.app.routers.budget_requests._load", return_value=[
            {"user_login": "heidi", "user_name": "Heidi H", "reviewed_by": "admin", "history": [{"by": "ivan"}]},
        ]))
        self.enterContext(patch.object(user_roster, "load_owners", return_value={"ent": {"cc1": {"judy": {"granted_by": "admin"}}}}))
        self.enterContext(patch.object(user_roster.pat_manager, "get_all", return_value=[{"user_login": "patowner"}]))
        self.enterContext(patch.object(user_roster.auth_store, "get_oauth_config", return_value={"admins": ["ALICE", "sso-admin"]}))
        self.enterContext(patch.object(user_roster.auth_store, "load_credentials", return_value={"username": "admin"}))

    def test_collects_users_from_every_source_without_orgs_or_teams(self):
        roster = user_roster.build_roster()
        logins = [user["login"] for user in roster]
        self.assertEqual(logins, [
            "Alice", "bob", "carol", "dave", "erin", "frank", "grace", "heidi", "ivan", "judy", "patowner", "sso-admin",
        ])
        self.assertNotIn("org-a", logins)
        self.assertNotIn("Platform", logins)

    def test_keeps_display_names_and_drops_the_local_admin(self):
        names = {user["login"]: user["name"] for user in user_roster.build_roster()}
        self.assertEqual((names["carol"], names["heidi"], names["bob"]), ("Carol C", "Heidi H", ""))
        # "admin" is the local login, not a GitHub user: never aliased
        self.assertNotIn("admin", {login.lower() for login in names})


if __name__ == "__main__":
    unittest.main()
