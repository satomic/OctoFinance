package app

import (
	"crypto/pbkdf2"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"encoding/hex"
	"os"
	"strings"
	"sync"
	"time"

	"github.com/satomic/octofinance/backend-go/internal/githost"
	"github.com/satomic/octofinance/backend-go/internal/jx"
)

// Authentication store, JSON-persisted under data/:
//   auth.json              local super-admin credentials (username + hash)
//   oauth.json             GitHub OAuth App configuration + admin allow-list
//   auth_sessions.json     active login sessions (survive restarts)
//   auth_oauth_states.json OAuth CSRF states

const (
	sessionTTL    = 7 * 24 * time.Hour
	oauthStateTTL = 10 * time.Minute
)

var defaultOAuth = jx.M{
	"client_id":       "",
	"client_secret":   "",
	"callback_url":    "",
	"admins":          jx.L{},
	"allow_all_users": true,
	"host":            "",
}

// AuthStore holds credentials, OAuth config and sessions.
type AuthStore struct {
	mu            sync.Mutex
	sessions      map[string]jx.M
	sessionsMtime time.Time
	oauthStates   map[string]float64
}

// Auth is the global auth store.
var Auth = &AuthStore{sessions: map[string]jx.M{}, oauthStates: map[string]float64{}}

func authFile() string     { return dataPath("auth.json") }
func oauthFile() string    { return dataPath("oauth.json") }
func sessionsFile() string { return dataPath("auth_sessions.json") }
func statesFile() string   { return dataPath("auth_oauth_states.json") }

func nowUnix() float64 { return float64(time.Now().UnixNano()) / 1e9 }

// LoadCredentials returns the local admin credentials or nil.
func (a *AuthStore) LoadCredentials() jx.M {
	return jx.Map(jx.ReadJSONOr(authFile(), nil))
}

func hashPassword(password string, salt []byte) string {
	key, _ := pbkdf2.Key(sha256.New, password, salt, 100_000, 32)
	return hex.EncodeToString(key)
}

// SaveCredentials stores a new local admin.
func (a *AuthStore) SaveCredentials(username, password string) error {
	salt := make([]byte, 32)
	_, _ = rand.Read(salt)
	return jx.WriteJSON(authFile(), jx.M{
		"username":      username,
		"password_hash": hashPassword(password, salt),
		"salt":          hex.EncodeToString(salt),
	})
}

// VerifyPassword checks a password against the stored hash.
func (a *AuthStore) VerifyPassword(password, storedHash, saltHex string) bool {
	salt, err := hex.DecodeString(saltHex)
	if err != nil {
		return false
	}
	return subtle.ConstantTimeCompare([]byte(hashPassword(password, salt)), []byte(storedHash)) == 1
}

// OAuthConfig returns the OAuth config: file values win, env vars are the fallback.
func (a *AuthStore) OAuthConfig() jx.M {
	cfg := jx.Merge(defaultOAuth, jx.Map(jx.ReadJSONOr(oauthFile(), jx.M{})))
	for key, env := range map[string]string{
		"client_id":     "GITHUB_OAUTH_CLIENT_ID",
		"client_secret": "GITHUB_OAUTH_CLIENT_SECRET",
		"callback_url":  "GITHUB_OAUTH_CALLBACK_URL",
		"host":          "GITHUB_OAUTH_HOST",
	} {
		if !jx.Truthy(cfg[key]) {
			cfg[key] = os.Getenv(env)
		}
	}
	admins := jx.L{}
	for _, v := range jx.GetList(cfg, "admins") {
		if s := strings.TrimSpace(jx.Str(v)); s != "" {
			admins = append(admins, s)
		}
	}
	cfg["admins"] = admins
	return cfg
}

// SaveOAuthConfig applies updates (nil values skipped). Returns an error for a bad host.
func (a *AuthStore) SaveOAuthConfig(updates jx.M) (jx.M, error) {
	cfg := jx.Merge(defaultOAuth, jx.Map(jx.ReadJSONOr(oauthFile(), jx.M{})))
	for key, value := range updates {
		if value == nil {
			continue
		}
		if _, known := defaultOAuth[key]; !known {
			continue
		}
		switch key {
		case "admins":
			admins := jx.L{}
			for _, v := range jx.List(value) {
				if s := strings.TrimSpace(jx.Str(v)); s != "" {
					admins = append(admins, s)
				}
			}
			cfg[key] = admins
		case "allow_all_users":
			cfg[key] = jx.Truthy(value)
		case "host":
			s := strings.TrimSpace(jx.Str(value))
			if s == "" {
				cfg[key] = ""
			} else {
				h, err := githost.Normalize(s)
				if err != nil {
					return nil, err
				}
				cfg[key] = h
			}
		default:
			cfg[key] = strings.TrimSpace(jx.Str(value))
		}
	}
	if err := jx.WriteJSON(oauthFile(), cfg); err != nil {
		return nil, err
	}
	return a.OAuthConfig(), nil
}

// GithubEnabled reports whether OAuth is configured.
func (a *AuthStore) GithubEnabled() bool {
	cfg := a.OAuthConfig()
	return jx.Truthy(cfg["client_id"]) && jx.Truthy(cfg["client_secret"])
}

// IsAdminLogin reports whether a GitHub login gets the administrator experience:
// it is on the allow-list or owns one of the configured PATs.
func (a *AuthStore) IsAdminLogin(login string) bool {
	if login == "" {
		return false
	}
	target := strings.ToLower(strings.TrimSpace(login))
	for _, admin := range jx.Strings(a.OAuthConfig()["admins"]) {
		if strings.ToLower(admin) == target {
			return true
		}
	}
	for _, u := range APIs.DiscoveredUsers() {
		if strings.ToLower(jx.GetStr(u, "login")) == target {
			return true
		}
	}
	return false
}

func (a *AuthStore) loadStates() map[string]float64 {
	raw := jx.Map(jx.ReadJSONOr(statesFile(), jx.M{}))
	now := nowUnix()
	out := map[string]float64{}
	for s, t := range raw {
		if f, ok := t.(float64); ok && now-f < oauthStateTTL.Seconds() {
			out[s] = f
		}
	}
	return out
}

func (a *AuthStore) saveStates(states map[string]float64) {
	m := jx.M{}
	for k, v := range states {
		m[k] = v
	}
	_ = jx.WriteJSON(statesFile(), m)
}

// CreateOAuthState issues a CSRF state token.
func (a *AuthStore) CreateOAuthState() string {
	b := make([]byte, 24)
	_, _ = rand.Read(b)
	state := base64.RawURLEncoding.EncodeToString(b)
	a.mu.Lock()
	defer a.mu.Unlock()
	states := a.loadStates()
	now := nowUnix()
	for k, v := range a.oauthStates {
		if now-v < oauthStateTTL.Seconds() {
			states[k] = v
		}
	}
	states[state] = now
	a.oauthStates = states
	a.saveStates(states)
	return state
}

// ConsumeOAuthState validates and removes a state token.
func (a *AuthStore) ConsumeOAuthState(state string) bool {
	if state == "" {
		return false
	}
	a.mu.Lock()
	defer a.mu.Unlock()
	states := a.loadStates()
	for k, v := range a.oauthStates {
		states[k] = v
	}
	_, found := states[state]
	delete(states, state)
	a.oauthStates = states
	a.saveStates(states)
	return found
}

func (a *AuthStore) loadSessionsLocked() {
	raw := jx.Map(jx.ReadJSONOr(sessionsFile(), jx.M{}))
	now := nowUnix()
	a.sessions = map[string]jx.M{}
	for token, info := range raw {
		m := jx.Map(info)
		if m != nil && now-jx.Float(m["created_at"]) < sessionTTL.Seconds() {
			a.sessions[token] = m
		}
	}
	if st, err := os.Stat(sessionsFile()); err == nil {
		a.sessionsMtime = st.ModTime()
	} else {
		a.sessionsMtime = time.Time{}
	}
}

func (a *AuthStore) persistSessionsLocked() {
	m := jx.M{}
	for k, v := range a.sessions {
		m[k] = v
	}
	_ = jx.WriteJSON(sessionsFile(), m)
	if st, err := os.Stat(sessionsFile()); err == nil {
		a.sessionsMtime = st.ModTime()
	}
}

// LoadSessions reads persisted sessions at startup.
func (a *AuthStore) LoadSessions() {
	a.mu.Lock()
	defer a.mu.Unlock()
	a.loadSessionsLocked()
}

// CreateSession starts a session and returns its token.
func (a *AuthStore) CreateSession(login, name, avatarURL, authType string, isAdmin bool, githubID any) string {
	token := randHex(32)
	if name == "" {
		name = login
	}
	a.mu.Lock()
	defer a.mu.Unlock()
	a.sessions[token] = jx.M{
		"login":      login,
		"name":       name,
		"avatar_url": avatarURL,
		"auth_type":  authType,
		"is_admin":   isAdmin,
		"github_id":  githubID,
		"created_at": nowUnix(),
	}
	a.persistSessionsLocked()
	return token
}

// GetSession returns the session payload for a token, or nil.
func (a *AuthStore) GetSession(token string) jx.M {
	if token == "" {
		return nil
	}
	a.mu.Lock()
	info, ok := a.sessions[token]
	if !ok {
		// Another process (e.g. the other backend) may have created it
		if st, err := os.Stat(sessionsFile()); err == nil && !st.ModTime().Equal(a.sessionsMtime) {
			a.loadSessionsLocked()
		}
		info, ok = a.sessions[token]
	}
	if !ok || info == nil {
		a.mu.Unlock()
		return nil
	}
	if nowUnix()-jx.Float(info["created_at"]) >= sessionTTL.Seconds() {
		delete(a.sessions, token)
		a.persistSessionsLocked()
		a.mu.Unlock()
		return nil
	}
	info = jx.Copy(info)
	a.mu.Unlock()
	// SSO admin status is re-evaluated on every request so allow-list changes apply immediately.
	if jx.Str(info["auth_type"]) == "github" {
		info["is_admin"] = a.IsAdminLogin(jx.Str(info["login"]))
	}
	return info
}

// DestroySession logs a token out.
func (a *AuthStore) DestroySession(token string) {
	if token == "" {
		return
	}
	a.mu.Lock()
	defer a.mu.Unlock()
	if _, ok := a.sessions[token]; ok {
		delete(a.sessions, token)
		a.persistSessionsLocked()
	}
}
