package app

import (
	"context"
	"os"
	"path/filepath"
	"time"

	"github.com/satomic/octofinance/backend-go/internal/jx"
)

// Data sync triggers and the real-time sync log stream.

func init() { registerRoutes(registerSyncRoutes) }

func registerSyncRoutes(r *Router) {
	r.Handle("GET /api/sync-stream", syncStream)
	r.Handle("POST /api/sync", syncAll)
	r.Handle("POST /api/sync/dataset/{dataset}", syncDatasetRoute)
	r.Handle("POST /api/sync/{org}", syncOrgRoute)
	r.Handle("GET /api/sync/status", syncStatus)
}

// syncCollectors always includes the global collector, plus a session collector when requested.
func syncCollectors(sessionID string) []*DataCollector {
	collectors := []*DataCollector{Collector}
	if sessionID != "" && validSessionID(sessionID) {
		dir := filepath.Join(SessionsDir(), sessionID)
		_ = os.MkdirAll(dir, 0o755)
		collectors = append(collectors, NewSessionCollector(dir))
	}
	return collectors
}

func syncStream(c *Ctx) any {
	ch := Syncs.Subscribe()
	defer Syncs.Unsubscribe(ch)
	send, comment := c.SSE()
	_ = send
	ctx := c.R.Context()
	keepalive := time.NewTicker(30 * time.Second)
	defer keepalive.Stop()
	for {
		select {
		case <-ctx.Done():
			return nil
		case ev, ok := <-ch:
			if !ok {
				return nil
			}
			// Plain "data: {...}\n\n" frames, as the Python StreamingResponse wrote them.
			if _, err := c.W.Write([]byte("data: " + jx.Dumps(ev) + "\n\n")); err != nil {
				return nil
			}
			if f, ok := c.W.(interface{ Flush() }); ok {
				f.Flush()
			}
		case <-keepalive.C:
			if comment("keepalive") != nil {
				return nil
			}
		}
	}
}

func syncAll(c *Ctx) any {
	if Syncs.IsSyncing() {
		return jx.M{"status": "already_syncing"}
	}
	collectors := syncCollectors(c.Query("session_id"))
	Syncs.RunInBackground(func(ctx context.Context, logFn LogFn) {
		for _, dc := range collectors {
			dc.SyncAll(ctx, logFn)
		}
	}, "manual")
	return jx.M{"status": "started"}
}

func syncDatasetRoute(c *Ctx) any {
	dataset := c.Path("dataset")
	if dataset != "cost_centers" && dataset != "budgets" && dataset != "enterprise_teams" {
		return jx.M{"status": "error", "error": "Unsupported dataset '" + dataset + "'"}
	}
	if Syncs.IsSyncing() {
		return jx.M{"status": "already_syncing"}
	}
	collectors := syncCollectors(c.Query("session_id"))
	Syncs.RunInBackground(func(ctx context.Context, logFn LogFn) {
		for _, dc := range collectors {
			dc.SyncDataset(ctx, dataset, logFn)
		}
	}, "manual")
	return jx.M{"status": "started", "dataset": dataset}
}

func syncOrgRoute(c *Ctx) any {
	org := c.Path("org")
	if Syncs.IsSyncing() {
		return jx.M{"status": "already_syncing"}
	}
	collectors := syncCollectors(c.Query("session_id"))
	Syncs.RunInBackground(func(ctx context.Context, logFn LogFn) {
		for _, dc := range collectors {
			dc.SyncOrg(ctx, org, logFn)
		}
	}, "manual")
	return jx.M{"status": "started"}
}

func syncStatus(c *Ctx) any {
	orgs := []jx.M{}
	allSeats := Collector.LoadAllLatest("seats")
	allBilling := Collector.LoadAllLatest("billing")
	for _, o := range APIs.AllOrgs() {
		name := jx.Str(o["login"])
		has := func(cat string) bool { return Collector.LoadLatest(cat, name) != nil }
		orgs = append(orgs, jx.M{
			"org":             name,
			"has_seats":       allSeats[name] != nil,
			"has_billing":     allBilling[name] != nil,
			"has_usage":       has("usage"),
			"has_usage_users": has("usage_users"),
			"has_metrics":     has("metrics"),
			"has_ai_credits":  has("ai_credits"),
		})
	}
	return jx.M{
		"users":      APIs.DiscoveredLogins(),
		"total_orgs": len(orgs),
		"orgs":       orgs,
		"is_syncing": Syncs.IsSyncing(),
	}
}
