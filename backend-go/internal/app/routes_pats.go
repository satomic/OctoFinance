package app

import (
	"context"
	"fmt"
	"strings"

	"github.com/satomic/octofinance/backend-go/internal/githost"
	"github.com/satomic/octofinance/backend-go/internal/jx"
)

// PAT management and app settings.

func init() { registerRoutes(registerPATRoutes) }

func registerPATRoutes(r *Router) {
	r.Handle("GET /api/pats", func(c *Ctx) any { return jx.M{"pats": Pats.GetAllMasked()} })
	r.Handle("POST /api/pats", addPAT)
	r.Handle("PUT /api/pats/{pat_id}", updatePAT)
	r.Handle("DELETE /api/pats/{pat_id}", deletePAT)
	r.Handle("GET /api/settings", func(c *Ctx) any { return Pats.GetSettings() })
	r.Handle("PUT /api/settings", updateSettings)
}

// resolveHostAndSlugs normalizes the PAT host and enterprise slugs (slugs may be enterprise URLs).
func resolveHostAndSlugs(hostInput string, rawSlugs []string) (string, []string, error) {
	host := ""
	if strings.TrimSpace(hostInput) != "" {
		h, err := githost.Normalize(hostInput)
		if err != nil {
			return "", nil, err
		}
		host = h
	}
	slugs := []string{}
	for _, raw := range rawSlugs {
		raw = strings.TrimSpace(raw)
		if raw == "" {
			continue
		}
		urlHost, slug, ok, err := githost.ParseEnterpriseURL(raw)
		if err != nil {
			return "", nil, err
		}
		if ok {
			if host != "" && urlHost != host {
				return "", nil, fmt.Errorf("Enterprise URL host '%s' does not match the PAT host '%s'.", urlHost, host)
			}
			host = urlHost
			raw = slug
		}
		slugs = append(slugs, raw)
	}
	if host == "" {
		host = githost.DefaultHost
	}
	return host, slugs, nil
}

func maskedPAT(id string) any {
	for _, p := range Pats.GetAllMasked() {
		if jx.Str(p["id"]) == id {
			return p
		}
	}
	return nil
}

func addPAT(c *Ctx) any {
	var body struct {
		Label                *string  `json:"label"`
		Token                *string  `json:"token"`
		EnterpriseSlugs      []string `json:"enterprise_slugs"`
		IncludeOrganizations *bool    `json:"include_organizations"`
		Host                 string   `json:"host"`
	}
	if r := c.Bind(&body); r != nil {
		return r
	}
	if body.Label == nil || body.Token == nil {
		missing := []string{}
		if body.Label == nil {
			missing = append(missing, "label")
		}
		if body.Token == nil {
			missing = append(missing, "token")
		}
		return Missing(missing...)
	}
	token := strings.TrimSpace(*body.Token)
	label := strings.TrimSpace(*body.Label)
	if token == "" {
		return HTTPError(400, "Token is required")
	}
	host, slugs, err := resolveHostAndSlugs(body.Host, body.EnterpriseSlugs)
	if err != nil {
		return HTTPError(400, err.Error())
	}
	includeOrgs := true
	if body.IncludeOrganizations != nil {
		includeOrgs = *body.IncludeOrganizations
	}
	pat, err := Pats.Add(label, token, slugs, includeOrgs, host)
	if err != nil {
		return HTTPError(400, err.Error())
	}
	patID := jx.Str(pat["id"])
	user, err := APIs.AddAndDiscover(c.R.Context(), patID)
	if err != nil {
		Pats.Remove(patID)
		return HTTPError(400, err.Error())
	}
	Engine.ScheduleCLIHostRefresh()

	updated := Pats.FindByID(patID)
	orgs := jx.Strings(jx.Get(updated, "orgs"))
	hasEnterprises := false
	for _, e := range APIs.AllEnterprises() {
		if jx.Str(e["pat_id"]) == patID {
			hasEnterprises = true
			break
		}
	}
	if len(orgs) > 0 || hasEnterprises {
		Syncs.RunInBackground(func(ctx context.Context, logFn LogFn) {
			for _, org := range orgs {
				Collector.SyncOrg(ctx, org, logFn)
			}
			Collector.SyncEnterprises(ctx, logFn)
		}, "pat_change")
	}
	return jx.M{"pat": maskedPAT(patID), "user": jx.GetStr(user, "login")}
}

func updatePAT(c *Ctx) any {
	patID := c.Path("pat_id")
	var body struct {
		Label                *string `json:"label"`
		IncludeOrganizations *bool   `json:"include_organizations"`
		Token                *string `json:"token"`
	}
	if r := c.Bind(&body); r != nil {
		return r
	}
	existing := Pats.FindByID(patID)
	if existing == nil {
		return HTTPError(404, "PAT not found")
	}
	tokenChanged := false
	if body.Token != nil && strings.TrimSpace(*body.Token) != jx.Str(existing["token"]) {
		token := strings.TrimSpace(*body.Token)
		if token == "" {
			return HTTPError(400, "Token is required")
		}
		cred := CredCheckToken(c.R.Context(), token, jx.Str(existing["host"]))
		if isBlocking(jx.Str(cred["state"])) {
			return HTTPError(400, CredDescribe(existing, cred))
		}
		newLogin := jx.Str(cred["login"])
		oldLogin := jx.Str(existing["user_login"])
		if oldLogin != "" && newLogin != "" && !strings.EqualFold(newLogin, oldLogin) {
			Syncs.Log("warn", fmt.Sprintf("PAT '%s' now belongs to %s (was %s)", jx.Str(existing["label"]), newLogin, oldLogin))
		}
		if _, err := Pats.SetToken(patID, token); err != nil {
			return HTTPError(400, err.Error())
		}
		delete(cred, "login")
		Pats.Update(patID, jx.M{"credential": cred})
		Syncs.Log("info", fmt.Sprintf("PAT '%s' token replaced", jx.Str(existing["label"])))
		tokenChanged = true
	}
	fields := jx.M{}
	if body.Label != nil {
		fields["label"] = strings.TrimSpace(*body.Label)
	}
	includeChanged := body.IncludeOrganizations != nil &&
		*body.IncludeOrganizations != jx.GetBoolDef(existing, "include_organizations", true)
	if body.IncludeOrganizations != nil {
		fields["include_organizations"] = *body.IncludeOrganizations
	}
	if len(fields) > 0 {
		if Pats.Update(patID, fields) == nil {
			return HTTPError(404, "PAT not found")
		}
	}
	if includeChanged || tokenChanged {
		APIs.Rebuild(c.R.Context())
		Syncs.RunInBackground(func(ctx context.Context, logFn LogFn) {
			Collector.SyncAll(ctx, logFn)
		}, "pat_change")
	}
	return jx.M{"pat": maskedPAT(patID)}
}

func deletePAT(c *Ctx) any {
	patID := c.Path("pat_id")
	if Pats.FindByID(patID) == nil {
		return HTTPError(404, "PAT not found")
	}
	APIs.RemoveAPI(patID)
	Pats.Remove(patID)
	Engine.ScheduleCLIHostRefresh()
	return jx.M{"deleted": true, "pat_id": patID}
}

func updateSettings(c *Ctx) any {
	body, r := c.BindMap()
	if r != nil {
		return r
	}
	updates := jx.M{}
	if v, ok := body["auto_sync_on_startup"]; ok && v != nil {
		b, isBool := v.(bool)
		if !isBool {
			return JSONStatus(422, jx.M{"detail": jx.L{jx.M{"type": "bool_type", "loc": jx.L{"body", "auto_sync_on_startup"}, "msg": "Input should be a valid boolean"}}})
		}
		updates["auto_sync_on_startup"] = b
	}
	if v, ok := body["sync_cron"]; ok && v != nil {
		updates["sync_cron"] = jx.Str(v)
	}
	for key, bounds := range map[string][2]float64{
		"csv_fetch_poll_seconds":    {10, 600},
		"csv_fetch_timeout_minutes": {5, 1440},
	} {
		v, ok := body[key]
		if !ok || v == nil {
			continue
		}
		f, isNum := jx.FloatOK(v)
		if !isNum || f != float64(int64(f)) {
			return JSONStatus(422, jx.M{"detail": jx.L{jx.M{"type": "int_type", "loc": jx.L{"body", key}, "msg": "Input should be a valid integer"}}})
		}
		if f < bounds[0] {
			return JSONStatus(422, jx.M{"detail": jx.L{jx.M{
				"type": "greater_than_equal", "loc": jx.L{"body", key},
				"msg":   fmt.Sprintf("Input should be greater than or equal to %v", bounds[0]),
				"input": v, "ctx": jx.M{"ge": bounds[0]},
			}}})
		}
		if f > bounds[1] {
			return JSONStatus(422, jx.M{"detail": jx.L{jx.M{
				"type": "less_than_equal", "loc": jx.L{"body", key},
				"msg":   fmt.Sprintf("Input should be less than or equal to %v", bounds[1]),
				"input": v, "ctx": jx.M{"le": bounds[1]},
			}}})
		}
		updates[key] = int64(f)
	}
	settings := Pats.UpdateSettings(updates)
	if v, ok := body["sync_cron"]; ok && v != nil {
		Syncs.StopCronScheduler()
		if expr := strings.TrimSpace(jx.Str(v)); expr != "" {
			Syncs.StartCronScheduler(expr, RunFullSync)
		}
	}
	return settings
}
