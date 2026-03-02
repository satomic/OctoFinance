# AGENTS.md — OctoFinance AI Agent Instructions

## Agent Identity

**Name**: OctoFinance AI FinOps Assistant
**Platform**: GitHub Copilot Python SDK (`github-copilot-sdk`)
**Runtime**: Copilot CLI (JSON-RPC control via SDK)

The OctoFinance AI agent is a specialized FinOps assistant that helps GitHub Copilot administrators optimize costs, manage seats, and gain insights across multiple organizations and enterprises.

---

## System Prompt

The agent operates under the following system prompt (defined in `backend/app/services/copilot_engine.py`):

```
You are OctoFinance AI FinOps Assistant, specialized in helping GitHub Copilot
administrators optimize costs and manage seats efficiently.

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
- For destructive operations (seat removal), always explain the impact first
  and ask for confirmation

Available data dimensions:
- Seats: who has Copilot, when they last used it, which team they belong to
- Usage Reports: org-level and user-level usage metrics (28-day or specific day),
  feature adoption, engagement data
- Billing: plan type, cost per seat, total cost, waste
- Metrics: detailed IDE completions, chat usage, PR summaries (legacy API)
- Premium Requests: per-model breakdown of premium request consumption,
  pricing, and costs

Copilot Premium Requests quota (included free per user per month):
- Copilot Business: 300 premium requests/user/month
- Copilot Enterprise: 1000 premium requests/user/month
Requests beyond the included quota are billed at $0.04 per request.

For usage data, prefer the new usage report tools (get_usage_report,
get_users_usage_report) which use the latest Copilot Usage Metrics API.
You can also use fetch_org_usage_report / fetch_org_users_usage_report to get
live data directly from GitHub API for a specific day or the latest 28-day period.
```

---

## Tool Catalog (17 Tools)

### Seat Management Tools (`backend/app/tools/seat_tools.py`)

| # | Tool | Type | Description |
|---|------|------|-------------|
| 1 | `get_all_seats` | Read | Get all Copilot seat assignments. Returns user list with activity info, assigned teams, and last active dates. Supports filtering by org or querying all orgs. |
| 2 | `find_inactive_users` | Read | Find Copilot users who have been inactive for N days (default: 30). Returns list of inactive users with last activity date, assigned team, and per-user cost impact. |
| 3 | `remove_user_seat` | Write | Remove Copilot seats for specified users. Auto-detects org-level vs. team-level assignment and uses the correct removal API. Destructive — requires admin confirmation. |
| 4 | `add_team_member` | Write | Add a user to an organization team. Grants team-level Copilot access if the team has Copilot enabled. |

### Usage Analysis Tools (`backend/app/tools/usage_tools.py`)

| # | Tool | Type | Description |
|---|------|------|-------------|
| 5 | `get_usage_report` | Read (Cached) | Get org-level Copilot usage report from cached data. Contains aggregated usage statistics, feature adoption metrics, and engagement data for the latest 28-day period. |
| 6 | `get_users_usage_report` | Read (Cached) | Get user-level Copilot usage report from cached data. Contains per-user engagement statistics, feature usage patterns, and adoption metrics. |
| 7 | `get_metrics_detail` | Read (Cached) | Get detailed Copilot metrics (legacy API) including IDE code completions, chat usage, PR summaries, and per-editor/model breakdown. |
| 8 | `get_premium_request_usage` | Read (Cached) | Get premium request usage from cached data. Shows per-model breakdown: model names, request counts, pricing, gross/discount/net amounts. |
| 9 | `get_user_premium_usage` | Read (CSV) | Get per-user premium request usage from uploaded CSV data. Shows each user's daily consumption by AI model, including costs, quota usage, and active days. |
| 10 | `fetch_org_usage_report` | Read (Live) | Fetch LIVE org-level usage report directly from GitHub API. Supports specific day or 28-day report. Data available from Oct 10, 2025 onward. |
| 11 | `fetch_org_users_usage_report` | Read (Live) | Fetch LIVE user-level usage report directly from GitHub API. Supports specific day or 28-day report. |
| 12 | `fetch_premium_request_usage` | Read (Live) | Fetch LIVE premium request usage from GitHub API. Supports historical queries (year/month, up to 24 months). |

### Billing & ROI Tools (`backend/app/tools/billing_tools.py`)

| # | Tool | Type | Description |
|---|------|------|-------------|
| 13 | `get_cost_overview` | Read | Get cost overview across organizations. Shows total seats, active seats, wasted seats, monthly cost, estimated waste, and utilization percentage. |
| 14 | `calculate_roi` | Read | Calculate ROI metrics: cost per active user, suggestions per dollar, acceptance rate, and efficiency metrics per organization. |

### Action & Recommendation Tools (`backend/app/tools/action_tools.py`)

| # | Tool | Type | Description |
|---|------|------|-------------|
| 15 | `batch_remove_seats` | Write | Batch remove Copilot seats. Auto-detects org-level vs. team-level. Records action in audit log. Requires admin confirmation. |
| 16 | `record_recommendation` | Write | Record an AI-generated recommendation for admin review. Supports types: remove_seats, send_reminder, upgrade_plan, downgrade_plan. Stored in Action Panel. |
| 17 | `get_recommendations` | Read | Get recorded recommendations filtered by status (pending, approved, rejected, executed, all). |

---

## Data Flow Architecture

### Read Path (Cached Data)
```
User Question
  → Copilot SDK Session (LLM selects tools)
    → Tool reads from DataCollector
      → DataCollector loads JSON from data/{type}/{org}.json
        → Tool returns structured data to LLM
          → LLM generates analysis response
```

### Read Path (Live API)
```
User Question
  → Copilot SDK Session (LLM selects fetch_* tool)
    → Tool calls GitHubAPI via APIManager
      → GitHubAPI makes HTTP request to GitHub REST API
        → Response cached locally + returned to LLM
          → LLM generates analysis response
```

### Write Path (Operations)
```
User requests action
  → LLM calls record_recommendation
    → Recommendation stored in data/recommendations.json
      → Shown in frontend Action Panel
        → Admin clicks "Approve"
          → Backend calls GitHub API (remove seat / add team member)
            → Result logged in data/audit_log.json
```

---

## Session Management

### Session Isolation
Each chat session gets its own working directory at `data/sessions/{session_id}/`. The Copilot SDK uses this directory for:
- Session state persistence (`.copilot_session_id`)
- Session-specific data cache
- Copilot Skills (`.github/skills/`)

### Session Lifecycle
1. **Create**: `CopilotClient.create_session(config)` — registers tools, system prompt, working directory
2. **Resume**: `CopilotClient.resume_session(sdk_session_id, config)` — restores state after backend restart
3. **Send**: `session.send({"prompt": message})` — triggers agentic loop with event streaming
4. **Destroy**: `session.destroy()` — cleanup

### Copilot Skills
The SDK discovers skills from `.github/skills/` within the session working directory. Skills are markdown-defined capabilities that extend the agent's knowledge base without code changes.

---

## How to Extend the Agent

### Adding a New Tool

1. **Define the tool** in `backend/app/tools/`:

```python
from pydantic import BaseModel, Field
from copilot import define_tool

class MyToolParams(BaseModel):
    org: str = Field(default="", description="Organization name")

@define_tool(description="Clear description of what this tool does")
def my_new_tool(params: MyToolParams) -> str:
    # Read from collector or call API
    result = collector.load_latest("data_type", params.org)
    return json.dumps(result)
```

2. **Register in `copilot_engine.py`**:

```python
from ..tools.my_tools import create_my_tools

def _build_tools_for_session(self, working_directory):
    tools = (
        create_seat_tools(...)
        + create_usage_tools(...)
        + create_billing_tools(...)
        + create_action_tools(...)
        + create_my_tools(...)  # Add here
    )
    return tools
```

### Design Principles

| Principle | Guideline |
|-----------|-----------|
| **Clear descriptions** | The `description` parameter is how the LLM decides when to call your tool |
| **Accurate schemas** | Use Pydantic models with `Field(description=...)` for all parameters |
| **Single responsibility** | Multiple simple tools > one complex tool |
| **Read/write separation** | Read ops use DataCollector, write ops use APIManager → GitHubAPI |
| **Structured output** | Return JSON strings for LLM consumption |
| **Error handling** | Return error messages as JSON, don't raise exceptions |

---

## Configuration

### Environment
- **Python 3.13+** with FastAPI
- **GitHub Copilot CLI** must be installed and authenticated
- **GitHub PATs** configured via the web UI or `GITHUB_PAT` env var

### Key Files
| File | Purpose |
|------|---------|
| `backend/app/services/copilot_engine.py` | SDK client, session management, system prompt |
| `backend/app/tools/*.py` | All 17 custom tools |
| `backend/app/services/data_collector.py` | Data caching and retrieval |
| `backend/app/services/github_api.py` | GitHub REST API client |
| `backend/app/services/api_manager.py` | Multi-PAT API management |
| `backend/app/config.py` | Pricing, paths, directories |
