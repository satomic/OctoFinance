package app

import (
	"fmt"
	"sort"
	"strconv"
	"strings"

	copilot "github.com/github/copilot-sdk/go"

	"github.com/satomic/octofinance/backend-go/internal/jx"
)

// Port of backend/app/tools/usage_tools.py.
//
// Note: the Python live-fetch tools (fetch_org_usage_report,
// fetch_org_users_usage_report, fetch_ai_credit_usage) are synchronous
// handlers that call loop.run_until_complete() on the already-running event
// loop, so in Python they always fail with "This event loop is already
// running". The Go port implements their intended behaviour.

func init() { registerTools(usageTools) }

// usageToolCached serves a cached category for one org or all orgs.
func usageToolCached(dc *DataCollector, category, org, orgErr, allErr string) any {
	if org != "" {
		data := dc.LoadLatest(category, org)
		if !jx.Truthy(data) {
			return jx.M{"error": orgErr}
		}
		return data
	}
	keys, all := seatToolAllLatest(dc, category)
	if len(all) == 0 {
		return jx.M{"error": allErr}
	}
	return seatToolOMap{keys: keys, m: all}
}

// usageToolPyFloat is Python float(str) for CSV cells (raises on bad input).
func usageToolPyFloat(r CSVRecord, key string) float64 {
	v, ok := r[key]
	if !ok {
		return 0
	}
	f, err := strconv.ParseFloat(strings.ReplaceAll(strings.TrimSpace(v), "_", ""), 64)
	if err != nil {
		panic(fmt.Sprintf("could not convert string to float: '%s'", v))
	}
	return f
}

func usageToolGet(r CSVRecord, key, def string) string {
	if v, ok := r[key]; ok {
		return v
	}
	return def
}

func usageTools(tc *ToolCtx) []copilot.Tool {
	collector := tc.Collector
	orgParam := P{Name: "org", Type: "string", Default: "", Desc: "Organization name. Leave empty for all orgs."}
	requiredOrg := P{Name: "org", Type: "string", Required: true, Desc: "Organization name (required)."}
	dayParam := P{Name: "day", Type: "string", Default: "", Desc: "Specific day in YYYY-MM-DD format. Leave empty to get latest 28-day report."}

	return []copilot.Tool{
		defineTool("get_usage_report",
			"Get the org-level Copilot usage report from cached data (synced during last Sync Data). "+
				"Contains aggregated usage statistics, feature adoption metrics, and engagement data "+
				"for the latest 28-day period.",
			[]P{orgParam}, func(a Args) any {
				org := a.Str("org")
				return usageToolCached(collector, "usage", org,
					"No usage report for org '"+org+"'. Try fetch_org_usage_report to get live data.",
					"No usage report data found. Try fetch_org_usage_report to get live data.")
			}),

		defineTool("get_users_usage_report",
			"Get the user-level Copilot usage report from cached data (synced during last Sync Data). "+
				"Contains per-user engagement statistics, feature usage patterns, and adoption metrics "+
				"for the latest 28-day period.",
			[]P{orgParam}, func(a Args) any {
				org := a.Str("org")
				return usageToolCached(collector, "usage_users", org,
					"No user-level usage report for org '"+org+"'. Try fetch_org_users_usage_report to get live data.",
					"No user-level usage data found. Try fetch_org_users_usage_report to get live data.")
			}),

		defineTool("get_metrics_detail",
			"Get detailed Copilot metrics (legacy API) including IDE code completions, chat usage, "+
				"PR summaries, and per-editor/model breakdown.",
			[]P{orgParam}, func(a Args) any {
				org := a.Str("org")
				return usageToolCached(collector, "metrics", org,
					"No metrics data for org '"+org+"'.",
					"No metrics data found.")
			}),

		defineTool("get_ai_credit_usage",
			"Get Copilot AI credit usage from cached data (synced during last Sync Data). "+
				"Under usage-based billing (UBB) each org consumes AI credits per model. "+
				"Shows per-model breakdown of AI credit consumption including model names, "+
				"credit quantities, pricing, gross/discount/net amounts. Essential for cost analysis.",
			[]P{orgParam}, func(a Args) any {
				org := a.Str("org")
				return usageToolCached(collector, "ai_credits", org,
					"No AI credit data for org '"+org+"'. Try fetch_ai_credit_usage to get live data.",
					"No AI credit data found. Try fetch_ai_credit_usage to get live data.")
			}),

		defineTool("get_user_ai_usage",
			"Get per-user AI usage from the ingested AI Usage report CSV data. "+
				"This data comes from the detailed billing report CSV, pulled from the GitHub billing "+
				"reports API or uploaded by the admin. "+
				"Under usage-based billing (UBB) each user consumes AI credits per AI model. "+
				"Shows each user's daily AI credit consumption broken down by model, "+
				"including credit amounts, costs, quota usage percentage, and active days. "+
				"Can filter by username or organization. Use this to answer questions about "+
				"individual user's AI spending and model preferences.",
			[]P{
				{Name: "user", Type: "string", Default: "", Desc: "Username to filter. Leave empty for all users."},
				{Name: "org", Type: "string", Default: "", Desc: "Organization name to filter. Leave empty for all orgs."},
			}, func(a Args) any {
				return usageToolUserAIUsage(a.Str("user"), a.Str("org"))
			}),

		defineTool("fetch_org_usage_report",
			"Fetch LIVE org-level Copilot usage report directly from GitHub API. "+
				"Provide a specific day (YYYY-MM-DD) to get a 1-day report, or leave day empty "+
				"for the latest 28-day report. The report contains aggregated usage statistics "+
				"for various Copilot features, user engagement data, and feature adoption metrics. "+
				"Data available from Oct 10, 2025 onward.",
			[]P{requiredOrg, dayParam}, func(a Args) any {
				org, day := a.Str("org"), a.Str("day")
				api := APIs.APIForOrg(org)
				if api == nil {
					return jx.M{"error": "No API client for org '" + org + "'."}
				}
				var result jx.M
				if day != "" {
					result = api.GetOrgUsageReport1Day(tc.Context(), org, day)
				} else {
					result = api.GetOrgUsageReport28Day(tc.Context(), org)
				}
				if !jx.Truthy(result) {
					return jx.M{"error": "No usage report available for org '" + org + "'.", "hint": "Ensure the org has the Copilot usage metrics policy enabled."}
				}
				collector.SaveJSON("usage", org, result)
				return result
			}),

		defineTool("fetch_org_users_usage_report",
			"Fetch LIVE user-level Copilot usage report directly from GitHub API. "+
				"Provide a specific day (YYYY-MM-DD) to get a 1-day report, or leave day empty "+
				"for the latest 28-day report. Contains per-user engagement statistics, "+
				"individual feature usage patterns, and adoption metrics broken down by user. "+
				"Data available from Oct 10, 2025 onward.",
			[]P{requiredOrg, dayParam}, func(a Args) any {
				org, day := a.Str("org"), a.Str("day")
				api := APIs.APIForOrg(org)
				if api == nil {
					return jx.M{"error": "No API client for org '" + org + "'."}
				}
				var result jx.M
				if day != "" {
					result = api.GetOrgUsersUsageReport1Day(tc.Context(), org, day)
				} else {
					result = api.GetOrgUsersUsageReport28Day(tc.Context(), org)
				}
				if !jx.Truthy(result) {
					return jx.M{"error": "No user-level usage report available for org '" + org + "'.", "hint": "Ensure the org has the Copilot usage metrics policy enabled."}
				}
				collector.SaveJSON("usage_users", org, result)
				return result
			}),

		defineTool("fetch_ai_credit_usage",
			"Fetch LIVE Copilot AI credit usage directly from GitHub API (UBB). "+
				"Shows per-model breakdown of AI credit consumption including "+
				"model names (GPT-5.4, Claude Opus 4.7, etc.), credit quantities, "+
				"pricing ($0.01/credit), gross/discount/net amounts. "+
				"Optionally specify year and month to query historical data (up to 24 months).",
			[]P{
				requiredOrg,
				{Name: "year", Type: "integer", Default: 0, Desc: "Year (e.g. 2026). Leave 0 for current year."},
				{Name: "month", Type: "integer", Default: 0, Desc: "Month (1-12). Leave 0 for current month."},
			}, func(a Args) any {
				org := a.Str("org")
				api := APIs.APIForOrg(org)
				if api == nil {
					return jx.M{"error": "No API client for org '" + org + "'."}
				}
				result, err := api.GetAICreditUsage(tc.Context(), org, a.Int("year"), a.Int("month"), 0)
				if err != nil {
					panic(err.Error())
				}
				if !jx.Truthy(result) {
					return jx.M{"error": "No AI credit data for org '" + org + "'.", "hint": "Ensure the PAT has 'Administration' org permission (read)."}
				}
				collector.SaveJSON("ai_credits", org, result)
				return result
			}),
	}
}

func usageToolUserAIUsage(user, org string) any {
	// CSVs are only ever ingested into the global data dir.
	records := LoadAllCSVRecords(CSVTypeAI)
	if len(records) == 0 {
		return jx.M{"error": "No per-user AI usage CSV data found. Fetch it from the GitHub billing " +
			"reports API or upload an AI Usage CSV from the Dashboard page."}
	}
	filtered := make([]CSVRecord, 0, len(records))
	for _, r := range records {
		if org != "" && usageToolGet(r, "organization", "") != org {
			continue
		}
		if user != "" && usageToolGet(r, "username", "") != user {
			continue
		}
		filtered = append(filtered, r)
	}
	if len(filtered) == 0 {
		return jx.M{"error": fmt.Sprintf("No records found matching user='%s', org='%s'.", user, org)}
	}

	type userInfo struct {
		name       string
		credits    float64
		cost       float64
		models     map[string]float64
		modelOrder []string
		days       jx.StrSet
		org        string
		quota      int
	}
	users := map[string]*userInfo{}
	order := []*userInfo{}
	for _, r := range filtered {
		name := usageToolGet(r, "username", "")
		u := users[name]
		if u == nil {
			u = &userInfo{name: name, models: map[string]float64{}, days: jx.StrSet{}}
			users[name] = u
			order = append(order, u)
		}
		qty := usageToolPyFloat(r, "quantity")
		u.credits += qty
		u.cost += usageToolPyFloat(r, "gross_amount")
		model := usageToolGet(r, "model", "unknown")
		if _, ok := u.models[model]; !ok {
			u.modelOrder = append(u.modelOrder, model)
		}
		u.models[model] += qty
		u.days.Add(usageToolGet(r, "date", ""))
		u.org = usageToolGet(r, "organization", "")
		if q, ok := r["total_monthly_quota"]; ok {
			if n, err := strconv.Atoi(strings.ReplaceAll(strings.TrimSpace(q), "_", "")); err == nil {
				u.quota = n
			}
		} else {
			u.quota = 0
		}
	}
	sort.SliceStable(order, func(i, j int) bool { return order[i].credits > order[j].credits })

	result := []jx.M{}
	for _, u := range order {
		var usagePct any = 0
		if u.quota > 0 {
			usagePct = jx.Round(u.credits/float64(u.quota)*100, 1)
		}
		var dateRange any
		if len(u.days) > 0 {
			days := u.days.Sorted()
			dateRange = jx.M{"start": days[0], "end": days[len(days)-1]}
		}
		models := append([]string(nil), u.modelOrder...)
		sort.SliceStable(models, func(i, j int) bool { return u.models[models[i]] > u.models[models[j]] })
		mvals := map[string]any{}
		for _, m := range models {
			mvals[m] = jx.Round(u.models[m], 2)
		}
		result = append(result, jx.M{
			"user":          u.name,
			"org":           u.org,
			"total_credits": jx.Round(u.credits, 2),
			"total_cost":    jx.Round(u.cost, 4),
			"quota":         u.quota,
			"usage_pct":     usagePct,
			"days_active":   len(u.days),
			"date_range":    dateRange,
			"models":        seatToolOMap{keys: models, m: mvals},
		})
	}
	return jx.M{"users": result, "total_records": len(filtered)}
}
