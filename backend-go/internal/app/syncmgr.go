package app

import (
	"context"
	"fmt"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/satomic/octofinance/backend-go/internal/jx"
)

const maxRecordedErrors = 20

var everyNRE = regexp.MustCompile(`^\*/(\d+)$`)

// parseCronInterval supports */N minutes, 0 */N hours, 0 0 daily, 0 0 */N days.
func parseCronInterval(expr string) (time.Duration, bool) {
	parts := strings.Fields(expr)
	if len(parts) != 5 {
		return 0, false
	}
	minute, hour, dom, month, dow := parts[0], parts[1], parts[2], parts[3], parts[4]
	n := func(s string) (int, bool) {
		m := everyNRE.FindStringSubmatch(s)
		if m == nil {
			return 0, false
		}
		v, err := strconv.Atoi(m[1])
		return v, err == nil
	}
	if v, ok := n(minute); ok && hour == "*" && dom == "*" && month == "*" && dow == "*" {
		return time.Duration(v) * time.Minute, true
	}
	if v, ok := n(hour); ok && minute == "0" && dom == "*" && month == "*" && dow == "*" {
		return time.Duration(v) * time.Hour, true
	}
	if minute == "0" && hour == "0" && dom == "*" && month == "*" && dow == "*" {
		return 24 * time.Hour, true
	}
	if v, ok := n(dom); ok && minute == "0" && hour == "0" && month == "*" && dow == "*" {
		return time.Duration(v) * 24 * time.Hour, true
	}
	return 0, false
}

// DescribeCron returns a human-readable description, or "".
func DescribeCron(expr string) string {
	d, ok := parseCronInterval(expr)
	if !ok {
		return ""
	}
	secs := int(d.Seconds())
	plural := func(n int) string {
		if n != 1 {
			return "s"
		}
		return ""
	}
	switch {
	case secs < 3600:
		m := secs / 60
		return fmt.Sprintf("Every %d minute%s", m, plural(m))
	case secs < 86400:
		h := secs / 3600
		return fmt.Sprintf("Every %d hour%s", h, plural(h))
	}
	days := secs / 86400
	if days == 1 {
		return "Daily"
	}
	return fmt.Sprintf("Every %d days", days)
}

// SyncFunc is a sync job; it receives the log function.
type SyncFunc func(ctx context.Context, logFn LogFn)

// SyncManager tracks global sync state, broadcasts log events and runs the cron scheduler.
type SyncManager struct {
	mu         sync.Mutex
	syncing    bool
	listeners  map[chan jx.M]struct{}
	done       chan struct{}
	cronStop   chan struct{}
	cronExpr   string
	preflight  func(ctx context.Context, logFn LogFn)
	run        jx.M
	status     jx.M
	statusPath string
}

// Syncs is the global sync manager.
var Syncs = &SyncManager{listeners: map[chan jx.M]struct{}{}}

// LoadStatus reads the persisted last-run outcome.
func (s *SyncManager) LoadStatus() {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.statusPath = dataPath("sync_status.json")
	s.status = jx.Map(jx.ReadJSONOr(s.statusPath, jx.M{}))
	if s.status == nil {
		s.status = jx.M{}
	}
}

func (s *SyncManager) saveStatusLocked() {
	if s.statusPath == "" {
		s.statusPath = dataPath("sync_status.json")
	}
	if err := jx.WriteJSON(s.statusPath, s.status); err != nil {
		printf("[SyncManager] Could not save sync status: %v", err)
	}
}

// Status is the last run, last success and cron state for /api/health.
func (s *SyncManager) Status() jx.M {
	s.mu.Lock()
	defer s.mu.Unlock()
	desc := ""
	if s.cronExpr != "" {
		desc = DescribeCron(s.cronExpr)
	}
	return jx.M{
		"last_run":         jx.DeepCopy(s.status["last_run"]),
		"last_success_at":  s.status["last_success_at"],
		"cron":             s.cronExpr,
		"cron_description": desc,
	}
}

// SetPreflight registers a check that runs at the start of every sync.
func (s *SyncManager) SetPreflight(fn func(ctx context.Context, logFn LogFn)) {
	s.mu.Lock()
	s.preflight = fn
	s.mu.Unlock()
}

// IsSyncing reports whether a sync is running.
func (s *SyncManager) IsSyncing() bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.syncing
}

// Subscribe returns a channel of sync events (starting with the current state).
func (s *SyncManager) Subscribe() chan jx.M {
	ch := make(chan jx.M, 500)
	s.mu.Lock()
	s.listeners[ch] = struct{}{}
	syncing := s.syncing
	s.mu.Unlock()
	ch <- jx.M{"type": "sync_status", "syncing": syncing, "timestamp": jx.NowISO()}
	return ch
}

// Unsubscribe removes a subscriber.
func (s *SyncManager) Unsubscribe(ch chan jx.M) {
	s.mu.Lock()
	delete(s.listeners, ch)
	s.mu.Unlock()
}

func (s *SyncManager) emitLocked(event jx.M) {
	for ch := range s.listeners {
		select {
		case ch <- event:
		default:
			delete(s.listeners, ch) // queue full: drop the dead subscriber
		}
	}
}

// Log emits a log event and records errors/warnings on the current run.
func (s *SyncManager) Log(level, message string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.run != nil && (level == "error" || level == "warn" || level == "warning") {
		if level == "error" {
			s.run["error_count"] = jx.Int(s.run["error_count"]) + 1
			errs := jx.List(s.run["errors"])
			if len(errs) < maxRecordedErrors {
				s.run["errors"] = append(errs, strings.TrimSpace(message))
			}
		} else {
			s.run["warning_count"] = jx.Int(s.run["warning_count"]) + 1
		}
	}
	s.emitLocked(jx.M{"type": "sync_log", "level": level, "message": message, "timestamp": jx.NowISO()})
}

func (s *SyncManager) end(success bool, errMsg string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	finished := jx.NowISO()
	run := s.run
	s.run = nil
	errorCount := 0
	var firstErr any
	var trigger any
	if run != nil {
		run["finished_at"] = finished
		errs := jx.List(run["errors"])
		if errMsg != "" {
			errs = append(jx.L{errMsg}, errs...)
			run["errors"] = errs
		}
		errorCount = jx.Int(run["error_count"])
		if s.status == nil {
			s.status = jx.M{}
		}
		if !success || errorCount > 0 {
			run["status"] = "failed"
		} else {
			run["status"] = "success"
			s.status["last_success_at"] = finished
		}
		s.status["last_run"] = run
		s.saveStatusLocked()
		if len(errs) > 0 {
			firstErr = errs[0]
		}
		trigger = run["trigger"]
	}
	if errMsg != "" {
		firstErr = errMsg
	}
	s.syncing = false
	if s.done != nil {
		close(s.done)
		s.done = nil
	}
	s.emitLocked(jx.M{
		"type":        "sync_complete",
		"success":     success && errorCount == 0,
		"error":       firstErr,
		"error_count": errorCount,
		"trigger":     trigger,
		"timestamp":   finished,
	})
}

// NotifyDataChanged tells open pages to reload their data (the frontend
// refreshes every panel on sync_complete). Skipped while a sync runs, because
// that sync's own completion refreshes the pages.
func (s *SyncManager) NotifyDataChanged(message string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.syncing {
		return
	}
	now := jx.NowISO()
	s.emitLocked(jx.M{"type": "sync_log", "level": "info", "message": message, "timestamp": now})
	s.emitLocked(jx.M{"type": "sync_complete", "success": true, "error": nil, "error_count": 0,
		"trigger": "discovery", "timestamp": now})
}

// RunInBackground starts a sync unless one is running. Returns false when busy.
func (s *SyncManager) RunInBackground(fn SyncFunc, trigger string) bool {
	if trigger == "" {
		trigger = "manual"
	}
	s.mu.Lock()
	if s.syncing {
		s.mu.Unlock()
		s.Log("warn", "Sync already in progress, skipping")
		return false
	}
	s.syncing = true
	s.done = make(chan struct{})
	preflight := s.preflight
	s.mu.Unlock()

	// Fire-and-forget: an offline deployment must not delay or fail the sync.
	Updates.Schedule()

	go func() {
		ctx := context.Background()
		s.mu.Lock()
		s.run = jx.M{
			"trigger":       trigger,
			"started_at":    jx.NowISO(),
			"error_count":   0,
			"warning_count": 0,
			"errors":        jx.L{},
		}
		s.emitLocked(jx.M{"type": "sync_start", "timestamp": jx.NowISO()})
		s.mu.Unlock()

		defer func() {
			if r := recover(); r != nil {
				msg := fmt.Sprint(r)
				s.Log("error", "Sync failed: "+msg)
				s.end(false, msg)
			}
		}()
		if preflight != nil {
			preflight(ctx, s.Log)
		}
		fn(ctx, s.Log)
		s.end(true, "")
	}()
	return true
}

// WaitUntilIdle waits for the running sync to finish. Returns false on timeout.
func (s *SyncManager) WaitUntilIdle(timeout time.Duration) bool {
	s.mu.Lock()
	done := s.done
	syncing := s.syncing
	s.mu.Unlock()
	if done == nil {
		return !syncing
	}
	select {
	case <-done:
		return true
	case <-time.After(timeout):
		return false
	}
}

// StartCronScheduler starts a periodic sync. Returns false for an unparseable expression.
func (s *SyncManager) StartCronScheduler(expr string, fn SyncFunc) bool {
	interval, ok := parseCronInterval(expr)
	if !ok {
		s.Log("warn", "Cannot parse cron expression: "+expr)
		return false
	}
	s.StopCronScheduler()
	stop := make(chan struct{})
	s.mu.Lock()
	s.cronExpr = expr
	s.cronStop = stop
	s.mu.Unlock()
	desc := DescribeCron(expr)
	s.Log("info", fmt.Sprintf("Cron scheduler started: %s (%s)", desc, expr))
	go func() {
		ticker := time.NewTicker(interval)
		defer ticker.Stop()
		for {
			select {
			case <-stop:
				return
			case <-ticker.C:
				s.Log("info", fmt.Sprintf("Cron triggered sync (%s)", desc))
				s.RunInBackground(fn, "scheduled")
			}
		}
	}()
	return true
}

// StopCronScheduler stops the periodic sync.
func (s *SyncManager) StopCronScheduler() {
	s.mu.Lock()
	stop := s.cronStop
	s.cronStop = nil
	s.cronExpr = ""
	s.mu.Unlock()
	if stop != nil {
		close(stop)
		s.Log("info", "Cron scheduler stopped")
	}
}

// CronExpr returns the active cron expression.
func (s *SyncManager) CronExpr() string {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.cronExpr
}

// RunFullSync refreshes every JSON dataset, then ingests the latest billing CSVs
// (used by the startup and scheduled runs).
func RunFullSync(ctx context.Context, logFn LogFn) {
	Collector.SyncAll(ctx, logFn)
	result, err := csvFetchLatestSafe(ctx, logFn)
	if err != nil {
		Logger.Error("Scheduled billing report CSV fetch failed: " + err.Error())
		logFn("error", "Billing report CSV fetch failed: "+err.Error())
		return
	}
	if result != nil {
		if errs := jx.GetList(result, "errors"); len(errs) > 0 {
			logFn("warn", fmt.Sprintf("Billing report CSV fetch finished with %d error(s)", len(errs)))
		}
	}
}

func csvFetchLatestSafe(ctx context.Context, logFn LogFn) (result jx.M, err error) {
	defer func() {
		if r := recover(); r != nil {
			err = fmt.Errorf("%v", r)
		}
	}()
	return CSVFetchLatest(ctx, logFn), nil
}
