import unittest
from unittest.mock import AsyncMock, patch

from backend.app.routers import data


class UnassignedUsersTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.enterprises = [{"slug": "example"}, {"slug": "other"}]
        self.datasets = {
            ("enterprise", "all"): self.enterprises,
            ("cost_centers", "example"): {
                "cost_centers": [
                    {"id": "active", "name": "Active", "members": [{"login": "ASSIGNED"}]},
                    {"id": "inactive", "name": "Inactive", "state": "deleted", "members": [{"login": "Direct"}]},
                ],
            },
            ("seats", "org"): {"seats": [{"assignee": {"login": "Assigned"}}]},
            ("seats", "example-enterprise"): {"seats": [
                {"assignee": {"login": "assigned"}},
                {"assignee": {"login": "Direct"}},
                {"assignee": {"login": "direct"}},
            ]},
            ("seats", "other-enterprise"): {"seats": [{"assignee": {"login": "Unrelated"}}]},
        }
        self.api = AsyncMock()
        self.api.get_enterprise_orgs.return_value = [{"login": "org"}]
        self.enterContext(patch.object(data.data_collector, "load_latest", side_effect=lambda kind, scope: self.datasets.get((kind, scope))))
        self.enterContext(patch.object(data.api_manager, "get_api_for_enterprise", return_value=self.api))
        self.enterContext(patch.object(data.api_manager, "get_all_orgs", return_value=[]))
        self.enterContext(patch.object(data.api_manager, "get_enterprise_pseudo_orgs", return_value=[]))

    async def test_enterprise_seats_survive_live_org_discovery(self):
        result = await data.get_cost_center_unassigned_users("example", "")
        self.assertEqual(result["orgs"], ["example-enterprise", "org"])
        self.assertEqual(result["total_copilot_users"], 2)
        self.assertEqual(result["assigned_user_count"], 1)
        self.assertEqual([user["login"] for user in result["unassigned_users"]], ["Direct"])

    async def test_cached_enterprise_seats_without_discovered_orgs(self):
        self.api.get_enterprise_orgs.return_value = []
        result = await data.get_cost_center_unassigned_users("example", "")
        self.assertEqual(result["orgs"], ["example-enterprise"])
        self.assertEqual(result["total_unassigned"], 1)

    async def test_org_only_enterprise(self):
        del self.datasets[("seats", "example-enterprise")]
        result = await data.get_cost_center_unassigned_users("example", "")
        self.assertEqual(result["orgs"], ["org"])
        self.assertEqual(result["total_copilot_users"], 1)
        self.assertEqual(result["total_unassigned"], 0)

    async def test_search_is_case_insensitive_and_does_not_change_population(self):
        result = await data.get_cost_center_unassigned_users("example", " DIRECT ")
        self.assertEqual(result["total_unassigned"], 1)
        result = await data.get_cost_center_unassigned_users("example", "missing")
        self.assertEqual(result["total_unassigned"], 0)
        self.assertEqual(result["total_copilot_users"], 2)
        self.assertEqual(result["assigned_user_count"], 1)

    async def test_missing_cost_center_data(self):
        del self.datasets[("cost_centers", "example")]
        result = await data.get_cost_center_unassigned_users("example", "")
        self.assertTrue(result["no_data"])


if __name__ == "__main__":
    unittest.main()