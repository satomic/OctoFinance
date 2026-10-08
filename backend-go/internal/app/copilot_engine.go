package app

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"time"

	copilot "github.com/github/copilot-sdk/go"

	"github.com/satomic/octofinance/backend-go/internal/githost"
	"github.com/satomic/octofinance/backend-go/internal/jx"
)

// The AI engine: a Copilot SDK client with one session per chat session,
// FinOps tools, and session resumption across restarts.

const sdkSessionIDFile = ".copilot_session_id"

// FinOpsSystemPrompt is appended to the Copilot system prompt.
const FinOpsSystemPrompt = `You are OctoFinance AI FinOps Assistant, specialized in helping GitHub Copilot administrators optimize costs and manage seats efficiently.

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
- For destructive operations (seat removal), always explain the impact first and ask for confirmation
- Cached tools read the data from the last Sync Data. When cached data is missing or stale, or right after a
  live write (e.g. create_cost_center) that a cache-based tool depends on, call sync_data with the narrowest
  dataset (e.g. 'cost_centers') and then retry, instead of asking the admin to click Sync Data

Available data dimensions:
- Seats: who has Copilot, when they last used it, which team they belong to
- Usage Reports: org-level and user-level usage metrics (28-day or specific day), feature adoption, engagement data
- Billing: plan type, cost per seat, total cost, waste
- Metrics: detailed IDE completions, chat usage, PR summaries (legacy API)
- AI Credits: per-model breakdown of AI credit consumption, pricing, and costs (UBB)
- Budgets: UBB (Usage-Based Billing) AI credits budgets - Universal user-level budgets (default for all users), Individual user-level budgets (user-specific overrides), Enterprise/Cost center budgets (overage controls)
- Enterprise Teams: enterprise-level groups of users, independent of organizations, that can hold Copilot Business licenses directly

Enterprise Teams:
None of the Copilot datasets (seats, usage reports, metrics, AI credit CSVs) carry an enterprise-team field.
To analyze anything per enterprise team, first call list_enterprise_teams / get_enterprise_team to get the member
roster, then join it against the other datasets on the user login. get_enterprise_team_copilot_usage does this join
for you. Note that enterprise teams can include unaffiliated users who belong to no organization — those users never
appear in org seat data, so a team's member count can legitimately exceed the number of seats you can match.

Copilot AI credits (UBB - Usage-Based Billing, effective June 1, 2026):
Each Copilot plan includes a monthly allowance of AI credits per user; Copilot Enterprise includes
a larger allowance than Copilot Business. AI credit usage beyond the included monthly allowance is
billed per the model's price per credit (e.g. ~$0.01/credit). Use this information when analyzing
AI credit usage and cost optimization.
Note: The Copilot AI credit API only returns org-level totals by model. The per-user breakdown comes from the
detailed billing report CSV, which the admin can now pull automatically through the billing reports API
("Fetch CSV" in the UI) or still upload by hand from the GitHub UI export.

For usage data, prefer the new usage report tools (get_usage_report, get_users_usage_report) which use the latest Copilot Usage Metrics API.
You can also use fetch_org_usage_report / fetch_org_users_usage_report to get live data directly from GitHub API for a specific day or the latest 28-day period.

Budget Management (UBB Era - June 2026):
Starting June 1, 2026, GitHub Copilot billing switched from Premium Requests to AI Credits (UBB - Usage-Based Billing).
- Universal user-level budget: Default personal limit for ALL Copilot users (each enterprise/org can have only one)
- Individual user-level budget: User-specific limits that override Universal budget (for high-frequency users, core engineers, or restricted users)
- Enterprise/Cost center budgets: Control overage spending after the shared pool of included credits is exhausted
User-level budgets are hard limits by default (prevent_further_usage=true). When a user hits their budget limit, they are blocked from consuming more AI credits.
Use batch_create_user_budgets for bulk operations (onboarding teams, applying uniform limits to user groups).
`

var (
	jsonRPCPrefixRE = regexp.MustCompile(`^JSON-RPC Error -?\d+:\s*`)
	requestFailRE   = regexp.MustCompile(`^Request [\w.]+ failed with message:\s*`)
	newlinesRE      = regexp.MustCompile(`(\\n|\s)+`)
	trailingQuoteRE = regexp.MustCompile(`\s+"$`)
)

// cleanError drops the JSON-RPC wrapper around CLI errors.
func cleanError(err any) string {
	text := fmt.Sprint(err)
	text = jsonRPCPrefixRE.ReplaceAllString(text, "")
	text = requestFailRE.ReplaceAllString(text, "")
	text = newlinesRE.ReplaceAllString(text, " ")
	return strings.TrimSpace(trailingQuoteRE.ReplaceAllString(text, `"`))
}

func bareHost(v string) string {
	if v == "" {
		return ""
	}
	if !strings.Contains(v, "://") {
		v = "https://" + v
	}
	u, err := url.Parse(v)
	if err != nil {
		return ""
	}
	return strings.ToLower(u.Hostname())
}

var engineHTTP = &http.Client{Timeout: 10 * time.Second}

func tokenUserStatus(ctx context.Context, token, host string) (int, jx.M) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, githost.APIBase(host)+"/user", nil)
	if err != nil {
		return 0, nil
	}
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Accept", "application/vnd.github+json")
	resp, err := engineHTTP.Do(req)
	if err != nil {
		Logger.Warn(fmt.Sprintf("Could not check the Copilot token against %s: %v", host, err))
		return 0, nil
	}
	defer resp.Body.Close()
	var v any
	_ = jsonDecode(resp.Body, &v)
	return resp.StatusCode, jx.Map(v)
}

func lookupLogin(ctx context.Context, token, host string) string {
	status, body := tokenUserStatus(ctx, token, githost.FromAPIBase(host))
	if status == 200 {
		return jx.Str(body["login"])
	}
	return ""
}

// CopilotEngine manages the Copilot SDK client and sessions.
type CopilotEngine struct {
	mu            sync.Mutex
	opMu          sync.Mutex // serializes client (re)starts
	client        *copilot.Client
	started       bool
	sessions      map[string]*copilot.Session
	sessionModels map[string]string
	sessionLocks  map[string]*sync.Mutex
	cliHost       string
	authStatus    jx.M
}

// Engine is the global AI engine.
var Engine = &CopilotEngine{
	sessions:      map[string]*copilot.Session{},
	sessionModels: map[string]string{},
	sessionLocks:  map[string]*sync.Mutex{},
	authStatus:    jx.M{},
}

type credentials struct {
	token  string
	source jx.M
}

// resolveCredentials picks the token for the Copilot CLI: Settings -> env vars ->
// first non-classic PAT -> the CLI's own logged-in user.
func resolveCredentials() credentials {
	if token, _ := ChatAuthGet(); token != "" {
		Logger.Info("Using the token from Settings -> AI Chat for Copilot CLI authentication")
		return credentials{token, jx.M{"kind": "settings", "detail": "", "token_masked": MaskToken(token)}}
	}
	for _, env := range []string{"COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"} {
		if token := strings.TrimSpace(os.Getenv(env)); token != "" {
			Logger.Info(fmt.Sprintf("Using %s environment variable for Copilot CLI authentication", env))
			return credentials{token, jx.M{"kind": "env", "detail": env, "token_masked": MaskToken(token)}}
		}
	}
	pats := Pats.GetAll()
	if len(pats) == 0 {
		pats = Pats.Load()
	}
	for _, pat := range pats {
		token := jx.Str(pat["token"])
		if token == "" || strings.HasPrefix(token, "ghp_") {
			continue
		}
		Logger.Info(fmt.Sprintf("Using configured PAT '%s' for Copilot CLI", jx.Str(pat["label"])))
		return credentials{token, jx.M{
			"kind": "pat", "detail": jx.Str(pat["label"]), "token_masked": MaskToken(token),
			"pat_host": jx.Str(pat["host"]),
		}}
	}
	return credentials{"", jx.M{"kind": "cli_login", "detail": "", "token_masked": ""}}
}

// detectTokenHost returns the GHE.com host a token belongs to ("" for github.com).
// The token is only sent to hosts already configured in OctoFinance.
func detectTokenHost(ctx context.Context, token string) string {
	candidates := []string{}
	add := func(h string) {
		if githost.IsGHE(h) {
			for _, c := range candidates {
				if c == h {
					return
				}
			}
			candidates = append(candidates, h)
		}
	}
	pats := Pats.GetAll()
	if len(pats) == 0 {
		pats = Pats.Load()
	}
	for _, p := range pats {
		add(jx.Str(p["host"]))
	}
	if h, err := githost.Normalize(jx.Str(Auth.OAuthConfig()["host"])); err == nil {
		add(h)
	}
	for _, h := range candidates {
		if status, _ := tokenUserStatus(ctx, token, h); status == 200 {
			return h
		}
	}
	return ""
}

// resolveCLIHost returns the host for COPILOT_GH_HOST ("" = CLI default).
func resolveCLIHost(ctx context.Context, cred credentials) string {
	if _, pinned := ChatAuthGet(); pinned != "" {
		return pinned
	}
	if os.Getenv("COPILOT_GH_HOST") != "" || os.Getenv("GH_HOST") != "" {
		return ""
	}
	if h := jx.Str(cred.source["pat_host"]); githost.IsGHE(h) && h != "" {
		return h
	}
	if cred.token != "" {
		h := detectTokenHost(ctx, cred.token)
		if h != "" {
			Logger.Info(fmt.Sprintf("Copilot token belongs to %s; pointing the Copilot CLI at it", h))
		}
		return h
	}
	return ""
}

// cliPathEnv returns COPILOT_CLI_PATH=<copilot on PATH> when the variable is
// unset. Newer Copilot Go SDKs no longer fall back to the PATH themselves.
func cliPathEnv() []string {
	if strings.TrimSpace(os.Getenv("COPILOT_CLI_PATH")) != "" {
		return nil
	}
	if p, err := exec.LookPath("copilot"); err == nil {
		return []string{"COPILOT_CLI_PATH=" + p}
	}
	return nil
}

func newClient(token string, useLoggedInUser bool, host string) *copilot.Client {
	env := append(os.Environ(), cliPathEnv()...)
	if host != "" {
		env = append(env, "COPILOT_GH_HOST="+host)
	}
	opts := &copilot.ClientOptions{Env: env, LogLevel: "error"}
	if token != "" {
		opts.GitHubToken = token
		opts.UseLoggedInUser = copilot.Bool(false)
	} else if useLoggedInUser {
		opts.UseLoggedInUser = copilot.Bool(true)
	}
	return copilot.NewClient(opts)
}

func ptrStr(p *string) string {
	if p == nil {
		return ""
	}
	return *p
}

// probeStatus reports who the CLI is signed in as and whether Copilot serves models.
func probeStatus(ctx context.Context, client *copilot.Client, base jx.M, token string) jx.M {
	status := jx.Merge(base, jx.M{"authenticated": false, "login": "", "host": "", "models_available": nil})
	auth, err := client.GetAuthStatus(ctx)
	if err != nil {
		if !jx.Truthy(status["error"]) {
			status["error"] = cleanError(err)
		}
		return status
	}
	host := bareHost(ptrStr(auth.Host))
	if host == "" {
		host = jx.Str(base["requested_host"])
	}
	if host == "" {
		host = "github.com"
	}
	status["authenticated"] = auth.IsAuthenticated
	status["login"] = ptrStr(auth.Login)
	status["host"] = host
	if auth.IsAuthenticated && ptrStr(auth.Login) == "" && token != "" {
		status["login"] = lookupLogin(ctx, token, host)
	}
	if !auth.IsAuthenticated && !jx.Truthy(status["error"]) {
		msg := ptrStr(auth.StatusMessage)
		if msg == "" {
			msg = "Not authenticated"
		}
		status["error"] = msg
	}
	if auth.IsAuthenticated {
		models, err := client.ListModels(ctx)
		if err != nil {
			status["models_available"] = 0
			status["models_error"] = cleanError(err)
		} else {
			status["models_available"] = len(models)
		}
	}
	return status
}

// startClient starts a client, falling back to the CLI's own login if the token is rejected.
func (e *CopilotEngine) startClient(ctx context.Context) (*copilot.Client, jx.M, string, error) {
	cred := resolveCredentials()
	host := resolveCLIHost(ctx, cred)
	requested := host
	if requested == "" {
		requested = os.Getenv("COPILOT_GH_HOST")
	}
	if requested == "" {
		requested = os.Getenv("GH_HOST")
	}
	base := jx.M{"source": cred.source, "requested_host": requested, "fallback_used": false, "error": ""}

	client := newClient(cred.token, false, host)
	if err := client.Start(ctx); err != nil {
		return nil, jx.Merge(base, jx.M{"authenticated": false, "error": cleanError(err)}), host, err
	}
	if cred.token == "" {
		return client, probeStatus(ctx, client, base, ""), host, nil
	}
	rejection := ""
	auth, err := client.GetAuthStatus(ctx)
	if err == nil && auth.IsAuthenticated {
		return client, probeStatus(ctx, client, base, cred.token), host, nil
	}
	if err != nil {
		Logger.Error("Failed to read Copilot auth status: " + err.Error())
		rejection = cleanError(err)
	} else {
		rejection = ptrStr(auth.StatusMessage)
		if rejection == "" {
			rejection = "Not authenticated"
		}
	}
	Logger.Warn("Configured Copilot token was rejected; falling back to the Copilot CLI's logged-in user")
	_ = client.Stop()
	fallback := newClient("", true, "")
	if err := fallback.Start(ctx); err != nil {
		return nil, jx.Merge(base, jx.M{"authenticated": false, "fallback_used": true, "error": cleanError(err)}), host, err
	}
	base["fallback_used"] = true
	base["error"] = "Token rejected: " + rejection
	return fallback, probeStatus(ctx, fallback, base, ""), host, nil
}

// Start starts the SDK client.
func (e *CopilotEngine) Start(ctx context.Context) error {
	return e.restart(ctx)
}

// restart (re)starts the client, dropping all sessions.
func (e *CopilotEngine) restart(ctx context.Context) error {
	e.opMu.Lock()
	defer e.opMu.Unlock()
	e.mu.Lock()
	old := e.client
	e.client = nil
	e.started = false
	e.sessions = map[string]*copilot.Session{}
	e.sessionModels = map[string]string{}
	e.mu.Unlock()
	if old != nil {
		if err := old.Stop(); err != nil {
			Logger.Error("Failed to stop Copilot SDK client during restart: " + err.Error())
		}
	}
	type result struct {
		client *copilot.Client
		status jx.M
		host   string
		err    error
	}
	ch := make(chan result, 1)
	go func() {
		c, s, h, err := e.startClient(context.Background())
		ch <- result{c, s, h, err}
	}()
	var res result
	select {
	case res = <-ch:
	case <-ctx.Done():
		// Keep the start running; adopt its client when it finishes.
		go func() {
			r := <-ch
			e.mu.Lock()
			defer e.mu.Unlock()
			e.authStatus = r.status
			if r.err == nil && e.client == nil {
				e.client, e.started, e.cliHost = r.client, true, r.host
			} else if r.client != nil && r.err == nil {
				_ = r.client.Stop()
			}
		}()
		return ctx.Err()
	}
	e.mu.Lock()
	defer e.mu.Unlock()
	e.authStatus = res.status
	e.cliHost = res.host
	if res.err != nil {
		return res.err
	}
	e.client = res.client
	e.started = true
	return nil
}

// IsReady reports whether the client is running.
func (e *CopilotEngine) IsReady() bool {
	e.mu.Lock()
	defer e.mu.Unlock()
	return e.client != nil && e.started
}

func (e *CopilotEngine) getClient() *copilot.Client {
	e.mu.Lock()
	defer e.mu.Unlock()
	return e.client
}

// AuthStatus returns the chat authentication status; refresh re-checks with the CLI.
func (e *CopilotEngine) AuthStatus(ctx context.Context, refresh bool) jx.M {
	if !e.IsReady() {
		if err := e.restart(ctx); err != nil {
			e.mu.Lock()
			defer e.mu.Unlock()
			return jx.Merge(e.authStatus, jx.M{"authenticated": false, "error": cleanError(err)})
		}
	} else if refresh {
		e.mu.Lock()
		base := jx.M{}
		for k, d := range map[string]any{"source": "", "requested_host": "", "fallback_used": false, "error": ""} {
			base[k] = jx.GetOr(e.authStatus, k, d)
		}
		client := e.client
		e.mu.Unlock()
		token := ""
		if !jx.Truthy(base["fallback_used"]) {
			token = resolveCredentials().token
		}
		status := probeStatus(ctx, client, base, token)
		e.mu.Lock()
		e.authStatus = status
		e.mu.Unlock()
	}
	e.mu.Lock()
	defer e.mu.Unlock()
	return jx.Copy(e.authStatus)
}

// ApplyAuthSettings reconnects with the credentials from Settings.
func (e *CopilotEngine) ApplyAuthSettings(ctx context.Context) jx.M {
	if err := e.restart(ctx); err != nil {
		Logger.Error("Failed to restart the Copilot client with new chat settings: " + err.Error())
		e.mu.Lock()
		defer e.mu.Unlock()
		return jx.Merge(e.authStatus, jx.M{"authenticated": false, "error": cleanError(err)})
	}
	e.mu.Lock()
	defer e.mu.Unlock()
	return jx.Copy(e.authStatus)
}

// Stop disconnects all sessions and stops the client.
func (e *CopilotEngine) Stop() {
	e.mu.Lock()
	sessions := e.sessions
	client := e.client
	e.sessions = map[string]*copilot.Session{}
	e.sessionModels = map[string]string{}
	e.client = nil
	e.started = false
	e.mu.Unlock()
	for _, s := range sessions {
		_ = s.Disconnect()
	}
	if client != nil {
		_ = client.Stop()
	}
}

// RefreshCLIHost restarts the client when the token now resolves to a different host.
func (e *CopilotEngine) RefreshCLIHost(ctx context.Context) {
	cred := resolveCredentials()
	if cred.token == "" {
		return
	}
	host := resolveCLIHost(ctx, cred)
	e.mu.Lock()
	current := e.cliHost
	e.mu.Unlock()
	if host != current {
		Logger.Info(fmt.Sprintf("Copilot CLI host changed (%s -> %s); restarting the client", current, host))
		if err := e.restart(ctx); err != nil {
			Logger.Error("Failed to refresh the Copilot CLI host: " + err.Error())
		}
	}
}

// ScheduleCLIHostRefresh runs RefreshCLIHost in the background.
func (e *CopilotEngine) ScheduleCLIHostRefresh() {
	if !e.IsReady() {
		return
	}
	go e.RefreshCLIHost(context.Background())
}

// ---------------------------------------------------------------------------
// Sessions
// ---------------------------------------------------------------------------

func readSDKSessionID(wd string) string {
	if wd == "" {
		return ""
	}
	b, err := os.ReadFile(filepath.Join(wd, sdkSessionIDFile))
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(b))
}

func writeSDKSessionID(wd, id string) {
	if wd == "" {
		return
	}
	_ = os.MkdirAll(wd, 0o755)
	_ = os.WriteFile(filepath.Join(wd, sdkSessionIDFile), []byte(id), 0o644)
}

func deleteSDKSessionID(wd string) {
	if wd == "" {
		return
	}
	_ = os.Remove(filepath.Join(wd, sdkSessionIDFile))
}

func (e *CopilotEngine) sessionLock(id string) *sync.Mutex {
	e.mu.Lock()
	defer e.mu.Unlock()
	l, ok := e.sessionLocks[id]
	if !ok {
		l = &sync.Mutex{}
		e.sessionLocks[id] = l
	}
	return l
}

func systemMessage() *copilot.SystemMessageConfig {
	return &copilot.SystemMessageConfig{Mode: "append", Content: FinOpsSystemPrompt}
}

func (e *CopilotEngine) createSession(ctx context.Context, id, wd string) (*copilot.Session, error) {
	client := e.getClient()
	if client == nil {
		return nil, errors.New("Copilot client not started")
	}
	session, err := client.CreateSession(ctx, &copilot.SessionConfig{
		Tools:               BuildTools(wd),
		SystemMessage:       systemMessage(),
		OnPermissionRequest: copilot.PermissionHandler.ApproveAll,
		WorkingDirectory:    wd,
		Streaming:           copilot.Bool(true),
	})
	if err != nil {
		return nil, err
	}
	e.mu.Lock()
	e.sessions[id] = session
	e.mu.Unlock()
	writeSDKSessionID(wd, session.SessionID)
	Logger.Info(fmt.Sprintf("Created new Copilot session %s (SDK %s)", id, session.SessionID))
	return session, nil
}

func (e *CopilotEngine) resumeSession(ctx context.Context, id, sdkID, wd string) (*copilot.Session, error) {
	client := e.getClient()
	if client == nil {
		return nil, errors.New("Copilot client not started")
	}
	session, err := client.ResumeSession(ctx, sdkID, &copilot.ResumeSessionConfig{
		Tools:               BuildTools(wd),
		SystemMessage:       systemMessage(),
		OnPermissionRequest: copilot.PermissionHandler.ApproveAll,
		WorkingDirectory:    wd,
		Streaming:           copilot.Bool(true),
	})
	if err != nil {
		return nil, err
	}
	e.mu.Lock()
	e.sessions[id] = session
	e.mu.Unlock()
	writeSDKSessionID(wd, session.SessionID)
	return session, nil
}

// GetOrCreateSession returns an in-memory session, resumes a persisted one, or creates one.
func (e *CopilotEngine) GetOrCreateSession(ctx context.Context, id, wd string) (*copilot.Session, error) {
	if !e.IsReady() {
		Logger.Warn("Copilot client is not ready; starting SDK client before creating session " + id)
		if err := e.restart(ctx); err != nil {
			return nil, err
		}
	}
	e.mu.Lock()
	if s, ok := e.sessions[id]; ok {
		e.mu.Unlock()
		return s, nil
	}
	e.mu.Unlock()

	if sdkID := readSDKSessionID(wd); sdkID != "" {
		s, err := e.resumeSession(ctx, id, sdkID, wd)
		if err == nil {
			Logger.Info(fmt.Sprintf("Resumed Copilot session %s (SDK %s)", id, sdkID))
			return s, nil
		}
		Logger.Warn(fmt.Sprintf("Failed to resume SDK session %s, creating new: %v", sdkID, err))
		deleteSDKSessionID(wd)
	}
	s, err := e.createSession(ctx, id, wd)
	if err == nil {
		return s, nil
	}
	Logger.Error(fmt.Sprintf("Failed to create Copilot session %s; restarting SDK client and retrying once: %v", id, err))
	if rerr := e.restart(ctx); rerr != nil {
		return nil, rerr
	}
	deleteSDKSessionID(wd)
	return e.createSession(ctx, id, wd)
}

func (e *CopilotEngine) retryWithNewSession(ctx context.Context, id, wd string) (*copilot.Session, error) {
	e.mu.Lock()
	old := e.sessions[id]
	delete(e.sessions, id)
	delete(e.sessionModels, id)
	e.mu.Unlock()
	if old != nil {
		_ = old.Disconnect()
	}
	return e.createSession(ctx, id, wd)
}

// ListModels lists models available to the authenticated account.
func (e *CopilotEngine) ListModels(ctx context.Context) ([]jx.M, error) {
	if !e.IsReady() {
		if err := e.restart(ctx); err != nil {
			return nil, err
		}
	}
	client := e.getClient()
	if client == nil {
		return []jx.M{}, nil
	}
	models, err := client.ListModels(ctx)
	if err != nil {
		return nil, err
	}
	out := []jx.M{}
	for _, m := range models {
		var multiplier any
		if m.Billing != nil && m.Billing.Multiplier != nil {
			multiplier = *m.Billing.Multiplier
		}
		var efforts any
		if m.SupportedReasoningEfforts != nil {
			efforts = m.SupportedReasoningEfforts
		}
		var def any
		if m.DefaultReasoningEffort != "" {
			def = m.DefaultReasoningEffort
		}
		out = append(out, jx.M{
			"id":                          m.ID,
			"name":                        m.Name,
			"multiplier":                  multiplier,
			"is_premium":                  nil,
			"supported_reasoning_efforts": efforts,
			"default_reasoning_effort":    def,
		})
	}
	return out, nil
}

func (e *CopilotEngine) applyModel(ctx context.Context, s *copilot.Session, id, model string) {
	target := model
	if target == "" {
		target = "auto"
	}
	e.mu.Lock()
	current := e.sessionModels[id]
	e.mu.Unlock()
	if current == target {
		return
	}
	if err := s.SetModel(ctx, target, nil); err != nil {
		Logger.Error(fmt.Sprintf("Failed to switch session %s to model %s: %v", id, target, err))
		return
	}
	e.mu.Lock()
	e.sessionModels[id] = target
	e.mu.Unlock()
}

// ChatEvent is one streamed event: {"type", "content", ...}.
type ChatEvent = jx.M

func serializeArgs(v any) any {
	if v == nil {
		return nil
	}
	if s, ok := v.(string); ok {
		return s
	}
	return jx.Dumps(v)
}

func eventToChat(ev copilot.SessionEvent) (ChatEvent, bool) {
	switch d := ev.Data.(type) {
	case *copilot.AssistantMessageDeltaData:
		return ChatEvent{"type": "delta", "content": d.DeltaContent}, true
	case *copilot.AssistantMessageData:
		return ChatEvent{"type": "message", "content": d.Content}, true
	case *copilot.AssistantReasoningDeltaData:
		if d.DeltaContent != "" {
			return ChatEvent{"type": "thinking_delta", "content": d.DeltaContent}, true
		}
	case *copilot.ToolExecutionStartData:
		name := d.ToolName
		if name == "" {
			name = "unknown"
		}
		return ChatEvent{"type": "tool_start", "content": name, "tool_call_id": d.ToolCallID, "detail": serializeArgs(d.Arguments)}, true
	case *copilot.ToolExecutionCompleteData:
		var name any
		if d.ToolDescription != nil && d.ToolDescription.Name != "" {
			name = d.ToolDescription.Name
		}
		var result any
		if d.Result != nil {
			result = d.Result.Content
		}
		return ChatEvent{"type": "tool_complete", "content": name, "tool_call_id": d.ToolCallID, "detail": result}, true
	case *copilot.AssistantUsageData:
		var in, out, cost, dur any
		if d.InputTokens != nil {
			in = *d.InputTokens
		}
		if d.OutputTokens != nil {
			out = *d.OutputTokens
		}
		if d.Cost != nil {
			cost = *d.Cost
		}
		if d.Duration != nil {
			dur = *d.Duration
		}
		return ChatEvent{"type": "usage", "content": d.Model, "detail": jx.Dumps(jx.M{
			"input_tokens": in, "output_tokens": out, "cost": cost, "duration": dur,
		})}, true
	case *copilot.SessionErrorData:
		msg := d.Message
		if msg == "" {
			msg = "Unknown error"
		}
		return ChatEvent{"type": "error", "content": msg}, true
	}
	return nil, false
}

// Chat sends a message and streams events to emit until the session goes idle.
// Tool-start names are resolved for tool_complete events that omit them.
func (e *CopilotEngine) Chat(ctx context.Context, message, id, wd, model string, emit func(ChatEvent)) error {
	lock := e.sessionLock(id)
	lock.Lock()
	defer lock.Unlock()

	session, err := e.GetOrCreateSession(ctx, id, wd)
	if err != nil {
		return err
	}
	e.applyModel(ctx, session, id, model)

	events := make(chan ChatEvent, 1024)
	done := make(chan struct{}, 1)
	var mu sync.Mutex
	closed := false
	toolNames := map[string]any{}
	handler := func(ev copilot.SessionEvent) {
		mu.Lock()
		defer mu.Unlock()
		if closed {
			return
		}
		if _, idle := ev.Data.(*copilot.SessionIdleData); idle {
			closed = true
			done <- struct{}{}
			return
		}
		ce, ok := eventToChat(ev)
		if !ok {
			return
		}
		switch jx.Str(ce["type"]) {
		case "tool_start":
			toolNames[jx.Str(ce["tool_call_id"])] = ce["content"]
		case "tool_complete":
			if ce["content"] == nil {
				ce["content"] = toolNames[jx.Str(ce["tool_call_id"])]
			}
		}
		select {
		case events <- ce:
		default:
		}
		if jx.Str(ce["type"]) == "error" {
			closed = true
			done <- struct{}{}
		}
	}
	unsubscribe := session.On(handler)
	defer func() { unsubscribe() }()

	if _, err := session.Send(ctx, copilot.MessageOptions{Prompt: message}); err != nil {
		if !strings.Contains(err.Error(), "Session not found") {
			return err
		}
		Logger.Warn(fmt.Sprintf("Session not found for %s, creating new session", id))
		unsubscribe()
		session, err = e.retryWithNewSession(ctx, id, wd)
		if err != nil {
			return err
		}
		unsubscribe = session.On(handler)
		if _, err := session.Send(ctx, copilot.MessageOptions{Prompt: message}); err != nil {
			return err
		}
	}

	timeout := time.NewTimer(300 * time.Second)
	defer timeout.Stop()
	for {
		select {
		case ce := <-events:
			emit(ce)
			if !timeout.Stop() {
				<-timeout.C
			}
			timeout.Reset(300 * time.Second)
		case <-done:
			// drain events delivered before idle
			for {
				select {
				case ce := <-events:
					emit(ce)
				default:
					return nil
				}
			}
		case <-timeout.C:
			emit(ChatEvent{"type": "error", "content": "Response timeout"})
			return nil
		case <-ctx.Done():
			_ = session.Abort(context.Background())
			return ctx.Err()
		}
	}
}

// ChatSimple sends a message and returns the final response text.
func (e *CopilotEngine) ChatSimple(ctx context.Context, message, id, wd, model string) (string, error) {
	var last string
	var chatErr string
	err := e.Chat(ctx, message, id, wd, model, func(ce ChatEvent) {
		switch jx.Str(ce["type"]) {
		case "message":
			if c := jx.Str(ce["content"]); c != "" {
				last = c
			}
		case "error":
			chatErr = jx.Str(ce["content"])
		}
	})
	if err != nil {
		return "", err
	}
	if last == "" && chatErr != "" {
		return "", errors.New(chatErr)
	}
	return last, nil
}

// DestroySession disconnects and deletes a session's server-side state.
func (e *CopilotEngine) DestroySession(id string) {
	e.mu.Lock()
	s := e.sessions[id]
	delete(e.sessions, id)
	delete(e.sessionModels, id)
	client := e.client
	e.mu.Unlock()
	if s == nil {
		return
	}
	sdkID := s.SessionID
	_ = s.Disconnect()
	if client != nil {
		_ = client.DeleteSession(context.Background(), sdkID)
	}
}
