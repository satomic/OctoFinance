package app

import (
	"sort"
	"strings"

	"github.com/satomic/octofinance/backend-go/internal/jx"
)

// Every GitHub user known to OctoFinance, for the frontend's demo mode
// (Python services/user_roster.py). Demo mode aliases user logins in the
// browser and needs to know which strings are logins.

// BuildUserRoster returns sorted [{login, name}] for every user in the synced data.
func BuildUserRoster() []jx.M {
	users := map[string]jx.M{}
	add := func(login any, name any) {
		s, ok := login.(string)
		if !ok || strings.TrimSpace(s) == "" {
			return
		}
		s = strings.TrimSpace(s)
		key := strings.ToLower(s)
		entry, exists := users[key]
		if !exists {
			entry = jx.M{"login": s, "name": ""}
			users[key] = entry
		}
		if n, ok := name.(string); ok && strings.TrimSpace(n) != "" && strings.TrimSpace(n) != s {
			entry["name"] = strings.TrimSpace(n)
		}
	}

	l := newDataLoader()
	each := func(category string, collect func(snapshot jx.M)) {
		keys, all := l.allLatest(category)
		for _, k := range keys {
			if snap := jx.Map(all[k]); snap != nil {
				collect(snap)
			}
		}
	}
	each("seats", func(s jx.M) {
		for _, seat := range jx.GetMaps(s, "seats") {
			add(jx.GetMap(seat, "assignee")["login"], "")
		}
	})
	each("usage_users", func(s jx.M) {
		for _, rec := range jx.GetMaps(s, "records") {
			add(rec["user_login"], "")
		}
	})
	each("enterprise_teams", func(s jx.M) {
		for _, team := range jx.GetMaps(s, "teams") {
			for _, m := range jx.GetMaps(team, "members") {
				add(m["login"], jx.GetOr(m, "name", ""))
			}
		}
	})
	each("cost_centers", func(s jx.M) {
		for _, center := range jx.GetMaps(s, "cost_centers") {
			for _, m := range jx.GetList(center, "members") {
				if mm := jx.Map(m); mm != nil {
					add(mm["login"], "")
				} else {
					add(m, "")
				}
			}
			for _, r := range jx.GetMaps(center, "resources") {
				if t, ok := r["type"].(string); ok && t == "User" {
					add(r["name"], "")
				}
			}
		}
	})
	each("budgets", func(s jx.M) {
		for _, b := range jx.GetMaps(s, "budgets") {
			if sc, ok := b["budget_scope"].(string); ok && sc == "user" {
				add(b["budget_entity_name"], "")
				add(b["user"], "")
			}
		}
	})
	for _, t := range []string{CSVTypeAI, CSVTypeUsage} {
		for _, r := range LoadAllCSVRecords(t) {
			if v, ok := r["username"]; ok {
				add(v, "")
			}
		}
	}
	for _, req := range LoadBudgetRequests() {
		add(req["user_login"], jx.GetOr(req, "user_name", ""))
		add(req["reviewed_by"], "")
		for _, h := range jx.GetMaps(req, "history") {
			add(h["by"], "")
		}
	}
	owners := LoadCCOwners()
	for _, ent := range jx.SortedKeys(owners) {
		centers := jx.Map(owners[ent])
		for _, cid := range jx.SortedKeys(centers) {
			grants := jx.Map(centers[cid])
			for _, login := range jx.SortedKeys(grants) {
				add(login, "")
				add(jx.Map(grants[login])["granted_by"], "")
			}
		}
	}
	for _, pat := range Pats.GetAll() {
		add(pat["user_login"], "")
	}
	for _, a := range jx.GetList(Auth.OAuthConfig(), "admins") {
		add(a, "")
	}
	localAdmin := strings.ToLower(jx.OrStr(Auth.LoadCredentials(), "username", ""))
	delete(users, localAdmin)

	out := make([]jx.M, 0, len(users))
	for _, u := range users {
		out = append(out, u)
	}
	sort.Slice(out, func(i, j int) bool {
		a, b := strings.ToLower(jx.Str(out[i]["login"])), strings.ToLower(jx.Str(out[j]["login"]))
		return a < b
	})
	return out
}
