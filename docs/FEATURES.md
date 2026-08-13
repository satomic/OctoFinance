# OctoFinance — Feature Details & API Reference

> Applies to **v1.1.3**.

## Copilot SDK Agentic AI (Core)

- **42 custom tools** registered via `define_tool()` from `github-copilot-sdk`
- **Session management** with resume capability across backend restarts
- **Streaming responses** via SSE (Server-Sent Events)
- **Tool transparency**: real-time tool execution indicators in the chat UI
- **Multi-turn conversations**: context preserved across messages within a session
- **Model selection**: a dropdown next to the chat input lists the models the Copilot account can actually use, fetched live from the SDK (`models.list`). The default is **Auto** (Copilot picks); choosing a model calls `session.set_model()` so it applies from the next message onward, and switching back to Auto resets the session to Copilot's `auto` model
- **Copilot Skills**: the SDK discovers markdown-defined skills from `.github/skills/` inside each session working directory

> **Auth fallback** — if the configured Copilot token (`COPILOT_GITHUB_TOKEN` / `GH_TOKEN` / `GITHUB_TOKEN`, or the first UI-configured PAT) is rejected, the engine falls back to the Copilot CLI's own logged-in user instead of leaving every request failing with *Not authenticated*.

### Tool Catalog

| Category | Tool | Description |
|----------|------|-------------|
| **Seats** (4) | `get_all_seats` | Get seat assignments with activity info |
| | `find_inactive_users` | Find users inactive for N days with cost impact |
| | `remove_user_seat` | Remove seats (auto-detects org vs. team assignment) |
| | `add_team_member` | Add user to team for Copilot access |
| **Usage** (8) | `get_usage_report` | Org-level usage from cached data |
| | `get_users_usage_report` | User-level usage from cached data |
| | `get_metrics_detail` | Detailed metrics (legacy API) |
| | `get_ai_credit_usage` | Org-level AI credit breakdown from cache |
| | `get_user_ai_usage` | Per-user AI usage from uploaded CSV data |
| | `fetch_org_usage_report` | Live org-level usage from GitHub API |
| | `fetch_org_users_usage_report` | Live user-level usage from GitHub API |
| | `fetch_ai_credit_usage` | Live AI credit data from GitHub API |
| **Billing** (2) | `get_cost_overview` | Cost overview: seats, waste, utilization |
| | `calculate_roi` | ROI metrics: cost per user, acceptance rate |
| **Actions** (3) | `batch_remove_seats` | Batch seat removal with audit logging |
| | `record_recommendation` | Create recommendation for admin review |
| | `get_recommendations` | Retrieve pending/approved/rejected recommendations |
| **Cost Centers** (8) | `get_synced_enterprise_data` | Enterprise + cost center data from the last sync |
| | `list_cost_centers` | List enterprise cost centers |
| | `create_cost_center` | Create a cost center |
| | `get_cost_center` | Get one cost center with members |
| | `update_cost_center` | Rename / update a cost center |
| | `delete_cost_center` | Delete a cost center |
| | `add_cost_center_resources` | Add users/orgs/repos to a cost center |
| | `remove_cost_center_resources` | Remove resources from a cost center |
| **Budgets — UBB** (6) | `get_all_budgets` | List budgets for an enterprise/org, filterable by scope |
| | `get_budget_detail` | Get a single budget by ID |
| | `create_user_budget` | Create a universal or individual user budget |
| | `update_budget` | Change budget amount / hard-limit flag |
| | `delete_budget` | Delete a budget |
| | `batch_create_user_budgets` | Create individual budgets for many users at once |
| **Enterprise Teams** (11) | `list_enterprise_teams` | List enterprise teams with member counts and assigned orgs |
| | `get_enterprise_team` | One team's full detail including its member roster |
| | `get_user_enterprise_teams` | Which enterprise teams a given user belongs to |
| | `get_enterprise_team_copilot_usage` | Per-team seats, members without a seat, active members, interactions, estimated seat cost |
| | `create_enterprise_team` | Create a team (description, IdP group, org assignment mode) |
| | `update_enterprise_team` | Rename / change description, org mode or notifications |
| | `delete_enterprise_team` | Delete a team and its IdP mappings |
| | `add_enterprise_team_organizations` | Assign a team to organizations |
| | `remove_enterprise_team_organizations` | Unassign a team from organizations |
| | `add_enterprise_team_members` | Bulk add users to a team |
| | `remove_enterprise_team_members` | Bulk remove users from a team |

> Enterprise team endpoints accept **classic PATs only** — `read:enterprise` for reads, `admin:enterprise` for writes. Fine-grained and GitHub App tokens are rejected by GitHub.

## Authentication & Roles

Two sign-in paths, both landing on the same session model:

- **Local admin** — username/password, PBKDF2-SHA256 (100,000 iterations), created on first visit. Stored in `data/auth.json`.
- **GitHub SSO** — standard OAuth App flow (`/api/auth/github/login` → GitHub → `/api/auth/github/callback`). Configured in **Settings → GitHub SSO** or via `GITHUB_OAUTH_CLIENT_ID` / `GITHUB_OAUTH_CLIENT_SECRET` / `GITHUB_OAUTH_CALLBACK_URL`. Stored in `data/oauth.json`.

| Role | How it is determined | Scope |
|------|----------------------|-------|
| **Administrator** | Local login, a GitHub login on the admin allow-list, or the owner of any configured PAT | Full platform, identical for local and SSO logins |
| **Regular user** | Any other GitHub account | Personal portal only — their own data plus budget requests |

Role enforcement is server-side in `main.py`'s auth middleware: non-admins may only reach `/api/auth/*`, `/api/me/*` and `/api/budget-requests`; everything else returns `403`. Setting **Allow any GitHub user to sign in** to off restricts login to admins and PAT owners.

Sessions are JSON-persisted in `data/auth_sessions.json` and re-read from disk on a cache miss, so a backend restart does not log everyone out and multiple uvicorn workers sharing a data directory see the same sessions. OAuth CSRF state lives in `data/auth_oauth_states.json` for the same reason.

## Self-Service User Portal

Regular users signing in with GitHub get a portal scoped strictly to themselves:

- **My seats** — every org where they hold a Copilot seat, with plan, team, assignment date, last activity, days inactive and per-seat cost (de-duplicated per org)
- **My activity** — interactions, code generation vs. acceptance, acceptance rate, active days, plus per-feature, per-model, per-IDE and per-language breakdowns with a daily trend
- **My AI credits** — daily consumption trend and per-model breakdown with cost, and quota usage against the plan allowance
- **My billed usage** — per-SKU gross/net amounts
- **My budget** — the budget that actually applies to them (individual, or the universal fallback) with live `consumed_amount` / remaining straight from the GitHub Billing Budgets API
- **My cost centers** — every cost center they belong to, how they joined (User / Org / Team), whether the AI credit pool is enabled, and that cost center's budget with consumption

## User Requests (applied for real)

Regular users can raise two kinds of request. Both are reviewed by an administrator, and approving applies the change against the real GitHub API.

### Budget requests

| Step | Behaviour |
|------|-----------|
| **Submit** | A user files an amount plus an optional org and a justification. GitHub Copilot budgets run on a **single monthly billing cycle**, so there is no period to choose — the amount is the monthly allowance |
| **Review** | Admins see all requests in **Dashboard → Requests**, filter by status, edit the approved amount inline, and add a comment |
| **Approve** | Creates or updates a real GitHub `budget_scope: "user"`, `ai_credits` budget via `POST`/`PATCH /enterprises/{slug}/settings/billing/budgets`. Enterprises are preferred over organizations because that is where Copilot budgets are administered |
| **Verify** | The sync result (`created` / `updated` / `failed` / `skipped`) plus budget ID and entity are stored on the request and shown as a badge to both admin and requester |
| **Recover** | A failed sync can be retried with one click (`/api/budget-requests/resync`). Unticking *"Apply the change to GitHub on approve"* records an approval without touching GitHub |

The budget is personal (`user` scope), so cost centers are deliberately not part of this request — they have their own request type below.

### Cost center requests

| Step | Behaviour |
|------|-----------|
| **Submit** | A user picks the cost center they should belong to from a dropdown, pre-selected with their current one. **GitHub assigns each user to at most one cost center**, so this is a single choice; picking `Unassigned` removes them from their current one |
| **Inherited membership** | A user who lands in a cost center because their whole *organization* or *team* is a resource of it is shown read-only — that membership cannot be changed per user, so it is excluded from the dropdown |
| **Approve** | Calls `POST /enterprises/{slug}/settings/billing/cost-centers/{id}/resource` to assign the user. GitHub moves them out of their previous cost center automatically and reports it in `reassigned_resources`; leaving without joining uses the matching `DELETE` |
| **Verify** | The result (`applied` / `partial` / `failed` / `noop` / `skipped`) with the from → to move is stored on the request and badged in the UI |

### Shared

An **Approval History** tab renders a flat, newest-first trail of every submission, approval, rejection, amount change and re-sync, each with its request type and GitHub outcome.

Both types require the **data-sync PAT** to carry the `manage_billing:copilot` scope. (This is separate from the Copilot CLI token used for the AI chat, which must be a fine-grained PAT with the **Copilot Requests** account permission.) All records live in `data/budget_requests.json`.

## Current-Month Switch

A top-bar toggle flips every dashboard between **All Time** and **Current Month**:

- Usage, AI credit and spend figures are filtered to the running billing cycle
- Budgets are fetched **live from the GitHub API** rather than the last sync, so consumed and remaining amounts are the real ones that decide how much allowance is left this month
- The backend forces live mode for `period=current_month` regardless of what the client requests, so the number can never be stale

## Analytics Dashboards

The dashboard is split into eight tabs.

| Tab | Contents |
|-----|----------|
| **Usage Metrics** | Active user trends (MAU/WAU/DAU), code productivity & acceptance rate, feature usage, language distribution, model & AI credits, IDE distribution, seat management, top active users |
| **AI Usage** | Uploaded AI-credit CSV: daily trend, model/org/cost-center breakdowns, per-user table with quota bars |
| **Usage Report** | Uploaded usage-report CSV: daily trend, product/SKU/org/cost-center breakdowns, per-user table |
| **Cost Centers** | Cost centers with members and resources, user → cost center mapping, downloadable and shareable HTML report |
| **Unassigned Users** | Copilot seat holders not in any active cost center, with bulk assignment |
| **Enterprise Teams** | Per-team Copilot adoption and cost, expandable member rosters, and seat holders no team covers |
| **Budgets** | All enterprise budgets by scope, with amount, **consumed**, **remaining** and usage %, live-refreshable from GitHub |
| **Requests** | Budget request review + approval history (admins only) |

## Enterprise Teams

[Enterprise Teams](https://docs.github.com/en/rest/enterprise-teams) group users at the enterprise level, independently of organizations, and can hold Copilot Business licenses directly — including users who belong to no organization at all.

**The join problem.** No Copilot dataset carries an enterprise-team field: seats, usage reports, legacy metrics and both CSV exports have organization and cost-center columns, but nothing that identifies a team. (GitHub denormalizes `cost_center_name` into the CSVs; it does not do the same for teams.) OctoFinance therefore syncs the team rosters itself and joins them against every other dataset **on the user login**.

- **Sync** — `GET /enterprises/{ent}/teams`, plus each team's `/memberships` and `/organizations`, stored as `data/enterprise_teams/{slug}_latest.json`. The file carries both the team list and a `member_index` (`login → [team_slug]`) so lookups do not have to rescan every roster. Runs as part of a full sync, or on its own via `POST /api/sync/dataset/enterprise_teams`
- **Dashboard tab** — per team: members, seats, members without a seat, active members, interactions, AI credit cost and estimated monthly seat cost. Expanding a team shows each member's seat status, organizations, interactions, active days, AI spend and last activity. A separate section lists **seat holders that no enterprise team covers** — the blind spot of team-based reporting
- **Cross-dashboard filter** — Usage Metrics, AI Usage and Usage Report all gained an **Enterprise Team** filter, including a **(No enterprise team)** option for users that belong to no team
- **Seat attribution** — where GitHub *does* report a team, it appears in `assigning_team` with `type: "enterprise" | "organization"`, so a seat granted through an enterprise team is distinguishable from an org-team seat

> **Team members can legitimately exceed matched seats.** Enterprise teams may contain unaffiliated users who belong to no organization, and those users never appear in any org's seat data. The dashboard reports them as *members without a seat* rather than silently dropping them.

### Filtering by team

The org-level usage report is pre-aggregated and has no user dimension, so it cannot be sliced by team. When a team filter is active the Usage Metrics dashboard is **recomputed from the user-level report** instead — daily trend, feature/model/IDE/language breakdowns are rebuilt from per-user records, DAU/WAU/MAU become distinct-user counts over trailing 1/7/28-day windows, KPIs are derived from the team's own seats, and AI credit detail comes from the per-user CSV rather than the model-aggregated cache.

### What is not available

GitHub's [enterprise-team model policy targeting](https://github.blog/changelog/2026-07-31-enterprise-teams-model-policy-targeting-in-public-preview/) (assigning *Optional* models to specific teams) is **UI-only**. A full scan of GitHub's published OpenAPI description contains no model-policy endpoint at any level, so OctoFinance cannot read or manage per-team model availability.

## Update Notifications

Every data sync — manual, startup auto-sync or cron — also kicks off a **release version check**.

| Aspect | Behaviour |
|--------|-----------|
| **How the version is resolved** | A single `GET https://github.com/satomic/OctoFinance/releases/latest`, which GitHub redirects to `/releases/tag/<version>`. The tag is read from the redirect target — no GitHub API call, no token, no rate limit |
| **Comparison** | The resolved tag is compared numerically against `APP_VERSION` (leading `v` ignored) |
| **UI** | When a newer release exists, the **Source Code** button in the status bar becomes a highlighted **New version vX.Y.Z** button linking straight to that release page. Shown to admins and to regular users in the self-service portal |
| **Non-blocking** | The check is fired as a detached asyncio task; the sync never waits for it and never fails because of it |
| **Timeout** | Hard ceiling of **30 seconds** for the whole check (connect + redirects). On timeout the task is cancelled and the state records the error |
| **Offline / air-gapped** | A failed or timed-out check simply leaves `latest_version: null` and `update_available: false`, so the button stays a plain Source Code link. Nothing is retried until the next sync |
| **State** | Held in memory only (`current_version`, `latest_version`, `update_available`, `release_url`, `checked_at`, `error`) and exposed on `/api/health` and `/api/auth/status` |

> **Network allowlist** — the only host this feature contacts is **`github.com`** (specifically `https://github.com/satomic/OctoFinance/releases/latest` and the `/releases/tag/*` redirect target). If your deployment restricts egress and you want update notifications, allow that host; otherwise the feature degrades silently and everything else keeps working.

## Multi-Organization Management

- Support for **multiple GitHub PATs** with label management
- **Auto-discovery** of all organizations and enterprises per PAT
- **Auto-detection** of Copilot plan type (Business $19/seat vs. Enterprise $39/seat)
- **Cross-org filtering** in dashboards with multi-select dropdowns
- **Enterprises without organizations** — some enterprises grant Copilot access purely via Enterprise Teams with zero organizations underneath. Each PAT has an **"Include Organizations"** toggle (default on); when disabled, organization discovery/sync is skipped for that PAT and enterprise-level Copilot data is synced instead (seats via `GET /enterprises/{ent}/copilot/billing/seats`, usage/user usage reports, and AI credit usage). This data is stored under a pseudo-org key so it flows through the existing dashboard aggregation unchanged — the Organizations list stays empty (as expected) while KPIs/charts remain fully populated. Since GitHub has no enterprise-wide billing overview endpoint, seat KPIs (active/inactive, plan type) are synthesized from the seats list

## Cost Center Report Sharing

- Per-cost-center HTML report, shareable via a tokenized public link (`/share/cc/{token}`) with no OctoFinance account required
- Each share is either **public** or **password-protected** (PBKDF2-hashed)
- Shares can be updated (change password / switch mode) or disabled at any time
- The shared page offers a Download button producing a standalone HTML file
- Share settings persist in `data/cc_shares.json`

## Real-Time Data Synchronization

- **Auto-sync on startup** (configurable)
- **Cron-based scheduling** (e.g., `*/30 * * * *` for every 30 minutes)
- **SSE streaming** of sync progress to the frontend
- **Per-organization** and **per-dataset** sync capability
- **Dual-write**: syncs to both the global data store and the per-session working directory
- **Incremental historical merge**: GitHub's usage-metrics and legacy-metrics endpoints always return a rolling window (e.g. the latest 28 days), so a naive overwrite could never show data older than that window even with daily syncs. `_latest.json` is merged day-by-day (or day+user, or date, depending on category) with the previously synced data — the newest sync always wins on overlapping days, while older days no longer covered by the API window are preserved
- **Single-file storage**: each category/org is stored as exactly one `_latest.json`, written via a temp file and atomic replace. Per-sync timestamped snapshots are no longer produced, and any left over from earlier versions are removed on startup, so `data/` no longer grows without bound

## Human-in-the-Loop Operations

- AI generates **recommendations** with estimated cost savings
- Recommendations stored in the **Action Panel** for admin review
- **Approve & Execute** or **Reject** workflow
- **Intelligent seat removal**: auto-detects org-level vs. team-level assignment and uses the correct API
- **Audit logging** for all executed operations

## AI Credit Analytics

- **Org-level AI credit** tracking via the GitHub Billing API (UBB)
- **Per-user AI usage** from CSV upload (GitHub UI AI Usage report export)
- **Per-model breakdown** (GPT-5.4, Claude Opus 4.7, etc.)
- **Quota tracking** with visual progress bars
- **Cost analysis** including gross/discount/net amounts

## Internationalization & Theming

- **8 languages** selected from a dropdown: English, 简体中文, 繁體中文, 日本語, 한국어, हिन्दी, Tiếng Việt, ไทย
- Initial language is **auto-detected from the browser** (`zh-Hant`/`tw`/`hk`/`mo` resolve to Traditional Chinese); missing keys fall back to English
- Each locale is a standalone file under `frontend/src/locales/`, all sharing the same key order
- **Dark and Light** theme toggle
- **UI state persistence** via localStorage (sidebar, dashboard sections, filters, period mode, session)

---

## API Reference

### Auth

| Endpoint | Method | Access | Description |
|----------|--------|--------|-------------|
| `/api/auth/status` | GET | public | Setup required, current user, admin flag, SSO availability, version |
| `/api/auth/setup` | POST | public | First-time local credential setup |
| `/api/auth/login` | POST | public | Login with username/password |
| `/api/auth/logout` | POST | any user | Clear session |
| `/api/auth/github/login` | GET | public | Redirect to GitHub OAuth consent |
| `/api/auth/github/callback` | GET | public | OAuth callback — exchange code, start session |
| `/api/auth/github/config` | GET/PUT | admin | Read/update OAuth App settings and admin allow-list |

### Personal ("me")

| Endpoint | Method | Access | Description |
|----------|--------|--------|-------------|
| `/api/me/dashboard` | GET | any user | Own seats, activity, AI credits, spend, budget, cost centers. Params: `period`, `date_from`, `date_to`, `live` |
| `/api/me/budget` | GET | any user | Live budget snapshot + current-month AI cost |
| `/api/me/cost-centers` | GET | any user | Selectable cost centers, flagged with current/inherited membership |

### Budget requests

| Endpoint | Method | Access | Description |
|----------|--------|--------|-------------|
| `/api/budget-requests` | GET | any user | Own requests; admins see all. Param: `status` |
| `/api/budget-requests` | POST | any user | Submit a request (`request_type`: `budget` \| `cost_center`) |
| `/api/budget-requests/review` | POST | admin | Approve (provisioning the real GitHub budget or cost center move) or reject |
| `/api/budget-requests/amount` | POST | admin | Change an approved amount and re-apply to GitHub |
| `/api/budget-requests/resync` | POST | admin | Retry applying an approved request to GitHub |
| `/api/budget-requests/audit` | GET | admin | Flat approval audit trail |
| `/api/budget-requests/{id}` | DELETE | owner/admin | Withdraw a pending request / delete any request |

### Chat & sessions

| Endpoint | Method | Access | Description |
|----------|--------|--------|-------------|
| `/api/chat` | POST | admin | AI chat with SSE streaming response. Body: `message`, `session_id`, `model` (empty = Auto) |
| `/api/chat/simple` | POST | admin | AI chat, wait for the complete response |
| `/api/chat/models` | GET | admin | Models available to the Copilot account, fetched live from the SDK |
| `/api/sessions` | GET/POST | admin | List / create chat sessions |
| `/api/sessions/{id}` | GET/PUT/DELETE | admin | Get / rename / delete a session |
| `/api/sessions/{id}/messages` | GET | admin | Messages for a session |

### Data

| Endpoint | Method | Access | Description |
|----------|--------|--------|-------------|
| `/api/health` | GET | admin | Health check — users, orgs, AI engine status, version |
| `/api/data/orgs` | GET | admin | All discovered organizations, grouped by enterprise |
| `/api/data/overview` | GET | admin | Global overview (seats, costs, waste) |
| `/api/data/seats/{org}` | GET | admin | Seat data for an organization |
| `/api/data/billing/{org}` | GET | admin | Billing data for an organization |
| `/api/data/dashboard` | GET | admin | Aggregated usage-metrics dashboard. Params: `orgs`, `enterprise_team` |
| `/api/data/csv-dashboard` | GET | admin | Aggregated CSV dashboard (AI usage + usage report). Params include `enterprise_team` |
| `/api/data/csv-info` | GET | admin | Uploaded CSV coverage info |
| `/api/data/upload-csv` | POST | admin | Upload an AI usage / usage report CSV (type auto-detected) |
| `/api/data/budgets-dashboard` | GET | admin | Budgets with consumed/remaining. Params: `enterprise`, `scope`, `search`, `live`, `period` |
| `/api/data/cost-center-dashboard` | GET | admin | Cost centers, members, user mapping |
| `/api/data/cost-center-report` | GET | admin | Per-cost-center report payload |
| `/api/data/cost-center-unassigned-users` | GET | admin | Seat holders with no active cost center |
| `/api/data/cost-center-unassigned-users/assign` | POST | admin | Bulk-assign users to a cost center |
| `/api/data/cost-center-shares` | GET | admin | List share links |
| `/api/data/cost-center-share` | POST/DELETE | admin | Create/update or disable a share link |
| `/api/data/enterprise-teams-dashboard` | GET | admin | Enterprise teams joined with seats, usage and AI spend. Params: `enterprise`, `teams`, `search` |

### Sync, actions & settings

| Endpoint | Method | Access | Description |
|----------|--------|--------|-------------|
| `/api/sync` | POST | admin | Trigger a full data sync (background) |
| `/api/sync/{org}` | POST | admin | Sync one organization |
| `/api/sync/dataset/{dataset}` | POST | admin | Sync a single dataset (`budgets`, `cost_centers`, `enterprise_teams`) |
| `/api/sync/status` | GET | admin | Current sync status |
| `/api/sync-stream` | GET | admin | SSE stream of sync progress |
| `/api/actions/pending` | GET | admin | Pending AI recommendations |
| `/api/actions/approve` | POST | admin | Approve a recommendation |
| `/api/actions/execute` | POST | admin | Execute a recommendation |
| `/api/actions/reject` | POST | admin | Reject a recommendation |
| `/api/pats` | GET/POST | admin | List / add PATs |
| `/api/pats/{id}` | PUT/DELETE | admin | Update / remove a PAT |
| `/api/settings` | GET/PUT | admin | App settings (auto-sync, cron schedule) |

### Public share pages (no OctoFinance account)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/share/cc/{token}` | GET | Shared cost center report page |
| `/share/cc/{token}/verify` | POST | Submit the access password |
| `/share/cc/{token}/download` | GET | Download the report as standalone HTML |

## Configuration

PATs and settings are managed through the web UI (**Settings** modal):

- **Add/Remove PATs** — manage multiple GitHub PATs with labels and an "Include Organizations" toggle
- **Auto Sync on Startup** — toggle automatic data sync when the backend starts
- **Sync Cron Schedule** — set periodic sync (e.g. `*/30 * * * *`)
- **GitHub SSO** — OAuth Client ID/Secret, callback URL, admin allow-list, and whether any GitHub user may sign in

### Data files

| File | Contents |
|------|----------|
| `data/auth.json` | Local admin credentials (PBKDF2 hash + salt) |
| `data/oauth.json` | GitHub OAuth App config + admin allow-list |
| `data/auth_sessions.json` | Active login sessions |
| `data/auth_oauth_states.json` | Short-lived OAuth CSRF states |
| `data/pats.json` | PATs and app settings |
| `data/budget_requests.json` | Budget requests + approval history |
| `data/cc_shares.json` | Cost center share links |
| `data/audit_log.json` | Executed operations |
| `data/{category}/{org}_latest.json` | Synced GitHub data (seats, billing, usage, usage_users, metrics, ai_credits, cost_centers, budgets, enterprise) |
| `data/enterprise_teams/{slug}_latest.json` | Enterprise team rosters + `login → teams` index used to join teams onto every other dataset |
| `data/ai_usage_csv/`, `data/usage_report_csv/` | Uploaded CSV files |
| `data/sessions/{id}/` | Per-chat-session working directories |
