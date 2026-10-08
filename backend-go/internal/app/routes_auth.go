package app

import (
	"context"
	"fmt"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/satomic/octofinance/backend-go/internal/githost"
	"github.com/satomic/octofinance/backend-go/internal/jx"
)

// Local username/password login and GitHub OAuth SSO.

const sessionMaxAge = 60 * 60 * 24 * 7

func init() { registerRoutes(registerAuthRoutes) }

func registerAuthRoutes(r *Router) {
	r.Handle("GET /api/auth/status", authStatus)
	r.Handle("POST /api/auth/setup", authSetup)
	r.Handle("POST /api/auth/login", authLogin)
	r.Handle("POST /api/auth/logout", authLogout)
	r.Handle("GET /api/auth/github/login", githubLogin)
	r.Handle("GET /api/auth/github/callback", githubCallback)
	r.Handle("GET /api/auth/github/config", getGithubConfig)
	r.Handle("PUT /api/auth/github/config", updateGithubConfig)
}

func oauthURLs(cfg jx.M) (authorize, token, user string) {
	host, err := githost.Normalize(jx.Str(cfg["host"]))
	if err != nil {
		host = githost.DefaultHost
	}
	web := githost.WebBase(host)
	return web + "/login/oauth/authorize", web + "/login/oauth/access_token", githost.APIBase(host) + "/user"
}

// forwardedOrigin is the request origin, honouring reverse-proxy headers.
func forwardedOrigin(r *http.Request) string {
	first := func(v string) string { return strings.TrimSpace(strings.Split(v, ",")[0]) }
	proto := first(r.Header.Get("X-Forwarded-Proto"))
	host := first(r.Header.Get("X-Forwarded-Host"))
	if proto == "" {
		proto = "http"
		if r.TLS != nil {
			proto = "https"
		}
	}
	if host == "" {
		host = r.Host
	}
	return proto + "://" + host
}

func setSessionCookie(w http.ResponseWriter, r *http.Request, token string) {
	http.SetCookie(w, &http.Cookie{
		Name:     sessionCookie,
		Value:    token,
		Path:     "/",
		MaxAge:   sessionMaxAge,
		Expires:  time.Now().Add(sessionMaxAge * time.Second),
		HttpOnly: true,
		SameSite: http.SameSiteLaxMode,
		Secure:   strings.HasPrefix(forwardedOrigin(r), "https://"),
	})
}

func publicUser(session jx.M) any {
	if session == nil {
		return nil
	}
	return jx.M{
		"login":      jx.GetStr(session, "login"),
		"name":       jx.GetStr(session, "name"),
		"avatar_url": jx.GetStr(session, "avatar_url"),
		"auth_type":  jx.GetStr(session, "auth_type", "local"),
		"is_admin":   jx.GetBool(session, "is_admin"),
		"github_id":  session["github_id"],
	}
}

func callbackURL(r *http.Request) string {
	if cfg := strings.TrimSpace(jx.Str(Auth.OAuthConfig()["callback_url"])); cfg != "" {
		return cfg
	}
	return forwardedOrigin(r) + "/api/auth/github/callback"
}

func authStatus(c *Ctx) any {
	token := ""
	if ck, err := c.R.Cookie(sessionCookie); err == nil {
		token = ck.Value
	}
	session := Auth.GetSession(token)
	if token != "" && session == nil {
		Logger.Warn(fmt.Sprintf("[auth] Session cookie presented but not found (host=%s). If OctoFinance runs with "+
			"multiple workers, ensure they share the same data directory.", c.R.Host))
	}
	return jx.M{
		"setup_required": Auth.LoadCredentials() == nil,
		"authenticated":  session != nil,
		"user":           publicUser(session),
		"is_admin":       jx.GetBool(session, "is_admin"),
		"github_enabled": Auth.GithubEnabled(),
		"version":        AppVersion,
		"update":         Updates.State(),
	}
}

type credentialsBody struct {
	Username *string `json:"username"`
	Password *string `json:"password"`
}

func (b credentialsBody) missing() *Resp {
	fields := []string{}
	if b.Username == nil {
		fields = append(fields, "username")
	}
	if b.Password == nil {
		fields = append(fields, "password")
	}
	if len(fields) > 0 {
		return Missing(fields...)
	}
	return nil
}

func authSetup(c *Ctx) any {
	var body credentialsBody
	if r := c.Bind(&body); r != nil {
		return r
	}
	if r := body.missing(); r != nil {
		return r
	}
	if Auth.LoadCredentials() != nil {
		return jx.M{"error": "Credentials already configured. Use login instead."}
	}
	username := strings.TrimSpace(*body.Username)
	if username == "" || strings.TrimSpace(*body.Password) == "" {
		return jx.M{"error": "Username and password are required."}
	}
	if err := Auth.SaveCredentials(username, *body.Password); err != nil {
		return HTTPError(500, err.Error())
	}
	token := Auth.CreateSession(username, username, "", "local", true, nil)
	setSessionCookie(c.W, c.R, token)
	return jx.M{"ok": true}
}

func authLogin(c *Ctx) any {
	var body credentialsBody
	if r := c.Bind(&body); r != nil {
		return r
	}
	if r := body.missing(); r != nil {
		return r
	}
	creds := Auth.LoadCredentials()
	if creds == nil {
		return jx.M{"error": "No credentials configured. Please set up first."}
	}
	stored := jx.Str(creds["username"])
	if strings.TrimSpace(*body.Username) != stored ||
		!Auth.VerifyPassword(*body.Password, jx.Str(creds["password_hash"]), jx.Str(creds["salt"])) {
		return jx.M{"error": "Invalid username or password."}
	}
	token := Auth.CreateSession(stored, stored, "", "local", true, nil)
	setSessionCookie(c.W, c.R, token)
	return jx.M{"ok": true}
}

func authLogout(c *Ctx) any {
	if ck, err := c.R.Cookie(sessionCookie); err == nil {
		Auth.DestroySession(ck.Value)
	}
	http.SetCookie(c.W, &http.Cookie{
		Name: sessionCookie, Value: "", Path: "/", MaxAge: -1,
		Expires: time.Unix(0, 0), HttpOnly: true, SameSite: http.SameSiteLaxMode,
	})
	return jx.M{"ok": true}
}

func redirect(c *Ctx, target string) any {
	http.Redirect(c.W, c.R, target, http.StatusFound)
	return nil
}

func githubLogin(c *Ctx) any {
	cfg := Auth.OAuthConfig()
	if !jx.Truthy(cfg["client_id"]) || !jx.Truthy(cfg["client_secret"]) {
		return redirect(c, "/?auth_error=github_not_configured")
	}
	state := Auth.CreateOAuthState()
	redirectURI := callbackURL(c.R)
	origin := forwardedOrigin(c.R)
	if !strings.HasPrefix(redirectURI, origin) {
		Logger.Warn(fmt.Sprintf("[auth] OAuth callback origin (%s) differs from the browsing origin (%s). The session "+
			"cookie will be stored on the callback origin, so the user must browse OctoFinance on that same origin. "+
			"Fix the 'Callback URL' in Settings -> GitHub SSO, or leave it blank to auto-detect.", redirectURI, origin))
	}
	Logger.Info(fmt.Sprintf("[auth] GitHub login start: origin=%s redirect_uri=%s", origin, redirectURI))
	params := url.Values{
		"client_id":    {jx.Str(cfg["client_id"])},
		"redirect_uri": {redirectURI},
		"scope":        {"read:user user:email"},
		"state":        {state},
		"allow_signup": {"false"},
	}
	authorize, _, _ := oauthURLs(cfg)
	return redirect(c, authorize+"?"+params.Encode())
}

var oauthHTTP = &http.Client{Timeout: 20 * time.Second}

func githubCallback(c *Ctx) any {
	if e := c.Query("error"); e != "" {
		return redirect(c, "/?auth_error="+url.QueryEscape(e))
	}
	code := c.Query("code")
	if code == "" {
		return redirect(c, "/?auth_error=missing_code")
	}
	if !Auth.ConsumeOAuthState(c.Query("state")) {
		return redirect(c, "/?auth_error=invalid_state")
	}
	cfg := Auth.OAuthConfig()
	if !jx.Truthy(cfg["client_id"]) || !jx.Truthy(cfg["client_secret"]) {
		return redirect(c, "/?auth_error=github_not_configured")
	}
	_, tokenURL, userURL := oauthURLs(cfg)
	ctx, cancel := context.WithTimeout(c.R.Context(), 20*time.Second)
	defer cancel()

	form := url.Values{
		"client_id":     {jx.Str(cfg["client_id"])},
		"client_secret": {jx.Str(cfg["client_secret"])},
		"code":          {code},
		"redirect_uri":  {callbackURL(c.R)},
	}
	req, _ := http.NewRequestWithContext(ctx, http.MethodPost, tokenURL, strings.NewReader(form.Encode()))
	req.Header.Set("Accept", "application/json")
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	tokenData, err := doJSON(req)
	if err != nil {
		Logger.Error("GitHub OAuth error: " + err.Error())
		return redirect(c, "/?auth_error=github_api_error")
	}
	accessToken := jx.Str(tokenData["access_token"])
	if accessToken == "" {
		Logger.Warn(fmt.Sprintf("GitHub OAuth token exchange failed: %v", tokenData["error"]))
		return redirect(c, "/?auth_error=token_exchange_failed")
	}
	ureq, _ := http.NewRequestWithContext(ctx, http.MethodGet, userURL, nil)
	ureq.Header.Set("Accept", "application/vnd.github+json")
	ureq.Header.Set("Authorization", "Bearer "+accessToken)
	ureq.Header.Set("X-GitHub-Api-Version", "2022-11-28")
	ghUser, err := doJSON(ureq)
	if err != nil {
		Logger.Error("GitHub OAuth error: " + err.Error())
		return redirect(c, "/?auth_error=github_api_error")
	}
	login := jx.Str(ghUser["login"])
	if login == "" {
		return redirect(c, "/?auth_error=no_login")
	}
	admin := Auth.IsAdminLogin(login)
	if !admin && !jx.GetBoolDef(cfg, "allow_all_users", true) {
		return redirect(c, "/?auth_error=not_allowed")
	}
	name := jx.Str(ghUser["name"])
	if name == "" {
		name = login
	}
	token := Auth.CreateSession(login, name, jx.Str(ghUser["avatar_url"]), "github", admin, ghUser["id"])
	Logger.Info(fmt.Sprintf("[auth] GitHub login OK: user=%s admin=%v origin=%s secure_cookie=%v",
		login, admin, forwardedOrigin(c.R), strings.HasPrefix(forwardedOrigin(c.R), "https://")))
	setSessionCookie(c.W, c.R, token)
	return redirect(c, "/?login=github")
}

// doJSON performs a request and decodes a JSON object, failing on non-2xx.
func doJSON(req *http.Request) (jx.M, error) {
	resp, err := oauthHTTP.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("HTTP %d from %s", resp.StatusCode, req.URL)
	}
	var v any
	if err := jsonDecode(resp.Body, &v); err != nil {
		return nil, err
	}
	m := jx.Map(v)
	if m == nil {
		m = jx.M{}
	}
	return m, nil
}

func getGithubConfig(c *Ctx) any {
	cfg := Auth.OAuthConfig()
	secret := jx.Str(cfg["client_secret"])
	masked := ""
	if secret != "" {
		tail := secret
		if len(tail) > 4 {
			tail = tail[len(tail)-4:]
		}
		masked = strings.Repeat("*", 8) + tail
	}
	host := jx.Str(cfg["host"])
	if host == "" {
		host = githost.DefaultHost
	}
	admins := jx.GetList(cfg, "admins")
	if admins == nil {
		admins = jx.L{}
	}
	return jx.M{
		"client_id":            jx.Str(cfg["client_id"]),
		"client_secret_set":    secret != "",
		"client_secret_masked": masked,
		"callback_url":         jx.Str(cfg["callback_url"]),
		"admins":               admins,
		"allow_all_users":      jx.GetBoolDef(cfg, "allow_all_users", true),
		"host":                 host,
		"enabled":              Auth.GithubEnabled(),
	}
}

func updateGithubConfig(c *Ctx) any {
	body, r := c.BindMap()
	if r != nil {
		return r
	}
	updates := jx.M{}
	for k, v := range body {
		if v != nil {
			updates[k] = v
		}
	}
	if !jx.Truthy(updates["client_secret"]) {
		delete(updates, "client_secret")
	}
	if _, err := Auth.SaveOAuthConfig(updates); err != nil {
		return jx.M{"error": err.Error()}
	}
	if _, ok := updates["host"]; ok {
		Engine.ScheduleCLIHostRefresh()
	}
	return getGithubConfig(c)
}
