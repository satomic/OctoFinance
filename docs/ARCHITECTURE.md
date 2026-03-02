# OctoFinance — Architecture

## System Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         React Frontend (Vite + TypeScript)               │
│  ┌──────────────┐  ┌───────────────────┐  ┌──────────────────────────┐  │
│  │  AI Chat      │  │  Analytics        │  │  Action Panel            │  │
│  │  Interface    │  │  Dashboard        │  │  (Human-in-the-Loop)     │  │
│  │  (SSE Stream) │  │  (9 Sections)     │  │  Approve / Reject        │  │
│  └──────┬───────┘  └────────┬──────────┘  └────────────┬─────────────┘  │
│         │                   │                           │                │
│  ┌──────┴───────────────────┴───────────────────────────┴─────────────┐  │
│  │  Auth Gate · Session Manager · UI State Persistence · i18n (EN/ZH) │  │
│  └────────────────────────────────┬──────────────────────────────────┘  │
└───────────────────────────────────┼──────────────────────────────────────┘
                    SSE / REST API  │
┌───────────────────────────────────┼──────────────────────────────────────┐
│                    FastAPI Backend │(Python 3.13+)                        │
│  ┌────────────────────────────────┴──────────────────────────────────┐  │
│  │                        API Layer (FastAPI)                         │  │
│  │  POST /api/chat (SSE)     GET /api/data/*     POST /api/sync      │  │
│  │  GET /api/health          POST /api/actions/*  GET /api/pats       │  │
│  └────────────────────────────────┬──────────────────────────────────┘  │
│                                   │                                      │
│  ┌──────────────────┐   ┌────────┴─────────────────────────────────┐   │
│  │  Auth Middleware  │   │        Copilot SDK AI Engine              │   │
│  │  Cookie Sessions  │   │  ┌─────────────────────────────────────┐ │   │
│  │  PBKDF2 Hashing   │   │  │  CopilotClient → CopilotSession    │ │   │
│  └──────────────────┘   │  │  System Prompt: FinOps Assistant     │ │   │
│                          │  │  Session Persistence (.copilot_sid)  │ │   │
│  ┌──────────────────┐   │  └───────────────┬─────────────────────┘ │   │
│  │  Sync Manager    │   │                  │ 17 Custom Tools        │   │
│  │  Cron Scheduler  │   │  ┌───────────────┴─────────────────────┐ │   │
│  │  SSE Broadcast   │   │  │ Seat Tools    │ Usage Tools          │ │   │
│  └──────────────────┘   │  │ get_all_seats │ get_usage_report     │ │   │
│                          │  │ find_inactive │ get_users_usage      │ │   │
│  ┌──────────────────┐   │  │ remove_seat   │ get_metrics_detail   │ │   │
│  │  PAT Manager     │   │  │ add_team_mbr  │ get_premium_requests │ │   │
│  │  Multi-PAT       │   │  │               │ get_user_premium     │ │   │
│  │  Auto-Discovery  │   │  │ Billing Tools │ fetch_org_usage*     │ │   │
│  └──────────────────┘   │  │ get_cost_ovw  │ fetch_org_users*     │ │   │
│                          │  │ calculate_roi │ fetch_premium*       │ │   │
│  ┌──────────────────┐   │  │               │                      │ │   │
│  │  MCP Server      │   │  │ Action Tools                         │ │   │
│  │  (stdio)         │   │  │ batch_remove  │ record_recommendation│ │   │
│  │  17 MCP Tools    │   │  │               │ get_recommendations  │ │   │
│  └──────────────────┘   │  └──────────────────────────────────────┘ │   │
│                          └──────────────────────────────────────────┘   │
│                                   │                                      │
│  ┌────────────────────────────────┴──────────────────────────────────┐  │
│  │                    Data Collection Layer                           │  │
│  │  GitHub REST API → JSON Files (data/)                             │  │
│  │  Auto-sync on startup · Cron scheduling · Manual trigger          │  │
│  └───────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────┘
                                   │
                    ┌──────────────┴──────────────┐
                    │      GitHub REST API         │
                    │  /orgs/{org}/copilot/billing  │
                    │  /orgs/{org}/copilot/seats    │
                    │  /orgs/{org}/copilot/metrics  │
                    │  /orgs/{org}/copilot/reports  │
                    │  /organizations/{org}/billing  │
                    │  /enterprises/{ent}/reports    │
                    └──────────────────────────────┘
```

## Data Flow

```
1. PAT Configuration → Auto-discover user → Auto-discover orgs → Detect Copilot plans
2. Data Sync → Fetch seats, billing, usage, metrics, premium requests → Cache as JSON
3. User Message → Copilot SDK Session → LLM selects tools → Tools read cached data or call live API
4. AI Analysis → Generate recommendations → Human approval → Execute via GitHub API
5. Audit Log → Record all operational actions with timestamps
```

## MCP Integration

OctoFinance also runs as a standalone MCP server (`backend/app/mcp_server.py`), exposing the same 17 tools over the Model Context Protocol. This allows external LLM clients (VS Code, etc.) to call OctoFinance tools directly via stdio transport.

```
MCP Client
    ↓ stdio
OctoFinance MCP Server
    ↓ reuses
DataCollector + APIManager → GitHub REST API + JSON cache
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| AI Engine | GitHub Copilot Python SDK (`github-copilot-sdk`) |
| MCP Server | `mcp` Python SDK (FastMCP) |
| Backend | Python 3.13+, FastAPI, Uvicorn, httpx |
| Frontend | React 19, TypeScript 5.9, Vite 7, Recharts |
| Data | JSON files (no database required) |
| Streaming | Server-Sent Events (SSE) via `sse-starlette` |
| Auth | PBKDF2-SHA256, httpOnly cookies |

---

## Project Structure

```
OctoFinance/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app, middleware, lifespan
│   │   ├── mcp_server.py        # MCP server (17 tools via stdio)
│   │   ├── config.py            # Configuration (data paths, pricing)
│   │   ├── routers/
│   │   │   ├── auth.py          # Authentication endpoints
│   │   │   ├── chat.py          # AI chat (SSE streaming)
│   │   │   ├── sessions.py      # Chat session management
│   │   │   ├── sync.py          # Data sync + SSE progress
│   │   │   ├── data.py          # Data query endpoints
│   │   │   ├── actions.py       # Recommendation execution
│   │   │   └── pats.py          # PAT management CRUD
│   │   ├── services/
│   │   │   ├── copilot_engine.py  # Copilot SDK integration
│   │   │   ├── github_api.py     # GitHub REST API client
│   │   │   ├── data_collector.py  # Data collection & caching
│   │   │   ├── api_manager.py     # Multi-PAT API management
│   │   │   ├── session_manager.py # Chat session persistence
│   │   │   ├── sync_manager.py    # Sync state & cron scheduler
│   │   │   ├── pat_manager.py     # PAT CRUD & settings
│   │   │   └── ops_executor.py    # Operation executor
│   │   └── tools/
│   │       ├── seat_tools.py      # 4 seat management tools
│   │       ├── usage_tools.py     # 8 usage analysis tools
│   │       ├── billing_tools.py   # 2 billing/ROI tools
│   │       └── action_tools.py    # 3 action/recommendation tools
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.tsx                # Main app with AuthGate
│   │   ├── components/
│   │   │   ├── ChatInterface.tsx  # AI chat UI
│   │   │   ├── Dashboard.tsx      # 9-section analytics
│   │   │   ├── ActionPanel.tsx    # Recommendation review
│   │   │   ├── LoginPage.tsx      # Auth login/setup
│   │   │   ├── StatusBar.tsx      # Status + sync + logout
│   │   │   ├── ConsolePanel.tsx   # Tool execution console
│   │   │   ├── SessionSelector.tsx # Multi-session selector
│   │   │   ├── OrgSelector.tsx    # Org overview sidebar
│   │   │   ├── OverviewPanel.tsx  # KPI overview
│   │   │   ├── PATSettingsModal.tsx # PAT configuration
│   │   │   └── MessageBubble.tsx  # Chat message renderer
│   │   ├── contexts/
│   │   │   ├── I18nContext.tsx     # EN/ZH translations
│   │   │   ├── ThemeContext.tsx    # Dark/Light theme
│   │   │   └── UIStateContext.tsx  # Persistent UI state
│   │   ├── hooks/
│   │   │   ├── useChat.ts         # Chat + SSE hook
│   │   │   ├── useData.ts         # Dashboard data hook
│   │   │   ├── useSessions.ts     # Session management
│   │   │   ├── useSyncStream.ts   # Sync SSE listener
│   │   │   └── usePATs.ts         # PAT management hook
│   │   └── styles/
│   │       └── index.css          # Complete stylesheet
│   └── package.json
├── docs/
│   ├── USAGE.md                   # Usage guide
│   ├── FEATURES.md                # Detailed features & API reference
│   ├── ARCHITECTURE.md            # This file
│   └── SECURITY.md                # RAI notes & security
├── AGENTS.md                      # Custom instructions
├── mcp.json                       # MCP server configuration
├── README.md                      # Project overview & quick start
└── SECURITY.md                    # Microsoft security policy
```
