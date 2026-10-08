package app

import (
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"

	"github.com/satomic/octofinance/backend-go/internal/jx"
)

// Helpers shared by several route files (Python: routers.data._append_audit_log,
// routers.me.resolve_period, routers.budget_requests._load/_save,
// services.cost_center_owners).

// ---------------------------------------------------------------------------
// Audit log (data/audit_log.json)
// ---------------------------------------------------------------------------

// AppendAuditLog appends an entry to data/audit_log.json.
func AppendAuditLog(entry jx.M) {
	path := filepath.Join(Collector.DataDir(), "audit_log.json")
	mu := jx.FileLock(path)
	mu.Lock()
	defer mu.Unlock()
	logs := jx.List(jx.ReadJSONOr(path, jx.L{}))
	if logs == nil {
		logs = jx.L{}
	}
	logs = append(logs, entry)
	_ = jx.WriteJSON(path, logs)
}

// ---------------------------------------------------------------------------
// Period switch
// ---------------------------------------------------------------------------

// ResolvePeriod translates the UI period switch into a date window:
// "current_month" overrides any explicit range.
func ResolvePeriod(period, dateFrom, dateTo string) (mode, from, to string) {
	m := strings.ToLower(strings.TrimSpace(period))
	if m == "" {
		m = "all"
	}
	if m == "current_month" {
		start, end := CurrentMonthRange()
		return "current_month", start, end
	}
	return "all", dateFrom, dateTo
}

// ---------------------------------------------------------------------------
// Budget / cost center requests (data/budget_requests.json)
// ---------------------------------------------------------------------------

// BudgetRequestsMu guards read-modify-write of budget_requests.json.
var BudgetRequestsMu sync.Mutex

// BudgetRequestsFile is data/budget_requests.json.
func BudgetRequestsFile() string { return dataPath("budget_requests.json") }

// LoadBudgetRequests returns all requests (accepts a list or {"requests": [...]}).
func LoadBudgetRequests() []jx.M {
	raw, err := jx.ReadJSON(BudgetRequestsFile())
	if err != nil {
		return []jx.M{}
	}
	if l := jx.List(raw); l != nil {
		return jx.Maps(l)
	}
	if m := jx.Map(raw); m != nil {
		return jx.GetMaps(m, "requests")
	}
	return []jx.M{}
}

// SaveBudgetRequests persists requests as {"requests": [...]}.
func SaveBudgetRequests(requests []jx.M) {
	if requests == nil {
		requests = []jx.M{}
	}
	_ = jx.WriteJSON(BudgetRequestsFile(), jx.M{"requests": requests})
}

// LoadRequestsFor returns all requests submitted by a user.
func LoadRequestsFor(login string) []jx.M {
	out := []jx.M{}
	for _, r := range LoadBudgetRequests() {
		if strings.EqualFold(jx.Str(r["user_login"]), login) {
			out = append(out, r)
		}
	}
	return out
}

// ---------------------------------------------------------------------------
// Cost center ownership (data/cc_owners.json):
// {enterprise: {cost_center_id: {login_lower: {granted_by, granted_at}}}}
// ---------------------------------------------------------------------------

var ccOwnersMu sync.Mutex

func ccOwnersFile() string { return dataPath("cc_owners.json") }

// LoadCCOwners returns the ownership map.
func LoadCCOwners() jx.M {
	m := jx.Map(jx.ReadJSONOr(ccOwnersFile(), jx.M{}))
	if m == nil {
		return jx.M{}
	}
	return m
}

// CCOwnerLogins returns the sorted owner logins of one cost center.
func CCOwnerLogins(enterprise, costCenterID string) []string {
	owners := jx.GetMap(jx.GetMap(LoadCCOwners(), enterprise), costCenterID)
	return jx.SortedKeys(owners)
}

// SetCCOwner grants or revokes ownership.
func SetCCOwner(enterprise, costCenterID, login string, enabled bool, actor string) {
	ccOwnersMu.Lock()
	defer ccOwnersMu.Unlock()
	withFlock(strings.TrimSuffix(ccOwnersFile(), ".json")+".lock", func() {
		owners := LoadCCOwners()
		ent := jx.Map(owners[enterprise])
		if ent == nil {
			ent = jx.M{}
			owners[enterprise] = ent
		}
		members := jx.Map(ent[costCenterID])
		if members == nil {
			members = jx.M{}
			ent[costCenterID] = members
		}
		if enabled {
			members[strings.ToLower(login)] = jx.M{"granted_by": actor, "granted_at": jx.NowISO()}
		} else {
			delete(members, strings.ToLower(login))
		}
		_ = os.MkdirAll(filepath.Dir(ccOwnersFile()), 0o755)
		_ = jx.WriteJSON(ccOwnersFile(), owners)
	})
}

// OwnedCostCenters lists active cost centers the user owns and is a member of.
func OwnedCostCenters(login string) []jx.M {
	result := []jx.M{}
	target := strings.ToLower(login)
	for enterprise, centersAny := range LoadCCOwners() {
		centers := jx.Map(centersAny)
		snapshot := Collector.LoadLatestMap("cost_centers", enterprise)
		for _, center := range jx.GetMaps(snapshot, "cost_centers") {
			state := "active"
			if v, ok := center["state"]; ok {
				state = jx.Str(v)
			}
			if state != "active" {
				continue
			}
			if _, ok := jx.GetMap(centers, jx.Str(center["id"]))[target]; !ok {
				continue
			}
			member := false
			for _, m := range jx.GetMaps(center, "members") {
				if strings.ToLower(jx.Str(m["login"])) == target {
					member = true
					break
				}
			}
			if !member {
				continue
			}
			result = append(result, jx.M{"enterprise": enterprise, "id": jx.Str(center["id"]), "name": center["name"]})
		}
	}
	sort.SliceStable(result, func(i, j int) bool {
		a, b := jx.Str(result[i]["enterprise"]), jx.Str(result[j]["enterprise"])
		if a != b {
			return a < b
		}
		return strings.ToLower(jx.Str(result[i]["name"])) < strings.ToLower(jx.Str(result[j]["name"]))
	})
	return result
}
