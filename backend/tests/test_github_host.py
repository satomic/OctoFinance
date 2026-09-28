import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from backend.app.routers import auth, pats
from backend.app.services import chat_auth_store as chat_auth_store_module
from backend.app.services import copilot_engine
from backend.app.services.chat_auth_store import chat_auth_store
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


class _FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code

    def json(self):
        return {"login": "token-owner"}


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


class _FakeCopilotClient:
    """Stands in for CopilotClient. ``accepts`` decides whether a token authenticates."""

    created: list[dict] = []
    accepts = staticmethod(lambda kwargs: True)
    models_error: str | None = None
    reports_login = True

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        _FakeCopilotClient.created.append(kwargs)

    async def start(self):
        pass

    async def stop(self):
        pass

    async def get_auth_status(self):
        ok = _FakeCopilotClient.accepts(self.kwargs)
        host = (self.kwargs.get("env") or {}).get("COPILOT_GH_HOST", "github.com")
        return type("S", (), {
            "isAuthenticated": ok,
            "login": "mona" if ok and _FakeCopilotClient.reports_login else None,
            "host": f"https://{host}" if ok else None,
            "statusMessage": None if ok else "Bad credentials",
        })()

    async def list_models(self):
        if _FakeCopilotClient.models_error:
            raise RuntimeError(_FakeCopilotClient.models_error)
        return [object(), object()]


class CopilotChatAuthTests(unittest.IsolatedAsyncioTestCase):
    """Credential and host resolution for the AI chat engine."""

    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.enterContext(patch.object(chat_auth_store_module, "CHAT_AUTH_FILE", Path(directory) / "copilot_chat.json"))
        self.pm = self.enterContext(patch("backend.app.services.pat_manager.pat_manager"))
        self.pm.get_all.return_value = []
        store = self.enterContext(patch("backend.app.services.auth_store.auth_store"))
        store.get_oauth_config.return_value = {"host": ""}
        self.calls: list[str] = []
        self.valid_hosts: list[str] = []
        self.enterContext(patch.object(copilot_engine.httpx, "AsyncClient", _FakeHTTP(self.valid_hosts, self.calls)))
        _FakeCopilotClient.created = []
        _FakeCopilotClient.accepts = staticmethod(lambda kwargs: True)
        _FakeCopilotClient.models_error = None
        _FakeCopilotClient.reports_login = True
        self.enterContext(patch.object(copilot_engine, "CopilotClient", _FakeCopilotClient))

    def _env(self, **env):
        self.enterContext(patch.dict("os.environ", env, clear=True))

    async def _start(self):
        engine = copilot_engine.CopilotAIEngine()
        await engine._start_client()
        return engine, _FakeCopilotClient.created[0]

    # --- token source ---------------------------------------------------

    async def test_settings_token_wins_over_env(self):
        self._env(COPILOT_GITHUB_TOKEN="github_pat_env")
        chat_auth_store.save(token="github_pat_settings")
        engine, kwargs = await self._start()
        self.assertEqual(kwargs["github_token"], "github_pat_settings")
        self.assertEqual(engine._auth_status["source"]["kind"], "settings")
        self.assertEqual(engine._auth_status["source"]["token_masked"], "gith***ings")

    async def test_env_then_fine_grained_pat_then_cli_login(self):
        self._env(COPILOT_GITHUB_TOKEN="github_pat_env")
        self.assertEqual(copilot_engine.CopilotAIEngine._resolve_credentials()[1]["kind"], "env")
        self._env()
        self.pm.get_all.return_value = [
            {"label": "classic", "token": "ghp_x"},
            {"label": "fine", "token": "github_pat_y", "host": "acme.ghe.com"},
        ]
        options, source = copilot_engine.CopilotAIEngine._resolve_credentials()
        self.assertEqual((options["github_token"], source["kind"], source["pat_host"]),
                         ("github_pat_y", "pat", "acme.ghe.com"))
        self.pm.get_all.return_value = [{"label": "classic", "token": "ghp_x"}]
        self.assertEqual(copilot_engine.CopilotAIEngine._resolve_credentials(),
                         ({}, {"kind": "cli_login", "detail": "", "token_masked": ""}))

    # --- host -----------------------------------------------------------

    async def test_settings_host_pins_cli_host_over_env(self):
        self._env(COPILOT_GITHUB_TOKEN="t", COPILOT_GH_HOST="other.ghe.com")
        chat_auth_store.save(host="https://acme.ghe.com/")
        engine, kwargs = await self._start()
        self.assertEqual(kwargs["env"]["COPILOT_GH_HOST"], "acme.ghe.com")
        self.assertEqual(self.calls, [])  # pinned: no detection

    async def test_settings_host_github_com_overrides_gh_host(self):
        self._env(COPILOT_GITHUB_TOKEN="t", GH_HOST="acme.ghe.com")
        chat_auth_store.save(host="github.com")
        _, kwargs = await self._start()
        self.assertEqual(kwargs["env"]["COPILOT_GH_HOST"], "github.com")

    async def test_env_pinned_host_is_left_to_the_cli(self):
        self._env(COPILOT_GITHUB_TOKEN="t", GH_HOST="acme.ghe.com")
        self.pm.get_all.return_value = [{"token": "ghp_a", "host": "acme.ghe.com"}]
        engine, kwargs = await self._start()
        self.assertNotIn("env", kwargs)
        self.assertEqual(self.calls, [])
        self.assertEqual(engine._auth_status["requested_host"], "acme.ghe.com")

    async def test_fallback_pat_uses_its_own_host(self):
        self._env()
        self.pm.get_all.return_value = [{"label": "fine", "token": "github_pat_y", "host": "acme.ghe.com"}]
        _, kwargs = await self._start()
        self.assertEqual(kwargs["env"]["COPILOT_GH_HOST"], "acme.ghe.com")

    async def test_env_token_is_matched_to_its_ghe_host_without_probing_github_com(self):
        self._env(COPILOT_GITHUB_TOKEN="github_pat_env")
        self.pm.get_all.return_value = [{"token": "ghp_a", "host": "other.ghe.com"},
                                        {"token": "ghp_b", "host": "acme.ghe.com"}]
        self.valid_hosts.append("acme.ghe.com")
        engine, kwargs = await self._start()
        self.assertEqual(kwargs["env"]["COPILOT_GH_HOST"], "acme.ghe.com")
        self.assertEqual(engine._cli_host, "acme.ghe.com")
        self.assertTrue(all("api.github.com" not in url for url in self.calls))

    async def test_sso_host_is_a_detection_candidate(self):
        self._env(COPILOT_GITHUB_TOKEN="t")
        from backend.app.services import auth_store
        auth_store.auth_store.get_oauth_config.return_value = {"host": "sso.ghe.com"}
        self.valid_hosts.append("sso.ghe.com")
        _, kwargs = await self._start()
        self.assertEqual(kwargs["env"]["COPILOT_GH_HOST"], "sso.ghe.com")

    async def test_no_match_means_github_com(self):
        self._env(COPILOT_GITHUB_TOKEN="t")
        self.pm.get_all.return_value = [{"token": "ghp_a", "host": "acme.ghe.com"}]
        _, kwargs = await self._start()
        self.assertNotIn("env", kwargs)
        self.assertEqual(self.calls, ["https://api.acme.ghe.com/user"])

    # --- status ----------------------------------------------------------

    async def test_status_reports_login_host_and_models(self):
        self._env()
        chat_auth_store.save(token="github_pat_s", host="acme.ghe.com")
        engine, _ = await self._start()
        status = engine._auth_status
        self.assertTrue(status["authenticated"])
        self.assertEqual((status["login"], status["host"], status["models_available"]),
                         ("mona", "acme.ghe.com", 2))
        self.assertFalse(status["fallback_used"])

    async def test_login_is_looked_up_on_the_cli_host_when_the_cli_omits_it(self):
        self._env()
        chat_auth_store.save(token="github_pat_s", host="acme.ghe.com")
        _FakeCopilotClient.reports_login = False
        self.valid_hosts.append("acme.ghe.com")
        engine, _ = await self._start()
        self.assertEqual(engine._auth_status["login"], "token-owner")
        self.assertEqual(self.calls, ["https://api.acme.ghe.com/user"])

    async def test_policy_denial_is_reported(self):
        self._env()
        chat_auth_store.save(token="github_pat_s")
        _FakeCopilotClient.models_error = "403 unauthorized: not authorized to use this Copilot feature"
        engine, _ = await self._start()
        self.assertTrue(engine._auth_status["authenticated"])
        self.assertEqual(engine._auth_status["models_available"], 0)
        self.assertIn("403", engine._auth_status["models_error"])

    async def test_rejected_token_falls_back_and_says_so(self):
        self._env()
        chat_auth_store.save(token="github_pat_bad")
        _FakeCopilotClient.accepts = staticmethod(lambda kwargs: "github_token" not in kwargs)
        engine = copilot_engine.CopilotAIEngine()
        await engine._start_client()
        self.assertTrue(_FakeCopilotClient.created[1]["use_logged_in_user"])
        self.assertTrue(engine._auth_status["fallback_used"])
        self.assertIn("Bad credentials", engine._auth_status["error"])
        self.assertEqual(engine._auth_status["source"]["kind"], "settings")


class ChatAuthStoreTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.enterContext(patch.object(chat_auth_store_module, "CHAT_AUTH_FILE", Path(directory) / "c.json"))

    def test_save_keep_and_clear(self):
        self.assertEqual(chat_auth_store.get(), {"token": "", "host": ""})
        chat_auth_store.save(token=" github_pat_x ", host="API.acme.ghe.com")
        self.assertEqual(chat_auth_store.get(), {"token": "github_pat_x", "host": "acme.ghe.com"})
        chat_auth_store.save(token="", host=None)  # blank token keeps the stored one
        self.assertEqual(chat_auth_store.get()["token"], "github_pat_x")
        chat_auth_store.save(clear_token=True, host="")
        self.assertEqual(chat_auth_store.get(), {"token": "", "host": ""})

    def test_invalid_host_is_rejected_and_nothing_saved(self):
        chat_auth_store.save(token="github_pat_x")
        with self.assertRaises(ValueError):
            chat_auth_store.save(token="github_pat_y", host="github.example.com")
        self.assertEqual(chat_auth_store.get()["token"], "github_pat_x")


class ChatAuthApiTests(unittest.TestCase):
    def setUp(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from backend.app.routers import chat

        directory = self.enterContext(TemporaryDirectory())
        self.enterContext(patch.object(chat_auth_store_module, "CHAT_AUTH_FILE", Path(directory) / "c.json"))
        self.engine = self.enterContext(patch.object(chat, "copilot_engine"))
        self.engine.get_auth_status = AsyncMock(return_value={"authenticated": True, "login": "mona"})
        self.engine.apply_auth_settings = AsyncMock(return_value={"authenticated": True, "login": "mona"})
        app = FastAPI()
        app.include_router(chat.router, prefix="/api")
        self.client = TestClient(app)

    def test_put_saves_masks_and_reconnects(self):
        res = self.client.put("/api/chat/auth", json={"token": "github_pat_abcdefgh1234", "host": "acme.ghe.com"})
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["config"], {"token_set": True, "token_masked": "gith***1234", "host": "acme.ghe.com"})
        self.assertNotIn("github_pat_abcdefgh1234", res.text)
        self.engine.apply_auth_settings.assert_awaited_once()
        self.assertEqual(self.client.get("/api/chat/auth").json()["config"]["token_masked"], "gith***1234")

    def test_put_rejects_bad_host(self):
        res = self.client.put("/api/chat/auth", json={"host": "evil.example.com"})
        self.assertEqual(res.status_code, 400)
        self.engine.apply_auth_settings.assert_not_awaited()

    def test_get_refresh_is_passed_through(self):
        self.client.get("/api/chat/auth?refresh=true")
        self.engine.get_auth_status.assert_awaited_with(refresh=True)


class ReportLinkTests(unittest.TestCase):
    def test_member_links_use_enterprise_host(self):
        cc = {"name": "cc", "members": [{"login": "mona", "source_type": "User", "source_name": "mona"}]}
        html = generate_single_report_html("acme", "Acme", cc, [], [], web_base="https://acme.ghe.com")
        self.assertIn("https://acme.ghe.com/mona", html)
        self.assertNotIn("https://github.com/mona", html)


if __name__ == "__main__":
    unittest.main()
