package app

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"time"

	"github.com/satomic/octofinance/backend-go/internal/ghapi"
	"github.com/satomic/octofinance/backend-go/internal/jx"
)

// LogFn receives sync progress: level ("info", "warn", "error") and message.
type LogFn func(level, message string)

func (l LogFn) log(level, msg string) {
	if l != nil {
		l(level, msg)
	}
}

var snapshotNameRE = regexp.MustCompile(`.*_\d{8}_\d{6}\.json$`)

// emptyResultLog explains why a fetch produced no data.
// role is the PAT owner's role in an org scope ("member", "admin" or "" when unknown).
func emptyResultLog(api *ghapi.Client, scope, dataset, role string) (string, string) {
	failure := api.ConsumeFailure()
	if failure == nil {
		return "info", fmt.Sprintf("  %s: %s returned nothing (not enabled for this scope)", scope, dataset)
	}
	status := jx.Int(failure["status"])
	detail := strings.TrimSpace(jx.Str(failure["detail"]))
	// The PAT owner is only a member of this org: Copilot data needs an org
	// owner (or a role with Copilot access), and no token scope can grant that.
	// Expected, so report it without failing the sync.
	if status == 403 && role == "member" {
		parts := []string{fmt.Sprintf("  %s: %s skipped", scope, dataset), "HTTP 403"}
		if detail != "" {
			parts = append(parts, detail)
		}
		parts = append(parts, "the PAT owner is a member, not an owner, of this organization; "+
			"make them an organization owner (or use an owner's PAT) to sync its Copilot data")
		return "warn", strings.Join(parts, " | ")
	}
	level := "warn"
	if status == 401 || status == 403 {
		level = "error"
	}
	parts := []string{fmt.Sprintf("  %s: %s unavailable", scope, dataset)}
	if status != 0 {
		parts = append(parts, fmt.Sprintf("HTTP %d", status))
	}
	if detail != "" {
		parts = append(parts, detail)
	}
	if status == 401 || status == 403 {
		parts = append(parts, "check the PAT and its scopes")
	}
	return level, strings.Join(parts, " | ")
}

// EnterprisePseudoOrg is the pseudo-org key for enterprise-level Copilot data.
func EnterprisePseudoOrg(slug string) string { return slug + "-enterprise" }

// ---------------------------------------------------------------------------
// `_latest.json` merge strategies: day-granular categories merge new data into
// the stored file so history outlives GitHub's rolling 28-day window.
// ---------------------------------------------------------------------------

func mergeUsageReport(oldData, newData any) any {
	newM := jx.Map(newData)
	if newM == nil {
		return newData
	}
	oldM := jx.Map(oldData)
	if oldM == nil || !jx.Truthy(oldM["records"]) {
		return newData
	}
	collect := func(data jx.M) (map[string]any, jx.M) {
		days := map[string]any{}
		meta := jx.M{}
		for _, rec := range jx.GetMaps(data, "records") {
			meta = jx.M{}
			for k, v := range rec {
				if k != "day_totals" {
					meta[k] = v
				}
			}
			for _, dt := range jx.GetMaps(rec, "day_totals") {
				if day := jx.Str(dt["day"]); day != "" && jx.Truthy(dt["day"]) {
					days[day] = dt
				}
			}
		}
		return days, meta
	}
	oldDays, oldMeta := collect(oldM)
	newDays, newMeta := collect(newM)
	if len(oldDays) == 0 {
		return newData
	}
	merged := map[string]any{}
	for k, v := range oldDays {
		merged[k] = v
	}
	for k, v := range newDays {
		merged[k] = v
	}
	keys := jx.SortedKeys(merged)
	record := jx.Merge(oldMeta, newMeta)
	totals := jx.L{}
	for _, k := range keys {
		totals = append(totals, merged[k])
	}
	record["day_totals"] = totals
	out := jx.Merge(oldM, newM)
	if len(keys) > 0 {
		record["report_start_day"] = keys[0]
		record["report_end_day"] = keys[len(keys)-1]
		out["report_start_day"] = keys[0]
		out["report_end_day"] = keys[len(keys)-1]
	}
	out["records"] = jx.L{record}
	out["total_records"] = 1
	return out
}

func mergeUsageUsersReport(oldData, newData any) any {
	newM := jx.Map(newData)
	if newM == nil {
		return newData
	}
	oldM := jx.Map(oldData)
	if oldM == nil || !jx.Truthy(oldM["records"]) {
		return newData
	}
	key := func(rec jx.M) string {
		user := jx.Str(rec["user_login"])
		if !jx.Truthy(rec["user_login"]) {
			user = jx.Str(rec["user_id"])
		}
		return jx.Str(rec["day"]) + "\x00" + user
	}
	merged := map[string]jx.M{}
	for _, rec := range jx.GetMaps(oldM, "records") {
		merged[key(rec)] = rec
	}
	for _, rec := range jx.GetMaps(newM, "records") {
		merged[key(rec)] = rec
	}
	recs := make([]jx.M, 0, len(merged))
	for _, r := range merged {
		recs = append(recs, r)
	}
	sort.SliceStable(recs, func(i, j int) bool {
		di, dj := jx.Str(recs[i]["day"]), jx.Str(recs[j]["day"])
		if di != dj {
			return di < dj
		}
		return jx.Str(recs[i]["user_login"]) < jx.Str(recs[j]["user_login"])
	})
	days := []string{}
	list := make(jx.L, len(recs))
	for i, r := range recs {
		list[i] = r
		if d := jx.Str(r["day"]); d != "" {
			days = append(days, d)
		}
	}
	out := jx.Merge(oldM, newM)
	out["records"] = list
	out["total_records"] = len(list)
	if lo, hi, ok := jx.MinMax(days); ok {
		out["report_start_day"] = lo
		out["report_end_day"] = hi
	}
	return out
}

func mergeMetricsList(oldData, newData any) any {
	newL := jx.List(newData)
	if newL == nil {
		return newData
	}
	oldL := jx.List(oldData)
	if len(oldL) == 0 {
		return newData
	}
	merged := map[string]any{}
	for _, e := range oldL {
		if m := jx.Map(e); m != nil && jx.Truthy(m["date"]) {
			merged[jx.Str(m["date"])] = m
		}
	}
	for _, e := range newL {
		if m := jx.Map(e); m != nil && jx.Truthy(m["date"]) {
			merged[jx.Str(m["date"])] = m
		}
	}
	if len(merged) == 0 {
		return newData
	}
	out := jx.L{}
	for _, k := range jx.SortedKeys(merged) {
		out = append(out, merged[k])
	}
	return out
}

var latestMergeStrategies = map[string]func(any, any) any{
	"usage":       mergeUsageReport,
	"usage_users": mergeUsageUsersReport,
	"metrics":     mergeMetricsList,
}

// DataCollector fetches GitHub data and stores it as data/{category}/{org}_latest.json.
// A session collector writes to its session dir and reads with fallback to the global dir.
type DataCollector struct {
	dataDir     string
	fallbackDir string
}

// Collector is the global data collector.
var Collector = &DataCollector{}

// NewSessionCollector returns a collector scoped to a session directory.
func NewSessionCollector(sessionDir string) *DataCollector {
	return &DataCollector{dataDir: sessionDir, fallbackDir: DataDir}
}

// DataDir returns the primary data directory.
func (dc *DataCollector) DataDir() string {
	if dc.dataDir == "" {
		return DataDir
	}
	return dc.dataDir
}

// SaveJSON writes {category}/{org}_latest.json, merging day-granular history.
func (dc *DataCollector) SaveJSON(category, org string, data any) string {
	latest := filepath.Join(dc.DataDir(), category, org+"_latest.json")
	mu := jx.FileLock(latest)
	mu.Lock()
	defer mu.Unlock()
	toWrite := data
	if merge, ok := latestMergeStrategies[category]; ok {
		old, _ := jx.ReadJSON(latest)
		func() {
			defer func() {
				if recover() != nil {
					toWrite = data
				}
			}()
			toWrite = merge(old, jx.Normalize(data))
		}()
	}
	if err := jx.WriteJSON(latest, toWrite); err != nil {
		Logger.Error("Failed to save " + latest + ": " + err.Error())
	}
	return latest
}

// PurgeSnapshots deletes legacy timestamped snapshot files.
func (dc *DataCollector) PurgeSnapshots() int {
	matches, _ := filepath.Glob(filepath.Join(dc.DataDir(), "*", "*.json"))
	removed := 0
	for _, p := range matches {
		name := filepath.Base(p)
		if strings.HasSuffix(name, "_latest.json") || !snapshotNameRE.MatchString(name) {
			continue
		}
		if os.Remove(p) == nil {
			removed++
		}
	}
	return removed
}

// LoadLatest loads one org's latest data (seats/billing go through the dedup view).
func (dc *DataCollector) LoadLatest(category, org string) any {
	if category == "seats" || category == "billing" {
		return dc.LoadAllLatest(category)[org]
	}
	return dc.loadLatestRaw(category, org)
}

// LoadLatestMap is LoadLatest returning an object (nil when absent / not an object).
func (dc *DataCollector) LoadLatestMap(category, org string) jx.M {
	return jx.Map(dc.LoadLatest(category, org))
}

// Parsed snapshot files share dataFileCache with the dashboards; callers get a
// deep copy, so they may mutate it.
func readJSONCached(path string) (any, error) {
	st, err := os.Stat(path)
	if err != nil {
		return nil, err
	}
	v, err := dataFileCache.load(path, st, func() (any, error) { return jx.ReadJSON(path) })
	if err != nil {
		return nil, err
	}
	return jx.DeepCopy(v), nil
}

func (dc *DataCollector) loadLatestRaw(category, org string) any {
	path := filepath.Join(dc.DataDir(), category, org+"_latest.json")
	if v, err := readJSONCached(path); err == nil {
		return v
	}
	if dc.fallbackDir != "" {
		if v, err := readJSONCached(filepath.Join(dc.fallbackDir, category, org+"_latest.json")); err == nil {
			return v
		}
	}
	return nil
}

func (dc *DataCollector) loadAllLatestRaw(category string) map[string]any {
	result := map[string]any{}
	read := func(dir string) {
		matches, _ := filepath.Glob(filepath.Join(dir, category, "*_latest.json"))
		for _, f := range matches {
			org := strings.TrimSuffix(filepath.Base(f), "_latest.json")
			if _, ok := result[org]; ok {
				continue
			}
			if v, err := readJSONCached(f); err == nil {
				result[org] = v
			}
		}
	}
	read(dc.DataDir())
	if dc.fallbackDir != "" {
		read(dc.fallbackDir)
	}
	return result
}

// LoadAllLatest loads latest data for every org. For seats/billing, enterprise
// seat payloads are de-duplicated against org seats and billing is synthesized
// for enterprise scopes.
func (dc *DataCollector) LoadAllLatest(category string) map[string]any {
	if category != "seats" && category != "billing" {
		return dc.loadAllLatestRaw(category)
	}
	rawSeats := dc.loadAllLatestRaw("seats")
	enterprises := APIs.AllEnterprises()
	enterpriseKeys := jx.StrSet{}
	for _, e := range enterprises {
		enterpriseKeys.Add(EnterprisePseudoOrg(jx.Str(e["slug"])))
	}
	for scope, payload := range rawSeats {
		if jx.Truthy(jx.Map(payload)["_enterprise_slug"]) {
			enterpriseKeys.Add(scope)
		}
	}
	rawBilling := dc.loadAllLatestRaw("billing")
	for scope, payload := range rawBilling {
		if jx.Str(jx.Map(payload)["_source"]) == "enterprise_seats_aggregate" {
			enterpriseKeys.Add(scope)
		}
	}
	// The API manager always exists here, so restrict to discovered scopes.
	orgKeys := jx.StrSet{}
	for _, o := range APIs.AllOrgLogins() {
		orgKeys.Add(o)
	}
	known := jx.StrSet{}
	for _, e := range enterprises {
		known.Add(EnterprisePseudoOrg(jx.Str(e["slug"])))
	}
	for k := range enterpriseKeys {
		if !known.Has(k) {
			delete(enterpriseKeys, k)
		}
	}

	seatViews := map[string]any{}
	covered := jx.StrSet{}
	for scope, payload := range rawSeats {
		if orgKeys.Has(scope) {
			seatViews[scope] = payload
			for _, seat := range jx.GetMaps(jx.Map(payload), "seats") {
				if login := strings.ToLower(jx.Str(jx.GetMap(seat, "assignee")["login"])); login != "" {
					covered.Add(login)
				}
			}
		}
	}
	for _, scope := range enterpriseKeys.Sorted() {
		payload := jx.Map(rawSeats[scope])
		if payload == nil {
			continue
		}
		remaining := jx.L{}
		for _, seat := range jx.GetMaps(payload, "seats") {
			login := strings.ToLower(jx.Str(jx.GetMap(seat, "assignee")["login"]))
			if login != "" && covered.Has(login) {
				continue
			}
			remaining = append(remaining, seat)
			if login != "" {
				covered.Add(login)
			}
		}
		seatViews[scope] = jx.Merge(payload, jx.M{"seats": remaining, "total_seats": len(remaining)})
	}
	if category == "seats" {
		return seatViews
	}
	billingViews := map[string]any{}
	for scope, payload := range rawBilling {
		if orgKeys.Has(scope) || enterpriseKeys.Has(scope) {
			billingViews[scope] = payload
		}
	}
	for scope, seats := range seatViews {
		if _, has := billingViews[scope]; enterpriseKeys.Has(scope) || !has {
			billingViews[scope] = BuildSyntheticEnterpriseBilling(jx.Map(seats))
		}
	}
	return billingViews
}

// BuildSyntheticEnterpriseBilling approximates /orgs/{org}/copilot/billing from seats.
func BuildSyntheticEnterpriseBilling(seats jx.M) jx.M {
	seatList := jx.GetMaps(seats, "seats")
	total := jx.Int(jx.GetOr(seats, "total_seats", len(seatList)))
	cutoff := time.Now().UTC().Add(-28 * 24 * time.Hour)
	active, pending := 0, 0
	planCounts := map[string]int{}
	planOrder := []string{}
	for _, s := range seatList {
		plan := jx.Str(s["plan_type"])
		if plan == "" {
			plan = "unknown"
		}
		if _, ok := planCounts[plan]; !ok {
			planOrder = append(planOrder, plan)
		}
		planCounts[plan]++
		if jx.Truthy(s["pending_cancellation_date"]) {
			pending++
		}
		if t, ok := jx.ParseISO(jx.Str(s["last_activity_at"])); ok && !t.Before(cutoff) {
			active++
		}
	}
	planType := "enterprise"
	best := -1
	for _, p := range planOrder {
		if planCounts[p] > best {
			best = planCounts[p]
			planType = p
		}
	}
	if _, ok := CopilotPricing[planType]; !ok {
		planType = "enterprise"
	}
	return jx.M{
		"seat_breakdown": jx.M{
			"total":                total,
			"added_this_cycle":     0,
			"pending_cancellation": pending,
			"pending_invitation":   0,
			"active_this_cycle":    active,
			"inactive_this_cycle":  total - active,
		},
		"public_code_suggestions":  "unconfigured",
		"plan_type":                planType,
		"_detected_plan_type":      planType,
		"_detected_price_per_seat": CopilotPricing[planType],
		"_synthetic":               true,
		"_source":                  "enterprise_seats_aggregate",
	}
}

// SyncSummary is {"org"?, "synced": [...], "errors": [...]}.
type SyncSummary = jx.M

func newSummary(org string) SyncSummary {
	s := SyncSummary{"synced": []string{}, "errors": []string{}}
	if org != "" {
		s["org"] = org
	}
	return s
}

func addSynced(s SyncSummary, item string) { s["synced"] = append(s["synced"].([]string), item) }
func addError(s SyncSummary, item string)  { s["errors"] = append(s["errors"].([]string), item) }
func summaryList(s SyncSummary, key string) []string {
	if l, ok := s[key].([]string); ok {
		return l
	}
	return jx.Strings(s[key])
}

// fetchStep runs one dataset fetch with the standard logging/summary handling.
func fetchStep(summary SyncSummary, api *ghapi.Client, logFn LogFn, scope, role, key, label string,
	fetch func() (any, error), save func(any) string) {
	data, err := fetch()
	if err != nil {
		addError(summary, fmt.Sprintf("%s: %v", key, err))
		logFn.log("error", fmt.Sprintf("  %s: %s error - %v", scope, label, err))
		return
	}
	if jx.Truthy(data) {
		addSynced(summary, save(data))
		return
	}
	level, msg := emptyResultLog(api, scope, label, role)
	if level == "error" {
		addError(summary, strings.TrimSpace(msg))
	}
	logFn.log(level, msg)
}

// SyncOrg syncs every Copilot dataset for one org.
func (dc *DataCollector) SyncOrg(ctx context.Context, org string, logFn LogFn) SyncSummary {
	summary := newSummary(org)
	logFn.log("info", fmt.Sprintf("Syncing %s...", org))
	api := APIs.APIForOrg(org)
	role := APIs.OrgRole(org)
	if api == nil {
		msg := "No API client available for " + org
		addError(summary, msg)
		logFn.log("error", fmt.Sprintf("  %s: %s", org, msg))
		return summary
	}

	fetchStep(summary, api, logFn, org, role, "billing", "billing",
		func() (any, error) { v, err := api.GetCopilotBilling(ctx, org); return nilIfEmpty(v), err },
		func(d any) string {
			dc.SaveJSON("billing", org, d)
			logFn.log("info", fmt.Sprintf("  %s: billing synced", org))
			return "billing"
		})

	fetchStep(summary, api, logFn, org, role, "seats", "seats",
		func() (any, error) { v, err := api.GetCopilotSeats(ctx, org); return nilIfEmpty(v), err },
		func(d any) string {
			dc.SaveJSON("seats", org, d)
			n := jx.Int(jx.Map(d)["total_seats"])
			logFn.log("info", fmt.Sprintf("  %s: seats synced (%d total)", org, n))
			return fmt.Sprintf("seats (%d total)", n)
		})

	fetchStep(summary, api, logFn, org, role, "usage", "usage report",
		func() (any, error) { return nilIfEmpty(api.GetOrgUsageReport28Day(ctx, org)), nil },
		func(d any) string {
			dc.SaveJSON("usage", org, d)
			n := jx.Int(jx.Map(d)["total_records"])
			logFn.log("info", fmt.Sprintf("  %s: usage report synced (%d records)", org, n))
			return fmt.Sprintf("usage (%d records)", n)
		})

	fetchStep(summary, api, logFn, org, role, "usage_users", "usage users report",
		func() (any, error) { return nilIfEmpty(api.GetOrgUsersUsageReport28Day(ctx, org)), nil },
		func(d any) string {
			dc.SaveJSON("usage_users", org, d)
			n := jx.Int(jx.Map(d)["total_records"])
			logFn.log("info", fmt.Sprintf("  %s: usage users report synced (%d records)", org, n))
			return fmt.Sprintf("usage_users (%d records)", n)
		})

	fetchStep(summary, api, logFn, org, role, "metrics", "metrics",
		func() (any, error) {
			v, err := api.GetCopilotMetrics(ctx, org, "", "")
			if len(v) == 0 {
				return nil, err
			}
			return v, err
		},
		func(d any) string {
			dc.SaveJSON("metrics", org, d)
			n := len(jx.List(d))
			logFn.log("info", fmt.Sprintf("  %s: metrics synced (%d entries)", org, n))
			return fmt.Sprintf("metrics (%d entries)", n)
		})

	fetchStep(summary, api, logFn, org, role, "ai_credits", "AI credit usage",
		func() (any, error) { v, err := api.GetAICreditUsage(ctx, org, 0, 0, 0); return nilIfEmpty(v), err },
		func(d any) string {
			dc.SaveJSON("ai_credits", org, d)
			n := len(jx.GetList(jx.Map(d), "usageItems"))
			logFn.log("info", fmt.Sprintf("  %s: AI credit usage synced (%d items)", org, n))
			return fmt.Sprintf("ai_credits (%d items)", n)
		})

	logFn.log("info", fmt.Sprintf("  %s: done (%d synced, %d errors)", org,
		len(summaryList(summary, "synced")), len(summaryList(summary, "errors"))))
	return summary
}

func nilIfEmpty(m jx.M) any {
	if len(m) == 0 {
		return nil
	}
	return m
}

// expandCostCenterMembers expands resources into a flat member list.
func (dc *DataCollector) expandCostCenterMembers(ctx context.Context, cc jx.M, api *ghapi.Client, logFn LogFn) jx.L {
	members := jx.L{}
	seen := jx.StrSet{}
	add := func(raw jx.M, sourceType, sourceName string) {
		login := jx.Str(raw["login"])
		if login == "" || seen.Has(login) {
			return
		}
		seen.Add(login)
		htmlURL := jx.Str(raw["html_url"])
		if htmlURL == "" {
			htmlURL = api.WebBase() + "/" + login
		}
		members = append(members, jx.M{
			"login":       login,
			"avatar_url":  jx.GetStr(raw, "avatar_url"),
			"html_url":    htmlURL,
			"source_type": sourceType,
			"source_name": sourceName,
		})
	}
	for _, res := range jx.GetMaps(cc, "resources") {
		rtype := jx.Str(res["type"])
		rname := jx.Str(res["name"])
		switch rtype {
		case "User":
			add(jx.M{"login": rname}, "User", rname)
		case "Org":
			orgMembers := api.GetOrgMembers(ctx, rname)
			for _, m := range orgMembers {
				add(m, "Org", rname)
			}
			logFn.log("info", fmt.Sprintf("    Org '%s': %d members", rname, len(orgMembers)))
		case "Team":
			parts := strings.SplitN(rname, "/", 2)
			if len(parts) == 2 && parts[0] != "" {
				teamMembers := api.GetTeamMembers(ctx, parts[0], parts[1])
				for _, m := range teamMembers {
					add(m, "Team", rname)
				}
				logFn.log("info", fmt.Sprintf("    Team '%s': %d members", rname, len(teamMembers)))
			}
		}
	}
	return members
}

// SyncEnterprises syncs the enterprise list, cost centers, budgets, teams and
// enterprise-level Copilot data.
func (dc *DataCollector) SyncEnterprises(ctx context.Context, logFn LogFn) SyncSummary {
	summary := newSummary("")
	enterprises := APIs.AllEnterprises()
	if len(enterprises) == 0 {
		logFn.log("info", "  No enterprises discovered, skipping enterprise sync")
		return summary
	}
	dc.SaveJSON("enterprise", "all", enterprises)
	slugs := []string{}
	for _, e := range enterprises {
		slugs = append(slugs, jx.Str(e["slug"]))
	}
	addSynced(summary, fmt.Sprintf("enterprises (%d total)", len(enterprises)))
	logFn.log("info", fmt.Sprintf("  Enterprises synced: %s", pyStrList(slugs)))

	for _, part := range []SyncSummary{
		dc.syncCostCenters(ctx, enterprises, logFn),
		dc.syncBudgets(ctx, enterprises, logFn),
		dc.syncEnterpriseTeams(ctx, enterprises, logFn),
	} {
		for _, s := range summaryList(part, "synced") {
			addSynced(summary, s)
		}
		for _, s := range summaryList(part, "errors") {
			addError(summary, s)
		}
	}

	usageSlugs := jx.StrSet{}
	for _, e := range APIs.EnterprisePseudoOrgs() {
		usageSlugs.Add(jx.Str(e["slug"]))
	}
	for _, ent := range enterprises {
		part := dc.SyncEnterpriseCopilotData(ctx, ent, logFn, !usageSlugs.Has(jx.Str(ent["slug"])))
		for _, s := range summaryList(part, "synced") {
			addSynced(summary, s)
		}
		for _, s := range summaryList(part, "errors") {
			addError(summary, s)
		}
	}
	return summary
}

// pyStrList renders a string list like Python's repr: ['a', 'b'].
func pyStrList(items []string) string {
	q := make([]string, len(items))
	for i, s := range items {
		q[i] = "'" + s + "'"
	}
	return "[" + strings.Join(q, ", ") + "]"
}

// SyncEnterpriseCopilotData syncs enterprise seats (always) and, unless
// seatsOnly, enterprise usage / users usage / AI credits.
func (dc *DataCollector) SyncEnterpriseCopilotData(ctx context.Context, enterprise jx.M, logFn LogFn, seatsOnly bool) SyncSummary {
	slug := jx.Str(enterprise["slug"])
	summary := newSummary(slug)
	api := APIs.APIForEnterprise(slug)
	if api == nil {
		msg := "No API client available for enterprise " + slug
		addError(summary, msg)
		logFn.log("error", fmt.Sprintf("  %s: %s", slug, msg))
		return summary
	}
	pseudo := EnterprisePseudoOrg(slug)
	logFn.log("info", fmt.Sprintf("Syncing %s (enterprise-level)...", slug))

	var seats jx.M
	fetchStep(summary, api, logFn, slug, "", "seats", "enterprise seats",
		func() (any, error) { v, err := api.GetEnterpriseBillingSeats(ctx, slug); return nilIfEmpty(v), err },
		func(d any) string {
			seats = jx.Merge(jx.Map(d), jx.M{"_enterprise_slug": slug})
			dc.SaveJSON("seats", pseudo, seats)
			n := jx.Int(seats["total_seats"])
			logFn.log("info", fmt.Sprintf("  %s: enterprise seats synced (%d total)", slug, n))
			return fmt.Sprintf("seats (%d total)", n)
		})
	if seats != nil {
		dc.SaveJSON("billing", pseudo, BuildSyntheticEnterpriseBilling(seats))
		addSynced(summary, "billing (synthesized from seats)")
	}
	if seatsOnly {
		return summary
	}

	fetchStep(summary, api, logFn, slug, "", "usage", "enterprise usage report",
		func() (any, error) { return nilIfEmpty(api.GetEnterpriseUsageReport28Day(ctx, slug)), nil },
		func(d any) string {
			dc.SaveJSON("usage", pseudo, d)
			n := jx.Int(jx.Map(d)["total_records"])
			logFn.log("info", fmt.Sprintf("  %s: enterprise usage report synced (%d records)", slug, n))
			return fmt.Sprintf("usage (%d records)", n)
		})
	fetchStep(summary, api, logFn, slug, "", "usage_users", "enterprise usage users report",
		func() (any, error) { return nilIfEmpty(api.GetEnterpriseUsersUsageReport28Day(ctx, slug)), nil },
		func(d any) string {
			dc.SaveJSON("usage_users", pseudo, d)
			n := jx.Int(jx.Map(d)["total_records"])
			logFn.log("info", fmt.Sprintf("  %s: enterprise usage users report synced (%d records)", slug, n))
			return fmt.Sprintf("usage_users (%d records)", n)
		})
	fetchStep(summary, api, logFn, slug, "", "ai_credits", "enterprise AI credit usage",
		func() (any, error) {
			v, err := api.GetEnterpriseAICreditUsage(ctx, slug, 0, 0, 0)
			return nilIfEmpty(v), err
		},
		func(d any) string {
			dc.SaveJSON("ai_credits", pseudo, d)
			n := len(jx.GetList(jx.Map(d), "usageItems"))
			logFn.log("info", fmt.Sprintf("  %s: enterprise AI credit usage synced (%d items)", slug, n))
			return fmt.Sprintf("ai_credits (%d items)", n)
		})
	logFn.log("info", fmt.Sprintf("  %s: done (%d synced, %d errors)", slug,
		len(summaryList(summary, "synced")), len(summaryList(summary, "errors"))))
	return summary
}

// SyncDataset syncs a single enterprise dataset: cost_centers, budgets or enterprise_teams.
func (dc *DataCollector) SyncDataset(ctx context.Context, dataset string, logFn LogFn) SyncSummary {
	summary := newSummary("")
	enterprises := APIs.AllEnterprises()
	if len(enterprises) == 0 {
		logFn.log("info", "  No enterprises discovered, skipping sync")
		return summary
	}
	dc.SaveJSON("enterprise", "all", enterprises)
	var result SyncSummary
	switch dataset {
	case "cost_centers":
		logFn.log("info", "Syncing cost center data...")
		result = dc.syncCostCenters(ctx, enterprises, logFn)
	case "budgets":
		logFn.log("info", "Syncing budget data...")
		result = dc.syncBudgets(ctx, enterprises, logFn)
	case "enterprise_teams":
		logFn.log("info", "Syncing enterprise team data...")
		result = dc.syncEnterpriseTeams(ctx, enterprises, logFn)
	default:
		addError(summary, fmt.Sprintf("Unknown dataset '%s'", dataset))
		logFn.log("error", fmt.Sprintf("  Unknown dataset '%s'", dataset))
		return summary
	}
	for _, s := range summaryList(result, "synced") {
		addSynced(summary, s)
	}
	for _, s := range summaryList(result, "errors") {
		addError(summary, s)
	}
	return summary
}

func (dc *DataCollector) syncCostCenters(ctx context.Context, enterprises []jx.M, logFn LogFn) SyncSummary {
	summary := newSummary("")
	for _, ent := range enterprises {
		slug := jx.Str(ent["slug"])
		api := APIs.APIForEnterprise(slug)
		if api == nil {
			addError(summary, fmt.Sprintf("cost_centers/%s: no API client", slug))
			continue
		}
		raw, err := api.GetEnterpriseCostCenters(ctx, slug)
		if err != nil {
			addError(summary, fmt.Sprintf("cost_centers/%s: %v", slug, err))
			logFn.log("error", fmt.Sprintf("  %s: cost centers error - %v", slug, err))
			continue
		}
		logFn.log("info", fmt.Sprintf("  %s: %d cost centers, expanding members...", slug, len(raw)))
		expanded := jx.L{}
		total := 0
		unique := jx.StrSet{}
		for _, cc := range raw {
			members := dc.expandCostCenterMembers(ctx, cc, api, logFn)
			expanded = append(expanded, jx.Merge(cc, jx.M{"members": members, "member_count": len(members)}))
			total += len(members)
			for _, m := range jx.Maps(members) {
				unique.Add(jx.Str(m["login"]))
			}
		}
		dc.SaveJSON("cost_centers", slug, jx.M{
			"enterprise":           slug,
			"enterprise_name":      jx.GetStr(ent, "name"),
			"cost_centers":         expanded,
			"total":                len(expanded),
			"total_unique_members": len(unique),
		})
		addSynced(summary, fmt.Sprintf("cost_centers/%s (%d centers, %d member assignments)", slug, len(expanded), total))
		logFn.log("info", fmt.Sprintf("  %s: cost centers synced (%d centers, %d member assignments)", slug, len(expanded), total))
	}
	return summary
}

// SyncCostCentersForEnterprise refreshes cached cost centers for one enterprise.
func (dc *DataCollector) SyncCostCentersForEnterprise(ctx context.Context, enterprise jx.M, logFn LogFn) SyncSummary {
	return dc.syncCostCenters(ctx, []jx.M{enterprise}, logFn)
}

// UpdateCachedCostCenter patches one cached cost center's fields.
func (dc *DataCollector) UpdateCachedCostCenter(enterprise, costCenterID string, fields jx.M) bool {
	data := dc.LoadLatestMap("cost_centers", enterprise)
	if data == nil {
		return false
	}
	for _, cc := range jx.GetMaps(data, "cost_centers") {
		if jx.Str(cc["id"]) == costCenterID {
			for k, v := range fields {
				cc[k] = v
			}
			dc.SaveJSON("cost_centers", enterprise, data)
			return true
		}
	}
	return false
}

func (dc *DataCollector) syncEnterpriseTeams(ctx context.Context, enterprises []jx.M, logFn LogFn) SyncSummary {
	summary := newSummary("")
	for _, ent := range enterprises {
		slug := jx.Str(ent["slug"])
		api := APIs.APIForEnterprise(slug)
		if api == nil {
			addError(summary, fmt.Sprintf("enterprise_teams/%s: no API client", slug))
			continue
		}
		rawTeams := api.GetEnterpriseTeams(ctx, slug)
		logFn.log("info", fmt.Sprintf("  %s: %d enterprise teams, expanding members...", slug, len(rawTeams)))
		expanded := jx.L{}
		memberIndex := map[string][]string{}
		indexOrder := []string{}
		for _, team := range rawTeams {
			teamSlug := jx.Str(team["slug"])
			if teamSlug == "" {
				continue
			}
			rawMembers := api.GetEnterpriseTeamMembers(ctx, slug, teamSlug)
			orgAssignments := api.GetEnterpriseTeamOrganizations(ctx, slug, teamSlug)
			members := jx.L{}
			for _, m := range rawMembers {
				login := jx.Str(m["login"])
				if login == "" {
					continue
				}
				htmlURL := jx.Str(m["html_url"])
				if htmlURL == "" {
					htmlURL = api.WebBase() + "/" + login
				}
				members = append(members, jx.M{"login": login, "avatar_url": jx.GetStr(m, "avatar_url"), "html_url": htmlURL})
				key := strings.ToLower(login)
				if _, ok := memberIndex[key]; !ok {
					indexOrder = append(indexOrder, key)
				}
				memberIndex[key] = append(memberIndex[key], teamSlug)
			}
			orgs := jx.L{}
			for _, o := range orgAssignments {
				if l := jx.Str(o["login"]); l != "" {
					orgs = append(orgs, l)
				}
			}
			name := jx.Str(team["name"])
			if _, ok := team["name"]; !ok {
				name = teamSlug
			}
			expanded = append(expanded, jx.M{
				"id":                          team["id"],
				"slug":                        teamSlug,
				"name":                        name,
				"description":                 jx.Str(team["description"]),
				"html_url":                    jx.GetStr(team, "html_url"),
				"group_id":                    team["group_id"],
				"group_name":                  team["group_name"],
				"organization_selection_type": jx.GetStr(team, "organization_selection_type"),
				"created_at":                  jx.GetStr(team, "created_at"),
				"updated_at":                  jx.GetStr(team, "updated_at"),
				"organizations":               orgs,
				"members":                     members,
				"member_count":                len(members),
			})
			logFn.log("info", fmt.Sprintf("    Team '%s': %d members", teamSlug, len(members)))
		}
		index := jx.M{}
		for _, k := range indexOrder {
			index[k] = memberIndex[k]
		}
		dc.SaveJSON("enterprise_teams", slug, jx.M{
			"enterprise":           slug,
			"enterprise_name":      jx.GetStr(ent, "name"),
			"teams":                expanded,
			"member_index":         index,
			"total":                len(expanded),
			"total_unique_members": len(index),
		})
		addSynced(summary, fmt.Sprintf("enterprise_teams/%s (%d teams, %d unique members)", slug, len(expanded), len(index)))
		logFn.log("info", fmt.Sprintf("  %s: enterprise teams synced (%d teams, %d unique members)", slug, len(expanded), len(index)))
	}
	return summary
}

func (dc *DataCollector) syncBudgets(ctx context.Context, enterprises []jx.M, logFn LogFn) SyncSummary {
	summary := newSummary("")
	for _, ent := range enterprises {
		slug := jx.Str(ent["slug"])
		api := APIs.APIForEnterprise(slug)
		if api == nil {
			addError(summary, fmt.Sprintf("budgets/%s: no API client", slug))
			continue
		}
		budgets, err := api.GetAllBudgetsPaginated(ctx, "enterprise", slug, "", false)
		if err != nil {
			addError(summary, fmt.Sprintf("budgets/%s: %v", slug, err))
			logFn.log("error", fmt.Sprintf("  %s: budgets error - %v", slug, err))
			continue
		}
		dc.SaveJSON("budgets", slug, jx.M{
			"enterprise":      slug,
			"enterprise_name": jx.GetStr(ent, "name"),
			"budgets":         budgets,
			"total":           len(budgets),
		})
		addSynced(summary, fmt.Sprintf("budgets/%s (%d budgets)", slug, len(budgets)))
		logFn.log("info", fmt.Sprintf("  %s: budgets synced (%d budgets)", slug, len(budgets)))
	}
	return summary
}

// SyncAll syncs every discovered org, then enterprise data.
func (dc *DataCollector) SyncAll(ctx context.Context, logFn LogFn) []SyncSummary {
	orgs := APIs.AllOrgLogins()
	logFn.log("info", fmt.Sprintf("Starting sync for %d org(s): %s", len(orgs), strings.Join(orgs, ", ")))
	results := []SyncSummary{}
	for _, org := range orgs {
		results = append(results, dc.SyncOrg(ctx, org, logFn))
	}
	logFn.log("info", "Syncing enterprise and cost center data...")
	ent := dc.SyncEnterprises(ctx, logFn)
	ent["org"] = "__enterprise__"
	results = append(results, ent)
	synced, errs := 0, 0
	for _, r := range results {
		synced += len(summaryList(r, "synced"))
		errs += len(summaryList(r, "errors"))
	}
	logFn.log("info", fmt.Sprintf("Sync complete: %d datasets synced, %d errors", synced, errs))
	return results
}
