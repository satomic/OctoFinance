package app

import (
	"fmt"
	"net/http"
	"net/url"
	"strings"

	copilot "github.com/github/copilot-sdk/go"

	"github.com/satomic/octofinance/backend-go/internal/ghapi"
	"github.com/satomic/octofinance/backend-go/internal/jx"
)

// Port of backend/app/tools/cost_center_tools.py (Billing Cost Centers REST
// API, version 2026-03-10). Lookups read the synced cache; writes go live.

func init() { registerTools(costCenterTools) }

var ccToolVersionHeader = map[string]string{"X-GitHub-Api-Version": ghapi.BillingAPIVersion}

const ccToolEnterpriseDesc = "Enterprise slug. Leave empty to auto-detect from synced data."

func ccToolLoadEnterprises(dc *DataCollector) []jx.M {
	if l, ok := dc.LoadLatest("enterprise", "all").([]any); ok {
		return jx.Maps(l)
	}
	return []jx.M{}
}

func ccToolResolveEnterprise(dc *DataCollector, requested string) string {
	if requested != "" {
		return requested
	}
	ents := APIs.AllEnterprises()
	if len(ents) == 1 {
		return jx.Str(ents[0]["slug"])
	}
	if len(ents) > 1 {
		return ""
	}
	ents = ccToolLoadEnterprises(dc)
	if len(ents) == 1 {
		return jx.Str(ents[0]["slug"])
	}
	return ""
}

func ccToolEnterpriseError(dc *DataCollector) jx.M {
	ents := ccToolLoadEnterprises(dc)
	if live := APIs.AllEnterprises(); len(live) > 0 {
		ents = live
	}
	if len(ents) > 0 {
		slugs := []string{}
		for _, e := range ents {
			slugs = append(slugs, jx.Str(e["slug"]))
		}
		return jx.M{"error": "Multiple enterprises available. Please specify the enterprise slug. " +
			"Available: " + pyStrList(slugs)}
	}
	return jx.M{"error": "No enterprise data found. " +
		"Please run Sync Data first so enterprise information can be discovered, " +
		"or provide the enterprise slug explicitly."}
}

// ccToolRequest performs a request; transport errors and non-404 HTTP errors
// fail the tool like an uncaught httpx exception in Python.
func ccToolRequest(tc *ToolCtx, api *ghapi.Client, method, path string, body any) *ghapi.Response {
	r, err := api.Do(tc.Context(), method, path, nil, body, ccToolVersionHeader)
	if err != nil {
		panic(err.Error())
	}
	return r
}

func ccToolRaise(r *ghapi.Response) {
	if err := ghapi.RaiseForStatus(r); err != nil {
		panic(err.Error())
	}
}

// ccToolJSON is resp.json() (fails the tool on a non-JSON body).
func ccToolJSON(r *ghapi.Response) any {
	v := r.JSON()
	if v == nil && strings.TrimSpace(r.Text()) != "null" {
		panic("Expecting value: line 1 column 1 (char 0)")
	}
	return v
}

func ccToolResourceBody(a Args) (jx.M, bool) {
	users, orgs, repos := a.Strings("users"), a.Strings("organizations"), a.Strings("repositories")
	if len(users) == 0 && len(orgs) == 0 && len(repos) == 0 {
		return nil, false
	}
	body := jx.M{}
	if len(users) > 0 {
		body["users"] = users
	}
	if len(orgs) > 0 {
		body["organizations"] = orgs
	}
	if len(repos) > 0 {
		body["repositories"] = repos
	}
	return body, true
}

func costCenterTools(tc *ToolCtx) []copilot.Tool {
	dc := tc.Collector
	entParam := P{Name: "enterprise", Type: "string", Default: "", Desc: ccToolEnterpriseDesc}
	idParam := P{Name: "cost_center_id", Type: "string", Required: true, Desc: "The unique ID of the cost center"}

	// withAPI resolves the enterprise and API client, or returns the error result.
	withAPI := func(a Args, fn func(enterprise string, api *ghapi.Client) any) any {
		enterprise := ccToolResolveEnterprise(dc, a.Str("enterprise"))
		if enterprise == "" {
			return ccToolEnterpriseError(dc)
		}
		api := APIs.APIForEnterprise(enterprise)
		if api == nil {
			return jx.M{"error": "No API client found for enterprise '" + enterprise + "'."}
		}
		return fn(enterprise, api)
	}
	ccPath := func(enterprise, id string) string {
		return "/enterprises/" + enterprise + "/settings/billing/cost-centers/" + id
	}
	notFound := func(id string) jx.M { return jx.M{"error": "Cost center '" + id + "' not found."} }

	resourceParams := func(verb string) []P {
		return []P{
			entParam, idParam,
			{Name: "users", Type: "array", Items: "string", Desc: "GitHub usernames to " + verb + " this cost center"},
			{Name: "organizations", Type: "array", Items: "string", Desc: "Organization login names to " + verb + " this cost center"},
			{Name: "repositories", Type: "array", Items: "string", Desc: "Repositories in 'org/repo' format to " + verb + " this cost center"},
		}
	}
	resourceTool := func(method string) func(a Args) any {
		return func(a Args) any {
			return withAPI(a, func(enterprise string, api *ghapi.Client) any {
				body, ok := ccToolResourceBody(a)
				if !ok {
					return jx.M{"error": "Provide at least one of: users, organizations, repositories."}
				}
				id := a.Str("cost_center_id")
				r := ccToolRequest(tc, api, method, ccPath(enterprise, id)+"/resource", body)
				if r.Status == 404 {
					return notFound(id)
				}
				ccToolRaise(r)
				if len(r.Body) == 0 {
					return jx.M{"success": true}
				}
				return ccToolJSON(r)
			})
		}
	}

	return []copilot.Tool{
		defineTool("get_synced_enterprise_data",
			"List all synced enterprises and their cost centers from local data. "+
				"Use this to discover available enterprise slugs and existing cost centers "+
				"without making a live API call. Run Sync Data first to populate this data.",
			[]P{}, func(a Args) any {
				ents := ccToolLoadEnterprises(dc)
				if len(ents) == 0 {
					ents = APIs.AllEnterprises()
				}
				if len(ents) == 0 {
					return jx.M{"message": "No enterprise data found. Please run Sync Data first.", "enterprises": jx.L{}}
				}
				result := []jx.M{}
				for _, ent := range ents {
					slug := jx.Str(ent["slug"])
					cc := jx.Map(dc.LoadLatest("cost_centers", slug))
					var ccs, total any = jx.L{}, 0
					if jx.Truthy(cc) {
						ccs = jx.GetOr(cc, "cost_centers", jx.L{})
						total = jx.GetOr(cc, "total", 0)
					}
					result = append(result, jx.M{
						"slug":               slug,
						"name":               jx.GetOr(ent, "name", ""),
						"role":               jx.GetOr(ent, "role", ""),
						"cost_centers":       ccs,
						"cost_centers_total": total,
					})
				}
				return jx.M{"enterprises": result, "total": len(result)}
			}),

		defineTool("list_cost_centers",
			"List all cost centers for a GitHub Enterprise from live API. "+
				"Returns cost center IDs, names, state, and resource assignments. "+
				"Use state='active' (default), 'archived', or 'all'. "+
				"Leave enterprise empty to auto-detect from synced data.",
			[]P{
				{Name: "enterprise", Type: "string", Default: "", Desc: "Enterprise slug (e.g. 'my-enterprise'). " +
					"Leave empty to auto-detect from synced data."},
				{Name: "state", Type: "string", Default: "active", Desc: "Filter by state: 'active' (default), 'archived', or 'all'"},
			}, func(a Args) any {
				return withAPI(a, func(enterprise string, api *ghapi.Client) any {
					base := "/enterprises/" + enterprise + "/settings/billing/cost-centers"
					state := a.Str("state")
					results := jx.L{}
					for page := 1; ; page++ {
						// Keep httpx's parameter order (state, per_page, page).
						q := ""
						if state != "" && state != "all" {
							q = "state=" + url.QueryEscape(state) + "&"
						}
						q += fmt.Sprintf("per_page=100&page=%d", page)
						r := ccToolRequest(tc, api, http.MethodGet, base+"?"+q, nil)
						if r.Status == 404 {
							return jx.M{"error": "Enterprise not found or Cost Centers API not available."}
						}
						ccToolRaise(r)
						data := ccToolJSON(r)
						var batch jx.L
						if l, ok := data.([]any); ok {
							batch = l
						} else {
							m := jx.Map(data)
							if v := m["costCenters"]; jx.Truthy(v) {
								batch = jx.List(v)
							} else if v := m["cost_centers"]; jx.Truthy(v) {
								batch = jx.List(v)
							}
						}
						if len(batch) == 0 {
							break
						}
						results = append(results, batch...)
						if len(batch) < 100 {
							break
						}
					}
					return jx.M{"enterprise": enterprise, "cost_centers": results, "total": len(results)}
				})
			}),

		defineTool("create_cost_center",
			"Create a new cost center for a GitHub Enterprise. "+
				"Returns the created cost center object including its ID. "+
				"The AI credit included usage cap (ai_credit_pool_enabled) defaults to true, "+
				"which caps the cost center at the included credits its members' licenses "+
				"already cover so usage stops there instead of drawing from the shared "+
				"enterprise pool. "+
				"This is a write operation — confirm the name before executing. "+
				"Leave enterprise empty to auto-detect from synced data.",
			[]P{
				entParam,
				{Name: "name", Type: "string", Required: true, Desc: "Name for the new cost center"},
				{Name: "ai_credit_pool_enabled", Type: "boolean", Default: true, Desc: "AI credit included usage cap. True (default) caps the cost center at the " +
					"included credits its members' licenses already cover, so usage stops there. " +
					"False lets it draw from the shared enterprise pool with no cap. " +
					"Can only be enabled for cost centers holding user or team resources only."},
			}, func(a Args) any {
				return withAPI(a, func(enterprise string, api *ghapi.Client) any {
					r := ccToolRequest(tc, api, http.MethodPost, "/enterprises/"+enterprise+"/settings/billing/cost-centers",
						jx.M{"name": a.Str("name"), "ai_credit_pool_enabled": a.Bool("ai_credit_pool_enabled")})
					if r.Status == 404 {
						return jx.M{"error": "Enterprise not found or Cost Centers API not available."}
					}
					ccToolRaise(r)
					return ccToolJSON(r)
				})
			}),

		defineTool("get_cost_center",
			"Get details for a specific cost center by its ID. "+
				"Returns the cost center name, state, and all assigned resources (users, orgs, repos). "+
				"Leave enterprise empty to auto-detect from synced data.",
			[]P{entParam, idParam}, func(a Args) any {
				return withAPI(a, func(enterprise string, api *ghapi.Client) any {
					id := a.Str("cost_center_id")
					r := ccToolRequest(tc, api, http.MethodGet, ccPath(enterprise, id), nil)
					if r.Status == 404 {
						return notFound(id)
					}
					ccToolRaise(r)
					return ccToolJSON(r)
				})
			}),

		defineTool("update_cost_center",
			"Update an existing cost center: rename it and/or turn its AI credit included "+
				"usage cap (ai_credit_pool_enabled) on or off. Enabling the cap stops usage at "+
				"the included credits the members' licenses already cover; disabling it lets the "+
				"cost center draw from the shared enterprise pool. "+
				"Returns the updated cost center object. "+
				"This is a write operation — confirm the change before executing. "+
				"Leave enterprise empty to auto-detect from synced data.",
			[]P{
				entParam, idParam,
				{Name: "name", Type: "string", Default: "", Desc: "New name for the cost center. Leave empty to keep the current name."},
				{Name: "ai_credit_pool_enabled", Type: "boolean", Nullable: true, Desc: "AI credit included usage cap. True caps the cost center at the included " +
					"credits its members' licenses already cover, so usage stops there. " +
					"False lets it draw from the shared enterprise pool with no cap. " +
					"Leave unset to keep the current setting."},
			}, func(a Args) any {
				return withAPI(a, func(enterprise string, api *ghapi.Client) any {
					body := jx.M{}
					if name := strings.TrimSpace(a.Str("name")); name != "" {
						body["name"] = name
					}
					if p := a.BoolPtr("ai_credit_pool_enabled"); p != nil {
						body["ai_credit_pool_enabled"] = *p
					}
					if len(body) == 0 {
						return jx.M{"error": "Provide a new name and/or ai_credit_pool_enabled."}
					}
					id := a.Str("cost_center_id")
					r := ccToolRequest(tc, api, http.MethodPatch, ccPath(enterprise, id), body)
					if r.Status == 404 {
						return notFound(id)
					}
					ccToolRaise(r)
					return ccToolJSON(r)
				})
			}),

		defineTool("delete_cost_center",
			"Delete (archive) a cost center by its ID. "+
				"Archived cost centers are hidden from active listings but not permanently removed. "+
				"This is a destructive operation — confirm the cost center ID before executing. "+
				"Leave enterprise empty to auto-detect from synced data.",
			[]P{entParam, {Name: "cost_center_id", Type: "string", Required: true, Desc: "The unique ID of the cost center to archive/delete"}},
			func(a Args) any {
				return withAPI(a, func(enterprise string, api *ghapi.Client) any {
					id := a.Str("cost_center_id")
					r := ccToolRequest(tc, api, http.MethodDelete, ccPath(enterprise, id), nil)
					if r.Status == 404 {
						return notFound(id)
					}
					ccToolRaise(r)
					return jx.M{"success": true, "enterprise": enterprise, "cost_center_id": id}
				})
			}),

		defineTool("add_cost_center_resources",
			"Add users, organizations, or repositories to a cost center. "+
				"Provide at least one of: users (GitHub usernames), organizations (org logins), "+
				"or repositories ('org/repo' format). "+
				"This is a write operation — confirm the resources before executing. "+
				"Leave enterprise empty to auto-detect from synced data.",
			resourceParams("assign to"), resourceTool(http.MethodPost)),

		defineTool("remove_cost_center_resources",
			"Remove users, organizations, or repositories from a cost center. "+
				"Provide at least one of: users (GitHub usernames), organizations (org logins), "+
				"or repositories ('org/repo' format). "+
				"This is a write operation — confirm the resources before executing. "+
				"Leave enterprise empty to auto-detect from synced data.",
			resourceParams("remove from"), resourceTool(http.MethodDelete)),
	}
}
