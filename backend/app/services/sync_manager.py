"""
Sync manager - tracks global sync state and broadcasts log events via async queues.
Enables real-time sync progress streaming to frontend via SSE.
Supports scheduled (cron-based) periodic sync.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Coroutine

from ..config import DATA_DIR

STATUS_FILE = DATA_DIR / "sync_status.json"

# Error lines kept from a run, for the UI notice
MAX_RECORDED_ERRORS = 20


def _parse_cron_interval(cron_expr: str) -> int | None:
    """Parse a simple cron expression into an interval in seconds.

    Supports common patterns:
        ``*/N * * * *``   → every N minutes
        ``0 */N * * *``   → every N hours
        ``0 0 * * *``     → every 24 hours (daily)
        ``0 0 */N * *``   → every N days

    Returns None if the expression cannot be parsed.
    """
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        return None

    minute, hour, dom, month, dow = parts

    # Every N minutes: */N * * * *
    m = re.fullmatch(r"\*/(\d+)", minute)
    if m and hour == "*" and dom == "*" and month == "*" and dow == "*":
        return int(m.group(1)) * 60

    # Every N hours: 0 */N * * *
    m = re.fullmatch(r"\*/(\d+)", hour)
    if minute == "0" and m and dom == "*" and month == "*" and dow == "*":
        return int(m.group(1)) * 3600

    # Daily: 0 0 * * *
    if minute == "0" and hour == "0" and dom == "*" and month == "*" and dow == "*":
        return 86400

    # Every N days: 0 0 */N * *
    m = re.fullmatch(r"\*/(\d+)", dom)
    if minute == "0" and hour == "0" and m and month == "*" and dow == "*":
        return int(m.group(1)) * 86400

    return None


def describe_cron(cron_expr: str) -> str:
    """Return a human-readable description of a cron expression, or empty string."""
    interval = _parse_cron_interval(cron_expr)
    if interval is None:
        return ""
    if interval < 3600:
        mins = interval // 60
        return f"Every {mins} minute{'s' if mins != 1 else ''}"
    if interval < 86400:
        hrs = interval // 3600
        return f"Every {hrs} hour{'s' if hrs != 1 else ''}"
    days = interval // 86400
    if days == 1:
        return "Daily"
    return f"Every {days} days"


class SyncManager:
    """Manages global sync state, cron scheduling, and broadcasts real-time log events."""

    def __init__(self, status_file: Path = STATUS_FILE):
        self._syncing = False
        self._listeners: list[asyncio.Queue] = []
        self._current_task: asyncio.Task | None = None
        self._cron_task: asyncio.Task | None = None
        self._cron_expr: str = ""
        self._preflight: Callable[[Callable[[str, str], None]], Awaitable[None]] | None = None
        # Outcome of the run in progress, then of the last finished run
        self._run: dict | None = None
        self._status_file = status_file
        self._status = self._load_status()

    # ------------------------------------------------------------------
    # Run outcome (persisted, so a failed overnight sync is still reported
    # after a restart or to an admin who was not watching the Console)
    # ------------------------------------------------------------------

    def _load_status(self) -> dict:
        try:
            return json.loads(self._status_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_status(self) -> None:
        try:
            self._status_file.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self._status_file.parent, delete=False
            ) as stream:
                temporary_path = stream.name
                json.dump(self._status, stream, indent=2)
            os.replace(temporary_path, self._status_file)
        except OSError as e:
            print(f"[SyncManager] Could not save sync status: {e}")

    @property
    def status(self) -> dict:
        """Last finished run, last success time and cron state, for /api/health."""
        return {
            "last_run": self._status.get("last_run"),
            "last_success_at": self._status.get("last_success_at"),
            "cron": self._cron_expr,
            "cron_description": describe_cron(self._cron_expr) if self._cron_expr else "",
        }

    def set_preflight(self, fn: Callable[[Callable[[str, str], None]], Awaitable[None]] | None) -> None:
        """Register a check that runs at the start of every sync (credentials)."""
        self._preflight = fn

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
        run = self._run
        if run is not None and level in ("error", "warn", "warning"):
            if level == "error":
                run["error_count"] += 1
                if len(run["errors"]) < MAX_RECORDED_ERRORS:
                    run["errors"].append(message.strip())
            else:
                run["warning_count"] += 1
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
        finished_at = datetime.now(timezone.utc).isoformat()
        run, self._run = self._run, None
        if run is not None:
            run["finished_at"] = finished_at
            if error:
                run["errors"].insert(0, error)
            # A run that logged errors kept some data stale: report it as failed
            # even though the sync itself completed.
            if not success or run["error_count"]:
                run["status"] = "failed"
            else:
                run["status"] = "success"
                self._status["last_success_at"] = finished_at
            self._status["last_run"] = run
            self._save_status()
        self._syncing = False
        self._current_task = None
        self._emit({
            "type": "sync_complete",
            "success": success and not (run and run["error_count"]),
            "error": error or (run["errors"][0] if run and run["errors"] else None),
            "error_count": run["error_count"] if run else 0,
            "trigger": run["trigger"] if run else None,
            "timestamp": finished_at,
        })

    def run_in_background(
        self,
        coro_fn: Callable[[Callable[[str, str], None]], Coroutine[Any, Any, Any]],
        trigger: str = "manual",
    ) -> bool:
        """Run a sync coroutine in the background. Returns immediately.

        Args:
            coro_fn: An async callable that takes a log function (level, message) -> None.
                     e.g., lambda log_fn: data_collector.sync_all(log_fn=log_fn)
            trigger: What started the sync (manual, scheduled, startup, chat, pat_change),
                     reported with the run's outcome.

        Returns:
            True if sync was started, False if already syncing.
        """
        if self._syncing:
            self.log("warn", "Sync already in progress, skipping")
            return False

        # Fire-and-forget: an offline deployment must not delay or fail the sync.
        from .update_checker import update_checker
        update_checker.schedule()

        async def _run():
            self._run = {
                "trigger": trigger,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "error_count": 0,
                "warning_count": 0,
                "errors": [],
            }
            self._start()
            try:
                if self._preflight:
                    try:
                        await self._preflight(self.log)
                    except Exception as e:
                        self.log("warn", f"Credential check failed: {e}")
                await coro_fn(self.log)
                self._end(success=True)
            except Exception as e:
                self.log("error", f"Sync failed: {e}")
                self._end(success=False, error=str(e))

        # Mark busy now, not when the task first runs, so a second caller in the
        # same event-loop tick sees the sync and cannot start another one.
        self._syncing = True
        self._current_task = asyncio.create_task(_run())
        return True

    async def wait_until_idle(self, timeout: float) -> bool:
        """Wait for the running sync (if any) to finish. Returns False on timeout.

        The sync keeps running after a timeout; only the wait is abandoned.
        """
        task = self._current_task
        if task is None or task.done():
            return not self._syncing
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
        except asyncio.TimeoutError:
            return False
        return True

    # ------------------------------------------------------------------
    # Cron-based periodic sync
    # ------------------------------------------------------------------

    def start_cron_scheduler(
        self,
        cron_expr: str,
        sync_fn: Callable[[Callable[[str, str], None]], Coroutine[Any, Any, Any]],
    ) -> bool:
        """Start a periodic sync based on a cron expression.

        Returns True if the scheduler was started, False if the cron expression
        could not be parsed.
        """
        interval = _parse_cron_interval(cron_expr)
        if interval is None:
            self.log("warn", f"Cannot parse cron expression: {cron_expr}")
            return False

        self.stop_cron_scheduler()
        self._cron_expr = cron_expr

        desc = describe_cron(cron_expr)
        self.log("info", f"Cron scheduler started: {desc} ({cron_expr})")

        async def _cron_loop():
            try:
                while True:
                    await asyncio.sleep(interval)
                    self.log("info", f"Cron triggered sync ({desc})")
                    self.run_in_background(sync_fn, trigger="scheduled")
            except asyncio.CancelledError:
                pass

        self._cron_task = asyncio.create_task(_cron_loop())
        return True

    def stop_cron_scheduler(self):
        """Stop the periodic sync scheduler if running."""
        if self._cron_task and not self._cron_task.done():
            self._cron_task.cancel()
            self.log("info", "Cron scheduler stopped")
        self._cron_task = None
        self._cron_expr = ""

    @property
    def cron_expr(self) -> str:
        """Return the currently active cron expression, or empty string."""
        return self._cron_expr


sync_manager = SyncManager()
