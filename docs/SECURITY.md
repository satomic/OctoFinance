# OctoFinance — Responsible AI & Security

## Responsible AI (RAI) Notes

### Human-in-the-Loop Design

OctoFinance implements a strict human-in-the-loop pattern for all destructive operations:

1. **AI Recommends, Human Decides**: The AI agent can identify inactive users and calculate potential savings, but it cannot remove seats autonomously. All seat removal operations must go through the **recommendation → review → approval** workflow.

2. **Explicit Confirmation**: When the AI suggests seat removals, the recommendations are stored in the Action Panel. Each recommendation shows the affected users, organization, and estimated savings. The administrator must explicitly click "Approve & Execute" or "Reject."

3. **Audit Trail**: Every executed action is logged in `data/audit_log.json` with timestamps, affected users, organization, reason, and results.

### Data Privacy

- **No PII Collection**: The platform only accesses publicly available GitHub profile information (usernames, avatars) and Copilot usage metrics available through the GitHub API.
- **Local Data Storage**: All data is stored locally in JSON files under the `data/` directory. No data is sent to external services beyond the GitHub API.
- **PAT Security**: GitHub PATs are stored locally in `data/pats.json` and are masked in the UI (only last 4 characters shown). PATs are never transmitted to any third party.
- **Session Security**: Authentication uses httpOnly cookies with SameSite=Lax policy. Passwords are hashed with PBKDF2-SHA256 (100,000 iterations).

### Transparency

- **Tool Execution Visibility**: During AI conversations, the UI shows real-time indicators of which tools are being called and their results, ensuring full transparency of the AI's decision-making process.
- **Data Source Attribution**: The AI agent clearly communicates which data sources it's using (cached data vs. live API calls) and when data was last synchronized.
- **Reasoning Display**: The AI agent's thinking/reasoning process can be observed through the console panel.

### Limitations & Responsible Use

- **Scope of Authority**: The AI agent operates within the permissions granted by the configured GitHub PATs. It cannot access data or perform operations beyond what the PAT allows.
- **Rate Limiting**: GitHub API rate limits apply. The platform handles rate limit errors gracefully and communicates them to the user.
- **Data Freshness**: Cached data may not reflect the most current state. Users can trigger manual sync or configure cron-based auto-sync to maintain data freshness.
- **Recommendation Quality**: AI recommendations are based on usage patterns and configurable thresholds (e.g., 30-day inactivity). Administrators should consider business context (e.g., employees on leave) before executing recommendations.

---

## Security Considerations

| Aspect | Implementation |
|--------|---------------|
| Authentication | Cookie-based sessions, PBKDF2-SHA256 password hashing |
| Authorization | Auth middleware on all `/api/*` routes |
| PAT Storage | Local file with masked display |
| Session Tokens | `secrets.token_hex(32)`, in-memory set, 7-day cookie expiry |
| API Security | CORS restricted to configured origins |
| Audit Logging | All destructive operations logged with timestamps |
| Input Validation | Pydantic models for all API request bodies |
| Dependency Security | Minimal dependencies, all from trusted sources |
