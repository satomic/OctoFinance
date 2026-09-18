import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.services import cost_center_owners as owners
from backend.app.routers import cost_center_owner as routes
from backend.app.services.github_api import GitHubAPI


class CostCenterOwnersTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.object(owners, "OWNERS_FILE", Path(directory) / "owners.json"))
        self.centers = [
            {"id": "one", "name": "One", "members": [{"login": "Alice"}]},
            {"id": "two", "name": "Two", "members": [{"login": "alice"}]},
        ]
        self.enterContext(patch.object(owners.data_collector, "load_latest", return_value={"cost_centers": self.centers}))

    def test_multiple_centers_case_insensitive_and_revocation(self):
        owners.set_owner("enterprise", "one", "ALICE", True, "admin")
        owners.set_owner("enterprise", "two", "Alice", True, "admin")
        self.assertEqual(len(owners.owned_cost_centers("alice")), 2)
        owners.set_owner("enterprise", "one", "Alice", False, "admin")
        self.assertEqual([center["id"] for center in owners.owned_cost_centers("ALICE")], ["two"])
        self.assertEqual(owners.owned_cost_centers("bob"), [])

    def test_enterprise_isolation_and_sync_does_not_erase_ownership(self):
        owners.set_owner("enterprise", "one", "alice", True, "admin")
        self.assertEqual(owners.owner_logins("other", "one"), [])
        self.assertEqual(owners.owner_logins("enterprise", "one"), ["alice"])
        self.centers[0]["members"] = []
        self.assertEqual(owners.owned_cost_centers("alice"), [])
        self.assertEqual(owners.owner_logins("enterprise", "one"), ["alice"])

    def test_archived_centers_are_not_accessible(self):
        owners.set_owner("enterprise", "one", "alice", True, "admin")
        self.centers[0]["state"] = "archived"
        self.assertEqual(owners.owned_cost_centers("alice"), [])


class OwnerAPITests(CostCenterOwnersTests):
    def setUp(self):
        super().setUp()
        app = FastAPI()
        app.include_router(routes.router, prefix="/api")
        self.client = TestClient(app)
        self.user = {"login": "alice", "is_admin": False}
        self.enterContext(patch.object(routes, "require_user", side_effect=lambda request: self.user))
        self.enterContext(patch.object(routes, "_append_audit_log"))
        self.enterContext(patch.object(routes.data_collector, "load_all_latest", return_value={"enterprise": {"cost_centers": self.centers}}))
        self.records = [
            {"cost_center_name": "One", "username": "alice", "date": "2026-09-01", "quantity": "10", "gross_amount": "1"},
            {"cost_center_name": "Two", "username": "alice", "date": "2026-09-01", "quantity": "999"},
        ]
        self.enterContext(patch.object(routes, "load_all_csv_records", return_value=self.records))
        self.api = AsyncMock()
        self.api.get_cost_center.return_value = {"state": "active", "ai_credit_pool_state": {"current_amount": 10, "target_amount": 100}}
        self.api.update_cost_center.return_value = {"ai_credit_pool_enabled": True}
        self.api.get_all_budgets_paginated.return_value = []
        self.api.create_budget.return_value = {"budget": {"id": "created-budget"}}
        self.api.update_budget.return_value = {"id": "existing-budget"}
        self.enterContext(patch.object(routes.api_manager, "get_api_for_enterprise", return_value=self.api))
        self.enterContext(patch.object(routes.data_collector, "update_cached_cost_center"))
        self.url = "/api/me/owned-cost-center?enterprise=enterprise&cost_center_id=one"

    def test_only_admin_can_assign_and_member_required(self):
        params = {"enterprise": "enterprise", "cost_center_id": "one", "login": "alice", "enabled": True}
        self.assertEqual(self.client.put("/api/data/cost-center-owner", json=params).status_code, 403)
        self.user["is_admin"] = True
        self.assertEqual(self.client.put("/api/data/cost-center-owner", json={**params, "login": "outsider"}).status_code, 400)
        self.assertEqual(self.client.put("/api/data/cost-center-owner", json=params).json()["owners"], ["alice"])

    def test_dashboard_scope_and_revocation(self):
        self.assertEqual(self.client.get(self.url).status_code, 403)
        owners.set_owner("enterprise", "one", "alice", True, "admin")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["ai_usage"]["kpi"]["total_requests"], 10)
        self.assertEqual(response.json()["credit_status"], "live")
        self.assertEqual(self.client.get(self.url.replace("enterprise=enterprise", "enterprise=other")).status_code, 403)
        owners.set_owner("enterprise", "one", "alice", False, "admin")
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_owner_cannot_change_credit_cap(self):
        params = {"enterprise": "enterprise", "cost_center_id": "one", "ai_credit_pool_enabled": True}
        self.assertEqual(self.client.put("/api/me/owned-cost-center/settings", json=params).status_code, 403)
        self.api.update_cost_center.assert_not_called()
        owners.set_owner("enterprise", "one", "alice", True, "admin")
        self.assertEqual(self.client.put("/api/me/owned-cost-center/settings", json={**params, "name": "injected"}).status_code, 422)
        self.assertEqual(self.client.put("/api/me/owned-cost-center/settings", json=params).status_code, 403)
        self.api.update_cost_center.assert_not_called()

    def test_only_admin_can_use_existing_cap_endpoint(self):
        from backend.app import main
        from backend.app.routers import data

        params = {"enterprise": "enterprise", "cost_center_id": "one", "enabled": True}
        with patch.object(main, "get_current_user", side_effect=lambda token: self.user), \
                patch.object(data, "_resolve_enterprise", return_value=("enterprise", {"slug": "enterprise"}, [])), \
                patch.object(data, "_append_audit_log"), \
                patch.object(data.sync_manager, "log"):
            client = TestClient(main.app)
            owners.set_owner("enterprise", "one", "alice", True, "admin")
            self.assertEqual(client.post("/api/data/cost-center-ai-credit-pool", json=params).status_code, 403)
            self.api.update_cost_center.assert_not_called()
            self.user["is_admin"] = True
            response = client.post("/api/data/cost-center-ai-credit-pool", json=params)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "ok")
            self.api.update_cost_center.assert_awaited_once_with("enterprise", "one", ai_credit_pool_enabled=True)

    def allow_budget_writes(self):
        owners.set_owner("enterprise", "one", "alice", True, "admin")
        self.api.get_cost_center.return_value = {
            "state": "active", "ai_credit_pool_enabled": True,
            "resources": [{"type": "User", "name": "Alice"}],
        }
        return {"enterprise": "enterprise", "cost_center_id": "one", "login": "ALICE", "amount": 25.50, "prevent_further_usage": True}

    def personal_budget(self, **overrides):
        return {
            "id": "existing-budget", "budget_type": "BundlePricing", "budget_scope": "user",
            "budget_product_sku": "ai_credits", "budget_entity_name": "Alice",
            "budget_amount": 20, "consumed_amount": 7, "prevent_further_usage": True,
            **overrides,
        }

    def test_cap_on_creates_enterprise_individual_budget(self):
        params = self.allow_budget_writes()
        response = self.client.put("/api/me/owned-cost-center/user-budget", json=params)
        self.assertEqual(response.status_code, 200)
        fields = self.api.create_budget.call_args.kwargs
        self.assertEqual(fields["entity_type"], "enterprise")
        self.assertEqual(fields["entity_name"], "enterprise")
        self.assertEqual(fields["budget_data"]["budget_scope"], "user")
        self.assertEqual(fields["budget_data"]["budget_product_sku"], "ai_credits")
        self.assertEqual(fields["budget_data"]["user"], "alice")
        self.assertEqual(fields["budget_data"]["budget_amount"], 25.50)
        self.api.update_budget.assert_not_called()
        self.api.get_all_budgets_paginated.assert_awaited_once_with("enterprise", "enterprise", scope="user", strict=True)

    def test_update_matches_user_scope_and_product(self):
        params = self.allow_budget_writes()
        self.api.get_all_budgets_paginated.return_value = [
            self.personal_budget(id="other-sku", budget_product_sku="actions"),
            self.personal_budget(id="universal", budget_scope="multi_user_customer"),
            self.personal_budget(id="other-user", budget_entity_name="bob"),
            self.personal_budget(),
        ]
        response = self.client.put("/api/me/owned-cost-center/user-budget", json=params)
        self.assertEqual(response.status_code, 200)
        self.api.update_budget.assert_awaited_once_with(entity_type="enterprise", entity_name="enterprise", budget_id="existing-budget", budget_data={"budget_amount": 25.50, "prevent_further_usage": True})
        self.api.create_budget.assert_not_called()

    def test_cap_off_keeps_budgets_visible_but_denies_writes(self):
        params = self.allow_budget_writes()
        self.api.get_cost_center.return_value["ai_credit_pool_enabled"] = False
        self.api.get_all_budgets_paginated.return_value = [self.personal_budget(), self.personal_budget(budget_entity_name="bob")]
        self.centers[0]["ai_credit_pool_enabled"] = True
        dashboard = self.client.get(self.url).json()
        self.assertFalse(dashboard["cost_center"]["ai_credit_pool_enabled"])
        self.assertEqual(dashboard["budget_read_only_reason"], "cap_off")
        self.assertEqual(len(dashboard["user_budgets"]), 1)
        self.assertEqual(dashboard["user_budgets"][0]["budgets"][0]["consumed_amount"], 7)
        self.assertFalse(dashboard["user_budgets"][0]["can_edit"])
        response = self.client.put("/api/me/owned-cost-center/user-budget", json=params)
        self.assertEqual(response.json()["detail"]["code"], "cap_off")
        self.api.create_budget.assert_not_called()
        self.api.update_budget.assert_not_called()

    def test_cap_is_rechecked_immediately_before_write(self):
        params = self.allow_budget_writes()
        enabled = self.api.get_cost_center.return_value
        self.api.get_cost_center.side_effect = [enabled, {**enabled, "ai_credit_pool_enabled": False}]
        response = self.client.put("/api/me/owned-cost-center/user-budget", json=params)
        self.assertEqual(response.status_code, 403)
        self.api.create_budget.assert_not_called()

    def test_unknown_cap_or_budget_read_failure_denies_writes(self):
        params = self.allow_budget_writes()
        self.api.get_cost_center.side_effect = RuntimeError("unavailable")
        self.assertEqual(self.client.put("/api/me/owned-cost-center/user-budget", json=params).status_code, 503)
        self.api.get_cost_center.side_effect = None
        self.api.get_all_budgets_paginated.side_effect = RuntimeError("forbidden")
        self.assertEqual(self.client.put("/api/me/owned-cost-center/user-budget", json=params).status_code, 502)
        self.assertEqual(self.client.get(self.url).json()["budget_read_only_reason"], "budgets_unavailable")
        self.api.create_budget.assert_not_called()

    def test_nonmember_and_stale_membership_cannot_write(self):
        params = self.allow_budget_writes()
        self.assertEqual(self.client.put("/api/me/owned-cost-center/user-budget", json={**params, "login": "outsider"}).status_code, 403)
        self.api.get_cost_center.return_value["resources"] = []
        self.assertEqual(self.client.put("/api/me/owned-cost-center/user-budget", json=params).status_code, 403)
        self.api.create_budget.assert_not_called()

    def test_team_membership_is_checked_live(self):
        params = self.allow_budget_writes()
        self.api.get_cost_center.return_value["resources"] = [{"type": "Team", "name": "engineering"}]
        self.api.get_enterprise_team_members.return_value = [{"login": "Alice"}]
        self.assertEqual(self.client.put("/api/me/owned-cost-center/user-budget", json=params).status_code, 200)
        self.api.get_enterprise_team_members.assert_awaited_with("enterprise", "engineering")

    def test_budget_write_cannot_cross_enterprise_or_inject_id(self):
        params = self.allow_budget_writes()
        self.assertEqual(self.client.put("/api/me/owned-cost-center/user-budget", json={**params, "enterprise": "other"}).status_code, 403)
        self.assertEqual(self.client.put("/api/me/owned-cost-center/user-budget", json={**params, "budget_id": "arbitrary"}).status_code, 422)
        for amount in (-1, 0, 0.001):
            self.assertEqual(self.client.put("/api/me/owned-cost-center/user-budget", json={**params, "amount": amount}).status_code, 422)
        self.api.create_budget.assert_not_called()

    def test_duplicate_budgets_and_github_write_failure(self):
        params = self.allow_budget_writes()
        self.api.get_all_budgets_paginated.return_value = [self.personal_budget(), self.personal_budget(id="duplicate")]
        self.assertEqual(self.client.put("/api/me/owned-cost-center/user-budget", json=params).status_code, 409)
        self.api.update_budget.assert_not_called()
        self.api.get_all_budgets_paginated.return_value = []
        self.api.create_budget.return_value = {"error": "Rejected"}
        self.assertEqual(self.client.put("/api/me/owned-cost-center/user-budget", json=params).status_code, 502)

    def test_revoked_owner_cannot_write_budget(self):
        params = self.allow_budget_writes()
        owners.set_owner("enterprise", "one", "alice", False, "admin")
        self.assertEqual(self.client.put("/api/me/owned-cost-center/user-budget", json=params).status_code, 403)
        self.api.create_budget.assert_not_called()


    def test_ambiguous_names_and_explicit_enterprise(self):
        with patch.object(routes.data_collector, "load_all_latest", return_value={"enterprise": {"cost_centers": self.centers}, "other": {"cost_centers": self.centers}}):
            scoped, ambiguous = routes.scoped_records(self.records, "enterprise", self.centers[0], "", "")
            self.assertTrue(ambiguous)
            self.assertEqual(scoped, [])
            scoped, _ = routes.scoped_records([{**self.records[0], "enterprise": "enterprise"}], "enterprise", self.centers[0], "2026-09-01", "2026-09-30")
            self.assertEqual(len(scoped), 1)

    def test_live_failure_is_marked_and_anonymous_is_denied(self):
        owners.set_owner("enterprise", "one", "alice", True, "admin")
        self.api.get_cost_center.side_effect = RuntimeError("API failure")
        self.assertEqual(self.client.get(self.url).json()["credit_status"], "unavailable")
        self.user = None
        self.assertEqual(self.client.get(self.url).status_code, 401)

    def test_application_middleware_preserves_admin_boundary(self):
        from backend.app import main

        with patch.object(main, "get_current_user", side_effect=lambda token: self.user):
            client = TestClient(main.app)
            self.assertEqual(client.get("/api/data/cost-center-owners?enterprise=enterprise").status_code, 403)
            self.assertEqual(client.get("/api/me/owned-cost-centers").status_code, 200)
            self.assertEqual(client.get(self.url).status_code, 403)
            owners.set_owner("enterprise", "one", "alice", True, "admin")
            self.assertEqual(client.get(self.url).status_code, 200)
            self.user = None
            self.assertEqual(client.get("/api/me/owned-cost-centers").status_code, 401)

    def test_period_filter_and_explicit_other_enterprise(self):
        records = [
            {**self.records[0], "date": "2026-08-31"},
            {**self.records[0], "date": "2026-09-01"},
            {**self.records[0], "enterprise": "other"},
        ]
        scoped, _ = routes.scoped_records(records, "enterprise", self.centers[0], "2026-09-01", "2026-09-30")
        self.assertEqual(len(scoped), 1)

    def test_unsupported_cap_never_calls_github_write(self):
        owners.set_owner("enterprise", "one", "alice", True, "admin")
        self.centers[0]["resources"] = [{"type": "Org", "name": "organization"}]
        params = {"enterprise": "enterprise", "cost_center_id": "one", "ai_credit_pool_enabled": True}
        self.assertEqual(self.client.put("/api/me/owned-cost-center/settings", json=params).status_code, 403)
        self.api.update_cost_center.assert_not_called()


class StrictBudgetPaginationTests(unittest.IsolatedAsyncioTestCase):
    async def test_partial_failure_is_not_empty_success(self):
        api = SimpleNamespace(get_budgets=AsyncMock(side_effect=[{"budgets": [{"id": "one"}], "has_next_page": True}, None]))
        with self.assertRaises(ValueError):
            await GitHubAPI.get_all_budgets_paginated(api, "enterprise", "example", strict=True)

    async def test_empty_success_and_existing_default(self):
        api = SimpleNamespace(get_budgets=AsyncMock(return_value={"budgets": [], "has_next_page": False}))
        self.assertEqual(await GitHubAPI.get_all_budgets_paginated(api, "enterprise", "example", strict=True), [])
        api.get_budgets.return_value = None
        self.assertEqual(await GitHubAPI.get_all_budgets_paginated(api, "enterprise", "example"), [])