package app

import (
	"context"
	"strings"
	"sync"
	"time"

	copilot "github.com/github/copilot-sdk/go"

	"github.com/satomic/octofinance/backend-go/internal/jx"
)

// Port of backend/app/tools/sync_tools.py: refreshes the GLOBAL cache through
// the shared SyncManager, exactly like the Sync Data button.

func init() { registerTools(syncTools) }

var syncToolDatasets = []string{"cost_centers", "budgets", "enterprise_teams"}

const (
	// A narrow dataset sync takes seconds; a full sync can take minutes on large estates.
	syncToolWaitTimeout = 600 * time.Second
	// A sync started elsewhere may include a long billing CSV fetch; chat only
	// waits this long for it before refreshing the requested dataset itself.
	syncToolBusyWait = 60 * time.Second
)

func syncToolIsDataset(d string) bool {
	for _, x := range syncToolDatasets {
		if x == d {
			return true
		}
	}
	return false
}

func syncToolResult(status, dataset, org string, startedAt time.Time, summaries []SyncSummary) jx.M {
	synced := []string{}
	errs := []string{}
	for _, s := range summaries {
		synced = append(synced, summaryList(s, "synced")...)
		errs = append(errs, summaryList(s, "errors")...)
	}
	var orgVal any
	if org != "" {
		orgVal = org
	}
	return jx.M{
		"status":           status,
		"dataset":          dataset,
		"org":              orgVal,
		"duration_seconds": jx.Round(time.Since(startedAt).Seconds(), 1),
		"synced_count":     len(synced),
		"synced":           synced[:min(len(synced), 50)],
		"errors":           errs[:min(len(errs), 20)],
		"error_count":      len(errs),
	}
}

func syncTools(tc *ToolCtx) []copilot.Tool {
	return []copilot.Tool{
		defineTool("sync_data",
			"Refresh OctoFinance's cached GitHub data (the same as the Sync Data button) and wait "+
				"for it to finish. Call this when cached data is missing or stale, in particular right "+
				"after a live write such as create_cost_center, add_cost_center_resources or "+
				"create_enterprise_team, before using a tool that reads the cache (for example "+
				"create_cost_center_budget, get_synced_enterprise_data, get_all_budgets summaries). "+
				"Does not fetch billing report CSVs.",
			[]P{
				{Name: "dataset", Type: "string", Default: "all", Desc: "What to refresh: 'cost_centers', 'budgets' or 'enterprise_teams' for a fast " +
					"enterprise-scoped refresh, or 'all' for the full Sync Data (every org's seats, " +
					"usage, billing and AI credits, plus all enterprise data). Prefer the narrowest " +
					"dataset that covers what changed."},
				{Name: "org", Type: "string", Default: "", Desc: "Only with dataset='all': sync just this organization instead of everything."},
			}, func(a Args) any {
				rawDataset := a.Str("dataset")
				dataset := rawDataset
				if dataset == "" {
					dataset = "all"
				}
				dataset = strings.ToLower(strings.TrimSpace(dataset))
				org := strings.TrimSpace(a.Str("org"))
				if dataset != "all" && !syncToolIsDataset(dataset) {
					return jx.M{"error": "Unknown dataset '" + rawDataset + "'. Use 'all' or one of " + pyStrList(syncToolDatasets) + "."}
				}
				if org != "" && dataset != "all" {
					return jx.M{"error": "'org' can only be combined with dataset='all'."}
				}

				if Syncs.IsSyncing() {
					finished := Syncs.WaitUntilIdle(syncToolBusyWait)
					if !finished && syncToolIsDataset(dataset) {
						startedAt := time.Now()
						Syncs.Log("info", "[chat] Refreshing "+dataset+" while another sync is running")
						summary := Collector.SyncDataset(context.Background(), dataset, Syncs.Log)
						return syncToolResult("completed", dataset, org, startedAt, []SyncSummary{summary})
					}
					tail := " and is still in progress. "
					if finished {
						tail = " and has now finished. "
					}
					return jx.M{
						"status":   "already_running",
						"finished": finished,
						"message": "Another sync was already running" + tail +
							"It may have started before your latest change; if the data you need is " +
							"still missing, call sync_data again.",
					}
				}

				// Written by the sync goroutine, read after WaitUntilIdle (or, on timeout,
				// a snapshot under the lock).
				var mu sync.Mutex
				summaries := []SyncSummary{}
				doSync := func(ctx context.Context, logFn LogFn) {
					var got []SyncSummary
					switch {
					case syncToolIsDataset(dataset):
						got = []SyncSummary{Collector.SyncDataset(ctx, dataset, logFn)}
					case org != "":
						got = []SyncSummary{Collector.SyncOrg(ctx, org, logFn)}
					default:
						got = Collector.SyncAll(ctx, logFn)
					}
					mu.Lock()
					summaries = append(summaries, got...)
					mu.Unlock()
				}
				startedAt := time.Now()
				if !Syncs.RunInBackground(doSync, "chat") {
					return jx.M{"status": "already_running", "message": "Another sync just started; try again shortly."}
				}
				finished := Syncs.WaitUntilIdle(syncToolWaitTimeout)
				status := "still_running"
				if finished {
					status = "completed"
				}
				mu.Lock()
				snap := append([]SyncSummary(nil), summaries...)
				mu.Unlock()
				return syncToolResult(status, dataset, org, startedAt, snap)
			}),
	}
}
