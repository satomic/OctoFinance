package app

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/satomic/octofinance/backend-go/internal/ghapi"
	"github.com/satomic/octofinance/backend-go/internal/githost"
	"github.com/satomic/octofinance/backend-go/internal/jx"
)

// Credential health of the data-sync PATs: every sync starts by asking GitHub
// who each PAT belongs to, so an expired/revoked token is reported in the UI.

const (
	expiryWarningDays = 7
	expiryHeader      = "github-authentication-token-expiration"
	networkAttempts   = 2
	networkRetryDelay = 2 * time.Second
)

// BlockingStates stop a PAT from syncing anything.
var BlockingStates = []string{"invalid", "forbidden", "unreachable"}

func isBlocking(state string) bool {
	for _, s := range BlockingStates {
		if s == state {
			return true
		}
	}
	return false
}

// parseExpiry parses e.g. "2026-10-20 08:00:00 UTC".
func parseExpiry(value string) (time.Time, bool) {
	value = strings.TrimSpace(value)
	if value == "" {
		return time.Time{}, false
	}
	for _, layout := range []string{"2006-01-02 15:04:05 -0700", "2006-01-02 15:04:05 MST", "2006-01-02 15:04:05"} {
		if t, err := time.Parse(layout, value); err == nil {
			return t.UTC(), true
		}
	}
	return time.Time{}, false
}

// classifyCredential turns a GET /user outcome into a credential state. status 0 = unreachable.
func classifyCredential(status int, detail, expiry string) jx.M {
	now := time.Now().UTC()
	expiresAt, hasExpiry := parseExpiry(expiry)
	var state string
	switch {
	case status == 0:
		state = "unreachable"
	case status == 401:
		state = "invalid"
		if detail == "" {
			detail = "Bad credentials"
		}
	case status == 403:
		state = "forbidden"
	case status >= 200 && status < 300:
		state = "ok"
		if hasExpiry && expiresAt.Sub(now) <= expiryWarningDays*24*time.Hour {
			state = "expiring"
		}
	default:
		state = "unreachable"
	}
	detail = strings.TrimSpace(detail)
	if r := []rune(detail); len(r) > 300 {
		detail = string(r[:300])
	}
	var st, exp any
	if status != 0 {
		st = status
	}
	if hasExpiry {
		exp = jx.ISO(expiresAt)
	}
	return jx.M{
		"state":      state,
		"status":     st,
		"detail":     detail,
		"expires_at": exp,
		"checked_at": jx.ISO(now),
	}
}

// CredCheckToken checks one token against its host. The result carries "login" on success.
func CredCheckToken(ctx context.Context, token, host string) jx.M {
	if host == "" {
		host = githost.DefaultHost
	}
	api := ghapi.New(token, githost.APIBase(host))
	var resp *ghapi.Response
	for attempt := 0; attempt < networkAttempts; attempt++ {
		r, err := api.Get(ctx, "/user", nil, nil)
		if err == nil {
			resp = r
			break
		}
		if attempt+1 == networkAttempts {
			return classifyCredential(0, fmt.Sprintf("%T: %v", errors.Unwrap(err), err), "")
		}
		time.Sleep(networkRetryDelay)
	}
	detail := ""
	if !resp.OK() {
		detail = ghapi.ErrorDetail(resp)
	}
	result := classifyCredential(resp.Status, detail, resp.Header.Get(expiryHeader))
	if resp.OK() {
		result["login"] = jx.GetStr(jx.Map(resp.JSON()), "login")
	}
	return result
}

// CredDescribe is one log line explaining a credential problem.
func CredDescribe(pat jx.M, cred jx.M) string {
	label := jx.Str(pat["label"])
	if label == "" {
		label = jx.Str(pat["user_login"])
	}
	if label == "" {
		label = jx.Str(pat["id"])
	}
	name := fmt.Sprintf("PAT '%s' (%s)", label, jx.OrStr(pat, "host", githost.DefaultHost))
	detail := ""
	if d := jx.Str(cred["detail"]); d != "" {
		detail = ": " + d
	}
	switch jx.Str(cred["state"]) {
	case "invalid":
		return fmt.Sprintf("%s was rejected by GitHub (HTTP 401%s). The token has expired or been revoked; replace it in Settings > PAT Manager", name, detail)
	case "forbidden":
		return fmt.Sprintf("%s is not allowed to call GitHub (HTTP 403%s). Check its permissions, SSO authorization and rate limits", name, detail)
	case "unreachable":
		return fmt.Sprintf("%s could not reach GitHub%s", name, detail)
	case "expiring":
		exp := jx.Str(cred["expires_at"])
		if len(exp) > 10 {
			exp = exp[:10]
		}
		return fmt.Sprintf("%s expires on %s; renew it before then or syncs will fail", name, exp)
	}
	return name + " is valid"
}

// CredCheckAll checks every PAT, stores the result and logs anything that needs attention.
func CredCheckAll(ctx context.Context, logFn LogFn) []jx.M {
	results := []jx.M{}
	for _, pat := range Pats.GetAll() {
		cred := CredCheckToken(ctx, jx.Str(pat["token"]), jx.OrStr(pat, "host", githost.DefaultHost))
		delete(cred, "login")
		Pats.Update(jx.Str(pat["id"]), jx.M{"credential": cred})
		results = append(results, jx.Merge(jx.M{"pat_id": pat["id"]}, cred))
		state := jx.Str(cred["state"])
		if state != "ok" {
			level := "warn"
			if isBlocking(state) {
				level = "error"
			}
			msg := CredDescribe(pat, cred)
			Logger.Warn("[credentials] " + msg)
			if logFn != nil {
				logFn(level, msg)
			}
		}
	}
	return results
}

// CredRecordFailure records a credential failure seen outside a health check.
func CredRecordFailure(patID string, err error) {
	var he *ghapi.HTTPError
	var te *ghapi.TransportError
	var cred jx.M
	switch {
	case errors.As(err, &he):
		cred = classifyCredential(he.Resp.Status, ghapi.ErrorDetail(he.Resp), he.Resp.Header.Get(expiryHeader))
	case errors.As(err, &te):
		cred = classifyCredential(0, strings.TrimRight(fmt.Sprintf("%T: %v", te.Err, te.Err), ": "), "")
	default:
		return
	}
	Pats.Update(patID, jx.M{"credential": cred})
}

// CredProblems lists PATs whose last check needs admin action.
func CredProblems() []jx.M {
	out := []jx.M{}
	for _, pat := range Pats.GetAll() {
		cred := jx.GetMap(pat, "credential")
		state := jx.Str(cred["state"])
		if isBlocking(state) || state == "expiring" {
			out = append(out, jx.Merge(jx.M{
				"pat_id":     pat["id"],
				"label":      jx.GetStr(pat, "label"),
				"user_login": jx.GetStr(pat, "user_login"),
				"host":       jx.OrStr(pat, "host", githost.DefaultHost),
			}, cred))
		}
	}
	return out
}

// CredPreflight runs before every sync: check credentials, re-discover PATs that now work.
func CredPreflight(ctx context.Context, logFn LogFn) {
	results := CredCheckAll(ctx, logFn)
	discovered := APIs.DiscoveredUsers()
	n := 0
	for _, r := range results {
		state := jx.Str(r["state"])
		if (state == "ok" || state == "expiring") && discovered[jx.Str(r["pat_id"])] == nil {
			n++
		}
	}
	if n > 0 {
		logFn("info", fmt.Sprintf("Re-discovering organizations for %d PAT(s) that were not discovered at startup", n))
		APIs.Rebuild(ctx)
	}
}
