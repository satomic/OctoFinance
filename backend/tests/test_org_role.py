import unittest

import httpx

from backend.app.services.data_collector import _empty_result_log
from backend.app.services.github_api import GitHubAPI

ROLE_403 = {"message": "Insufficient permissions. This action requires admin, or relevant organization role access."}


def api_with(handler) -> GitHubAPI:
    api = GitHubAPI(token="t", base_url="https://api.github.test")
    api._client = httpx.AsyncClient(base_url="https://api.github.test", transport=httpx.MockTransport(handler))
    return api


class EmptyResultLogRoleTests(unittest.TestCase):
    def _failed(self, status):
        api = GitHubAPI(token="t")
        api._record_failure("usage_report", status=status, detail=ROLE_403["message"])
        return api

    def test_member_403_is_a_warning_with_guidance(self):
        level, msg = _empty_result_log(self._failed(403), "cht-it", "usage report", role="member")
        self.assertEqual(level, "warn")
        self.assertIn("cht-it: usage report skipped", msg)
        self.assertIn("member, not an owner", msg)

    def test_403_stays_an_error_for_admins_and_unknown_roles(self):
        for role in ("admin", None):
            level, msg = _empty_result_log(self._failed(403), "cht-it", "usage report", role=role)
            self.assertEqual(level, "error", role)
            self.assertIn("check the PAT and its scopes", msg)

    def test_401_stays_an_error_even_for_members(self):
        level, _ = _empty_result_log(self._failed(401), "cht-it", "billing", role="member")
        self.assertEqual(level, "error")


class OrgMembershipsTests(unittest.IsolatedAsyncioTestCase):
    async def test_reads_roles(self):
        def handler(request):
            self.assertEqual(request.url.path, "/user/memberships/orgs")
            return httpx.Response(200, json=[
                {"organization": {"login": "CHT-IT"}, "role": "member", "state": "active"},
                {"organization": {"login": "ops"}, "role": "admin", "state": "active"},
            ])
        api = api_with(handler)
        self.assertEqual(await api.get_org_memberships(), {"cht-it": "member", "ops": "admin"})
        await api.close()

    async def test_unreadable_roles_are_unknown(self):
        api = api_with(lambda request: httpx.Response(403, json={"message": "Resource not accessible by personal access token"}))
        self.assertIsNone(await api.get_org_memberships())
        await api.close()


if __name__ == "__main__":
    unittest.main()
