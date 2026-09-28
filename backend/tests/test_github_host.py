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


class _FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


class _FakeHTTP:
    """Stands in for httpx.AsyncClient; records which URLs saw the token."""

    def __init__(self, valid_hosts, calls):
        self.valid_hosts, self.calls = valid_hosts, calls

    def __call__(self, *args, **kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, headers=None):
        self.calls.append(url)
        ok = any(url == f"https://api.{h}/user" for h in self.valid_hosts)
        return _FakeResponse(200 if ok else 401)


class CopilotTokenHostDetectionTests(unittest.IsolatedAsyncioTestCase):
    def _patch(self, pats, valid_hosts, env=None, sso_host=""):
        calls: list[str] = []
        self.enterContext(patch.dict("os.environ", env or {}, clear=True))
        pm = self.enterContext(patch("backend.app.services.pat_manager.pat_manager"))
        pm.get_all.return_value = pats
        store = self.enterContext(patch("backend.app.services.auth_store.auth_store"))
        store.get_oauth_config.return_value = {"host": sso_host}
        self.enterContext(patch.object(copilot_engine.httpx, "AsyncClient", _FakeHTTP(valid_hosts, calls)))
        return calls

    async def test_env_token_is_matched_to_its_ghe_host(self):
        calls = self._patch(
            [{"token": "ghp_a", "host": "other.ghe.com"}, {"token": "ghp_b", "host": "acme.ghe.com"}],
            valid_hosts=["acme.ghe.com"],
        )
        host = await copilot_engine.CopilotAIEngine._detect_token_host("github_pat_env")
        self.assertEqual(host, "acme.ghe.com")
        # The token is never sent to github.com
        self.assertTrue(all("api.github.com" not in url for url in calls))

    async def test_sso_host_is_a_candidate(self):
        self._patch([], valid_hosts=["sso.ghe.com"], sso_host="sso.ghe.com")
        self.assertEqual(await copilot_engine.CopilotAIEngine._detect_token_host("t"), "sso.ghe.com")

    async def test_no_match_means_github_com_without_probing_it(self):
        calls = self._patch([{"token": "ghp_a", "host": "acme.ghe.com"}], valid_hosts=[])
        self.assertIsNone(await copilot_engine.CopilotAIEngine._detect_token_host("t"))
        self.assertEqual(calls, ["https://api.acme.ghe.com/user"])

    async def test_pinned_host_skips_detection(self):
        calls = self._patch([{"token": "ghp_a", "host": "acme.ghe.com"}], ["acme.ghe.com"],
                            env={"COPILOT_GH_HOST": "acme.ghe.com"})
        self.assertIsNone(await copilot_engine.CopilotAIEngine._detect_token_host("t"))
        self.assertEqual(calls, [])

    async def test_start_client_passes_detected_host_to_cli(self):
        self._patch([{"token": "ghp_a", "host": "acme.ghe.com"}], valid_hosts=["acme.ghe.com"],
                    env={"COPILOT_GITHUB_TOKEN": "github_pat_env"})
        created: list[dict] = []

        class FakeClient:
            def __init__(self, **kwargs):
                created.append(kwargs)

            async def start(self):
                pass

            async def get_auth_status(self):
                return type("S", (), {"isAuthenticated": True})()

        with patch.object(copilot_engine, "CopilotClient", FakeClient):
            engine = copilot_engine.CopilotAIEngine()
            await engine._start_client()

        self.assertEqual(created[0]["github_token"], "github_pat_env")
        self.assertEqual(created[0]["env"]["COPILOT_GH_HOST"], "acme.ghe.com")
        self.assertEqual(engine._cli_host, "acme.ghe.com")


class ReportLinkTests(unittest.TestCase):
    def test_member_links_use_enterprise_host(self):
        cc = {"name": "cc", "members": [{"login": "mona", "source_type": "User", "source_name": "mona"}]}
        html = generate_single_report_html("acme", "Acme", cc, [], [], web_base="https://acme.ghe.com")
        self.assertIn("https://acme.ghe.com/mona", html)
        self.assertNotIn("https://github.com/mona", html)


if __name__ == "__main__":
    unittest.main()
