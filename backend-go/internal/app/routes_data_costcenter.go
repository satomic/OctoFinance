package app

import (
	"context"
	"encoding/json"
	"fmt"
	"sort"
	"strconv"
	"strings"

	"github.com/satomic/octofinance/backend-go/internal/jx"
)

// Cost center, enterprise team and budget dashboards (Python routers/data.py).

func dataLoadEnterpriseList(l *dataLoader) []jx.M {
	list := jx.List(l.latest("enterprise", "all"))
	if list == nil {
		return []jx.M{}
	}
	return jx.Maps(list)
}

// dataResolveEnterprise mirrors _resolve_enterprise: (slug, selected, list).
func dataResolveEnterprise(l *dataLoader, enterprise string) (string, jx.M, []jx.M) {
	list := dataLoadEnterpriseList(l)
	if len(list) == 0 {
		list = APIs.AllEnterprises()
	}
	if len(list) == 0 {
		return "", nil, list
	}
	selectedSlug := dataGetStr(list[0], "slug", "")
	for _, e := range list {
		if v, ok := e["slug"].(string); ok && v == enterprise {
			selectedSlug = enterprise
			break
		}
	}
	for _, e := range list {
		if v, ok := e["slug"].(string); ok && v == selectedSlug {
			return selectedSlug, e, list
		}
	}
	return selectedSlug, nil, list
}

func dataEnterpriseOrgLogins(ctx context.Context, l *dataLoader, slug string, info jx.M) []string {
	orgs := []string{}
	if api := APIs.APIForEnterprise(slug); api != nil {
		for _, o := range api.GetEnterpriseOrgs(ctx, slug) {
			if jx.Truthy(o["login"]) {
				orgs = append(orgs, dataGetStr(o, "login", ""))
			}
		}
	}
	if len(orgs) == 0 {
		patID := jx.Get(info, "pat_id")
		discovered := APIs.AllOrgs()
		if jx.Truthy(patID) {
			for _, o := range discovered {
				if jx.Truthy(o["login"]) && jx.Str(o["pat_id"]) == jx.Str(patID) && o["pat_id"] != nil {
					orgs = append(orgs, dataGetStr(o, "login", ""))
				}
			}
		} else if len(dataLoadEnterpriseList(l)) <= 1 {
			for _, o := range discovered {
				if jx.Truthy(o["login"]) {
					orgs = append(orgs, dataGetStr(o, "login", ""))
				}
			}
		}
	}
	if len(orgs) == 0 {
		for _, e := range APIs.EnterprisePseudoOrgs() {
			if jx.Str(e["slug"]) == slug {
				orgs = []string{EnterprisePseudoOrg(slug)}
				break
			}
		}
	}
	if len(orgs) == 0 && len(dataLoadEnterpriseList(l)) <= 1 {
		keys, _ := l.allLatest("seats")
		orgs = append(orgs, keys...)
	}
	pseudo := EnterprisePseudoOrg(slug)
	if l.latest("seats", pseudo) != nil {
		orgs = append(orgs, pseudo)
	}
	set := jx.StrSet{}
	out := []string{}
	for _, o := range orgs {
		if !set.Has(o) {
			set.Add(o)
			out = append(out, o)
		}
	}
	sort.SliceStable(out, func(i, j int) bool {
		a, b := strings.ToLower(out[i]), strings.ToLower(out[j])
		if a != b {
			return a < b
		}
		return out[i] < out[j]
	})
	return out
}

func dataActiveCostCenters(ccData jx.M) []jx.M {
	out := []jx.M{}
	if !jx.Truthy(ccData) {
		return out
	}
	for _, cc := range jx.GetMaps(ccData, "cost_centers") {
		if dataStateIs(cc, "active") {
			out = append(out, cc)
		}
	}
	return out
}

// dataStateIs is “cc.get("state", "active") == want“.
func dataStateIs(cc jx.M, want string) bool {
	v, ok := cc["state"]
	if !ok {
		return want == "active"
	}
	s, isStr := v.(string)
	return isStr && s == want
}

func dataStrListContains(list jx.L, s string) bool {
	for _, v := range list {
		if v == s {
			return true
		}
	}
	return false
}

func dataSortAnyLower(list jx.L) {
	sort.SliceStable(list, func(i, j int) bool {
		return strings.ToLower(jx.Str(list[i])) < strings.ToLower(jx.Str(list[j]))
	})
}

func dataOrNone(s string) any {
	if s == "" {
		return nil
	}
	return s
}

func dataCCUnassignedUsers(c *Ctx) any {
	enterprise := c.Query("enterprise", "")
	search := c.Query("search", "")
	l := newDataLoader()
	slug, selected, list := dataResolveEnterprise(l, enterprise)
	empty := jx.M{
		"enterprises":         list,
		"selected_enterprise": dataOrNone(slug),
		"enterprise_name":     jx.GetOr(selected, "name", slug),
		"cost_centers":        jx.L{},
		"unassigned_users":    jx.L{},
		"total_unassigned":    0,
		"total_copilot_users": 0,
		"assigned_user_count": 0,
		"orgs":                jx.L{},
		"no_data":             true,
	}
	if slug == "" {
		return empty
	}
	ccData := l.latestMap("cost_centers", slug)
	active := dataActiveCostCenters(ccData)
	if !jx.Truthy(ccData) {
		return empty
	}
	assigned := jx.StrSet{}
	for _, cc := range active {
		for _, m := range jx.GetMaps(cc, "members") {
			if jx.Truthy(m["login"]) {
				assigned.Add(strings.ToLower(dataGetStr(m, "login", "")))
			}
		}
	}

	orgLogins := dataEnterpriseOrgLogins(c.R.Context(), l, slug, selected)
	seatUsers := newDataOM[jx.M]()
	for _, org := range orgLogins {
		sd := l.latestMap("seats", org)
		if !jx.Truthy(sd) {
			continue
		}
		for _, seat := range jx.GetMaps(sd, "seats") {
			assignee := jx.Map(seat["assignee"])
			login := dataGetStr(assignee, "login", "")
			if login == "" {
				continue
			}
			entry := seatUsers.at(strings.ToLower(login), func() jx.M {
				html := jx.Get(assignee, "html_url")
				if !jx.Truthy(html) {
					html = APIs.WebBaseForOrg(org) + "/" + login
				}
				return jx.M{
					"login":                login,
					"avatar_url":           jx.GetOr(assignee, "avatar_url", ""),
					"html_url":             html,
					"orgs":                 jx.L{},
					"teams":                jx.L{},
					"plan_types":           jx.L{},
					"last_activity_at":     jx.OrStr(seat, "last_activity_at", ""),
					"last_activity_editor": jx.OrStr(seat, "last_activity_editor", ""),
					"seat_count":           0,
				}
			})
			if !dataStrListContains(entry["orgs"].(jx.L), org) {
				entry["orgs"] = append(entry["orgs"].(jx.L), org)
			}
			team := jx.Map(seat["assigning_team"])
			teamName := jx.OrStr(team, "name", "")
			if teamName == "" {
				teamName = jx.OrStr(team, "slug", "")
			}
			if teamName != "" && !dataStrListContains(entry["teams"].(jx.L), teamName) {
				entry["teams"] = append(entry["teams"].(jx.L), teamName)
			}
			if pt := jx.OrStr(seat, "plan_type", ""); pt != "" && !dataStrListContains(entry["plan_types"].(jx.L), pt) {
				entry["plan_types"] = append(entry["plan_types"].(jx.L), pt)
			}
			last := jx.OrStr(seat, "last_activity_at", "")
			if cur := jx.Str(entry["last_activity_at"]); last != "" && (cur == "" || last > cur) {
				entry["last_activity_at"] = last
				entry["last_activity_editor"] = jx.OrStr(seat, "last_activity_editor", "")
			}
			entry["seat_count"] = entry["seat_count"].(int) + 1
		}
	}

	unassigned := []jx.M{}
	for _, k := range seatUsers.keys {
		if !assigned.Has(k) {
			unassigned = append(unassigned, seatUsers.m[k])
		}
	}
	if q := strings.ToLower(strings.TrimSpace(search)); q != "" {
		kept := []jx.M{}
		for _, u := range unassigned {
			match := strings.Contains(strings.ToLower(jx.Str(u["login"])), q)
			for _, o := range u["orgs"].(jx.L) {
				match = match || strings.Contains(strings.ToLower(jx.Str(o)), q)
			}
			for _, t := range u["teams"].(jx.L) {
				match = match || strings.Contains(strings.ToLower(jx.Str(t)), q)
			}
			if match {
				kept = append(kept, u)
			}
		}
		unassigned = kept
	}
	for _, u := range unassigned {
		dataSortAnyLower(u["orgs"].(jx.L))
		dataSortAnyLower(u["teams"].(jx.L))
		dataSortAnyLower(u["plan_types"].(jx.L))
	}
	costCenters := []jx.M{}
	for _, cc := range active {
		if jx.Truthy(cc["id"]) && jx.Truthy(cc["name"]) {
			costCenters = append(costCenters, jx.M{
				"id":           jx.GetOr(cc, "id", ""),
				"name":         jx.GetOr(cc, "name", ""),
				"state":        jx.GetOr(cc, "state", "active"),
				"member_count": jx.GetOr(cc, "member_count", 0),
			})
		}
	}
	sort.SliceStable(costCenters, func(i, j int) bool {
		return strings.ToLower(jx.Str(costCenters[i]["name"])) < strings.ToLower(jx.Str(costCenters[j]["name"]))
	})
	sortedUnassigned := append([]jx.M{}, unassigned...)
	sort.SliceStable(sortedUnassigned, func(i, j int) bool {
		return strings.ToLower(jx.Str(sortedUnassigned[i]["login"])) < strings.ToLower(jx.Str(sortedUnassigned[j]["login"]))
	})
	assignedCount := 0
	for _, k := range seatUsers.keys {
		if assigned.Has(k) {
			assignedCount++
		}
	}
	return jx.M{
		"enterprises":         list,
		"selected_enterprise": slug,
		"enterprise_name":     jx.GetOr(ccData, "enterprise_name", slug),
		"cost_centers":        costCenters,
		"unassigned_users":    sortedUnassigned,
		"total_unassigned":    len(unassigned),
		"total_copilot_users": len(seatUsers.keys),
		"assigned_user_count": assignedCount,
		"orgs":                orgLogins,
		"no_data":             false,
	}
}

// dataStrField decodes a pydantic “str“ field: (value, present, ok).
func dataStrField(raw map[string]json.RawMessage, key string) (string, bool, bool) {
	v, ok := raw[key]
	if !ok {
		return "", false, true
	}
	var s string
	if err := json.Unmarshal(v, &s); err != nil {
		return "", true, false
	}
	return s, true, true
}

// dataMissing is FastAPI's 422 for missing body fields, including the
// "input" member (the whole request body) that pydantic v2 reports.
func dataMissing(c *Ctx, fields ...string) *Resp {
	var input any
	if json.Unmarshal(c.Body(), &input) != nil || input == nil {
		input = jx.M{}
	}
	errs := jx.L{}
	for _, f := range fields {
		errs = append(errs, jx.M{"type": "missing", "loc": jx.L{"body", f}, "msg": "Field required", "input": input})
	}
	return JSONStatus(422, jx.M{"detail": errs})
}

func dataTypeError(field, kind string) *Resp {
	return JSONStatus(422, jx.M{"detail": jx.L{jx.M{"type": kind, "loc": jx.L{"body", field}, "msg": "Input should be a valid " + strings.TrimSuffix(kind, "_type")}}})
}

// dataFindActiveCC returns the active cost center with the given id.
func dataFindActiveCC(l *dataLoader, slug, id string) jx.M {
	for _, cc := range dataActiveCostCenters(l.latestMap("cost_centers", slug)) {
		if v, ok := cc["id"].(string); ok && v == id {
			return cc
		}
	}
	return nil
}

func dataCCAssignUsers(c *Ctx) any {
	var raw map[string]json.RawMessage
	if r := c.Bind(&raw); r != nil {
		return r
	}
	enterprise, _, ok := dataStrField(raw, "enterprise")
	if !ok {
		return dataTypeError("enterprise", "string_type")
	}
	ccID, present, ok := dataStrField(raw, "cost_center_id")
	if !ok {
		return dataTypeError("cost_center_id", "string_type")
	}
	if !present {
		return dataMissing(c, "cost_center_id")
	}
	rawUsers := []string{}
	if v, has := raw["users"]; has {
		if err := json.Unmarshal(v, &rawUsers); err != nil || rawUsers == nil {
			return dataTypeError("users", "list_type")
		}
	}
	set := jx.StrSet{}
	users := []string{}
	for _, u := range rawUsers {
		if u = strings.TrimSpace(u); u != "" && !set.Has(u) {
			set.Add(u)
			users = append(users, u)
		}
	}
	sort.SliceStable(users, func(i, j int) bool {
		a, b := strings.ToLower(users[i]), strings.ToLower(users[j])
		if a != b {
			return a < b
		}
		return users[i] < users[j]
	})
	if len(users) == 0 {
		return jx.M{"error": "Select at least one user to assign."}
	}
	if strings.TrimSpace(ccID) == "" {
		return jx.M{"error": "Select a cost center."}
	}
	l := newDataLoader()
	slug, selected, _ := dataResolveEnterprise(l, enterprise)
	if slug == "" || !jx.Truthy(selected) {
		return jx.M{"error": "No enterprise data found. Run Sync Data first."}
	}
	target := dataFindActiveCC(l, slug, ccID)
	if target == nil {
		return jx.M{"error": fmt.Sprintf("Active cost center '%s' was not found.", ccID)}
	}
	api := APIs.APIForEnterprise(slug)
	if api == nil {
		return jx.M{"error": fmt.Sprintf("No API client found for enterprise '%s'.", slug)}
	}
	ctx := c.R.Context()
	apiResult, err := api.AddCostCenterResources(ctx, slug, ccID, users, nil, nil)
	if err != nil {
		return jx.M{"error": fmt.Sprintf("GitHub API assignment failed: %v", err)}
	}
	syncResult := Collector.SyncCostCentersForEnterprise(ctx, selected, nil)
	AppendAuditLog(jx.M{
		"timestamp":        jx.NowISO(),
		"action":           "assign_cost_center_users",
		"enterprise":       slug,
		"cost_center_id":   ccID,
		"cost_center_name": jx.GetOr(target, "name", ""),
		"users":            users,
		"api_result":       apiResult,
	})
	return jx.M{
		"status":         "ok",
		"enterprise":     slug,
		"cost_center":    jx.M{"id": ccID, "name": jx.GetOr(target, "name", "")},
		"assigned_users": users,
		"api_result":     apiResult,
		"sync_result":    syncResult,
	}
}

// dataPyBool decodes a pydantic (lax) “bool“ field.
func dataPyBool(v json.RawMessage) (bool, bool) {
	var x any
	if json.Unmarshal(v, &x) != nil {
		return false, false
	}
	switch t := x.(type) {
	case bool:
		return t, true
	case float64:
		if t == 0 || t == 1 {
			return t == 1, true
		}
	case string:
		switch strings.ToLower(strings.TrimSpace(t)) {
		case "1", "true", "t", "yes", "y", "on":
			return true, true
		case "0", "false", "f", "no", "n", "off":
			return false, true
		}
	}
	return false, false
}

func dataCCAICreditPool(c *Ctx) any {
	var raw map[string]json.RawMessage
	if r := c.Bind(&raw); r != nil {
		return r
	}
	enterprise, _, ok := dataStrField(raw, "enterprise")
	if !ok {
		return dataTypeError("enterprise", "string_type")
	}
	ccID, present, ok := dataStrField(raw, "cost_center_id")
	if !ok {
		return dataTypeError("cost_center_id", "string_type")
	}
	missing := []string{}
	if !present {
		missing = append(missing, "cost_center_id")
	}
	enabledRaw, hasEnabled := raw["enabled"]
	if !hasEnabled {
		missing = append(missing, "enabled")
	}
	if len(missing) > 0 {
		return dataMissing(c, missing...)
	}
	enabled, ok := dataPyBool(enabledRaw)
	if !ok {
		return dataTypeError("enabled", "bool_type")
	}
	if strings.TrimSpace(ccID) == "" {
		return jx.M{"error": "Select a cost center."}
	}
	l := newDataLoader()
	slug, selected, _ := dataResolveEnterprise(l, enterprise)
	if slug == "" || !jx.Truthy(selected) {
		return jx.M{"error": "No enterprise data found. Run Sync Data first."}
	}
	target := dataFindActiveCC(l, slug, ccID)
	if target == nil {
		return jx.M{"error": fmt.Sprintf("Active cost center '%s' was not found.", ccID)}
	}
	api := APIs.APIForEnterprise(slug)
	if api == nil {
		return jx.M{"error": fmt.Sprintf("No API client found for enterprise '%s'.", slug)}
	}
	ccName := jx.OrStr(target, "name", "")
	if ccName == "" {
		ccName = ccID
	}
	action := "Disabling"
	if enabled {
		action = "Enabling"
	}
	Syncs.Log("info", fmt.Sprintf("%s AI credit included usage cap for cost center '%s' (%s)", action, ccName, slug))
	apiResult, err := api.UpdateCostCenter(c.R.Context(), slug, ccID, nil, &enabled)
	if err != nil {
		Syncs.Log("error", fmt.Sprintf("Cost center '%s': AI credit cap update failed - %v", ccName, err))
		return jx.M{"error": fmt.Sprintf("GitHub API update failed: %v", err)}
	}
	var poolState any
	if apiResult != nil {
		poolState = apiResult["ai_credit_pool_state"]
	}
	Collector.UpdateCachedCostCenter(slug, ccID, jx.M{
		"ai_credit_pool_enabled": enabled,
		"ai_credit_pool_state":   poolState,
	})
	capTarget, hasCap := jx.Map(poolState)["target_amount"]
	state := "disabled"
	if enabled {
		state = "enabled"
	}
	msg := fmt.Sprintf("Cost center '%s': AI credit cap %s", ccName, state)
	if enabled && hasCap && capTarget != nil {
		msg += fmt.Sprintf(" (included allowance %s)", dataPyRepr(capTarget))
	}
	Syncs.Log("info", msg)
	AppendAuditLog(jx.M{
		"timestamp":              jx.NowISO(),
		"action":                 "set_cost_center_ai_credit_pool",
		"enterprise":             slug,
		"cost_center_id":         ccID,
		"cost_center_name":       jx.GetOr(target, "name", ""),
		"ai_credit_pool_enabled": enabled,
		"api_result":             apiResult,
	})
	return jx.M{
		"status":                 "ok",
		"enterprise":             slug,
		"cost_center":            jx.M{"id": ccID, "name": jx.GetOr(target, "name", "")},
		"ai_credit_pool_enabled": enabled,
		"ai_credit_pool_state":   poolState,
		"api_result":             apiResult,
	}
}

// dataPyRepr formats a JSON scalar like Python's str() (floats keep ".0").
func dataPyRepr(v any) string {
	if f, ok := v.(float64); ok {
		s := strconv.FormatFloat(f, 'f', -1, 64)
		if !strings.ContainsAny(s, ".eE") {
			s += ".0"
		}
		return s
	}
	return jx.Str(v)
}

func dataCCReport(c *Ctx) any {
	enterprise := c.Query("enterprise", "")
	l := newDataLoader()
	list := dataLoadEnterpriseList(l)
	slugs := []string{}
	for _, e := range list {
		slugs = append(slugs, jx.Str(e["slug"]))
	}
	slug := ""
	if dataContains(slugs, enterprise) {
		slug = enterprise
	} else if len(slugs) > 0 {
		slug = slugs[0]
	}
	if slug == "" {
		return jx.M{"error": "No enterprise data found. Run Sync Data first."}
	}
	ccData := l.latestMap("cost_centers", slug)
	if !jx.Truthy(ccData) {
		return jx.M{"error": fmt.Sprintf("No cost center data for enterprise '%s'. Run Sync Data first.", slug)}
	}
	costCenters := jx.GetMaps(ccData, "cost_centers")
	enterpriseName := jx.Str(jx.GetOr(ccData, "enterprise_name", slug))
	// The report generator may annotate cost centers; hand it private copies.
	copies := make([]jx.M, len(costCenters))
	for i, cc := range costCenters {
		copies[i] = jx.DeepCopy(cc).(jx.M)
	}
	zipBytes, err := GenerateReportZip(slug, enterpriseName, copies,
		LoadAllCSVRecords(CSVTypeAI), LoadAllCSVRecords(CSVTypeUsage), APIs.WebBaseForEnterprise(slug))
	if err != nil {
		panic(err)
	}
	filename := fmt.Sprintf("cc-report-%s.zip", slug)
	c.W.Header().Set("Content-Type", "application/zip")
	c.W.Header().Set("Content-Disposition", fmt.Sprintf(`attachment; filename="%s"`, filename))
	c.W.WriteHeader(200)
	_, _ = c.W.Write(zipBytes)
	return nil
}

func dataCCDashboard(c *Ctx) any {
	enterprise := c.Query("enterprise", "")
	ccParam := c.Query("cost_centers", "")
	state := c.Query("state", "active")
	search := c.Query("search", "")
	l := newDataLoader()
	list := dataLoadEnterpriseList(l)
	if len(list) == 0 {
		return jx.M{
			"enterprises": jx.L{}, "selected_enterprise": nil, "cost_centers": jx.L{},
			"total_cost_centers": 0, "total_unique_members": 0, "user_map": jx.L{}, "no_data": true,
		}
	}
	slugs := []string{}
	for _, e := range list {
		slugs = append(slugs, jx.Str(e["slug"]))
	}
	slug := slugs[0]
	if dataContains(slugs, enterprise) {
		slug = enterprise
	}
	ccData := l.latestMap("cost_centers", slug)
	if !jx.Truthy(ccData) {
		return jx.M{
			"enterprises": list, "selected_enterprise": slug, "cost_centers": jx.L{},
			"total_cost_centers": 0, "total_unique_members": 0, "user_map": jx.L{}, "no_data": true,
		}
	}
	all := jx.GetMaps(ccData, "cost_centers")
	if state != "all" {
		kept := []jx.M{}
		for _, cc := range all {
			if dataStateIs(cc, state) {
				kept = append(kept, cc)
			}
		}
		all = kept
	}
	if filter := dataSplitCSV(ccParam); len(filter) > 0 {
		kept := []jx.M{}
		for _, cc := range all {
			if name, ok := cc["name"].(string); ok && dataContains(filter, name) {
				kept = append(kept, cc)
			}
		}
		all = kept
	}
	if q := strings.ToLower(strings.TrimSpace(search)); q != "" {
		kept := []jx.M{}
		for _, cc := range all {
			matched := jx.L{}
			for _, m := range jx.GetMaps(cc, "members") {
				if strings.Contains(strings.ToLower(dataGetStr(m, "login", "")), q) {
					matched = append(matched, m)
				}
			}
			if len(matched) > 0 {
				kept = append(kept, jx.Merge(cc, jx.M{"members": matched, "member_count": len(matched)}))
			}
		}
		all = kept
	}
	userMap := newDataOM[jx.M]()
	for _, cc := range all {
		for _, member := range jx.GetMaps(cc, "members") {
			login := jx.Str(member["login"])
			entry := userMap.at(login, func() jx.M {
				return jx.M{
					"login":        member["login"],
					"avatar_url":   jx.GetOr(member, "avatar_url", ""),
					"html_url":     jx.GetOr(member, "html_url", ""),
					"cost_centers": jx.L{},
				}
			})
			entry["cost_centers"] = append(entry["cost_centers"].(jx.L), jx.M{
				"name":        cc["name"],
				"id":          jx.GetOr(cc, "id", ""),
				"source_type": jx.GetOr(member, "source_type", ""),
				"source_name": jx.GetOr(member, "source_name", ""),
			})
		}
	}
	users := []jx.M{}
	for _, k := range userMap.keys {
		users = append(users, userMap.m[k])
	}
	sort.SliceStable(users, func(i, j int) bool {
		return strings.ToLower(jx.Str(users[i]["login"])) < strings.ToLower(jx.Str(users[j]["login"]))
	})
	return jx.M{
		"enterprises":          list,
		"selected_enterprise":  slug,
		"enterprise_name":      jx.GetOr(ccData, "enterprise_name", slug),
		"cost_centers":         all,
		"total_cost_centers":   len(all),
		"total_unique_members": len(users),
		"user_map":             users,
		"no_data":              false,
	}
}
