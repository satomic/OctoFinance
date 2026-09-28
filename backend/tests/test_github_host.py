import unittest
from unittest.mock import AsyncMock, patch

from backend.app.routers import auth, pats
from backend.app.services import copilot_engine
from backend.app.services.api_manager import APIManager
from backend.app.services.github_api import GitHubAPI
from backend.app.services.github_host import (
    api_base_url,
    normalize_host,
    parse_enterprise_url,
    web_base_url,
)
from backend.app.services.report_generator import generate_single_report_html


class NormalizeHostTests(unittest.TestCase):
    def test_github_com_variants(self):
        for value in ("", None, "github.com", "https://github.com/", "api.github.com", "WWW.GitHub.com"):
            self.assertEqual(normalize_host(value), "github.com", value)

    def test_ghe_com_variants(self):
        for value in (
            "acme.ghe.com",
            "ACME.ghe.com",
            "api.acme.ghe.com",
            "https://acme.ghe.com/enterprises/acme",
            "https://api.acme.ghe.com",
        ):
            self.assertEqual(normalize_host(value), "acme.ghe.com", value)

    def test_rejects_other_hosts(self):
        for value in ("ghe.com", "github.example.com", "acme.ghe.com.evil.io", "a.b.ghe.com"):
            with self.assertRaises(ValueError, msg=value):
                normalize_host(value)

    def test_base_urls(self):
        self.assertEqual(api_base_url("github.com"), "https://api.github.com")
        self.assertEqual(web_base_url("github.com"), "https://github.com")
        self.assertEqual(api_base_url("acme.ghe.com"), "https://api.acme.ghe.com")
        self.assertEqual(web_base_url("acme.ghe.com"), "https://acme.ghe.com")

    def test_parse_enterprise_url(self):
        self.assertEqual(
            parse_enterprise_url("https://acme.ghe.com/enterprises/acme-corp"),
            ("acme.ghe.com", "acme-corp"),
        )
        self.assertEqual(
            parse_enterprise_url("github.com/enterprises/octo/settings"),
            ("github.com", "octo"),
        )
        self.assertIsNone(parse_enterprise_url("acme-corp"))

    def test_client_host_properties(self):
        api = GitHubAPI(token="t", base_url=api_base_url("acme.ghe.com"))
        self.assertEqual(api.host, "acme.ghe.com")
        self.assertEqual(api.web_base, "https://acme.ghe.com")
        self.assertEqual(GitHubAPI(token="t").web_base, "https://github.com")


class PatHostResolutionTests(unittest.TestCase):
    def test_enterprise_url_sets_host_and_slug(self):
        host, slugs = pats._resolve_host_and_slugs("", ["https://acme.ghe.com/enterprises/acme", " other "])
        self.assertEqual(host, "acme.ghe.com")
        self.assertEqual(slugs, ["acme", "other"])

    def test_default_host(self):
        self.assertEqual(pats._resolve_host_and_slugs("", ["acme"]), ("github.com", ["acme"]))

    def test_conflicting_hosts_rejected(self):
        with self.assertRaises(ValueError):
            pats._resolve_host_and_slugs("github.com", ["https://acme.ghe.com/enterprises/acme"])


class APIManagerHostTests(unittest.IsolatedAsyncioTestCase):
    async def test_rebuild_uses_each_pats_host(self):
        manager = APIManager()
        fake_pats = [
            {"id": "p1", "label": "dotcom", "token": "a", "include_organizations": True},
            {"id": "p2", "label": "ghe", "token": "b", "host": "acme.ghe.com", "include_organizations": True,
             "enterprise_slugs": ["acme"]},
        ]
        created: list[str] = []

        def fake_api(token, base_url):
            created.append(base_url)
            api = AsyncMock()
            api.discover_user.return_value = {"login": f"user-{token}"}
            api.discover_orgs.return_value = [{"login": f"org-{token}"}]
            api.get_org_detail.return_value = {"company": ""}
            api.discover_enterprises.return_value = []
            return api

        with patch("backend.app.services.api_manager.pat_manager") as pm, \
                patch("backend.app.services.api_manager.GitHubAPI", side_effect=fake_api):
            pm.get_all.return_value = fake_pats
            await manager.rebuild()

            self.assertEqual(created, ["https://api.github.com", "https://api.acme.ghe.com"])
            self.assertEqual(manager.web_base_for_org("org-a"), "https://github.com")
            self.assertEqual(manager.web_base_for_org("org-b"), "https://acme.ghe.com")
            self.assertEqual(manager.web_base_for_enterprise("acme"), "https://acme.ghe.com")
            # Enterprise-level data lives under the "<slug>-enterprise" pseudo org
            self.assertEqual(manager.web_base_for_org("acme-enterprise"), "https://acme.ghe.com")


class OAuthHostTests(unittest.TestCase):
    def test_default_urls(self):
        self.assertEqual(auth._oauth_urls({}), (
            "https://github.com/login/oauth/authorize",
            "https://github.com/login/oauth/access_token",
            "https://api.github.com/user",
        ))

    def test_ghe_urls(self):
        self.assertEqual(auth._oauth_urls({"host": "acme.ghe.com"}), (
            "https://acme.ghe.com/login/oauth/authorize",
            "https://acme.ghe.com/login/oauth/access_token",
            "https://api.acme.ghe.com/user",
        ))


class CopilotClientHostTests(unittest.TestCase):
    def _options(self, configured, env=None):
        with patch.dict("os.environ", env or {}, clear=True), \
                patch("backend.app.services.pat_manager.pat_manager") as pm:
            pm.get_all.return_value = configured
            return copilot_engine.CopilotAIEngine._client_options()

    def test_skips_classic_pats_and_sets_ghe_host(self):
        options = self._options([
            {"label": "classic", "token": "ghp_x", "host": "github.com"},
            {"label": "fine", "token": "github_pat_y", "host": "acme.ghe.com"},
        ])
        self.assertEqual(options["github_token"], "github_pat_y")
        self.assertEqual(options["env"]["COPILOT_GH_HOST"], "acme.ghe.com")

    def test_github_com_pat_has_no_env_override(self):
        options = self._options([{"label": "fine", "token": "github_pat_y"}])
        self.assertNotIn("env", options)

    def test_pinned_host_env_wins(self):
        options = self._options(
            [{"label": "fine", "token": "github_pat_y", "host": "acme.ghe.com"}],
            env={"GH_HOST": "other.ghe.com"},
        )
        self.assertNotIn("env", options)

    def test_only_classic_pats_falls_back_to_cli_login(self):
        self.assertEqual(self._options([{"label": "classic", "token": "ghp_x"}]), {})


class ReportLinkTests(unittest.TestCase):
    def test_member_links_use_enterprise_host(self):
        cc = {"name": "cc", "members": [{"login": "mona", "source_type": "User", "source_name": "mona"}]}
        html = generate_single_report_html("acme", "Acme", cc, [], [], web_base="https://acme.ghe.com")
        self.assertIn("https://acme.ghe.com/mona", html)
        self.assertNotIn("https://github.com/mona", html)


if __name__ == "__main__":
    unittest.main()
