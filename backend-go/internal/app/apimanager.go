package app

import (
	"context"
	"fmt"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/satomic/octofinance/backend-go/internal/ghapi"
	"github.com/satomic/octofinance/backend-go/internal/githost"
	"github.com/satomic/octofinance/backend-go/internal/jx"
)

// APIManager manages one GitHub client per PAT plus aggregated discovery
// results (orgs with enterprise grouping, enterprises, users).
type APIManager struct {
	mu              sync.RWMutex
	rebuildMu       sync.Mutex
	recovering      atomic.Bool
	instances       map[string]*ghapi.Client // pat_id -> client
	instanceOrder   []string
	orgToPat        map[string]string
	allOrgs         []jx.M
	discoveredUsers map[string]jx.M // pat_id -> user
	userOrder       []string
	allEnterprises  []jx.M
}

// APIs is the global API manager.
var APIs = &APIManager{
	instances:       map[string]*ghapi.Client{},
	orgToPat:        map[string]string{},
	discoveredUsers: map[string]jx.M{},
}

type discovery struct {
	user        jx.M
	orgs        []jx.M
	enterprises []jx.M
}

// discover runs user/org/enterprise discovery for one PAT outside the lock.
func discoverPAT(ctx context.Context, pat jx.M, api *ghapi.Client, verbose bool) (*discovery, error) {
	label := jx.Str(pat["label"])
	patID := jx.Str(pat["id"])
	host := jx.OrStr(pat, "host", githost.DefaultHost)

	user, err := api.DiscoverUser(ctx)
	if err != nil {
		return nil, err
	}
	if verbose {
		printf("[APIManager] PAT '%s' authenticated as: %s", label, jx.GetStr(user, "login", "unknown"))
	}
	Pats.Update(patID, jx.M{"user_login": jx.GetStr(user, "login"), "user_avatar": jx.GetStr(user, "avatar_url")})

	includeOrgs := jx.GetBoolDef(pat, "include_organizations", true)
	var orgs []jx.M
	if includeOrgs {
		orgs, err = api.DiscoverOrgs(ctx)
		if err != nil {
			orgs = nil
			if verbose {
				printf("[APIManager] Failed to discover organizations for PAT '%s': %v", label, err)
			}
		}
	} else if verbose {
		printf("[APIManager] PAT '%s' has organization scanning disabled, skipping org discovery", label)
	}
	logins := jx.L{}
	for _, o := range orgs {
		logins = append(logins, jx.Str(o["login"]))
	}
	Pats.Update(patID, jx.M{"orgs": logins})
	if includeOrgs && verbose {
		printf("[APIManager] PAT '%s' has %d orgs: %v", label, len(orgs), logins)
	}

	entries := []jx.M{}
	for _, o := range orgs {
		login := jx.Str(o["login"])
		enterprise := "Unknown"
		detail, derr := api.GetOrgDetail(ctx, login)
		if derr == nil {
			enterprise = strings.TrimSpace(jx.GetStr(detail, "company"))
			if enterprise == "" {
				enterprise = "Independent"
			}
		} else if verbose {
			printf("[APIManager] Failed to get detail for %s: %v", login, derr)
		}
		entries = append(entries, jx.Merge(o, jx.M{
			"enterprise": enterprise,
			"pat_id":     patID,
			"pat_label":  label,
			"pat_user":   jx.GetStr(user, "login"),
			"host":       host,
		}))
	}

	var ents []jx.M
	manual := jx.Strings(pat["enterprise_slugs"])
	if len(manual) > 0 {
		for _, s := range manual {
			ents = append(ents, jx.M{"slug": s, "name": s, "id": nil, "role": "member"})
		}
		if verbose {
			printf("[APIManager] PAT '%s' using %d manually specified enterprise(s): %v", label, len(ents), manual)
		}
	} else {
		ents = api.DiscoverEnterprises(ctx)
		if verbose {
			slugs := []string{}
			for _, e := range ents {
				slugs = append(slugs, jx.Str(e["slug"]))
			}
			printf("[APIManager] PAT '%s' auto-discovered %d enterprise(s): %v", label, len(ents), slugs)
		}
	}
	entEntries := []jx.M{}
	for _, e := range ents {
		entEntries = append(entEntries, jx.Merge(e, jx.M{
			"pat_id":    patID,
			"pat_label": label,
			"pat_user":  jx.GetStr(user, "login"),
			"host":      host,
		}))
	}
	Pats.Update(patID, jx.M{"last_synced_at": jx.NowISO()})
	return &discovery{user: user, orgs: entries, enterprises: entEntries}, nil
}

// merge folds one PAT's discovery into the aggregate (first PAT wins). Caller holds mu.
func (a *APIManager) mergeLocked(patID string, d *discovery) {
	if _, ok := a.discoveredUsers[patID]; !ok {
		a.userOrder = append(a.userOrder, patID)
	}
	a.discoveredUsers[patID] = d.user
	for _, o := range d.orgs {
		login := jx.Str(o["login"])
		if _, ok := a.orgToPat[login]; !ok {
			a.orgToPat[login] = patID
		}
		dup := false
		for _, existing := range a.allOrgs {
			if jx.Str(existing["login"]) == login {
				dup = true
				break
			}
		}
		if !dup {
			a.allOrgs = append(a.allOrgs, o)
		}
	}
	for _, e := range d.enterprises {
		slug := jx.Str(e["slug"])
		dup := false
		for _, existing := range a.allEnterprises {
			if jx.Str(existing["slug"]) == slug {
				dup = true
				break
			}
		}
		if !dup {
			a.allEnterprises = append(a.allEnterprises, e)
		}
	}
}

// Rebuild reloads all PATs and reruns discovery for each. If a PAT could not
// be discovered because GitHub was unreachable, discovery is retried in the
// background (see scheduleRecovery).
func (a *APIManager) Rebuild(ctx context.Context) {
	a.rebuildLocked(ctx)
	a.scheduleRecovery()
}

func (a *APIManager) rebuildLocked(ctx context.Context) {
	a.rebuildMu.Lock()
	defer a.rebuildMu.Unlock()

	pats := Pats.GetAll()
	instances := map[string]*ghapi.Client{}
	order := []string{}
	fresh := &APIManager{instances: instances, orgToPat: map[string]string{}, discoveredUsers: map[string]jx.M{}}
	if len(pats) == 0 {
		printf("[APIManager] No PATs configured, skipping discovery.")
	}
	for _, pat := range pats {
		patID := jx.Str(pat["id"])
		host := jx.OrStr(pat, "host", githost.DefaultHost)
		api := ghapi.New(jx.Str(pat["token"]), githost.APIBase(host))
		instances[patID] = api
		order = append(order, patID)
		d, err := discoverPAT(ctx, pat, api, true)
		if err != nil {
			printf("[APIManager] Failed to discover for PAT '%s': %T: %v", jx.Str(pat["label"]), err, err)
			CredRecordFailure(patID, err)
			continue
		}
		fresh.mergeLocked(patID, d)
	}

	a.mu.Lock()
	a.instances = instances
	a.instanceOrder = order
	a.orgToPat = fresh.orgToPat
	a.allOrgs = fresh.allOrgs
	a.discoveredUsers = fresh.discoveredUsers
	a.userOrder = fresh.userOrder
	a.allEnterprises = fresh.allEnterprises
	a.mu.Unlock()
}

// Discovery recovery: a PAT whose discovery failed only because GitHub could
// not be reached (a dropped connection at startup) contributes no organizations,
// so every dashboard would show no data until the next sync. Instead, discovery
// is retried in the background with a growing interval until it succeeds.

var recoveryDelays = []time.Duration{5 * time.Second, 10 * time.Second, 20 * time.Second,
	40 * time.Second, 80 * time.Second, 160 * time.Second, 5 * time.Minute}

// recoverable lists PATs that are not discovered and were not rejected by GitHub.
func (a *APIManager) recoverable() []string {
	discovered := a.DiscoveredUsers()
	out := []string{}
	for _, pat := range Pats.GetAll() {
		id := jx.Str(pat["id"])
		if discovered[id] != nil {
			continue
		}
		state := jx.Str(jx.GetMap(pat, "credential")["state"])
		if state == "invalid" || state == "forbidden" {
			continue // a rejected token is reported in the UI; retrying cannot fix it
		}
		out = append(out, jx.Str(pat["label"]))
	}
	return out
}

func (a *APIManager) scheduleRecovery() {
	if len(a.recoverable()) == 0 || !a.recovering.CompareAndSwap(false, true) {
		return
	}
	go func() {
		defer a.recovering.Store(false)
		for attempt := 0; attempt < 30; attempt++ {
			delay := recoveryDelays[len(recoveryDelays)-1]
			if attempt < len(recoveryDelays) {
				delay = recoveryDelays[attempt]
			}
			pending := a.recoverable()
			if len(pending) == 0 {
				return
			}
			printf("[APIManager] Discovery incomplete for PAT(s) %v (GitHub unreachable); retrying in %s", pending, delay)
			time.Sleep(delay)
			if len(a.recoverable()) == 0 {
				return // a sync or PAT change re-discovered in the meantime
			}
			ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
			a.rebuildLocked(ctx)
			cancel()
			if len(a.recoverable()) == 0 {
				// The outage left these PATs marked "unreachable"; re-check so the
				// UI's sync-failure banner reflects the real token state again.
				checkCtx, checkCancel := context.WithTimeout(context.Background(), time.Minute)
				CredCheckAll(checkCtx, nil)
				checkCancel()
				msg := fmt.Sprintf("GitHub was unreachable at startup; discovery recovered: %d organizations, %d enterprises",
					len(a.AllOrgLogins()), len(a.AllEnterprises()))
				printf("[APIManager] %s", msg)
				Syncs.NotifyDataChanged(msg) // open pages reload instead of showing "no data"
				return
			}
		}
	}()
}

// AddAndDiscover adds one PAT's client and runs discovery. Returns the user.
func (a *APIManager) AddAndDiscover(ctx context.Context, patID string) (jx.M, error) {
	pat := Pats.FindByID(patID)
	if pat == nil {
		return nil, fmt.Errorf("PAT %s not found", patID)
	}
	host := jx.OrStr(pat, "host", githost.DefaultHost)
	api := ghapi.New(jx.Str(pat["token"]), githost.APIBase(host))
	if _, err := api.DiscoverUser(ctx); err != nil {
		return nil, fmt.Errorf("Invalid token: could not authenticate with %s", host)
	}
	d, err := discoverPAT(ctx, pat, api, false)
	if err != nil {
		return nil, fmt.Errorf("Invalid token: could not authenticate with %s", host)
	}
	a.mu.Lock()
	if _, ok := a.instances[patID]; !ok {
		a.instanceOrder = append(a.instanceOrder, patID)
	}
	a.instances[patID] = api
	a.mergeLocked(patID, d)
	a.mu.Unlock()
	return d.user, nil
}

// RemoveAPI drops a PAT's client and everything discovered through it.
func (a *APIManager) RemoveAPI(patID string) {
	a.mu.Lock()
	defer a.mu.Unlock()
	delete(a.instances, patID)
	order := []string{}
	for _, id := range a.instanceOrder {
		if id != patID {
			order = append(order, id)
		}
	}
	a.instanceOrder = order
	delete(a.discoveredUsers, patID)
	users := []string{}
	for _, id := range a.userOrder {
		if id != patID {
			users = append(users, id)
		}
	}
	a.userOrder = users
	orgs := []jx.M{}
	for _, o := range a.allOrgs {
		if jx.Str(o["pat_id"]) != patID {
			orgs = append(orgs, o)
		}
	}
	a.allOrgs = orgs
	a.orgToPat = map[string]string{}
	for _, o := range a.allOrgs {
		a.orgToPat[jx.Str(o["login"])] = jx.Str(o["pat_id"])
	}
	ents := []jx.M{}
	for _, e := range a.allEnterprises {
		if jx.Str(e["pat_id"]) != patID {
			ents = append(ents, e)
		}
	}
	a.allEnterprises = ents
}

func (a *APIManager) firstInstanceLocked() *ghapi.Client {
	for _, id := range a.instanceOrder {
		if c, ok := a.instances[id]; ok {
			return c
		}
	}
	return nil
}

// APIForOrg returns the client with access to org (falls back to the first client).
func (a *APIManager) APIForOrg(org string) *ghapi.Client {
	a.mu.RLock()
	defer a.mu.RUnlock()
	if patID, ok := a.orgToPat[org]; ok {
		return a.instances[patID]
	}
	return a.firstInstanceLocked()
}

// APIForEnterprise returns the client with access to an enterprise (falls back to the first client).
func (a *APIManager) APIForEnterprise(slug string) *ghapi.Client {
	a.mu.RLock()
	defer a.mu.RUnlock()
	for _, e := range a.allEnterprises {
		if jx.Str(e["slug"]) == slug {
			if c, ok := a.instances[jx.Str(e["pat_id"])]; ok {
				return c
			}
		}
	}
	return a.firstInstanceLocked()
}

// AllOrgs returns discovered orgs (copies).
func (a *APIManager) AllOrgs() []jx.M {
	a.mu.RLock()
	defer a.mu.RUnlock()
	out := make([]jx.M, len(a.allOrgs))
	for i, o := range a.allOrgs {
		out[i] = jx.Copy(o)
	}
	return out
}

// AllEnterprises returns discovered enterprises (copies).
func (a *APIManager) AllEnterprises() []jx.M {
	a.mu.RLock()
	defer a.mu.RUnlock()
	out := make([]jx.M, len(a.allEnterprises))
	for i, e := range a.allEnterprises {
		out[i] = jx.Copy(e)
	}
	return out
}

// EnterprisePseudoOrgs returns enterprises whose PAT discovered no orgs — those
// get enterprise-level usage aggregation.
func (a *APIManager) EnterprisePseudoOrgs() []jx.M {
	a.mu.RLock()
	defer a.mu.RUnlock()
	perPat := map[string]int{}
	for _, o := range a.allOrgs {
		if id := jx.Str(o["pat_id"]); id != "" {
			perPat[id]++
		}
	}
	out := []jx.M{}
	for _, e := range a.allEnterprises {
		if perPat[jx.Str(e["pat_id"])] == 0 {
			out = append(out, jx.Copy(e))
		}
	}
	return out
}

// HostForOrg returns the GitHub host an org was discovered on.
func (a *APIManager) HostForOrg(org string) string {
	a.mu.RLock()
	for _, o := range a.allOrgs {
		if jx.Str(o["login"]) == org {
			h := jx.OrStr(o, "host", githost.DefaultHost)
			a.mu.RUnlock()
			return h
		}
	}
	a.mu.RUnlock()
	if strings.HasSuffix(org, "-enterprise") {
		return a.HostForEnterprise(strings.TrimSuffix(org, "-enterprise"))
	}
	return defaultHost()
}

// HostForEnterprise returns the GitHub host an enterprise belongs to.
func (a *APIManager) HostForEnterprise(slug string) string {
	a.mu.RLock()
	defer a.mu.RUnlock()
	for _, e := range a.allEnterprises {
		if jx.Str(e["slug"]) == slug {
			return jx.OrStr(e, "host", githost.DefaultHost)
		}
	}
	return defaultHost()
}

// WebBaseForOrg is the web URL base for an org's host.
func (a *APIManager) WebBaseForOrg(org string) string { return githost.WebBase(a.HostForOrg(org)) }

// WebBaseForEnterprise is the web URL base for an enterprise's host.
func (a *APIManager) WebBaseForEnterprise(slug string) string {
	return githost.WebBase(a.HostForEnterprise(slug))
}

func defaultHost() string {
	pats := Pats.GetAll()
	if len(pats) > 0 {
		return jx.OrStr(pats[0], "host", githost.DefaultHost)
	}
	return githost.DefaultHost
}

// DiscoveredUsers returns pat_id -> user.
func (a *APIManager) DiscoveredUsers() map[string]jx.M {
	a.mu.RLock()
	defer a.mu.RUnlock()
	out := make(map[string]jx.M, len(a.discoveredUsers))
	for k, v := range a.discoveredUsers {
		out[k] = v
	}
	return out
}

// DiscoveredLogins returns the logins of discovered PAT users in discovery order.
func (a *APIManager) DiscoveredLogins() []string {
	a.mu.RLock()
	defer a.mu.RUnlock()
	out := []string{}
	for _, id := range a.userOrder {
		if u, ok := a.discoveredUsers[id]; ok {
			out = append(out, jx.GetStr(u, "login"))
		}
	}
	return out
}

// AllOrgLogins returns all discovered org logins.
func (a *APIManager) AllOrgLogins() []string {
	a.mu.RLock()
	defer a.mu.RUnlock()
	out := []string{}
	for _, o := range a.allOrgs {
		out = append(out, jx.Str(o["login"]))
	}
	return out
}

// HasInstances reports whether any client exists.
func (a *APIManager) HasInstances() bool {
	a.mu.RLock()
	defer a.mu.RUnlock()
	return len(a.instances) > 0
}
