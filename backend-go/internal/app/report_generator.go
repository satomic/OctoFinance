package app

// Cost Center HTML report generator (Python services/report_generator.py).
//
// Produces self-contained HTML files (no external dependencies) with embedded
// CSS and server-generated SVG charts. One file per cost center, packaged
// into a ZIP archive. Output is byte-identical to the Python renderer apart
// from the generation timestamp.

import (
	"archive/zip"
	"bytes"
	"math"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/satomic/octofinance/backend-go/internal/githost"
	"github.com/satomic/octofinance/backend-go/internal/jx"
)

// ── colour palette ──────────────────────────────────────────────────────────

var rptTypeColors = map[string]string{
	"Org":  "#539bf5",
	"User": "#3fb950",
	"Team": "#d29922",
}

const (
	rptAccent = "#539bf5"
	rptGreen  = "#3fb950"
	rptMuted  = "#768390"
)

// ── Python formatting helpers ───────────────────────────────────────────────

// rptEscape mirrors Python html.escape(s, quote=True).
func rptEscape(s string) string {
	if !strings.ContainsAny(s, "&<>\"'") {
		return s
	}
	var b strings.Builder
	b.Grow(len(s) + 16)
	for _, r := range s {
		switch r {
		case '&':
			b.WriteString("&amp;")
		case '<':
			b.WriteString("&lt;")
		case '>':
			b.WriteString("&gt;")
		case '"':
			b.WriteString("&quot;")
		case '\'':
			b.WriteString("&#x27;")
		default:
			b.WriteRune(r)
		}
	}
	return b.String()
}

// rptE is Python _e: escape(str(v) if v is not None else "").
func rptE(v any) string { return rptEscape(rptPyStr(v)) }

// rptPyStr is str(v) for JSON values (None -> ""). JSON numbers decode to
// float64 in Go; integral ones print without ".0" like Python ints.
func rptPyStr(v any) string { return jx.Str(v) }

// rptFixed is Python f"{f:.Nf}".
func rptFixed(f float64, n int) string {
	switch {
	case math.IsNaN(f):
		return "nan"
	case math.IsInf(f, 1):
		return "inf"
	case math.IsInf(f, -1):
		return "-inf"
	}
	return strconv.FormatFloat(f, 'f', n, 64)
}

// rptGroup inserts thousands separators into the integer part of a decimal string.
func rptGroup(s string) string {
	neg := strings.HasPrefix(s, "-")
	if neg {
		s = s[1:]
	}
	intPart, frac, hasFrac := strings.Cut(s, ".")
	if len(intPart) > 3 && intPart[0] >= '0' && intPart[0] <= '9' {
		var b strings.Builder
		first := len(intPart) % 3
		if first > 0 {
			b.WriteString(intPart[:first])
		}
		for i := first; i < len(intPart); i += 3 {
			if b.Len() > 0 {
				b.WriteByte(',')
			}
			b.WriteString(intPart[i : i+3])
		}
		intPart = b.String()
	}
	out := intPart
	if hasFrac {
		out += "." + frac
	}
	if neg {
		out = "-" + out
	}
	return out
}

// rptToFloat mirrors Python float(v) (ok=false where Python raises).
func rptToFloat(v any) (float64, bool) {
	switch t := v.(type) {
	case string:
		s := strings.ToLower(strings.TrimSpace(strings.ReplaceAll(t, "_", "")))
		switch s {
		case "nan", "+nan", "-nan":
			return math.NaN(), true
		case "inf", "+inf", "infinity", "+infinity":
			return math.Inf(1), true
		case "-inf", "-infinity":
			return math.Inf(-1), true
		}
		f, err := strconv.ParseFloat(s, 64)
		if err != nil {
			return 0, false
		}
		return f, true
	case nil:
		return 0, false
	}
	return jx.FloatOK(v)
}

// rptMoney is Python _money.
func rptMoney(v any) string {
	f, ok := rptToFloat(v)
	if !ok {
		return "-"
	}
	return "$" + rptGroup(rptFixed(f, 2))
}

// rptNum is Python _num: f"{int(float(v)):,}".
func rptNum(v any) string {
	f, ok := rptToFloat(v)
	if !ok || math.IsNaN(f) || math.IsInf(f, 0) {
		return rptPyStr(v)
	}
	return rptGroup(strconv.FormatFloat(math.Trunc(f), 'f', 0, 64))
}

// rptPct is Python _pct.
func rptPct(v any) string {
	f, ok := rptToFloat(v)
	if !ok {
		return "-"
	}
	return rptFixed(f, 1) + "%"
}

// ── ordered accumulation helpers ────────────────────────────────────────────

type rptStrFloat struct {
	keys []string
	vals map[string]float64
}

func newRptStrFloat() *rptStrFloat { return &rptStrFloat{vals: map[string]float64{}} }

func (o *rptStrFloat) add(k string, v float64) {
	if _, ok := o.vals[k]; !ok {
		o.keys = append(o.keys, k)
	}
	o.vals[k] += v
}

// sortedDesc returns keys sorted by descending value (stable on insertion order).
func (o *rptStrFloat) sortedDesc() []string {
	keys := append([]string(nil), o.keys...)
	sort.SliceStable(keys, func(i, j int) bool { return -o.vals[keys[i]] < -o.vals[keys[j]] })
	return keys
}

func rptMetricFields(src jx.M) jx.M {
	out := jx.M{}
	for _, f := range AIUsageMetricFields {
		out[f] = src[f]
	}
	return out
}

// rptPyInt mirrors Python int(str) for the quota column.
func rptPyInt(s string) (int, bool) {
	t := strings.TrimSpace(s)
	if strings.Contains(t, "_") {
		if strings.HasPrefix(t, "_") || strings.HasSuffix(t, "_") || strings.Contains(t, "__") {
			return 0, false
		}
		t = strings.ReplaceAll(t, "_", "")
	}
	n, err := strconv.Atoi(t)
	if err != nil {
		return 0, false
	}
	return n, true
}

// ── aggregation (mirrors data.py logic on pre-filtered records) ─────────────

type rptAIUser struct {
	requests, gross, net float64
	models               *rptStrFloat
	days                 jx.StrSet
	org                  string
	quota                int
	metrics              jx.M
}

type rptAgg struct {
	requests, amount float64
	users            jx.StrSet
	metrics          jx.M
}

func rptRecGet(r CSVRecord, key string) string { return r[key] }

// BuildAIUsageSection aggregates AI usage CSV records (Python _build_ai_usage_section).
func BuildAIUsageSection(records []CSVRecord) jx.M {
	if len(records) == 0 {
		return jx.M{"has_data": false}
	}
	dates := []string{}
	for _, r := range records {
		if d := r["date"]; d != "" {
			dates = append(dates, d)
		}
	}
	dateRange := jx.M{}
	if lo, hi, ok := jx.MinMax(dates); ok {
		dateRange = jx.M{"start": lo, "end": hi}
	}

	userOrder := []string{}
	userMap := map[string]*rptAIUser{}
	dayOrder := []string{}
	dayMap := map[string]*rptAgg{}
	modelOrder := []string{}
	modelMap := map[string]*rptAgg{}
	metricTotals := jx.M{}

	for _, r := range records {
		user := r["username"]
		qty := jx.Float(r["quantity"])
		gross := jx.Float(r["gross_amount"])
		net := jx.Float(r["net_amount"])
		model := r["model"]
		if model == "" {
			model = "unknown"
		}
		day := r["date"]

		u, ok := userMap[user]
		if !ok {
			u = &rptAIUser{models: newRptStrFloat(), days: jx.StrSet{}, metrics: jx.M{}}
			userMap[user] = u
			userOrder = append(userOrder, user)
		}
		AddAIUsageMetrics(metricTotals, r)
		AddAIUsageMetrics(u.metrics, r)
		u.requests += qty
		u.gross += gross
		u.net += net
		u.models.add(model, qty)
		u.days.Add(day)
		u.org = r["organization"]
		if raw, has := r["total_monthly_quota"]; !has || raw == "" {
			u.quota = 0
		} else if n, ok := rptPyInt(raw); ok {
			u.quota = n
		}

		dm, ok := dayMap[day]
		if !ok {
			dm = &rptAgg{users: jx.StrSet{}, metrics: jx.M{}}
			dayMap[day] = dm
			dayOrder = append(dayOrder, day)
		}
		AddAIUsageMetrics(dm.metrics, r)
		dm.requests += qty
		dm.amount += gross
		dm.users.Add(user)

		mm, ok := modelMap[model]
		if !ok {
			mm = &rptAgg{users: jx.StrSet{}, metrics: jx.M{}}
			modelMap[model] = mm
			modelOrder = append(modelOrder, model)
		}
		AddAIUsageMetrics(mm.metrics, r)
		mm.requests += qty
		mm.amount += gross
		mm.users.Add(user)
	}

	sortedUsers := append([]string(nil), userOrder...)
	sort.SliceStable(sortedUsers, func(i, j int) bool {
		return -userMap[sortedUsers[i]].requests < -userMap[sortedUsers[j]].requests
	})
	users := []jx.M{}
	for _, name := range sortedUsers {
		info := userMap[name]
		models := jx.L{}
		for _, m := range info.models.sortedDesc() {
			models = append(models, jx.M{"model": m, "requests": info.models.vals[m]})
		}
		var usagePct any = 0
		if info.quota > 0 {
			usagePct = jx.Round(info.requests/float64(info.quota)*100, 1)
		}
		users = append(users, jx.Merge(jx.M{
			"user": name, "org": info.org,
			"requests":     jx.Round(info.requests, 2),
			"gross_amount": jx.Round(info.gross, 4),
			"net_amount":   jx.Round(info.net, 4),
			"days_active":  len(info.days),
			"quota":        info.quota,
			"usage_pct":    usagePct,
			"models":       models,
		}, rptMetricFields(info.metrics)))
	}

	sortedDays := append([]string(nil), dayOrder...)
	sort.Strings(sortedDays)
	dailyTrend := []jx.M{}
	for _, d := range sortedDays {
		v := dayMap[d]
		dailyTrend = append(dailyTrend, jx.Merge(jx.M{
			"day": d, "requests": jx.Round(v.requests, 2),
			"amount": jx.Round(v.amount, 4), "active_users": len(v.users),
		}, rptMetricFields(v.metrics)))
	}

	sortedModels := append([]string(nil), modelOrder...)
	sort.SliceStable(sortedModels, func(i, j int) bool {
		return -modelMap[sortedModels[i]].requests < -modelMap[sortedModels[j]].requests
	})
	modelBreakdown := []jx.M{}
	for _, m := range sortedModels {
		v := modelMap[m]
		modelBreakdown = append(modelBreakdown, jx.Merge(jx.M{
			"model": m, "requests": jx.Round(v.requests, 2),
			"amount": jx.Round(v.amount, 4), "user_count": len(v.users),
		}, rptMetricFields(v.metrics)))
	}

	totalReq, totalCost := 0.0, 0.0
	for _, u := range users {
		totalReq += u["requests"].(float64)
	}
	for _, u := range users {
		totalCost += u["gross_amount"].(float64)
	}

	return jx.M{
		"has_data":   true,
		"date_range": dateRange,
		"kpi": jx.Merge(jx.M{
			"total_requests": jx.Round(totalReq, 2),
			"total_cost":     jx.Round(totalCost, 4),
			"unique_users":   len(users),
		}, metricTotals),
		"daily_trend":     dailyTrend,
		"model_breakdown": modelBreakdown,
		"users":           users,
	}
}

type rptUsageUser struct {
	gross, net, qty float64
	org             string
	skus            *rptStrFloat
	days            jx.StrSet
}

type rptUsageAgg struct {
	gross, net, qty float64
	users           jx.StrSet
}

// BuildUsageSection aggregates usage report CSV records (Python _build_usage_section).
func BuildUsageSection(records []CSVRecord) jx.M {
	if len(records) == 0 {
		return jx.M{"has_data": false}
	}
	dates := []string{}
	for _, r := range records {
		if d := r["date"]; d != "" {
			dates = append(dates, d)
		}
	}
	dateRange := jx.M{}
	if lo, hi, ok := jx.MinMax(dates); ok {
		dateRange = jx.M{"start": lo, "end": hi}
	}

	userOrder, dayOrder, skuOrder := []string{}, []string{}, []string{}
	userMap := map[string]*rptUsageUser{}
	dayMap := map[string]*rptUsageAgg{}
	skuMap := map[string]*rptUsageAgg{}

	for _, r := range records {
		user := r["username"]
		gross := jx.Float(r["gross_amount"])
		net := jx.Float(r["net_amount"])
		qty := jx.Float(r["quantity"])
		sku := r["sku"]
		if sku == "" {
			sku = "unknown"
		}
		day := r["date"]

		um, ok := userMap[user]
		if !ok {
			um = &rptUsageUser{skus: newRptStrFloat(), days: jx.StrSet{}}
			userMap[user] = um
			userOrder = append(userOrder, user)
		}
		um.gross += gross
		um.net += net
		um.qty += qty
		um.org = r["organization"]
		um.skus.add(sku, gross)
		um.days.Add(day)

		dm, ok := dayMap[day]
		if !ok {
			dm = &rptUsageAgg{users: jx.StrSet{}}
			dayMap[day] = dm
			dayOrder = append(dayOrder, day)
		}
		dm.gross += gross
		dm.net += net
		dm.users.Add(user)

		sm, ok := skuMap[sku]
		if !ok {
			sm = &rptUsageAgg{users: jx.StrSet{}}
			skuMap[sku] = sm
			skuOrder = append(skuOrder, sku)
		}
		sm.gross += gross
		sm.net += net
		sm.qty += qty
		sm.users.Add(user)
	}

	sortedUsers := append([]string(nil), userOrder...)
	sort.SliceStable(sortedUsers, func(i, j int) bool {
		return -userMap[sortedUsers[i]].gross < -userMap[sortedUsers[j]].gross
	})
	users := []jx.M{}
	for _, name := range sortedUsers {
		info := userMap[name]
		skus := jx.L{}
		for _, s := range info.skus.sortedDesc() {
			skus = append(skus, jx.M{"sku": s, "amount": jx.Round(info.skus.vals[s], 4)})
		}
		users = append(users, jx.M{
			"user": name, "org": info.org,
			"gross_amount": jx.Round(info.gross, 4),
			"net_amount":   jx.Round(info.net, 4),
			"quantity":     jx.Round(info.qty, 4),
			"days_active":  len(info.days),
			"skus":         skus,
		})
	}

	sortedDays := append([]string(nil), dayOrder...)
	sort.Strings(sortedDays)
	dailyTrend := []jx.M{}
	for _, d := range sortedDays {
		v := dayMap[d]
		dailyTrend = append(dailyTrend, jx.M{
			"day": d, "gross_amount": jx.Round(v.gross, 4),
			"net_amount": jx.Round(v.net, 4), "active_users": len(v.users),
		})
	}

	sortedSkus := append([]string(nil), skuOrder...)
	sort.SliceStable(sortedSkus, func(i, j int) bool {
		return -skuMap[sortedSkus[i]].gross < -skuMap[sortedSkus[j]].gross
	})
	skuBreakdown := []jx.M{}
	for _, s := range sortedSkus {
		v := skuMap[s]
		skuBreakdown = append(skuBreakdown, jx.M{
			"sku": s, "gross_amount": jx.Round(v.gross, 4),
			"net_amount": jx.Round(v.net, 4),
			"quantity":   jx.Round(v.qty, 4), "user_count": len(v.users),
		})
	}

	totalGross, totalNet, totalDiscount := 0.0, 0.0, 0.0
	for _, r := range records {
		totalGross += jx.Float(r["gross_amount"])
	}
	for _, r := range records {
		totalNet += jx.Float(r["net_amount"])
	}
	for _, r := range records {
		totalDiscount += jx.Float(r["discount_amount"])
	}

	return jx.M{
		"has_data":   true,
		"date_range": dateRange,
		"kpi": jx.M{
			"total_gross":    jx.Round(totalGross, 4),
			"total_net":      jx.Round(totalNet, 4),
			"total_discount": jx.Round(totalDiscount, 4),
			"unique_users":   len(users),
		},
		"daily_trend":   dailyTrend,
		"sku_breakdown": skuBreakdown,
		"users":         users,
	}
}

// ── SVG chart ───────────────────────────────────────────────────────────────

func rptSVGLineChart(data []jx.M, xKey, yKey, yLabel, chartID string) string {
	const w, h = 780, 200
	if len(data) == 0 {
		return `<p class="no-data">No trend data available.</p>`
	}
	values := make([]float64, len(data))
	labels := make([]string, len(data))
	for i, d := range data {
		values[i] = jx.Float(jx.GetOr(d, yKey, 0))
		labels[i] = rptPyStr(jx.GetOr(d, xKey, ""))
	}
	n := len(values)
	const pl, pr, pt, pb = 62, 16, 16, 46
	iw := float64(w - pl - pr)
	ih := float64(h - pt - pb)

	maxV, minV := values[0], values[0]
	for _, v := range values[1:] {
		if v > maxV {
			maxV = v
		}
		if v < minV {
			minV = v
		}
	}
	rng := maxV - minV
	if rng == 0 {
		rng = 1
	}
	den := float64(n - 1)
	if den < 1 {
		den = 1
	}
	// Explicit float64 conversions stop the compiler from fusing a*b+c into an
	// FMA (arm64), which would change the rounding vs Python.
	xp := func(i int) float64 { return pl + float64((float64(i)/den)*iw) }
	yp := func(v float64) float64 { return (pt + ih) - float64(((v-minV)/rng)*ih) }
	f1 := func(f float64) string { return rptFixed(f, 1) }

	ptsParts := make([]string, n)
	for i, v := range values {
		ptsParts[i] = f1(xp(i)) + "," + f1(yp(v))
	}
	pts := strings.Join(ptsParts, " ")
	area := f1(xp(0)) + "," + f1(pt+ih) + " " + pts + " " + f1(xp(n-1)) + "," + f1(pt+ih)

	var grid strings.Builder
	const nTicks = 4
	for ti := 0; ti <= nTicks; ti++ {
		v := minV + float64(rng*float64(ti))/nTicks
		y := yp(v)
		var lbl string
		if math.Abs(v) >= 1000 {
			lbl = f1(v/1000) + "k"
		} else {
			lbl = f1(v)
		}
		grid.WriteString(`<line x1="` + strconv.Itoa(pl) + `" y1="` + f1(y) + `" x2="` + strconv.Itoa(w-pr) + `" y2="` + f1(y) + `"` +
			` class="chart-grid" stroke-dasharray="4,3"/>` +
			`<text x="` + strconv.Itoa(pl-5) + `" y="` + f1(y+4) + `" text-anchor="end"` +
			` font-size="10" class="chart-label">` + rptEscape(lbl) + `</text>`)
	}

	step := n / 8
	if step < 1 {
		step = 1
	}
	var xLabels strings.Builder
	for i, lbl := range labels {
		if i%step == 0 || i == n-1 {
			xLabels.WriteString(`<text x="` + f1(xp(i)) + `" y="` + strconv.Itoa(pt+int(ih)+18) + `" text-anchor="middle"` +
				` font-size="10" class="chart-label">` + rptEscape(lbl) + `</text>`)
		}
	}

	var dots strings.Builder
	if n <= 60 {
		for i, v := range values {
			dots.WriteString(`<circle cx="` + f1(xp(i)) + `" cy="` + f1(yp(v)) + `" r="2.5" fill="` + rptAccent + `"/>`)
		}
	}

	gid := "g" + chartID
	return `<svg viewBox="0 0 ` + strconv.Itoa(w) + ` ` + strconv.Itoa(h) + `" xmlns="http://www.w3.org/2000/svg"` +
		` style="width:100%;height:` + strconv.Itoa(h) + `px;display:block;">` +
		`<defs>` +
		`<linearGradient id="` + gid + `" x1="0" y1="0" x2="0" y2="1">` +
		`<stop offset="0%" stop-color="` + rptAccent + `" stop-opacity="0.25"/>` +
		`<stop offset="100%" stop-color="` + rptAccent + `" stop-opacity="0.02"/>` +
		`</linearGradient>` +
		`</defs>` +
		`<rect class="chart-bg" width="` + strconv.Itoa(w) + `" height="` + strconv.Itoa(h) + `"/>` +
		grid.String() +
		xLabels.String() +
		`<polygon points="` + area + `" fill="url(#` + gid + `)"/>` +
		`<polyline points="` + pts + `" fill="none" stroke="` + rptAccent + `" stroke-width="2"` +
		` stroke-linejoin="round" stroke-linecap="round"/>` +
		dots.String() +
		`<text x="` + rptFixed(pl+iw/2, 0) + `" y="` + strconv.Itoa(h-4) + `" text-anchor="middle"` +
		` font-size="11" class="chart-label">` + rptEscape(yLabel) + `</text>` +
		`</svg>`
}

// ── HTML building blocks ────────────────────────────────────────────────────

func rptKPICard(label, value, sub string) string {
	subHTML := ""
	if sub != "" {
		subHTML = `<div class="kpi-sub">` + rptEscape(sub) + `</div>`
	}
	return `<div class="kpi-card">` +
		`<div class="kpi-value">` + rptEscape(value) + `</div>` +
		`<div class="kpi-label">` + rptEscape(label) + `</div>` +
		subHTML +
		`</div>`
}

func rptTypeBadge(sourceType any) string {
	color, ok := rptTypeColors[jx.AsString(sourceType)]
	if !ok {
		color = rptMuted
	}
	return `<span class="badge" style="border-color:` + color + `;color:` + color + `">` +
		rptE(sourceType) + `</span>`
}

func rptStateBadge(state any) string {
	s, isStr := state.(string)
	color := rptAccent
	if isStr && s == "active" {
		color = rptGreen
	} else if isStr && s == "archived" {
		color = rptMuted
	}
	return `<span class="badge" style="border-color:` + color + `;color:` + color + `">` + rptE(state) + `</span>`
}

// ── section renderers ───────────────────────────────────────────────────────

func rptSectionResources(cc jx.M) string {
	resources := jx.GetMaps(cc, "resources")
	var rows strings.Builder
	for _, r := range resources {
		rows.WriteString("<tr><td class='td'>" + rptTypeBadge(jx.GetOr(r, "type", "")) + "</td>" +
			"<td class='td'>" + rptE(jx.GetOr(r, "name", "")) + "</td></tr>")
	}
	return "<details open class='section'>" +
		"<summary class='section-title'>Resources <span class='count'>(" + strconv.Itoa(len(jx.GetList(cc, "resources"))) + ")</span></summary>" +
		"<div class='table-wrap'><table class='table'>" +
		"<thead><tr><th>Type</th><th>Name</th></tr></thead>" +
		"<tbody>" + rows.String() + "</tbody></table></div>" +
		"</details>"
}

func rptSectionMembers(cc jx.M, webBase string) string {
	members := jx.GetMaps(cc, "members")
	var rows strings.Builder
	for _, m := range members {
		avatar := `<div class="avatar-placeholder"></div>`
		if jx.Truthy(m["avatar_url"]) {
			avatar = `<img src="` + rptE(m["avatar_url"]) + `" class="avatar" ` +
				`onerror="this.style.display='none'" />`
		}
		ghURL := m["html_url"]
		if !jx.Truthy(ghURL) {
			ghURL = webBase + "/" + rptPyStr(m["login"])
		}
		rows.WriteString("<tr>" +
			"<td class='td'><div class='user-cell'>" + avatar +
			"<a href='" + rptE(ghURL) + "' target='_blank' class='user-link'>" + rptE(m["login"]) + "</a></div></td>" +
			"<td class='td'>" + rptTypeBadge(jx.GetOr(m, "source_type", "")) + "</td>" +
			"<td class='td muted'>" + rptE(jx.GetOr(m, "source_name", "")) + "</td>" +
			"</tr>")
	}
	return "<details open class='section'>" +
		"<summary class='section-title'>Members <span class='count'>(" + strconv.Itoa(len(jx.GetList(cc, "members"))) + ")</span></summary>" +
		"<div class='table-wrap'><table class='table'>" +
		"<thead><tr><th>User</th><th>Source Type</th><th>Source Name</th></tr></thead>" +
		"<tbody>" + rows.String() + "</tbody></table></div>" +
		"</details>"
}

func rptDateStr(dr jx.M) string {
	return jx.AsString(jx.GetOr(dr, "start", "")) + " → " + jx.AsString(jx.GetOr(dr, "end", ""))
}

// rptFloatOr1 is Python “float(kpi.get(key, 1)) or 1“.
func rptFloatOr1(kpi jx.M, key string) float64 {
	f, _ := rptToFloat(jx.GetOr(kpi, key, 1.0))
	if f == 0 {
		return 1
	}
	return f
}

func rptShareCell(pct float64) string {
	return "<td class='td'>" +
		"<div class='pb-wrap'><div class='pb-fill' style='width:" + rptFixed(math.Min(pct, 100), 1) + "%'></div></div>" +
		"<span class='muted'>" + rptFixed(pct, 1) + "%</span></td>"
}

func rptSectionAIUsage(ai jx.M, chartID, webBase string) string {
	if !jx.GetBool(ai, "has_data") {
		return "<details open class='section'>" +
			"<summary class='section-title'>AI Usage Analysis</summary>" +
			"<p class='no-data'>No AI usage CSV data available for this cost center.</p>" +
			"</details>"
	}
	kpi := jx.GetMap(ai, "kpi")
	dateStr := rptDateStr(jx.GetMap(ai, "date_range"))

	kpiRow := "<div class='kpi-row'>" +
		rptKPICard("Total AI Credits", rptNum(jx.GetOr(kpi, "total_requests", 0)), "") +
		rptKPICard("Total Cost", rptMoney(jx.GetOr(kpi, "total_cost", 0)), "") +
		rptKPICard("Unique Users", rptNum(jx.GetOr(kpi, "unique_users", 0)), "") +
		rptKPICard("Date Range", dateStr, "") +
		"</div>"

	chart := rptSVGLineChart(jx.GetMaps(ai, "daily_trend"), "day", "requests", "Daily AI Credits", chartID+"pr")

	totalReq := rptFloatOr1(kpi, "total_requests")
	var modelRows strings.Builder
	for _, m := range jx.GetMaps(ai, "model_breakdown") {
		pct := jx.Round(jx.Float(m["requests"])/totalReq*100, 1)
		modelRows.WriteString("<tr>" +
			"<td class='td small'>" + rptE(m["model"]) + "</td>" +
			"<td class='td num'>" + rptNum(m["requests"]) + "</td>" +
			"<td class='td num'>" + rptMoney(m["amount"]) + "</td>" +
			"<td class='td num'>" + rptNum(m["user_count"]) + "</td>" +
			rptShareCell(pct) +
			"</tr>")
	}
	modelTable := "<h3 class='sub-title'>Model Breakdown</h3>" +
		"<div class='table-wrap'><table class='table'>" +
		"<thead><tr><th>Model</th><th class='num'>AI Credits</th>" +
		"<th class='num'>Cost</th><th class='num'>Users</th><th>Share</th></tr></thead>" +
		"<tbody>" + modelRows.String() + "</tbody></table></div>"

	var userRows strings.Builder
	for _, u := range jx.GetMaps(ai, "users") {
		topModel := any("—")
		if models := jx.GetMaps(u, "models"); jx.Truthy(u["models"]) && len(models) > 0 {
			topModel = models[0]["model"]
		}
		uname := u["user"]
		userRows.WriteString("<tr>" +
			"<td class='td'><a href='" + rptEscape(webBase) + "/" + rptE(uname) + "'" +
			" target='_blank' class='user-link'>" + rptE(uname) + "</a></td>" +
			"<td class='td muted small'>" + rptE(jx.GetOr(u, "org", "")) + "</td>" +
			"<td class='td num'>" + rptNum(u["requests"]) + "</td>" +
			"<td class='td num'>" + rptMoney(u["gross_amount"]) + "</td>" +
			"<td class='td num'>" + rptNum(jx.GetOr(u, "quota", 0)) + "</td>" +
			"<td class='td num'>" + rptPct(jx.GetOr(u, "usage_pct", 0)) + "</td>" +
			"<td class='td num'>" + rptPyStr(jx.GetOr(u, "days_active", 0)) + "</td>" +
			"<td class='td muted small'>" + rptE(topModel) + "</td>" +
			"</tr>")
	}
	userTable := "<h3 class='sub-title'>Per-User Details</h3>" +
		"<div class='table-wrap'><table class='table'>" +
		"<thead><tr><th>User</th><th>Org</th><th class='num'>AI Credits</th>" +
		"<th class='num'>Cost</th><th class='num'>Quota</th>" +
		"<th class='num'>Usage%</th><th class='num'>Active Days</th>" +
		"<th>Top Model</th></tr></thead>" +
		"<tbody>" + userRows.String() + "</tbody></table></div>"

	return "<details open class='section'>" +
		"<summary class='section-title'>💰 AI Usage Analysis</summary>" +
		kpiRow + "<div class='chart-wrap'>" + chart + "</div>" +
		modelTable + userTable +
		"</details>"
}

func rptSectionUsage(usage jx.M, chartID, webBase string) string {
	if !jx.GetBool(usage, "has_data") {
		return "<details open class='section'>" +
			"<summary class='section-title'>Usage Report Analysis</summary>" +
			"<p class='no-data'>No usage report CSV data available for this cost center.</p>" +
			"</details>"
	}
	kpi := jx.GetMap(usage, "kpi")
	dateStr := rptDateStr(jx.GetMap(usage, "date_range"))

	kpiRow := "<div class='kpi-row'>" +
		rptKPICard("Total Gross", rptMoney(jx.GetOr(kpi, "total_gross", 0)), "") +
		rptKPICard("Total Net", rptMoney(jx.GetOr(kpi, "total_net", 0)), "") +
		rptKPICard("Discount", rptMoney(jx.GetOr(kpi, "total_discount", 0)), "saved") +
		rptKPICard("Unique Users", rptNum(jx.GetOr(kpi, "unique_users", 0)), "") +
		rptKPICard("Date Range", dateStr, "") +
		"</div>"

	chart := rptSVGLineChart(jx.GetMaps(usage, "daily_trend"), "day", "gross_amount", "Daily Gross Amount ($)", chartID+"ur")

	totalGross := rptFloatOr1(kpi, "total_gross")
	var skuRows strings.Builder
	for _, s := range jx.GetMaps(usage, "sku_breakdown") {
		pct := jx.Round(jx.Float(s["gross_amount"])/totalGross*100, 1)
		skuRows.WriteString("<tr>" +
			"<td class='td small'>" + rptE(s["sku"]) + "</td>" +
			"<td class='td num'>" + rptMoney(s["gross_amount"]) + "</td>" +
			"<td class='td num'>" + rptMoney(s["net_amount"]) + "</td>" +
			"<td class='td num'>" + rptNum(s["user_count"]) + "</td>" +
			rptShareCell(pct) +
			"</tr>")
	}
	skuTable := "<h3 class='sub-title'>SKU Breakdown</h3>" +
		"<div class='table-wrap'><table class='table'>" +
		"<thead><tr><th>SKU</th><th class='num'>Gross</th>" +
		"<th class='num'>Net</th><th class='num'>Users</th><th>Share</th></tr></thead>" +
		"<tbody>" + skuRows.String() + "</tbody></table></div>"

	var userRows strings.Builder
	for _, u := range jx.GetMaps(usage, "users") {
		topSku := any("—")
		if skus := jx.GetMaps(u, "skus"); jx.Truthy(u["skus"]) && len(skus) > 0 {
			topSku = skus[0]["sku"]
		}
		uname := u["user"]
		userRows.WriteString("<tr>" +
			"<td class='td'><a href='" + rptEscape(webBase) + "/" + rptE(uname) + "'" +
			" target='_blank' class='user-link'>" + rptE(uname) + "</a></td>" +
			"<td class='td muted small'>" + rptE(jx.GetOr(u, "org", "")) + "</td>" +
			"<td class='td num'>" + rptMoney(u["gross_amount"]) + "</td>" +
			"<td class='td num'>" + rptMoney(u["net_amount"]) + "</td>" +
			"<td class='td num'>" + rptPyStr(jx.GetOr(u, "days_active", 0)) + "</td>" +
			"<td class='td muted small'>" + rptE(topSku) + "</td>" +
			"</tr>")
	}
	userTable := "<h3 class='sub-title'>Per-User Details</h3>" +
		"<div class='table-wrap'><table class='table'>" +
		"<thead><tr><th>User</th><th>Org</th><th class='num'>Gross</th>" +
		"<th class='num'>Net</th><th class='num'>Active Days</th>" +
		"<th>Top SKU</th></tr></thead>" +
		"<tbody>" + userRows.String() + "</tbody></table></div>"

	return "<details open class='section'>" +
		"<summary class='section-title'>📊 Usage Report Analysis</summary>" +
		kpiRow + "<div class='chart-wrap'>" + chart + "</div>" +
		skuTable + userTable +
		"</details>"
}

func rptSectionInsights(cc, ai jx.M, webBase string) string {
	hasAI := jx.GetBool(ai, "has_data")
	memberLogins := jx.StrSet{}
	for _, m := range jx.GetMaps(cc, "members") {
		memberLogins.Add(jx.Str(m["login"]))
	}
	aiUsers := jx.StrSet{}
	var allUsers []jx.M
	if hasAI {
		allUsers = jx.GetMaps(ai, "users")
		for _, u := range allUsers {
			aiUsers.Add(jx.Str(u["user"]))
		}
	}
	top5 := append([]jx.M(nil), allUsers...)
	sort.SliceStable(top5, func(i, j int) bool {
		return -jx.Float(jx.GetOr(top5[i], "gross_amount", 0)) < -jx.Float(jx.GetOr(top5[j], "gross_amount", 0))
	})
	if len(top5) > 5 {
		top5 = top5[:5]
	}
	var zeroAI []string
	if hasAI {
		for _, l := range memberLogins.Sorted() {
			if !aiUsers.Has(l) {
				zeroAI = append(zeroAI, l)
			}
		}
	}

	parts := []string{}
	if len(top5) > 0 {
		var rows strings.Builder
		for i, u := range top5 {
			uname := u["user"]
			rows.WriteString("<tr>" +
				"<td class='td num muted'>" + strconv.Itoa(i+1) + "</td>" +
				"<td class='td'><a href='" + rptEscape(webBase) + "/" + rptE(uname) + "'" +
				" target='_blank' class='user-link'>" + rptE(uname) + "</a></td>" +
				"<td class='td num'>" + rptMoney(u["gross_amount"]) + "</td>" +
				"<td class='td num'>" + rptNum(u["requests"]) + "</td>" +
				"<td class='td num'>" + rptPct(jx.GetOr(u, "usage_pct", 0)) + "</td>" +
				"</tr>")
		}
		parts = append(parts, "<div class='insight-card'>"+
			"<h3 class='sub-title'>🏆 Top 5 by AI Cost</h3>"+
			"<div class='table-wrap'><table class='table'>"+
			"<thead><tr><th>#</th><th>User</th><th class='num'>Cost</th>"+
			"<th class='num'>AI Credits</th><th class='num'>Quota%</th></tr></thead>"+
			"<tbody>"+rows.String()+"</tbody></table></div>"+
			"</div>")
	}
	if len(zeroAI) > 0 {
		tags := make([]string, len(zeroAI))
		for i, u := range zeroAI {
			tags[i] = "<a href='" + rptEscape(webBase) + "/" + rptEscape(u) + "' target='_blank' class='user-tag'>" + rptEscape(u) + "</a>"
		}
		plural := ""
		if len(zeroAI) != 1 {
			plural = "s"
		}
		parts = append(parts, "<div class='insight-card insight-warn'>"+
			"<h3 class='sub-title'>⚠️ Zero AI Usage ("+strconv.Itoa(len(zeroAI))+" member"+plural+")</h3>"+
			"<p class='insight-desc'>These cost center members had no AI usage activity "+
			"in the data period. Review their Copilot seat assignment.</p>"+
			"<div class='tag-list'>"+strings.Join(tags, " ")+"</div>"+
			"</div>")
	}
	if len(parts) == 0 {
		return ""
	}
	return "<details open class='section'>" +
		"<summary class='section-title'>🔍 Insights &amp; Analysis</summary>" +
		strings.Join(parts, "") +
		"</details>"
}

// ── CSS ─────────────────────────────────────────────────────────────────────

const rptCSS = `
/* ── Themes ── */
:root {
  --bg:#ffffff; --card:#f6f8fa; --card2:#eaeef2; --border:#d0d7de;
  --text:#1f2328; --muted:#6e7781; --accent:#0969da; --green:#1a7f37;
  --warn-border:rgba(207,34,46,.25); --hover:rgba(0,0,0,.04);
}
[data-theme="dark"] {
  --bg:#0d1117; --card:#161b22; --card2:#21262d; --border:#30363d;
  --text:#e6edf3; --muted:#768390; --accent:#539bf5; --green:#3fb950;
  --warn-border:rgba(214,83,35,.35); --hover:rgba(255,255,255,.03);
}

*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html{font-size:14px}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
  background:var(--bg);color:var(--text);line-height:1.5;min-height:100vh;
  transition:background .2s,color .2s}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}

/* ── Header ── */
.report-header{background:var(--card);border-bottom:1px solid var(--border);padding:24px 32px;
  transition:background .2s,border-color .2s}
.header-inner{max-width:1100px;margin:0 auto;display:flex;justify-content:space-between;
  align-items:flex-start;gap:24px;flex-wrap:wrap}
.header-brand{font-size:11px;text-transform:uppercase;letter-spacing:.08em;
  color:var(--muted);margin-bottom:6px}
.header-title{font-size:24px;font-weight:700;margin-bottom:8px}
.header-meta{display:flex;align-items:center;gap:12px;flex-wrap:wrap;font-size:13px;color:var(--muted)}
.header-right{text-align:right;flex-shrink:0}
.header-cost-label{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}
.header-cost-value{font-size:32px;font-weight:700;color:var(--text);margin:4px 0}
.header-gen{font-size:11px;color:var(--muted)}

/* ── Theme toggle ── */
.theme-btn{margin-top:10px;padding:5px 12px;border-radius:6px;border:1px solid var(--border);
  background:var(--card2);color:var(--text);font-size:12px;cursor:pointer;
  transition:background .2s,border-color .2s,color .2s}
.theme-btn:hover{border-color:var(--accent);color:var(--accent)}

/* ── Layout ── */
.main-content{max-width:1100px;margin:0 auto;padding:24px 32px;display:flex;
  flex-direction:column;gap:16px}

/* ── Sections ── */
details.section{background:var(--card);border:1px solid var(--border);border-radius:8px;
  overflow:hidden;transition:background .2s,border-color .2s}
details.section[open] summary.section-title{border-bottom:1px solid var(--border)}
summary.section-title{display:flex;align-items:center;gap:8px;padding:14px 18px;
  font-size:15px;font-weight:600;cursor:pointer;list-style:none;user-select:none}
summary.section-title::-webkit-details-marker{display:none}
summary.section-title::before{content:"▶";font-size:10px;color:var(--muted);
  transition:transform .2s;display:inline-block}
details[open] summary.section-title::before{transform:rotate(90deg)}
.count{font-size:12px;color:var(--muted);font-weight:400}
.section > *:not(summary){padding:16px 18px}

/* ── KPI ── */
.kpi-row{display:flex;flex-wrap:wrap;gap:12px;margin-bottom:16px}
.kpi-card{background:var(--card2);border:1px solid var(--border);border-radius:6px;
  padding:14px 18px;min-width:130px;flex:1;transition:background .2s,border-color .2s}
.kpi-value{font-size:22px;font-weight:700;line-height:1.2}
.kpi-label{font-size:11px;color:var(--muted);margin-top:4px;text-transform:uppercase;letter-spacing:.05em}
.kpi-sub{font-size:11px;color:var(--green);margin-top:2px}

/* ── Tables ── */
.table-wrap{overflow-x:auto}
.table{width:100%;border-collapse:collapse;font-size:13px}
.table thead tr{background:var(--card2);border-bottom:1px solid var(--border)}
.table th{padding:8px 12px;text-align:left;font-weight:600;color:var(--muted);
  font-size:11px;text-transform:uppercase;letter-spacing:.05em;white-space:nowrap}
.table th.num{text-align:right}
.table td.td{padding:8px 12px;border-bottom:1px solid var(--border);vertical-align:middle}
.table td.num{text-align:right;font-variant-numeric:tabular-nums}
.table tbody tr:last-child td{border-bottom:none}
.table tbody tr:hover{background:var(--hover)}
.small{font-size:12px}
.muted{color:var(--muted)}

/* ── User cell ── */
.user-cell{display:flex;align-items:center;gap:8px}
.avatar{width:22px;height:22px;border-radius:50%;vertical-align:middle}
.avatar-placeholder{width:22px;height:22px;border-radius:50%;background:var(--border)}
.user-link{color:var(--accent)}

/* ── Badge ── */
.badge{display:inline-block;font-size:11px;font-weight:500;padding:1px 7px;
  border-radius:12px;border:1px solid;white-space:nowrap}

/* ── Progress bar ── */
.pb-wrap{display:inline-block;width:80px;height:6px;background:var(--border);
  border-radius:3px;vertical-align:middle;margin-right:6px}
.pb-fill{height:100%;background:var(--accent);border-radius:3px}

/* ── Chart ── */
.chart-wrap{border:1px solid var(--border);border-radius:6px;overflow:hidden;
  margin-bottom:16px;background:var(--bg);transition:background .2s,border-color .2s}
.chart-bg{fill:var(--bg);transition:fill .2s}
.chart-grid{stroke:var(--border)}
.chart-label{fill:var(--muted)}

/* ── Sub-titles ── */
.sub-title{font-size:13px;font-weight:600;color:var(--muted);text-transform:uppercase;
  letter-spacing:.06em;margin:16px 0 10px}

/* ── Insights ── */
.insight-card{background:var(--card2);border:1px solid var(--border);border-radius:6px;
  padding:16px;margin-bottom:12px;transition:background .2s,border-color .2s}
.insight-card:last-child{margin-bottom:0}
.insight-warn{border-color:var(--warn-border)}
.insight-desc{font-size:13px;color:var(--muted);margin:6px 0 10px}
.tag-list{display:flex;flex-wrap:wrap;gap:8px}
.user-tag{display:inline-block;padding:2px 10px;border-radius:12px;
  border:1px solid var(--border);font-size:12px;color:var(--accent)}
.user-tag:hover{border-color:var(--accent)}

/* ── No data ── */
.no-data{color:var(--muted);font-size:13px;padding:8px 0}

/* ── Footer ── */
.report-footer{max-width:1100px;margin:16px auto;padding:0 32px 32px;
  font-size:11px;color:var(--muted)}
`

// ── main HTML renderer ──────────────────────────────────────────────────────

func rptRenderHTML(enterprise, enterpriseName string, cc, ai, usage jx.M, generatedAt, chartID, downloadURL, webBase string) string {
	name := jx.GetOr(cc, "name", "Unknown")
	state := jx.GetOr(cc, "state", "active")
	memberCount := jx.GetOr(cc, "member_count", len(jx.GetList(cc, "members")))

	allDates := []string{}
	for _, sect := range []jx.M{ai, usage} {
		dr := jx.GetMap(sect, "date_range")
		for _, k := range []string{"start", "end"} {
			if jx.Truthy(dr[k]) {
				allDates = append(allDates, jx.Str(dr[k]))
			}
		}
	}
	dateRangeStr := "No data"
	if lo, hi, ok := rptMinMaxAll(allDates); ok {
		dateRangeStr = lo + " → " + hi
	}

	totalCost := 0.0
	if jx.GetBool(ai, "has_data") {
		totalCost += jx.Float(jx.GetMap(ai, "kpi")["total_cost"])
	}
	if jx.GetBool(usage, "has_data") {
		totalCost += jx.Float(jx.GetMap(usage, "kpi")["total_gross"])
	}

	downloadBtn := ""
	if downloadURL != "" {
		downloadBtn = `<a class="theme-btn" style="text-decoration:none;display:inline-block;` +
			`margin-left:8px" href="` + rptEscape(downloadURL) + `">` + "⬇" + ` Download</a>`
	}
	entLabel := enterpriseName
	if entLabel == "" {
		entLabel = enterprise
	}

	var b strings.Builder
	b.Grow(64 << 10)
	b.WriteString(`<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Cost Center Report · ` + rptE(name) + `</title>
<style>` + rptCSS + `</style>
<script>
(function(){
  var t = localStorage.getItem('report-theme');
  if (t === 'dark') document.documentElement.setAttribute('data-theme', 'dark');
})();
</script>
</head>
<body>
<header class="report-header">
  <div class="header-inner">
    <div class="header-left">
      <div class="header-brand">OctoFinance · Cost Center Report</div>
      <h1 class="header-title">` + rptE(name) + `</h1>
      <div class="header-meta">
        <span>Enterprise: <strong>` + rptEscape(entLabel) + `</strong></span>
        ` + rptStateBadge(state) + `
        <span>` + rptE(memberCount) + ` members</span>
        <span>Period: ` + rptEscape(dateRangeStr) + `</span>
      </div>
    </div>
    <div class="header-right">
      <div class="header-cost-label">Total Cost</div>
      <div class="header-cost-value">` + rptMoney(totalCost) + `</div>
      <div class="header-gen">Generated ` + rptEscape(generatedAt) + `</div>
      <button id="theme-btn" class="theme-btn" onclick="toggleTheme()">🌙 Dark</button>` + downloadBtn + `
    </div>
  </div>
</header>

<main class="main-content">
  ` + rptSectionResources(cc) + `
  ` + rptSectionMembers(cc, webBase) + `
  ` + rptSectionAIUsage(ai, chartID, webBase) + `
  ` + rptSectionUsage(usage, chartID, webBase) + `
  ` + rptSectionInsights(cc, ai, webBase) + `
</main>

<footer class="report-footer">
  Generated by <strong>OctoFinance</strong> on ` + rptEscape(generatedAt) + ` ·
  Enterprise: ` + rptEscape(entLabel) + ` · Cost Center: ` + rptE(name) + `
</footer>
<script>
function toggleTheme() {
  var d = document.documentElement;
  var isDark = d.getAttribute('data-theme') === 'dark';
  d.setAttribute('data-theme', isDark ? '' : 'dark');
  document.getElementById('theme-btn').textContent = isDark ? '🌙 Dark' : '☀️ Light';
  localStorage.setItem('report-theme', isDark ? '' : 'dark');
}
(function() {
  var isDark = document.documentElement.getAttribute('data-theme') === 'dark';
  document.getElementById('theme-btn').textContent = isDark ? '☀️ Light' : '🌙 Dark';
})();
</script>
</body>
</html>`)
	return b.String()
}

// rptMinMaxAll is min()/max() over strings (empty strings included).
func rptMinMaxAll(values []string) (string, string, bool) {
	if len(values) == 0 {
		return "", "", false
	}
	lo, hi := values[0], values[0]
	for _, v := range values[1:] {
		if v < lo {
			lo = v
		}
		if v > hi {
			hi = v
		}
	}
	return lo, hi, true
}

// rptFilterByCC is “[r for r in records if r.get("cost_center_name") == cc_name]“.
func rptFilterByCC(records []CSVRecord, ccName any) []CSVRecord {
	out := []CSVRecord{}
	name, isStr := ccName.(string)
	for _, r := range records {
		v, ok := r["cost_center_name"]
		if (ok && isStr && v == name) || (!ok && ccName == nil) {
			out = append(out, r)
		}
	}
	return out
}

func rptGeneratedAt() string {
	return time.Now().UTC().Format("2006-01-02 15:04") + " UTC"
}

func rptWebBase(webBase string) string {
	if webBase == "" {
		return githost.WebBase(githost.DefaultHost)
	}
	return webBase
}

// GenerateSingleReportHTML renders one cost center report (Python generate_single_report_html).
// downloadURL "" means no Download button.
func GenerateSingleReportHTML(enterprise, enterpriseName string, cc jx.M, aiRecords, usageRecords []CSVRecord, downloadURL, webBase string) string {
	generatedAt := rptGeneratedAt()
	ccName := jx.GetOr(cc, "name", "")
	return rptRenderHTML(enterprise, enterpriseName, cc,
		BuildAIUsageSection(rptFilterByCC(aiRecords, ccName)),
		BuildUsageSection(rptFilterByCC(usageRecords, ccName)),
		generatedAt, "0", downloadURL, rptWebBase(webBase))
}

// GenerateReportZip returns a ZIP with one HTML report per cost center (Python generate_report_zip).
func GenerateReportZip(enterprise, enterpriseName string, costCenters []jx.M, aiRecords, usageRecords []CSVRecord, webBase string) ([]byte, error) {
	generatedAt := rptGeneratedAt()
	webBase = rptWebBase(webBase)
	var buf bytes.Buffer
	zw := zip.NewWriter(&buf)
	now := time.Now()
	for idx, cc := range costCenters {
		ccName := jx.GetOr(cc, "name", "cc_"+strconv.Itoa(idx))
		html := rptRenderHTML(enterprise, enterpriseName, cc,
			BuildAIUsageSection(rptFilterByCC(aiRecords, ccName)),
			BuildUsageSection(rptFilterByCC(usageRecords, ccName)),
			generatedAt, strconv.Itoa(idx), "", webBase)
		safe := strings.NewReplacer("/", "_", "\\", "_", " ", "_", ":", "_").Replace(jx.Str(ccName))
		w, err := zw.CreateHeader(&zip.FileHeader{Name: safe + ".html", Method: zip.Deflate, Modified: now})
		if err != nil {
			return nil, err
		}
		if _, err := w.Write([]byte(html)); err != nil {
			return nil, err
		}
	}
	if err := zw.Close(); err != nil {
		return nil, err
	}
	return buf.Bytes(), nil
}
