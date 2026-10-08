package app

import (
	"context"
	"fmt"
	"io"
	"sort"
	"strconv"
	"strings"

	"github.com/satomic/octofinance/backend-go/internal/jx"
)

// CSV dashboard + CSV ingestion endpoints (Python routers/data.py).

func dataCSVDashboard(c *Ctx) any {
	selectedOrgs := dataSplitCSV(c.Query("orgs", ""))
	selectedCCs := dataSplitCSV(c.Query("cost_centers", ""))
	selectedProducts := dataSplitCSV(c.Query("products", ""))
	selectedSKUs := dataSplitCSV(c.Query("skus", ""))
	dateFrom := c.Query("date_from", "")
	dateTo := c.Query("date_to", "")
	enterpriseTeam := c.Query("enterprise_team", "")
	selectedUser := strings.TrimSpace(c.Query("user", ""))

	l := newDataLoader()
	teamFilter := dataTeamMemberLogins(l, enterpriseTeam)
	memberFilter := dataWithUserFilter(teamFilter, selectedUser)

	allAI := LoadAllCSVRecords(CSVTypeAI)
	allUsage := LoadAllCSVRecords(CSVTypeUsage)
	aiUsage := dataBuildAIUsageSection(allAI, selectedOrgs, selectedCCs, dateFrom, dateTo, memberFilter)
	usage := dataBuildUsageReportSection(allUsage, selectedOrgs, selectedCCs, selectedProducts, selectedSKUs, dateFrom, dateTo, memberFilter)

	orgs, ccs, products, skus := jx.StrSet{}, jx.StrSet{}, jx.StrSet{}, jx.StrSet{}
	users := newDataOM[string]()
	collectUser := func(name string) {
		if name == "" {
			return
		}
		key := strings.ToLower(name)
		if teamFilter != nil && !teamFilter.has(key) {
			return
		}
		users.at(key, func() string { return name })
	}
	for _, r := range allAI {
		if v := r["organization"]; v != "" {
			orgs.Add(v)
		}
		if v := r["cost_center_name"]; v != "" {
			ccs.Add(v)
		}
		collectUser(r["username"])
	}
	for _, r := range allUsage {
		if v := r["organization"]; v != "" {
			orgs.Add(v)
		}
		if v := r["cost_center_name"]; v != "" {
			ccs.Add(v)
		}
		if v := r["product"]; v != "" {
			products.Add(v)
		}
		if v := r["sku"]; v != "" {
			skus.Add(v)
		}
		collectUser(r["username"])
	}
	userList := []string{}
	for _, k := range users.keys {
		userList = append(userList, users.m[k])
	}
	dataSortLower(userList)

	var selTeam, selUser any
	if enterpriseTeam != "" {
		selTeam = enterpriseTeam
	}
	if selectedUser != "" {
		selUser = selectedUser
	}
	return jx.M{
		"ai_usage":                 aiUsage,
		"usage_report":             usage,
		"selected_enterprise_team": selTeam,
		"selected_user":            selUser,
		"filters": jx.M{
			"orgs":             orgs.Sorted(),
			"cost_centers":     ccs.Sorted(),
			"products":         products.Sorted(),
			"skus":             skus.Sorted(),
			"users":            userList,
			"enterprise_teams": dataEnterpriseTeamOptions(l),
		},
	}
}

func dataApplyCommonFilters(records []CSVRecord, orgs, ccs []string, from, to string, filter *dataMemberFilter) []CSVRecord {
	out := make([]CSVRecord, 0, len(records))
	for _, r := range records {
		if len(orgs) > 0 && !dataContains(orgs, dataRec(r, "organization", "")) {
			continue
		}
		if len(ccs) > 0 && !dataContains(ccs, r["cost_center_name"]) {
			continue
		}
		if filter != nil && !filter.has(strings.ToLower(r["username"])) {
			continue
		}
		if from != "" && dataRec(r, "date", "") < from {
			continue
		}
		if to != "" && dataRec(r, "date", "") > to {
			continue
		}
		out = append(out, r)
	}
	return out
}

// dataRecFloat is “float(r.get(key, 0))“.
func dataRecFloat(r CSVRecord, key string) float64 {
	v, ok := r[key]
	if !ok {
		return 0
	}
	return jx.Float(v)
}

func dataDateRange(records []CSVRecord) jx.M {
	dates := []string{}
	for _, r := range records {
		if d := r["date"]; d != "" {
			dates = append(dates, d)
		}
	}
	lo, hi, _ := jx.MinMax(dates)
	return jx.M{"start": lo, "end": hi}
}

// dataAIGroup is a {requests, amount, users} bucket with token metrics.
type dataAIGroup struct {
	requests, amount float64
	users            jx.StrSet
	metrics          jx.M
}

func newDataAIGroup() *dataAIGroup { return &dataAIGroup{users: jx.StrSet{}, metrics: jx.M{}} }

func (g *dataAIGroup) add(r CSVRecord) {
	AddAIUsageMetrics(g.metrics, r)
	g.requests += dataRecFloat(r, "quantity")
	g.amount += dataRecFloat(r, "gross_amount")
	g.users.Add(dataRec(r, "username", ""))
}

func dataAIGroupRows(om *dataOM[*dataAIGroup], label string, countKey string, byRequests bool) jx.L {
	keys := om.keys
	if byRequests {
		keys = om.sortedKeysBy(func(a, b *dataAIGroup) bool { return a.requests > b.requests })
	} else {
		keys = append([]string{}, keys...)
		sort.Strings(keys)
	}
	out := jx.L{}
	for _, k := range keys {
		g := om.m[k]
		row := jx.M{label: k, "requests": jx.Round(g.requests, 2), "amount": jx.Round(g.amount, 4), countKey: len(g.users)}
		for _, f := range AIUsageMetricFields {
			row[f] = g.metrics[f]
		}
		out = append(out, row)
	}
	return out
}

func dataEmptyAISection() jx.M {
	return jx.M{"has_data": false, "date_range": jx.M{}, "kpi": jx.M{}, "daily_trend": jx.L{},
		"model_breakdown": jx.L{}, "org_breakdown": jx.L{}, "cost_center_breakdown": jx.L{}, "users": jx.L{}}
}

func dataBuildAIUsageSection(all []CSVRecord, orgs, ccs []string, from, to string, filter *dataMemberFilter) jx.M {
	if len(all) == 0 {
		return dataEmptyAISection()
	}
	filtered := dataApplyCommonFilters(all, orgs, ccs, from, to, filter)
	if len(filtered) == 0 {
		return dataEmptyAISection()
	}

	type userInfo struct {
		requests, gross, net float64
		models               *dataOM[*float64]
		days                 jx.StrSet
		org, costCenter      string
		quota                int
		metrics              jx.M
	}
	userMap := newDataOM[*userInfo]()
	metricTotals := jx.M{}
	dayMap := newDataOM[*dataAIGroup]()
	modelMap := newDataOM[*dataAIGroup]()
	orgMap := newDataOM[*dataAIGroup]()
	ccMap := newDataOM[*dataAIGroup]()
	for _, r := range filtered {
		qty := dataRecFloat(r, "quantity")
		u := userMap.at(dataRec(r, "username", ""), func() *userInfo {
			return &userInfo{models: newDataOM[*float64](), days: jx.StrSet{}, metrics: jx.M{}}
		})
		AddAIUsageMetrics(u.metrics, r)
		AddAIUsageMetrics(metricTotals, r)
		u.requests += qty
		u.gross += dataRecFloat(r, "gross_amount")
		u.net += dataRecFloat(r, "net_amount")
		*u.models.at(dataRec(r, "model", "unknown"), func() *float64 { return new(float64) }) += qty
		u.days.Add(dataRec(r, "date", ""))
		u.org = dataRec(r, "organization", "")
		u.costCenter = r["cost_center_name"]
		if raw, ok := r["total_monthly_quota"]; ok {
			if q, err := strconv.Atoi(strings.TrimSpace(raw)); err == nil {
				u.quota = q
			}
		} else {
			u.quota = 0
		}

		dayMap.at(dataRec(r, "date", ""), newDataAIGroup).add(r)
		modelMap.at(dataRec(r, "model", "unknown"), newDataAIGroup).add(r)
		orgMap.at(dataRec(r, "organization", ""), newDataAIGroup).add(r)
		cc := r["cost_center_name"]
		if cc == "" {
			cc = "Unknown"
		}
		ccMap.at(cc, newDataAIGroup).add(r)
	}

	users := jx.L{}
	totalRequests, totalCost := 0.0, 0.0
	for _, name := range userMap.sortedKeysBy(func(a, b *userInfo) bool { return a.requests > b.requests }) {
		info := userMap.m[name]
		models := jx.L{}
		for _, m := range info.models.sortedKeysBy(func(a, b *float64) bool { return *a > *b }) {
			models = append(models, jx.M{"model": m, "requests": *info.models.m[m]})
		}
		var usagePct any = 0
		if info.quota > 0 {
			usagePct = jx.Round(info.requests/float64(info.quota)*100, 1)
		}
		row := jx.M{
			"user": name, "org": info.org, "cost_center": info.costCenter,
			"requests": jx.Round(info.requests, 2), "gross_amount": jx.Round(info.gross, 4),
			"net_amount": jx.Round(info.net, 4), "days_active": len(info.days),
			"quota": info.quota, "usage_pct": usagePct, "models": models,
		}
		for _, f := range AIUsageMetricFields {
			row[f] = info.metrics[f]
		}
		totalRequests += jx.Round(info.requests, 2)
		totalCost += jx.Round(info.gross, 4)
		users = append(users, row)
	}

	dailyTrend := jx.L{}
	days := append([]string{}, dayMap.keys...)
	sort.Strings(days)
	for _, d := range days {
		g := dayMap.m[d]
		row := jx.M{"day": d, "requests": jx.Round(g.requests, 2), "amount": jx.Round(g.amount, 4), "active_users": len(g.users)}
		for _, f := range AIUsageMetricFields {
			row[f] = g.metrics[f]
		}
		dailyTrend = append(dailyTrend, row)
	}
	orgBreakdown := dataAIGroupRows(orgMap, "org", "user_count", true)

	kpi := jx.M{
		"total_requests": jx.Round(totalRequests, 2),
		"total_cost":     jx.Round(totalCost, 4),
		"unique_users":   len(users),
		"unique_orgs":    len(orgBreakdown),
	}
	for k, v := range metricTotals {
		kpi[k] = v
	}
	return jx.M{
		"has_data":              true,
		"date_range":            dataDateRange(filtered),
		"kpi":                   kpi,
		"daily_trend":           dailyTrend,
		"model_breakdown":       dataAIGroupRows(modelMap, "model", "user_count", true),
		"org_breakdown":         orgBreakdown,
		"cost_center_breakdown": dataAIGroupRows(ccMap, "cost_center", "user_count", true),
		"users":                 users,
	}
}

func dataEmptyUsageSection() jx.M {
	return jx.M{"has_data": false, "date_range": jx.M{}, "kpi": jx.M{}, "daily_trend": jx.L{},
		"product_breakdown": jx.L{}, "sku_breakdown": jx.L{}, "org_breakdown": jx.L{},
		"cost_center_breakdown": jx.L{}, "users": jx.L{}}
}

type dataMoneyGroup struct {
	gross, net, quantity float64
	users                jx.StrSet
}

func newDataMoneyGroup() *dataMoneyGroup { return &dataMoneyGroup{users: jx.StrSet{}} }

func (g *dataMoneyGroup) add(r CSVRecord) {
	g.gross += dataRecFloat(r, "gross_amount")
	g.net += dataRecFloat(r, "net_amount")
	g.quantity += dataRecFloat(r, "quantity")
	g.users.Add(dataRec(r, "username", ""))
}

func dataMoneyRows(om *dataOM[*dataMoneyGroup], label string, withQuantity bool) jx.L {
	out := jx.L{}
	for _, k := range om.sortedKeysBy(func(a, b *dataMoneyGroup) bool { return a.gross > b.gross }) {
		g := om.m[k]
		row := jx.M{label: k, "gross_amount": jx.Round(g.gross, 4), "net_amount": jx.Round(g.net, 4), "user_count": len(g.users)}
		if withQuantity {
			row["quantity"] = jx.Round(g.quantity, 4)
		}
		out = append(out, row)
	}
	return out
}

func dataBuildUsageReportSection(all []CSVRecord, orgs, ccs, products, skus []string, from, to string, filter *dataMemberFilter) jx.M {
	if len(all) == 0 {
		return dataEmptyUsageSection()
	}
	filtered := dataApplyCommonFilters(all, orgs, ccs, from, to, filter)
	if len(products) > 0 || len(skus) > 0 {
		kept := filtered[:0:0]
		for _, r := range filtered {
			if len(products) > 0 && !dataContains(products, dataRec(r, "product", "")) {
				continue
			}
			if len(skus) > 0 && !dataContains(skus, dataRec(r, "sku", "")) {
				continue
			}
			kept = append(kept, r)
		}
		filtered = kept
	}
	if len(filtered) == 0 {
		return dataEmptyUsageSection()
	}

	type userInfo struct {
		gross, net, quantity float64
		org, costCenter      string
		skus                 *dataOM[*float64]
		days                 jx.StrSet
	}
	dayMap := newDataOM[*dataMoneyGroup]()
	prodMap := newDataOM[*dataMoneyGroup]()
	skuMap := newDataOM[*dataMoneyGroup]()
	orgMap := newDataOM[*dataMoneyGroup]()
	ccMap := newDataOM[*dataMoneyGroup]()
	userMap := newDataOM[*userInfo]()
	var totalGross, totalNet, totalDiscount float64
	for _, r := range filtered {
		gross := dataRecFloat(r, "gross_amount")
		dayMap.at(dataRec(r, "date", ""), newDataMoneyGroup).add(r)
		prodMap.at(dataRec(r, "product", "unknown"), newDataMoneyGroup).add(r)
		skuMap.at(dataRec(r, "sku", "unknown"), newDataMoneyGroup).add(r)
		orgMap.at(dataRec(r, "organization", ""), newDataMoneyGroup).add(r)
		cc := r["cost_center_name"]
		if cc == "" {
			cc = "Unknown"
		}
		ccMap.at(cc, newDataMoneyGroup).add(r)

		u := userMap.at(dataRec(r, "username", ""), func() *userInfo {
			return &userInfo{skus: newDataOM[*float64](), days: jx.StrSet{}}
		})
		u.gross += gross
		u.net += dataRecFloat(r, "net_amount")
		u.quantity += dataRecFloat(r, "quantity")
		u.org = dataRec(r, "organization", "")
		u.costCenter = r["cost_center_name"]
		*u.skus.at(dataRec(r, "sku", "unknown"), func() *float64 { return new(float64) }) += gross
		u.days.Add(dataRec(r, "date", ""))

		totalGross += gross
		totalNet += dataRecFloat(r, "net_amount")
		totalDiscount += dataRecFloat(r, "discount_amount")
	}

	dailyTrend := jx.L{}
	days := append([]string{}, dayMap.keys...)
	sort.Strings(days)
	for _, d := range days {
		g := dayMap.m[d]
		dailyTrend = append(dailyTrend, jx.M{"day": d, "gross_amount": jx.Round(g.gross, 4),
			"net_amount": jx.Round(g.net, 4), "active_users": len(g.users)})
	}

	users := jx.L{}
	for _, name := range userMap.sortedKeysBy(func(a, b *userInfo) bool { return a.gross > b.gross }) {
		info := userMap.m[name]
		skuRows := jx.L{}
		for _, s := range info.skus.sortedKeysBy(func(a, b *float64) bool { return *a > *b }) {
			skuRows = append(skuRows, jx.M{"sku": s, "amount": jx.Round(*info.skus.m[s], 4)})
		}
		users = append(users, jx.M{
			"user": name, "org": info.org, "cost_center": info.costCenter,
			"gross_amount": jx.Round(info.gross, 4), "net_amount": jx.Round(info.net, 4),
			"quantity": jx.Round(info.quantity, 4), "days_active": len(info.days),
			"skus": skuRows,
		})
	}
	orgBreakdown := dataMoneyRows(orgMap, "org", false)
	return jx.M{
		"has_data":   true,
		"date_range": dataDateRange(filtered),
		"kpi": jx.M{
			"total_gross":    jx.Round(totalGross, 4),
			"total_net":      jx.Round(totalNet, 4),
			"total_discount": jx.Round(totalDiscount, 4),
			"unique_users":   len(users),
			"unique_orgs":    len(orgBreakdown),
		},
		"daily_trend":           dailyTrend,
		"product_breakdown":     dataMoneyRows(prodMap, "product", true),
		"sku_breakdown":         dataMoneyRows(skuMap, "sku", true),
		"org_breakdown":         orgBreakdown,
		"cost_center_breakdown": dataMoneyRows(ccMap, "cost_center", false),
		"users":                 users,
	}
}

// ---------------------------------------------------------------------------
// CSV ingestion
// ---------------------------------------------------------------------------

func dataUploadCSV(c *Ctx) any {
	missing := JSONStatus(422, jx.M{"detail": jx.L{jx.M{
		"type": "missing", "loc": jx.L{"body", "file"}, "msg": "Field required", "input": nil,
	}}})
	if err := c.R.ParseMultipartForm(64 << 20); err != nil {
		return missing
	}
	f, hdr, err := c.R.FormFile("file")
	if err != nil {
		return missing
	}
	defer f.Close()
	if hdr.Filename == "" || !strings.HasSuffix(hdr.Filename, ".csv") {
		return jx.M{"error": "Only CSV files are accepted."}
	}
	content, err := io.ReadAll(f)
	if err != nil {
		panic(err)
	}
	return IngestCSVText(strings.TrimPrefix(string(content), "\xef\xbb\xbf"))
}

type dataFetchCSVReq struct {
	Enterprise string    `json:"enterprise"`
	StartDate  string    `json:"start_date"`
	EndDate    string    `json:"end_date"`
	CSVTypes   *[]string `json:"csv_types"`
}

func dataFetchCSV(c *Ctx) any {
	var req dataFetchCSVReq
	if r := c.Bind(&req); r != nil {
		return r
	}
	requested := AllCSVTypes
	if req.CSVTypes != nil {
		requested = *req.CSVTypes
	}
	csvTypes := []string{}
	for _, t := range requested {
		if dataContains(AllCSVTypes, t) {
			csvTypes = append(csvTypes, t)
		}
	}
	if len(csvTypes) == 0 {
		quoted := []string{}
		for _, t := range AllCSVTypes {
			quoted = append(quoted, "'"+t+"'")
		}
		return jx.M{"status": "error", "error": fmt.Sprintf("csv_types must be a subset of [%s].", strings.Join(quoted, ", "))}
	}
	var enterprises []string
	if req.Enterprise != "" {
		enterprises = []string{req.Enterprise}
	} else {
		enterprises = CSVResolveEnterprises()
	}
	if len(enterprises) == 0 {
		return jx.M{"status": "error", "error": "No enterprise is configured. " +
			"This report is only available at enterprise level."}
	}
	defStart, defEnd := CSVDefaultDateRange()
	start := req.StartDate
	if start == "" {
		start = defStart
	}
	end := req.EndDate
	if end == "" {
		end = defEnd
	}
	if msg := CSVValidateDateRange(start, end); msg != "" {
		return jx.M{"status": "error", "error": msg}
	}
	if Syncs.IsSyncing() {
		return jx.M{"status": "already_syncing"}
	}
	job := CSVBeginJob(enterprises, start, end, csvTypes)
	Syncs.RunInBackground(func(ctx context.Context, logFn LogFn) {
		CSVFetchAndIngest(ctx, enterprises, start, end, csvTypes, logFn)
	}, "manual")
	return jx.M{
		"status":      "started",
		"job_id":      job["job_id"],
		"enterprises": enterprises,
		"csv_types":   csvTypes,
		"date_range":  jx.M{"start": start, "end": end},
	}
}
