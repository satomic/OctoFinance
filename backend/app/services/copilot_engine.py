"""
Copilot SDK AI Engine - Core AI-powered FinOps analysis engine.
Uses the Copilot Python SDK to create sessions with custom FinOps tools.
Supports resuming persisted sessions across backend restarts.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import AsyncIterator, TYPE_CHECKING

from copilot import CopilotClient, CopilotSession
from copilot.generated.session_events import SessionEvent, SessionEventType

from .data_collector import create_session_collector
from ..tools.action_tools import create_action_tools
from ..tools.billing_tools import create_billing_tools
from ..tools.seat_tools import create_seat_tools
from ..tools.usage_tools import create_usage_tools

if TYPE_CHECKING:
    from .api_manager import APIManager

logger = logging.getLogger(__name__)

# File written inside each session's working_directory to persist the SDK session ID.
_SDK_SESSION_ID_FILE = ".copilot_session_id"

FINOPS_SYSTEM_PROMPT = """You are OctoFinance AI FinOps Assistant, specialized in helping GitHub Copilot administrators optimize costs and manage seats efficiently.

Your responsibilities:
1. Proactively analyze Copilot usage data to identify waste and inefficiency
2. Provide specific cost optimization recommendations with estimated savings amounts
3. Execute operational actions (remove/add seats) after admin confirmation
4. Compare across organizations, teams, and users
5. Generate FinOps reports and insights

Key behaviors:
- Always use the provided tools to get real data before making recommendations
- Include specific numbers: cost, savings, user counts, dates
- When recommending seat removal, use record_recommendation to create actionable items
- Respond in the same language as the user's message
- Be proactive: if asked about usage, also mention cost implications
- For destructive operations (seat removal), always explain the impact first and ask for confirmation

Available data dimensions:
- Seats: who has Copilot, when they last used it, which team they belong to
- Usage Reports: org-level and user-level usage metrics (28-day or specific day), feature adoption, engagement data
- Billing: plan type, cost per seat, total cost, waste
- Metrics: detailed IDE completions, chat usage, PR summaries (legacy API)
- Premium Requests: per-model breakdown of premium request consumption, pricing, and costs

Copilot Premium Requests quota (included free per user per month):
- Copilot Business: 300 premium requests/user/month
- Copilot Enterprise: 1000 premium requests/user/month
Requests beyond the included quota are billed at $0.04 per request. Use this information when analyzing premium request usage and cost optimization.
Note: Per-user premium request breakdown is NOT available via API — only org-level totals by model. Per-user data can only be obtained through the GitHub UI email export.

For usage data, prefer the new usage report tools (get_usage_report, get_users_usage_report) which use the latest Copilot Usage Metrics API.
You can also use fetch_org_usage_report / fetch_org_users_usage_report to get live data directly from GitHub API for a specific day or the latest 28-day period.
"""


class CopilotAIEngine:
    """Manages Copilot SDK client and sessions for AI-powered FinOps."""

    def __init__(self):
        self._client: CopilotClient | None = None
        self._sessions: dict[str, CopilotSession] = {}
        self._api_manager: APIManager | None = None

    def set_api_manager(self, api_manager: APIManager):
        """Set the API manager for tool creation."""
        self._api_manager = api_manager

    async def start(self):
        """Start the Copilot SDK client."""
        self._client = CopilotClient()
        await self._client.start()

    async def stop(self):
        """Stop all sessions and the client."""
        for session in self._sessions.values():
            try:
                await session.destroy()
            except Exception:
                pass
        self._sessions.clear()
        if self._client:
            await self._client.stop()
            self._client = None

    def is_ready(self) -> bool:
        return self._client is not None and self._client.get_state() == "connected"

    def _build_tools_for_session(self, working_directory: str | None) -> list:
        """Build a set of tools scoped to a session's data directory."""
        if working_directory:
            collector = create_session_collector(
                Path(working_directory),
                api_manager=self._api_manager,
            )
        else:
            from .data_collector import data_collector
            collector = data_collector

        tools = (
            create_seat_tools(collector, api_manager=self._api_manager)
            + create_usage_tools(collector, api_manager=self._api_manager)
            + create_billing_tools(collector)
            + create_action_tools(api_manager=self._api_manager, collector=collector)
        )
        return tools

    # ------------------------------------------------------------------
    # Session lifecycle: get / resume / create
    # ------------------------------------------------------------------

    async def get_or_create_session(
        self, session_id: str = "default", working_directory: str | None = None
    ) -> CopilotSession:
        """Return an in-memory session, try to resume a persisted one, or create new."""
        # 1. Fast path — already in memory
        if session_id in self._sessions:
            return self._sessions[session_id]

        # 2. Try resuming from the SDK session ID persisted on disk
        sdk_session_id = self._read_sdk_session_id(working_directory)
        if sdk_session_id:
            try:
                session = await self._resume_session(session_id, sdk_session_id, working_directory)
                logger.info("Resumed Copilot session %s (SDK %s)", session_id, sdk_session_id)
                return session
            except Exception as exc:
                logger.warning(
                    "Failed to resume SDK session %s, creating new: %s",
                    sdk_session_id, exc,
                )

        # 3. Create brand-new session
        return await self._create_session(session_id, working_directory)

    async def _resume_session(
        self,
        session_id: str,
        sdk_session_id: str,
        working_directory: str | None = None,
    ) -> CopilotSession:
        """Resume a previously persisted Copilot SDK session."""
        if not self._client:
            raise RuntimeError("Copilot client not started")

        session_tools = self._build_tools_for_session(working_directory)

        resume_config: dict = {
            "tools": session_tools,
            "system_message": {
                "mode": "append",
                "content": FINOPS_SYSTEM_PROMPT,
            },
            "on_permission_request": self._auto_approve,
        }
        if working_directory:
            resume_config["working_directory"] = working_directory

        session = await self._client.resume_session(sdk_session_id, resume_config)
        self._sessions[session_id] = session
        # Update the persisted ID (it should be the same, but be safe)
        self._write_sdk_session_id(working_directory, session.session_id)
        return session

    async def _create_session(
        self, session_id: str = "default", working_directory: str | None = None
    ) -> CopilotSession:
        """Create a brand-new Copilot session with FinOps tools."""
        if not self._client:
            raise RuntimeError("Copilot client not started")

        session_tools = self._build_tools_for_session(working_directory)

        session_config: dict = {
            "tools": session_tools,
            "system_message": {
                "mode": "append",
                "content": FINOPS_SYSTEM_PROMPT,
            },
            "on_permission_request": self._auto_approve,
        }
        if working_directory:
            session_config["working_directory"] = working_directory

        session = await self._client.create_session(session_config)
        self._sessions[session_id] = session

        # Persist SDK session ID so we can resume after restart
        self._write_sdk_session_id(working_directory, session.session_id)
        logger.info("Created new Copilot session %s (SDK %s)", session_id, session.session_id)
        return session

    async def _retry_with_new_session(
        self, session_id: str, working_directory: str | None = None
    ) -> CopilotSession:
        """Discard stale in-memory session and create a fresh one."""
        old = self._sessions.pop(session_id, None)
        if old:
            try:
                await old.destroy()
            except Exception:
                pass
        return await self._create_session(session_id, working_directory)

    # ------------------------------------------------------------------
    # SDK session ID persistence helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _read_sdk_session_id(working_directory: str | None) -> str | None:
        if not working_directory:
            return None
        path = Path(working_directory) / _SDK_SESSION_ID_FILE
        if path.is_file():
            return path.read_text(encoding="utf-8").strip() or None
        return None

    @staticmethod
    def _write_sdk_session_id(working_directory: str | None, sdk_session_id: str):
        if not working_directory:
            return
        path = Path(working_directory) / _SDK_SESSION_ID_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(sdk_session_id, encoding="utf-8")

    async def chat(
        self, message: str, session_id: str = "default", working_directory: str | None = None
    ) -> AsyncIterator[dict]:
        """
        Send a message and yield response events as they arrive.
        Yields dicts with: {"type": "delta"|"message"|"tool"|"idle", "content": ...}
        """
        session = await self.get_or_create_session(session_id, working_directory)

        # Use an asyncio.Queue to bridge the sync event handler with async generator
        queue: asyncio.Queue[dict | None] = asyncio.Queue()

        def _serialize_args(val):
            """Safely serialize tool arguments to a JSON string."""
            if val is None:
                return None
            import json
            try:
                if isinstance(val, str):
                    return val
                return json.dumps(val, ensure_ascii=False, default=str)
            except Exception:
                return str(val)

        def on_event(event: SessionEvent):
            if event.type == SessionEventType.ASSISTANT_MESSAGE_DELTA:
                queue.put_nowait({
                    "type": "delta",
                    "content": getattr(event.data, "delta_content", ""),
                })
            elif event.type == SessionEventType.ASSISTANT_MESSAGE:
                queue.put_nowait({
                    "type": "message",
                    "content": getattr(event.data, "content", ""),
                })
            elif event.type == SessionEventType.ASSISTANT_REASONING_DELTA:
                text = getattr(event.data, "reasoning_text", None)
                if text:
                    queue.put_nowait({
                        "type": "thinking_delta",
                        "content": text,
                    })
            elif event.type == SessionEventType.TOOL_EXECUTION_START:
                tool_name = getattr(event.data, "tool_name", "unknown")
                tool_call_id = getattr(event.data, "tool_call_id", None)
                arguments = getattr(event.data, "arguments", None)
                queue.put_nowait({
                    "type": "tool_start",
                    "content": tool_name,
                    "tool_call_id": tool_call_id,
                    "detail": _serialize_args(arguments),
                })
            elif event.type == SessionEventType.TOOL_EXECUTION_COMPLETE:
                tool_name = getattr(event.data, "tool_name", None)
                tool_call_id = getattr(event.data, "tool_call_id", None)
                result_obj = getattr(event.data, "result", None)
                result_text = None
                if result_obj is not None:
                    result_text = getattr(result_obj, "content", None)
                queue.put_nowait({
                    "type": "tool_complete",
                    "content": tool_name,
                    "tool_call_id": tool_call_id,
                    "detail": result_text,
                })
            elif event.type == SessionEventType.ASSISTANT_USAGE:
                data = event.data
                queue.put_nowait({
                    "type": "usage",
                    "content": getattr(data, "model", ""),
                    "detail": _serialize_args({
                        "input_tokens": getattr(data, "input_tokens", None),
                        "output_tokens": getattr(data, "output_tokens", None),
                        "cost": getattr(data, "cost", None),
                        "duration": getattr(data, "duration", None),
                    }),
                })
            elif event.type == SessionEventType.SESSION_IDLE:
                queue.put_nowait(None)  # Signal end
            elif event.type == SessionEventType.SESSION_ERROR:
                queue.put_nowait({
                    "type": "error",
                    "content": str(getattr(event.data, "message", "Unknown error")),
                })
                queue.put_nowait(None)

        unsubscribe = session.on(on_event)
        try:
            try:
                await session.send({"prompt": message})
            except Exception as send_err:
                if "Session not found" in str(send_err):
                    # Session expired or SDK restarted — create fresh and retry
                    logger.warning("Session not found for %s, creating new session", session_id)
                    unsubscribe()
                    session = await self._retry_with_new_session(session_id, working_directory)
                    unsubscribe = session.on(on_event)
                    await session.send({"prompt": message})
                else:
                    raise

            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=300)
                except asyncio.TimeoutError:
                    yield {"type": "error", "content": "Response timeout"}
                    break
                if event is None:
                    break
                yield event
        finally:
            unsubscribe()

    async def chat_simple(
        self, message: str, session_id: str = "default", working_directory: str | None = None
    ) -> str:
        """Send a message and return the final response text."""
        session = await self.get_or_create_session(session_id, working_directory)
        try:
            response = await session.send_and_wait({"prompt": message}, timeout=300)
        except Exception as e:
            if "Session not found" in str(e):
                logger.warning("Session not found for %s, creating new session", session_id)
                session = await self._retry_with_new_session(session_id, working_directory)
                response = await session.send_and_wait({"prompt": message}, timeout=300)
            else:
                raise
        if response:
            return getattr(response.data, "content", "")
        return ""

    async def destroy_session(self, session_id: str):
        """Destroy a specific Copilot SDK session."""
        session = self._sessions.pop(session_id, None)
        if session:
            try:
                await session.destroy()
            except Exception:
                pass

    @staticmethod
    async def _auto_approve(request, context):
        """Auto-approve tool permission requests."""
        return {"kind": "approved"}


# Global instance
copilot_engine = CopilotAIEngine()
