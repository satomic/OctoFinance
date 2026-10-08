package app

import (
	"context"
	"fmt"
	"sort"
	"strings"

	"github.com/satomic/octofinance/backend-go/internal/jx"
)

// Cost center membership provisioning (Python services/cost_center_provisioner.py).
//
// A user belongs to at most one cost center (adding moves them out of the
// previous one), and inherited (org/team) membership cannot be changed per user.

const ccpSourceUser = "User"

// ccpEnterpriseSlugs lists enterprises with cost center data: discovered
// enterprises first, then any extra cached cost_centers/{slug}_latest.json.
func ccpEnterpriseSlugs() []string {
	slugs := []string{}
	seen := jx.StrSet{}
	for _, e := range APIs.AllEnterprises() {
		s := jx.Str(e["slug"])
		slugs = append(slugs, s)
		seen.Add(s)
	}
	for _, slug := range latestFileScopes("cost_centers") {
		if !seen.Has(slug) {
			seen.Add(slug)
			slugs = append(slugs, slug)
		}
	}
	return slugs
}

// ccpIsActive mirrors “str(cc.get("state", "active")).lower() in ("active", "")“
// (a null state is str(None) == "none", i.e. inactive).
func ccpIsActive(cc jx.M) bool {
	state := "active"
	if v, ok := cc["state"]; ok {
		if v == nil {
			state = "none"
		} else {
			state = strings.ToLower(jx.Str(v))
		}
	}
	return state == "active" || state == ""
}

// ListCostCentersForUser returns every selectable cost center flagged with this
// user's membership: {"enterprises": [...], "cost_centers": [...]}.
func ListCostCentersForUser(login string) jx.M {
	target := strings.ToLower(login)
	costCenters := []jx.M{}
	enterprises := []jx.M{}
	for _, slug := range ccpEnterpriseSlugs() {
		data := Collector.LoadLatestMap("cost_centers", slug)
		if len(data) == 0 {
			continue
		}
		entName := jx.GetOr(data, "enterprise_name", slug)
		enterprises = append(enterprises, jx.M{"slug": slug, "name": entName})
		for _, cc := range jx.GetMaps(data, "cost_centers") {
			if !ccpIsActive(cc) {
				continue
			}
			var member jx.M
			for _, m := range jx.GetMaps(cc, "members") {
				if strings.ToLower(jx.Str(jx.GetOr(m, "login", ""))) == target {
					member = m
					break
				}
			}
			direct := false
			for _, r := range jx.GetMaps(cc, "resources") {
				if jx.Str(r["type"]) == ccpSourceUser && strings.ToLower(jx.Str(jx.GetOr(r, "name", ""))) == target {
					direct = true
					break
				}
			}
			memberCount := jx.GetOr(cc, "member_count", nil)
			if !jx.Has(cc, "member_count") {
				memberCount = len(jx.GetList(cc, "members"))
			}
			costCenters = append(costCenters, jx.M{
				"id":                     jx.GetOr(cc, "id", ""),
				"name":                   jx.GetOr(cc, "name", ""),
				"enterprise":             slug,
				"enterprise_name":        entName,
				"state":                  jx.GetOr(cc, "state", ""),
				"ai_credit_pool_enabled": jx.GetBool(cc, "ai_credit_pool_enabled"),
				"member_count":           memberCount,
				"is_member":              member != nil,
				"is_direct":              direct,
				"locked":                 member != nil && !direct,
				"source":                 jx.GetOr(member, "source_type", ""),
				"source_name":            jx.GetOr(member, "source_name", ""),
			})
		}
	}
	sort.SliceStable(costCenters, func(i, j int) bool {
		a, b := jx.Str(costCenters[i]["enterprise"]), jx.Str(costCenters[j]["enterprise"])
		if a != b {
			return a < b
		}
		return strings.ToLower(jx.Str(costCenters[i]["name"])) < strings.ToLower(jx.Str(costCenters[j]["name"]))
	})
	return jx.M{"enterprises": enterprises, "cost_centers": costCenters}
}

// CurrentCostCenterAssignment is the cost center the user is directly assigned to.
func CurrentCostCenterAssignment(login string) jx.M {
	for _, c := range ListCostCentersForUser(login)["cost_centers"].([]jx.M) {
		if jx.GetBool(c, "is_direct") {
			return c
		}
	}
	return nil
}

// CCMembershipPlan is the move implied by choosing a target cost center.
type CCMembershipPlan struct {
	Add, Remove     []jx.M
	Current, Target jx.M // nil when none
	Invalid         bool
	All             []jx.M
}

// DiffCostCenterMembership works out the move implied by choosing targetID
// ("" = unassigned). Inherited memberships are never touched.
func DiffCostCenterMembership(login, targetID string) CCMembershipPlan {
	all := ListCostCentersForUser(login)["cost_centers"].([]jx.M)
	byID := map[string]jx.M{}
	var current jx.M
	for _, c := range all {
		byID[jx.Str(c["id"])] = c
		if current == nil && jx.GetBool(c, "is_direct") {
			current = c
		}
	}
	var target jx.M
	if targetID != "" {
		target = byID[targetID]
		if target == nil {
			return CCMembershipPlan{Add: []jx.M{}, Remove: []jx.M{}, Current: current, Invalid: true, All: all}
		}
	}
	same := current != nil && target != nil && jx.Str(current["id"]) == jx.Str(target["id"])
	plan := CCMembershipPlan{Add: []jx.M{}, Remove: []jx.M{}, Current: current, Target: target, All: all}
	if !same && target != nil {
		plan.Add = []jx.M{target}
	}
	if !same && target == nil && current != nil {
		plan.Remove = []jx.M{current}
	}
	return plan
}

func ccpEntry(cc jx.M) jx.M {
	return jx.M{"id": cc["id"], "name": cc["name"], "enterprise": cc["enterprise"]}
}

// ApplyCostCenterMembershipChange applies an approved assignment to GitHub.
// The result is always safe to persist:
// {"status": "applied"|"partial"|"failed"|"noop", "added": [...], "removed": [...], ...}.
func ApplyCostCenterMembershipChange(ctx context.Context, login, targetID string) jx.M {
	plan := DiffCostCenterMembership(login, targetID)
	if plan.Invalid {
		msg := fmt.Sprintf("Cost center '%s' not found.", targetID)
		return jx.M{
			"status": "failed", "added": jx.L{}, "removed": jx.L{},
			"errors":    jx.L{jx.M{"error": msg}},
			"error":     msg,
			"synced_at": jx.NowISO(),
		}
	}
	if len(plan.Add) == 0 && len(plan.Remove) == 0 {
		return jx.M{
			"status": "noop", "added": jx.L{}, "removed": jx.L{}, "errors": jx.L{},
			"message":   "Assignment already matches the request.",
			"synced_at": jx.NowISO(),
		}
	}

	added := []jx.M{}
	removed := []jx.M{}
	reassigned := []any{}
	errs := []jx.M{}

	for _, cc := range plan.Add {
		ent := jx.Str(cc["enterprise"])
		api := APIs.APIForEnterprise(ent)
		if api == nil {
			errs = append(errs, jx.M{"cost_center": cc["name"], "id": cc["id"], "action": "add",
				"error": fmt.Sprintf("No PAT with access to enterprise '%s'.", ent)})
			continue
		}
		resp, err := api.AddCostCenterResources(ctx, ent, jx.Str(cc["id"]), []string{login}, nil, nil)
		if err != nil {
			errs = append(errs, jx.M{"cost_center": cc["name"], "id": cc["id"], "action": "add", "error": err.Error()})
			Logger.Warn(fmt.Sprintf("[cost-center] Assign %s to %s failed: %v", login, jx.Str(cc["name"]), err))
			continue
		}
		added = append(added, ccpEntry(cc))
		for _, r := range jx.GetList(resp, "reassigned_resources") {
			if m := jx.Map(r); m != nil {
				reassigned = append(reassigned, m)
			} else {
				reassigned = append(reassigned, jx.M{"resource": r})
			}
		}
		Logger.Info(fmt.Sprintf("[cost-center] Assigned %s to %s", login, jx.Str(cc["name"])))
	}

	for _, cc := range plan.Remove {
		ent := jx.Str(cc["enterprise"])
		api := APIs.APIForEnterprise(ent)
		if api == nil {
			errs = append(errs, jx.M{"cost_center": cc["name"], "id": cc["id"], "action": "remove",
				"error": fmt.Sprintf("No PAT with access to enterprise '%s'.", ent)})
			continue
		}
		if _, err := api.RemoveCostCenterResources(ctx, ent, jx.Str(cc["id"]), []string{login}, nil, nil); err != nil {
			errs = append(errs, jx.M{"cost_center": cc["name"], "id": cc["id"], "action": "remove", "error": err.Error()})
			Logger.Warn(fmt.Sprintf("[cost-center] Unassign %s from %s failed: %v", login, jx.Str(cc["name"]), err))
			continue
		}
		removed = append(removed, ccpEntry(cc))
		Logger.Info(fmt.Sprintf("[cost-center] Unassigned %s from %s", login, jx.Str(cc["name"])))
	}

	// The previous assignment is implicitly dropped by GitHub when moving.
	if prev := plan.Current; len(added) > 0 && prev != nil && jx.Str(prev["id"]) != jx.Str(added[0]["id"]) {
		removed = append(removed, ccpEntry(prev))
	}

	status := "applied"
	if len(errs) > 0 && len(added) == 0 && len(removed) == 0 {
		status = "failed"
	} else if len(errs) > 0 {
		status = "partial"
	}
	var errText any
	if len(errs) > 0 {
		parts := make([]string, 0, len(errs))
		for _, e := range errs {
			name := "?"
			if v, ok := e["cost_center"]; ok {
				name = brPyStr(v)
			}
			parts = append(parts, name+": "+jx.Str(e["error"]))
		}
		errText = strings.Join(parts, "; ")
	}
	return jx.M{
		"status":     status,
		"added":      added,
		"removed":    removed,
		"reassigned": reassigned,
		"errors":     errs,
		"error":      errText,
		"synced_at":  jx.NowISO(),
	}
}
