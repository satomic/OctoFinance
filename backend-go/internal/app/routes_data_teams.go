package app

import (
	"sort"
	"strings"

	"github.com/satomic/octofinance/backend-go/internal/jx"
)

// Enterprise teams dashboard and budgets dashboard (Python routers/data.py).

type dataSeatSummary struct {
	login, avatarURL, htmlURL any
	orgs, teams, planTypes    jx.L
	lastActivityAt            string
	lastActivityEditor        string
	seatCount                 int
}

func dataAggregateSeatsByLogin(l *dataLoader, orgLogins []string) *dataOM[*dataSeatSummary] {
	out := newDataOM[*dataSeatSummary]()
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
			entry := out.at(strings.ToLower(login), func() *dataSeatSummary {
				html := jx.Get(assignee, "html_url")
				if !jx.Truthy(html) {
					html = APIs.WebBaseForOrg(org) + "/" + login
				}
				return &dataSeatSummary{
					login: login, avatarURL: jx.GetOr(assignee, "avatar_url", ""), htmlURL: html,
					orgs: jx.L{}, teams: jx.L{}, planTypes: jx.L{},
				}
			})
			if !dataStrListContains(entry.orgs, org) {
				entry.orgs = append(entry.orgs, org)
			}
			team := jx.Map(seat["assigning_team"])
			label := jx.OrStr(team, "name", "")
			if label == "" {
				label = jx.OrStr(team, "slug", "")
			}
			if label != "" {
				scope := "organization"
				if t, ok := team["type"].(string); ok && t == "enterprise" {
					scope = "enterprise"
				}
				dup := false
				for _, e := range entry.teams {
					em := e.(jx.M)
					if em["name"] == label && em["scope"] == scope {
						dup = true
						break
					}
				}
				if !dup {
					entry.teams = append(entry.teams, jx.M{"name": label, "scope": scope})
				}
			}
			if pt := jx.OrStr(seat, "plan_type", ""); pt != "" && !dataStrListContains(entry.planTypes, pt) {
				entry.planTypes = append(entry.planTypes, pt)
			}
			if last := jx.OrStr(seat, "last_activity_at", ""); last != "" && last > entry.lastActivityAt {
				entry.lastActivityAt = last
				entry.lastActivityEditor = jx.OrStr(seat, "last_activity_editor", "")
			}
			entry.seatCount++
		}
	}
	return out
}

type dataUsageSummary struct {
	interactions, codeGenerations, codeAcceptances, locAdded int
	activeDays                                               jx.StrSet
	lastActiveDay                                            string
}

func dataAggregateUsageUsersByLogin(l *dataLoader, orgLogins []string) map[string]*dataUsageSummary {
	out := map[string]*dataUsageSummary{}
	for _, org := range orgLogins {
		report := l.latestMap("usage_users", org)
		if report == nil {
			continue
		}
		for _, rec := range jx.GetMaps(report, "records") {
			login := jx.OrStr(rec, "user_login", "")
			if login == "" {
				continue
			}
			key := strings.ToLower(login)
			entry, ok := out[key]
			if !ok {
				entry = &dataUsageSummary{activeDays: jx.StrSet{}}
				out[key] = entry
			}
			interactions := jx.GetInt(rec, "user_initiated_interaction_count")
			entry.interactions += interactions
			entry.codeGenerations += jx.GetInt(rec, "code_generation_activity_count")
			entry.codeAcceptances += jx.GetInt(rec, "code_acceptance_activity_count")
			entry.locAdded += jx.GetInt(rec, "loc_added_sum")
			day := jx.OrStr(rec, "day", "")
			if day != "" && interactions > 0 {
				entry.activeDays.Add(day)
				if day > entry.lastActiveDay {
					entry.lastActiveDay = day
				}
			}
		}
	}
	return out
}

type dataAISpend struct {
	requests, gross, net float64
	costCenters          jx.L
}

func dataSumAIRecords(records []CSVRecord, orgSet jx.StrSet) map[string]*dataAISpend {
	out := map[string]*dataAISpend{}
	for _, r := range records {
		username := dataRec(r, "username", "")
		if username == "" {
			continue
		}
		org := strings.ToLower(r["organization"])
		if org != "" && len(orgSet) > 0 && !orgSet.Has(org) {
			continue
		}
		key := strings.ToLower(username)
		entry, ok := out[key]
		if !ok {
			entry = &dataAISpend{costCenters: jx.L{}}
			out[key] = entry
		}
		// float(x or 0) raising part-way leaves earlier increments applied.
		func() {
			for _, f := range []struct {
				key string
				dst *float64
			}{{"quantity", &entry.requests}, {"gross_amount", &entry.gross}, {"net_amount", &entry.net}} {
				raw := r[f.key]
				if raw == "" {
					continue
				}
				v, ok := jx.FloatOK(raw)
				if !ok {
					return
				}
				*f.dst += v
			}
		}()
		if cc := r["cost_center_name"]; cc != "" && !dataStrListContains(entry.costCenters, cc) {
			entry.costCenters = append(entry.costCenters, cc)
		}
	}
	return out
}

func dataAggregateAICostByLogin(l *dataLoader, orgLogins []string, records []CSVRecord) map[string]*dataAISpend {
	pseudo := jx.StrSet{}
	for _, e := range dataLoadEnterpriseList(l) {
		pseudo.Add(strings.ToLower(EnterprisePseudoOrg(dataGetStr(e, "slug", ""))))
	}
	orgSet := jx.StrSet{}
	for _, o := range orgLogins {
		if lo := strings.ToLower(o); !pseudo.Has(lo) {
			orgSet.Add(lo)
		}
	}
	result := dataSumAIRecords(records, orgSet)
	if len(result) == 0 && len(orgSet) > 0 {
		result = dataSumAIRecords(records, jx.StrSet{})
	}
	return result
}

func dataEnterpriseTeamsDashboard(c *Ctx) any {
	enterprise := c.Query("enterprise", "")
	teamsParam := c.Query("teams", "")
	search := c.Query("search", "")
	l := newDataLoader()
	slug, selected, list := dataResolveEnterprise(l, enterprise)
	empty := jx.M{
		"enterprises":           list,
		"selected_enterprise":   dataOrNone(slug),
		"enterprise_name":       jx.GetOr(selected, "name", slug),
		"teams":                 jx.L{},
		"all_teams":             jx.L{},
		"orgs":                  jx.L{},
		"totals":                jx.M{},
		"unassigned_seat_users": jx.L{},
		"ai_usage_available":    false,
		"no_data":               true,
	}
	if slug == "" {
		return empty
	}
	teamData := l.latestMap("enterprise_teams", slug)
	if teamData == nil {
		return empty
	}
	allTeams := jx.GetMaps(teamData, "teams")
	orgLogins := dataEnterpriseOrgLogins(c.R.Context(), l, slug, selected)
	seatMap := dataAggregateSeatsByLogin(l, orgLogins)
	usageMap := dataAggregateUsageUsersByLogin(l, orgLogins)
	aiRecords := LoadAllCSVRecords(CSVTypeAI)
	aiMap := dataAggregateAICostByLogin(l, orgLogins, aiRecords)
	pricePerSeat, ok := CopilotPricing["business"]
	if !ok {
		pricePerSeat = 19.0
	}
	webBase := APIs.WebBaseForEnterprise(slug)

	buildMember := func(login string, avatarURL, htmlURL any) jx.M {
		key := strings.ToLower(login)
		seat := seatMap.m[key]
		m := jx.M{
			"login":                login,
			"has_seat":             seat != nil,
			"orgs":                 jx.L{},
			"plan_types":           jx.L{},
			"assigning_teams":      jx.L{},
			"last_activity_at":     "",
			"last_activity_editor": "",
			"interactions":         0,
			"code_acceptances":     0,
			"loc_added":            0,
			"active_days":          0,
			"last_active_day":      "",
			"ai_requests":          0.0,
			"ai_net_amount":        0.0,
			"cost_centers":         jx.L{},
		}
		if jx.Truthy(avatarURL) {
			m["avatar_url"] = avatarURL
		} else if seat != nil {
			m["avatar_url"] = seat.avatarURL
		} else {
			m["avatar_url"] = ""
		}
		if jx.Truthy(htmlURL) {
			m["html_url"] = htmlURL
		} else {
			m["html_url"] = webBase + "/" + login
		}
		if seat != nil {
			m["orgs"] = seat.orgs
			m["plan_types"] = seat.planTypes
			m["assigning_teams"] = seat.teams
			m["last_activity_at"] = seat.lastActivityAt
			m["last_activity_editor"] = seat.lastActivityEditor
		}
		if u := usageMap[key]; u != nil {
			m["interactions"] = u.interactions
			m["code_acceptances"] = u.codeAcceptances
			m["loc_added"] = u.locAdded
			m["active_days"] = len(u.activeDays)
			m["last_active_day"] = u.lastActiveDay
		}
		if a := aiMap[key]; a != nil {
			m["ai_requests"] = jx.Round(a.requests, 2)
			m["ai_net_amount"] = jx.Round(a.net, 4)
			m["cost_centers"] = a.costCenters
		}
		return m
	}

	teamFilter := jx.StrSet{}
	for _, s := range dataSplitCSV(teamsParam) {
		teamFilter.Add(s)
	}
	q := strings.ToLower(strings.TrimSpace(search))

	type teamRow struct {
		m           jx.M
		memberCount int
		name        string
	}
	rows := []teamRow{}
	for _, team := range allTeams {
		if len(teamFilter) > 0 {
			s, isStr := team["slug"].(string)
			if !isStr || !teamFilter.Has(s) {
				continue
			}
		}
		members := []jx.M{}
		for _, mem := range jx.GetMaps(team, "members") {
			if jx.Truthy(mem["login"]) {
				members = append(members, buildMember(dataGetStr(mem, "login", ""), jx.GetOr(mem, "avatar_url", ""), jx.GetOr(mem, "html_url", "")))
			}
		}
		if q != "" {
			kept := []jx.M{}
			for _, m := range members {
				if strings.Contains(strings.ToLower(jx.Str(m["login"])), q) {
					kept = append(kept, m)
				}
			}
			members = kept
			if len(members) == 0 {
				continue
			}
		}
		seatCount, active := 0, 0
		var interactions, locAdded int
		var aiReq, aiNet float64
		for _, m := range members {
			if m["has_seat"].(bool) {
				seatCount++
			}
			if jx.Int(m["interactions"]) > 0 {
				active++
			}
			interactions += jx.Int(m["interactions"])
			locAdded += jx.Int(m["loc_added"])
			aiReq += jx.Float(m["ai_requests"])
			aiNet += jx.Float(m["ai_net_amount"])
		}
		sorted := append([]jx.M{}, members...)
		sort.SliceStable(sorted, func(i, j int) bool {
			return strings.ToLower(jx.Str(sorted[i]["login"])) < strings.ToLower(jx.Str(sorted[j]["login"]))
		})
		name := jx.GetOr(team, "name", "")
		rows = append(rows, teamRow{m: jx.M{
			"id":                          team["id"],
			"slug":                        jx.GetOr(team, "slug", ""),
			"name":                        name,
			"description":                 jx.GetOr(team, "description", ""),
			"html_url":                    jx.GetOr(team, "html_url", ""),
			"group_name":                  jx.OrStr(team, "group_name", ""),
			"organization_selection_type": jx.GetOr(team, "organization_selection_type", ""),
			"organizations":               jx.GetOr(team, "organizations", jx.L{}),
			"members":                     sorted,
			"member_count":                len(members),
			"seat_count":                  seatCount,
			"no_seat_count":               len(members) - seatCount,
			"active_member_count":         active,
			"interactions":                interactions,
			"loc_added":                   locAdded,
			"ai_requests":                 jx.Round(aiReq, 2),
			"ai_net_amount":               jx.Round(aiNet, 4),
			"seat_cost":                   jx.Round(float64(seatCount)*pricePerSeat, 2),
		}, memberCount: len(members), name: strings.ToLower(jx.Str(name))})
	}
	sort.SliceStable(rows, func(i, j int) bool {
		if rows[i].memberCount != rows[j].memberCount {
			return rows[i].memberCount > rows[j].memberCount
		}
		return rows[i].name < rows[j].name
	})
	resultTeams := jx.L{}
	var totalAINet, totalSeatCost float64
	for _, r := range rows {
		resultTeams = append(resultTeams, r.m)
		totalAINet += jx.Float(r.m["ai_net_amount"])
		totalSeatCost += jx.Float(r.m["seat_cost"])
	}

	assigned := jx.StrSet{}
	for _, team := range allTeams {
		for _, m := range jx.GetMaps(team, "members") {
			if jx.Truthy(m["login"]) {
				assigned.Add(strings.ToLower(dataGetStr(m, "login", "")))
			}
		}
	}
	unassigned := []jx.M{}
	for _, k := range seatMap.keys {
		if !assigned.Has(k) {
			s := seatMap.m[k]
			unassigned = append(unassigned, buildMember(jx.Str(s.login), s.avatarURL, s.htmlURL))
		}
	}
	if q != "" {
		kept := []jx.M{}
		for _, u := range unassigned {
			if strings.Contains(strings.ToLower(jx.Str(u["login"])), q) {
				kept = append(kept, u)
			}
		}
		unassigned = kept
	}
	sort.SliceStable(unassigned, func(i, j int) bool {
		return strings.ToLower(jx.Str(unassigned[i]["login"])) < strings.ToLower(jx.Str(unassigned[j]["login"]))
	})
	withSeat, withoutSeat := 0, 0
	for k := range assigned {
		if seatMap.has(k) {
			withSeat++
		} else {
			withoutSeat++
		}
	}
	coverage := 0.0
	if len(seatMap.keys) > 0 {
		coverage = jx.Round(float64(withSeat)/float64(len(seatMap.keys))*100, 1)
	}
	allTeamsOut := jx.L{}
	for _, t := range allTeams {
		allTeamsOut = append(allTeamsOut, jx.M{"slug": jx.GetOr(t, "slug", ""), "name": jx.GetOr(t, "name", "")})
	}
	return jx.M{
		"enterprises":         list,
		"selected_enterprise": slug,
		"enterprise_name":     jx.GetOr(teamData, "enterprise_name", slug),
		"teams":               resultTeams,
		"all_teams":           allTeamsOut,
		"orgs":                orgLogins,
		"totals": jx.M{
			"total_teams":           len(allTeams),
			"shown_teams":           len(resultTeams),
			"total_unique_members":  len(assigned),
			"members_with_seat":     withSeat,
			"members_without_seat":  withoutSeat,
			"total_seat_users":      len(seatMap.keys),
			"unassigned_seat_users": len(unassigned),
			"coverage_pct":          coverage,
			"ai_net_amount":         jx.Round(totalAINet, 4),
			"seat_cost":             jx.Round(totalSeatCost, 2),
			"price_per_seat":        pricePerSeat,
		},
		"unassigned_seat_users": unassigned,
		"ai_usage_available":    len(aiRecords) > 0,
		"no_data":               len(allTeams) == 0,
	}
}

// ---------------------------------------------------------------------------
// Budgets dashboard
// ---------------------------------------------------------------------------

func dataBudgetsDashboard(c *Ctx) any {
	enterprise := c.Query("enterprise", "")
	scope := c.Query("scope", "all")
	search := c.Query("search", "")
	live := c.QueryBool("live", false)
	period := c.Query("period", "all")
	l := newDataLoader()
	list := dataLoadEnterpriseList(l)
	empty := jx.M{
		"enterprises": list, "selected_enterprise": nil, "enterprise_name": "", "budgets": jx.L{},
		"total_budgets": 0, "total_amount": 0, "hard_limit_count": 0, "alerting_count": 0,
		"scope_breakdown": jx.L{}, "scopes": jx.L{}, "total_consumed": 0, "total_remaining": 0,
		"tracked_budgets": 0, "live": false, "no_data": true,
	}
	if len(list) == 0 {
		return empty
	}
	slugs := []string{}
	for _, e := range list {
		slugs = append(slugs, jx.Str(e["slug"]))
	}
	slug := slugs[0]
	if dataContains(slugs, enterprise) {
		slug = enterprise
	}
	budgetsData := l.latestMap("budgets", slug)
	raw := jx.Maps(jx.GetOr(budgetsData, "budgets", jx.L{}))
	liveFetched := false
	if live {
		if fresh := FetchBudgets(c.R.Context(), "enterprise", slug, ""); len(fresh) > 0 {
			raw = fresh
			liveFetched = true
		}
	}
	if len(raw) == 0 {
		return jx.Merge(empty, jx.M{"selected_enterprise": slug})
	}

	type budget struct {
		m                   jx.M
		scope, entity, typ  string
		skus                []string
		amount              float64
		consumed, remaining *float64
		prevent, alert      bool
	}
	normalize := func(b jx.M) budget {
		skus := jx.GetList(b, "budget_product_skus")
		if !jx.Truthy(skus) {
			skus = jx.L{}
			if single := b["budget_product_sku"]; jx.Truthy(single) {
				skus = jx.L{single}
			}
		}
		skuOut := []any{}
		skuStrs := []string{}
		for _, s := range skus {
			if jx.Truthy(s) {
				skuOut = append(skuOut, s)
				skuStrs = append(skuStrs, jx.Str(s))
			}
		}
		alerting := jx.Map(b["budget_alerting"])
		amount := jx.Float(jx.GetOr(b, "budget_amount", 0))
		out := budget{
			scope:   jx.Str(jx.GetOr(b, "budget_scope", "")),
			entity:  jx.OrStr(b, "budget_entity_name", ""),
			typ:     jx.Str(jx.GetOr(b, "budget_type", "")),
			skus:    skuStrs,
			amount:  amount,
			prevent: jx.Truthy(jx.GetOr(b, "prevent_further_usage", false)),
			alert:   jx.Truthy(jx.GetOr(alerting, "will_alert", false)),
		}
		var consumedOut, remainingOut, pctOut any
		if raw, ok := b["consumed_amount"]; ok && raw != nil {
			consumed := jx.Float(raw)
			c := jx.Round(consumed, 4)
			r := jx.Round(amount-consumed, 4)
			out.consumed, out.remaining = &c, &r
			consumedOut, remainingOut = c, r
			if amount > 0 {
				pctOut = jx.Round(consumed/amount*100, 1)
			}
		}
		recipients := jx.GetOr(alerting, "alert_recipients", jx.L{})
		if !jx.Truthy(recipients) {
			recipients = jx.L{}
		}
		out.m = jx.M{
			"id":                    jx.GetOr(b, "id", ""),
			"budget_type":           jx.GetOr(b, "budget_type", ""),
			"scope":                 jx.GetOr(b, "budget_scope", ""),
			"entity_name":           out.entity,
			"skus":                  skuOut,
			"amount":                amount,
			"consumed_amount":       consumedOut,
			"remaining_amount":      remainingOut,
			"usage_pct":             pctOut,
			"prevent_further_usage": out.prevent,
			"will_alert":            out.alert,
			"alert_recipients":      recipients,
		}
		return out
	}
	budgets := []budget{}
	for _, b := range raw {
		budgets = append(budgets, normalize(b))
	}
	scopeSet := jx.StrSet{}
	for _, b := range budgets {
		if b.scope != "" {
			scopeSet.Add(b.scope)
		}
	}
	if scope != "" && scope != "all" {
		kept := []budget{}
		for _, b := range budgets {
			if b.scope == scope {
				kept = append(kept, b)
			}
		}
		budgets = kept
	}
	if q := strings.ToLower(strings.TrimSpace(search)); q != "" {
		kept := []budget{}
		for _, b := range budgets {
			hay := strings.ToLower(strings.Join([]string{b.entity, b.scope, b.typ, strings.Join(b.skus, " ")}, " "))
			if strings.Contains(hay, q) {
				kept = append(kept, b)
			}
		}
		budgets = kept
	}
	type scopeAgg struct {
		count  int
		amount float64
	}
	scopeMap := newDataOM[*scopeAgg]()
	var totalAmount, totalConsumed, totalRemaining float64
	hard, alerting, tracked := 0, 0, 0
	out := jx.L{}
	for _, b := range budgets {
		key := b.scope
		if key == "" {
			key = "unknown"
		}
		sa := scopeMap.at(key, func() *scopeAgg { return &scopeAgg{} })
		sa.count++
		sa.amount += b.amount
		totalAmount += b.amount
		if b.prevent {
			hard++
		}
		if b.alert {
			alerting++
		}
		if b.consumed != nil {
			totalConsumed += *b.consumed
			if b.amount != 0 {
				tracked++
				totalRemaining += *b.remaining
			}
		}
		out = append(out, b.m)
	}
	breakdown := jx.L{}
	for _, k := range scopeMap.sortedKeysBy(func(a, b *scopeAgg) bool { return a.amount > b.amount }) {
		breakdown = append(breakdown, jx.M{"scope": k, "count": scopeMap.m[k].count, "amount": jx.Round(scopeMap.m[k].amount, 2)})
	}
	monthStart, monthEnd := CurrentMonthRange()
	return jx.M{
		"enterprises":         list,
		"selected_enterprise": slug,
		"enterprise_name":     jx.GetOr(budgetsData, "enterprise_name", slug),
		"live":                liveFetched,
		"period":              period,
		"current_month":       jx.M{"start": monthStart, "end": monthEnd},
		"total_consumed":      jx.Round(totalConsumed, 4),
		"total_remaining":     jx.Round(totalRemaining, 4),
		"tracked_budgets":     tracked,
		"budgets":             out,
		"total_budgets":       len(budgets),
		"total_amount":        jx.Round(totalAmount, 2),
		"hard_limit_count":    hard,
		"alerting_count":      alerting,
		"scope_breakdown":     breakdown,
		"scopes":              scopeSet.Sorted(),
		"no_data":             false,
	}
}
