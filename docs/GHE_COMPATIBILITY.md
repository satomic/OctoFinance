# OctoFinance — GHE.com (Data Residency) Compatibility Report

> Applies to **v1.5.0**. Tested on 2026-09-28.

## Summary

GitHub Enterprise Cloud with data residency (`<subdomain>.ghe.com`) serves the **same REST API** as github.com. Every endpoint OctoFinance calls today behaves the same way, with the same paths, API versions (`2022-11-28` and `2026-03-10`), OAuth scopes, request bodies, response schemas and business-rule validation. The only differences are:

1. **The hosts are different.** The API lives at `https://api.<subdomain>.ghe.com`. Signed download links point at `copilot-reports.<subdomain>.ghe.com` and a regional Azure blob host.
2. **The org-level budgets endpoint fails.** `/organizations/{org}/settings/billing/budgets` returned an error on ghe.com (details under [Differences Found](#differences-found)). OctoFinance only uses this endpoint as a fallback when no enterprise is configured, which never happens on ghe.com because every tenant is an enterprise.

**Conclusion:** ghe.com support needed no new API client logic, only a configurable host instead of a hardcoded one: per-PAT API base URLs, OAuth URLs, profile links and the Copilot CLI host. This is now implemented and verified end to end; see [Implementation](#implementation) and [End-to-End Test Results](#end-to-end-test-results).

## Test Method

| Item | Detail |
|---|---|
| ghe.com tenant | A test enterprise on `<subdomain>.ghe.com` with 1 visible org and 12 Copilot seats (`plan_type: business`) |
| ghe.com token | Classic PAT with `admin:enterprise`, `admin:org`, `copilot`, `repo`, `user` and more. It did **not** carry `manage_billing:copilot`; every Copilot endpoint still accepted it through `admin:org` / `admin:enterprise`. |
| Baseline | The same probes, run read-only against a github.com enterprise with a classic PAT |
| Scope | Every endpoint in `backend/app/services/github_api.py` plus the direct calls in `backend/app/tools/cost_center_tools.py` and `backend/app/tools/enterprise_team_tools.py` |
| Writes | Performed on ghe.com only. Every object created (cost centers, budgets, enterprise team) was deleted afterwards. |
| Schema check | Recursive key-set diff of the JSON bodies, and of the downloaded NDJSON records for the usage-metrics reports |

## Hosts

| Purpose | github.com | ghe.com |
|---|---|---|
| Web UI | `https://github.com` | `https://<subdomain>.ghe.com` |
| REST API | `https://api.github.com` | `https://api.<subdomain>.ghe.com` |
| Copilot usage-metrics report downloads | `https://copilot-reports.github.com/...` | `https://copilot-reports.<subdomain>.ghe.com/...` |
| Billing report CSV downloads | Azure blob (signed URL) | Regional Azure blob, e.g. `mbprodsdc01.blob.core.windows.net` (signed URL) |
| User HTML URL | `https://github.com/{login}` | `https://<subdomain>.ghe.com/{login}` |
| Avatars | `https://avatars.githubusercontent.com/u/{id}` | `https://<subdomain>.ghe.com/avatars/u/{id}?token=...` (tokenized) |
| OAuth authorize / token | `https://github.com/login/oauth/...` | `https://<subdomain>.ghe.com/login/oauth/...` (authorize endpoint confirmed, returns 302) |

Both kinds of signed download link work **without** an `Authorization` header on ghe.com, which matches how `_download_and_merge_reports` and `download_billing_report_csv` already fetch them.

## Endpoint Compatibility Matrix

Legend: ✅ same behavior and schema · ⚠️ difference · ➖ same "unsupported" result on both platforms

### Discovery and organizations

| Endpoint | ghe.com | github.com | Result |
|---|---|---|---|
| `GET /user` | 200 | 200 | ✅ |
| `GET /user/orgs` | 200 | 200 | ✅ |
| `GET /orgs/{org}` | 200 | 200 | ✅ |
| `GET /orgs/{org}/members` | 200 | 200 | ✅ |
| `GET /orgs/{org}/teams` | 200 | 200 | ✅ |
| `GET /user/enterprise-memberships` | 404 | 404 | ➖ Auto-discovery doesn't work on either platform; the manual enterprise slug in PAT settings is required on both |
| `GET /enterprises/{e}/organizations` | 404 | 404 | ➖ |

### Copilot seats and billing

| Endpoint | ghe.com | github.com | Result |
|---|---|---|---|
| `GET /orgs/{org}/copilot/billing` | 200 | 200 | ✅ Identical key set |
| `GET /orgs/{org}/copilot/billing/seats` | 200 | 200 | ✅ |
| `GET /enterprises/{e}/copilot/billing/seats` | 200 | 200 | ✅ `assigning_team` only appears for team-assigned seats on both platforms. The ghe.com sample had org-assigned seats only. |
| `POST/DELETE /orgs/{org}/copilot/billing/selected_users` | not tested | — | Not tested because it changes paid seats. Same path and version as the other Copilot endpoints, so expected to be compatible. |

### Copilot usage metrics

| Endpoint | ghe.com | github.com | Result |
|---|---|---|---|
| `GET /orgs/{org}/copilot/metrics` (legacy) | 404 | 404 | ➖ The legacy API is gone on both platforms |
| `GET /enterprises/{e}/copilot/metrics` (legacy) | 404 | 404 | ➖ |
| `GET /orgs/{org}/copilot/metrics/reports/organization-28-day/latest` | 200 | 403 in baseline¹ | ✅ |
| `GET /orgs/{org}/copilot/metrics/reports/users-28-day/latest` | 200 | 403 in baseline¹ | ✅ |
| `GET /orgs/{org}/copilot/metrics/reports/organization-1-day?day=` | 200 | 403 in baseline¹ | ✅ |
| `GET /orgs/{org}/copilot/metrics/reports/users-1-day?day=` | 204 (no data that day) | 403 in baseline¹ | ✅ |
| `GET /enterprises/{e}/copilot/metrics/reports/enterprise-28-day/latest` | 200 | 200 | ✅ Same metadata keys (`download_links`, `report_start_day`, `report_end_day`) and the same NDJSON record schema |
| `GET /enterprises/{e}/copilot/metrics/reports/users-28-day/latest` | 200 | 200 | ✅ |
| `GET /enterprises/{e}/copilot/metrics/reports/enterprise-1-day?day=` | 200 | 200 | ✅ |
| `GET /enterprises/{e}/copilot/metrics/reports/users-1-day?day=` | 200 (empty body) | 200 | ✅ |

¹ The baseline org has the usage-metrics policy disabled. That is an org setting, not a platform difference.

The NDJSON key diffs covered only optional breakdown objects (`totals_by_cli`, `totals_by_plugin`, `totals_by_custom_agent`, `pull_requests.median_minutes_to_merge`, and so on). These appear only when the underlying activity exists. The ghe.com tenant simply has less activity. No field changed name or type.

### Billing usage, AI credits and CSV reports

| Endpoint | ghe.com | github.com | Result |
|---|---|---|---|
| `GET /organizations/{org}/settings/billing/ai_credit/usage` | 200 | 200 | ✅ |
| `GET /enterprises/{e}/settings/billing/ai_credit/usage` | 200 | 200 | ✅ Identical key set. `pricePerUnit` is 0.01 on both. |
| `GET /enterprises/{e}/settings/billing/usage` | 200 | 200 | ✅ List prices match github.com (Copilot Business $19, GHEC $21) |
| `GET /enterprises/{e}/settings/billing/usage/summary` | 200 | 200 | ✅ |
| `GET /enterprises/{e}/settings/billing/premium_request/usage` | 200 | 200 | ✅ |
| `GET /enterprises/{e}/settings/billing/reports` | 200 | 200 | ✅ |
| `POST /enterprises/{e}/settings/billing/reports` (`ai_credit`, `detailed`, `summarized`) | 202 → `completed` | — | ✅ Each export finished in under 2 minutes |
| `GET /enterprises/{e}/settings/billing/reports/{id}` | 200 | — | ✅ Keys: `id, report_type, start_date, end_date, status, created_at, actor, download_urls` |
| CSV download (signed URL, no auth) | 200 | 200 | ✅ See the note below |

The CSV headers are **identical** to the github.com files OctoFinance already ingests:

- `ai_credit`: `date, username, product, sku, model, quantity, unit_type, applied_cost_per_quantity, gross_amount, discount_amount, net_amount, total_monthly_quota, organization, repository, cost_center_name, aic_quantity, aic_gross_amount, input, output, cache_read, cache_write`
- `detailed`: `date, product, sku, quantity, unit_type, applied_cost_per_quantity, gross_amount, discount_amount, net_amount, username, organization, repository, workflow_path, cost_center_name`
- `summarized`: the same as `detailed` without `username` and `workflow_path`

The files start with a UTF-8 BOM and quote every field. `csv_store.py` already strips the BOM (`utf-8-sig` / `lstrip("﻿")`).

### Cost centers (API version `2026-03-10`)

Every write was round-tripped on ghe.com.

| Operation | ghe.com | Result |
|---|---|---|
| `GET .../cost-centers` (`state=active` / `state=deleted`) | 200 | ✅ Deleted cost centers stay in the unfiltered list with `state: "deleted"`, the same as on github.com |
| `POST .../cost-centers` with `{name, ai_credit_pool_enabled}` | 200 | ✅ |
| `GET .../cost-centers/{id}` | 200 | ✅ Also returns `ai_credit_pool_state {target_amount, current_amount}` |
| `PATCH .../cost-centers/{id}` (rename and toggle the pool) | 200 | ✅ |
| `POST .../cost-centers/{id}/resource` (users, organizations) | 200 | ✅ |
| `DELETE .../cost-centers/{id}/resource` | 200 | ✅ |
| `DELETE .../cost-centers/{id}` | 200 | ✅ Returns `costCenterState: "CostCenterArchived"` |

### Budgets (API version `2026-03-10`)

| Operation | ghe.com | github.com | Result |
|---|---|---|---|
| `GET /enterprises/{e}/settings/billing/budgets` | 200 | 200 | ✅ Same envelope (`budgets`, `has_next_page`, `total_count`) |
| Create, get, update and delete, `budget_scope: user` | 200 | — | ✅ |
| Create, get, update and delete, `budget_scope: multi_user_customer` (universal) | 200 | — | ✅ |
| Create, get, update and delete, `budget_scope: cost_center` | 200 | — | ✅ `budget_entity_name` accepts the cost center ID and is echoed back as the name |
| Create, get, update and delete, `budget_scope: multi_user_cost_center` | 200 | — | ✅ |
| Create, get, update and delete, `budget_scope: enterprise` | 200 | — | ✅ |
| Create, get, update and delete, `budget_scope: organization` (on the enterprise endpoint) | 200 | — | ✅ |
| `GET /organizations/{org}/settings/billing/budgets` | **400** `Unable to get budgets.` | 200 | ⚠️ |
| `POST /organizations/{org}/settings/billing/budgets` | **503** `Unable to verify budget uniqueness.` | — | ⚠️ |

ghe.com enforces the same validation rules OctoFinance already follows:

- `user` and `multi_user_customer` budgets must keep `prevent_further_usage: true` (400 otherwise).
- A `multi_user_cost_center` budget requires a cost center that contains **only users** (400 if it contains an org or repo).

### Enterprise teams

Every write was round-tripped on ghe.com.

| Operation | ghe.com | github.com | Result |
|---|---|---|---|
| `GET /enterprises/{e}/teams` | 200 | 200 | ✅ Identical key set. Slugs carry the `ent:` prefix on both platforms. |
| `POST /enterprises/{e}/teams` | 201 | — | ✅ |
| `GET` / `PATCH` / `DELETE /enterprises/{e}/teams/{slug}` | 200 / 200 / 204 | — | ✅ |
| `POST .../memberships/add`, `GET .../memberships`, `POST .../memberships/remove` | 200 | — | ✅ |
| `POST .../organizations/add`, `GET .../organizations`, `POST .../organizations/remove` | 200 / 200 / 204 | — | ✅ |

## Differences Found

| # | Difference | Impact on OctoFinance | Action |
|---|---|---|---|
| 1 | API, report-download and web hosts are per tenant | Was blocking: `config.github_api_base` was a single global value (`https://api.github.com`) | Fixed: each PAT carries its own host |
| 2 | `/organizations/{org}/settings/billing/budgets` returns 400 on GET and 503 on POST | Low. `budget_provisioner` only falls back to org budgets when no enterprise is configured, and every ghe.com tenant is an enterprise. Enterprise-endpoint budgets with `budget_scope: organization` work. | Configure an enterprise slug on ghe.com PATs so the enterprise endpoint is used |
| 3 | Avatar URLs are tokenized (`/avatars/u/{id}?token=...`). The `https://<host>/{login}.png` fallback redirects to the login page. | Cosmetic. Stored avatar URLs may expire, and the frontend fallback in `OrgSelector.tsx` produces a broken image. | The API's `avatar_url` is used as-is and refreshed on each sync. It loaded correctly in the e2e run. |

## Implementation

ghe.com support is implemented as follows. The API client code is unchanged; only host selection was added.

| Area | Change |
|---|---|
| Host model | New `backend/app/services/github_host.py` normalizes input to `github.com` or `<subdomain>.ghe.com` and derives the API and web base URLs. Any other host (including GitHub Enterprise Server) is rejected. |
| PATs | Each PAT stores a `host` (`pat_manager.py`, `routers/pats.py`). The Settings form has a **Host** field. Pasting an enterprise URL such as `https://acme.ghe.com/enterprises/acme` into **Ent Slug** extracts the slug and, when Host is blank, the host. PATs saved before this change default to github.com. |
| API routing | `api_manager.py` builds each `GitHubAPI` with its PAT's API base and tags discovered orgs and enterprises with their host. `GitHubAPI.host` / `GitHubAPI.web_base` and `api_manager.web_base_for_org()` / `web_base_for_enterprise()` expose it. The global `config.github_api_base` is gone. |
| Profile links | Fallback `html_url` values in `routers/data.py` and `services/data_collector.py`, and all links in the cost center report (`report_generator.py`, used by the ZIP export and the share page), use the owning host |
| OAuth SSO | `oauth.json` / Settings → GitHub SSO has a **GitHub host** field (env fallback `GITHUB_OAUTH_HOST`). Authorize, token and user URLs are derived from it. |
| Copilot CLI | When chat falls back to a configured PAT on a ghe.com host, the CLI is spawned with `COPILOT_GH_HOST=<host>` unless `COPILOT_GH_HOST` / `GH_HOST` is already set. Classic PATs are skipped for chat because the CLI rejects them. With `COPILOT_GITHUB_TOKEN`, set `COPILOT_GH_HOST` yourself. |
| UI | Host badge on non-github.com PATs, host-aware org avatar fallback, and new strings in all 8 locales |
| Tests | `backend/tests/test_github_host.py` covers host normalization, per-PAT routing, pseudo-org host lookup, OAuth URLs, Copilot CLI options and report links |

**Known limits**

- One deployment can mix github.com and ghe.com PATs. However, cached data is keyed by org or enterprise slug only, so a slug that exists on both hosts shares one data file.
- The AI engine uses a single Copilot CLI host per process.
- Deployments behind a firewall need outbound HTTPS to `api.<subdomain>.ghe.com`, `copilot-reports.<subdomain>.ghe.com`, `<subdomain>.ghe.com` and `*.blob.core.windows.net`.

## End-to-End Test Results

Run on 2026-09-28 against the ghe.com test tenant. The app ran from an isolated copy with an empty data directory, driven through the web UI with Playwright where possible.

| Scenario | How | Result |
|---|---|---|
| Add PAT | Settings UI, Host left blank, Ent Slug = the full enterprise URL | ✅ Host `<subdomain>.ghe.com` and slug derived. Authenticated against `api.<subdomain>.ghe.com`. 1 org discovered. |
| Initial sync | Automatic after adding the PAT | ✅ Every request went to `api.<subdomain>.ghe.com` / `copilot-reports.<subdomain>.ghe.com`. The only warnings were the legacy metrics 404 and the `state=archived` side finding. |
| Dashboards | UI: all 8 tabs | ✅ Seats, usage metrics, AI usage (input/output/cache), usage report, cost centers, unassigned users, enterprise teams and budgets rendered with no console errors. Every profile link pointed to `https://<subdomain>.ghe.com/...`. |
| Fetch CSV | UI button | ✅ `ai_credit` (33 rows) and `detailed` (418 rows) exports created, polled, downloaded from the regional blob host and ingested |
| Sync Data | UI button | ✅ |
| AI chat, reads | UI chat, CLI authenticated to github.com (mixed mode) | ✅ Live tools queried the ghe.com tenant |
| AI chat, writes | UI chat | ✅ Created a cost center, added a user, created and deleted a `cost_center` budget, deleted the cost center, all on ghe.com |
| Budget request | Requester session for a tenant user → admin approve → admin amount change | ✅ Created a real `user` budget (POST), then updated it (PATCH). `/api/me/budget` read it back live. |
| Cost center report ZIP | `GET /api/data/cost-center-report` | ✅ Member links pointed to `https://<subdomain>.ghe.com/<login>` |
| OAuth SSO | UI settings: invalid host, then a ghe.com host with a dummy OAuth App | ✅ Invalid host rejected with a clear message. `/api/auth/github/login` redirected to `https://<subdomain>.ghe.com/login/oauth/authorize`, which ghe.com accepted (it redirects to the tenant's sign-in page). |
| Cleanup | ghe.com API | ✅ No test cost centers, budgets or teams left on the tenant |

**Not covered end to end**

- **Full SSO sign-in.** It needs an OAuth App registered on the tenant.
- **Chat with the Copilot CLI authenticated to the ghe.com host.** It needs a fine-grained PAT or a CLI `/login` on the tenant, because the test tenant only provided a classic PAT. The `COPILOT_GH_HOST` wiring is covered by unit tests.
- **Seat add/remove**, which incurs cost.

## Unchanged (Verified Compatible)

- Every path, method, query parameter and request body in `github_api.py`, `cost_center_tools.py`, `budget_tools.py`, `budget_provisioner.py` and `enterprise_team_tools.py`
- The `X-GitHub-Api-Version` values `2022-11-28` and `2026-03-10`
- Classic PAT scopes (`admin:enterprise` / `read:enterprise` for enterprise teams, `manage_billing:enterprise` for billing)
- The NDJSON usage-metrics report parsing and the billing CSV parsing, BOM included
- Pagination parameters (`per_page`, `page`) and response envelopes (`costCenters`, `budgets` + `has_next_page`, `usage_report_exports`, `usageItems`)
- Error bodies (`message`, `documentation_url`, `status`), so `GitHubAPI._error_detail` needs no change

## Side Finding (Both Platforms)

`GitHubAPI.get_enterprise_cost_centers` requests `state=active` and then `state=archived`. Both github.com and ghe.com reject `archived` with **400** (`Invalid state parameter. Must be 'active' or 'deleted'.`). The loop treats the 400 as "stop" and records a failure, so deleted cost centers are never synced. The call should use `state=deleted` instead. This is unrelated to ghe.com support.
