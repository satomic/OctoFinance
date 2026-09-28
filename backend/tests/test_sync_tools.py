import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

from copilot.tools import ToolInvocation

from backend.app.services.sync_manager import SyncManager
from backend.app.tools import sync_tools


async def _invoke(arguments: dict) -> dict:
    tool = sync_tools.create_sync_tools()[0]
    result = await tool.handler(ToolInvocation(tool_name="sync_data", arguments=arguments))
    return json.loads(result.text_result_for_llm)


class SyncDataToolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.manager = SyncManager()
        self.collector = AsyncMock()
        self.collector.sync_dataset.return_value = {"synced": ["cost_centers:acme"], "errors": []}
        self.collector.sync_all.return_value = [
            {"org": "o1", "synced": ["seats"], "errors": []},
            {"org": "__enterprise__", "synced": ["budgets"], "errors": ["boom"]},
        ]
        self.collector.sync_org.return_value = {"org": "o1", "synced": ["seats"], "errors": []}
        self.enterContext(patch.object(sync_tools, "sync_manager", self.manager))
        self.enterContext(patch.object(sync_tools, "data_collector", self.collector))

    async def test_dataset_sync_runs_through_sync_manager_and_waits(self):
        result = await _invoke({"dataset": "cost_centers"})

        self.collector.sync_dataset.assert_awaited_once()
        self.assertEqual(self.collector.sync_dataset.await_args.args[0], "cost_centers")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["synced"], ["cost_centers:acme"])
        self.assertFalse(self.manager.is_syncing)

    async def test_full_and_single_org_sync(self):
        full = await _invoke({})
        self.assertEqual(full["synced_count"], 2)
        self.assertEqual(full["errors"], ["boom"])

        await _invoke({"dataset": "all", "org": "o1"})
        self.collector.sync_org.assert_awaited_once()
        self.assertEqual(self.collector.sync_org.await_args.args[0], "o1")

    async def test_rejects_unknown_dataset_and_org_with_dataset(self):
        self.assertIn("error", await _invoke({"dataset": "seats"}))
        self.assertIn("error", await _invoke({"dataset": "budgets", "org": "o1"}))
        self.collector.sync_dataset.assert_not_awaited()

    async def test_waits_for_a_sync_already_in_progress(self):
        gate = asyncio.Event()

        async def slow(log_fn):
            await gate.wait()

        self.manager.run_in_background(slow)
        waiter = asyncio.create_task(_invoke({"dataset": "budgets"}))
        await asyncio.sleep(0.05)
        self.assertFalse(waiter.done())
        gate.set()
        result = await waiter

        self.assertEqual(result["status"], "already_running")
        self.assertTrue(result["finished"])
        self.collector.sync_dataset.assert_not_awaited()

    async def test_long_running_sync_does_not_block_a_dataset_refresh(self):
        gate = asyncio.Event()

        async def csv_fetch(log_fn):
            await gate.wait()

        self.manager.run_in_background(csv_fetch)
        with patch.object(sync_tools, "BUSY_WAIT_SECONDS", 0.05):
            result = await _invoke({"dataset": "cost_centers"})

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["synced"], ["cost_centers:acme"])
        self.assertTrue(self.manager.is_syncing)  # the other sync is left alone
        gate.set()
        await self.manager.wait_until_idle(1)


if __name__ == "__main__":
    unittest.main()
