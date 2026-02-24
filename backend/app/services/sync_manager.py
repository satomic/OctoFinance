"""
Sync manager - tracks global sync state and broadcasts log events via async queues.
Enables real-time sync progress streaming to frontend via SSE.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine


class SyncManager:
    """Manages global sync state and broadcasts real-time log events to SSE subscribers."""

    def __init__(self):
        self._syncing = False
        self._listeners: list[asyncio.Queue] = []
        self._current_task: asyncio.Task | None = None

    @property
    def is_syncing(self) -> bool:
        return self._syncing

    def subscribe(self) -> asyncio.Queue:
        """Subscribe to sync events. Returns an asyncio.Queue that receives events."""
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._listeners.append(q)
        # Send initial state so the client knows whether a sync is in progress
        q.put_nowait({
            "type": "sync_status",
            "syncing": self._syncing,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        return q

    def unsubscribe(self, q: asyncio.Queue):
        """Remove a subscriber."""
        if q in self._listeners:
            self._listeners.remove(q)

    def _emit(self, event: dict):
        """Send event to all subscribers (non-blocking)."""
        dead: list[asyncio.Queue] = []
        for q in self._listeners:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._listeners.remove(q)

    def log(self, level: str, message: str):
        """Emit a log event to all subscribers."""
        self._emit({
            "type": "sync_log",
            "level": level,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def _start(self):
        self._syncing = True
        self._emit({
            "type": "sync_start",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def _end(self, success: bool = True, error: str | None = None):
        self._syncing = False
        self._current_task = None
        self._emit({
            "type": "sync_complete",
            "success": success,
            "error": error,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def run_in_background(
        self,
        coro_fn: Callable[[Callable[[str, str], None]], Coroutine[Any, Any, Any]],
    ) -> bool:
        """Run a sync coroutine in the background. Returns immediately.

        Args:
            coro_fn: An async callable that takes a log function (level, message) -> None.
                     e.g., lambda log_fn: data_collector.sync_all(log_fn=log_fn)

        Returns:
            True if sync was started, False if already syncing.
        """
        if self._syncing:
            self.log("warn", "Sync already in progress, skipping")
            return False

        async def _run():
            self._start()
            try:
                await coro_fn(self.log)
                self._end(success=True)
            except Exception as e:
                self.log("error", f"Sync failed: {e}")
                self._end(success=False, error=str(e))

        self._current_task = asyncio.create_task(_run())
        return True


sync_manager = SyncManager()
