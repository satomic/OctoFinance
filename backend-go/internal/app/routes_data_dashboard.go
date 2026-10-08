package app

import (
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/satomic/octofinance/backend-go/internal/jx"
)

// GET /api/data/dashboard — the Usage Metrics dashboard (Python get_dashboard).

// dataCounts accumulates usage counters (interactions, code_gen, ...).
type dataCounts struct {
	interactions, codeGen, codeAccept, locSuggested, locAccepted float64
}

func newDataCounts() *dataCounts { return &dataCounts{} }

func (c *dataCounts) add(src jx.M, withInteractions bool) {
	if withInteractions {
		c.interactions += jx.GetFloat(src, "user_initiated_interaction_count")
	}
	c.codeGen += jx.GetFloat(src, "code_generation_activity_count")
	c.codeAccept += jx.GetFloat(src, "code_acceptance_activity_count")
	c.locSuggested += jx.GetFloat(src, "loc_suggested_to_add_sum") + jx.GetFloat(src, "loc_suggested_to_delete_sum")
	c.locAccepted += jx.GetFloat(src, "loc_added_sum") + jx.GetFloat(src, "loc_deleted_sum")
}

func (c *dataCounts) fill(m jx.M, withInteractions bool) jx.M {
	if withInteractions {
		m["interactions"] = c.interactions
	}
	m["code_gen"] = c.codeGen
	m["code_accept"] = c.codeAccept
	m["loc_suggested"] = c.locSuggested
	m["loc_accepted"] = c.locAccepted
	return m
}

// dataBreakdown renders a counter map sorted by -interactions (or -code_gen).
func dataBreakdown(om *dataOM[*dataCounts], label string, withInteractions bool) jx.L {
	var keys []string
	if withInteractions {
		keys = om.sortedKeysBy(func(a, b *dataCounts) bool { return a.interactions > b.interactions })
	} else {
		keys = om.sortedKeysBy(func(a, b *dataCounts) bool { return a.codeGen > b.codeGen })
	}
	out := jx.L{}
	for _, k := range keys {
		out = append(out, om.m[k].fill(jx.M{label: k}, withInteractions))
	}
	return out
}

type dataDay struct {
	day                                  string
	dau, wau, mau, chatUsers, agentUsers float64
	counts                               dataCounts
}

func (d *dataDay) out() jx.M {
	return d.counts.fill(jx.M{
		"day": d.day, "dau": d.dau, "wau": d.wau, "mau": d.mau,
		"chat_users": d.chatUsers, "agent_users": d.agentUsers,
	}, true)
}

type dataUsageAgg struct {
	daily                         *dataOM[*dataDay]
	feature, model, ide, language *dataOM[*dataCounts]
	dateStart, dateEnd            string
}

func newDataUsageAgg() *dataUsageAgg {
	return &dataUsageAgg{
		daily:    newDataOM[*dataDay](),
		feature:  newDataOM[*dataCounts](),
		model:    newDataOM[*dataCounts](),
		ide:      newDataOM[*dataCounts](),
		language: newDataOM[*dataCounts](),
	}
}

func (a *dataUsageAgg) noteDay(day string) {
	if a.dateStart == "" || day < a.dateStart {
		a.dateStart = day
	}
	if a.dateEnd == "" || day > a.dateEnd {
		a.dateEnd = day
	}
}

func (a *dataUsageAgg) dayEntry(day string) *dataDay {
	return a.daily.at(day, func() *dataDay { return &dataDay{day: day} })
}

func (a *dataUsageAgg) addBreakdowns(src jx.M) {
	for _, fb := range jx.GetMaps(src, "totals_by_feature") {
		a.feature.at(dataGetStr(fb, "feature", "unknown"), newDataCounts).add(fb, true)
	}
	for _, mb := range jx.GetMaps(src, "totals_by_model_feature") {
		a.model.at(dataGetStr(mb, "model", "unknown"), newDataCounts).add(mb, true)
	}
	for _, ib := range jx.GetMaps(src, "totals_by_ide") {
		a.ide.at(dataGetStr(ib, "ide", "unknown"), newDataCounts).add(ib, true)
	}
	for _, lb := range jx.GetMaps(src, "totals_by_language_feature") {
		a.language.at(dataGetStr(lb, "language", "unknown"), newDataCounts).add(lb, false)
	}
}

func (a *dataUsageAgg) dailyTrend() jx.L {
	days := append([]string{}, a.daily.keys...)
	sort.Strings(days)
	out := jx.L{}
	for _, d := range days {
		out = append(out, a.daily.m[d].out())
	}
	return out
}

// dataAggregateUsageFromUsers rebuilds the usage aggregates from user-level records.
func dataAggregateUsageFromUsers(l *dataLoader, selected []string, filter *dataMemberFilter, from, to string) *dataUsageAgg {
	agg := newDataUsageAgg()
	dayUsers := map[string]jx.StrSet{}
	for _, org := range selected {
		report := l.latestMap("usage_users", org)
		if report == nil {
			continue
		}
		for _, rec := range jx.GetMaps(report, "records") {
			login := strings.ToLower(jx.Str(rec["user_login"]))
			if login == "" || !filter.has(login) {
				continue
			}
			day := dataGetStr(rec, "day", "")
			if !dataInRange(day, from, to) {
				continue
			}
			agg.noteDay(day)
			interactions := jx.GetFloat(rec, "user_initiated_interaction_count")
			dm := agg.dayEntry(day)
			dm.counts.add(rec, true)
			if interactions > 0 {
				s, ok := dayUsers[day]
				if !ok {
					s = jx.StrSet{}
					dayUsers[day] = s
				}
				s.Add(login)
			}
			if jx.Truthy(rec["used_chat"]) {
				dm.chatUsers++
			}
			if jx.Truthy(rec["used_agent"]) {
				dm.agentUsers++
			}
			agg.addBreakdowns(rec)
		}
	}
	days := append([]string{}, agg.daily.keys...)
	sort.Strings(days)
	union := func(window []string) int {
		u := jx.StrSet{}
		for _, d := range window {
			for k := range dayUsers[d] {
				u.Add(k)
			}
		}
		return len(u)
	}
	for i, d := range days {
		w7 := days[max(0, i-6) : i+1]
		w28 := days[max(0, i-27) : i+1]
		dm := agg.daily.m[d]
		dm.dau = float64(len(dayUsers[d]))
		dm.wau = float64(union(w7))
		dm.mau = float64(union(w28))
	}
	return agg
}

type dataUserAgg struct {
	counts              dataCounts
	daysActive          int
	usedAgent, usedChat bool
}

func dataDashboard(c *Ctx) any {
	orgsParam := c.Query("orgs", "")
	enterpriseTeam := c.Query("enterprise_team", "")
	user := c.Query("user", "")
	dateFrom := c.Query("date_from", "")
	dateTo := c.Query("date_to", "")

	l := newDataLoader()
	allOrgs := APIs.AllOrgs()
	usageOrgNames := jx.StrSet{}
	allOrgNames := []string{}
	for _, o := range allOrgs {
		usageOrgNames.Add(jx.Str(o["login"]))
		allOrgNames = append(allOrgNames, jx.Str(o["login"]))
	}
	for _, e := range APIs.EnterprisePseudoOrgs() {
		usageOrgNames.Add(EnterprisePseudoOrg(jx.Str(e["slug"])))
	}
	for _, e := range APIs.AllEnterprises() {
		allOrgNames = append(allOrgNames, EnterprisePseudoOrg(jx.Str(e["slug"])))
	}
	selectedSeatOrgs := allOrgNames
	if strings.TrimSpace(orgsParam) != "" {
		selectedSeatOrgs = dataSplitCSV(orgsParam)
	}
	selected := []string{}
	for _, s := range selectedSeatOrgs {
		if usageOrgNames.Has(s) {
			selected = append(selected, s)
		}
	}
	teamFilter := dataTeamMemberLogins(l, enterpriseTeam)
	selectedUser := strings.TrimSpace(user)
	memberFilter := dataWithUserFilter(teamFilter, selectedUser)

	// --- KPI from billing ---
	var totalSeats, activeSeats, monthlyCost, monthlyWaste float64
	for _, org := range selectedSeatOrgs {
		billing := l.latestMap("billing", org)
		if !jx.Truthy(billing) {
			continue
		}
		price := jx.Float(jx.GetOr(billing, "_detected_price_per_seat", 19.0))
		sb := jx.Map(jx.GetOr(billing, "seat_breakdown", jx.M{}))
		s := jx.Float(jx.GetOr(sb, "total", 0))
		a := jx.Float(jx.GetOr(sb, "active_this_cycle", 0))
		totalSeats += s
		activeSeats += a
		monthlyCost += s * price
		monthlyWaste += (s - a) * price
	}
	if memberFilter != nil {
		cutoff := jx.ISO(time.Now().Add(-30 * 24 * time.Hour))
		totalSeats, activeSeats, monthlyCost, monthlyWaste = 0, 0, 0, 0
		for _, org := range selectedSeatOrgs {
			billing := l.latestMap("billing", org)
			price := jx.Float(jx.GetOr(billing, "_detected_price_per_seat", 19.0))
			seatsData := l.latestMap("seats", org)
			if !jx.Truthy(seatsData) {
				continue
			}
			for _, seat := range jx.GetMaps(seatsData, "seats") {
				login := strings.ToLower(jx.Str(jx.GetMap(seat, "assignee")["login"]))
				if !memberFilter.has(login) {
					continue
				}
				totalSeats++
				monthlyCost += price
				if jx.Str(seat["last_activity_at"]) >= cutoff {
					activeSeats++
				} else {
					monthlyWaste += price
				}
			}
		}
	}
	var util any = 0
	if totalSeats > 0 {
		util = jx.Round(activeSeats/totalSeats*100, 1)
	}
	kpi := jx.M{
		"total_seats":     totalSeats,
		"active_seats":    activeSeats,
		"inactive_seats":  totalSeats - activeSeats,
		"utilization_pct": util,
		"monthly_cost":    monthlyCost,
		"monthly_waste":   monthlyWaste,
	}

	// --- Seat info ---
	var pendingInv, pendingCancel, addedCycle float64
	plans := jx.M{}
	features := jx.M{}
	seatRows := jx.L{}
	for _, org := range selectedSeatOrgs {
		billing := l.latestMap("billing", org)
		if jx.Truthy(billing) {
			sb := jx.Map(jx.GetOr(billing, "seat_breakdown", jx.M{}))
			pendingInv += jx.Float(jx.GetOr(sb, "pending_invitation", 0))
			pendingCancel += jx.Float(jx.GetOr(sb, "pending_cancellation", 0))
			addedCycle += jx.Float(jx.GetOr(sb, "added_this_cycle", 0))
			pt := jx.Str(jx.GetOr(billing, "_detected_plan_type", jx.GetOr(billing, "plan_type", "unknown")))
			plans[pt] = jx.Float(plans[pt]) + 1
			for _, feat := range []string{"ide_chat", "cli", "platform_chat", "public_code_suggestions"} {
				if val := jx.GetOr(billing, feat, ""); jx.Truthy(val) {
					features[feat] = val
				}
			}
		}
		seatsData := l.latestMap("seats", org)
		if jx.Truthy(seatsData) {
			for _, s := range jx.GetMaps(seatsData, "seats") {
				assignee := jx.GetMap(s, "assignee")
				if memberFilter != nil && !memberFilter.has(strings.ToLower(jx.Str(assignee["login"]))) {
					continue
				}
				teamName := any("")
				if team := jx.Map(s["assigning_team"]); jx.Truthy(team) {
					teamName = jx.GetOr(team, "name", "")
				}
				seatRows = append(seatRows, jx.M{
					"user":                      jx.GetOr(assignee, "login", ""),
					"avatar":                    jx.GetOr(assignee, "avatar_url", ""),
					"org":                       org,
					"plan_type":                 jx.GetOr(s, "plan_type", ""),
					"created_at":                jx.GetOr(s, "created_at", ""),
					"last_activity_at":          s["last_activity_at"],
					"last_activity_editor":      s["last_activity_editor"],
					"pending_cancellation_date": s["pending_cancellation_date"],
					"team":                      teamName,
				})
			}
		}
	}
	seatInfo := jx.M{
		"breakdown": jx.M{"pending_invitation": pendingInv, "pending_cancellation": pendingCancel, "added_this_cycle": addedCycle},
		"plans":     plans,
		"features":  features,
		"seats":     seatRows,
	}

	// --- Aggregate usage data ---
	agg := newDataUsageAgg()
	if memberFilter == nil {
		for _, org := range selected {
			usage := l.latestMap("usage", org)
			if !jx.Truthy(usage) {
				continue
			}
			for _, rec := range jx.GetMaps(usage, "records") {
				for _, dt := range jx.GetMaps(rec, "day_totals") {
					day := dataGetStr(dt, "day", "")
					if !dataInRange(day, dateFrom, dateTo) {
						continue
					}
					agg.noteDay(day)
					dm := agg.dayEntry(day)
					dm.dau += jx.GetFloat(dt, "daily_active_users")
					dm.wau += jx.GetFloat(dt, "weekly_active_users")
					dm.mau += jx.GetFloat(dt, "monthly_active_users")
					dm.chatUsers += jx.GetFloat(dt, "monthly_active_chat_users")
					dm.agentUsers += jx.GetFloat(dt, "monthly_active_agent_users")
					dm.counts.add(dt, true)
					agg.addBreakdowns(dt)
				}
			}
		}
	} else {
		agg = dataAggregateUsageFromUsers(l, selected, memberFilter, dateFrom, dateTo)
	}
	dailyTrend := agg.dailyTrend()
	featureUsage := dataBreakdown(agg.feature, "feature", true)
	modelUsage := dataBreakdown(agg.model, "model", true)
	ideUsage := dataBreakdown(agg.ide, "ide", true)
	languageUsage := dataBreakdown(agg.language, "language", false)

	// --- AI credit detail ---
	type prDetail struct{ grossQty, discountQty, netQty, grossAmount, netAmount float64 }
	aiCreditPeriod := ""
	prMap := newDataOM[*prDetail]()
	if memberFilter == nil {
		for _, org := range selected {
			pr := l.latestMap("ai_credits", org)
			if !jx.Truthy(pr) {
				continue
			}
			tp := jx.Map(pr["timePeriod"])
			if !(jx.Truthy(tp["year"]) && jx.Truthy(tp["month"])) {
				continue
			}
			label := fmt.Sprintf("%s-%02d", jx.Str(tp["year"]), jx.Int(tp["month"]))
			if (dateFrom != "" && label < dataPrefix(dateFrom, 7)) || (dateTo != "" && label > dataPrefix(dateTo, 7)) {
				continue
			}
			aiCreditPeriod = label
			for _, item := range jx.GetMaps(pr, "usageItems") {
				p := prMap.at(dataGetStr(item, "model", "unknown"), func() *prDetail { return &prDetail{} })
				p.grossQty += jx.GetFloat(item, "grossQuantity")
				p.discountQty += jx.GetFloat(item, "discountQuantity")
				p.netQty += jx.GetFloat(item, "netQuantity")
				p.grossAmount += jx.GetFloat(item, "grossAmount")
				p.netAmount += jx.GetFloat(item, "netAmount")
			}
		}
	}
	aiCreditDetail := jx.L{}
	for _, k := range prMap.sortedKeysBy(func(a, b *prDetail) bool { return a.grossQty > b.grossQty }) {
		p := prMap.m[k]
		aiCreditDetail = append(aiCreditDetail, jx.M{
			"model": k, "gross_qty": p.grossQty, "discount_qty": p.discountQty, "net_qty": p.netQty,
			"gross_amount": p.grossAmount, "net_amount": p.netAmount,
		})
	}
	creditsByKey := map[string]float64{}
	for _, m := range prMap.keys {
		creditsByKey[dataModelKey(m)] += prMap.m[m].grossQty
	}
	for _, e := range modelUsage {
		entry := e.(jx.M)
		key := dataModelKey(jx.Str(entry["model"]))
		if v, ok := creditsByKey[key]; ok {
			entry["ai_credits"] = v
			delete(creditsByKey, key)
		} else {
			entry["ai_credits"] = 0
		}
	}
	for _, m := range prMap.keys {
		key := dataModelKey(m)
		qty, ok := creditsByKey[key]
		delete(creditsByKey, key)
		if ok && qty != 0 {
			modelUsage = append(modelUsage, jx.M{"model": m, "interactions": 0, "code_gen": 0, "code_accept": 0,
				"loc_suggested": 0, "loc_accepted": 0, "ai_credits": qty})
		}
	}

	// --- Top users ---
	userAgg := newDataOM[*dataUserAgg]()
	for _, org := range selected {
		uu := l.latestMap("usage_users", org)
		if !jx.Truthy(uu) {
			continue
		}
		for _, rec := range jx.GetMaps(uu, "records") {
			login := jx.Str(jx.GetOr(rec, "user_login", ""))
			if login == "" {
				continue
			}
			if !dataInRange(dataGetStr(rec, "day", ""), dateFrom, dateTo) {
				continue
			}
			if memberFilter != nil && !memberFilter.has(strings.ToLower(login)) {
				continue
			}
			u := userAgg.at(login, func() *dataUserAgg { return &dataUserAgg{} })
			u.counts.add(rec, true)
			u.daysActive++
			if jx.Truthy(rec["used_agent"]) {
				u.usedAgent = true
			}
			if jx.Truthy(rec["used_chat"]) {
				u.usedChat = true
			}
		}
	}
	topUsers := jx.L{}
	for i, k := range userAgg.sortedKeysBy(func(a, b *dataUserAgg) bool { return a.counts.interactions > b.counts.interactions }) {
		if i >= 30 {
			break
		}
		u := userAgg.m[k]
		topUsers = append(topUsers, u.counts.fill(jx.M{
			"user": k, "days_active": u.daysActive, "used_agent": u.usedAgent, "used_chat": u.usedChat,
		}, true))
	}

	// --- Metrics data (legacy metrics API) ---
	type langMetric struct{ suggestions, acceptances, linesSuggested, linesAccepted, engaged float64 }
	langMap := newDataOM[*langMetric]()
	var ideChats, ideCopy, ideInsert, dotcomChats, prSummaries float64
	if memberFilter == nil {
		for _, org := range selected {
			metrics := l.latest("metrics", org)
			if !jx.Truthy(metrics) {
				continue
			}
			entries := jx.List(metrics)
			if entries == nil {
				entries = jx.L{metrics}
			}
			for _, e := range entries {
				entry := jx.Map(e)
				if (dateFrom != "" || dateTo != "") && !dataInRange(dataGetStr(entry, "date", ""), dateFrom, dateTo) {
					continue
				}
				cc := jx.Map(jx.GetOr(entry, "copilot_ide_code_completions", jx.M{}))
				for _, editor := range jx.GetMaps(cc, "editors") {
					for _, model := range jx.GetMaps(editor, "models") {
						for _, lang := range jx.GetMaps(model, "languages") {
							lm := langMap.at(dataGetStr(lang, "name", "unknown"), func() *langMetric { return &langMetric{} })
							lm.suggestions += jx.GetFloat(lang, "total_code_suggestions")
							lm.acceptances += jx.GetFloat(lang, "total_code_acceptances")
							lm.linesSuggested += jx.GetFloat(lang, "total_code_lines_suggested")
							lm.linesAccepted += jx.GetFloat(lang, "total_code_lines_accepted")
							lm.engaged += jx.GetFloat(lang, "total_engaged_users")
						}
					}
				}
				ic := jx.Map(jx.GetOr(entry, "copilot_ide_chat", jx.M{}))
				for _, editor := range jx.GetMaps(ic, "editors") {
					for _, model := range jx.GetMaps(editor, "models") {
						ideChats += jx.GetFloat(model, "total_chats")
						ideCopy += jx.GetFloat(model, "total_chat_copy_events")
						ideInsert += jx.GetFloat(model, "total_chat_insertion_events")
					}
				}
				dc := jx.Map(jx.GetOr(entry, "copilot_dotcom_chat", jx.M{}))
				for _, model := range jx.GetMaps(dc, "models") {
					dotcomChats += jx.GetFloat(model, "total_chats")
				}
				dpr := jx.Map(jx.GetOr(entry, "copilot_dotcom_pull_requests", jx.M{}))
				for _, repo := range jx.GetMaps(dpr, "repositories") {
					for _, model := range jx.GetMaps(repo, "models") {
						prSummaries += jx.GetFloat(model, "total_pr_summaries_created")
					}
				}
			}
		}
	}
	codeCompletions := jx.L{}
	for _, k := range langMap.sortedKeysBy(func(a, b *langMetric) bool { return a.suggestions > b.suggestions }) {
		lm := langMap.m[k]
		codeCompletions = append(codeCompletions, jx.M{
			"language": k, "suggestions": lm.suggestions, "acceptances": lm.acceptances,
			"lines_suggested": lm.linesSuggested, "lines_accepted": lm.linesAccepted, "engaged_users": lm.engaged,
		})
	}

	var teamMemberCount any
	if teamFilter != nil && teamFilter.isSet {
		teamMemberCount = len(teamFilter.set)
	}
	var selTeam, selUser any
	if enterpriseTeam != "" {
		selTeam = enterpriseTeam
	}
	if selectedUser != "" {
		selUser = selectedUser
	}
	return jx.M{
		"kpi":              kpi,
		"seat_info":        seatInfo,
		"daily_trend":      dailyTrend,
		"feature_usage":    featureUsage,
		"model_usage":      modelUsage,
		"ide_usage":        ideUsage,
		"language_usage":   languageUsage,
		"code_completions": codeCompletions,
		"ai_credit_detail": aiCreditDetail,
		"ai_credit_period": aiCreditPeriod,
		"chat_stats": jx.M{"ide_chats": ideChats, "ide_copy_events": ideCopy, "ide_insertion_events": ideInsert,
			"dotcom_chats": dotcomChats, "pr_summaries": prSummaries},
		"top_users":                topUsers,
		"orgs":                     allOrgNames,
		"enterprise_teams":         dataEnterpriseTeamOptions(l),
		"selected_enterprise_team": selTeam,
		"team_filtered":            teamFilter != nil,
		"team_member_count":        teamMemberCount,
		"users":                    dataDashboardUserOptions(l, selectedSeatOrgs, teamFilter),
		"selected_user":            selUser,
		"date_range":               jx.M{"start": agg.dateStart, "end": agg.dateEnd},
	}
}

// dataPrefix is Python s[:n].
func dataPrefix(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n]
}

// dataDashboardUserOptions lists every login the dashboard can be filtered to.
func dataDashboardUserOptions(l *dataLoader, selectedOrgs []string, filter *dataMemberFilter) []string {
	logins := newDataOM[string]()
	add := func(login string) {
		if login == "" {
			return
		}
		key := strings.ToLower(login)
		if filter != nil && !filter.has(key) {
			return
		}
		logins.at(key, func() string { return login })
	}
	for _, org := range selectedOrgs {
		if sd := l.latestMap("seats", org); sd != nil {
			for _, seat := range jx.GetMaps(sd, "seats") {
				add(jx.Str(jx.GetMap(seat, "assignee")["login"]))
			}
		}
		if uu := l.latestMap("usage_users", org); uu != nil {
			for _, rec := range jx.GetMaps(uu, "records") {
				add(jx.Str(rec["user_login"]))
			}
		}
	}
	out := []string{}
	for _, k := range logins.keys {
		out = append(out, logins.m[k])
	}
	dataSortLower(out)
	return out
}
