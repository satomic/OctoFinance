**English** | [简体中文](README_CN.md)

# OctoFinance - GitHub Copilot AI FinOps Platform

AI-powered GitHub Copilot Financial Operations platform for intelligent seat management and cost optimization through the Copilot SDK.

## Prerequisites

- Python 3.13+ (`.venv` configured)
- Node.js 22+
- GitHub PAT (pre-configured in `backend/app/config.py`, can be overridden via `GITHUB_PAT` environment variable)
- **GitHub Copilot CLI** (required) — see [installation guide](https://github.com/github/copilot-cli)

### Installing GitHub Copilot CLI

> Requires an active [GitHub Copilot subscription](https://github.com/features/copilot/plans).

**Windows** (PowerShell v6+ required):
```powershell
winget install GitHub.Copilot
```

**macOS / Linux** (Homebrew):
```bash
brew install copilot-cli
```

**All platforms** (npm):
```bash
npm install -g @github/copilot
```

**macOS / Linux** (install script):
```bash
curl -fsSL https://gh.io/copilot-install | bash
```

After installation, launch `copilot` in your terminal and follow the prompts to authenticate with your GitHub account.

## Getting Started

### 1. Start Backend

```bash
cd OctoFinanceV2/backend
../.venv/bin/uvicorn app.main:app --reload --port 8000
```

You'll see:
```
[OctoFinance] Authenticated as: satomic
[OctoFinance] Discovered 11 organizations: [...]
[OctoFinance] Initial data sync complete.
[OctoFinance] Copilot AI engine ready.
[OctoFinance] Ready!
```

### 2. Start Frontend

Open a new terminal:

```bash
cd OctoFinanceV2/frontend
npm run dev
```

Visit http://localhost:5173 after startup

## Stopping Services

### Option 1: Interrupt Foreground Process

Press `Ctrl+C` in the corresponding terminal window.

### Option 2: Kill Background Process by Port

```bash
# Stop backend (port 8000)
lsof -ti:8000 | xargs kill

# Stop frontend (port 5173)
lsof -ti:5173 | xargs kill
```

### Option 3: Stop All at Once

```bash
lsof -ti:8000 -ti:5173 | xargs kill 2>/dev/null
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Health check, returns user/organization/AI engine status |
| `/api/chat` | POST | AI chat (SSE streaming response) |
| `/api/chat/simple` | POST | AI chat (wait for complete response) |
| `/api/sync` | POST | Trigger full data synchronization |
| `/api/sync/{org}` | POST | Sync specific organization |
| `/api/sync/status` | GET | Synchronization status |
| `/api/data/orgs` | GET | All discovered organizations |
| `/api/data/overview` | GET | Global overview (seats/costs/waste) |
| `/api/data/seats/{org}` | GET | Seat data for specific organization |
| `/api/data/billing/{org}` | GET | Billing data for specific organization |
| `/api/actions/pending` | GET | Pending AI recommendations |
| `/api/actions/execute` | POST | Execute recommendation |
| `/api/actions/reject` | POST | Reject recommendation |
