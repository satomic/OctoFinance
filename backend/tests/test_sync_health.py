import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.routers import pats as pat_routes
from backend.app.services import credential_health
from backend.app.services.pat_manager import PATManager
from backend.app.services.sync_manager import SyncManager

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


class ClassifyTests(unittest.TestCase):
    def test_parses_github_expiry_header_formats(self):
        self.assertEqual(credential_health.parse_expiry("2026-10-20 08:00:00 UTC").isoformat(), "2026-10-20T08:00:00+00:00")
        self.assertEqual(credential_health.parse_expiry("2026-10-20 08:00:00 +0800").utcoffset().total_seconds(), 8 * 3600)
        self.assertIsNone(credential_health.parse_expiry("not a date"))
        self.assertIsNone(credential_health.parse_expiry(None))

    def test_states(self):
        self.assertEqual(credential_health.classify(200, now=NOW)["state"], "ok")
        self.assertEqual(credential_health.classify(200, expiry="2026-12-01 00:00:00 UTC", now=NOW)["state"], "ok")
        expiring = credential_health.classify(200, expiry="2026-10-10 00:00:00 UTC", now=NOW)
        self.assertEqual((expiring["state"], expiring["expires_at"][:10]), ("expiring", "2026-10-10"))
        invalid = credential_health.classify(401, now=NOW)
        self.assertEqual((invalid["state"], invalid["detail"]), ("invalid", "Bad credentials"))
        self.assertEqual(credential_health.classify(403, "Resource protected by SAML", now=NOW)["state"], "forbidden")
        self.assertEqual(credential_health.classify(None, "ConnectTimeout", now=NOW)["state"], "unreachable")
        self.assertEqual(credential_health.classify(502, now=NOW)["state"], "unreachable")

    def test_describe_tells_the_admin_what_to_do(self):
        pat = {"id": "p1", "label": "prod", "host": "github.com"}
        message = credential_health.describe(pat, credential_health.classify(401, now=NOW))
        self.assertIn("PAT 'prod' (github.com)", message)
        self.assertIn("HTTP 401", message)
        self.assertIn("expired or been revoked", message)


class CheckTokenTests(unittest.IsolatedAsyncioTestCase):
    async def _check(self, handler):
        transport = httpx.MockTransport(handler)
        original = httpx.AsyncClient.__init__

        def init(client, *args, **kwargs):
            kwargs["transport"] = transport
            original(client, *args, **kwargs)

        with patch.object(httpx.AsyncClient, "__init__", init):
            return await credential_health.check_token("ghp_x", "github.com")

    async def test_valid_token_reports_login_and_expiry(self):
        result = await self._check(lambda request: httpx.Response(
            200, json={"login": "octo"}, headers={credential_health.EXPIRY_HEADER: "2099-01-01 00:00:00 UTC"}))
        self.assertEqual((result["state"], result["login"], result["expires_at"][:4]), ("ok", "octo", "2099"))

    async def test_rejected_token_carries_github_message(self):
        result = await self._check(lambda request: httpx.Response(401, json={"message": "Bad credentials"}))
        self.assertEqual((result["state"], result["status"], result["detail"]), ("invalid", 401, "Bad credentials"))

    async def test_network_error_is_unreachable(self):
        def fail(request):
            raise httpx.ConnectError("no route", request=request)
        with patch.object(credential_health, "NETWORK_RETRY_DELAY", 0):
            result = await self._check(fail)
        self.assertEqual(result["state"], "unreachable")
        self.assertIn("ConnectError", result["detail"])

    async def test_single_network_blip_is_retried(self):
        calls = []

        def flaky(request):
            calls.append(request)
            if len(calls) == 1:
                raise httpx.ConnectError("blip", request=request)
            return httpx.Response(401, json={"message": "Bad credentials"})
        with patch.object(credential_health, "NETWORK_RETRY_DELAY", 0):
            result = await self._check(flaky)
        self.assertEqual((len(calls), result["state"]), (2, "invalid"))


class CredentialStoreTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch("backend.app.services.pat_manager.PATS_FILE", Path(directory) / "pats.json"))
        self.pats = PATManager()
        self.pats.load()
        self.enterContext(patch.object(credential_health, "pat_manager", self.pats))
        self.good = self.pats.add("good", "ghp_good")
        self.bad = self.pats.add("bad", "ghp_bad")

    async def test_check_all_records_state_logs_problems_and_lists_them(self):
        async def fake_check(token, host):
            return credential_health.classify(200 if token == "ghp_good" else 401)

        logs = []
        with patch.object(credential_health, "check_token", side_effect=fake_check):
            await credential_health.check_all(lambda level, message: logs.append((level, message)))

        self.assertEqual(self.pats.find_by_id(self.good["id"])["credential"]["state"], "ok")
        self.assertEqual([level for level, _ in logs], ["error"])
        self.assertIn("PAT 'bad'", logs[0][1])
        problems = credential_health.problems()
        self.assertEqual([(p["label"], p["state"]) for p in problems], [("bad", "invalid")])
        # The token never leaves the server through the problem list
        self.assertNotIn("ghp_bad", json.dumps(problems))

    async def test_fixed_token_clears_the_problem(self):
        self.pats.update(self.bad["id"], credential=credential_health.classify(401))
        with patch.object(credential_health, "check_token", AsyncMock(return_value=credential_health.classify(200))):
            await credential_health.check_all()
        self.assertEqual(credential_health.problems(), [])

    def test_record_failure_from_discovery(self):
        request = httpx.Request("GET", "https://api.github.com/user")
        error = httpx.HTTPStatusError("401", request=request, response=httpx.Response(401, json={"message": "Bad credentials"}, request=request))
        credential_health.record_failure(self.bad["id"], error)
        self.assertEqual(self.pats.find_by_id(self.bad["id"])["credential"]["state"], "invalid")
        credential_health.record_failure(self.good["id"], ValueError("not an HTTP problem"))
        self.assertNotIn("credential", self.pats.find_by_id(self.good["id"]))

    async def test_preflight_rediscovers_pats_that_now_work(self):
        api_manager = unittest.mock.MagicMock()
        api_manager.get_discovered_users.return_value = {self.good["id"]: {"login": "x"}}
        api_manager.rebuild = AsyncMock()

        async def fake_check(token, host):
            return credential_health.classify(200)

        with patch("backend.app.services.api_manager.api_manager", api_manager), \
                patch.object(credential_health, "check_token", side_effect=fake_check):
            await credential_health.preflight(lambda level, message: None)
        api_manager.rebuild.assert_awaited_once()


class SyncOutcomeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.status_file = Path(directory) / "sync_status.json"
        self.manager = SyncManager(status_file=self.status_file)

    async def _run(self, coro_fn, trigger="manual"):
        self.assertTrue(self.manager.run_in_background(coro_fn, trigger=trigger))
        await self.manager.wait_until_idle(5)
        return self.manager.status

    async def test_clean_run_is_success_and_sets_last_success(self):
        async def ok(log_fn):
            log_fn("info", "seats synced")
            log_fn("warn", "org x has no Copilot")
        status = await self._run(ok, trigger="scheduled")
        run = status["last_run"]
        self.assertEqual((run["status"], run["trigger"], run["error_count"], run["warning_count"]), ("success", "scheduled", 0, 1))
        self.assertEqual(status["last_success_at"], run["finished_at"])

    async def test_logged_errors_mark_the_run_failed_but_keep_last_success(self):
        async def ok(log_fn):
            pass
        first = (await self._run(ok))["last_success_at"]

        async def unauthorized(log_fn):
            log_fn("error", "  org-a: seats unavailable | HTTP 401 | Bad credentials")
            log_fn("error", "  org-a: billing unavailable | HTTP 401")
        status = await self._run(unauthorized, trigger="scheduled")
        run = status["last_run"]
        self.assertEqual((run["status"], run["error_count"]), ("failed", 2))
        self.assertEqual(run["errors"][0], "org-a: seats unavailable | HTTP 401 | Bad credentials")
        self.assertEqual(status["last_success_at"], first)

    async def test_exception_is_recorded_first(self):
        async def boom(log_fn):
            raise RuntimeError("network down")
        run = (await self._run(boom))["last_run"]
        self.assertEqual(run["status"], "failed")
        self.assertEqual(run["errors"][0], "network down")

    async def test_outcome_survives_restart(self):
        async def bad(log_fn):
            log_fn("error", "HTTP 401")
        await self._run(bad, trigger="scheduled")
        reloaded = SyncManager(status_file=self.status_file).status
        self.assertEqual((reloaded["last_run"]["status"], reloaded["last_run"]["trigger"]), ("failed", "scheduled"))

    async def test_preflight_runs_first_and_its_errors_count(self):
        order = []

        async def preflight(log_fn):
            order.append("preflight")
            log_fn("error", "PAT 'prod' was rejected by GitHub (HTTP 401)")

        async def sync(log_fn):
            order.append("sync")
        self.manager.set_preflight(preflight)
        run = (await self._run(sync))["last_run"]
        self.assertEqual(order, ["preflight", "sync"])
        self.assertEqual(run["status"], "failed")
        self.assertIn("HTTP 401", run["errors"][0])

    async def test_broken_preflight_does_not_block_the_sync(self):
        ran = []

        async def preflight(log_fn):
            raise RuntimeError("boom")

        async def sync(log_fn):
            ran.append(True)
        self.manager.set_preflight(preflight)
        run = (await self._run(sync))["last_run"]
        self.assertEqual(ran, [True])
        self.assertEqual(run["status"], "success")

    async def test_sync_complete_event_reports_failure(self):
        queue = self.manager.subscribe()

        async def bad(log_fn):
            log_fn("error", "HTTP 401")
        await self._run(bad, trigger="scheduled")
        events = []
        while not queue.empty():
            events.append(queue.get_nowait())
        complete = [e for e in events if e["type"] == "sync_complete"][0]
        self.assertEqual((complete["success"], complete["error_count"], complete["trigger"]), (False, 1, "scheduled"))


class ReplaceTokenAPITests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch("backend.app.services.pat_manager.PATS_FILE", Path(directory) / "pats.json"))
        self.pats = PATManager()
        self.pats.load()
        self.pat = self.pats.add("prod", "ghp_old")
        self.pats.update(self.pat["id"], user_login="octo", credential=credential_health.classify(401))
        self.pats.add("other", "ghp_taken")
        self.enterContext(patch.object(pat_routes, "pat_manager", self.pats))
        self.manager = SyncManager(status_file=Path(directory) / "sync_status.json")
        self.enterContext(patch.object(pat_routes, "sync_manager", self.manager))
        self.rebuild = self.enterContext(patch.object(pat_routes.api_manager, "rebuild", AsyncMock()))
        self.manager.run_in_background = lambda *args, **kwargs: True
        app = FastAPI()
        app.include_router(pat_routes.router, prefix="/api")
        self.client = TestClient(app)

    def _put(self, token, check):
        with patch.object(credential_health, "check_token", AsyncMock(return_value=check)):
            return self.client.put(f"/api/pats/{self.pat['id']}", json={"token": token})

    def test_rejected_replacement_keeps_old_token(self):
        response = self._put("ghp_still_bad", credential_health.classify(401))
        self.assertEqual(response.status_code, 400)
        self.assertIn("HTTP 401", response.json()["detail"])
        self.assertEqual(self.pats.find_by_id(self.pat["id"])["token"], "ghp_old")
        self.rebuild.assert_not_awaited()

    def test_valid_replacement_clears_problem_and_resyncs(self):
        response = self._put("ghp_new", {**credential_health.classify(200), "login": "octo"})
        self.assertEqual(response.status_code, 200)
        body = response.json()["pat"]
        self.assertNotIn("token", body)
        self.assertEqual(body["credential"]["state"], "ok")
        self.assertEqual(self.pats.find_by_id(self.pat["id"])["token"], "ghp_new")
        self.rebuild.assert_awaited_once()

    def test_duplicate_token_is_rejected(self):
        response = self._put("ghp_taken", credential_health.classify(200))
        self.assertEqual(response.status_code, 400)
        self.assertIn("already configured", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
