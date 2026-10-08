package app

// Port of backend/app/tools/enterprise_team_tools.py: GitHub Enterprise Teams
// tools. Read tools use the synced roster cache
// (enterprise_teams/{slug}_latest.json); write tools call the REST API.

import (
	"fmt"
	"net/http"
	"sort"
	"strings"

	copilot "github.com/github/copilot-sdk/go"

	"github.com/satomic/octofinance/backend-go/internal/ghapi"
	"github.com/satomic/octofinance/backend-go/internal/jx"
)

func init() { registerTools(entTeamTools) }

const (
	entTeamEnterpriseDesc = "Enterprise slug. Leave empty to auto-detect from synced data."
	entTeamSlugDesc       = "Enterprise team slug, including the 'ent:' prefix (e.g. 'ent:platform')."
)

func entTeamEnterpriseParam() P {
	return P{Name: "enterprise", Type: "string", Default: "", Desc: entTeamEnterpriseDesc}
}

func entTeamTools(tc *ToolCtx) []copilot.Tool {
	ctx := tc.Context()
	collector := tc.Collector

	loadEnterprises := func() []jx.M {
		if collector == nil {
			return []jx.M{}
		}
		data, ok := collector.LoadLatest("enterprise", "all").([]any)
		if !ok {
			return []jx.M{}
		}
		return jx.Maps(data)
	}

	resolveEnterprise := func(requested string) string {
		if requested != "" {
			return requested
		}
		enterprises := APIs.AllEnterprises()
		if len(enterprises) == 1 {
			return jx.Str(enterprises[0]["slug"])
		}
		if len(enterprises) > 1 {
			return ""
		}
		enterprises = loadEnterprises()
		if len(enterprises) == 1 {
			return jx.Str(enterprises[0]["slug"])
		}
		return ""
	}

	enterpriseError := func() string {
		enterprises := loadEnterprises()
		if all := APIs.AllEnterprises(); len(all) > 0 {
			enterprises = all
		}
		if len(enterprises) > 0 {
			slugs := []string{}
			for _, e := range enterprises {
				slugs = append(slugs, jx.Str(e["slug"]))
			}
			return jx.Dumps(jx.M{"error": "Multiple enterprises available. Please specify the enterprise slug. " +
				"Available: " + budgetToolPyStrList(slugs)})
		}
		return jx.Dumps(jx.M{"error": "No enterprise data found. Run Sync Data first so enterprise " +
			"information can be discovered, or provide the enterprise slug explicitly."})
	}

	// loadTeamData returns the cached roster, nil when missing/empty (Python `if not team_data`).
	loadTeamData := func(enterprise string) jx.M {
		if collector == nil {
			return nil
		}
		data := collector.LoadLatestMap("enterprise_teams", enterprise)
		if len(data) == 0 {
			return nil
		}
		return data
	}

	teamsOf := func(teamData jx.M) []jx.M { return jx.Maps(jx.GetOr(teamData, "teams", jx.L{})) }

	findTeam := func(teamData jx.M, slug string) jx.M {
		wanted := strings.ToLower(strings.TrimSpace(slug))
		for _, t := range teamsOf(teamData) {
			if strings.ToLower(jx.Str(jx.GetOr(t, "slug", ""))) == wanted || strings.ToLower(jx.Str(jx.GetOr(t, "name", ""))) == wanted {
				return t
			}
		}
		return nil
	}

	slugList := func(teamData jx.M) jx.L {
		out := jx.L{}
		for _, t := range teamsOf(teamData) {
			out = append(out, jx.GetOr(t, "slug", ""))
		}
		return out
	}

	noCacheError := func(enterprise string) string {
		return jx.Dumps(jx.M{"error": fmt.Sprintf("No enterprise team data cached for '%s'. "+
			"Run Sync Data (or the 'enterprise_teams' dataset sync) first.", enterprise)})
	}

	noAPI := func(enterprise string) string {
		return jx.Dumps(jx.M{"error": fmt.Sprintf("No API client found for enterprise '%s'.", enterprise)})
	}

	// writeError maps the failure responses of the write endpoints ("" = none).
	writeError := func(r *ghapi.Response, subject string) string {
		switch {
		case r.Status == 404:
			return jx.Dumps(jx.M{"error": subject + " not found."})
		case r.Status == 401 || r.Status == 403:
			return jx.Dumps(jx.M{"error": "Forbidden — enterprise team writes need a classic PAT with the " +
				"admin:enterprise scope. Fine-grained and GitHub App tokens are rejected."})
		case r.Status == 422:
			return jx.Dumps(jx.M{"error": "Validation failed: " + r.Text()})
		}
		return ""
	}

	// send performs a write request; unexpected failures raise (tool failure)
	// like httpx's raise_for_status in the Python tool.
	send := func(api *ghapi.Client, method, path string, body any, subject string) (*ghapi.Response, string) {
		r, err := api.Do(ctx, method, path, nil, body, nil)
		if err != nil {
			panic(err.Error())
		}
		if msg := writeError(r, subject); msg != "" {
			return r, msg
		}
		if err := ghapi.RaiseForStatus(r); err != nil {
			panic(err.Error())
		}
		return r, ""
	}

	teamParam := func(desc string) P {
		return P{Name: "team_slug", Type: "string", Required: true, Desc: desc}
	}

	orgsParams := []P{
		entTeamEnterpriseParam(),
		teamParam(entTeamSlugDesc),
		{Name: "organizations", Type: "array", Items: "string", Desc: "Organization login/slug names to assign or unassign"},
	}
	membersParams := []P{
		entTeamEnterpriseParam(),
		teamParam(entTeamSlugDesc),
		{Name: "usernames", Type: "array", Items: "string", Desc: "GitHub usernames to add or remove"},
	}

	modifyOrgs := func(tool, action, resultKey string) func(a Args) any {
		return func(a Args) any {
			orgs := budgetToolStrings(tool, a, "organizations")
			enterprise := resolveEnterprise(a.Str("enterprise"))
			if enterprise == "" {
				return enterpriseError()
			}
			if len(orgs) == 0 {
				return jx.Dumps(jx.M{"error": "Provide at least one organization."})
			}
			api := APIs.APIForEnterprise(enterprise)
			if api == nil {
				return noAPI(enterprise)
			}
			slug := a.Str("team_slug")
			_, msg := send(api, http.MethodPost, "/enterprises/"+enterprise+"/teams/"+slug+"/organizations/"+action,
				jx.M{"organization_slugs": orgs}, fmt.Sprintf("enterprise team '%s'", slug))
			if msg != "" {
				return msg
			}
			return jx.Dumps(jx.M{"success": true, "enterprise": enterprise, "team_slug": slug, resultKey: orgs})
		}
	}

	modifyMembers := func(tool, action, resultKey string) func(a Args) any {
		return func(a Args) any {
			users := budgetToolStrings(tool, a, "usernames")
			enterprise := resolveEnterprise(a.Str("enterprise"))
			if enterprise == "" {
				return enterpriseError()
			}
			if len(users) == 0 {
				return jx.Dumps(jx.M{"error": "Provide at least one username."})
			}
			api := APIs.APIForEnterprise(enterprise)
			if api == nil {
				return noAPI(enterprise)
			}
			slug := a.Str("team_slug")
			_, msg := send(api, http.MethodPost, "/enterprises/"+enterprise+"/teams/"+slug+"/memberships/"+action,
				jx.M{"usernames": users}, fmt.Sprintf("enterprise team '%s'", slug))
			if msg != "" {
				return msg
			}
			return jx.Dumps(jx.M{"success": true, "enterprise": enterprise, "team_slug": slug, resultKey: users})
		}
	}

	return []copilot.Tool{
		defineTool("list_enterprise_teams",
			"List all enterprise teams with member counts and assigned organizations. "+
				"Enterprise teams group users at the enterprise level, independently of "+
				"organizations, and can hold Copilot Business licenses directly. "+
				"Reads from synced data by default; set live=true to query the GitHub API. "+
				"Leave enterprise empty to auto-detect from synced data.",
			[]P{
				entTeamEnterpriseParam(),
				{Name: "live", Type: "boolean", Default: false, Desc: "Fetch from the GitHub API instead of the local cache (slower, always current)."},
			},
			func(a Args) any {
				enterprise := resolveEnterprise(a.Str("enterprise"))
				if enterprise == "" {
					return enterpriseError()
				}
				if a.Bool("live") {
					api := APIs.APIForEnterprise(enterprise)
					if api == nil {
						return noAPI(enterprise)
					}
					teams := api.GetEnterpriseTeams(ctx, enterprise)
					if teams == nil {
						teams = []jx.M{}
					}
					return jx.Dumps(jx.M{"enterprise": enterprise, "teams": teams, "total": len(teams), "source": "live"})
				}
				teamData := loadTeamData(enterprise)
				if teamData == nil {
					return noCacheError(enterprise)
				}
				summary := jx.L{}
				for _, t := range teamsOf(teamData) {
					var idp any
					if g := jx.Get(t, "group_name"); jx.Truthy(g) {
						idp = g
					}
					summary = append(summary, jx.M{
						"slug":                        jx.GetOr(t, "slug", ""),
						"name":                        jx.GetOr(t, "name", ""),
						"description":                 jx.GetOr(t, "description", ""),
						"member_count":                jx.GetOr(t, "member_count", 0),
						"organizations":               jx.GetOr(t, "organizations", jx.L{}),
						"organization_selection_type": jx.GetOr(t, "organization_selection_type", ""),
						"idp_group":                   idp,
					})
				}
				return jx.Dumps(jx.M{
					"enterprise":           enterprise,
					"teams":                summary,
					"total":                len(summary),
					"total_unique_members": jx.GetOr(teamData, "total_unique_members", 0),
					"source":               "synced_cache",
				})
			}),

		defineTool("get_enterprise_team",
			"Get one enterprise team's full detail from synced data, including the "+
				"member roster and the organizations the team is assigned to. "+
				"Accepts the team slug (with 'ent:' prefix) or the team name.",
			[]P{
				entTeamEnterpriseParam(),
				teamParam("Enterprise team slug, including the 'ent:' prefix (e.g. 'ent:platform'). Team name is also accepted."),
			},
			func(a Args) any {
				enterprise := resolveEnterprise(a.Str("enterprise"))
				if enterprise == "" {
					return enterpriseError()
				}
				teamData := loadTeamData(enterprise)
				if teamData == nil {
					return noCacheError(enterprise)
				}
				slug := a.Str("team_slug")
				team := findTeam(teamData, slug)
				if team == nil {
					return jx.Dumps(jx.M{
						"error":           fmt.Sprintf("Enterprise team '%s' not found in '%s'.", slug, enterprise),
						"available_teams": slugList(teamData),
					})
				}
				return jx.Dumps(jx.M{"enterprise": enterprise, "team": team})
			}),

		defineTool("get_user_enterprise_teams",
			"Look up which enterprise teams a specific user belongs to. "+
				"Use this to attribute a user's Copilot seat, usage or AI credit spend "+
				"to an enterprise team, since none of those datasets carry a team field.",
			[]P{
				entTeamEnterpriseParam(),
				{Name: "username", Type: "string", Required: true, Desc: "GitHub username to look up"},
			},
			func(a Args) any {
				enterprise := resolveEnterprise(a.Str("enterprise"))
				if enterprise == "" {
					return enterpriseError()
				}
				teamData := loadTeamData(enterprise)
				if teamData == nil {
					return noCacheError(enterprise)
				}
				username := a.Str("username")
				login := strings.ToLower(strings.TrimSpace(username))
				slugs := jx.List(jx.GetOr(jx.Map(jx.GetOr(teamData, "member_index", jx.M{})), login, jx.L{}))
				bySlug := map[string]jx.M{}
				for _, t := range teamsOf(teamData) {
					bySlug[jx.Str(jx.GetOr(t, "slug", ""))] = t
				}
				teams := jx.L{}
				for _, s := range slugs {
					var name any = s
					if t, ok := bySlug[jx.Str(s)]; ok {
						name = jx.GetOr(t, "name", s)
					}
					teams = append(teams, jx.M{"slug": s, "name": name})
				}
				return jx.Dumps(jx.M{
					"enterprise": enterprise,
					"username":   username,
					"teams":      teams,
					"total":      len(slugs),
				})
			}),

		defineTool("get_enterprise_team_copilot_usage",
			"Analyze Copilot adoption and cost per enterprise team. For each team, joins "+
				"the member roster against Copilot seats and the user-level usage report to "+
				"report seat count, members without a seat, active members, interactions and "+
				"estimated seat cost. Also reports seat holders not covered by any enterprise team. "+
				"Leave team_slug empty to analyze all teams.",
			[]P{
				entTeamEnterpriseParam(),
				{Name: "team_slug", Type: "string", Default: "", Desc: "Enterprise team slug to analyze. Leave empty to report on every team."},
			},
			func(a Args) any {
				enterprise := resolveEnterprise(a.Str("enterprise"))
				if enterprise == "" {
					return enterpriseError()
				}
				if collector == nil {
					return jx.Dumps(jx.M{"error": "No data collector available."})
				}
				teamData := loadTeamData(enterprise)
				if teamData == nil {
					return noCacheError(enterprise)
				}

				// Seat + usage indexes across every org that has synced data
				// (only key membership is observable in the output).
				seatIndex := map[string]bool{}
				for _, seatsData := range collector.LoadAllLatest("seats") {
					sd := jx.Map(seatsData)
					if sd == nil {
						continue
					}
					for _, seat := range jx.Maps(jx.GetOr(sd, "seats", jx.L{})) {
						login := jx.Str(jx.GetOr(jx.Map(seat["assignee"]), "login", ""))
						if !jx.Truthy(jx.Get(jx.Map(seat["assignee"]), "login")) {
							continue
						}
						seatIndex[strings.ToLower(login)] = true
					}
				}
				usageIndex := map[string]int{}
				for _, report := range collector.LoadAllLatest("usage_users") {
					rp := jx.Map(report)
					if rp == nil {
						continue
					}
					for _, rec := range jx.GetMaps(rp, "records") {
						login := strings.ToLower(jx.OrStr(rec, "user_login", ""))
						if login != "" {
							usageIndex[login] += jx.GetInt(rec, "user_initiated_interaction_count")
						}
					}
				}

				price, ok := CopilotPricing["business"]
				if !ok {
					price = 19.0
				}

				teams := teamsOf(teamData)
				if slug := a.Str("team_slug"); slug != "" {
					team := findTeam(teamData, slug)
					if team == nil {
						return jx.Dumps(jx.M{
							"error":           fmt.Sprintf("Enterprise team '%s' not found in '%s'.", slug, enterprise),
							"available_teams": slugList(teamData),
						})
					}
					teams = []jx.M{team}
				}

				memberLogins := func(t jx.M) []string {
					out := []string{}
					for _, m := range jx.Maps(jx.GetOr(t, "members", jx.L{})) {
						if jx.Truthy(m["login"]) {
							out = append(out, jx.Str(jx.GetOr(m, "login", "")))
						}
					}
					return out
				}

				results := jx.L{}
				for _, team := range teams {
					logins := memberLogins(team)
					withSeat, withoutSeat, active, inactiveWithSeat := []string{}, []string{}, []string{}, []string{}
					interactions := 0
					for _, ln := range logins {
						l := strings.ToLower(ln)
						if seatIndex[l] {
							withSeat = append(withSeat, ln)
							if usageIndex[l] == 0 {
								inactiveWithSeat = append(inactiveWithSeat, ln)
							}
						} else {
							withoutSeat = append(withoutSeat, ln)
						}
						interactions += usageIndex[l]
						if usageIndex[l] > 0 {
							active = append(active, ln)
						}
					}
					results = append(results, jx.M{
						"slug":                        jx.GetOr(team, "slug", ""),
						"name":                        jx.GetOr(team, "name", ""),
						"organizations":               jx.GetOr(team, "organizations", jx.L{}),
						"member_count":                len(logins),
						"seat_count":                  len(withSeat),
						"members_without_seat":        withoutSeat,
						"active_member_count":         len(active),
						"inactive_with_seat":          inactiveWithSeat,
						"total_interactions":          interactions,
						"estimated_monthly_seat_cost": jx.Round(float64(len(withSeat))*price, 2),
					})
				}

				allTeamLogins := map[string]bool{}
				for _, t := range teamsOf(teamData) {
					for _, ln := range memberLogins(t) {
						allTeamLogins[strings.ToLower(ln)] = true
					}
				}
				uncovered := []string{}
				for ln := range seatIndex {
					if !allTeamLogins[ln] {
						uncovered = append(uncovered, ln)
					}
				}
				sort.Strings(uncovered)

				return jx.Dumps(jx.M{
					"enterprise":                         enterprise,
					"price_per_seat":                     price,
					"teams":                              results,
					"seat_users_without_enterprise_team": uncovered,
					"seat_users_without_enterprise_team_count": len(uncovered),
					"note": "Team members without a Copilot seat may be unaffiliated enterprise " +
						"users who belong to no organization, so they never appear in org seat data.",
				})
			}),

		defineTool("create_enterprise_team",
			"Create a new enterprise team. Enterprise teams group users at the enterprise "+
				"level and can be granted Copilot Business licenses directly, including users "+
				"who belong to no organization. Returns the created team with its 'ent:'-prefixed slug. "+
				"This is a write operation — confirm the name before executing. "+
				"Requires a classic PAT with the admin:enterprise scope. "+
				"Run Sync Data afterwards to refresh the local cache.",
			[]P{
				entTeamEnterpriseParam(),
				{Name: "name", Type: "string", Required: true, Desc: "Name for the new enterprise team"},
				{Name: "description", Type: "string", Default: "", Desc: "Optional description for the team"},
				{Name: "organization_selection_type", Type: "string", Default: "disabled", Desc: "Which organizations the team is assigned to: 'disabled' (none, the default), " +
					"'selected' (specific orgs, assign them afterwards with add_enterprise_team_organizations), " +
					"or 'all' (every current and future org in the enterprise)."},
				{Name: "group_id", Type: "string", Default: "", Desc: "Optional IdP group ID to sync membership from (SCIM/EMU enterprises only)."},
				{Name: "notification_setting", Type: "string", Default: "notifications_enabled", Desc: "'notifications_enabled' or 'notifications_disabled'"},
			},
			func(a Args) any {
				enterprise := resolveEnterprise(a.Str("enterprise"))
				if enterprise == "" {
					return enterpriseError()
				}
				name := strings.TrimSpace(a.Str("name"))
				if name == "" {
					return jx.Dumps(jx.M{"error": "A team name is required."})
				}
				api := APIs.APIForEnterprise(enterprise)
				if api == nil {
					return noAPI(enterprise)
				}
				body := jx.M{"name": name}
				for _, k := range []string{"description", "organization_selection_type", "group_id", "notification_setting"} {
					if v := a.Str(k); v != "" {
						body[k] = v
					}
				}
				r, msg := send(api, http.MethodPost, "/enterprises/"+enterprise+"/teams", body, fmt.Sprintf("enterprise '%s'", enterprise))
				if msg != "" {
					return msg
				}
				return jx.Dumps(jx.M{"success": true, "enterprise": enterprise, "team": r.JSON()})
			}),

		defineTool("update_enterprise_team",
			"Rename an enterprise team or change its description, organization assignment mode "+
				"or notification setting. Only the fields you provide are changed. "+
				"This is a write operation — confirm the changes before executing. "+
				"Requires a classic PAT with the admin:enterprise scope.",
			[]P{
				entTeamEnterpriseParam(),
				teamParam(entTeamSlugDesc),
				{Name: "name", Type: "string", Default: "", Desc: "New name for the team. Leave empty to keep the current name."},
				{Name: "description", Type: "string", Default: "", Desc: "New description. Leave empty to keep the current one."},
				{Name: "organization_selection_type", Type: "string", Default: "", Desc: "New organization assignment mode: 'disabled', 'selected' or 'all'. Leave empty to keep it."},
				{Name: "notification_setting", Type: "string", Default: "", Desc: "'notifications_enabled' or 'notifications_disabled'. Leave empty to keep it."},
			},
			func(a Args) any {
				enterprise := resolveEnterprise(a.Str("enterprise"))
				if enterprise == "" {
					return enterpriseError()
				}
				api := APIs.APIForEnterprise(enterprise)
				if api == nil {
					return noAPI(enterprise)
				}
				body := jx.M{}
				for _, k := range []string{"name", "description", "organization_selection_type", "notification_setting"} {
					if v := a.Str(k); v != "" {
						body[k] = v
					}
				}
				if len(body) == 0 {
					return jx.Dumps(jx.M{"error": "Provide at least one field to update."})
				}
				slug := a.Str("team_slug")
				r, msg := send(api, http.MethodPatch, "/enterprises/"+enterprise+"/teams/"+slug, body, fmt.Sprintf("enterprise team '%s'", slug))
				if msg != "" {
					return msg
				}
				return jx.Dumps(jx.M{"success": true, "enterprise": enterprise, "team": r.JSON()})
			}),

		defineTool("delete_enterprise_team",
			"Delete an enterprise team. Members lose any access the team granted, including "+
				"Copilot licenses assigned through it, and all of the team's IdP mappings are removed. "+
				"This is a destructive operation — confirm the team slug before executing. "+
				"Requires a classic PAT with the admin:enterprise scope.",
			[]P{
				entTeamEnterpriseParam(),
				teamParam("Enterprise team slug to delete, including the 'ent:' prefix."),
			},
			func(a Args) any {
				enterprise := resolveEnterprise(a.Str("enterprise"))
				if enterprise == "" {
					return enterpriseError()
				}
				api := APIs.APIForEnterprise(enterprise)
				if api == nil {
					return noAPI(enterprise)
				}
				slug := a.Str("team_slug")
				_, msg := send(api, http.MethodDelete, "/enterprises/"+enterprise+"/teams/"+slug, nil, fmt.Sprintf("enterprise team '%s'", slug))
				if msg != "" {
					return msg
				}
				return jx.Dumps(jx.M{"success": true, "enterprise": enterprise, "deleted_team": slug})
			}),

		defineTool("add_enterprise_team_organizations",
			"Assign an enterprise team to one or more organizations, granting its members "+
				"membership in those organizations. The team must use organization_selection_type='selected'. "+
				"This is a write operation — confirm the organizations before executing. "+
				"Requires a classic PAT with the admin:enterprise scope.",
			orgsParams, modifyOrgs("add_enterprise_team_organizations", "add", "assigned_organizations")),

		defineTool("remove_enterprise_team_organizations",
			"Unassign an enterprise team from one or more organizations. Members lose the "+
				"organization membership the team granted them. "+
				"This is a destructive operation — confirm the organizations before executing. "+
				"Requires a classic PAT with the admin:enterprise scope.",
			orgsParams, modifyOrgs("remove_enterprise_team_organizations", "remove", "unassigned_organizations")),

		defineTool("add_enterprise_team_members",
			"Add users to an enterprise team. Grants whatever access the team carries, "+
				"including Copilot Business if the team is licensed. "+
				"This is a write operation — confirm the team and usernames before executing. "+
				"Requires a classic PAT with the admin:enterprise scope.",
			membersParams, modifyMembers("add_enterprise_team_members", "add", "added")),

		defineTool("remove_enterprise_team_members",
			"Remove users from an enterprise team. If the team grants Copilot, the removed "+
				"users lose that access unless another team or organization grants it. "+
				"This is a destructive operation — confirm the team and usernames before executing. "+
				"Requires a classic PAT with the admin:enterprise scope.",
			membersParams, modifyMembers("remove_enterprise_team_members", "remove", "removed")),
	}
}
