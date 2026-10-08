package app

import (
	"context"
	"fmt"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/satomic/octofinance/backend-go/internal/ghapi"
	"github.com/satomic/octofinance/backend-go/internal/jx"
)

// Budget provisioning against the real GitHub Billing Budgets API, and the
// read-back of every budget that applies to a given user.

const (
	ScopeUser       = "user"
	ScopeUniversal  = "multi_user_customer"
	ScopeCostCenter = "cost_center"
	AICreditsSKU    = "ai_credits"
	BudgetType      = "BundlePricing"
)

// CurrentMonthRange returns the first and last day of the current UTC month.
func CurrentMonthRange() (string, string) {
	now := time.Now().UTC()
	start := time.Date(now.Year(), now.Month(), 1, 0, 0, 0, 0, time.UTC)
	end := start.AddDate(0, 1, -1)
	return start.Format("2006-01-02"), end.Format("2006-01-02")
}

// ListBillingEntities lists entities that can hold budgets, enterprises first.
func ListBillingEntities() []jx.M {
	out := []jx.M{}
	for _, e := range APIs.AllEnterprises() {
		label := jx.Str(e["name"])
		if label == "" {
			label = jx.Str(e["slug"])
		}
		out = append(out, jx.M{"entity_type": "enterprise", "entity_name": e["slug"], "label": label})
	}
	for _, o := range APIs.AllOrgs() {
		out = append(out, jx.M{"entity_type": "organization", "entity_name": o["login"], "label": o["login"]})
	}
	return out
}

// latestFileScopes lists {scope}_latest.json names in a global data category, sorted.
func latestFileScopes(category string) []string {
	matches, _ := filepath.Glob(filepath.Join(Collector.DataDir(), category, "*_latest.json"))
	sort.Strings(matches)
	out := []string{}
	for _, p := range matches {
		out = append(out, strings.TrimSuffix(filepath.Base(p), "_latest.json"))
	}
	return out
}

func userOrgs(login string) []string {
	target := strings.ToLower(login)
	orgs := []string{}
	view := Collector.LoadAllLatest("seats") // build the de-duplicated view once
	for _, org := range latestFileScopes("seats") {
		data := jx.Map(view[org])
		for _, seat := range jx.GetMaps(data, "seats") {
			if strings.ToLower(jx.Str(jx.GetMap(seat, "assignee")["login"])) == target {
				orgs = append(orgs, org)
				break
			}
		}
	}
	return orgs
}

// ResolveEntityForUser picks the entity whose budgets hold this user's personal
// budget: an enterprise whenever one exists, else an organization.
func ResolveEntityForUser(login, preferredOrg string) jx.M {
	enterprises := APIs.AllEnterprises()
	orgList := APIs.AllOrgs()
	allOrgs := map[string]jx.M{}
	for _, o := range orgList {
		allOrgs[jx.Str(o["login"])] = o
	}
	enterpriseOf := func(org string) jx.M {
		info := allOrgs[org]
		patID := jx.Str(info["pat_id"])
		label := jx.Str(info["enterprise"])
		for _, e := range enterprises {
			if label != "" && label != "Independent" && label != "Unknown" &&
				(jx.Str(e["slug"]) == label || jx.Str(e["name"]) == label) {
				return jx.M{"entity_type": "enterprise", "entity_name": e["slug"]}
			}
		}
		if patID != "" {
			for _, e := range enterprises {
				if jx.Str(e["pat_id"]) == patID {
					return jx.M{"entity_type": "enterprise", "entity_name": e["slug"]}
				}
			}
		}
		return nil
	}
	candidates := []string{}
	if p := strings.TrimSpace(preferredOrg); p != "" {
		candidates = append(candidates, p)
	}
	candidates = append(candidates, userOrgs(login)...)
	for _, org := range candidates {
		if ent := enterpriseOf(org); ent != nil {
			return ent
		}
	}
	if len(enterprises) > 0 {
		return jx.M{"entity_type": "enterprise", "entity_name": enterprises[0]["slug"]}
	}
	for _, org := range candidates {
		if _, ok := allOrgs[org]; ok {
			return jx.M{"entity_type": "organization", "entity_name": org}
		}
	}
	if len(orgList) > 0 {
		return jx.M{"entity_type": "organization", "entity_name": orgList[0]["login"]}
	}
	return nil
}

// APIForEntity returns the client for an enterprise or organization.
func APIForEntity(entityType, entityName string) *ghapi.Client {
	if entityType == "enterprise" {
		return APIs.APIForEnterprise(entityName)
	}
	return APIs.APIForOrg(entityName)
}

// FetchBudgets live-fetches budgets for an entity ([] when unavailable).
func FetchBudgets(ctx context.Context, entityType, entityName, scope string) []jx.M {
	api := APIForEntity(entityType, entityName)
	if api == nil {
		return []jx.M{}
	}
	budgets, err := api.GetAllBudgetsPaginated(ctx, entityType, entityName, scope, false)
	if err != nil {
		Logger.Warn(fmt.Sprintf("[budget] Live budget fetch failed for %s/%s: %v", entityType, entityName, err))
		return []jx.M{}
	}
	return budgets
}

// CachedBudgets returns budgets from the last sync.
func CachedBudgets(entityName string) []jx.M {
	return jx.GetMaps(Collector.LoadLatestMap("budgets", entityName), "budgets")
}

// NormalizeBudget converts a GitHub budget into the UI shape.
func NormalizeBudget(b jx.M, entityType, entityName string) jx.M {
	skus := jx.GetList(b, "budget_product_skus")
	if !jx.Truthy(skus) {
		skus = jx.L{}
		if single := b["budget_product_sku"]; jx.Truthy(single) {
			skus = jx.L{single}
		}
	}
	cleanSkus := jx.L{}
	for _, s := range skus {
		if jx.Truthy(s) {
			cleanSkus = append(cleanSkus, s)
		}
	}
	alerting := jx.GetMap(b, "budget_alerting")
	amount := jx.Float(b["budget_amount"])
	var consumed, remaining, pct any
	if raw, ok := b["consumed_amount"]; ok && raw != nil {
		c := jx.Float(raw)
		consumed = c
		remaining = jx.Round(amount-c, 4)
		if amount > 0 {
			pct = jx.Round(c/amount*100, 1)
		}
	}
	return jx.M{
		"id":                    jx.GetOr(b, "id", ""),
		"scope":                 jx.GetOr(b, "budget_scope", ""),
		"entity_type":           entityType,
		"entity_name":           entityName,
		"target_name":           jx.Str(b["budget_entity_name"]),
		"skus":                  cleanSkus,
		"amount":                amount,
		"consumed_amount":       consumed,
		"remaining_amount":      remaining,
		"usage_pct":             pct,
		"prevent_further_usage": jx.GetBool(b, "prevent_further_usage"),
		"will_alert":            jx.GetBool(alerting, "will_alert"),
	}
}

func isActiveState(cc jx.M) bool {
	state := "active"
	if v, ok := cc["state"]; ok {
		state = strings.ToLower(jx.Str(v))
		if v == nil {
			state = "none" // Python: str(None).lower()
		}
	}
	return state == "active" || state == ""
}

// UserCostCenters lists every active enterprise cost center the user belongs to.
func UserCostCenters(login string) []jx.M {
	target := strings.ToLower(login)
	results := []jx.M{}
	for _, slug := range latestFileScopes("cost_centers") {
		data := Collector.LoadLatestMap("cost_centers", slug)
		if data == nil {
			continue
		}
		for _, cc := range jx.GetMaps(data, "cost_centers") {
			if !isActiveState(cc) {
				continue
			}
			var member jx.M
			for _, m := range jx.GetMaps(cc, "members") {
				if strings.ToLower(jx.Str(m["login"])) == target {
					member = m
					break
				}
			}
			if member == nil {
				continue
			}
			resources := jx.GetList(cc, "resources")
			if resources == nil {
				resources = jx.L{}
			}
			results = append(results, jx.M{
				"id":                     jx.GetOr(cc, "id", ""),
				"name":                   jx.GetStr(cc, "name"),
				"enterprise":             slug,
				"enterprise_name":        jx.GetOr(data, "enterprise_name", slug),
				"state":                  jx.GetStr(cc, "state"),
				"ai_credit_pool_enabled": jx.GetBool(cc, "ai_credit_pool_enabled"),
				"member_count":           jx.GetOr(cc, "member_count", len(jx.GetList(cc, "members"))),
				"membership_source":      jx.GetStr(member, "source_type"),
				"membership_source_name": jx.GetStr(member, "source_name"),
				"resources":              resources,
				"budget":                 nil,
			})
		}
	}
	return results
}

func matchCostCenterBudget(budgets []jx.M, cc jx.M) jx.M {
	name := strings.ToLower(jx.Str(cc["name"]))
	id := strings.ToLower(jx.Str(cc["id"]))
	for _, b := range budgets {
		if jx.Str(b["budget_scope"]) != ScopeCostCenter {
			continue
		}
		target := strings.ToLower(jx.Str(b["budget_entity_name"]))
		if target != "" && (target == name || target == id) {
			return b
		}
	}
	return nil
}

func budgetOwner(b jx.M) string {
	if jx.Truthy(b["user"]) {
		return strings.ToLower(jx.Str(b["user"]))
	}
	return strings.ToLower(jx.Str(b["budget_entity_name"]))
}

// GetUserBudgetContext returns the individual, universal and cost center budgets for one user.
func GetUserBudgetContext(ctx context.Context, login string, live bool) jx.M {
	target := strings.ToLower(login)
	costCenters := UserCostCenters(login)
	entities := []jx.M{}
	seen := jx.StrSet{}
	for _, cc := range costCenters {
		key := "enterprise\x00" + jx.Str(cc["enterprise"])
		if !seen.Has(key) {
			seen.Add(key)
			entities = append(entities, jx.M{"entity_type": "enterprise", "entity_name": cc["enterprise"]})
		}
	}
	if primary := ResolveEntityForUser(login, ""); primary != nil {
		key := jx.Str(primary["entity_type"]) + "\x00" + jx.Str(primary["entity_name"])
		if !seen.Has(key) {
			seen.Add(key)
			entities = append(entities, primary)
		}
	}
	perEntity := map[string][]jx.M{}
	for _, ent := range entities {
		name := jx.Str(ent["entity_name"])
		var raw []jx.M
		if live {
			raw = FetchBudgets(ctx, jx.Str(ent["entity_type"]), name, "")
			if len(raw) == 0 {
				raw = CachedBudgets(name)
			}
		} else {
			raw = CachedBudgets(name)
		}
		perEntity[name] = raw
	}
	var personal, universal jx.M
	for _, ent := range entities {
		name := jx.Str(ent["entity_name"])
		for _, b := range perEntity[name] {
			switch jx.Str(b["budget_scope"]) {
			case ScopeUser:
				if budgetOwner(b) == target && personal == nil {
					personal = NormalizeBudget(b, jx.Str(ent["entity_type"]), name)
				}
			case ScopeUniversal:
				if universal == nil {
					universal = NormalizeBudget(b, jx.Str(ent["entity_type"]), name)
				}
			}
		}
	}
	for _, cc := range costCenters {
		ent := jx.Str(cc["enterprise"])
		if match := matchCostCenterBudget(perEntity[ent], cc); match != nil {
			cc["budget"] = NormalizeBudget(match, "enterprise", ent)
		}
	}
	var effective, source any
	switch {
	case personal != nil:
		effective, source = personal, "personal"
	case universal != nil:
		effective, source = universal, "universal"
	}
	nilable := func(m jx.M) any {
		if m == nil {
			return nil
		}
		return m
	}
	return jx.M{
		"live":             live,
		"personal_budget":  nilable(personal),
		"universal_budget": nilable(universal),
		"effective_budget": effective,
		"effective_source": source,
		"cost_centers":     costCenters,
		"entities":         entities,
	}
}

// BudgetErrorText summarises a {"error","status_code","response"} result.
func BudgetErrorText(result jx.M) string {
	response := jx.Map(result["response"])
	parts := []string{}
	if msg := response["message"]; jx.Truthy(msg) {
		parts = append(parts, jx.Str(msg))
	}
	if errs := jx.List(response["errors"]); errs != nil {
		for _, e := range errs {
			if m := jx.Map(e); m != nil && jx.Truthy(m["message"]) {
				parts = append(parts, jx.Str(m["message"]))
			} else {
				parts = append(parts, jx.Dumps(e))
			}
		}
	}
	if len(parts) == 0 {
		parts = []string{jx.Str(jx.GetOr(result, "error", "Unknown error"))}
	}
	nonEmpty := []string{}
	for _, p := range parts {
		if p != "" {
			nonEmpty = append(nonEmpty, p)
		}
	}
	text := strings.Join(nonEmpty, "; ")
	if st := result["status_code"]; jx.Truthy(st) {
		return fmt.Sprintf("%s (HTTP %s)", text, jx.Str(st))
	}
	return text
}

// ProvisionUserBudget creates or updates the real GitHub user-scope AI-credit budget.
// The result is always safe to persist: {"status": created|updated|failed, ...}.
func ProvisionUserBudget(ctx context.Context, login string, amount float64, preferredOrg string, preventFurtherUsage, enableAlerts bool) jx.M {
	entity := ResolveEntityForUser(login, preferredOrg)
	if entity == nil {
		return jx.M{
			"status":    "failed",
			"error":     "No GitHub enterprise or organization is configured, so no budget could be created.",
			"synced_at": jx.NowISO(),
		}
	}
	entityType := jx.Str(entity["entity_type"])
	entityName := jx.Str(entity["entity_name"])
	api := APIForEntity(entityType, entityName)
	if api == nil {
		return jx.M{
			"status": "failed", "entity_type": entityType, "entity_name": entityName,
			"error":     fmt.Sprintf("No PAT with access to %s '%s'.", entityType, entityName),
			"synced_at": jx.NowISO(),
		}
	}
	existingID := ""
	budgets, err := api.GetAllBudgetsPaginated(ctx, entityType, entityName, ScopeUser, false)
	if err != nil {
		Logger.Warn("[budget] Could not list existing budgets: " + err.Error())
	}
	for _, b := range budgets {
		if budgetOwner(b) == strings.ToLower(login) {
			existingID = jx.Str(b["id"])
			break
		}
	}
	amount = jx.Round(amount, 2)
	if existingID != "" {
		result := api.UpdateBudget(ctx, entityType, entityName, existingID, jx.M{
			"budget_amount":         amount,
			"prevent_further_usage": preventFurtherUsage,
		})
		if _, failed := result["error"]; failed {
			return jx.M{
				"status": "failed", "entity_type": entityType, "entity_name": entityName,
				"budget_id": existingID, "amount": amount,
				"error": BudgetErrorText(result), "synced_at": jx.NowISO(),
			}
		}
		Logger.Info(fmt.Sprintf("[budget] Updated GitHub budget %s for %s -> $%v", existingID, login, amount))
		return jx.M{
			"status": "updated", "entity_type": entityType, "entity_name": entityName,
			"budget_id": existingID, "amount": amount, "scope": ScopeUser, "synced_at": jx.NowISO(),
		}
	}
	recipients := jx.L{}
	if enableAlerts {
		recipients = jx.L{login}
	}
	result := api.CreateBudget(ctx, entityType, entityName, jx.M{
		"budget_type":           BudgetType,
		"budget_product_sku":    AICreditsSKU,
		"budget_scope":          ScopeUser,
		"budget_entity_name":    login,
		"budget_amount":         amount,
		"prevent_further_usage": preventFurtherUsage,
		"user":                  login,
		"consumed_amount":       0,
		"budget_alerting":       jx.M{"will_alert": enableAlerts, "alert_recipients": recipients},
	})
	if _, failed := result["error"]; failed {
		return jx.M{
			"status": "failed", "entity_type": entityType, "entity_name": entityName,
			"amount": amount, "error": BudgetErrorText(result), "synced_at": jx.NowISO(),
		}
	}
	budgetID := jx.Str(jx.GetMap(result, "budget")["id"])
	if budgetID == "" {
		budgetID = jx.Str(result["id"])
	}
	Logger.Info(fmt.Sprintf("[budget] Created GitHub budget %s for %s -> $%v", budgetID, login, amount))
	return jx.M{
		"status": "created", "entity_type": entityType, "entity_name": entityName,
		"budget_id": budgetID, "amount": amount, "scope": ScopeUser, "synced_at": jx.NowISO(),
	}
}
