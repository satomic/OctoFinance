# OctoFinance — Architecture

> Applies to **v1.2.0**.

## System Architecture

```
┌───────────────────────────────────────────────────────────────────────────────┐
│                       React Frontend (Vite + TypeScript)                      │
│                                                                               │
│   ADMIN VIEW                                    REGULAR-USER VIEW             │
│  ┌──────────┐ ┌────────────────┐ ┌──────────┐  ┌───────────────────────────┐ │
│  │ AI Chat  │ │  Dashboards    │ │ Action   │  │  UserPortal               │ │
│  │ (SSE)    │ │  7 tabs        │ │ Panel    │  │  My usage · My budget     │ │
│  │          │ │                │ │ HITL     │  │  My cost centers          │ │
│  └────┬─────┘ └───────┬────────┘ └────┬─────┘  │  Budget requests          │ │
│       │               │               │        └─────────────┬─────────────┘ │
│  ┌────┴───────────────┴───────────────┴──────────────────────┴─────────────┐ │
│  │ AuthGate (role routing) · PeriodToggle · LanguageSelector (8 locales)   │ │
│  │ Session Manager · UI State Persistence · Theme                          │ │
│  └────────────────────────────────┬───────────────────────────────────────┘ │
└───────────────────────────────────┼───────────────────────────────────────────┘
                    SSE / REST API  │
┌───────────────────────────────────┼───────────────────────────────────────────┐
│                    FastAPI Backend│(Python 3.13+)                             │
│  ┌────────────────────────────────┴────────────────────────────────────────┐ │
│  │             Auth + Role Middleware  (public / any-user / admin)          │ │
│  │  public: /api/auth/status|setup|login|github/*                          │ │
│  │  any user: /api/me/*  /api/budget-requests      admin: everything else  │ │
│  └────────────────────────────────┬────────────────────────────────────────┘ │
│  ┌────────────────────────────────┴────────────────────────────────────────┐ │
│  │                           API Layer (routers)                            │ │
│  │  auth · me · budget_requests · chat · sessions · sync · data · actions   │ │
│  │  pats · share (public)                                                   │ │
│  └────────────────────────────────┬────────────────────────────────────────┘ │
│                                   │                                           │
│  ┌──────────────────┐  ┌──────────┴───────────────────────────────────────┐  │
│  │  AuthStore       │  │            Copilot SDK AI Engine                  │  │
│  │  local + OAuth   │  │  ┌────────────────────────────────────────────┐  │  │
│  │  JSON sessions   │  │  │  CopilotClient → CopilotSession            │  │  │
│  │  (multi-worker)  │  │  │  System Prompt: FinOps Assistant           │  │  │
│  └──────────────────┘  │  │  Session Persistence (.copilot_session_id) │  │  │
│                        │  └──────────────────┬─────────────────────────┘  │  │
│  ┌──────────────────┐  │                     │  42 Custom Tools           │  │
│  │ BudgetProvisioner│  │  ┌──────────────────┴─────────────────────────┐  │  │
│  │ real GitHub      │  │  │ Seats (4)      │ Usage (8)                 │  │  │
│  │ user budgets     │  │  │ Billing (2)    │ Actions (3)               │  │  │
│  └──────────────────┘  │  │ Cost Centers(8)│ Budgets / UBB (6)         │  │  │
│                        │  └────────────────────────────────────────────┘  │  │
│  ┌──────────────────┐  └───────────────────────────────────────────────────┘  │
│  │ Sync Manager     │                                                          │
│  │ Cron · SSE       │  ┌───────────────────────────────────────────────────┐  │
│  ├──────────────────┤  │             Data Collection Layer                  │  │
│  │ PAT Manager      │  │  GitHub REST API → data/{category}/{org}_latest    │  │
│  │ Multi-PAT        │  │  Atomic writes · incremental historical merge      │  │
│  │ Auto-Discovery   │  │  Auto-sync on startup · Cron · Manual trigger      │  │
│  └──────────────────┘  └───────────────────────────────────────────────────┘  │
└───────────────────────────────────┬───────────────────────────────────────────┘
                    ┌───────────────┴───────────────┐
                    │        GitHub REST API         │
                    │  /orgs/{org}/copilot/billing    │
                    │  /orgs/{org}/copilot/seats      │
                    │  /orgs/{org}/copilot/metrics    │
                    │  /orgs/{org}/copilot/reports    │
                    │  /organizations/{org}/billing   │
                    │  /enterprises/{ent}/reports     │
                    │  /enterprises/{ent}/budgets     │
                    │  /enterprises/{ent}/cost-centers│
                    │  /enterprises/{ent}/teams       │
                    │  github.com/login/oauth/*  (SSO)│
                    └───────────────────────────────┘
```

## Data Flow

```
1. PAT Configuration → Auto-discover user → Auto-discover orgs & enterprises → Detect Copilot plans
2. Data Sync        → Fetch seats, billing, usage, metrics, AI credits, cost centers, budgets, enterprise teams
                    → Merge into data/{category}/{org}_latest.json (atomic write)
3. Admin Message    → Copilot SDK Session → LLM selects tools → Tools read cache or call live API
4. AI Analysis      → Recommendations → Admin approval → Execute via GitHub API → Audit log
5. User Login (SSO) → Role resolved (admin allow-list / PAT owner) → Portal scoped to own data
6. Budget Request   → User submits → Admin approves → BudgetProvisioner writes a REAL
                      user-scope budget to GitHub → sync result stored on the request
```

## Authentication & Authorization Flow

```
                    ┌─────────────────────────────┐
   Local login ────►│  AuthStore.create_session   │
                    │  data/auth_sessions.json    │──► httpOnly cookie (Secure on HTTPS)
   GitHub SSO ─────►│  is_admin_login(login)?     │
                    └─────────────┬───────────────┘
                                  │
                    ┌─────────────▼───────────────┐
   every /api/* ───►│      Role middleware        │
                    │  none      → 401            │
                    │  non-admin → /api/me/*,     │
                    │              /api/budget-*  │
                    │  admin     → everything     │
                    └─────────────────────────────┘
```

Sessions survive restarts (JSON-persisted) and are re-read from disk on a cache miss so multiple uvicorn workers sharing `data/` stay consistent. Behind a reverse proxy the callback URL and cookie `Secure` flag are derived from `X-Forwarded-Proto` / `X-Forwarded-Host`.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| AI Engine | GitHub Copilot Python SDK (`github-copilot-sdk`) |
| Backend | Python 3.13+, FastAPI, Uvicorn, httpx |
| Frontend | React 19, TypeScript 5.9, Vite 7, Recharts |
| Data | JSON files (no database required) |
| Streaming | Server-Sent Events (SSE) via `sse-starlette` |
| Auth | PBKDF2-SHA256, GitHub OAuth App, httpOnly cookies |

---

## Project Structure

```
OctoFinance/
├── backend/
│   ├── app/
│   │   ├── main.py                     # FastAPI app, auth+role middleware, lifespan
│   │   ├── config.py                   # APP_VERSION, data paths, pricing
│   │   ├── routers/
│   │   │   ├── auth.py                 # Local login + GitHub OAuth SSO + role helpers
│   │   │   ├── me.py                   # Personal ("me") data — own usage & budget
│   │   │   ├── budget_requests.py      # Request → approve → real GitHub budget → audit
│   │   │   ├── chat.py                 # AI chat (SSE streaming)
│   │   │   ├── sessions.py             # Chat session management
│   │   │   ├── sync.py                 # Data sync + SSE progress
│   │   │   ├── data.py                 # Dashboard/data query endpoints
│   │   │   ├── actions.py              # Recommendation execution
│   │   │   ├── pats.py                 # PAT management CRUD + app settings
│   │   │   └── share.py                # Public cost center report share pages
│   │   ├── services/
│   │   │   ├── copilot_engine.py       # Copilot SDK integration, tool registration
│   │   │   ├── auth_store.py           # Credentials, OAuth config, persisted sessions
│   │   │   ├── budget_provisioner.py   # Real GitHub budget create/update + budget reads
│   │   │   ├── github_api.py           # GitHub REST API client
│   │   │   ├── data_collector.py       # Data collection, merge & atomic caching
│   │   │   ├── api_manager.py          # Multi-PAT API management & discovery
│   │   │   ├── session_manager.py      # Chat session persistence
│   │   │   ├── sync_manager.py         # Sync state & cron scheduler
│   │   │   ├── update_checker.py       # Latest-release lookup (30s cap, non-blocking)
│   │   │   ├── pat_manager.py          # PAT CRUD & settings
│   │   │   ├── report_generator.py     # Cost center HTML/ZIP report generation
│   │   │   └── ops_executor.py         # Operation executor
│   │   └── tools/                      # 42 Copilot SDK tools
│   │       ├── seat_tools.py           # 4 seat management tools
│   │       ├── usage_tools.py          # 8 usage analysis tools
│   │       ├── billing_tools.py        # 2 billing/ROI tools
│   │       ├── action_tools.py         # 3 action/recommendation tools
│   │       ├── cost_center_tools.py    # 8 cost center tools
│   │       ├── budget_tools.py         # 6 budget management tools (UBB)
│   │       └── enterprise_team_tools.py # 11 enterprise team tools
│   └── requirements.txt
├── frontend/
│   ├── public/copilot.svg              # Favicon
│   ├── src/
│   │   ├── App.tsx                     # AuthGate → admin layout or UserPortal
│   │   ├── components/
│   │   │   ├── LoginPage.tsx           # Local login + "Sign in with GitHub"
│   │   │   ├── UserPortal.tsx          # Regular-user shell
│   │   │   ├── MyDashboard.tsx         # Own usage, budget, cost centers
│   │   │   ├── BudgetRequestPanel.tsx  # User: submit + own history
│   │   │   ├── BudgetRequestsAdmin.tsx # Admin: review + approval history
│   │   │   ├── UnifiedDashboard.tsx    # 8 admin dashboard tabs
│   │   │   ├── Dashboard.tsx           # Usage metrics (9 sections)
│   │   │   ├── CsvDashboard.tsx        # AI usage / usage report CSV
│   │   │   ├── CostCenterDashboard.tsx # Cost centers + sharing
│   │   │   ├── UnassignedCostCenterUsersDashboard.tsx
│   │   │   ├── EnterpriseTeamsDashboard.tsx # Per-team adoption, cost & rosters
│   │   │   ├── BudgetsDashboard.tsx    # Budgets with consumed/remaining
│   │   │   ├── ChatInterface.tsx       # AI chat UI + model selector
│   │   │   ├── SourceCodeLink.tsx      # Source code / new-version button
│   │   │   ├── ActionPanel.tsx         # Recommendation review
│   │   │   ├── StatusBar.tsx           # Status, period toggle, language, sync
│   │   │   ├── PeriodToggle.tsx        # All Time / Current Month
│   │   │   ├── LanguageSelector.tsx    # 8-language dropdown
│   │   │   ├── GithubSSOSettings.tsx   # OAuth App configuration
│   │   │   ├── PATSettingsModal.tsx    # PAT + sync + SSO settings
│   │   │   ├── ConsolePanel.tsx        # Tool execution console
│   │   │   ├── SessionSelector.tsx     # Multi-session selector
│   │   │   ├── OrgSelector.tsx         # Org overview sidebar
│   │   │   ├── OverviewPanel.tsx       # KPI overview
│   │   │   └── MessageBubble.tsx       # Chat message renderer
│   │   ├── locales/                    # en, zh, zh-TW, ja, ko, hi, vi, th
│   │   ├── contexts/
│   │   │   ├── I18nContext.tsx         # Locale loading, detection, t()
│   │   │   ├── ThemeContext.tsx        # Dark/Light theme
│   │   │   └── UIStateContext.tsx      # Persistent UI state (incl. periodMode)
│   │   ├── hooks/
│   │   │   ├── useChat.ts              # Chat + SSE hook
│   │   │   ├── useData.ts              # Dashboard data hooks
│   │   │   ├── useMe.ts                # Personal dashboard + budget requests
│   │   │   ├── useSessions.ts          # Session management
│   │   │   ├── useSyncStream.ts        # Sync SSE listener
│   │   │   └── usePATs.ts              # PAT management hook
│   │   ├── utils/                      # period.ts, budgetRequests.ts
│   │   └── styles/index.css            # Complete stylesheet
│   └── package.json
├── docs/
│   ├── USAGE.md                        # Usage guide
│   ├── FEATURES.md                     # Detailed features & API reference
│   ├── ARCHITECTURE.md                 # This file
│   └── SECURITY.md                     # RAI notes & security
├── AGENTS.md                           # Custom instructions for the AI agent
├── README.md                           # Project overview & quick start
└── SECURITY.md                         # Microsoft security policy
```
