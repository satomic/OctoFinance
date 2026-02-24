# OctoFinance V2 - GitHub Copilot AI FinOps Platform

## Context

GitHub Copilot 管理员需要一个**以 AI 为核心的 FinOps 运维平台**，而不是传统的 Dashboard。核心价值在于：让 AI 主动分析 Copilot 使用数据，发现浪费（如长期未使用的席位）、提出优化建议（如提醒低使用率用户）、并可直接执行运维操作（如移除席位）。

平台需要支持多 Enterprise、多 Organization、多 Team 维度的统一管理。

## Tech Stack

- **Backend**: Python FastAPI + Copilot Python SDK (`github-copilot-sdk`)
- **Frontend**: React (Vite + TypeScript)
- **AI Engine**: GitHub Copilot SDK (JSON-RPC control of Copilot CLI with custom tools)
- **Data Storage**: JSON files (no database)
- **Python env**: `.venv`

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    React Frontend                         │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────┐ │
│  │  AI Chat     │  │ Smart Actions │  │  Org Selector   │ │
│  │  Interface   │  │ Panel (建议)  │  │  & Overview     │ │
│  └──────┬──────┘  └──────┬───────┘  └────────┬────────┘ │
└─────────┼────────────────┼───────────────────┼──────────┘
          │    SSE/REST    │                   │
┌─────────┼────────────────┼───────────────────┼──────────┐
│         ▼  FastAPI Backend                   ▼          │
│  ┌─────────────────────────────────────────────────┐    │
│  │              API Layer (FastAPI)                  │    │
│  │  /api/chat (SSE)  /api/sync  /api/actions       │    │
│  └─────────────────────┬───────────────────────────┘    │
│                        │                                 │
│  ┌─────────────────────▼───────────────────────────┐    │
│  │           Copilot SDK AI Engine                   │    │
│  │  CopilotClient + CopilotSession                  │    │
│  │  Custom Tools: analyze_seats, find_waste,         │    │
│  │  remove_seat, get_usage, calculate_roi...         │    │
│  └─────────────────────┬───────────────────────────┘    │
│                        │                                 │
│  ┌─────────────────────▼───────────────────────────┐    │
│  │         Data Collection Layer                     │    │
│  │  GitHub REST API → JSON Files (data/)             │    │
│  └─────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────┘
```

## Implementation Progress

### Step 1: Project Scaffolding
- [x] Create directory structure
- [x] Backend: `requirements.txt`
- [x] `.gitignore`
- [x] `config.py`, `main.py`
- [x] Frontend: Vite + React + TypeScript init

### Step 2: GitHub REST API Client (Auto-discovery + Data Collection)
- [x] `github_api.py` - Auto-discover user/orgs/enterprises, detect Copilot plan type
- [x] `data_collector.py` - Collect data → JSON files

### Step 3: Copilot SDK AI Engine (Core)
- [x] `copilot_engine.py` - CopilotClient + session management
- [x] `seat_tools.py` - Seat management tools (get_all_seats, find_inactive_users, remove_user_seat)
- [x] `usage_tools.py` - Usage analysis tools (get_usage_summary, get_metrics_detail)
- [x] `billing_tools.py` - Cost/billing tools (get_cost_overview, calculate_roi)
- [x] `action_tools.py` - Ops action tools (batch_remove_seats, record_recommendation, get_recommendations)

### Step 4: FastAPI Routers
- [x] `chat.py` - SSE chat endpoint (/api/chat, /api/chat/simple)
- [x] `sync.py` - Data sync endpoint (/api/sync, /api/sync/{org}, /api/sync/status)
- [x] `data.py` - Data query endpoint (/api/data/orgs, /api/data/overview, /api/data/seats/{org})
- [x] `actions.py` - Action execution endpoint (/api/actions/pending, execute, reject)

### Step 5: React Frontend
- [x] Initialize Vite + React + TypeScript
- [x] `ChatInterface.tsx` - AI chat UI with quick prompts
- [x] `ActionPanel.tsx` - Smart action panel with approve/reject
- [x] `OrgSelector.tsx` - Organization selector with overview stats
- [x] `StatusBar.tsx` - Status bar with sync button
- [x] `useChat.ts` - SSE chat hook with streaming
- [x] `useData.ts` - Data hooks (orgs, overview, actions, sync)
- [x] Styling (GitHub-dark theme)
- [x] Frontend build verified (TypeScript + Vite build pass)

### Step 6: End-to-end Verification
- [x] Backend imports verified
- [x] Frontend build verified
- [x] Backend starts, auto-discovers 11 orgs (user: satomic)
- [x] Copilot AI engine starts successfully
- [x] Data sync works: 9 orgs with Copilot detected (auto plan type: Business/Enterprise)
- [x] AI chat works: correctly calls tools and returns real data analysis
- [x] Chinese/English bilingual responses confirmed
- [x] Inactive user detection: found 3 users, $117/month waste
- [x] Recommendation creation works via AI tools
- [x] SSE streaming works: tool_start → tool_complete → message events
- [x] /api/actions/pending returns pending recommendations

## How to Run

```bash
# Backend (terminal 1)
cd backend
PYTHONPATH=. ../.venv/bin/uvicorn app.main:app --reload --port 8000

# Frontend (terminal 2)
cd frontend
npm run dev
```

Then open http://localhost:5173
