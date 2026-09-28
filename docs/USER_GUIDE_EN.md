# OctoFinance Complete User Guide

Applies to **v1.5.0**. [简体中文](USER_GUIDE_CN.md)

OctoFinance brings GitHub Copilot seats, adoption, AI credits, billing and budgets into one workspace, with an AI assistant for analysis and operational tasks. This guide is organized around the three user roles.

All screenshots use the **English interface and light theme**. Both language editions reuse the same images. A few older screenshots still show an earlier release, so tab counts and control positions may differ slightly from v1.5.0. Screenshots of role views and of tables that would otherwise contain real accounts use illustrative logins such as `alex-demo`; they are not actual users, budgets or grants.

**Contents**

1. [Administrators: Setup, Analysis and Governance](#admin)
2. [Cost Center Owners: Manage Your Assigned Centers](#owner)
3. [Regular Users: Personal Usage and Requests](#user)

| Capability | Administrator | Cost Center Owner | Regular User |
|------------|---------------|-------------------|--------------|
| Global dashboards, AI chat, sync and CSV import | Yes, within configured PAT permissions | No | No |
| Personal usage and requests | Uses the administrator workspace | Available through personal view | Yes |
| Center usage and member details | Yes | Assigned centers only | Own membership and related summaries only |
| Change AI Credit Cap | Yes, subject to GitHub restrictions | Read-only | No |
| Set member individual budgets directly | Yes | Eligible members only, with a verified enabled cap | Submit a request instead |
| Grant ownership, review requests, configure PAT/SSO | Yes | No | No |

> **Keep the units separate.** A seat grants access. AI credits measure model consumption. A budget controls monetary spending. The CSV fields `input`, `output`, `cache_read` and `cache_write` are additional usage measures, not interchangeable with credits or dollars. Displayed data depends on permissions, the last sync and imported report coverage; it is not necessarily a live final invoice.

<a id="admin"></a>
## Chapter 1: Administrators

### 1.1 Identity and First Use

Administrators include the local administrator account, GitHub accounts in the SSO administrator allow-list, and owners of configured PATs. Other GitHub users normally enter the personal portal; an ownership grant adds access to specific cost center views.

Recommended setup order:

1. Open the deployment URL. Development commonly uses `http://localhost:5173`; use the published domain in production.
2. Create the local administrator account on first access and store the credentials securely.
3. Add a data-sync PAT in **Settings**, then verify discovered organizations and enterprises.
4. Run **Sync Data** and inspect **Console** for results.
5. Run **Fetch CSV** or use **Upload CSV** for detailed billing data.
6. Configure GitHub SSO and test access with a regular user.
7. Assign cost center owners and verify their role selector and data scope.

See [README](../README.md) for installation and deployment. Regular users do not need to add PATs or install Copilot CLI.

### 1.2 PATs and Enterprise Scope

Open **Settings > GitHub Personal Access Tokens**.

![English light-theme Settings panel with the PAT list, the Add PAT form and sync settings](../images/settings_pat_en.png)

A saved token is shown masked (`ghp_***lOsO`), with its GitHub owner and the number of discovered organizations. The same panel also holds Sync Settings, CSV Fetch and GitHub SSO further down.

| Field | Purpose |
|-------|---------|
| Label | A recognizable token name. The saved label is displayed separately from the GitHub account owner |
| Token | The data-sync PAT. Never include it in screenshots, chat or shared documents |
| Host | Leave blank for github.com. For GHE.com (GitHub Enterprise Cloud with data residency) enter the tenant host, such as `acme.ghe.com`; the token is then used against `api.acme.ghe.com` |
| Ent Slug | The enterprise identifier from a URL such as `github.com/enterprises/example-enterprise`; specify it when automatic discovery is incomplete. You can paste the whole URL (for example `https://acme.ghe.com/enterprises/acme`): the slug is extracted and, when Host is blank, the host is taken from the URL |
| Include Organizations | Whether to scan organizations. Disable when the enterprise uses Enterprise Teams and organization scanning is not needed |

**Add PAT** validates and discovers the account scope; data sync runs in the background. Multiple PATs can cover different scopes. Discovering an organization does not prove that the token can read all its billing data or perform every operation.

**Organization scanning and enterprise seat collection are independent.** Enabling Include Organizations must not suppress enterprise seat sync. Enterprise seats already represented in organization data are excluded from the supplementary enterprise view on read, preventing double counting. An orgless enterprise can legitimately have an empty Organizations list and still have Copilot seats.

**GHE.com (data residency).** Each PAT belongs to one host, shown as a badge next to the PAT when it is not github.com. All data sync, CSV fetches, cost center, budget and Enterprise Teams operations for that PAT go to its host, and profile links in dashboards and cost center reports point to the same host. github.com and GHE.com PATs can be configured side by side, but an organization or enterprise slug that exists on both hosts would share one data file, so keep slugs distinct. Firewalled deployments must allow outbound HTTPS to `api.<tenant>.ghe.com`, `copilot-reports.<tenant>.ghe.com`, `<tenant>.ghe.com` and `*.blob.core.windows.net`. See [GHE.com compatibility](GHE_COMPATIBILITY.md).

Changing the organization toggle reruns discovery and sync. Removing a PAT affects future access but does not cancel GitHub seats or revoke the token on GitHub.

| Permission or credential | Main use and limits |
|--------------------------|---------------------|
| `read:org` and applicable organization administration permissions | Discovery, organization seats and billing, subject to account role and endpoint requirements |
| `copilot` or applicable Copilot permissions | Copilot usage data |
| `manage_billing:copilot` | Copilot budget writes and related cost center operations, with the required management role |
| `manage_billing:enterprise` | Automatic detailed billing CSV requests by an enterprise administrator or billing manager |
| Classic PAT with `read:enterprise` | Enterprise Teams reads |
| Classic PAT with `admin:enterprise` | Enterprise Teams creation and changes |
| Separate Copilot CLI authentication | AI chat; configuring a data-sync PAT alone does not guarantee chat authentication |

Enterprise Teams endpoints reject fine-grained PATs and GitHub App tokens. AI chat follows the Copilot CLI/SDK authentication requirements. For a GHE.com tenant, the chat token must be issued on that tenant. OctoFinance detects which configured GHE.com host (from your PATs or the SSO host) the token belongs to and points the CLI at it automatically, including when the GHE.com PAT is added after startup. The token is only checked against those configured hosts. To choose the host yourself, set `COPILOT_GH_HOST=<tenant>.ghe.com` (or `GH_HOST`), which always wins. Classic PATs are never used for chat because the CLI rejects them. When using a token, check the personal account, active Copilot subscription and Copilot Requests permission requirements in the [CLI authentication guide](https://docs.github.com/en/copilot/how-tos/copilot-cli/set-up-copilot-cli/authenticate-copilot-cli).

### 1.3 GitHub SSO

1. Create an OAuth App in GitHub under **Settings > Developer settings > OAuth Apps**. For GHE.com, create it on your tenant (`https://<tenant>.ghe.com`) and enter that host in the **GitHub host** field; github.com OAuth Apps cannot sign in GHE.com users.
2. Set Homepage URL to the actual OctoFinance browsing URL.
3. Set Callback URL to `https://your-domain/api/auth/github/callback`.
4. Enter Client ID and Client Secret in OctoFinance **GitHub SSO** settings and verify the callback URL.
5. Configure administrator GitHub logins and **Allow any GitHub user to sign in**.
6. Test administrator and regular-user access in separate browser sessions.

![GitHub Register a new OAuth app form with the homepage and callback URL fields highlighted](../images/github-oauth.png)

Restricting regular-user sign-in can also prevent cost center owners from entering their portal. SSO does not automatically grant Copilot seats or cost center ownership.

The browsing origin and callback origin must match. Cookies are not shared between `localhost`, `127.0.0.1` and a production domain. A reverse proxy must forward the original host and protocol correctly; multiple workers must share the session store.

### 1.4 Navigation, Theme and Time Range

| Entry | Purpose |
|-------|---------|
| Chat / Dashboard | AI conversation or eight dashboard tabs |
| All Time / Current Month | Collected history or the current billing cycle |
| Settings | PATs, scheduling, CSV fetch parameters and SSO |
| Console | Tool activity, sync progress and failures |
| Sync Data / Fetch CSV / Upload CSV | API sync, automatic report retrieval and manual report import |
| User menu | Identity, language, theme and sign-out |
| Overview / Organizations | Seat and cost summaries and discovered organization scope |
| Sessions / Pending Actions | Conversation management and AI recommendation review |

Eight languages are supported. Theme, language, filters and some collapsed states persist in the browser. Expand sections using their headings, scroll wide tables horizontally and resize the sidebar as needed.

**Current Month does not make every dataset live.** CSV charts filter already imported records. Budget views and personal budgets support live reads, but check source labels and errors. Seats and memberships are snapshots from the latest sync; a date filter does not reconstruct historical access assignments.

### 1.5 Sync and CSV Maintenance

Sync Settings and CSV Fetch live in the same Settings panel shown in [1.2](#12-pats-and-enterprise-scope).

| Source | Contents |
|--------|----------|
| API cache | Seats, billing summaries, Copilot usage, cost centers, budgets and Enterprise Teams |
| AI Usage CSV | Per-user, per-model credits, amounts, quota and input/output/cache fields |
| Usage Report CSV | Detailed billed usage by product, SKU, user, organization and cost center |

| Trigger | API datasets | CSV reports |
|---------|--------------|-------------|
| Sync Data | Updated | Not fetched |
| Auto Sync on Startup | Updated | Fetched afterward |
| Sync Cron Schedule | Updated | Fetched afterward |
| Fetch CSV | No full API sync | Requested, downloaded and imported |
| Upload CSV | No full API sync | Selected file imported |

**Manual sync:** click Sync Data and inspect Console. One failed dataset does not mean the entire run failed. Identify the affected organization, endpoint and response, correct access, then retry.

**Scheduling:** enable startup sync or choose a preset/custom cron schedule. Scheduled ticks are skipped while a previous run remains active. CSV failures are logged separately and do not mean every API dataset is unavailable.

**Automatic reports:** Fetch CSV requests the latest 31 days of `ai_credit` and `detailed` reports. GitHub generation generally takes minutes and can take longer. Polling and timeout settings control the wait; Console shows progress. Reloading the page lets you observe an active job rather than requiring another export.

**Manual import:** export complete detailed reports from GitHub and choose Upload CSV. Type detection is automatic. Verify coverage dates and the matching tab afterward. Summarized exports cannot replace the per-user detail needed by these dashboards.

> **Replacement is atomic by date.** If a new export covers a day, all stored rows for that day are replaced. Dates not covered remain unchanged. Never upload a slice containing only one user or organization: it could remove other rows for those days. Reimporting the same complete data does not add duplicate consumption.

All Time means collected history, not every record GitHub has ever held. Missing columns in older exports are not invented; later imports preserve the expanded column set.

### 1.6 AI Chat and Recommendations

![English light-theme AI conversation showing a cost and ROI analysis](../images/chat.png)

This existing screenshot illustrates the conversation and sidebar layout; available models and figures depend on the current environment.

1. Create a session and select Auto or an available model.
2. Specify the enterprise or organization, time period and question.
3. Check tool calls, source dates and numerical evidence.
4. Before writes, verify targets, impact and required approval.
5. Review recorded recommendations in Pending Actions and approve execution or reject them.

```text
Compare Copilot utilization across organizations using the latest synced data.
Find users inactive for 30 days. Create recommendations only; do not remove seats.
Which models consumed the most AI credits this month? Include the source period.
List cost centers and budgets in example-enterprise without making changes.
Explain shared cost center budgets versus per-member budgets before creating one.
```

Sessions can be created, switched, renamed and deleted. Send submits, Stop interrupts a response, and Clear clears the conversation. Sessions retain multi-turn context. Model selection affects subsequent messages, not business permissions.

Tools cover seats, usage, billing, cost centers, budgets and Enterprise Teams. Some management operations are available through AI tools rather than dedicated forms. **Confirmation or approval can invoke real APIs.** Not every write necessarily creates the same pending-action entry. Confirm business authorization before removing seats, members, budgets or centers; audit logs are not a substitute for review.

### 1.7 Usage Metrics

![English light-theme Usage Metrics dashboard with seat KPIs and active-user trends](../images/usage_metrics_en.png)

This view uses API usage and seat data to answer whether Copilot is being used, which features are adopted and where seats may be idle.

| Section | Interpretation |
|---------|----------------|
| KPIs | Seats, active seats, utilization, estimated monthly cost and waste |
| Active User Trends | DAU, WAU, MAU, Chat and Agent adoption |
| Code Productivity | Generation and acceptance activity, lines of code and acceptance rate |
| Feature / Language / IDE / Model | Adoption across workflows and environments |
| Seat Management | Accounts, plans, teams, assignment dates, last activity and pending cancellation |
| Top Active Users | Highly active users within the collected scope |

Filter by organization, enterprise team, user and date. Teams are joined by GitHub login against synced rosters. Some filtered aggregates are rebuilt from user-level reports and need not exactly match unfiltered organization summaries.

Seat cost and waste are estimates, not final invoices. Inactivity does not automatically justify removal: check onboarding, leave, responsibilities and assignment method. Code volume and acceptance rate should not be used alone to assess individual performance.

### 1.8 AI Usage and Input/Output/Cache

This tab uses detailed AI credit CSV data. Check coverage first, then filter organizations, cost centers, teams, users and dates. Review credits, cost, daily trends and model/organization breakdowns. User tables include quota, active days and Auto model share. Sortable headings support comparisons.

![English light-theme AI Usage tab with credit KPIs and the daily credit trend](../images/ai_usage_en.png)

| Field | Display | Caution |
|-------|---------|---------|
| `input` | Input usage | Preserves the reported value, without credit conversion |
| `output` | Output usage | Not the same as accepted lines of code |
| `cache_read` | Cache reads | Not a direct monetary savings figure |
| `cache_write` | Cache writes | Shown separately from reads |

![English light-theme input, output and cache totals with daily trends](../images/ai_usage_tokens.png)

These metrics have totals, trends and model/user detail. Missing, blank or invalid values display **Not reported**; a reported zero displays `0`. Mixed old/new exports sum reported values only, so coverage may be smaller than for credits and cost. Missing does not mean zero consumption. Existing stored CSVs containing the columns need no reimport.

### 1.9 Usage Report

Usage Report focuses on products and SKUs, whereas AI Usage focuses on models. It shows daily amounts, product/SKU breakdowns, organization/center totals and user-level billed usage. Use the product, SKU, organization, center, team, user and date filters available on the tab.

![English light-theme Usage Report tab with gross, net and discount totals and the product and SKU breakdown](../images/usage_report_en.png)

| Amount | Meaning |
|--------|---------|
| Gross | Original reported amount |
| Discount | Reported discount |
| Net | Amount after discounts |

Reconcile using the same period, scope and gross/net basis. AI Usage gross, Usage Report net, estimated seat costs and consumed budgets may overlap; do not simply add them into a total invoice.

### 1.10 Cost Centers, Cap and Ownership

![English light-theme cost center list with resource tags, AI Credit Cap toggles and the user to cost center mapping](../images/cost_centers_en.png)

The cost center table carries the Cap toggle and the Share action per center. The mapping table below shows how each user reaches a center, either directly or through an organization or team resource.

Select the enterprise and centers, filter active/archived state and expand members and resource sources. Administrators can also use AI tools to create or rename centers and manage resources. New centers default to an enabled included usage cap, subject to GitHub's response.

**AI Credit Cap** is GitHub's included usage cap. When enabled, the center is constrained by credits included with its members' licenses rather than continuing into the shared enterprise pool. It is not an arbitrary dollar budget. Only administrators can change it. GitHub resource-type restrictions can disable the control. The UI updates optimistically, then rolls back with an error if GitHub rejects the change; Console records progress.

**Assign an owner:**

1. Expand an active center and locate the member.
2. Enable **Cost center owner** for that member.
3. Ask them to sign in with the matching GitHub account and select the center in the role dropdown.
4. Verify access is limited to the authorized scope.

Multiple owners and multiple centers per owner are supported. Revoking ownership does not remove membership or a Copilot seat. Center membership, ownership and administrator access are distinct.

**Download Report** produces standalone HTML. **Share** creates a public or password-protected link that can be updated or disabled. Recipients need not sign in and do not gain ownership. Handle links as financial/personnel data; disabling a link does not revoke files already downloaded.

![English light-theme Share Report dialog with the share link, public and password-protected access options](../images/cc_shares.png)

### 1.11 Unassigned Users

Candidates are collected Copilot seat holders who are not in an active cost center, not the full enterprise directory and not users without seats. Archived/deleted centers do not count as an active assignment.

![English light-theme Unassigned Users tab with seat holders that belong to no active cost center](../images/unassigned_users_en.png)

1. Select an enterprise, search users and verify sync coverage.
2. Select accounts and a target center.
3. Review the confirmation and perform the bulk assignment.
4. Inspect individual outcomes and refresh.

Direct enterprise-team seats can participate even without organization membership. An empty list can mean everyone is assigned or data is missing. Assignment changes real GitHub resources.

### 1.12 Enterprise Teams

Review team members, assigned organizations, matched seats, active users, usage and estimated cost. Expand members for detail; a separate section identifies seat holders outside every team. Dedicated Sync refreshes rosters used by Enterprise Team and No enterprise team filters elsewhere.

![English light-theme Enterprise Teams tab with coverage KPIs, the team table and seat holders outside every team](../images/enterprise_teams_en.png)

GitHub usage does not carry a native enterprise-team dimension; OctoFinance joins by login. Users can belong to multiple teams, so adding team totals can overcount unique users or usage. Membership counts larger than matched seat counts are not necessarily errors.

Creation, updates and member/organization assignment are available through administrator AI tools with write permissions. Team model availability policy management is not currently supported.

### 1.13 Budgets

Filter enterprise budgets by scope and search. Review amount, consumed, remaining, percentage and hard/soft limit; use live refresh where needed and inspect source status.

![English light-theme Budgets tab with budget KPIs, the scope chart and the budget table](../images/budgets_en.png)

| Scope | Meaning |
|-------|---------|
| Universal / `multi_user_customer` | A common personal budget rule for all users, not one shared total |
| Individual / `user` | A specific user's budget |
| `cost_center` | One shared center budget |
| `multi_user_cost_center` | The same personal budget rule for each member of the center |
| Enterprise, organization, repository and others | The scope returned by GitHub |

AI tools support creation, updates, deletion and batch individual budgets; individual budgets can also be provisioned through request approvals. Specify scope, target, amount and hard limit. Updating an existing budget does not directly change its scope; evaluate overlapping rules before changing scope through new budgets.

Copilot budgets use monthly cycles and dollar amounts. A hard limit blocks further applicable use at the limit; a soft limit is not equivalent to blocking. Personal budgets, included credits and center Cap settings do not replace one another.

### 1.14 Requests: Review and Provisioning

Review contains budget and cost center requests. History records submissions, decisions, amount changes and retries.

![English light-theme Requests review tab with request KPIs, the approval controls and the request table](../images/requests_review_en.png)

1. Filter pending requests and verify requester, type, justification and target.
2. Adjust the approved budget amount if appropriate; for a center move, check both old and new centers.
3. Enter a review comment and set the budget hard-limit option.
4. Check **Apply the change to GitHub on approve**.
5. Approve or reject, then inspect the GitHub result.

| Result | Follow-up |
|--------|-----------|
| Created / Updated / Applied | A successful result was returned; verify the scope |
| Partially applied | Inspect successful and failed steps separately |
| Failed | Correct access or target errors and retry sync |
| Not synced / Skipped | Approval may exist only locally, without a GitHub write |

**Approved is not proof that GitHub changed.** Disabled write-back or provisioning failure can leave an approved local record. Direct user reassignment can move the user out of the previous center. Organization/team-inherited membership cannot simply be changed as a direct user assignment.

### 1.15 Console, Troubleshooting and Routine Checks

Console shows timestamped tool activity and sync progress. AI startup does not necessarily prevent viewing cached dashboards. Sync also triggers a release check; the source-code entry can indicate a newer version.

![English light-theme Console panel with timestamped INFO, WARN and ERROR sync lines](../images/console_en.png)

Each line carries a timestamp, a source tag and a level. An `[ERROR]` line names the affected organization, the HTTP status and the reason, which is normally enough to identify the missing permission or policy.

| Symptom | Check |
|---------|-------|
| Empty seats | PAT, enterprise slug, organization/enterprise endpoint permissions and logs |
| Empty AI Usage | Detailed CSV availability, selected dates and username matching |
| Metrics not reported | Missing, blank or invalid original CSV values |
| Empty Enterprise Teams | Classic PAT, `read:enterprise` and roster sync |
| Budget unchanged | GitHub result, target entity, error and retry status |
| SSO returns to login | Origin, callback, proxy headers and shared sessions |
| AI never ready | CLI installation, separate authentication, subscription and model access |
| Current-month charts lag | Latest CSV date; a live budget does not refresh reports |
| Owner cannot find a center | Login, ownership grant, center state and sign-in policy |

Regularly check sync, unassigned users, model/team cost trends and pending requests before acting on idle-seat recommendations. Keep business approval for real writes. Never share PATs, OAuth secrets or session cookies in troubleshooting messages.

<a id="owner"></a>
## Chapter 2: Cost Center Owners

### 2.1 Authorization and Role Switching

An administrator grants ownership to a center member. Joining a center does not automatically make a user its owner or an enterprise administrator.

![English light-theme role selector with the Platform Engineering cost center owner view selected](../images/owner_role_view_en.png)

Use the top role dropdown to move between personal and owner views. Not reported in this example means additional metrics are unavailable, not that credit pool consumption is zero.

1. Sign in with the authorized GitHub account.
2. Use the top role selector, which defaults to personal view and lists owned centers.
3. Select a center and verify its enterprise, especially when names repeat.
4. Return to personal view for your own usage or personal requests.

Roles refresh periodically and when the window regains focus. Reload after a new grant if necessary. The backend rejects access after revocation even if an older page remains open.

### 2.2 Current Credits and Historical Usage

![English light-theme owner overview with read-only Cap, credit pool and usage](../images/cost_center_owner_usage.png)

| Information | Interpretation |
|-------------|----------------|
| AI Credit Cap | Read-only status; administrators alone can change it |
| Consumed / Included allowance / Remaining | Current-cycle credit pool consumption, allowance and balance |
| Live / Cached / Unavailable | Source and availability; unknown is not zero |
| AI credits / AI cost | Imported CSV consumption and amount for the selected period |
| Billed cost | Detailed billing net amount, potentially different from AI cost's gross basis |
| Members | Current membership count, not a guarantee of report records for everyone |

Selecting historical usage does not turn the current credit pool into a historical snapshot. Even with All Time selected, the pool describes current-cycle constraints. The screenshot uses illustrative data.

### 2.3 Model, Member and Input/Output/Cache Analysis

Confirm center and period, inspect CSV coverage, locate daily spikes, then compare models and members. Ranking charts support credits or amounts and can show only leading entries when many exist; use tables for full detail.

Input, Output & Cache provides four totals and trends, with model and member detail. Not reported means missing, while 0 means a reported zero. Missing fields in an older export do not prove inactivity. Cache volume is not a direct savings amount.

Only authorized center data is accessible. A billing-scope ambiguity warning means some records cannot be attributed reliably. Ask an administrator to reconcile scope instead of treating the displayed result as a complete bill.

### 2.4 Member Individual Budgets

| Condition | Behavior |
|-----------|----------|
| Cap verified enabled, budgets readable, membership and budget match clear | Set/edit allowed |
| Cap disabled | Read-only to avoid expanding spending without the center cap |
| Cap unknown or live verification failed | Read-only until verification is restored |
| Budgets unavailable or multiple candidate budgets | Read-only; administrator investigation required |
| Member left or ownership revoked | Write rejected |

1. Open the center's **Settings**.
2. Review the member's amount, consumed, remaining and hard limit.
3. Choose **Set budget** or **Edit budget**.
4. Enter a monthly dollar amount and select the hard-limit behavior.
5. Verify user and center, then choose **Confirm and save**.
6. Check the result and refreshed values.

![English light-theme member individual budget confirmation dialog](../images/cost_center_owner_budget.png)

The screenshot stops before saving. Saving performs a real GitHub individual-budget write and rechecks ownership, membership and Cap. An enabled editor when opened does not guarantee that saving later will still be allowed.

This does not add shared credit to the center or guarantee that the user can consume the entire amount. Other limits may apply first. Follow the amount validation; do not use negative values or zero as an undocumented disable operation.

### 2.5 Boundaries and Troubleshooting

Owners cannot configure PAT/SSO, perform global sync/imports, use administrator AI tools, approve global requests, grant ownership, change Cap or manage unauthorized centers. Report sharing and ownership are independent.

| Problem | Action |
|---------|--------|
| No role selector | Verify the grant and signed-in account |
| Only some centers appear | Only authorized centers are listed, not every membership |
| Members visible but budgets disabled | Check Cap, verification, budget availability and uniqueness |
| Missing member metrics | Inspect report coverage and fields; do not infer inactivity |
| Save returns an authorization error | Refresh ownership, membership and Cap; contact the administrator |

Ask administrators to change center allowances, resources or fix sync failures. Submit your own budget or membership requests through personal view as described in Chapter 3.

<a id="user"></a>
## Chapter 3: Regular Users

### 3.1 Sign-In and Personal Portal

Choose **Sign in with GitHub** using your own account. Non-admins enter a personal portal with **My Usage** and requests. All Time / Current Month is available at the top; the user menu contains language, theme and sign-out.

Personal data is matched by GitHub login against administrator-collected records. You do not need to supply a PAT. Ask the administrator to investigate account renames, missing sync or report coverage. Center membership does not grant access to colleagues' usage.

### 3.2 Reading My Usage

![English light-theme personal portal showing a personal budget, cost center membership and input/output/cache metrics](../images/user_portal_en.png)

This example shows the sections with available data. Use My Usage and Budget Requests in the top bar to switch between consumption and requests.

| Section | Contents |
|---------|----------|
| KPIs | Budget, consumed, remaining, seats and estimated monthly seat cost, credits, cost, interactions and acceptance |
| My GitHub Budget | Effective individual or universal budget with consumption source |
| My Cost Centers | Membership, direct/inherited source, Cap and related summaries |
| AI Credit Quota | Reported plan allowance and usage percentage |
| My Copilot Seats | Plan, team, assignment date and last activity |
| Activity / Feature | Daily interactions, acceptance and feature adoption |
| AI Credit Usage / Models | Your daily credits, costs and models |
| Input, Output & Cache | Four totals, trends and model detail |
| Billed Usage | Personal SKU-level billing |

Some sections only appear when data exists. An empty view does not prove you lack Copilot access; records may be unavailable for the period or not yet collected. Acceptance and code volume are usage observations, not stand-alone performance evaluations.

### 3.3 Budgets, Quotas and Membership

A budget is a spending control, not payment or prepaid credit. Select Current Month when reviewing current remaining funds, refresh where offered, and check whether consumption is from GitHub or a usage estimate. Changing the period does not fetch missing CSV data.

Do not add individual and universal amounts into a personal total. The page identifies the effective source. Included credits, CSV quota, dollar budgets and center Cap are different constraints. One progress bar below its limit does not override the others.

Direct membership can be changed by request. Organization/team-inherited membership needs administrator changes to the parent resource, not a workaround through the personal form. Viewing a center summary does not reveal other members' usage.

### 3.4 Input, Output and Cache

The four fields aggregate only your records; supported model-table headings can be sorted. Not reported means no valid value, while 0 is an actual reported zero. If old exports lack columns, an administrator can import newer complete detailed reports; no personal reconfiguration is required.

Output volume is not completed task count, and cache reads are not a direct discount. Review credits, costs and remaining budget together when estimating your needs.

### 3.5 Requesting a Personal Budget

![English light-theme budget request form with a monthly target amount and a previous request's GitHub outcome](../images/user_budget_request_en.png)

The new request in the screenshot has not been submitted. History entries are illustrative.

1. Open requests and choose **Budget**.
2. Enter the desired total monthly personal budget and an organization if needed.
3. Explain the work, why the current limit is insufficient and expected demand.
4. Review and submit, then follow **My Request History**.

The amount is the requested budget level, not an automatic increment. To move from 50 to 100, clearly request a target of 100 rather than assuming a request for 50 is added. Budgets follow a monthly cycle, not arbitrary start/end dates.

Submission creates a request only. An administrator can approve a different amount, reject it or encounter provisioning failure. Do not submit repeated identical requests instead of checking status.

### 3.6 Requesting a Cost Center Change

![English light-theme cost center request showing current membership, destination and the move preview](../images/user_cost_center_request_en.png)

1. Choose the **Cost Center** request type.
2. Verify your current center and membership source.
3. Choose the destination, or **Unassigned** to leave a direct assignment.
4. Review the old-to-new preview, provide a reason and submit.
5. Wait for review and inspect the GitHub result.

Direct assignment normally moves you out of the previous center rather than creating another direct membership. Inherited membership cannot be changed as a direct user assignment. A move can affect cost attribution and limits, but it neither grants ownership nor automatically increases your personal budget.

### 3.7 Tracking and Confirming Changes

| State | Meaning |
|-------|---------|
| Pending | Awaiting review; withdraw using the available control |
| Approved | Approved locally; still inspect GitHub status |
| Rejected | Read the comment and submit a revised justification if appropriate |
| Failed / Not synced | GitHub change is not confirmed; ask an administrator to investigate or retry |
| Created / Updated / Applied | GitHub returned success; refresh budget or membership to verify |

Personal history contains your own requests only. Approved is not the same as provisioned, and an approval notice is not an invoice. Use the latest record and source information after subsequent amount changes.

### 3.8 Common Problems

| Symptom | Action |
|---------|--------|
| Sign-in denied | Ask whether regular-user SSO is allowed |
| No global dashboards or AI chat | Expected role restriction |
| No role selector | No owner grant; membership alone is insufficient |
| Copilot works but personal usage is empty | Verify sync, CSV dates and login matching |
| Only part of this month is shown | Wait for an administrator to retrieve newer reports |
| Usage blocked before budget is exhausted | Check Cap, included allowance, hard limits and GitHub policies |
| Approved request has no visible effect | Inspect provisioning status and ask for refresh/retry |

When reporting a problem, provide your login, time, selected period, request reference and error. Do not send PATs, OAuth secrets, cookies or unredacted billing exports.

Further reading: [Chinese complete guide](USER_GUIDE_CN.md), [features and API](FEATURES.md), [architecture](ARCHITECTURE.md), and [security](SECURITY.md).