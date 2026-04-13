"""
OctoFinance V2 - GitHub Copilot AI FinOps Platform
FastAPI application entry point.
"""

from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .routers import actions, auth, chat, data, pats, sessions, sync
from .routers.auth import AUTH_PUBLIC_PATHS, is_authenticated
from .services.api_manager import api_manager
from .services.copilot_engine import copilot_engine
from .services.data_collector import data_collector
from .services.ops_executor import ops_executor
from .services.pat_manager import pat_manager
from .services.sync_manager import sync_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup/shutdown lifecycle."""
    print("[OctoFinance] Starting up...")

    # Load PATs from file (auto-migrates GITHUB_PAT env var if needed)
    pats_list = pat_manager.load()
    print(f"[OctoFinance] Loaded {len(pats_list)} PAT(s)")

    # Wire up api_manager and data_collector to services that need them
    data_collector.set_api_manager(api_manager)
    copilot_engine.set_api_manager(api_manager)
    ops_executor.set_api_manager(api_manager)
    ops_executor.set_data_collector(data_collector)

    # Read settings
    settings = pat_manager.get_settings()

    # Discover orgs for all PATs
    if pats_list:
        print("[OctoFinance] Auto-discovering GitHub resources...")
        try:
            await api_manager.rebuild()
            all_orgs = api_manager.get_all_orgs()
            org_names = [o["login"] for o in all_orgs]
            print(f"[OctoFinance] Discovered {len(all_orgs)} organizations: {org_names}")

            # Initial data collection (controlled by settings)
            if settings.get("auto_sync_on_startup", True):
                print("[OctoFinance] Starting initial data sync (background)...")
                sync_manager.run_in_background(
                    lambda log_fn: data_collector.sync_all(log_fn=log_fn)
                )
            else:
                print("[OctoFinance] Auto sync on startup is disabled, skipping initial sync.")

            # Start cron scheduler if configured
            cron_expr = settings.get("sync_cron", "").strip()
            if cron_expr:
                sync_manager.start_cron_scheduler(
                    cron_expr,
                    lambda log_fn: data_collector.sync_all(log_fn=log_fn),
                )
        except Exception as e:
            print(f"[OctoFinance] Startup discovery warning: {e}")
    else:
        print("[OctoFinance] No PATs configured. Add a PAT via Settings to get started.")

    # Start Copilot AI engine
    print("[OctoFinance] Starting Copilot AI engine...")
    try:
        await copilot_engine.start()
        print("[OctoFinance] Copilot AI engine ready.")
    except Exception as e:
        print(f"[OctoFinance] Copilot engine startup warning: {e}")

    print("[OctoFinance] Ready!")
    yield

    # Shutdown
    print("[OctoFinance] Shutting down...")
    sync_manager.stop_cron_scheduler()
    await copilot_engine.stop()
    await api_manager.close_all()


app = FastAPI(
    title="OctoFinance V2",
    description="GitHub Copilot AI FinOps Platform",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(sessions.router, prefix="/api")
app.include_router(sync.router, prefix="/api")
app.include_router(data.router, prefix="/api")
app.include_router(actions.router, prefix="/api")
app.include_router(pats.router, prefix="/api")

# Serve frontend static files
_dist = Path(__file__).parent.parent.parent / "frontend" / "dist"
if _dist.exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_frontend(full_path: str):
        return FileResponse(_dist / "index.html")


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Require authentication for all /api/* routes except public auth endpoints."""
    path = request.url.path
    if path.startswith("/api") and path not in AUTH_PUBLIC_PATHS:
        token = request.cookies.get("octofinance_session")
        if not is_authenticated(token):
            return JSONResponse(status_code=401, content={"error": "Authentication required"})
    return await call_next(request)


@app.get("/api/health")
async def health():
    users = api_manager.get_discovered_users()
    user_logins = [u.get("login", "") for u in users.values()]
    all_orgs = api_manager.get_all_orgs()
    pat_count = len(pat_manager.get_all())

    return {
        "status": "ok",
        "users": user_logins,
        "user": user_logins[0] if user_logins else None,
        "orgs": [o["login"] for o in all_orgs],
        "pat_count": pat_count,
        "copilot_engine": copilot_engine.is_ready(),
        "is_syncing": sync_manager.is_syncing,
    }
