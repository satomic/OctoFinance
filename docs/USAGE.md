# OctoFinance Usage Guide

> Applies to **v1.1.3**.

OctoFinance has two experiences, chosen automatically by role:

| You are… | You get… |
|----------|----------|
| **Administrator** | The full platform — AI chat, all dashboards, PAT/SSO settings, approvals |
| **Regular GitHub user** | A personal portal — your own usage, your budget and cost centers, budget requests |

---

## First-Time Setup (administrator)

1. Open the app in your browser (default `http://localhost:5173` for dev, or port 8000 in production)
2. On first visit the **Create Account** screen appears — choose a username and password
3. Credentials are stored locally (PBKDF2-SHA256) and used for subsequent logins
4. Open **Settings → PAT Manager** and add an org-admin PAT — organizations and enterprises are discovered automatically and the first sync starts on its own

A language dropdown is available on the login page; the initial language is guessed from your browser.

## Enabling GitHub SSO (optional but recommended)

Letting engineers check their own usage removes a lot of admin busywork.

1. On GitHub: **Settings → Developer settings → OAuth Apps → New OAuth App**
   - **Homepage URL** — your OctoFinance URL, e.g. `http://localhost:8000`
   - **Authorization callback URL** — `<your OctoFinance URL>/api/auth/github/callback`
2. In OctoFinance: **Settings → GitHub SSO (OAuth App)** → paste the **Client ID** and **Client Secret** → Save
   (Or set `GITHUB_OAUTH_CLIENT_ID` / `GITHUB_OAUTH_CLIENT_SECRET` as environment variables.)
3. A **Sign in with GitHub** button now appears on the login page

**Who becomes an administrator**

- The local username/password account
- Any GitHub login listed under **Admin GitHub logins**
- The owner of any configured PAT (always an admin)

Everyone else is a regular user. Turn **Allow any GitHub user to sign in** off to restrict login to admins and PAT owners only.

> **Important:** the session cookie is stored on the callback origin. Browse OctoFinance on exactly the host in the callback URL — opening `http://localhost:8000` while the callback points at `https://octofinance.example.com` cannot work. Leaving **Callback URL** blank auto-detects the browsing origin.

---

## Regular User Portal

After signing in with GitHub, a non-admin sees a two-tab portal.

### My Usage

| Section | What it shows |
|---------|---------------|
| **KPI row** | Budget limit, budget used, budget left, your seats, seat cost/month, AI credits used and their cost, interactions, acceptance rate |
| **My GitHub Budget** | The budget that applies to you — individual, or the universal default — with a consumption bar. Consumption comes live from the GitHub API where available |
| **My Cost Centers** | Every cost center you belong to, how you joined (User / Org / Team), whether the AI credit pool is on, and that cost center's budget and consumption |
| **AI Credit Quota** | Your plan allowance and how much of it you've used |
| **My Copilot Seats** | Each org where you hold a seat: plan, team, assignment date, last activity, seat cost |
| **My Copilot Activity** | Daily interactions vs. accepted suggestions |
| **My AI Credit Usage** | Daily credit consumption and cost, plus a per-model breakdown |
| **By Feature** | Which Copilot features you actually use |
| **My Billed Usage** | Per-SKU quantity, gross and net amounts |

### Budget Requests

Pick a request type at the top of the form.

**Budget** — ask for a personal AI-credit allowance.

1. Enter the amount and optionally an org, plus a justification
2. Click **Submit Request**

GitHub Copilot budgets run on a single monthly billing cycle, so there is no period to pick — the amount is your monthly allowance. The budget is personal, so cost centers are not part of this form.

**Cost Center** — ask to be moved to a different cost center.

1. The dropdown is pre-selected with your current cost center
2. Choose another one, or **Unassigned** to leave without joining another
3. A preview shows the move (`current → requested`) before you submit

GitHub assigns each user to at most one cost center, so picking a new one moves you out of the current one. If you belong to a cost center because your whole organization or team is attached to it, that membership is listed as **Inherited** and cannot be changed for you individually.

**Tracking** — both types appear in **My Request History** with status (pending / approved / rejected) and a **GitHub Budget** column telling you whether the change actually landed on GitHub. Pending requests can be withdrawn.

---

## Administrator Interface

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│  StatusBar                                                                       │
│  [OctoFinance] ● user · 3 orgs · ● AI Ready                                      │
│   [All Time|Current Month] [Chat|Dashboard] [Settings] [Console] [🌐] [Dark]     │
│   [CSV↑] [Sync] [Source] [Issue] [user chip] [Logout]                            │
├────────────────┬─────────────────────────────────────────────────────────────────┤
│   Sidebar      │              Main Content Area                                  │
│   (resizable)  │   ┌─────────────────────────────────┐                           │
│  ▼ Overview    │   │  Chat View  OR  Dashboard View  │                           │
│  ▼ Orgs        │   └─────────────────────────────────┘                           │
│  ▼ Sessions    │   ┌─────────────────────────────────┐                           │
│  ▼ Actions     │   │  Console Panel (toggleable)      │                           │
│                │   └─────────────────────────────────┘                           │
└────────────────┴─────────────────────────────────────────────────────────────────┘
```

### StatusBar

| Element | Description |
|---------|-------------|
| **Health indicators** | Username + org count (backend connected), AI status (Ready/Starting) |
| **All Time / Current Month** | Global period switch — see below |
| **Chat / Dashboard** | Toggle between the two main views |
| **Settings** | PAT management, sync configuration, GitHub SSO |
| **Console** | Toggle the bottom console panel |
| **Language dropdown** | English, 简体中文, 繁體中文, 日本語, 한국어, हिन्दी, Tiếng Việt, ไทย |
| **Dark / Light** | Switch colour theme |
| **Upload CSV** | Upload an AI Usage or Usage Report CSV (type auto-detected) |
| **Sync Data** | Manually trigger a full data sync |
| **Source Code / Report an Issue** | Links to the GitHub repository |
| **User chip** | Signed-in account, with an Admin badge |
| **Logout** | End session |

### The Current-Month switch

Budgets and quotas reset with the billing cycle, so "how much is left this month?" is usually the question that matters.

- **All Time** — everything collected so far
- **Current Month** — every dashboard narrows to the running billing cycle, and budgets are fetched **live from the GitHub API** rather than the last sync

A banner shows the active cycle (e.g. `2026-08-01 ~ 2026-08-31`) with a **LIVE** badge and a manual refresh button.

### Sidebar Panels

Click any header to collapse/expand; drag the edge to resize.

- **Overview** — total seats, active vs. inactive, utilization, monthly cost and waste
- **Organizations** — every discovered org with plan type and seat counts, grouped by enterprise
- **Sessions** — create, switch, rename and delete AI chat sessions (each keeps its own context)
- **Pending Actions** — AI recommendations awaiting review, with **Approve & Execute** / **Reject**

> **Warning:** Approve & Execute performs real operations (e.g. removing Copilot seats). Review carefully.

---

## Chat View

A natural-language interface to the AI FinOps assistant. Four quick prompts appear on an empty conversation: **Overview**, **Inactive Users**, **Cost Optimization**, **ROI Analysis**.

### Conversation examples

```
Show me the current Copilot usage and costs across all organizations
Which users haven't used Copilot in over 30 days? How much money is wasted?
How is Copilot utilization in the contoso organization? Who uses it most?
Show me AI credit usage — which models cost the most?
List all inactive users and create suggestions to remove their seats
List the cost centers in my enterprise and who belongs to each
Create a $200 individual AI credit budget for user alice
Compare Copilot utilization across organizations — which has the most waste?
```

Multi-turn context is preserved within a session:

```
You: Show me inactive users in contoso
AI:  Found 5 inactive users... Should I create removal recommendations?
You: Yes, create them
AI:  Recommendations created, estimated savings of $285/month
You: Actually, skip user alice — she's on parental leave
```

### Tool indicators

Tool calls appear inline as tags — spinning while running, green check when complete. You'll commonly see `get_all_seats`, `find_inactive_users`, `get_cost_overview`, `calculate_roi`, `get_usage_report`, `list_cost_centers`, `get_all_budgets`, `record_recommendation`.

### Controls

| Control | Action |
|---------|--------|
| **Send** (Enter) | Send message |
| **Model** | Pick the model for the next message. The list is fetched live from the Copilot SDK, so it only shows models your account can actually use. **Auto** (the default) lets Copilot choose; switching back to Auto resets a session that had an explicit model |
| **Clear** | Clear conversation history |
| **Stop** | Abort the response in progress |

---

## Dashboard View

Eight tabs, each with its own filters. Sections are collapsible.

> **Enterprise Team filter** — Usage Metrics, AI Usage and Usage Report each have an **Enterprise Team** dropdown next to the Organizations filter, listing every synced team plus a **(No enterprise team)** option for users that belong to none. Since GitHub does not tag any Copilot data with a team, the filter matches on the user login using the synced team rosters; on Usage Metrics the charts are then recomputed from user-level records so they stay accurate. Run a sync (or `Sync` on the Enterprise Teams tab) first to populate the list.

### 1. Usage Metrics

| Section | Visualizations |
|---------|---------------|
| **Active User Trends** | MAU / WAU / DAU area chart, Chat & Agent overlay |
| **Code Productivity** | LOC suggested/accepted trend, acceptance rate |
| **Feature Usage** | Per-feature interactions, code generation, acceptance |
| **Language Distribution** | Horizontal bar chart + code completions by language |
| **Model & AI Credits** | Model usage pie + per-model cost/quantity table |
| **IDE Distribution** | IDE interaction bar chart + detail table |
| **Seat Management** | Seat table with status, team, activity, plan badges |
| **Top Active Users** | Ranked table of the most active users |

### 2. AI Usage · 3. Usage Report

Built from uploaded CSVs. Daily trend, model / product / SKU / org / cost-center breakdowns, and a per-user table with quota bars. Filter by org, cost center, product, SKU and date range.

### 4. Cost Centers

Cost centers with members and resources, plus a user → cost center mapping.

- **Download Report** — standalone HTML report for a cost center
- **Share** — publish a tokenized link (`/share/cc/{token}`) that needs no OctoFinance account. Choose **Public** or **Password protected**; update or disable it at any time

### 5. Unassigned Users

Copilot seat holders who belong to no active cost center. Select users, pick a target cost center, and assign them in bulk after a confirmation step.

### 6. Enterprise Teams

Enterprise-level teams and how they actually use Copilot. The **Sync** button refreshes just this dataset.

- **KPI cards** — teams, unique members, members with/without a seat, seat holders outside any team, seat coverage %, monthly seat cost and AI credit cost
- **Teams table** — per team: assigned organizations, members, seats, members without a seat, active members, interactions, AI cost and estimated seat cost. Expand a row to see each member's seat status, organizations, interactions, active days, AI spend and last activity
- **Seat Holders Outside Enterprise Teams** — users holding a Copilot seat that no team covers, so team-based reporting does not silently miss them

> A team's member count can legitimately exceed the seats matched to it: enterprise teams may include unaffiliated users who belong to no organization, and those users never appear in org seat data.
>
> Enterprise team endpoints require a **classic** PAT (`read:enterprise`; `admin:enterprise` for writes) — fine-grained and GitHub App tokens are rejected by GitHub.

### 7. Budgets

All enterprise budgets by scope (enterprise / universal / individual user / cost center / org / repo), showing amount, **used**, **remaining**, usage %, hard-vs-soft limit and alerting. In Current Month mode the numbers come live from GitHub — a **Live from GitHub** badge and a **Refresh live** button confirm it.

### 8. Requests

Two sub-tabs:

- **Review** — pending and historical requests of both types. A **Type** column distinguishes Budget from Cost Center, and **Details** shows either the monthly amount or the `current → requested` move. For budget requests the approved amount is editable inline. Two switches control the write-back:
  - *Apply the change to GitHub on approve* (default on) — untick to record an approval without touching GitHub
  - *Hard limit* (default on, budgets only) — block usage once the budget is exhausted
  Approved requests show a badge (Created / Updated / Applied / Partially applied / Failed / Not synced). Failures show the error and offer a **⟳** retry.
- **History** — a flat, newest-first audit trail of every submission, approval, rejection, amount change and re-sync, with who did it and the GitHub outcome.

> Approving writes to GitHub for real — either a `budget_scope: "user"` AI-credit budget, or a cost center assignment. The PAT needs the **`manage_billing:copilot`** scope, otherwise the approval is recorded but flagged **GitHub sync failed**.

---

## PAT Settings

Open **Settings** in the StatusBar.

### Add a PAT

1. Enter a label (e.g. "Production PAT")
2. Paste your GitHub Personal Access Token
3. Optionally set an **Ent Slug** (required for cost center management — find it in `github.com/enterprises/YOUR-SLUG`)
4. Leave **Include Organizations** ticked unless this enterprise has no organizations and grants Copilot via Enterprise Teams
5. Click **Add PAT** — the user, organizations and Copilot plans are discovered automatically

### Required PAT permissions

These are the scopes for the **data-sync PAT** you add here — the token that reads seats, billing, usage and budgets from the GitHub API.

| Scope | Purpose |
|-------|---------|
| `read:org` | Discover organizations |
| `admin:org` | Read Copilot billing and seats |
| `copilot` | Access Copilot usage metrics |
| `manage_billing:copilot` | AI credit usage, cost centers, and budget writes |
| `read:enterprise` | Enterprise teams (reads). `admin:enterprise` is required to create/modify teams |

> **Enterprise teams need a classic PAT.** GitHub rejects fine-grained and GitHub App tokens on the `/enterprises/{ent}/teams` endpoints, so the Enterprise Teams tab and its filters stay empty unless the data-sync PAT is a classic token with `read:enterprise`.

> **This is not the same token that powers the AI chat.** The Copilot CLI / SDK authenticates separately via the `COPILOT_GITHUB_TOKEN` environment variable (or an interactive `copilot` login), and that one must be a **fine-grained PAT** (`github_pat_…`) owned by a **personal account** with an active Copilot subscription and the **Copilot Requests: Read** account permission. Classic PATs (`ghp_…`) are rejected by Copilot CLI. See [Authenticating GitHub Copilot CLI](https://docs.github.com/en/copilot/how-tos/copilot-cli/set-up-copilot-cli/authenticate-copilot-cli).

### Sync configuration

- **Auto Sync on Startup** — sync automatically when the backend starts
- **Sync Cron Schedule** — presets (30min, 1h, 6h, 24h, Off) or a custom cron expression

> Every sync also checks GitHub for a newer OctoFinance release. If one exists, the **Source Code** button in the top bar turns into a highlighted **New version vX.Y.Z** button that links to that release. The check is detached from the sync and gives up after **30 seconds**, so an offline deployment is unaffected — it only needs outbound access to `github.com` to work.

### GitHub SSO

Client ID, Client Secret, callback URL, admin allow-list, and whether any GitHub user may sign in. See "Enabling GitHub SSO" above.

---

## Console Panel

Toggle via **Console**. Shows tool execution logs with timestamps and real-time sync progress (SSE). Auto-opens when a sync begins.

---

## AI Usage CSV Upload

GitHub exposes per-user AI credit data only through a CSV export, not the API.

1. GitHub.com → Organization/Enterprise Settings → Billing → export the usage report as CSV
2. Click **Upload CSV** in the StatusBar and pick the file
3. The type (AI Usage vs. Usage Report) is auto-detected and the data appears in the matching dashboard tab

Uploads are incremental — duplicate rows are ignored.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| GitHub authorized you but you land back on the login page | Browse OctoFinance on exactly the host in the OAuth callback URL — the cookie is stored on the callback origin. Leave **Callback URL** blank to auto-detect |
| Behind a reverse proxy, SSO or cookies misbehave | Start uvicorn with `--proxy-headers --forwarded-allow-ips="*"` so scheme/host are detected and cookies are marked `Secure` on HTTPS |
| `Session cookie presented but not found` in the log | Multiple workers are not sharing the same `data/` directory |
| Budget approval shows **GitHub sync failed** | The data-sync PAT lacks `manage_billing:copilot`, or no enterprise/org is reachable. Fix the PAT and hit the **⟳** retry |
| AI chat never becomes ready / `AI Starting...` forever | The Copilot CLI token is missing or the wrong type. It must be a fine-grained PAT with **Copilot Requests: Read**, owned by a personal account with an active Copilot subscription — classic `ghp_…` tokens are not supported. Dashboards and sync are unaffected |
| Budgets look stale | Switch to **Current Month** (always live) or press **Refresh live** on the Budgets tab |

---

## UI Tips

| Feature | How |
|---------|-----|
| Resize sidebar | Drag the divider between sidebar and main content |
| Collapse a panel or section | Click its header |
| Switch view | Chat / Dashboard in the StatusBar |
| Send a message | Press Enter |
| Persistence | Theme, language, period mode, sidebar width, filters and panel states are saved in your browser |
