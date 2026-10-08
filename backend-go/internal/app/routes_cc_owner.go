package app

// Admin ownership assignment and authenticated, center-scoped owner views
// (Python routers/cost_center_owner.py).

import (
	"bytes"
	"context"
	"encoding/json"
	"math"
	"strconv"
	"strings"

	"github.com/satomic/octofinance/backend-go/internal/jx"
)

func init() { registerRoutes(registerCCOwnerRoutes) }

func registerCCOwnerRoutes(r *Router) {
	r.Handle("GET /api/data/cost-center-owners", ccoListOwners)
	r.Handle("PUT /api/data/cost-center-owner", ccoAssignOwner)
	r.Handle("GET /api/me/owned-cost-centers", ccoMyOwnedCenters)
	r.Handle("GET /api/me/owned-cost-center", ccoOwnerDashboard)
	r.Handle("PUT /api/me/owned-cost-center/user-budget", ccoSaveUserBudget)
	r.Handle("PUT /api/me/owned-cost-center/settings", ccoUpdateSettings)
}

// ---------------------------------------------------------------------------
// Pydantic-style request validation (FastAPI 422 shapes)
// ---------------------------------------------------------------------------

type ccoValidator struct {
	body jx.M
	errs jx.L
}

func ccoStrPtr(s string) *string { return &s }

func (v *ccoValidator) add(e jx.M) { v.errs = append(v.errs, e) }

func (v *ccoValidator) missing(loc string) {
	v.add(jx.M{"type": "missing", "loc": jx.L{"body", loc}, "msg": "Field required", "input": v.body})
}

// str validates a str field (strict: no number coercion, like pydantic v2).
func (v *ccoValidator) str(name string, def *string) string {
	raw, ok := v.body[name]
	if !ok {
		if def == nil {
			v.missing(name)
			return ""
		}
		return *def
	}
	s, isStr := raw.(string)
	if !isStr {
		v.add(jx.M{"type": "string_type", "loc": jx.L{"body", name}, "msg": "Input should be a valid string", "input": raw})
		return ""
	}
	return s
}

// ccoParseBool mirrors pydantic's lax bool parsing; errType is "" on success.
func ccoParseBool(raw any) (bool, string) {
	switch t := raw.(type) {
	case bool:
		return t, ""
	case float64:
		if t == 0 {
			return false, ""
		}
		if t == 1 {
			return true, ""
		}
		return false, "bool_parsing"
	case string:
		switch strings.ToLower(strings.TrimSpace(t)) {
		case "0", "off", "f", "false", "n", "no":
			return false, ""
		case "1", "on", "t", "true", "y", "yes":
			return true, ""
		}
		return false, "bool_parsing"
	}
	return false, "bool_type"
}

func ccoBoolErr(errType string, loc jx.L, raw any) jx.M {
	msg := "Input should be a valid boolean"
	if errType == "bool_parsing" {
		msg = "Input should be a valid boolean, unable to interpret input"
	}
	return jx.M{"type": errType, "loc": loc, "msg": msg, "input": raw}
}

func (v *ccoValidator) boolean(name string, def *bool) bool {
	raw, ok := v.body[name]
	if !ok {
		if def == nil {
			v.missing(name)
			return false
		}
		return *def
	}
	b, errType := ccoParseBool(raw)
	if errType != "" {
		v.add(ccoBoolErr(errType, jx.L{"body", name}, raw))
	}
	return b
}

// number validates a float field; ok is false when an error was recorded.
func (v *ccoValidator) number(name string) (float64, bool) {
	raw, present := v.body[name]
	if !present {
		v.missing(name)
		return 0, false
	}
	switch t := raw.(type) {
	case float64:
		return t, true
	case bool:
		if t {
			return 1, true
		}
		return 0, true
	case string:
		f, err := strconv.ParseFloat(strings.TrimSpace(t), 64)
		if err != nil {
			v.add(jx.M{"type": "float_parsing", "loc": jx.L{"body", name},
				"msg": "Input should be a valid number, unable to parse string as a number", "input": raw})
			return 0, false
		}
		return f, true
	}
	v.add(jx.M{"type": "float_type", "loc": jx.L{"body", name}, "msg": "Input should be a valid number", "input": raw})
	return 0, false
}

// forbidExtra reports extra_forbidden for unknown keys (in body order).
func (v *ccoValidator) forbidExtra(keys []string, allowed ...string) {
	ok := jx.StrSet{}
	for _, a := range allowed {
		ok.Add(a)
	}
	for _, k := range keys {
		if !ok.Has(k) {
			v.add(jx.M{"type": "extra_forbidden", "loc": jx.L{"body", k}, "msg": "Extra inputs are not permitted", "input": v.body[k]})
		}
	}
}

func (v *ccoValidator) result() *Resp {
	if len(v.errs) == 0 {
		return nil
	}
	return JSONStatus(422, jx.M{"detail": v.errs})
}

// ccoBody decodes the JSON object body and its key order. A nil *Resp means success.
func ccoBody(c *Ctx) (jx.M, []string, *Resp) {
	raw := bytes.TrimSpace(c.Body())
	if len(raw) == 0 {
		return nil, nil, JSONStatus(422, jx.M{"detail": jx.L{jx.M{
			"type": "missing", "loc": jx.L{"body"}, "msg": "Field required", "input": nil}}})
	}
	var any_ any
	if err := json.Unmarshal(raw, &any_); err != nil {
		return nil, nil, JSONStatus(422, jx.M{"detail": jx.L{jx.M{
			"type": "json_invalid", "loc": jx.L{"body", 0}, "msg": "JSON decode error",
			"input": jx.M{}, "ctx": jx.M{"error": err.Error()}}}})
	}
	m, ok := any_.(map[string]any)
	if !ok {
		return nil, nil, JSONStatus(422, jx.M{"detail": jx.L{jx.M{
			"type": "model_attributes_type", "loc": jx.L{"body"},
			"msg": "Input should be a valid dictionary or object to extract fields from", "input": any_}}})
	}
	keys := []string{}
	dec := json.NewDecoder(bytes.NewReader(raw))
	if _, err := dec.Token(); err == nil {
		seen := jx.StrSet{}
		for dec.More() {
			t, err := dec.Token()
			if err != nil {
				break
			}
			k, _ := t.(string)
			if !seen.Has(k) {
				seen.Add(k)
				keys = append(keys, k)
			}
			var skip json.RawMessage
			if dec.Decode(&skip) != nil {
				break
			}
		}
	}
	return m, keys, nil
}

// ccoQueryErrors validates required/bool query params like FastAPI.
type ccoQuery struct {
	c    *Ctx
	errs jx.L
}

func (q *ccoQuery) required(name string) string {
	if !q.c.HasQuery(name) {
		q.errs = append(q.errs, jx.M{"type": "missing", "loc": jx.L{"query", name}, "msg": "Field required", "input": nil})
		return ""
	}
	return q.c.Query(name)
}

func (q *ccoQuery) boolean(name string, def bool) bool {
	if !q.c.HasQuery(name) {
		return def
	}
	raw := q.c.Query(name)
	b, errType := ccoParseBool(raw)
	if errType != "" {
		q.errs = append(q.errs, ccoBoolErr(errType, jx.L{"query", name}, raw))
	}
	return b
}

func (q *ccoQuery) result() *Resp {
	if len(q.errs) == 0 {
		return nil
	}
	return JSONStatus(422, jx.M{"detail": q.errs})
}

// ccoHTTPError is an HTTPException raised inside a helper.
type ccoHTTPError struct {
	status int
	detail any
}

func (e *ccoHTTPError) resp() *Resp { return JSONStatus(e.status, jx.M{"detail": e.detail}) }

func ccoCode(status int, code string) *ccoHTTPError {
	return &ccoHTTPError{status, jx.M{"code": code}}
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

func ccoIndividualCreditBudgets(budgets []jx.M, login string) []jx.M {
	matches := []jx.M{}
	for _, b := range budgets {
		skus := jx.GetList(b, "budget_product_skus")
		if !jx.Truthy(skus) {
			skus = jx.L{b["budget_product_sku"]}
		}
		onlyCredits := len(skus) > 0
		for _, s := range skus {
			if str, ok := s.(string); !ok || str != AICreditsSKU {
				onlyCredits = false
				break
			}
		}
		owner := b["user"]
		if !jx.Truthy(owner) {
			owner = b["budget_entity_name"]
		}
		if !jx.Truthy(owner) {
			owner = ""
		}
		if jx.GetOr(b, "budget_scope", nil) == ScopeUser &&
			jx.GetOr(b, "budget_type", nil) == BudgetType &&
			onlyCredits &&
			strings.ToLower(jx.Str(owner)) == strings.ToLower(login) {
			matches = append(matches, b)
		}
	}
	return matches
}

func ccoReadIndividualBudgets(ctx context.Context, enterprise string) ([]jx.M, *ccoHTTPError) {
	api := APIs.APIForEnterprise(enterprise)
	if api == nil {
		return nil, ccoCode(503, "budgets_unavailable")
	}
	budgets, err := api.GetAllBudgetsPaginated(ctx, "enterprise", enterprise, ScopeUser, true)
	if err != nil {
		return nil, ccoCode(502, "budgets_unavailable")
	}
	return budgets, nil
}

func ccoCurrentUser(c *Ctx, admin bool) (jx.M, *ccoHTTPError) {
	if c.User == nil {
		return nil, &ccoHTTPError{401, "Authentication required"}
	}
	if admin && !c.IsAdmin() {
		return nil, &ccoHTTPError{403, "Administrator access required"}
	}
	return c.User, nil
}

func ccoGetCenter(enterprise, costCenterID string) (jx.M, *ccoHTTPError) {
	snapshot := Collector.LoadLatestMap("cost_centers", enterprise)
	for _, center := range jx.GetMaps(snapshot, "cost_centers") {
		if shareIDStr(center["id"]) == costCenterID {
			return center, nil
		}
	}
	return nil, &ccoHTTPError{404, "Cost center not found"}
}

func ccoRequireOwner(c *Ctx, enterprise, costCenterID string) (jx.M, *ccoHTTPError) {
	user, herr := ccoCurrentUser(c, false)
	if herr != nil {
		return nil, herr
	}
	for _, center := range OwnedCostCenters(jx.Str(user["login"])) {
		if jx.Str(center["enterprise"]) == enterprise && jx.Str(center["id"]) == costCenterID {
			return user, nil
		}
	}
	return nil, &ccoHTTPError{403, "You do not own this cost center"}
}

func ccoIsMember(center jx.M, login string) bool {
	for _, m := range jx.GetMaps(center, "members") {
		if strings.ToLower(jx.Str(jx.GetOr(m, "login", ""))) == strings.ToLower(login) {
			return true
		}
	}
	return false
}

func ccoScopedRecords(records []CSVRecord, enterprise string, center jx.M, start, end string) ([]CSVRecord, bool) {
	centerName, nameIsStr := center["name"].(string)
	matching := 0
	for _, snapAny := range Collector.LoadAllLatest("cost_centers") {
		for _, item := range jx.GetMaps(jx.Map(snapAny), "cost_centers") {
			if n, ok := item["name"].(string); ok && nameIsStr && n == centerName {
				matching++
				break
			}
		}
	}
	ambiguous := matching > 1
	centerID := shareIDStr(center["id"])
	result := []CSVRecord{}
	for _, r := range records {
		recEnt := r["enterprise"]
		if recEnt == "" {
			recEnt = r["enterprise_slug"]
		}
		if recEnt != "" && strings.ToLower(recEnt) != strings.ToLower(enterprise) {
			continue
		}
		if recEnt == "" && ambiguous {
			continue
		}
		if id := r["cost_center_id"]; id != "" {
			if id != centerID {
				continue
			}
		} else {
			name, has := r["cost_center_name"]
			if !(has && nameIsStr && name == centerName) {
				continue
			}
		}
		day := r["date"]
		if (start != "" && day < start) || (end != "" && day > end) {
			continue
		}
		rec := make(CSVRecord, len(r)+1)
		for k, v := range r {
			rec[k] = v
		}
		rec["username"] = strings.ToLower(r["username"])
		result = append(result, rec)
	}
	return result, ambiguous
}

func ccoLiveCenter(ctx context.Context, enterprise, costCenterID string) (jx.M, *ccoHTTPError) {
	api := APIs.APIForEnterprise(enterprise)
	if api == nil {
		return nil, &ccoHTTPError{503, "No GitHub API client available"}
	}
	center, err := api.GetCostCenter(ctx, enterprise, costCenterID)
	if err != nil || center == nil {
		return nil, &ccoHTTPError{502, "Unable to read current credit state from GitHub"}
	}
	return center, nil
}

func ccoVerifyBudgetWrite(c *Ctx, enterprise, costCenterID, login string) (jx.M, *ccoHTTPError) {
	ctx := c.R.Context()
	user, herr := ccoRequireOwner(c, enterprise, costCenterID)
	if herr != nil {
		return nil, herr
	}
	center, herr := ccoGetCenter(enterprise, costCenterID)
	if herr != nil {
		return nil, herr
	}
	if !ccoIsMember(center, login) {
		return nil, ccoCode(403, "budget_member_only")
	}
	latest, herr := ccoLiveCenter(ctx, enterprise, costCenterID)
	if herr != nil {
		return nil, ccoCode(503, "cap_unknown")
	}
	if st, ok := latest["state"].(string); !ok || st != "active" {
		return nil, ccoCode(403, "budget_member_only")
	}
	if pool, ok := latest["ai_credit_pool_enabled"].(bool); !ok || !pool {
		code := "cap_unknown"
		if ok && !pool {
			code = "cap_off"
		}
		return nil, ccoCode(403, code)
	}
	api := APIs.APIForEnterprise(enterprise)
	if api == nil {
		return nil, ccoCode(503, "budget_member_unverified")
	}
	members := jx.StrSet{}
	addRoster := func(roster []jx.M) {
		for _, m := range roster {
			members.Add(strings.ToLower(jx.Str(jx.GetOr(m, "login", ""))))
		}
	}
	for _, resource := range jx.GetMaps(latest, "resources") {
		name := jx.Str(jx.GetOr(resource, "name", ""))
		switch jx.GetOr(resource, "type", nil) {
		case "User":
			members.Add(strings.ToLower(name))
		case "Team":
			if org, team, found := strings.Cut(name, "/"); found {
				addRoster(api.GetTeamMembers(ctx, org, team))
			} else {
				addRoster(api.GetEnterpriseTeamMembers(ctx, enterprise, name))
			}
		case "Org":
			addRoster(api.GetOrgMembers(ctx, name))
		}
	}
	if !members.Has(strings.ToLower(login)) || !members.Has(strings.ToLower(jx.Str(user["login"]))) {
		return nil, ccoCode(403, "budget_member_only")
	}
	if _, herr := ccoRequireOwner(c, enterprise, costCenterID); herr != nil {
		return nil, herr
	}
	return user, nil
}

// ---------------------------------------------------------------------------
// Endpoints
// ---------------------------------------------------------------------------

func ccoListOwners(c *Ctx) any {
	q := &ccoQuery{c: c}
	enterprise := q.required("enterprise")
	if r := q.result(); r != nil {
		return r
	}
	if _, herr := ccoCurrentUser(c, true); herr != nil {
		return herr.resp()
	}
	out := jx.M{}
	for centerID, members := range jx.GetMap(LoadCCOwners(), enterprise) {
		out[centerID] = jx.SortedKeys(jx.Map(members))
	}
	return jx.M{"owners": out}
}

func ccoAssignOwner(c *Ctx) any {
	body, keys, resp := ccoBody(c)
	if resp != nil {
		return resp
	}
	v := &ccoValidator{body: body}
	enterprise := v.str("enterprise", nil)
	costCenterID := v.str("cost_center_id", nil)
	rawLogin := v.str("login", nil)
	enabled := v.boolean("enabled", nil)
	v.forbidExtra(keys, "enterprise", "cost_center_id", "login", "enabled")
	if r := v.result(); r != nil {
		return r
	}
	user, herr := ccoCurrentUser(c, true)
	if herr != nil {
		return herr.resp()
	}
	center, herr := ccoGetCenter(enterprise, costCenterID)
	if herr != nil {
		return herr.resp()
	}
	login := strings.ToLower(strings.TrimSpace(rawLogin))
	if enabled {
		state := jx.GetOr(center, "state", "active")
		if state != "active" || !ccoIsMember(center, login) {
			return HTTPError(400, "Owner must be a member of this active cost center")
		}
	}
	actor := jx.Str(user["login"])
	SetCCOwner(enterprise, costCenterID, login, enabled, actor)
	AppendAuditLog(jx.M{
		"timestamp": jx.NowISO(), "action": "set_cost_center_owner", "actor": actor,
		"enterprise": enterprise, "cost_center_id": costCenterID, "login": rawLogin, "enabled": enabled,
	})
	return jx.M{"owners": CCOwnerLogins(enterprise, costCenterID)}
}

func ccoMyOwnedCenters(c *Ctx) any {
	user, herr := ccoCurrentUser(c, false)
	if herr != nil {
		return herr.resp()
	}
	return jx.M{"cost_centers": OwnedCostCenters(jx.Str(user["login"]))}
}

func ccoOwnerDashboard(c *Ctx) any {
	q := &ccoQuery{c: c}
	enterprise := q.required("enterprise")
	costCenterID := q.required("cost_center_id")
	period := c.Query("period", "all")
	live := q.boolean("live", true)
	if r := q.result(); r != nil {
		return r
	}
	ctx := c.R.Context()
	if _, herr := ccoRequireOwner(c, enterprise, costCenterID); herr != nil {
		return herr.resp()
	}
	cached, herr := ccoGetCenter(enterprise, costCenterID)
	if herr != nil {
		return herr.resp()
	}
	center := jx.Copy(cached)
	creditStatus := "cached"
	var creditError, checkedAt any
	capVerified := false
	if live {
		latest, herr := ccoLiveCenter(ctx, enterprise, costCenterID)
		if herr == nil {
			if jx.GetOr(latest, "state", "active") != "active" {
				return HTTPError(403, "Cost center is no longer active")
			}
			for _, k := range []string{"ai_credit_pool_enabled", "ai_credit_pool_state"} {
				if v, ok := latest[k]; ok {
					center[k] = v
				}
			}
			_, capVerified = latest["ai_credit_pool_enabled"].(bool)
			creditStatus = "live"
			checkedAt = jx.NowISO()
		} else {
			creditStatus = "unavailable"
			creditError = herr.detail
		}
	}
	mode, start, end := ResolvePeriod(period, "", "")
	aiRecords, ambiguous := ccoScopedRecords(LoadAllCSVRecords(CSVTypeAI), enterprise, center, start, end)
	usageRecords, usageAmbiguous := ccoScopedRecords(LoadAllCSVRecords(CSVTypeUsage), enterprise, center, start, end)
	budgetStatus := "live"
	budgets, berr := ccoReadIndividualBudgets(ctx, enterprise)
	if berr != nil {
		budgets = CachedBudgets(enterprise)
		budgetStatus = "unavailable"
	}
	var readOnly any
	switch {
	case !capVerified:
		readOnly = "cap_unknown"
	case center["ai_credit_pool_enabled"] != true:
		readOnly = "cap_off"
	case budgetStatus != "live":
		readOnly = "budgets_unavailable"
	}
	userBudgets := []jx.M{}
	seen := jx.StrSet{}
	for _, member := range jx.GetMaps(center, "members") {
		login := jx.Str(jx.GetOr(member, "login", ""))
		if login == "" || seen.Has(strings.ToLower(login)) {
			continue
		}
		seen.Add(strings.ToLower(login))
		matches := ccoIndividualCreditBudgets(budgets, login)
		normalized := []jx.M{}
		for _, b := range matches {
			normalized = append(normalized, NormalizeBudget(b, "enterprise", enterprise))
		}
		userBudgets = append(userBudgets, jx.M{
			"login":    login,
			"budgets":  normalized,
			"can_edit": readOnly == nil && len(matches) <= 1,
		})
	}
	if _, herr := ccoRequireOwner(c, enterprise, costCenterID); herr != nil {
		return herr.resp()
	}
	return jx.M{
		"enterprise":              enterprise,
		"cost_center":             center,
		"period":                  jx.M{"mode": mode, "start": start, "end": end},
		"ai_usage":                BuildAIUsageSection(aiRecords),
		"usage":                   BuildUsageSection(usageRecords),
		"ambiguous_billing_scope": ambiguous || usageAmbiguous,
		"credit_status":           creditStatus,
		"credit_error":            creditError,
		"credit_checked_at":       checkedAt,
		"cap_verified":            capVerified,
		"budget_status":           budgetStatus,
		"budget_read_only_reason": readOnly,
		"user_budgets":            userBudgets,
	}
}

// ccoMultipleOf mirrors pydantic-core's float multiple_of check (verified
// empirically against pydantic-core 2.41: |round(v/m)*m - v| <= 1e-9).
func ccoMultipleOf(value, multiple float64) bool {
	// The explicit float64 conversion keeps arm64 from fusing into an FMA.
	product := float64(math.Round(value/multiple) * multiple)
	return math.Abs(product-value) <= 1e-9
}

func ccoSaveUserBudget(c *Ctx) any {
	body, keys, resp := ccoBody(c)
	if resp != nil {
		return resp
	}
	v := &ccoValidator{body: body}
	enterprise := v.str("enterprise", nil)
	costCenterID := v.str("cost_center_id", nil)
	rawLogin := v.str("login", nil)
	if s, ok := body["login"].(string); ok && len([]rune(s)) < 1 {
		v.add(jx.M{"type": "string_too_short", "loc": jx.L{"body", "login"},
			"msg": "String should have at least 1 character", "input": s, "ctx": jx.M{"min_length": 1}})
	}
	amount, amountOK := v.number("amount")
	if amountOK {
		switch {
		case math.IsNaN(amount) || math.IsInf(amount, 0):
			v.add(jx.M{"type": "finite_number", "loc": jx.L{"body", "amount"}, "msg": "Input should be a finite number", "input": body["amount"]})
		case !ccoMultipleOf(amount, 0.01):
			v.add(jx.M{"type": "multiple_of", "loc": jx.L{"body", "amount"}, "msg": "Input should be a multiple of 0.01",
				"input": body["amount"], "ctx": jx.M{"multiple_of": 0.01}})
		case !(amount > 0):
			v.add(jx.M{"type": "greater_than", "loc": jx.L{"body", "amount"}, "msg": "Input should be greater than 0",
				"input": body["amount"], "ctx": jx.M{"gt": 0.0}})
		}
	}
	prevent := v.boolean("prevent_further_usage", ccoBoolPtr(true))
	v.forbidExtra(keys, "enterprise", "cost_center_id", "login", "amount", "prevent_further_usage")
	if r := v.result(); r != nil {
		return r
	}
	ctx := c.R.Context()
	login := strings.ToLower(strings.TrimSpace(rawLogin))
	if _, herr := ccoVerifyBudgetWrite(c, enterprise, costCenterID, login); herr != nil {
		return herr.resp()
	}
	budgets, herr := ccoReadIndividualBudgets(ctx, enterprise)
	if herr != nil {
		return herr.resp()
	}
	matches := ccoIndividualCreditBudgets(budgets, login)
	if len(matches) > 1 || (len(matches) == 1 && !jx.Truthy(matches[0]["id"])) {
		return ccoCode(409, "budget_ambiguous").resp()
	}
	user, herr := ccoVerifyBudgetWrite(c, enterprise, costCenterID, login)
	if herr != nil {
		return herr.resp()
	}
	api := APIs.APIForEnterprise(enterprise)
	if api == nil {
		return ccoCode(503, "budgets_unavailable").resp()
	}
	fields := jx.M{"budget_amount": amount, "prevent_further_usage": prevent}
	var result jx.M
	if len(matches) > 0 {
		result = api.UpdateBudget(ctx, "enterprise", enterprise, jx.Str(matches[0]["id"]), fields)
	} else {
		result = api.CreateBudget(ctx, "enterprise", enterprise, jx.Merge(fields, jx.M{
			"budget_type": BudgetType, "budget_product_sku": AICreditsSKU,
			"budget_scope": ScopeUser, "budget_entity_name": login, "user": login,
			"consumed_amount": 0, "budget_alerting": jx.M{"will_alert": false, "alert_recipients": jx.L{}},
		}))
	}
	if result == nil || jx.Truthy(result["error"]) {
		return ccoCode(502, "budget_write_failed").resp()
	}
	action := "created"
	var budgetID any
	if len(matches) > 0 {
		action = "updated"
		budgetID = matches[0]["id"]
	} else {
		src := result
		if b := result["budget"]; jx.Truthy(b) {
			src = jx.Map(b)
		}
		budgetID = jx.Get(src, "id")
	}
	AppendAuditLog(jx.M{
		"timestamp": jx.NowISO(), "action": "owner_set_individual_budget",
		"actor": jx.Str(user["login"]), "enterprise": enterprise, "cost_center_id": costCenterID,
		"login": login, "amount": amount, "prevent_further_usage": prevent,
		"result": action, "budget_id": budgetID,
	})
	return jx.M{"ok": true, "status": action}
}

func ccoBoolPtr(b bool) *bool { return &b }

func ccoUpdateSettings(c *Ctx) any {
	body, keys, resp := ccoBody(c)
	if resp != nil {
		return resp
	}
	v := &ccoValidator{body: body}
	v.str("enterprise", nil)
	v.str("cost_center_id", nil)
	v.boolean("ai_credit_pool_enabled", nil)
	v.forbidExtra(keys, "enterprise", "cost_center_id", "ai_credit_pool_enabled")
	if r := v.result(); r != nil {
		return r
	}
	if _, herr := ccoCurrentUser(c, false); herr != nil {
		return herr.resp()
	}
	return ccoCode(403, "cap_admin_only").resp()
}
