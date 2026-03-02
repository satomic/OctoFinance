# OctoFinance — Feature Details & API Reference

## Copilot SDK Agentic AI (Core)

- **17 custom tools** registered via `define_tool()` from `github-copilot-sdk`
- **Session management** with resume capability across backend restarts
- **Streaming responses** via SSE (Server-Sent Events)
- **Tool transparency**: Real-time tool execution indicators in the chat UI
- **Multi-turn conversations**: Context preserved across messages within a session
- **MCP integration**: All 17 tools also available via MCP protocol for external LLM clients

### Tool Catalog

| Category | Tool | Description |
|----------|------|-------------|
| **Seats** | `get_all_seats` | Get seat assignments with activity info |
| | `find_inactive_users` | Find users inactive for N days with cost impact |
| | `remove_user_seat` | Remove seats (auto-detects org vs. team assignment) |
| | `add_team_member` | Add user to team for Copilot access |
| **Usage** | `get_usage_report` | Org-level 28-day usage from cached data |
| | `get_users_usage_report` | User-level 28-day usage from cached data |
| | `get_metrics_detail` | Detailed metrics (legacy API) |
| | `get_premium_request_usage` | Org-level premium request breakdown |
| | `get_user_premium_usage` | Per-user premium usage from CSV data |
| | `fetch_org_usage_report` | Live org-level usage from GitHub API |
| | `fetch_org_users_usage_report` | Live user-level usage from GitHub API |
| | `fetch_premium_request_usage` | Live premium request data from GitHub API |
| **Billing** | `get_cost_overview` | Cost overview: seats, waste, utilization |
| | `calculate_roi` | ROI metrics: cost per user, acceptance rate |
| **Actions** | `batch_remove_seats` | Batch seat removal with audit logging |
| | `record_recommendation` | Create recommendation for admin review |
| | `get_recommendations` | Retrieve pending/approved/rejected recommendations |

## Analytics Dashboard (9 Sections)

| Section | Visualizations |
|---------|---------------|
| **Active User Trends** | MAU/WAU/DAU area chart, Chat & Agent user overlay |
| **Code Productivity** | LOC suggested/accepted trend, acceptance rate line chart |
| **Feature Usage** | Feature-by-feature table (interactions, code gen, acceptance) |
| **Language Distribution** | Horizontal bar chart + code completions table by language |
| **Model & Premium Requests** | Model usage pie chart + per-model cost/quantity table |
| **Per-User Premium** | Daily trend bar, model breakdown pie, per-user table with quota bars |
| **IDE Distribution** | IDE interaction bar chart + detailed table |
| **Seat Management** | Full seat table with status, team, activity, plan badges |
| **Top Active Users** | Ranked table with interactions, code gen, chat/agent usage |

## Multi-Organization Management

- Support for **multiple GitHub PATs** with label management
- **Auto-discovery** of all organizations per PAT
- **Auto-detection** of Copilot plan type (Business $19/seat vs. Enterprise $39/seat)
- **Cross-org filtering** in dashboard with multi-select dropdown
- **Enterprise-level** usage report support

## Real-Time Data Synchronization

- **Auto-sync on startup** (configurable)
- **Cron-based scheduling** (e.g., `*/30 * * * *` for every 30 minutes)
- **SSE streaming** of sync progress to frontend
- **Per-organization** sync capability
- **Dual-write**: syncs to both global data store and per-session working directory

## Human-in-the-Loop Operations

- AI generates **recommendations** with estimated cost savings
- Recommendations stored in **Action Panel** for admin review
- **Approve & Execute** or **Reject** workflow
- **Intelligent seat removal**: auto-detects org-level vs. team-level assignment and uses correct API
- **Audit logging** for all executed operations

## Premium Request Analytics

- **Org-level premium request** tracking via GitHub Billing API
- **Per-user premium usage** from CSV upload (GitHub UI email export)
- **Per-model breakdown** (GPT-5.2, Claude Opus 4.6, etc.)
- **Quota tracking** with visual progress bars
- **Cost analysis** including gross/discount/net amounts

## Security & Authentication

- **Cookie-based session auth** with PBKDF2-SHA256 password hashing
- **First-visit setup** flow for initial credential creation
- **Auth middleware** protecting all API endpoints
- **PAT masking** in UI (only last 4 characters visible)
- **httpOnly cookies** with SameSite=Lax

## Internationalization & Theming

- **English and Chinese** (Simplified) full UI translation
- **Dark and Light** theme toggle
- **UI state persistence** via localStorage (sidebar, dashboard sections, filters, session)

---

## API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Health check — user, orgs, AI engine status |
| `/api/auth/status` | GET | Auth status — setup required, authenticated |
| `/api/auth/setup` | POST | First-time credential setup |
| `/api/auth/login` | POST | Login with username/password |
| `/api/auth/logout` | POST | Logout, clear session |
| `/api/chat` | POST | AI chat with SSE streaming response |
| `/api/chat/simple` | POST | AI chat, wait for complete response |
| `/api/sessions` | GET | List all chat sessions |
| `/api/sessions` | POST | Create a new chat session |
| `/api/sessions/{id}` | DELETE | Delete a chat session |
| `/api/sessions/{id}/messages` | GET | Get messages for a session |
| `/api/sync` | POST | Trigger full data sync (background) |
| `/api/sync/{org}` | POST | Sync specific organization |
| `/api/sync/status` | GET | Current sync status |
| `/api/sync-stream` | GET | SSE stream of sync progress |
| `/api/data/orgs` | GET | All discovered organizations |
| `/api/data/overview` | GET | Global overview (seats, costs, waste) |
| `/api/data/seats/{org}` | GET | Seat data for an organization |
| `/api/data/billing/{org}` | GET | Billing data for an organization |
| `/api/data/dashboard` | GET | Aggregated dashboard data |
| `/api/actions/pending` | GET | Pending AI recommendations |
| `/api/actions/execute` | POST | Execute a recommendation |
| `/api/actions/reject` | POST | Reject a recommendation |
| `/api/pats` | GET/POST/PUT/DELETE | PAT management CRUD |
| `/api/pats/settings` | GET/PUT | App settings (sync config) |

## Configuration

PATs and settings are managed through the web UI (Settings modal):

- **Add/Remove PATs**: Manage multiple GitHub PATs with labels
- **Auto Sync on Startup**: Toggle automatic data sync when backend starts
- **Sync Cron Schedule**: Set periodic sync (e.g., `*/30 * * * *`)
