package app

import (
	"context"
	"fmt"
	"strings"
	"sync"
	"time"

	"github.com/satomic/octofinance/backend-go/internal/ghapi"
	"github.com/satomic/octofinance/backend-go/internal/jx"
)

// Pulls billing usage report CSVs through the GitHub billing reports API
// (create export -> poll until completed -> download signed CSV -> ingest).

// AllCSVTypes are the CSV flavours fetched by default.
var AllCSVTypes = []string{CSVTypeAI, CSVTypeUsage}

var (
	csvJobMu sync.Mutex
	csvJob   = jx.M{
		"job_id": "", "running": false, "step": 0, "total_steps": 0, "phase": "",
		"started_at": nil, "finished_at": nil, "date_range": nil, "enterprises": jx.L{},
		"results": jx.L{}, "new_rows": 0, "errors": jx.L{},
	}
)

func csvPollSettings() (time.Duration, time.Duration) {
	s := Pats.GetSettings()
	get := func(key string) int {
		v := jx.Int(s[key])
		if v == 0 {
			v = jx.Int(DefaultSettings[key])
		}
		return v
	}
	return time.Duration(get("csv_fetch_poll_seconds")) * time.Second,
		time.Duration(get("csv_fetch_timeout_minutes")) * time.Minute
}

// CSVGetJob returns a copy of the current/last fetch job state.
func CSVGetJob() jx.M {
	csvJobMu.Lock()
	defer csvJobMu.Unlock()
	return jx.DeepCopy(csvJob).(jx.M)
}

func csvJobUpdate(fields jx.M) {
	csvJobMu.Lock()
	defer csvJobMu.Unlock()
	for k, v := range fields {
		csvJob[k] = v
	}
}

// CSVBeginJob marks a job as running and returns its record.
func CSVBeginJob(enterprises []string, startDate, endDate string, csvTypes []string) jx.M {
	csvJobMu.Lock()
	defer csvJobMu.Unlock()
	ents := jx.L{}
	for _, e := range enterprises {
		ents = append(ents, e)
	}
	csvJob = jx.M{
		"job_id":      randHex(16),
		"running":     true,
		"step":        0,
		"total_steps": len(enterprises) * len(csvTypes),
		"phase":       "starting",
		"started_at":  jx.NowISO(),
		"finished_at": nil,
		"date_range":  jx.M{"start": startDate, "end": endDate},
		"enterprises": ents,
		"results":     jx.L{},
		"new_rows":    0,
		"errors":      jx.L{},
	}
	return jx.DeepCopy(csvJob).(jx.M)
}

// CSVDefaultDateRange is the widest window detail reports allow, ending today (UTC).
func CSVDefaultDateRange() (string, string) {
	end := time.Now().UTC()
	start := end.AddDate(0, 0, -(MaxReportDays - 1))
	return start.Format("2006-01-02"), end.Format("2006-01-02")
}

// CSVValidateDateRange returns an error message or "".
func CSVValidateDateRange(startDate, endDate string) string {
	start, err1 := time.Parse("2006-01-02", startDate)
	end, err2 := time.Parse("2006-01-02", endDate)
	if err1 != nil || err2 != nil {
		return "Dates must be in YYYY-MM-DD format."
	}
	if end.Before(start) {
		return "end_date must not be earlier than start_date."
	}
	span := int(end.Sub(start).Hours()/24) + 1
	if span > MaxReportDays {
		return fmt.Sprintf("Detail reports cover at most %d days; requested %d.", MaxReportDays, span)
	}
	return ""
}

func reportMatches(r jx.M, reportType, start, end string) bool {
	return jx.Str(r["report_type"]) == reportType && jx.Str(r["start_date"]) == start && jx.Str(r["end_date"]) == end
}

func awaitReport(ctx context.Context, api *ghapi.Client, enterprise, reportID string, logFn LogFn) jx.M {
	interval, timeout := csvPollSettings()
	started := time.Now()
	deadline := started.Add(timeout)
	lastLogged := 0
	for time.Now().Before(deadline) {
		select {
		case <-ctx.Done():
			return nil
		case <-time.After(interval):
		}
		report := api.GetBillingReport(ctx, enterprise, reportID)
		elapsed := int(time.Since(started).Seconds())
		if report == nil {
			continue
		}
		switch jx.Str(report["status"]) {
		case "completed":
			logFn.log("info", fmt.Sprintf("[%s] report ready after %ds", enterprise, elapsed))
			return report
		case "failed":
			logFn.log("error", fmt.Sprintf("[%s] report %s failed on GitHub's side", enterprise, reportID))
			return nil
		}
		if elapsed-lastLogged >= 60 {
			lastLogged = elapsed
			logFn.log("info", fmt.Sprintf("[%s] still generating (%ds elapsed)", enterprise, elapsed))
		}
	}
	logFn.log("error", fmt.Sprintf("[%s] report %s still processing after %d min, giving up", enterprise, reportID, int(timeout.Minutes())))
	return nil
}

func fetchOneReport(ctx context.Context, api *ghapi.Client, enterprise, csvType, start, end string, logFn LogFn) jx.M {
	reportType := ReportTypeByCSVType[csvType]
	fail := func(msg string) jx.M {
		return jx.M{"enterprise": enterprise, "csv_type": csvType, "error": msg}
	}
	logFn.log("info", fmt.Sprintf("[%s] requesting '%s' report %s ~ %s", enterprise, reportType, start, end))
	created := api.CreateBillingReport(ctx, enterprise, reportType, start, end)
	reportID := jx.Str(created["id"])
	if reportID == "" {
		detail := jx.Str(created["error"])
		if detail == "" {
			detail = "unknown error"
		}
		if jx.Int(created["status_code"]) != 409 {
			return fail(detail)
		}
		inFlight := []jx.M{}
		for _, r := range api.ListBillingReports(ctx, enterprise) {
			if jx.Str(r["status"]) == "processing" {
				inFlight = append(inFlight, r)
			}
		}
		for _, r := range inFlight {
			if reportMatches(r, reportType, start, end) {
				reportID = jx.Str(r["id"])
				break
			}
		}
		if reportID == "" {
			running := []string{}
			for _, r := range inFlight {
				running = append(running, fmt.Sprintf("%s (%s)", jx.Str(r["report_type"]), jx.Str(r["id"])))
			}
			msg := strings.Join(running, ", ")
			if msg == "" {
				msg = detail
			}
			return fail("Another export is already in progress: " + msg)
		}
		logFn.log("info", fmt.Sprintf("[%s] an identical export is already running, waiting on %s", enterprise, reportID))
	}
	report := awaitReport(ctx, api, enterprise, reportID, logFn)
	if report == nil {
		return fail("Report did not complete.")
	}
	urls := jx.Strings(report["download_urls"])
	if len(urls) == 0 {
		return fail("Report completed but returned no download URLs.")
	}
	parts := ghapi.DownloadBillingReportCSV(ctx, urls)
	if len(parts) == 0 {
		return fail("Could not download the report CSV.")
	}
	total, newRows, replaced, stored := 0, 0, 0, 0
	dates := []string{}
	for _, text := range parts {
		res := IngestCSVText(text)
		if e := jx.Str(res["error"]); e != "" {
			return fail(e)
		}
		total += jx.Int(res["total_rows"])
		newRows += jx.Int(res["new_rows"])
		replaced += jx.Int(res["replaced_rows"])
		stored = jx.Int(res["stored_rows"])
		rng := jx.GetMap(res, "date_range")
		for _, d := range []string{jx.Str(rng["start"]), jx.Str(rng["end"])} {
			if d != "" && d != "unknown" {
				dates = append(dates, d)
			}
		}
	}
	logFn.log("info", fmt.Sprintf("[%s] %s: merged %d rows (%d new, %d superseded), %d stored", enterprise, csvType, total, newRows, replaced, stored))
	var dr any
	if lo, hi, ok := jx.MinMax(dates); ok {
		dr = jx.M{"start": lo, "end": hi}
	}
	return jx.M{
		"enterprise": enterprise, "csv_type": csvType, "total_rows": total, "new_rows": newRows,
		"replaced_rows": replaced, "stored_rows": stored, "date_range": dr,
	}
}

// CSVFetchAndIngest fetches the requested detail reports for each enterprise and ingests them.
func CSVFetchAndIngest(ctx context.Context, enterprises []string, start, end string, csvTypes []string, logFn LogFn) jx.M {
	csvFetchAndIngest(ctx, enterprises, start, end, csvTypes, logFn)
	return CSVGetJob()
}

func csvFetchAndIngest(ctx context.Context, enterprises []string, start, end string, csvTypes []string, logFn LogFn) {
	results := jx.L{}
	defer func() {
		newRows := 0
		errs := jx.L{}
		for _, r := range jx.Maps(results) {
			newRows += jx.Int(r["new_rows"])
			if jx.Truthy(r["error"]) {
				errs = append(errs, r)
			}
		}
		csvJobUpdate(jx.M{
			"running": false, "phase": "done", "finished_at": jx.NowISO(),
			"results": results, "new_rows": newRows, "errors": errs,
		})
	}()
	for _, enterprise := range enterprises {
		api := APIs.APIForEnterprise(enterprise)
		if api == nil {
			results = append(results, jx.M{"enterprise": enterprise, "error": "No PAT configured with access to this enterprise."})
			continue
		}
		for _, csvType := range csvTypes {
			csvJobUpdate(jx.M{"phase": enterprise + "/" + csvType})
			func() {
				defer func() {
					if r := recover(); r != nil {
						results = append(results, jx.M{"enterprise": enterprise, "csv_type": csvType, "error": fmt.Sprint(r)})
					}
				}()
				results = append(results, fetchOneReport(ctx, api, enterprise, csvType, start, end, logFn))
			}()
			csvJobMu.Lock()
			csvJob["step"] = jx.Int(csvJob["step"]) + 1
			csvJob["results"] = append(jx.L{}, results...)
			csvJobMu.Unlock()
		}
	}
}

// CSVResolveEnterprises returns every enterprise slug the PATs can reach.
func CSVResolveEnterprises() []string {
	out := []string{}
	for _, e := range APIs.AllEnterprises() {
		out = append(out, jx.Str(e["slug"]))
	}
	return out
}

// CSVFetchLatest pulls the newest detail reports for every enterprise
// (Fetch CSV button and startup/scheduled syncs). Returns nil when there is no enterprise.
func CSVFetchLatest(ctx context.Context, logFn LogFn) jx.M {
	enterprises := CSVResolveEnterprises()
	if len(enterprises) == 0 {
		logFn.log("info", "No enterprise configured; skipping billing report CSV fetch")
		return nil
	}
	start, end := CSVDefaultDateRange()
	CSVBeginJob(enterprises, start, end, AllCSVTypes)
	return CSVFetchAndIngest(ctx, enterprises, start, end, AllCSVTypes, logFn)
}
