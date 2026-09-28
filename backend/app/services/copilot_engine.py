"""
Copilot SDK AI Engine - Core AI-powered FinOps analysis engine.
Uses the Copilot Python SDK to create sessions with custom FinOps tools.
Supports resuming persisted sessions across backend restarts.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import AsyncIterator, TYPE_CHECKING

import httpx
from copilot import CopilotClient, CopilotSession, PermissionHandler
from copilot.generated.session_events import SessionEvent, SessionEventType

from .data_collector import create_session_collector
from ..tools.action_tools import create_action_tools
from ..tools.billing_tools import create_billing_tools
from ..tools.budget_tools import create_budget_tools
from ..tools.cost_center_tools import create_cost_center_tools
from ..tools.enterprise_team_tools import create_enterprise_team_tools
from ..tools.seat_tools import create_seat_tools
from ..tools.sync_tools import create_sync_tools
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
- Cached tools read the data from the last Sync Data. When cached data is missing or stale, or right after a
  live write (e.g. create_cost_center) that a cache-based tool depends on, call sync_data with the narrowest
  dataset (e.g. 'cost_centers') and then retry, instead of asking the admin to click Sync Data

Available data dimensions:
- Seats: who has Copilot, when they last used it, which team they belong to
- Usage Reports: org-level and user-level usage metrics (28-day or specific day), feature adoption, engagement data
- Billing: plan type, cost per seat, total cost, waste
- Metrics: detailed IDE completions, chat usage, PR summaries (legacy API)
- AI Credits: per-model breakdown of AI credit consumption, pricing, and costs (UBB)
- Budgets: UBB (Usage-Based Billing) AI credits budgets - Universal user-level budgets (default for all users), Individual user-level budgets (user-specific overrides), Enterprise/Cost center budgets (overage controls)
- Enterprise Teams: enterprise-level groups of users, independent of organizations, that can hold Copilot Business licenses directly

Enterprise Teams:
None of the Copilot datasets (seats, usage reports, metrics, AI credit CSVs) carry an enterprise-team field.
To analyze anything per enterprise team, first call list_enterprise_teams / get_enterprise_team to get the member
roster, then join it against the other datasets on the user login. get_enterprise_team_copilot_usage does this join
for you. Note that enterprise teams can include unaffiliated users who belong to no organization — those users never
appear in org seat data, so a team's member count can legitimately exceed the number of seats you can match.

Copilot AI credits (UBB - Usage-Based Billing, effective June 1, 2026):
Each Copilot plan includes a monthly allowance of AI credits per user; Copilot Enterprise includes
a larger allowance than Copilot Business. AI credit usage beyond the included monthly allowance is
billed per the model's price per credit (e.g. ~$0.01/credit). Use this information when analyzing
AI credit usage and cost optimization.
Note: The Copilot AI credit API only returns org-level totals by model. The per-user breakdown comes from the
detailed billing report CSV, which the admin can now pull automatically through the billing reports API
("Fetch CSV" in the UI) or still upload by hand from the GitHub UI export.

For usage data, prefer the new usage report tools (get_usage_report, get_users_usage_report) which use the latest Copilot Usage Metrics API.
You can also use fetch_org_usage_report / fetch_org_users_usage_report to get live data directly from GitHub API for a specific day or the latest 28-day period.

Budget Management (UBB Era - June 2026):
Starting June 1, 2026, GitHub Copilot billing switched from Premium Requests to AI Credits (UBB - Usage-Based Billing).
- Universal user-level budget: Default personal limit for ALL Copilot users (each enterprise/org can have only one)
- Individual user-level budget: User-specific limits that override Universal budget (for high-frequency users, core engineers, or restricted users)
- Enterprise/Cost center budgets: Control overage spending after the shared pool of included credits is exhausted
User-level budgets are hard limits by default (prevent_further_usage=true). When a user hits their budget limit, they are blocked from consuming more AI credits.
Use batch_create_user_budgets for bulk operations (onboarding teams, applying uniform limits to user groups).
"""


def _clean_error(exc: BaseException | str) -> str:
    """Drop the JSON-RPC wrapper around CLI errors, keeping GitHub's own reason."""
    import re
    text = str(exc)
    text = re.sub(r"^JSON-RPC Error -?\d+:\s*", "", text)
    text = re.sub(r"^Request [\w.]+ failed with message:\s*", "", text)
    text = re.sub(r"(\\n|\s)+", " ", text)  # literal "\n" escapes and real newlines
    return re.sub(r'\s+"$', '"', text).strip()


def _bare_host(value: str | None) -> str:
    """``https://acme.ghe.com/`` -> ``acme.ghe.com``."""
    if not value:
        return ""
    from urllib.parse import urlparse
    return (urlparse(value if "://" in value else f"https://{value}").hostname or "").lower()


async def _lookup_login(token: str, host: str) -> str:
    """Login of the token's owner on ``host`` (the host the CLI already sends it to)."""
    from .github_host import api_base_url, host_from_api_base
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{api_base_url(host_from_api_base(host))}/user",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
            )
        if resp.status_code == 200:
            return resp.json().get("login", "")
    except Exception:
        logger.debug("Could not look up the Copilot token owner on %s", host, exc_info=True)
    return ""


class CopilotAIEngine:
    """Manages Copilot SDK client and sessions for AI-powered FinOps."""

    def __init__(self):
        self._client: CopilotClient | None = None
        self._client_started: bool = False
        self._sessions: dict[str, CopilotSession] = {}
        self._session_models: dict[str, str] = {}
        self._api_manager: APIManager | None = None
        # GHE.com host the Copilot CLI was pointed at (None = its default, github.com)
        self._cli_host: str | None = None
        # What the last client start resolved to and how authentication went,
        # shown in Settings -> AI Chat so a 401/403 is diagnosable from the UI.
        self._auth_status: dict = {}

    def set_api_manager(self, api_manager: APIManager):
        """Set the API manager for tool creation."""
        self._api_manager = api_manager

    async def start(self):
        """Start the Copilot SDK client."""
        self._client = await self._start_client()
        self._client_started = True

    async def _start_client(self) -> CopilotClient:
        """Start a client, falling back to the CLI's own login if the token is rejected.

        A stale COPILOT_GITHUB_TOKEN/GH_TOKEN would otherwise leave every request
        failing with "Not authenticated" even when `copilot` itself is logged in.
        The fallback is recorded in the auth status so it is visible in Settings.
        """
        options, source = self._resolve_credentials()
        host = await self._resolve_cli_host(options, source)
        if host:
            options["env"] = {**os.environ, "COPILOT_GH_HOST": host}
        self._cli_host = host
        status: dict = {
            "source": source,
            "requested_host": host or os.environ.get("COPILOT_GH_HOST") or os.environ.get("GH_HOST") or "",
            "fallback_used": False,
            "error": "",
        }
        client = CopilotClient(**options)
        try:
            await client.start()
        except BaseException as exc:
            self._client_started = False
            self._auth_status = {**status, "authenticated": False, "error": _clean_error(exc)}
            raise

        if not options.get("github_token"):
            self._auth_status = await self._probe_status(client, status)
            return client
        status["_token"] = options["github_token"]

        rejection = ""
        try:
            auth = await client.get_auth_status()
            if auth.isAuthenticated:
                self._auth_status = await self._probe_status(client, status)
                return client
            rejection = auth.statusMessage or "Not authenticated"
        except Exception as exc:
            logger.exception("Failed to read Copilot auth status")
            rejection = _clean_error(exc)

        logger.warning(
            "Configured Copilot token was rejected; falling back to the Copilot CLI's logged-in user"
        )
        try:
            await client.stop()
        except Exception:
            pass
        fallback = CopilotClient(use_logged_in_user=True)
        await fallback.start()
        status.pop("_token", None)
        status.update(fallback_used=True, error=f"Token rejected: {rejection}")
        self._auth_status = await self._probe_status(fallback, status)
        return fallback

    @staticmethod
    async def _probe_status(client: CopilotClient, base: dict) -> dict:
        """Who the CLI is signed in as, and whether Copilot actually serves models.

        auth.getStatus only covers authentication; a seat or policy problem
        (e.g. HTTP 403 "requires an enterprise or organization policy") only
        shows up when models are listed.
        """
        base = dict(base)
        token = base.pop("_token", None)
        status = {**base, "authenticated": False, "login": "", "host": "", "models_available": None}
        try:
            auth = await client.get_auth_status()
            status.update(
                authenticated=bool(auth.isAuthenticated),
                login=auth.login or "",
                host=_bare_host(auth.host) or base.get("requested_host") or "github.com",
            )
            if status["authenticated"] and not status["login"] and token:
                # The CLI omits the login for token auth; ask the host it already uses.
                status["login"] = await _lookup_login(token, status["host"])
            if not auth.isAuthenticated and not status["error"]:
                status["error"] = auth.statusMessage or "Not authenticated"
        except Exception as exc:
            status["error"] = status["error"] or _clean_error(exc)
            return status
        if status["authenticated"]:
            try:
                models = await client.list_models()
                status["models_available"] = len(models)
            except Exception as exc:
                status["models_available"] = 0
                status["models_error"] = _clean_error(exc)
        return status

    async def get_auth_status(self, refresh: bool = False) -> dict:
        """Current chat authentication status; ``refresh`` re-checks with the CLI."""
        if not self.is_ready():
            try:
                await self._restart_client()
            except Exception as exc:
                return {**self._auth_status, "authenticated": False, "error": _clean_error(exc)}
        elif refresh and self._client:
            base = {k: self._auth_status.get(k, d) for k, d in
                    (("source", ""), ("requested_host", ""), ("fallback_used", False), ("error", ""))}
            if not base["fallback_used"]:
                base["_token"] = self._resolve_credentials()[0].get("github_token")
            self._auth_status = await self._probe_status(self._client, base)
        return dict(self._auth_status)

    async def apply_auth_settings(self) -> dict:
        """Reconnect with the credentials from Settings and return the new status."""
        try:
            await self._restart_client()
        except Exception as exc:
            logger.exception("Failed to restart the Copilot client with new chat settings")
            return {**self._auth_status, "authenticated": False, "error": _clean_error(exc)}
        return dict(self._auth_status)

    async def stop(self):
        """Stop all sessions and the client."""
        for session in self._sessions.values():
            try:
                await session.disconnect()
            except Exception:
                pass
        self._sessions.clear()
        self._session_models.clear()
        if self._client:
            await self._client.stop()
            self._client = None
        self._client_started = False

    async def refresh_cli_host(self) -> None:
        """Restart the client when the Copilot token now resolves to a different host.

        Called after PATs or the SSO host change: a GHE.com host added later can
        be the one the env token belongs to, so chat starts working without a
        container restart.
        """
        options, source = self._resolve_credentials()
        if not options.get("github_token"):
            return
        host = await self._resolve_cli_host(options, source)
        if host != self._cli_host:
            logger.info("Copilot CLI host changed (%s -> %s); restarting the client", self._cli_host, host)
            await self._restart_client()

    def schedule_cli_host_refresh(self) -> None:
        """Fire-and-forget refresh_cli_host() so config endpoints stay fast."""
        if not self.is_ready():
            return  # the next chat request starts the client with fresh settings

        async def _run():
            try:
                await self.refresh_cli_host()
            except Exception:
                logger.exception("Failed to refresh the Copilot CLI host")

        asyncio.create_task(_run())

    async def _resolve_cli_host(self, options: dict, source: dict) -> str | None:
        """Host to pass to the CLI as COPILOT_GH_HOST, or None to leave its default.

        1. Host set in Settings -> AI Chat (github.com or <sub>.ghe.com)
        2. COPILOT_GH_HOST / GH_HOST in the environment: the CLI reads them itself
        3. The GHE.com host of the fallback data-sync PAT
        4. The configured GHE.com host that accepts the token (see _detect_token_host)
        """
        from .chat_auth_store import chat_auth_store
        from .github_host import is_ghe_host

        pinned = chat_auth_store.get()["host"]
        if pinned:
            return pinned
        if os.environ.get("COPILOT_GH_HOST") or os.environ.get("GH_HOST"):
            return None
        if is_ghe_host(source.get("pat_host")):
            return source["pat_host"]
        token = options.get("github_token")
        if token:
            host = await self._detect_token_host(token)
            if host:
                logger.info("Copilot token belongs to %s; pointing the Copilot CLI at it", host)
            return host
        return None

    @staticmethod
    async def _detect_token_host(token: str) -> str | None:
        """Return the GHE.com host a token belongs to, or None for github.com.

        The Copilot CLI authenticates against github.com unless told otherwise,
        so a GHE.com token would fail with 401. The token is only ever sent to
        hosts already configured in OctoFinance (PAT hosts and the SSO host),
        never probed against github.com.
        """
        from .auth_store import auth_store
        from .github_host import api_base_url, is_ghe_host, normalize_host
        from .pat_manager import pat_manager

        candidates: list[str] = []
        for pat in pat_manager.get_all() or pat_manager.load():
            host = pat.get("host") or ""
            if is_ghe_host(host) and host not in candidates:
                candidates.append(host)
        try:
            sso_host = normalize_host(auth_store.get_oauth_config().get("host", ""))
            if is_ghe_host(sso_host) and sso_host not in candidates:
                candidates.append(sso_host)
        except ValueError:
            pass

        async with httpx.AsyncClient(timeout=10.0) as client:
            for host in candidates:
                try:
                    resp = await client.get(
                        f"{api_base_url(host)}/user",
                        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                    )
                except httpx.HTTPError as exc:
                    logger.warning("Could not check the Copilot token against %s: %s", host, exc)
                    continue
                if resp.status_code == 200:
                    return host
        return None

    def is_ready(self) -> bool:
        return self._client is not None and self._client_started

    @staticmethod
    def _resolve_credentials() -> tuple[dict, dict]:
        """Pick the token for the Copilot CLI. Returns (client options, source info).

        Resolution order:
        1. Token saved in Settings -> AI Chat
        2. COPILOT_GITHUB_TOKEN / GH_TOKEN / GITHUB_TOKEN env vars (see
           https://docs.github.com/en/copilot/how-tos/copilot-cli/set-up-copilot-cli/authenticate-copilot-cli#authenticating-with-environment-variables)
        3. Fallback: the first non-classic data-sync PAT configured in Settings.
           The CLI rejects classic PATs (``ghp_``) outright, so they are skipped.
        4. Fallback: the CLI's own logged-in user (interactive `copilot` login)
        """
        from .chat_auth_store import chat_auth_store, mask_token

        token = chat_auth_store.get()["token"]
        if token:
            logger.info("Using the token from Settings -> AI Chat for Copilot CLI authentication")
            return (
                {"github_token": token, "use_logged_in_user": False},
                {"kind": "settings", "detail": "", "token_masked": mask_token(token)},
            )

        for env_var in ("COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"):
            token = os.environ.get(env_var, "").strip()
            if token:
                logger.info("Using %s environment variable for Copilot CLI authentication", env_var)
                return (
                    {"github_token": token, "use_logged_in_user": False},
                    {"kind": "env", "detail": env_var, "token_masked": mask_token(token)},
                )

        try:
            from .pat_manager import pat_manager

            for pat in pat_manager.get_all() or pat_manager.load():
                token = pat.get("token")
                if not token or token.startswith("ghp_"):
                    continue
                logger.info("Using configured PAT '%s' for Copilot CLI", pat.get("label"))
                return (
                    {"github_token": token, "use_logged_in_user": False},
                    {"kind": "pat", "detail": pat.get("label", ""), "token_masked": mask_token(token),
                     "pat_host": pat.get("host", "")},
                )
        except Exception:
            logger.exception("Failed to load configured PAT for Copilot SDK client")
        return {}, {"kind": "cli_login", "detail": "", "token_masked": ""}

    @classmethod
    def _client_options(cls) -> dict:
        """Client options for the resolved credentials (host is resolved separately)."""
        return cls._resolve_credentials()[0]

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
            + create_cost_center_tools(api_manager=self._api_manager, collector=collector)
            + create_budget_tools(api_manager=self._api_manager, collector=collector)
            + create_enterprise_team_tools(api_manager=self._api_manager, collector=collector)
            + create_sync_tools()
        )
        return tools

    # ------------------------------------------------------------------
    # Session lifecycle: get / resume / create
    # ------------------------------------------------------------------

    async def get_or_create_session(
        self, session_id: str = "default", working_directory: str | None = None
    ) -> CopilotSession:
        """Return an in-memory session, try to resume a persisted one, or create new."""
        if not self.is_ready():
            logger.warning("Copilot client is not ready; starting SDK client before creating session %s", session_id)
            await self._restart_client()

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
                self._delete_sdk_session_id(working_directory)

        # 3. Create brand-new session
        try:
            return await self._create_session(session_id, working_directory)
        except Exception:
            logger.exception("Failed to create Copilot session %s; restarting SDK client and retrying once", session_id)
            await self._restart_client()
            self._delete_sdk_session_id(working_directory)
            return await self._create_session(session_id, working_directory)

    async def _restart_client(self):
        """Restart the Copilot SDK client after a transport/session failure."""
        self._sessions.clear()
        self._session_models.clear()
        self._client_started = False
        if self._client:
            try:
                await self._client.stop()
            except Exception:
                logger.exception("Failed to stop Copilot SDK client during restart")
        try:
            self._client = await self._start_client()
            self._client_started = True
        except BaseException:
            self._client = None
            raise

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

        resume_kwargs: dict = {
            "tools": session_tools,
            "system_message": {
                "mode": "append",
                "content": FINOPS_SYSTEM_PROMPT,
            },
            "on_permission_request": PermissionHandler.approve_all,
        }
        if working_directory:
            resume_kwargs["working_directory"] = working_directory

        session = await self._client.resume_session(sdk_session_id, **resume_kwargs)
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

        session_kwargs: dict = {
            "tools": session_tools,
            "system_message": {
                "mode": "append",
                "content": FINOPS_SYSTEM_PROMPT,
            },
            "on_permission_request": PermissionHandler.approve_all,
        }
        if working_directory:
            session_kwargs["working_directory"] = working_directory

        session = await self._client.create_session(**session_kwargs)
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
        self._session_models.pop(session_id, None)
        if old:
            try:
                await old.disconnect()
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

    @staticmethod
    def _delete_sdk_session_id(working_directory: str | None):
        if not working_directory:
            return
        path = Path(working_directory) / _SDK_SESSION_ID_FILE
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.exception("Failed to delete stale SDK session id file: %s", path)

    # ------------------------------------------------------------------
    # Model selection
    # ------------------------------------------------------------------

    async def list_models(self) -> list[dict]:
        """List the models available to the authenticated Copilot account."""
        if not self.is_ready():
            await self._restart_client()
        if not self._client:
            return []
        models = await self._client.list_models()
        result = []
        for m in models:
            billing = getattr(m, "billing", None)
            result.append({
                "id": m.id,
                "name": m.name,
                "multiplier": getattr(billing, "multiplier", None) if billing else None,
                "is_premium": getattr(billing, "is_premium", None) if billing else None,
                "supported_reasoning_efforts": m.supported_reasoning_efforts,
                "default_reasoning_effort": m.default_reasoning_effort,
            })
        return result

    async def _apply_model(self, session: CopilotSession, session_id: str, model: str | None):
        """Switch the session's model. An empty selection maps to Copilot's own `auto`."""
        target = model or "auto"
        if self._session_models.get(session_id) == target:
            return
        try:
            await session.set_model(target)
            self._session_models[session_id] = target
        except Exception:
            logger.exception("Failed to switch session %s to model %s", session_id, target)

    async def chat(
        self,
        message: str,
        session_id: str = "default",
        working_directory: str | None = None,
        model: str | None = None,
    ) -> AsyncIterator[dict]:
        """
        Send a message and yield response events as they arrive.
        Yields dicts with: {"type": "delta"|"message"|"tool"|"idle", "content": ...}
        """
        session = await self.get_or_create_session(session_id, working_directory)
        await self._apply_model(session, session_id, model)

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
                text = getattr(event.data, "delta_content", None) or getattr(event.data, "reasoning_text", None)
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
                tool_name = getattr(event.data, "tool_name", None) or getattr(
                    getattr(event.data, "tool_description", None), "name", None
                )
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
                await session.send(message)
            except Exception as send_err:
                if "Session not found" in str(send_err):
                    # Session expired or SDK restarted — create fresh and retry
                    logger.warning("Session not found for %s, creating new session", session_id)
                    unsubscribe()
                    session = await self._retry_with_new_session(session_id, working_directory)
                    unsubscribe = session.on(on_event)
                    await session.send(message)
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
        self,
        message: str,
        session_id: str = "default",
        working_directory: str | None = None,
        model: str | None = None,
    ) -> str:
        """Send a message and return the final response text."""
        session = await self.get_or_create_session(session_id, working_directory)
        await self._apply_model(session, session_id, model)
        try:
            response = await session.send_and_wait(message, timeout=300)
        except Exception as e:
            if "Session not found" in str(e):
                logger.warning("Session not found for %s, creating new session", session_id)
                session = await self._retry_with_new_session(session_id, working_directory)
                response = await session.send_and_wait(message, timeout=300)
            else:
                raise
        if response:
            return getattr(response.data, "content", "")
        return ""

    async def destroy_session(self, session_id: str):
        """Destroy a specific Copilot SDK session (disconnect + delete server-side state)."""
        session = self._sessions.pop(session_id, None)
        if session:
            sdk_session_id = session.session_id
            try:
                await session.disconnect()
            except Exception:
                pass
            if self._client:
                try:
                    await self._client.delete_session(sdk_session_id)
                except Exception:
                    pass


# Global instance
copilot_engine = CopilotAIEngine()
