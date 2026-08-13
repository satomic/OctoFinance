"""
Release update checker.

Resolves the latest published release by following the redirect that
``/releases/latest`` issues to ``/releases/tag/<version>`` — no GitHub API token
or rate-limited API call involved.

The check is fire-and-forget and never propagates failures: offline or
air-gapped deployments simply keep reporting "unknown" instead of blocking a
sync or failing a request.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone

import httpx

from ..config import APP_VERSION

logger = logging.getLogger(__name__)

RELEASES_LATEST_URL = "https://github.com/satomic/OctoFinance/releases/latest"
RELEASES_PAGE_URL = "https://github.com/satomic/OctoFinance/releases"

# Hard ceiling for the whole check, including connect + redirect handling.
CHECK_TIMEOUT_SECONDS = 30.0

_TAG_RE = re.compile(r"/releases/tag/(?P<tag>[^/?#]+)")


def _normalize(version: str) -> str:
    return version.strip().lstrip("vV")


def _version_tuple(version: str) -> tuple:
    """Best-effort numeric comparison key; non-numeric parts sort as 0."""
    parts = re.split(r"[.\-+]", _normalize(version))
    key: list[int] = []
    for p in parts:
        if p.isdigit():
            key.append(int(p))
        else:
            break
    return tuple(key)


class UpdateChecker:
    """Caches the latest known release and whether it is newer than this build."""

    def __init__(self):
        self._latest_version: str | None = None
        self._release_url: str = RELEASES_PAGE_URL
        self._checked_at: str | None = None
        self._error: str | None = None
        self._task: asyncio.Task | None = None

    @property
    def state(self) -> dict:
        latest = self._latest_version
        update_available = bool(
            latest and _version_tuple(latest) > _version_tuple(APP_VERSION)
        )
        return {
            "current_version": APP_VERSION,
            "latest_version": latest,
            "update_available": update_available,
            "release_url": self._release_url,
            "checked_at": self._checked_at,
            "error": self._error,
        }

    def schedule(self) -> None:
        """Kick off a check in the background. Returns immediately.

        A check already in flight is left alone rather than stacking up.
        """
        if self._task and not self._task.done():
            return
        try:
            self._task = asyncio.create_task(self._run())
        except RuntimeError:
            # No running loop (e.g. called from sync code at import time).
            logger.debug("No event loop available for the update check")

    async def _run(self) -> None:
        try:
            await asyncio.wait_for(self._check(), timeout=CHECK_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            self._error = f"Timed out after {CHECK_TIMEOUT_SECONDS:.0f}s"
            self._checked_at = datetime.now(timezone.utc).isoformat()
            logger.info("Update check timed out; assuming no network access")
        except Exception as e:
            self._error = str(e)
            self._checked_at = datetime.now(timezone.utc).isoformat()
            logger.info("Update check failed: %s", e)

    async def _check(self) -> None:
        async with httpx.AsyncClient(
            timeout=CHECK_TIMEOUT_SECONDS,
            follow_redirects=True,
            headers={"User-Agent": f"OctoFinance/{APP_VERSION}"},
        ) as client:
            resp = await client.get(RELEASES_LATEST_URL)

        # The tag lands in the final URL; on a non-redirecting response the
        # history still carries the Location we care about.
        candidates = [str(resp.url)] + [str(r.headers.get("location", "")) for r in resp.history]
        tag = next(
            (m.group("tag") for c in candidates if (m := _TAG_RE.search(c))),
            None,
        )
        if not tag:
            raise ValueError("Could not resolve a release tag from the redirect")

        self._latest_version = tag
        self._release_url = f"https://github.com/satomic/OctoFinance/releases/tag/{tag}"
        self._checked_at = datetime.now(timezone.utc).isoformat()
        self._error = None
        logger.info("Latest release: %s (current %s)", tag, APP_VERSION)


update_checker = UpdateChecker()
