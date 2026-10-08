package app

import (
	"path/filepath"
	"time"

	copilot "github.com/github/copilot-sdk/go"

	"github.com/satomic/octofinance/backend-go/internal/jx"
)

// Port of backend/app/tools/action_tools.py.

func init() { registerTools(actionTools) }

// actionToolRecsFile is config.data_dir / "recommendations.json" (always global).
func actionToolRecsFile() string { return filepath.Join(DataDir, "recommendations.json") }

func actionTools(tc *ToolCtx) []copilot.Tool {
	return []copilot.Tool{
		defineTool("batch_remove_seats",
			"Batch remove Copilot seats for multiple users. Automatically detects org-level vs team-level assignment and uses the correct removal method. Records the action in audit log. Requires admin confirmation before execution.",
			[]P{
				{Name: "org", Type: "string", Required: true, Desc: "Organization name"},
				{Name: "usernames", Type: "array", Items: "string", Required: true, Desc: "List of GitHub usernames to remove"},
				{Name: "reason", Type: "string", Default: "inactive", Desc: "Reason for removal"},
			}, func(a Args) any {
				org := a.Str("org")
				api := APIs.APIForOrg(org)
				if api == nil {
					return jx.M{"error": "No API client available for org '" + org + "'."}
				}
				usernames := a.Strings("usernames")
				results := seatToolRemoveSeats(tc, api, org, usernames)
				AppendAuditLog(jx.M{
					"timestamp": jx.NowISO(),
					"action":    "batch_remove_seats",
					"org":       org,
					"usernames": usernames,
					"reason":    a.Str("reason"),
					"results":   results,
				})
				return jx.M{
					"action":        "batch_remove_seats",
					"org":           org,
					"users_removed": usernames,
					"count":         len(usernames),
					"results":       results,
				}
			}),

		defineTool("record_recommendation",
			"Record an AI-generated recommendation for admin review. Recommendations are stored and shown in the Action Panel for confirmation.",
			[]P{
				{Name: "org", Type: "string", Required: true, Desc: "Organization name"},
				{Name: "recommendation_type", Type: "string", Required: true, Desc: "Type: 'remove_seats', 'send_reminder', 'upgrade_plan', 'downgrade_plan'"},
				// default_factory=list: no "default" in the Pydantic JSON schema.
				{Name: "affected_users", Type: "array", Items: "string", Desc: "Users affected by recommendation"},
				{Name: "description", Type: "string", Required: true, Desc: "Human-readable description of the recommendation"},
				{Name: "estimated_monthly_savings", Type: "number", Default: 0, Desc: "Estimated monthly cost savings in USD"},
			}, func(a Args) any {
				now := time.Now().UTC()
				fields := jx.M{
					"id":                        now.Format("20060102150405"),
					"timestamp":                 jx.ISO(now),
					"org":                       a.Str("org"),
					"type":                      a.Str("recommendation_type"),
					"affected_users":            a.Strings("affected_users"),
					"description":               a.Str("description"),
					"estimated_monthly_savings": a.Float("estimated_monthly_savings"),
					"status":                    "pending",
				}
				// Keep Python's key order in recommendations.json and the result.
				rec := seatToolOMap{m: fields, keys: []string{"id", "timestamp", "org", "type", "affected_users",
					"description", "estimated_monthly_savings", "status"}}
				path := actionToolRecsFile()
				mu := jx.FileLock(path)
				mu.Lock()
				existing := jx.List(jx.ReadJSONOr(path, jx.L{}))
				if existing == nil {
					existing = jx.L{}
				}
				existing = append(existing, rec)
				err := jx.WriteJSON(path, existing)
				mu.Unlock()
				if err != nil {
					panic(err.Error())
				}
				return jx.M{"recorded": true, "recommendation": rec}
			}),

		defineTool("get_recommendations",
			"Get recorded recommendations. Can filter by status (pending/approved/rejected/executed/all).",
			[]P{
				{Name: "status", Type: "string", Default: "pending", Desc: "Filter by status: 'pending', 'approved', 'rejected', 'executed', or 'all'"},
			}, func(a Args) any {
				path := actionToolRecsFile()
				if !jx.Exists(path) {
					return jx.M{"recommendations": jx.L{}, "count": 0}
				}
				v, err := jx.ReadJSON(path)
				if err != nil {
					panic(err.Error())
				}
				recs := jx.List(v)
				status := a.Str("status")
				if status != "all" {
					out := jx.L{}
					for _, r := range recs {
						if s, ok := jx.Map(r)["status"].(string); ok && s == status {
							out = append(out, r)
						}
					}
					recs = out
				}
				if recs == nil {
					recs = jx.L{}
				}
				return jx.M{"recommendations": recs, "count": len(recs)}
			}),
	}
}
