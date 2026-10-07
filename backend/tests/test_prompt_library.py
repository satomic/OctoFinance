import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.routers import prompts as routes
from backend.app.services import prompt_library as library


class PromptLibraryTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.object(library, "PROMPTS_FILE", Path(directory) / "saved_prompts.json"))

    def test_private_prompts_are_per_admin_and_shared_ones_visible_to_all(self):
        library.create_prompt("alice", "Mine", "private question")
        library.create_prompt("alice", "Team", "shared question", shared=True)
        self.assertEqual({p["title"] for p in library.list_prompts("ALICE")}, {"Mine", "Team"})
        bob_view = library.list_prompts("bob")
        self.assertEqual([p["title"] for p in bob_view], ["Team"])
        self.assertFalse(bob_view[0]["is_owner"])

    def test_title_defaults_to_prompt_start_and_text_is_required(self):
        entry = library.create_prompt("alice", "  ", "  List   inactive\nusers  ")
        self.assertEqual(entry["title"], "List inactive users")
        self.assertEqual(entry["prompt"], "List   inactive\nusers")
        with self.assertRaises(ValueError):
            library.create_prompt("alice", "Empty", "   ")
        with self.assertRaises(ValueError):
            library.create_prompt("alice", "x" * 81, "text")

    def test_only_owner_can_change_or_delete(self):
        entry = library.create_prompt("alice", "Team", "q", shared=True)
        with self.assertRaises(library.PromptForbidden):
            library.update_prompt("bob", entry["id"], title="hijack")
        with self.assertRaises(library.PromptForbidden):
            library.delete_prompt("bob", entry["id"])
        updated = library.update_prompt("Alice", entry["id"], prompt="new q", shared=False)
        self.assertEqual((updated["title"], updated["prompt"], updated["shared"]), ("Team", "new q", False))
        self.assertEqual(library.list_prompts("bob"), [])
        library.delete_prompt("alice", entry["id"])
        self.assertEqual(library.list_prompts("alice"), [])
        with self.assertRaises(library.PromptNotFound):
            library.delete_prompt("alice", entry["id"])

    def test_usage_orders_most_recently_used_first(self):
        first = library.create_prompt("alice", "First", "1")
        library.create_prompt("alice", "Second", "2")
        library.mark_used("alice", first["id"])
        prompts = library.list_prompts("alice")
        self.assertEqual(prompts[0]["title"], "First")
        self.assertEqual(prompts[0]["use_count"], 1)

    def test_cannot_use_another_admins_private_prompt(self):
        entry = library.create_prompt("alice", "Mine", "q")
        with self.assertRaises(library.PromptNotFound):
            library.mark_used("bob", entry["id"])

    def test_non_ascii_prompts_round_trip(self):
        library.create_prompt("alice", "成本分析", "按组织统计 AI credit 消耗")
        self.assertEqual(library.list_prompts("alice")[0]["prompt"], "按组织统计 AI credit 消耗")


class PromptAPITests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.object(library, "PROMPTS_FILE", Path(directory) / "saved_prompts.json"))
        app = FastAPI()
        app.include_router(routes.router, prefix="/api")
        self.client = TestClient(app)
        self.user = {"login": "alice", "is_admin": True}
        self.enterContext(patch.object(routes, "require_user", side_effect=lambda request: self.user))

    def test_crud_flow_and_error_codes(self):
        created = self.client.post("/api/prompts", json={"title": "Waste", "prompt": "Find waste", "shared": True})
        self.assertEqual(created.status_code, 200)
        prompt_id = created.json()["id"]
        self.assertEqual(self.client.post("/api/prompts", json={"prompt": " "}).status_code, 400)

        self.user = {"login": "bob", "is_admin": True}
        self.assertEqual(self.client.get("/api/prompts").json()["prompts"][0]["owner"], "alice")
        self.assertEqual(self.client.put(f"/api/prompts/{prompt_id}", json={"title": "x"}).status_code, 403)
        self.assertEqual(self.client.delete(f"/api/prompts/{prompt_id}").status_code, 403)
        self.assertEqual(self.client.post(f"/api/prompts/{prompt_id}/use").json()["use_count"], 1)

        self.user = {"login": "alice", "is_admin": True}
        self.assertEqual(self.client.put(f"/api/prompts/{prompt_id}", json={"title": "Waste v2"}).json()["title"], "Waste v2")
        self.assertEqual(self.client.delete(f"/api/prompts/{prompt_id}").json(), {"ok": True})
        self.assertEqual(self.client.delete(f"/api/prompts/{prompt_id}").status_code, 404)

    def test_requires_login(self):
        self.user = None
        self.assertEqual(self.client.get("/api/prompts").status_code, 401)


if __name__ == "__main__":
    unittest.main()
