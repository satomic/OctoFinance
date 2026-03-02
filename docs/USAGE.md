# OctoFinance Usage Guide

## First-Time Setup

1. Open the app in your browser (default: `http://localhost:5173` for dev, or port 8000 for production)
2. On first visit, the **Create Account** screen appears — choose a username and password
3. These credentials are stored locally (PBKDF2-SHA256 hashed) and used for all subsequent logins
4. A language toggle (EN/中文) is available on the login page

## Login

After initial setup, subsequent visits show the login form. Enter your username and password to access the platform.

---

## Interface Overview

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│  StatusBar                                                                       │
│  [OctoFinance] ● user · 3 orgs · ● AI Ready                                    │
│          [Chat|Dashboard] [Settings] [Console] [中文] [Dark] [CSV↑] [Sync] [Logout] │
├────────────────┬─────────────────────────────────────────────────────────────────┤
│                │                                                                 │
│   Sidebar      │              Main Content Area                                  │
│   (resizable)  │                                                                 │
│                │   ┌─────────────────────────────────┐                           │
│  ▼ Overview    │   │  Chat View  OR  Dashboard View  │                           │
│    KPI cards   │   │  (toggled via StatusBar)         │                           │
│                │   │                                  │                           │
│  ▼ Orgs        │   │                                  │                           │
│    Org list    │   └─────────────────────────────────┘                           │
│                │                                                                 │
│  ▼ Sessions    │   ┌─────────────────────────────────┐                           │
│    [+] new     │   │  Console Panel (toggleable)      │                           │
│    Session list│   │  Tool logs · Sync progress        │                           │
│                │   └─────────────────────────────────┘                           │
│  ▼ Actions     │                                                                 │
│    Pending recs│                                                                 │
│                │                                                                 │
└────────────────┴─────────────────────────────────────────────────────────────────┘
```

The interface has four main areas:

1. **StatusBar** (top) — Health status, view toggle, settings, and controls
2. **Sidebar** (left, resizable) — Four collapsible panels
3. **Main Content** (center) — Chat view or Dashboard view
4. **Console Panel** (bottom, toggleable) — Tool execution and sync logs

---

## StatusBar

The top bar contains health indicators and controls (left to right):

| Element | Description |
|---------|-------------|
| **OctoFinance** | App title |
| **Health indicators** | Green dot + username + org count (backend connected), AI status (Ready/Starting) |
| **Chat / Dashboard** | Toggle between the two main views |
| **Settings** | Opens PAT management and sync configuration modal |
| **Console** | Toggle the bottom console panel |
| **中文 / EN** | Switch UI language between English and Chinese |
| **Dark / Light** | Switch color theme |
| **Upload CSV** | Upload premium request usage CSV (exported from GitHub UI) |
| **Sync Data** | Manually trigger a full data sync from GitHub APIs |
| **Logout** | End session and return to login |

---

## Sidebar Panels

The sidebar has four collapsible panels. Click any panel header to expand/collapse. Drag the sidebar edge to resize.

### Overview

Displays key performance indicators at a glance:
- Total seats across all organizations
- Active vs. inactive seat counts
- Utilization rate (percentage)
- Monthly cost and estimated monthly waste

### Organizations

Lists all auto-discovered organizations with:
- Organization name
- Copilot plan type (Business / Enterprise)
- Seat counts (total / active)

### Sessions

Manage multiple AI chat sessions:
- **+** button — Create a new session
- Click a session to switch to it
- Right-click or hover to **rename** or **delete** a session
- Each session maintains its own conversation history and context
- The AI retains multi-turn context within a session

### Pending Actions

Shows AI-generated recommendations awaiting admin review:
- Each card shows: action type, affected org/users, estimated savings
- **Approve & Execute** — Confirms and runs the operation (calls GitHub API)
- **Reject** — Declines the recommendation

> **Warning**: Approve & Execute performs real operations (e.g., removing Copilot seats). Review carefully before clicking.

---

## Chat View

The default main content view. Provides a natural language interface to the AI FinOps assistant.

### Quick Prompt Buttons

On first visit (empty conversation), four quick prompts appear:

| Button | What it does |
|--------|-------------|
| **Overview** | Global Copilot usage and cost overview across all orgs |
| **Inactive Users** | Find users inactive for 30+ days with cost impact |
| **Cost Optimization** | Analyze waste and provide specific savings recommendations |
| **ROI Analysis** | Calculate return on investment per org |

### Conversation Examples

**View overview:**
```
Show me the current Copilot usage and costs across all organizations
```

**Find inactive users:**
```
Which users haven't used Copilot in over 30 days? How much money is wasted?
```

**Deep dive into an organization:**
```
How is the Copilot utilization in the contoso organization? Who uses it most?
```

**Cost optimization:**
```
Help me analyze where we can save money and provide specific recommendations
```

**Create action suggestions:**
```
List all inactive users and create suggestions to remove their seats
```

**Premium request analysis:**
```
Show me premium request usage — which models cost the most?
```

**Cross-organization comparison:**
```
Compare Copilot utilization across organizations — which one has the most waste?
```

**Multi-turn conversation (AI remembers context):**
```
You: Show me inactive users in contoso
AI: Found 5 inactive users... Should I create removal recommendations?
You: Yes, create them
AI: Recommendations created, estimated savings of $285/month
You: Actually, skip user alice — she's on parental leave
```

### Tool Indicators

During AI responses, tool execution indicators appear as small tags:
- **Spinning** `get_all_seats` — Tool is running
- **Green check** `get_all_seats` — Tool completed successfully

Common tools you'll see: `get_all_seats`, `find_inactive_users`, `get_cost_overview`, `calculate_roi`, `get_usage_report`, `record_recommendation`

### Controls

| Control | Action |
|---------|--------|
| **Send** (Enter) | Send message |
| **Clear** | Clear conversation history |
| **Stop** | Abort AI response in progress |

---

## Dashboard View

Switch to Dashboard via the StatusBar toggle. Displays rich analytics visualizations.

### Filters

- **Organization multi-select** — Filter data by one or more orgs (top of dashboard)
- **Date range** — Filter time-series data with start/end date pickers

### 9 Dashboard Sections

Each section is collapsible. Click the header to expand/collapse.

| Section | Visualizations |
|---------|---------------|
| **Active User Trends** | MAU / WAU / DAU area chart, Chat & Agent user overlay |
| **Code Productivity** | LOC suggested/accepted trend line, acceptance rate chart |
| **Feature Usage** | Feature-by-feature table (interactions, code generation, acceptance) |
| **Language Distribution** | Horizontal bar chart + code completions table by language |
| **Model & Premium Requests** | Model usage pie chart + per-model cost/quantity table |
| **Per-User Premium** | Daily trend bar chart, model breakdown pie, per-user table with quota bars |
| **IDE Distribution** | IDE interaction bar chart + detailed table |
| **Seat Management** | Full seat table with status, team, activity, plan badges |
| **Top Active Users** | Ranked table with interactions, code generation, chat/agent usage |

---

## PAT Settings

Click **Settings** in the StatusBar to open the PAT management modal.

### Add a PAT

1. Enter a label (e.g., "Production PAT")
2. Paste your GitHub Personal Access Token
3. Click **Add** — the system auto-discovers the user, organizations, and Copilot plans

### Required PAT Permissions

| Scope | Purpose |
|-------|---------|
| `read:org` | Discover organizations |
| `admin:org` | Read Copilot billing and seats |
| `copilot` | Access Copilot usage metrics |
| `manage_billing:copilot` | Premium request usage data |

### Remove a PAT

Click the delete button next to a PAT. Confirm to remove.

### Sync Configuration

- **Auto Sync on Startup** — Toggle whether data syncs automatically when the backend starts
- **Sync Cron Schedule** — Set periodic sync interval using presets (30min, 1h, 6h, 24h, Off) or a custom cron expression

---

## Console Panel

Toggle via the **Console** button in the StatusBar. Shows:

- **Tool execution logs** — Each tool call during AI conversation with timestamps
- **Sync progress** — Real-time progress during data synchronization (SSE streaming)
- **Clear** button to reset the log

The console auto-opens when a sync begins.

---

## Premium Request CSV Upload

GitHub does not provide per-user premium request breakdown via API — only org-level totals. To get per-user data:

1. Go to GitHub.com > Organization Settings > Billing > Copilot > Export usage as CSV
2. Click **Upload CSV** in the StatusBar
3. Select the downloaded CSV file
4. The data appears in the Dashboard's **Per-User Premium** section

The upload is incremental — duplicate rows are automatically ignored.

---

## MCP Integration

OctoFinance can also be used as an MCP (Model Context Protocol) server, allowing external LLM clients to call OctoFinance tools directly.

### Setup

1. Install MCP dependency: `pip install mcp`
2. Add to your MCP client configuration:
   ```json
   {
     "mcpServers": {
       "octofinance": {
         "command": "python",
         "args": ["-m", "backend.app.mcp_server"]
       }
     }
   }
   ```
3. The MCP server exposes all 17 OctoFinance tools (seat management, usage analysis, billing, actions)

See `mcp.json` in the project root for the example configuration.

---

## UI Tips

| Feature | How |
|---------|-----|
| Resize sidebar | Drag the divider between sidebar and main content |
| Collapse sidebar panel | Click the panel header (Overview, Orgs, Sessions, Actions) |
| Collapse dashboard section | Click the section header |
| Switch view | Click Chat or Dashboard in the StatusBar |
| Keyboard shortcut | Press Enter to send a message |
| Theme persistence | Theme, language, sidebar width, and panel states are saved in your browser |
