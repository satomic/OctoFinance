package app

import (
	"bytes"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"time"

	copilot "github.com/github/copilot-sdk/go"

	"github.com/satomic/octofinance/backend-go/internal/ghapi"
	"github.com/satomic/octofinance/backend-go/internal/jx"
)

// Port of backend/app/tools/seat_tools.py.

func init() { registerTools(seatTools) }

// ---------------------------------------------------------------------------
// Helpers shared by the tools_*.go files of this area (seat/usage/billing/...)
// ---------------------------------------------------------------------------

// seatToolOMap is a JSON object that keeps its key order (Python dict order).
type seatToolOMap struct {
	keys []string
	m    map[string]any
}

func (o seatToolOMap) MarshalJSON() ([]byte, error) {
	var buf bytes.Buffer
	buf.WriteByte('{')
	for i, k := range o.keys {
		if i > 0 {
			buf.WriteByte(',')
		}
		kb, err := jx.Marshal(k)
		if err != nil {
			return nil, err
		}
		buf.Write(kb)
		buf.WriteByte(':')
		vb, err := jx.Marshal(o.m[k])
		if err != nil {
			return nil, err
		}
		buf.Write(vb)
	}
	buf.WriteByte('}')
	return buf.Bytes(), nil
}

// seatToolDirOrder lists "<org>" for {category}/<org>_latest.json in raw
// directory order (Python's Path.glob order), primary dir first, then fallback.
func seatToolDirOrder(dc *DataCollector, category string) []string {
	out := []string{}
	seen := map[string]bool{}
	dirs := []string{dc.DataDir()}
	if dc.fallbackDir != "" {
		dirs = append(dirs, dc.fallbackDir)
	}
	for _, d := range dirs {
		f, err := os.Open(filepath.Join(d, category))
		if err != nil {
			continue
		}
		names, _ := f.Readdirnames(-1)
		f.Close()
		for _, n := range names {
			if !strings.HasSuffix(n, "_latest.json") {
				continue
			}
			org := strings.TrimSuffix(n, "_latest.json")
			if !seen[org] {
				seen[org] = true
				out = append(out, org)
			}
		}
	}
	return out
}

// seatToolAllLatest is DataCollector.LoadAllLatest plus the key order the
// Python dict would have.
func seatToolAllLatest(dc *DataCollector, category string) ([]string, map[string]any) {
	data := dc.LoadAllLatest(category)
	keys := []string{}
	added := map[string]bool{}
	add := func(k string) {
		if _, ok := data[k]; ok && !added[k] {
			added[k] = true
			keys = append(keys, k)
		}
	}
	switch category {
	case "seats":
		ent := jx.StrSet{}
		for _, e := range APIs.AllEnterprises() {
			ent.Add(EnterprisePseudoOrg(jx.Str(e["slug"])))
		}
		orgs := jx.StrSet{}
		for _, o := range APIs.AllOrgLogins() {
			orgs.Add(o)
		}
		for _, k := range seatToolDirOrder(dc, category) {
			if orgs.Has(k) {
				add(k)
			}
		}
		for _, k := range jx.SortedKeys(data) {
			add(k)
		}
	case "billing":
		for _, k := range seatToolDirOrder(dc, "billing") {
			add(k)
		}
		seatKeys, _ := seatToolAllLatest(dc, "seats")
		for _, k := range seatKeys {
			add(k)
		}
		for _, k := range jx.SortedKeys(data) {
			add(k)
		}
	default:
		for _, k := range seatToolDirOrder(dc, category) {
			add(k)
		}
		for _, k := range jx.SortedKeys(data) {
			add(k)
		}
	}
	return keys, data
}

// seatToolHTTPResult mirrors the GitHubAPI write helpers: resp.json() on
// success, {"error", "status_code", "response"} on an HTTP error status.
func seatToolHTTPResult(r *ghapi.Response) any {
	if !r.OK() {
		body := r.JSON()
		if body == nil {
			body = jx.M{"text": r.Text()}
		}
		return jx.M{"error": (&ghapi.HTTPError{Resp: r}).Error(), "status_code": r.Status, "response": body}
	}
	return r.JSON()
}

var seatToolTZRE = regexp.MustCompile(`([+-]\d{2}(:?\d{2}(:?\d{2}(\.\d+)?)?)?)$`)

// seatToolDaysInactive mirrors the try/except around datetime.fromisoformat:
// unparsable or naive timestamps (aware - naive raises TypeError) give 999.
func seatToolDaysInactive(now time.Time, lastActivity string) int {
	s := strings.Replace(lastActivity, "Z", "+00:00", -1)
	t, ok := jx.ParseISO(s)
	if !ok {
		return 999
	}
	// Naive values (no UTC offset after the time part) cannot be subtracted from an aware now.
	timePart := s
	if i := strings.IndexAny(s, "T "); i >= 0 && len(s) > 10 {
		timePart = s[i+1:]
	} else {
		return 999 // date only -> naive
	}
	if !seatToolTZRE.MatchString(timePart) {
		return 999
	}
	return jx.DaysBetween(now, t)
}

// seatToolSeatMap maps lower-cased login -> assigning_team for an org's seats.
func seatToolSeatMap(dc *DataCollector, org string) map[string]any {
	seatMap := map[string]any{}
	seats := dc.LoadLatestMap("seats", org)
	if jx.Truthy(seats) {
		for _, seat := range jx.GetMaps(seats, "seats") {
			login := jx.AsString(jx.GetOr(jx.Map(seat["assignee"]), "login", ""))
			if login != "" {
				seatMap[strings.ToLower(login)] = seat["assigning_team"]
			}
		}
	}
	return seatMap
}

// seatToolRemoveSeats is the shared org-level / team-level removal used by
// remove_user_seat and batch_remove_seats.
func seatToolRemoveSeats(tc *ToolCtx, api *ghapi.Client, org string, usernames []string) jx.L {
	ctx := tc.Context()
	seatMap := seatToolSeatMap(tc.Collector, org)
	orgLevel := []string{}
	type teamRemoval struct{ user, team string }
	teamRemovals := []teamRemoval{}
	for _, u := range usernames {
		team := jx.Map(seatMap[strings.ToLower(u)])
		if jx.Truthy(team) && jx.Truthy(team["slug"]) {
			teamRemovals = append(teamRemovals, teamRemoval{u, jx.Str(team["slug"])})
		} else {
			orgLevel = append(orgLevel, u)
		}
	}
	results := jx.L{}
	if len(orgLevel) > 0 {
		r, err := api.Do(ctx, http.MethodDelete, "/orgs/"+org+"/copilot/billing/selected_users", nil,
			jx.M{"selected_usernames": orgLevel}, nil)
		if err != nil {
			panic(err.Error())
		}
		results = append(results, jx.M{"method": "org_level", "usernames": orgLevel, "result": seatToolHTTPResult(r)})
	}
	for _, tr := range teamRemovals {
		result := api.RemoveTeamMembership(ctx, org, tr.team, tr.user)
		results = append(results, jx.M{"method": "team_level", "username": tr.user, "team": tr.team, "result": result})
	}
	return results
}

// ---------------------------------------------------------------------------
// Tools
// ---------------------------------------------------------------------------

func seatTools(tc *ToolCtx) []copilot.Tool {
	collector := tc.Collector
	return []copilot.Tool{
		defineTool("get_all_seats",
			"Get all Copilot seat assignments. Returns user list with activity info, assigned teams, and last active dates.",
			[]P{
				{Name: "org", Type: "string", Default: "", Desc: "Organization name. Leave empty to get seats for all discovered orgs."},
			}, func(a Args) any {
				org := a.Str("org")
				if org != "" {
					data := collector.LoadLatest("seats", org)
					if !jx.Truthy(data) {
						return jx.M{"error": "No seat data found for org '" + org + "'. Try syncing first."}
					}
					return data
				}
				keys, all := seatToolAllLatest(collector, "seats")
				if len(all) == 0 {
					return jx.M{"error": "No seat data found. Try syncing first."}
				}
				return seatToolOMap{keys: keys, m: all}
			}),

		defineTool("find_inactive_users",
			"Find Copilot users who have been inactive for N days. Returns list of inactive users with their last activity date and cost impact.",
			[]P{
				{Name: "org", Type: "string", Default: "", Desc: "Organization name. Leave empty for all orgs."},
				{Name: "days", Type: "integer", Default: 30, Desc: "Number of days of inactivity to consider a user inactive."},
			}, func(a Args) any {
				days := a.Int("days")
				var orgs []string
				var allSeats map[string]any
				if org := a.Str("org"); org != "" {
					orgs = []string{org}
					allSeats = collector.LoadAllLatest("seats")
				} else {
					orgs, allSeats = seatToolAllLatest(collector, "seats")
				}
				allBilling := collector.LoadAllLatest("billing")
				now := time.Now().UTC()
				inactive := []jx.M{}
				for _, org := range orgs {
					seatsData := jx.Map(allSeats[org])
					billing := jx.Map(allBilling[org])
					var price any = 19.0
					if jx.Truthy(billing) {
						price = jx.GetOr(billing, "_detected_price_per_seat", 19.0)
					}
					if !jx.Truthy(seatsData) {
						continue
					}
					for _, seat := range jx.GetMaps(seatsData, "seats") {
						lastActivity := seat["last_activity_at"]
						daysInactive := 999
						if jx.Truthy(lastActivity) {
							daysInactive = seatToolDaysInactive(now, jx.Str(lastActivity))
						}
						if daysInactive >= days {
							assignee := jx.Map(jx.GetOr(seat, "assignee", jx.M{}))
							inactive = append(inactive, jx.M{
								"org":                  org,
								"login":                jx.GetOr(assignee, "login", "unknown"),
								"last_activity_at":     lastActivity,
								"days_inactive":        daysInactive,
								"last_activity_editor": seat["last_activity_editor"],
								"monthly_cost":         price,
								"team":                 jx.Map(seat["assigning_team"])["name"],
							})
						}
					}
				}
				sort.SliceStable(inactive, func(i, j int) bool {
					return inactive[i]["days_inactive"].(int) > inactive[j]["days_inactive"].(int)
				})
				total := 0.0
				for _, u := range inactive {
					total += jx.Float(u["monthly_cost"])
				}
				return jx.M{
					"inactive_users":      inactive,
					"total_count":         len(inactive),
					"total_monthly_waste": total,
					"threshold_days":      days,
				}
			}),

		defineTool("remove_user_seat",
			"Remove Copilot seats for specified users. Automatically detects whether a user was assigned at org level or team level and uses the correct removal method. This is a destructive operation - use only after admin confirmation.",
			[]P{
				{Name: "org", Type: "string", Required: true, Desc: "Organization name"},
				{Name: "usernames", Type: "array", Items: "string", Required: true, Desc: "List of GitHub usernames to remove from Copilot"},
			}, func(a Args) any {
				org := a.Str("org")
				api := APIs.APIForOrg(org)
				if api == nil {
					return jx.M{"error": "No API client available for org '" + org + "'."}
				}
				return seatToolRemoveSeats(tc, api, org, a.Strings("usernames"))
			}),

		defineTool("add_team_member",
			"Add a user to an organization team. This grants the user team-level Copilot access if the team has Copilot enabled. Use this to assign Copilot seats via team membership.",
			[]P{
				{Name: "org", Type: "string", Required: true, Desc: "Organization name"},
				{Name: "team_slug", Type: "string", Required: true, Desc: "Team slug (e.g. 'level1-team1')"},
				{Name: "username", Type: "string", Required: true, Desc: "GitHub username to add to the team"},
				{Name: "role", Type: "string", Default: "member", Desc: "Role in the team: 'member' (default) or 'maintainer'"},
			}, func(a Args) any {
				org := a.Str("org")
				api := APIs.APIForOrg(org)
				if api == nil {
					return jx.M{"error": "No API client available for org '" + org + "'."}
				}
				// Raw request: ghapi.AddTeamMembership rewrites an empty role to "member",
				// Python sends the role as given.
				r, err := api.Do(tc.Context(), http.MethodPut,
					"/orgs/"+org+"/teams/"+a.Str("team_slug")+"/memberships/"+a.Str("username"), nil,
					jx.M{"role": a.Str("role")}, nil)
				if err != nil {
					panic(err.Error())
				}
				return seatToolHTTPResult(r)
			}),
	}
}
