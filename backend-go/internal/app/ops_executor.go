package app

import (
	"context"
	"fmt"
	"strings"

	"github.com/satomic/octofinance/backend-go/internal/jx"
)

// Operations executor (Python services/ops_executor.py): executes, approves and
// rejects AI-recommended actions stored in data/recommendations.json.

func opsRecFile() string { return dataPath("recommendations.json") }

// opsLoadRecs reads recommendations.json; ok is false when the file is missing.
func opsLoadRecs() ([]jx.M, bool) {
	path := opsRecFile()
	if !jx.Exists(path) {
		return nil, false
	}
	v, err := jx.ReadJSON(path)
	if err != nil {
		panic(fmt.Sprintf("invalid recommendations.json: %v", err))
	}
	return jx.Maps(v), true
}

func opsSaveRecs(recs []jx.M) {
	if recs == nil {
		recs = []jx.M{}
	}
	if err := jx.WriteJSON(opsRecFile(), recs); err != nil {
		panic(err)
	}
}

// OpsExecuteRecommendation executes a pending recommendation by its ID.
func OpsExecuteRecommendation(ctx context.Context, id string) jx.M {
	mu := jx.FileLock(opsRecFile())
	mu.Lock()
	defer mu.Unlock()
	recs, ok := opsLoadRecs()
	if !ok {
		return jx.M{"error": "No recommendations found"}
	}
	var target jx.M
	for _, r := range recs {
		if v, ok := r["id"].(string); ok && v == id {
			target = r
			break
		}
	}
	if target == nil {
		return jx.M{"error": fmt.Sprintf("Recommendation %s not found", id)}
	}
	if s, ok := target["status"].(string); !ok || s != "pending" {
		return jx.M{"error": "Recommendation is already " + opsPyStr(target["status"])}
	}
	result := jx.M{"recommendation_id": id, "action": target["type"]}
	if t, _ := target["type"].(string); t == "remove_seats" {
		org := jx.Str(target["org"])
		api := APIs.APIForOrg(org)
		if api == nil {
			return jx.M{"error": fmt.Sprintf("No API client for org '%s'.", org)}
		}
		usernames := jx.Strings(target["affected_users"])
		seatTeams := map[string]jx.M{}
		if sd := Collector.LoadLatestMap("seats", org); jx.Truthy(sd) {
			for _, seat := range jx.GetMaps(sd, "seats") {
				login := dataGetStr(jx.GetMap(seat, "assignee"), "login", "")
				if login != "" {
					seatTeams[strings.ToLower(login)] = jx.Map(seat["assigning_team"])
				}
			}
		}
		orgLevel := []string{}
		type removal struct{ user, team string }
		teamRemovals := []removal{}
		for _, u := range usernames {
			team := seatTeams[strings.ToLower(u)]
			if jx.Truthy(team) && jx.Truthy(team["slug"]) {
				teamRemovals = append(teamRemovals, removal{u, jx.Str(team["slug"])})
			} else {
				orgLevel = append(orgLevel, u)
			}
		}
		apiResults := jx.L{}
		if len(orgLevel) > 0 {
			r := api.RemoveCopilotSeats(ctx, org, orgLevel)
			apiResults = append(apiResults, jx.M{"method": "org_level", "usernames": orgLevel, "result": opsNilable(r)})
		}
		for _, tr := range teamRemovals {
			r := api.RemoveTeamMembership(ctx, org, tr.team, tr.user)
			apiResults = append(apiResults, jx.M{"method": "team_level", "username": tr.user, "team": tr.team, "result": opsNilable(r)})
		}
		target["status"] = "executed"
		target["executed_at"] = jx.NowISO()
		target["execution_result"] = apiResults
		result["api_result"] = apiResults
	} else {
		target["status"] = "executed"
		target["executed_at"] = jx.NowISO()
	}
	opsSaveRecs(recs)
	result["status"] = "executed"
	return result
}

func opsNilable(m jx.M) any {
	if m == nil {
		return nil
	}
	return m
}

// opsPyStr renders a value like Python's str() in an f-string (None -> "None").
func opsPyStr(v any) string {
	if v == nil {
		return "None"
	}
	return dataPyRepr(v)
}

// OpsApproveRecommendation marks a pending recommendation approved.
func OpsApproveRecommendation(id string) jx.M {
	mu := jx.FileLock(opsRecFile())
	mu.Lock()
	defer mu.Unlock()
	recs, ok := opsLoadRecs()
	if !ok {
		return jx.M{"error": "No recommendations found"}
	}
	for _, r := range recs {
		if v, ok := r["id"].(string); ok && v == id {
			if s, ok := r["status"].(string); !ok || s != "pending" {
				return jx.M{"error": "Recommendation is already " + opsPyStr(r["status"])}
			}
			r["status"] = "approved"
			r["approved_at"] = jx.NowISO()
			opsSaveRecs(recs)
			return jx.M{"recommendation_id": id, "status": "approved", "recommendation": r}
		}
	}
	return jx.M{"error": fmt.Sprintf("Recommendation %s not found", id)}
}

// OpsRejectRecommendation rejects a recommendation.
func OpsRejectRecommendation(id string) jx.M {
	mu := jx.FileLock(opsRecFile())
	mu.Lock()
	defer mu.Unlock()
	recs, ok := opsLoadRecs()
	if !ok {
		return jx.M{"error": "No recommendations found"}
	}
	for _, r := range recs {
		if v, ok := r["id"].(string); ok && v == id {
			r["status"] = "rejected"
			r["rejected_at"] = jx.NowISO()
			opsSaveRecs(recs)
			return jx.M{"recommendation_id": id, "status": "rejected"}
		}
	}
	return jx.M{"error": fmt.Sprintf("Recommendation %s not found", id)}
}

// OpsPendingRecommendations returns all pending recommendations.
func OpsPendingRecommendations() []jx.M {
	recs, ok := opsLoadRecs()
	if !ok {
		return []jx.M{}
	}
	out := []jx.M{}
	for _, r := range recs {
		if s, ok := r["status"].(string); ok && s == "pending" {
			out = append(out, r)
		}
	}
	return out
}
