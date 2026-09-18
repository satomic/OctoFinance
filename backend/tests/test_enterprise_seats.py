import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from backend.app.config import COPILOT_PRICING
from backend.app.routers import data
from backend.app.services.api_manager import APIManager
from backend.app.services.data_collector import DataCollector


class EnterpriseSeatTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = self.enterContext(TemporaryDirectory())
        self.manager = APIManager()
        self.manager._all_enterprises = [{"slug": "example", "pat_id": "token"}]
        self.manager._all_orgs = [{"login": "personal-org", "pat_id": "token"}]
        self.api = AsyncMock()
        self.api.get_enterprise_billing_seats.return_value = {
            "total_seats": 1,
            "seats": [{"assignee": {"login": "direct"}, "plan_type": "enterprise"}],
        }
        self.manager._instances = {"token": self.api}
        self.collector = DataCollector(Path(self.directory), api_manager=self.manager)
        self.enterContext(patch.object(data, "data_collector", self.collector))
        self.enterContext(patch.object(data, "api_manager", self.manager))
        for method in ("_sync_cost_centers", "_sync_budgets", "_sync_enterprise_teams"):
            self.enterContext(patch.object(
                self.collector, method,
                new=AsyncMock(return_value={"synced": [], "errors": []}),
            ))

    async def test_org_discovery_does_not_skip_enterprise_seats(self):
        await self.collector.sync_enterprises()

        self.api.get_enterprise_billing_seats.assert_awaited_once_with("example")
        seats = self.collector.load_latest("seats", "example-enterprise")
        self.assertEqual(seats["total_seats"], 1)
        billing = self.collector.load_latest("billing", "example-enterprise")
        self.assertEqual(billing["seat_breakdown"]["total"], 1)

    async def test_overlap_is_removed_from_seats_and_billing_but_not_raw_cache(self):
        self.collector._save_json("seats", "personal-org", {
            "total_seats": 1,
            "seats": [{"assignee": {"login": "SHARED"}, "plan_type": "enterprise"}],
        })
        self.api.get_enterprise_billing_seats.return_value["seats"].append(
            {"assignee": {"login": "shared"}, "plan_type": "enterprise"},
        )
        self.api.get_enterprise_billing_seats.return_value["total_seats"] = 2
        await self.collector.sync_enterprises()

        seats = self.collector.load_latest("seats", "example-enterprise")
        self.assertEqual([seat["assignee"]["login"] for seat in seats["seats"]], ["direct"])
        self.assertEqual(seats["total_seats"], 1)
        self.assertEqual(sum(
            payload["seat_breakdown"]["total"]
            for payload in self.collector.load_all_latest("billing").values()
        ), 2)
        raw = self.collector._load_latest_raw("seats", "example-enterprise")
        self.assertEqual(raw["total_seats"], 2)

        self.manager._all_orgs = []
        self.assertEqual(self.collector.load_latest("seats", "example-enterprise")["total_seats"], 2)
        self.assertNotIn("personal-org", self.collector.load_all_latest("seats"))
        self.assertNotIn("personal-org", self.collector.load_all_latest("billing"))

    async def test_unavailable_enterprise_endpoint_keeps_org_data(self):
        self.api.get_enterprise_billing_seats.return_value = None
        self.api.consume_failure = lambda: {"status": 403, "detail": "Forbidden"}
        self.collector._save_json("seats", "personal-org", {
            "total_seats": 1, "seats": [{"assignee": {"login": "org-user"}}],
        })
        result = await self.collector.sync_enterprises()

        self.assertTrue(result["errors"])
        self.assertEqual(self.collector.load_latest("seats", "personal-org")["total_seats"], 1)
        self.assertIsNone(self.collector.load_latest("seats", "example-enterprise"))

    async def test_dashboard_and_overview_include_enterprise_seats_without_double_counting(self):
        org_seats = {
            "total_seats": 1,
            "seats": [{"assignee": {"login": "SHARED"}, "plan_type": "enterprise"}],
        }
        self.collector._save_json("seats", "personal-org", org_seats)
        self.collector._save_json("billing", "personal-org", {
            "seat_breakdown": {"total": 1, "active_this_cycle": 0},
            "_detected_plan_type": "enterprise",
            "_detected_price_per_seat": COPILOT_PRICING["enterprise"],
        })
        self.api.get_enterprise_billing_seats.return_value["seats"].extend(org_seats["seats"])
        self.api.get_enterprise_billing_seats.return_value["total_seats"] = 2
        await self.collector.sync_enterprises()

        overview = await data.get_overview()
        dashboard = await data.get_dashboard("", "", "", "", "")
        self.assertEqual(overview["total_seats"], 2)
        self.assertEqual(dashboard["kpi"]["total_seats"], 2)
        self.assertEqual(dashboard["kpi"]["monthly_cost"], 2 * COPILOT_PRICING["enterprise"])
        self.assertEqual(overview["monthly_cost"], dashboard["kpi"]["monthly_cost"])
        self.assertEqual(len(dashboard["seat_info"]["seats"]), 2)
        self.assertEqual(set(dashboard["users"]), {"SHARED", "direct"})

        filtered = await data.get_dashboard("", "", "direct", "", "")
        self.assertEqual(filtered["kpi"]["total_seats"], 1)
        self.assertEqual([seat["user"] for seat in filtered["seat_info"]["seats"]], ["direct"])
        org_only = await data.get_dashboard("personal-org", "", "", "", "")
        self.assertEqual(org_only["kpi"]["total_seats"], 1)

    async def test_seat_fix_does_not_add_overlapping_usage(self):
        usage = {"records": [{"day_totals": [{
            "day": "2026-09-01", "user_initiated_interaction_count": 5,
        }]}]}
        self.collector._save_json("usage", "personal-org", usage)
        self.collector._save_json("usage", "example-enterprise", usage)
        await self.collector.sync_enterprises()

        self.api.get_enterprise_usage_report_28day.assert_not_awaited()
        dashboard = await data.get_dashboard("personal-org,example-enterprise", "", "", "", "")
        self.assertEqual(dashboard["daily_trend"][0]["interactions"], 5)

    async def test_org_discovery_failure_does_not_abort_enterprise_discovery(self):
        self.api.discover_user.return_value = {"login": "admin"}
        self.api.discover_orgs.side_effect = RuntimeError("organization access denied")
        with (
            patch("backend.app.services.api_manager.pat_manager") as pats,
            patch("backend.app.services.api_manager.GitHubAPI", return_value=self.api),
        ):
            pats.get_all.return_value = [{
                "id": "token", "label": "test", "token": "test-token",
                "include_organizations": True, "enterprise_slugs": ["example"],
            }]
            await self.manager.rebuild()

        self.assertEqual(self.manager.get_all_orgs(), [])
        self.assertEqual([enterprise["slug"] for enterprise in self.manager.get_all_enterprises()], ["example"])

    async def test_disabled_org_scanning_preserves_enterprise_usage_sync(self):
        self.manager._all_orgs = []
        self.api.get_enterprise_usage_report_28day.return_value = {"records": [], "total_records": 0}
        self.api.get_enterprise_users_usage_report_28day.return_value = {"records": [], "total_records": 0}
        self.api.get_enterprise_ai_credit_usage.return_value = {"usageItems": []}
        result = await self.collector.sync_enterprises()

        self.assertEqual(result["errors"], [])
        self.api.get_enterprise_usage_report_28day.assert_awaited_once_with("example")
        self.api.get_enterprise_users_usage_report_28day.assert_awaited_once_with("example")
        self.api.get_enterprise_ai_credit_usage.assert_awaited_once_with("example")
        self.assertEqual((await data.get_overview())["total_seats"], 1)

    async def test_session_fallback_uses_same_deduplicated_seats(self):
        await self.collector.sync_enterprises()
        with TemporaryDirectory() as session_directory:
            session = DataCollector(
                Path(session_directory), fallback_dir=Path(self.directory),
                api_manager=self.manager,
            )
            session._save_json("seats", "personal-org", {
                "total_seats": 1,
                "seats": [{"assignee": {"login": "DIRECT"}, "plan_type": "enterprise"}],
            })
            self.assertEqual(session.load_latest("seats", "example-enterprise")["total_seats"], 0)
            self.assertEqual(sum(
                payload["seat_breakdown"]["total"]
                for payload in session.load_all_latest("billing").values()
            ), 1)
        self.assertEqual(self.collector.load_latest("seats", "example-enterprise")["total_seats"], 1)


if __name__ == "__main__":
    unittest.main()