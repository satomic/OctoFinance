package app

import (
	"math"
	"sort"
	"strings"
	"time"

	"github.com/satomic/octofinance/backend-go/internal/jx"
)

// Personal ("me") data router (Python routers/me.py). Every endpoint is scoped
// to the logged-in GitHub user.

func init() { registerRoutes(registerMeRoutes) }

func registerMeRoutes(r *Router) {
	r.Handle("GET /api/me/dashboard", meDashboard)
	r.Handle("GET /api/me/cost-centers", meCostCenters)
	r.Handle("GET /api/me/budget", meBudget)
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// meFSum is Python 3.12+'s builtin sum() over floats (Neumaier compensated).
func meFSum(xs []float64) float64 {
	var s, c float64
	for _, x := range xs {
		t := s + x
		if math.Abs(s) >= math.Abs(x) {
			c += (s - t) + x
		} else {
			c += (x - t) + s
		}
		s = t
	}
	if c != 0 && !math.IsInf(c, 0) && !math.IsNaN(c) {
		s += c
	}
	return s
}

// meOrd is an insertion-ordered map (Python dict / defaultdict).
type meOrd[T any] struct {
	keys []string
	raw  map[string]any
	m    map[string]*T
	mk   func() *T
}

func newMeOrd[T any](mk func() *T) *meOrd[T] {
	return &meOrd[T]{raw: map[string]any{}, m: map[string]*T{}, mk: mk}
}

// get returns the entry for key, creating it on first use (defaultdict).
func (o *meOrd[T]) get(key string) *T {
	v, ok := o.m[key]
	if !ok {
		v = o.mk()
		o.m[key] = v
		o.keys = append(o.keys, key)
		o.raw[key] = key
	}
	return v
}

// getAny keys by an arbitrary JSON value (None stays distinct from "None").
func (o *meOrd[T]) getAny(v any) *T {
	key := "s:" + jx.Str(v)
	if v == nil {
		key = "n:"
	} else if _, ok := v.(string); !ok {
		key = "o:" + jx.Str(v)
	}
	e := o.get(key)
	o.raw[key] = v
	return e
}

func (o *meOrd[T]) sortedKeys() []string {
	ks := append([]string(nil), o.keys...)
	sort.Strings(ks)
	return ks
}

// meCSVGet is “r.get(key, def)“ on a CSV row.
func meCSVGet(r CSVRecord, key, def string) string {
	if v, ok := r[key]; ok {
		return v
	}
	return def
}

func meDaysSince(iso string) any {
	if iso == "" {
		return nil
	}
	t, ok := jx.ParseISO(iso)
	if !ok {
		return nil
	}
	d := jx.DaysBetween(time.Now().UTC(), t)
	if d < 0 {
		d = 0
	}
	return d
}

// ---------------------------------------------------------------------------
// Section builders
// ---------------------------------------------------------------------------

func meSeats(login string) []jx.M {
	target := strings.ToLower(login)
	byOrg := map[string]jx.M{}
	scopes := latestFileScopes("seats")
	if len(scopes) == 0 {
		return []jx.M{}
	}
	allSeats := Collector.LoadAllLatest("seats")
	allBilling := Collector.LoadAllLatest("billing")
	for _, org := range scopes {
		data := jx.Map(allSeats[org])
		if len(data) == 0 {
			continue
		}
		billing := jx.Map(allBilling[org])
		price := jx.Float(jx.Get(billing, "_detected_price_per_seat"))
		if price == 0 {
			price = 19.0
		}
		plan := jx.GetOr(billing, "_detected_plan_type", "unknown")
		for _, seat := range jx.GetMaps(data, "seats") {
			assignee := jx.Map(seat["assignee"])
			if strings.ToLower(jx.Str(jx.GetOr(assignee, "login", ""))) != target {
				continue
			}
			lastActivity := jx.OrStr(seat, "last_activity_at", "")
			team := ""
			if t := jx.Map(seat["assigning_team"]); t != nil {
				team = jx.Str(jx.GetOr(t, "name", ""))
			}
			entry := jx.M{
				"org":                       org,
				"plan_type":                 plan,
				"price_per_seat":            price,
				"created_at":                jx.GetOr(seat, "created_at", ""),
				"last_activity_at":          lastActivity,
				"last_activity_editor":      jx.GetOr(seat, "last_activity_editor", ""),
				"days_inactive":             meDaysSince(lastActivity),
				"assigning_team":            team,
				"pending_cancellation_date": seat["pending_cancellation_date"],
			}
			existing, ok := byOrg[org]
			if !ok {
				byOrg[org] = entry
				continue
			}
			if lastActivity > jx.Str(existing["last_activity_at"]) {
				existing["last_activity_at"] = lastActivity
				existing["days_inactive"] = entry["days_inactive"]
				existing["last_activity_editor"] = entry["last_activity_editor"]
			}
			if jx.Truthy(entry["created_at"]) && (!jx.Truthy(existing["created_at"]) ||
				jx.Str(entry["created_at"]) < jx.Str(existing["created_at"])) {
				existing["created_at"] = entry["created_at"]
			}
			if team != "" && !jx.Truthy(existing["assigning_team"]) {
				existing["assigning_team"] = team
			}
		}
	}
	out := []jx.M{}
	for _, org := range jx.SortedKeys(byOrg) {
		out = append(out, byOrg[org])
	}
	return out
}

type meCounts struct{ interactions, generated, accepted, locAdded int }

func meActivity(login, dateFrom, dateTo string) jx.M {
	target := strings.ToLower(login)
	daily := newMeOrd(func() *meCounts { return &meCounts{} })
	features := newMeOrd(func() *meCounts { return &meCounts{} })
	languages := newMeOrd(func() *meCounts { return &meCounts{} })
	models := newMeOrd(func() *meCounts { return &meCounts{} })
	editors := newMeOrd(func() *meCounts { return &meCounts{} })
	orgs := jx.StrSet{}
	hasData := false

	for _, org := range latestFileScopes("usage_users") {
		data := Collector.LoadLatestMap("usage_users", org)
		if len(data) == 0 {
			continue
		}
		for _, rec := range jx.GetMaps(data, "records") {
			if strings.ToLower(jx.Str(jx.GetOr(rec, "user_login", ""))) != target {
				continue
			}
			day := jx.Str(jx.GetOr(rec, "day", ""))
			if dateFrom != "" && day < dateFrom {
				continue
			}
			if dateTo != "" && day > dateTo {
				continue
			}
			hasData = true
			orgs.Add(org)
			d := daily.get(day)
			d.interactions += jx.GetInt(rec, "user_initiated_interaction_count")
			d.generated += jx.GetInt(rec, "code_generation_activity_count")
			d.accepted += jx.GetInt(rec, "code_acceptance_activity_count")

			for _, f := range jx.GetMaps(rec, "totals_by_feature") {
				fm := features.getAny(jx.GetOr(f, "feature", "unknown"))
				fm.interactions += jx.GetInt(f, "user_initiated_interaction_count")
				fm.generated += jx.GetInt(f, "code_generation_activity_count")
				fm.accepted += jx.GetInt(f, "code_acceptance_activity_count")
			}
			for _, l := range jx.GetMaps(rec, "totals_by_language_feature") {
				lm := languages.getAny(jx.GetOr(l, "language", "unknown"))
				lm.generated += jx.GetInt(l, "code_generation_activity_count")
				lm.accepted += jx.GetInt(l, "code_acceptance_activity_count")
				lm.locAdded += jx.GetInt(l, "loc_added_sum")
			}
			for _, m := range jx.GetMaps(rec, "totals_by_language_model") {
				mm := models.getAny(jx.GetOr(m, "model", "unknown"))
				mm.generated += jx.GetInt(m, "code_generation_activity_count")
				mm.accepted += jx.GetInt(m, "code_acceptance_activity_count")
			}
			for _, i := range jx.GetMaps(rec, "totals_by_ide") {
				em := editors.getAny(jx.GetOr(i, "ide", "unknown"))
				em.interactions += jx.GetInt(i, "user_initiated_interaction_count")
				em.generated += jx.GetInt(i, "code_generation_activity_count")
				em.accepted += jx.GetInt(i, "code_acceptance_activity_count")
			}
		}
	}

	trend := []jx.M{}
	for _, day := range daily.sortedKeys() {
		if day == "" {
			continue
		}
		v := daily.m[day]
		trend = append(trend, jx.M{"day": day, "interactions": v.interactions, "generated": v.generated, "accepted": v.accepted})
	}
	var ti, tg, ta, active int
	for _, day := range daily.keys {
		v := daily.m[day]
		ti += v.interactions
		tg += v.generated
		ta += v.accepted
		if day != "" && v.interactions+v.generated+v.accepted > 0 {
			active++
		}
	}
	var rate any = 0
	if tg != 0 {
		rate = jx.Round(float64(ta)/float64(tg)*100, 1)
	}

	rank := func(o *meOrd[meCounts], key string, fields func(*meCounts) (jx.M, int)) []jx.M {
		keys := append([]string(nil), o.keys...)
		sort.SliceStable(keys, func(i, j int) bool {
			_, a := fields(o.m[keys[i]])
			_, b := fields(o.m[keys[j]])
			return -a < -b
		})
		out := []jx.M{}
		for _, k := range keys {
			m, _ := fields(o.m[k])
			m[key] = o.raw[k]
			out = append(out, m)
		}
		return out
	}
	igA := func(v *meCounts) (jx.M, int) {
		return jx.M{"interactions": v.interactions, "generated": v.generated, "accepted": v.accepted},
			v.interactions + v.generated + v.accepted
	}

	return jx.M{
		"has_data": hasData,
		"orgs":     orgs.Sorted(),
		"kpi": jx.M{
			"total_interactions": ti,
			"code_generated":     tg,
			"code_accepted":      ta,
			"acceptance_rate":    rate,
			"active_days":        active,
		},
		"daily_trend":       trend,
		"feature_breakdown": rank(features, "feature", igA),
		"language_breakdown": rank(languages, "language", func(v *meCounts) (jx.M, int) {
			return jx.M{"generated": v.generated, "accepted": v.accepted, "loc_added": v.locAdded},
				v.generated + v.accepted + v.locAdded
		}),
		"model_breakdown": rank(models, "model", func(v *meCounts) (jx.M, int) {
			return jx.M{"generated": v.generated, "accepted": v.accepted}, v.generated + v.accepted
		}),
		"editor_breakdown": rank(editors, "ide", igA),
	}
}

// meUserCSV returns this user's CSV rows within the date window.
func meUserCSV(csvType, login, dateFrom, dateTo string) []CSVRecord {
	target := strings.ToLower(login)
	out := []CSVRecord{}
	for _, r := range LoadAllCSVRecords(csvType) {
		if strings.ToLower(r["username"]) != target {
			continue
		}
		if dateFrom != "" && r["date"] < dateFrom {
			continue
		}
		if dateTo != "" && r["date"] > dateTo {
			continue
		}
		out = append(out, r)
	}
	return out
}

func meDateRange(records []CSVRecord) jx.M {
	dates := make([]string, 0, len(records))
	for _, r := range records {
		dates = append(dates, r["date"])
	}
	lo, hi, _ := jx.MinMax(dates)
	return jx.M{"start": lo, "end": hi}
}

type meAIAgg struct {
	requests, amount float64
	metrics          jx.M
}

func meAIUsage(login, dateFrom, dateTo string) jx.M {
	records := meUserCSV(CSVTypeAI, login, dateFrom, dateTo)
	if len(records) == 0 {
		return jx.M{"has_data": false, "kpi": jx.M{}, "daily_trend": jx.L{}, "model_breakdown": jx.L{}, "date_range": jx.M{}}
	}
	mk := func() *meAIAgg { return &meAIAgg{metrics: jx.M{}} }
	daily := newMeOrd(mk)
	models := newMeOrd(mk)
	metricTotals := jx.M{}
	quota := 0
	org, costCenter := "", ""
	nets := make([]float64, 0, len(records))

	for _, r := range records {
		qty := jx.Float(r["quantity"])
		gross := jx.Float(r["gross_amount"])
		day := r["date"]
		AddAIUsageMetrics(metricTotals, r)
		d := daily.get(day)
		AddAIUsageMetrics(d.metrics, r)
		d.requests += qty
		d.amount += gross
		m := models.get(meCSVGet(r, "model", "unknown"))
		AddAIUsageMetrics(m.metrics, r)
		m.requests += qty
		m.amount += gross
		if v := r["organization"]; v != "" {
			org = v
		}
		if v := r["cost_center_name"]; v != "" {
			costCenter = v
		}
		if q := int(jx.Float(r["total_monthly_quota"])); q > quota {
			quota = q
		}
		nets = append(nets, jx.Float(r["net_amount"]))
	}

	reqs := []float64{}
	amts := []float64{}
	activeDays := 0
	for _, k := range daily.keys {
		reqs = append(reqs, daily.m[k].requests)
		amts = append(amts, daily.m[k].amount)
		if k != "" {
			activeDays++
		}
	}
	totalRequests := meFSum(reqs)
	totalAmount := meFSum(amts)
	totalNet := meFSum(nets)

	var usagePct any = 0
	if quota > 0 {
		usagePct = jx.Round(totalRequests/float64(quota)*100, 1)
	}
	kpi := jx.M{
		"total_requests": jx.Round(totalRequests, 2),
		"total_cost":     jx.Round(totalAmount, 4),
		"net_cost":       jx.Round(totalNet, 4),
		"quota":          quota,
		"usage_pct":      usagePct,
		"active_days":    activeDays,
		"models_used":    len(models.keys),
	}
	for k, v := range metricTotals {
		kpi[k] = v
	}
	row := func(key, name string, v *meAIAgg) jx.M {
		out := jx.M{key: name, "requests": jx.Round(v.requests, 2), "amount": jx.Round(v.amount, 4)}
		for _, f := range AIUsageMetricFields {
			out[f] = v.metrics[f]
		}
		return out
	}
	trend := []jx.M{}
	for _, d := range daily.sortedKeys() {
		if d != "" {
			trend = append(trend, row("day", d, daily.m[d]))
		}
	}
	mkeys := append([]string(nil), models.keys...)
	sort.SliceStable(mkeys, func(i, j int) bool { return -models.m[mkeys[i]].requests < -models.m[mkeys[j]].requests })
	breakdown := []jx.M{}
	for _, k := range mkeys {
		breakdown = append(breakdown, row("model", k, models.m[k]))
	}
	return jx.M{
		"has_data":        true,
		"org":             org,
		"cost_center":     costCenter,
		"date_range":      meDateRange(records),
		"kpi":             kpi,
		"daily_trend":     trend,
		"model_breakdown": breakdown,
	}
}

type meSpendAgg struct{ gross, net, qty float64 }

func meSpend(login, dateFrom, dateTo string) jx.M {
	records := meUserCSV(CSVTypeUsage, login, dateFrom, dateTo)
	if len(records) == 0 {
		return jx.M{"has_data": false, "kpi": jx.M{}, "daily_trend": jx.L{}, "sku_breakdown": jx.L{}, "product_breakdown": jx.L{}}
	}
	mk := func() *meSpendAgg { return &meSpendAgg{} }
	daily := newMeOrd(mk)
	skus := newMeOrd(mk)
	products := newMeOrd(mk)
	for _, r := range records {
		gross, net, qty := jx.Float(r["gross_amount"]), jx.Float(r["net_amount"]), jx.Float(r["quantity"])
		d := daily.get(r["date"])
		d.gross += gross
		d.net += net
		for _, a := range []*meSpendAgg{skus.get(meCSVGet(r, "sku", "unknown")), products.get(meCSVGet(r, "product", "unknown"))} {
			a.gross += gross
			a.net += net
			a.qty += qty
		}
	}
	grosses, nets := []float64{}, []float64{}
	active := 0
	for _, k := range daily.keys {
		grosses = append(grosses, daily.m[k].gross)
		nets = append(nets, daily.m[k].net)
		if k != "" {
			active++
		}
	}
	trend := []jx.M{}
	for _, d := range daily.sortedKeys() {
		if d != "" {
			v := daily.m[d]
			trend = append(trend, jx.M{"day": d, "gross_amount": jx.Round(v.gross, 4), "net_amount": jx.Round(v.net, 4)})
		}
	}
	breakdown := func(o *meOrd[meSpendAgg], key string) []jx.M {
		keys := append([]string(nil), o.keys...)
		sort.SliceStable(keys, func(i, j int) bool { return -o.m[keys[i]].gross < -o.m[keys[j]].gross })
		out := []jx.M{}
		for _, k := range keys {
			v := o.m[k]
			out = append(out, jx.M{key: k, "gross_amount": jx.Round(v.gross, 4), "net_amount": jx.Round(v.net, 4),
				"quantity": jx.Round(v.qty, 4)})
		}
		return out
	}
	return jx.M{
		"has_data":   true,
		"date_range": meDateRange(records),
		"kpi": jx.M{
			"total_gross": jx.Round(meFSum(grosses), 4),
			"total_net":   jx.Round(meFSum(nets), 4),
			"active_days": active,
		},
		"daily_trend":       trend,
		"sku_breakdown":     breakdown(skus, "sku"),
		"product_breakdown": breakdown(products, "product"),
	}
}

// ---------------------------------------------------------------------------
// Endpoints
// ---------------------------------------------------------------------------

func meDashboard(c *Ctx) any {
	user := c.User
	login := jx.Str(jx.GetOr(user, "login", ""))
	mode, from, to := ResolvePeriod(c.Query("period", "all"), c.Query("date_from", ""), c.Query("date_to", ""))
	live, bad := meQueryBool(c, "live", false)
	if bad != nil {
		return bad
	}

	seats := meSeats(login)
	activity := meActivity(login, from, to)
	aiUsage := meAIUsage(login, from, to)
	spend := meSpend(login, from, to)

	wantLive := live || mode == "current_month"
	budgetCtx := GetUserBudgetContext(c.R.Context(), login, wantLive)

	requests := LoadRequestsFor(login)
	sort.SliceStable(requests, func(i, j int) bool {
		return jx.Str(jx.GetOr(requests[i], "created_at", "")) > jx.Str(jx.GetOr(requests[j], "created_at", ""))
	})

	prices := []float64{}
	seatOrgs := []string{}
	for _, s := range seats {
		prices = append(prices, jx.Float(s["price_per_seat"]))
		seatOrgs = append(seatOrgs, jx.Str(s["org"]))
	}
	seatCost := jx.Round(meFSum(prices), 2)
	aiCost := jx.Round(jx.Float(jx.GetMap(aiUsage, "kpi")["total_cost"]), 4)
	totalSpend := jx.Round(seatCost+aiCost, 4)

	effective := jx.Map(budgetCtx["effective_budget"])
	budgetAmount := 0.0
	if len(effective) > 0 {
		budgetAmount = jx.Float(effective["amount"])
	}
	consumed := effective["consumed_amount"]
	consumedValue := aiCost
	consumedSource := "usage_data"
	if consumed != nil {
		consumedValue = jx.Float(consumed)
		consumedSource = "github"
	}
	var remaining, usagePct any
	if budgetAmount > 0 {
		remaining = jx.Round(budgetAmount-consumedValue, 4)
		usagePct = jx.Round(consumedValue/budgetAmount*100, 1)
	}
	period := jx.M{"mode": mode, "date_from": from, "date_to": to, "label": ""}
	if from != "" && to != "" {
		period["label"] = from + " ~ " + to
	}
	hasAny := len(seats) > 0 || jx.GetBool(activity, "has_data") || jx.GetBool(aiUsage, "has_data") ||
		jx.GetBool(spend, "has_data") || jx.GetBool(budgetCtx, "cost_centers") || jx.GetBool(budgetCtx, "effective_budget")

	return jx.M{
		"profile": jx.M{
			"login":      login,
			"name":       jx.GetOr(user, "name", ""),
			"avatar_url": jx.GetOr(user, "avatar_url", ""),
			"auth_type":  jx.GetOr(user, "auth_type", "local"),
			"is_admin":   jx.GetBool(user, "is_admin"),
		},
		"period": period,
		"seats":  seats,
		"seat_summary": jx.M{
			"seat_count":        len(seats),
			"monthly_seat_cost": seatCost,
			"orgs":              seatOrgs,
		},
		"activity": activity,
		"ai_usage": aiUsage,
		"spend":    spend,
		"budget": jx.M{
			"live":             jx.GetBool(budgetCtx, "live"),
			"personal":         budgetCtx["personal_budget"],
			"universal":        budgetCtx["universal_budget"],
			"effective":        budgetCtx["effective_budget"],
			"effective_source": budgetCtx["effective_source"],
			"amount":           budgetAmount,
			"consumed":         jx.Round(consumedValue, 4),
			"consumed_source":  consumedSource,
			"remaining":        remaining,
			"usage_pct":        usagePct,
			"error":            budgetCtx["error"],
		},
		"cost_centers": jx.GetOr(budgetCtx, "cost_centers", jx.L{}),
		"totals": jx.M{
			"monthly_seat_cost": seatCost,
			"ai_credit_cost":    aiCost,
			"estimated_total":   totalSpend,
			"budget_amount":     budgetAmount,
			"budget_remaining":  remaining,
		},
		"budget_requests": requests,
		"has_any_data":    hasAny,
	}
}

func meCostCenters(c *Ctx) any {
	return ListCostCentersForUser(jx.Str(jx.GetOr(c.User, "login", "")))
}

func meBudget(c *Ctx) any {
	live, bad := meQueryBool(c, "live", true)
	if bad != nil {
		return bad
	}
	login := jx.Str(jx.GetOr(c.User, "login", ""))
	start, end := CurrentMonthRange()
	ctx := GetUserBudgetContext(c.R.Context(), login, live)
	month := meAIUsage(login, start, end)
	kpi := jx.GetMap(month, "kpi")
	out := jx.Copy(ctx)
	out["current_month"] = jx.M{"start": start, "end": end}
	out["current_month_ai_cost"] = jx.Round(jx.Float(kpi["total_cost"]), 4)
	out["current_month_requests"] = jx.Round(jx.Float(kpi["total_requests"]), 2)
	return out
}

// meQueryBool parses a FastAPI bool query param, returning a 422 on bad input.
func meQueryBool(c *Ctx, name string, def bool) (bool, *Resp) {
	if !c.HasQuery(name) {
		return def, nil
	}
	raw := c.Query(name)
	switch strings.ToLower(raw) {
	case "1", "true", "yes", "on", "t", "y":
		return true, nil
	case "0", "false", "no", "off", "f", "n":
		return false, nil
	}
	return def, JSONStatus(422, jx.M{"detail": jx.L{jx.M{
		"type": "bool_parsing", "loc": jx.L{"query", name},
		"msg": "Input should be a valid boolean, unable to interpret input", "input": raw,
	}}})
}
