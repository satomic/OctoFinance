# OctoFinance — Responsible AI & Security

> Applies to **v1.2.0**.

## Responsible AI (RAI) Notes

### Human-in-the-Loop Design

OctoFinance implements a strict human-in-the-loop pattern for all destructive or financially material operations:

1. **AI recommends, human decides** — the AI agent can identify inactive users and calculate potential savings, but it cannot remove seats autonomously. All seat removals go through **recommendation → review → approval**.

2. **Explicit confirmation** — recommendations are stored in the Action Panel showing affected users, organization and estimated savings. An administrator must click "Approve & Execute" or "Reject".

3. **Budget changes are administrator-gated** — a regular user can only *request* budget. Creating or updating a real GitHub budget requires an administrator to approve it, and the approved amount is editable before it is applied. Administrators can also record an approval without writing to GitHub.

4. **Audit trail** — executed operations are logged in `data/audit_log.json`. Budget decisions carry their own append-only history in `data/budget_requests.json` (who, when, amount, comment, and the GitHub sync outcome), surfaced in the **Approval History** tab.

### Data Privacy

- **No PII collection** — the platform accesses GitHub profile information (username, avatar) and Copilot usage metrics available through the GitHub API. GitHub SSO requests only the `read:user user:email` scopes and stores just the login, display name, avatar URL and numeric ID in the session.
- **Local data storage** — all data is stored locally as JSON under `data/`. Nothing is sent to third parties beyond the GitHub API and the Copilot SDK.
- **Least-privilege visibility** — regular users can only ever see their own data. Scoping is enforced server-side by the role middleware, not by hiding UI elements.
- **PAT security** — PATs live in `data/pats.json` and are masked in the UI (last 4 characters only). The OAuth client secret in `data/oauth.json` is likewise never returned in full by the API.
- **Session security** — httpOnly cookies with `SameSite=Lax`, automatically marked `Secure` when the request is served over HTTPS. Local passwords are hashed with PBKDF2-SHA256 (100,000 iterations) and verified in constant time.

### Transparency

- **Tool execution visibility** — the UI shows in real time which tools are being called and their results.
- **Data source attribution** — the personal dashboard states whether consumption came from the GitHub API (live) or from usage data, and the Budgets tab badges live data explicitly.
- **Honest write-back status** — an approved budget request always shows whether the amount actually reached GitHub (Created / Updated / Failed / Not synced). Failures surface the API error rather than silently appearing successful.
- **Reasoning display** — the agent's tool calls and progress can be observed in the console panel.

### Limitations & Responsible Use

- **Scope of authority** — the agent operates within the permissions of the configured PATs. Budget writes additionally require `manage_billing:copilot`.
- **Rate limiting** — GitHub API rate limits apply; errors are handled gracefully and reported.
- **Data freshness** — cached data may lag reality. Use manual sync, cron scheduling, or the **Current Month** switch (which reads budgets live) when accuracy matters.
- **Recommendation quality** — recommendations are based on usage patterns and configurable thresholds (e.g. 30-day inactivity). Administrators should weigh business context (parental leave, sabbaticals, contractors) before executing them.

---

## Security Considerations

| Aspect | Implementation |
|--------|---------------|
| Authentication | Local username/password (PBKDF2-SHA256, 100k iterations) and GitHub OAuth App SSO |
| OAuth CSRF | Single-use `state` parameter, persisted with a 10-minute TTL and consumed on callback |
| Authorization | Role middleware on every `/api/*` route: unauthenticated → 401; non-admin → only `/api/me/*` and `/api/budget-requests`; admin → everything |
| Admin determination | Local account, explicit GitHub allow-list, or PAT owner. Re-evaluated on every request so allow-list changes take effect without re-login |
| Session tokens | `secrets.token_hex(32)`, JSON-persisted with a 7-day TTL, re-read from disk so multi-worker deployments stay consistent |
| Cookies | httpOnly, `SameSite=Lax`, `Secure` when served over HTTPS, `Path=/` |
| Reverse proxy | `X-Forwarded-Proto` / `X-Forwarded-Host` honoured for callback URL derivation and the Secure-cookie decision |
| Secret storage | PATs and the OAuth client secret stored locally, masked in all API responses |
| Public share links | Unguessable tokens; optional PBKDF2-hashed password; revocable at any time |
| API security | CORS restricted to configured origins |
| Audit logging | Destructive operations and every budget decision logged with timestamps |
| Input validation | Pydantic models for all API request bodies |
| Data integrity | Synced files written via temp file + atomic replace, so readers never see a partial write |
| Dependency security | Minimal dependencies, all from trusted sources |

### Deployment Notes

- **`data/` is sensitive.** It holds admin credentials, PATs, the OAuth client secret, active sessions and billing data. Mount it as a private volume, restrict filesystem permissions, and never bake it into a container image or commit it.
- **Serve over HTTPS.** Session cookies are only marked `Secure` when the effective scheme is HTTPS.
- **Behind a proxy**, run uvicorn with `--proxy-headers --forwarded-allow-ips="<trusted>"` so the scheme and host are detected correctly. Avoid a blanket `"*"` on untrusted networks.
- **Restrict who can sign in.** If OctoFinance is internet-reachable, turn **Allow any GitHub user to sign in** off so only listed admins and PAT owners can authenticate.
- **Scope PATs minimally.** Only grant `manage_billing:copilot` if budget write-back and cost center management are actually needed. The Copilot CLI token is separate and needs only the **Copilot Requests: Read** account permission on a fine-grained PAT — never reuse an org-admin PAT for it.
- **Multiple workers must share one `data/` directory**, otherwise sessions and synced data diverge.
