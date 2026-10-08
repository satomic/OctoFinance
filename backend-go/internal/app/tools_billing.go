package app

import (
	copilot "github.com/github/copilot-sdk/go"

	"github.com/satomic/octofinance/backend-go/internal/jx"
)

// Port of backend/app/tools/billing_tools.py.

func init() { registerTools(billingTools) }

// billingToolOrgs is `[org] if org else list(load_all_latest("billing").keys())`.
func billingToolOrgs(dc *DataCollector, org string) ([]string, map[string]any) {
	if org != "" {
		return []string{org}, dc.LoadAllLatest("billing")
	}
	return seatToolAllLatest(dc, "billing")
}

func billingTools(tc *ToolCtx) []copilot.Tool {
	collector := tc.Collector
	return []copilot.Tool{
		defineTool("get_cost_overview",
			"Get cost overview for Copilot across organizations. Shows total seats, active seats, wasted seats, monthly cost, and estimated waste.",
			[]P{
				{Name: "org", Type: "string", Default: "", Desc: "Organization name. Leave empty for all orgs."},
			}, func(a Args) any {
				orgs, allBilling := billingToolOrgs(collector, a.Str("org"))
				overview := []jx.M{}
				grandCost, grandWaste := 0.0, 0.0
				for _, org := range orgs {
					billing := jx.Map(allBilling[org])
					if !jx.Truthy(billing) {
						continue
					}
					price := jx.Float(jx.GetOr(billing, "_detected_price_per_seat", 19.0))
					planType := jx.GetOr(billing, "_detected_plan_type", "business")
					breakdown := jx.Map(jx.GetOr(billing, "seat_breakdown", jx.M{}))
					total := jx.Float(jx.GetOr(breakdown, "total", 0))
					active := jx.Float(jx.GetOr(breakdown, "active_this_cycle", 0))
					pending := jx.GetOr(breakdown, "pending_cancellation", 0)
					inactive := total - active
					monthly := total * price
					waste := inactive * price
					var util any = 0
					if total > 0 {
						util = jx.Round(active/total*100, 1)
					}
					overview = append(overview, jx.M{
						"org":                     org,
						"plan_type":               planType,
						"price_per_seat":          price,
						"total_seats":             total,
						"active_seats":            active,
						"inactive_seats":          inactive,
						"pending_cancellation":    pending,
						"monthly_cost":            monthly,
						"estimated_monthly_waste": waste,
						"utilization_pct":         util,
					})
					grandCost += monthly
					grandWaste += waste
				}
				return jx.M{
					"organizations":               overview,
					"grand_total_monthly_cost":    grandCost,
					"grand_total_estimated_waste": grandWaste,
					"potential_annual_savings":    grandWaste * 12,
				}
			}),

		defineTool("calculate_roi",
			"Calculate ROI metrics for Copilot investment. Shows cost per active user, suggestions per dollar, and efficiency metrics.",
			[]P{
				{Name: "org", Type: "string", Default: "", Desc: "Organization name. Leave empty for all orgs."},
			}, func(a Args) any {
				orgs, allBilling := billingToolOrgs(collector, a.Str("org"))
				roi := []jx.M{}
				for _, org := range orgs {
					billing := jx.Map(allBilling[org])
					if !jx.Truthy(billing) {
						continue
					}
					usage := collector.LoadLatest("usage", org)
					price := jx.Float(jx.GetOr(billing, "_detected_price_per_seat", 19.0))
					breakdown := jx.Map(jx.GetOr(billing, "seat_breakdown", jx.M{}))
					total := jx.Float(jx.GetOr(breakdown, "total", 0))
					active := jx.Float(jx.GetOr(breakdown, "active_this_cycle", 0))
					monthly := total * price
					suggestions, acceptances := 0.0, 0.0
					if l, ok := usage.([]any); ok && len(l) > 0 {
						for _, d := range jx.Maps(l) {
							suggestions += jx.Float(jx.GetOr(d, "total_suggestions_count", 0))
							acceptances += jx.Float(jx.GetOr(d, "total_acceptances_count", 0))
						}
					}
					costPerActive := 0.0
					if active > 0 {
						costPerActive = monthly / active
					}
					acceptance := 0.0
					if suggestions > 0 {
						acceptance = acceptances / suggestions * 100
					}
					var perDollar any = 0
					if monthly > 0 {
						perDollar = jx.Round(suggestions/monthly, 1)
					}
					roi = append(roi, jx.M{
						"org":                    org,
						"monthly_cost":           monthly,
						"total_seats":            total,
						"active_seats":           active,
						"cost_per_active_user":   jx.Round(costPerActive, 2),
						"total_suggestions":      suggestions,
						"total_acceptances":      acceptances,
						"acceptance_rate_pct":    jx.Round(acceptance, 1),
						"suggestions_per_dollar": perDollar,
					})
				}
				return jx.M{"roi_by_org": roi}
			}),
	}
}
