package app

import (
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"

	"github.com/satomic/octofinance/backend-go/internal/jx"
)

// Data query router (Python routers/data.py) - read access to collected data,
// the Usage Metrics / CSV / cost center / enterprise team / budget dashboards
// and CSV ingestion. Split over routes_data*.go.

func init() { registerRoutes(registerDataRoutes) }

func registerDataRoutes(r *Router) {
	r.Handle("GET /api/data/user-roster", dataUserRoster)
	r.Handle("GET /api/data/orgs", dataOrgs)
	r.Handle("GET /api/data/overview", dataOverview)
	r.Handle("GET /api/data/seats/{org}", dataSeats)
	r.Handle("GET /api/data/billing/{org}", dataBilling)
	r.Handle("GET /api/data/dashboard", dataDashboard)
	r.Handle("GET /api/data/csv-dashboard", dataCSVDashboard)
	r.Handle("POST /api/data/upload-csv", dataUploadCSV)
	r.Handle("POST /api/data/fetch-csv", dataFetchCSV)
	r.Handle("GET /api/data/fetch-csv/status", func(c *Ctx) any { return CSVGetJob() })
	r.Handle("GET /api/data/csv-info", dataCSVInfo)
	r.Handle("GET /api/data/cost-center-unassigned-users", dataCCUnassignedUsers)
	r.Handle("POST /api/data/cost-center-unassigned-users/assign", dataCCAssignUsers)
	r.Handle("POST /api/data/cost-center-ai-credit-pool", dataCCAICreditPool)
	r.Handle("GET /api/data/cost-center-report", dataCCReport)
	r.Handle("GET /api/data/cost-center-dashboard", dataCCDashboard)
	r.Handle("GET /api/data/enterprise-teams-dashboard", dataEnterpriseTeamsDashboard)
	r.Handle("GET /api/data/budgets-dashboard", dataBudgetsDashboard)
}

// ---------------------------------------------------------------------------
// Dataset loading
//
// Dashboards read the same snapshots many times per request (Python re-parses
// the file on every load_latest call). dataLoader memoizes per request, and raw
// {category}/{scope}_latest.json files are additionally cached across requests
// keyed on mtime+size. Loaded values are SHARED: never mutate them.
// ---------------------------------------------------------------------------

var dataFileCache = newFileCache()

// dataReadCached decodes a JSON file, reusing the previous decode when the file
// is unchanged. ok is false when the file is missing or invalid.
func dataReadCached(path string) (any, bool) {
	st, err := os.Stat(path)
	if err != nil || st.IsDir() {
		return nil, false
	}
	v, err := dataFileCache.load(path, st, func() (any, error) { return jx.ReadJSON(path) })
	return v, err == nil
}

type dataLoader struct {
	views map[string]map[string]any // "seats"/"billing" de-dup views
	raw   map[string]any
	all   map[string]map[string]any
}

func newDataLoader() *dataLoader {
	return &dataLoader{views: map[string]map[string]any{}, raw: map[string]any{}, all: map[string]map[string]any{}}
}

// latest mirrors data_collector.load_latest(category, org).
func (l *dataLoader) latest(category, org string) any {
	if category == "seats" || category == "billing" {
		v, ok := l.views[category]
		if !ok {
			v = Collector.LoadAllLatest(category)
			l.views[category] = v
		}
		return v[org]
	}
	key := category + "/" + org
	if v, ok := l.raw[key]; ok {
		return v
	}
	v, _ := dataReadCached(filepath.Join(Collector.DataDir(), category, org+"_latest.json"))
	l.raw[key] = v
	return v
}

func (l *dataLoader) latestMap(category, org string) jx.M { return jx.Map(l.latest(category, org)) }

// allLatest mirrors data_collector.load_all_latest(category). Returns the
// scopes in sorted order alongside the map (Python iterates in glob order).
func (l *dataLoader) allLatest(category string) ([]string, map[string]any) {
	if category == "seats" || category == "billing" {
		v, ok := l.views[category]
		if !ok {
			v = Collector.LoadAllLatest(category)
			l.views[category] = v
		}
		return jx.SortedKeys(v), v
	}
	if v, ok := l.all[category]; ok {
		return jx.SortedKeys(v), v
	}
	out := map[string]any{}
	matches, _ := filepath.Glob(filepath.Join(Collector.DataDir(), category, "*_latest.json"))
	for _, f := range matches {
		org := strings.TrimSuffix(filepath.Base(f), "_latest.json")
		if v, ok := dataReadCached(f); ok {
			out[org] = v
		}
	}
	l.all[category] = out
	return jx.SortedKeys(out), out
}

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

// dataOM is an insertion-ordered map (Python dict / defaultdict).
type dataOM[V any] struct {
	keys []string
	m    map[string]V
}

func newDataOM[V any]() *dataOM[V] { return &dataOM[V]{m: map[string]V{}} }

func (o *dataOM[V]) at(k string, mk func() V) V {
	if v, ok := o.m[k]; ok {
		return v
	}
	v := mk()
	o.m[k] = v
	o.keys = append(o.keys, k)
	return v
}

func (o *dataOM[V]) has(k string) bool { _, ok := o.m[k]; return ok }

// sortedKeysBy returns keys ordered by less, stable on insertion order.
func (o *dataOM[V]) sortedKeysBy(less func(a, b V) bool) []string {
	keys := append([]string{}, o.keys...)
	sort.SliceStable(keys, func(i, j int) bool { return less(o.m[keys[i]], o.m[keys[j]]) })
	return keys
}

// dataSplitCSV is “[x.strip() for x in s.split(",") if x.strip()]“.
func dataSplitCSV(s string) []string {
	out := []string{}
	for _, p := range strings.Split(s, ",") {
		if p = strings.TrimSpace(p); p != "" {
			out = append(out, p)
		}
	}
	return out
}

func dataContains(list []string, s string) bool {
	for _, v := range list {
		if v == s {
			return true
		}
	}
	return false
}

// dataGetStr is Python “d.get(key, default)“ for string-valued fields.
func dataGetStr(m jx.M, key, def string) string {
	if v, ok := m[key]; ok {
		return jx.Str(v)
	}
	return def
}

// dataRec is “record.get(key, default)“ on a CSV row.
func dataRec(r CSVRecord, key, def string) string {
	if v, ok := r[key]; ok {
		return v
	}
	return def
}

func dataInRange(day, from, to string) bool {
	if day == "" {
		return false
	}
	if from != "" && day < from {
		return false
	}
	if to != "" && day > to {
		return false
	}
	return true
}

func dataSortLower(list []string) {
	sort.SliceStable(list, func(i, j int) bool { return strings.ToLower(list[i]) < strings.ToLower(list[j]) })
}

var dataModelKeyRE = regexp.MustCompile(`[\s_]+`)

// dataModelKey slugs a model name so billing and usage-metrics spellings collapse.
func dataModelKey(model string) string {
	s := strings.ToLower(strings.TrimSpace(model))
	if strings.HasPrefix(s, "auto:") {
		s = strings.TrimSpace(s[len("auto:"):])
	}
	return dataModelKeyRE.ReplaceAllString(s, "-")
}

// ---------------------------------------------------------------------------
// Enterprise team member filters
// ---------------------------------------------------------------------------

const dataNoEnterpriseTeam = "__no_team__"

// dataMemberFilter is a membership test over lowercased logins; nil means "no filter".
type dataMemberFilter struct {
	kind    int // 0 = set, 1 = users without team, 2 = all-of
	set     jx.StrSet
	subs    []*dataMemberFilter
	isSet   bool
	members int
}

func (f *dataMemberFilter) has(login string) bool {
	switch f.kind {
	case 1:
		return !f.set.Has(login)
	case 2:
		for _, s := range f.subs {
			if !s.has(login) {
				return false
			}
		}
		return true
	}
	return f.set.Has(login)
}

func dataSetFilter(s jx.StrSet) *dataMemberFilter {
	return &dataMemberFilter{kind: 0, set: s, isSet: true}
}

func dataWithUserFilter(base *dataMemberFilter, user string) *dataMemberFilter {
	login := strings.ToLower(strings.TrimSpace(user))
	if login == "" {
		return base
	}
	single := dataSetFilter(jx.StrSet{login: {}})
	if base == nil {
		return single
	}
	return &dataMemberFilter{kind: 2, subs: []*dataMemberFilter{base, single}}
}

func dataAllTeamMemberLogins(l *dataLoader) jx.StrSet {
	logins := jx.StrSet{}
	keys, all := l.allLatest("enterprise_teams")
	for _, k := range keys {
		data := jx.Map(all[k])
		if data == nil {
			continue
		}
		for _, team := range jx.GetMaps(data, "teams") {
			for _, m := range jx.GetMaps(team, "members") {
				if login := jx.Str(m["login"]); jx.Truthy(m["login"]) {
					logins.Add(strings.ToLower(login))
				}
			}
		}
	}
	return logins
}

func dataSeatLoginsWithoutTeam(l *dataLoader) jx.StrSet {
	teamLogins := dataAllTeamMemberLogins(l)
	out := jx.StrSet{}
	keys, all := l.allLatest("seats")
	for _, k := range keys {
		sd := jx.Map(all[k])
		if sd == nil {
			continue
		}
		for _, seat := range jx.GetMaps(sd, "seats") {
			login := strings.ToLower(jx.Str(jx.GetMap(seat, "assignee")["login"]))
			if login != "" && !teamLogins.Has(login) {
				out.Add(login)
			}
		}
	}
	return out
}

// dataTeamMemberLogins resolves an enterprise team slug (or name) to a filter.
func dataTeamMemberLogins(l *dataLoader, teamSlug string) *dataMemberFilter {
	if strings.TrimSpace(teamSlug) == "" {
		return nil
	}
	wanted := strings.ToLower(strings.TrimSpace(teamSlug))
	if wanted == dataNoEnterpriseTeam {
		return &dataMemberFilter{kind: 1, set: dataAllTeamMemberLogins(l)}
	}
	keys, all := l.allLatest("enterprise_teams")
	for _, k := range keys {
		data := jx.Map(all[k])
		if data == nil {
			continue
		}
		for _, team := range jx.GetMaps(data, "teams") {
			if strings.ToLower(dataGetStr(team, "slug", "")) == wanted || strings.ToLower(dataGetStr(team, "name", "")) == wanted {
				s := jx.StrSet{}
				for _, m := range jx.GetMaps(team, "members") {
					if jx.Truthy(m["login"]) {
						s.Add(strings.ToLower(dataGetStr(m, "login", "")))
					}
				}
				return dataSetFilter(s)
			}
		}
	}
	return dataSetFilter(jx.StrSet{})
}

func dataEnterpriseTeamOptions(l *dataLoader) jx.L {
	type opt struct {
		m    jx.M
		name string
	}
	opts := []opt{}
	keys, all := l.allLatest("enterprise_teams")
	for _, k := range keys {
		data := jx.Map(all[k])
		if data == nil {
			continue
		}
		for _, team := range jx.GetMaps(data, "teams") {
			slug := jx.GetOr(team, "slug", "")
			if !jx.Truthy(slug) {
				continue
			}
			name := jx.GetOr(team, "name", slug)
			opts = append(opts, opt{m: jx.M{
				"slug":         slug,
				"name":         name,
				"enterprise":   jx.GetOr(data, "enterprise", ""),
				"member_count": jx.GetOr(team, "member_count", 0),
			}, name: strings.ToLower(jx.Str(name))})
		}
	}
	sort.SliceStable(opts, func(i, j int) bool { return opts[i].name < opts[j].name })
	out := jx.L{}
	for _, o := range opts {
		out = append(out, o.m)
	}
	out = append(out, jx.M{
		"slug":         dataNoEnterpriseTeam,
		"name":         "(No enterprise team)",
		"enterprise":   "",
		"member_count": len(dataSeatLoginsWithoutTeam(l)),
	})
	return out
}

// ---------------------------------------------------------------------------
// Simple endpoints
// ---------------------------------------------------------------------------

func dataUserRoster(c *Ctx) any {
	return jx.M{"users": BuildUserRoster()}
}

func dataOrgs(c *Ctx) any {
	l := newDataLoader()
	orgsList := []jx.M{}
	for _, info := range APIs.AllOrgs() {
		name := jx.Str(info["login"])
		billingAny := l.latest("billing", name)
		billing := jx.Map(billingAny)
		org := jx.M{
			"login":       info["login"],
			"avatar_url":  info["avatar_url"],
			"description": info["description"],
			"has_copilot": billingAny != nil,
			"enterprise":  jx.GetOr(info, "enterprise", "Independent"),
			"pat_user":    jx.GetOr(info, "pat_user", ""),
		}
		if jx.Truthy(billingAny) {
			org["plan_type"] = jx.GetOr(billing, "_detected_plan_type", "unknown")
			org["price_per_seat"] = jx.GetOr(billing, "_detected_price_per_seat", 0)
			sb := jx.Map(jx.GetOr(billing, "seat_breakdown", jx.M{}))
			org["total_seats"] = jx.GetOr(sb, "total", 0)
			org["active_seats"] = jx.GetOr(sb, "active_this_cycle", 0)
		}
		orgsList = append(orgsList, org)
	}
	groups := newDataOM[*[]jx.M]()
	for _, org := range orgsList {
		g := groups.at(jx.Str(jx.GetOr(org, "enterprise", "Independent")), func() *[]jx.M { return &[]jx.M{} })
		*g = append(*g, org)
	}
	names := append([]string{}, groups.keys...)
	sort.SliceStable(names, func(i, j int) bool {
		a, b := names[i] == "Independent", names[j] == "Independent"
		if a != b {
			return !a
		}
		return names[i] < names[j]
	})
	enterprises := jx.L{}
	for _, n := range names {
		enterprises = append(enterprises, jx.M{"name": n, "orgs": *groups.m[n]})
	}
	return jx.M{"enterprises": enterprises, "orgs": orgsList, "total": len(orgsList)}
}

func dataOverview(c *Ctx) any {
	l := newDataLoader()
	allOrgs := APIs.AllOrgs()
	keys := []string{}
	for _, o := range allOrgs {
		keys = append(keys, jx.Str(o["login"]))
	}
	for _, e := range APIs.AllEnterprises() {
		keys = append(keys, EnterprisePseudoOrg(jx.Str(e["slug"])))
	}
	var totalSeats, totalActive, totalCost, totalWaste float64
	withCopilot := 0
	for _, name := range keys {
		billing := l.latestMap("billing", name)
		if !jx.Truthy(billing) {
			continue
		}
		withCopilot++
		price := jx.Float(jx.GetOr(billing, "_detected_price_per_seat", 19.0))
		sb := jx.Map(jx.GetOr(billing, "seat_breakdown", jx.M{}))
		seats := jx.Float(jx.GetOr(sb, "total", 0))
		active := jx.Float(jx.GetOr(sb, "active_this_cycle", 0))
		totalSeats += seats
		totalActive += active
		totalCost += seats * price
		totalWaste += (seats - active) * price
	}
	var util any = 0
	if totalSeats > 0 {
		util = jx.Round(totalActive/totalSeats*100, 1)
	}
	return jx.M{
		"total_organizations":  len(allOrgs),
		"orgs_with_copilot":    withCopilot,
		"total_seats":          totalSeats,
		"total_active_seats":   totalActive,
		"total_inactive_seats": totalSeats - totalActive,
		"utilization_pct":      util,
		"monthly_cost":         totalCost,
		"monthly_waste":        totalWaste,
		"annual_waste":         totalWaste * 12,
	}
}

func dataSeats(c *Ctx) any {
	org := c.Path("org")
	data := Collector.LoadLatest("seats", org)
	if !jx.Truthy(data) {
		return jx.M{"error": "No seat data for " + org}
	}
	return data
}

func dataBilling(c *Ctx) any {
	org := c.Path("org")
	data := Collector.LoadLatest("billing", org)
	if !jx.Truthy(data) {
		return jx.M{"error": "No billing data for " + org}
	}
	return data
}

func dataCSVInfo(c *Ctx) any {
	return jx.M{
		"ai_usage":     ScanCSVType(CSVTypeAI),
		"usage_report": ScanCSVType(CSVTypeUsage),
	}
}
