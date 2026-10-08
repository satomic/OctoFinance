package app

import (
	"bytes"
	"encoding/csv"
	"fmt"
	"io"
	"math"
	"os"
	"path/filepath"
	"slices"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/satomic/octofinance/backend-go/internal/jx"
)

// Storage and ingestion for GitHub billing usage report CSVs. Each flavour is
// kept in a single {type}_latest.csv; ingestion merges by date (an export is
// authoritative for every day it covers).

const (
	CSVTypeAI    = "ai_usage"
	CSVTypeUsage = "usage_report"
	// MaxReportDays caps detail report history.
	MaxReportDays = 31
)

// AIUsageMetricFields are the token metric columns of the AI usage export.
var AIUsageMetricFields = []string{"input", "output", "cache_read", "cache_write"}

// ReportTypeByCSVType maps a CSV flavour to its GitHub billing report type.
var ReportTypeByCSVType = map[string]string{
	CSVTypeAI:    "ai_credit",
	CSVTypeUsage: "detailed",
}

// CSVRecord is one CSV row (column -> value).
type CSVRecord = map[string]string

// AddAIUsageMetrics accumulates reported metric values into total, preserving
// unknown fields as nil (Python None).
func AddAIUsageMetrics(total jx.M, record CSVRecord) {
	for _, field := range AIUsageMetricFields {
		if _, ok := total[field]; !ok {
			total[field] = nil
		}
		raw, ok := record[field]
		if !ok {
			continue
		}
		value, ok := jx.FloatOK(raw)
		if !ok || math.IsNaN(value) || math.IsInf(value, 0) || value < 0 {
			continue
		}
		total[field] = jx.Float(total[field]) + value
	}
}

// AddAIUsageMetricsFrom accumulates metrics from an object record (JSON shaped).
func AddAIUsageMetricsFrom(total jx.M, record jx.M) {
	rec := CSVRecord{}
	for _, f := range AIUsageMetricFields {
		if v, ok := record[f]; ok && v != nil {
			rec[f] = jx.Str(v)
		}
	}
	AddAIUsageMetrics(total, rec)
}

var csvMu sync.Mutex

// CSVDir returns the directory for a CSV flavour.
func CSVDir(csvType string) string {
	if csvType == CSVTypeUsage {
		return filepath.Join(Collector.DataDir(), "usage_report_csv")
	}
	return filepath.Join(Collector.DataDir(), "ai_usage_csv")
}

// LatestCSVPath is {dir}/{type}_latest.csv.
func LatestCSVPath(csvType string) string {
	return filepath.Join(CSVDir(csvType), csvType+"_latest.csv")
}

// DetectCSVType identifies the flavour from the header.
func DetectCSVType(fields []string) string {
	cols := jx.StrSet{}
	for _, f := range fields {
		cols.Add(f)
	}
	if cols.Has("model") && cols.Has("username") && cols.Has("organization") {
		return CSVTypeAI
	}
	if cols.Has("product") && cols.Has("sku") && cols.Has("unit_type") {
		return CSVTypeUsage
	}
	return ""
}

func parseCSV(r io.Reader) ([]string, []CSVRecord, error) {
	reader := csv.NewReader(r)
	reader.FieldsPerRecord = -1
	reader.LazyQuotes = true
	header, err := reader.Read()
	if err != nil {
		if err == io.EOF {
			return nil, nil, nil
		}
		return nil, nil, err
	}
	if len(header) > 0 {
		header[0] = strings.TrimPrefix(header[0], "\ufeff")
	}
	// Exports repeat the same dates, logins, models and SKUs on every row;
	// interning keeps one copy of each and lets the reader's line buffers go.
	intern := map[string]string{}
	str := func(v string) string {
		if len(v) > 64 {
			return strings.Clone(v)
		}
		if s, ok := intern[v]; ok {
			return s
		}
		v = strings.Clone(v)
		intern[v] = v
		return v
	}
	for i, h := range header {
		header[i] = str(h)
	}
	rows := []CSVRecord{}
	for {
		rec, err := reader.Read()
		if err == io.EOF {
			break
		}
		if err != nil {
			return header, rows, err
		}
		if len(rec) == 0 || (len(rec) == 1 && rec[0] == "") {
			continue // csv.DictReader skips blank lines
		}
		row := make(CSVRecord, len(header))
		for i, h := range header {
			if i < len(rec) {
				row[h] = str(rec[i])
			} else {
				row[h] = ""
			}
		}
		rows = append(rows, row)
	}
	return header, rows, nil
}

func readCSVFile(path string) ([]string, []CSVRecord) {
	f, err := os.Open(path)
	if err != nil {
		return nil, nil
	}
	defer f.Close()
	fields, rows, err := parseCSV(f)
	if err != nil {
		Logger.Warn(fmt.Sprintf("Could not read %s: %v", path, err))
		if rows == nil {
			return nil, nil
		}
	}
	return fields, rows
}

func writeCSVFile(path string, fields []string, rows []CSVRecord) error {
	var buf bytes.Buffer
	w := csv.NewWriter(&buf)
	w.UseCRLF = true // Python's csv module default line terminator
	_ = w.Write(fields)
	for _, r := range rows {
		rec := make([]string, len(fields))
		for i, f := range fields {
			rec[i] = r[f]
		}
		_ = w.Write(rec)
	}
	w.Flush()
	return jx.WriteFileAtomic(path, buf.Bytes())
}

func unionFields(base, extra []string) []string {
	merged := append([]string{}, base...)
	seen := jx.StrSet{}
	for _, f := range base {
		seen.Add(f)
	}
	for _, f := range extra {
		if !seen.Has(f) {
			merged = append(merged, f)
			seen.Add(f)
		}
	}
	return merged
}

func mergeByDate(oldFields []string, oldRows []CSVRecord, newFields []string, newRows []CSVRecord) ([]string, []CSVRecord, int) {
	covered := jx.StrSet{}
	for _, r := range newRows {
		if d := r["date"]; d != "" {
			covered.Add(d)
		}
	}
	kept := []CSVRecord{}
	for _, r := range oldRows {
		if !covered.Has(r["date"]) {
			kept = append(kept, r)
		}
	}
	superseded := len(oldRows) - len(kept)
	var fields []string
	if len(oldFields) > 0 {
		fields = unionFields(oldFields, newFields)
	} else {
		fields = append([]string{}, newFields...)
	}
	merged := append(kept, newRows...)
	sort.SliceStable(merged, func(i, j int) bool {
		if merged[i]["date"] != merged[j]["date"] {
			return merged[i]["date"] < merged[j]["date"]
		}
		return merged[i]["username"] < merged[j]["username"]
	})
	return fields, merged, superseded
}

// CSVEnsureMigrated folds legacy per-upload CSVs into the latest file.
func CSVEnsureMigrated(csvType string) int {
	csvMu.Lock()
	defer csvMu.Unlock()
	return ensureMigratedLocked(csvType)
}

func ensureMigratedLocked(csvType string) int {
	dir := CSVDir(csvType)
	latest := LatestCSVPath(csvType)
	matches, _ := filepath.Glob(filepath.Join(dir, "*.csv"))
	type entry struct {
		path  string
		mtime time.Time
	}
	legacy := []entry{}
	for _, p := range matches {
		if p == latest {
			continue
		}
		st, err := os.Stat(p)
		if err != nil {
			continue
		}
		legacy = append(legacy, entry{p, st.ModTime()})
	}
	if len(legacy) == 0 {
		return 0
	}
	sort.Slice(legacy, func(i, j int) bool {
		if !legacy[i].mtime.Equal(legacy[j].mtime) {
			return legacy[i].mtime.Before(legacy[j].mtime)
		}
		return filepath.Base(legacy[i].path) < filepath.Base(legacy[j].path)
	})
	fields, rows := readCSVFile(latest)
	for _, e := range legacy {
		f, r := readCSVFile(e.path)
		if len(r) == 0 {
			continue
		}
		fields, rows, _ = mergeByDate(fields, rows, f, r)
	}
	_ = writeCSVFile(latest, fields, rows)
	for _, e := range legacy {
		os.Remove(e.path)
	}
	Logger.Info(fmt.Sprintf("[csv_store] merged %d legacy %s file(s) into %s (%d rows)", len(legacy), csvType, filepath.Base(latest), len(rows)))
	return len(legacy)
}

// CSV records are cached per file modification time: dashboards re-read the
// merged CSV on every request, which dominated response time on large exports.
var csvCache = newFileCache()

// LoadAllCSVRecords returns every stored record for a CSV flavour. The returned
// rows are shared — callers must not modify them.
func LoadAllCSVRecords(csvType string) []CSVRecord {
	csvMu.Lock()
	defer csvMu.Unlock()
	ensureMigratedLocked(csvType)
	path := LatestCSVPath(csvType)
	st, err := os.Stat(path)
	if err != nil {
		return []CSVRecord{}
	}
	if v, ok := csvCache.get(path, st); ok {
		return v.([]CSVRecord)
	}
	_, rows := readCSVFile(path)
	if rows == nil {
		rows = []CSVRecord{}
	}
	csvCache.put(path, st, rows)
	return rows
}

// csvUsernames returns the username column of a CSV flavour without keeping
// the parsed rows.
func csvUsernames(csvType string) []string {
	csvMu.Lock()
	defer csvMu.Unlock()
	ensureMigratedLocked(csvType)
	path := LatestCSVPath(csvType)
	if v, ok := statCSVCached(path); ok {
		return csvColumn(v, "username")
	}
	return fileLogins(path, func() []string {
		_, rows := readCSVFile(path)
		return csvColumn(rows, "username")
	})
}

// statCSVCached returns the rows of path when they are already in csvCache.
func statCSVCached(path string) ([]CSVRecord, bool) {
	st, err := os.Stat(path)
	if err != nil {
		return nil, false
	}
	v, ok := csvCache.get(path, st)
	if !ok {
		return nil, false
	}
	return v.([]CSVRecord), true
}

// csvHeader reads only the header row of a CSV file.
func csvHeader(path string) []string {
	f, err := os.Open(path)
	if err != nil {
		return nil
	}
	defer f.Close()
	r := csv.NewReader(f)
	r.FieldsPerRecord = -1
	r.LazyQuotes = true
	header, err := r.Read()
	if err != nil {
		return nil
	}
	if len(header) > 0 {
		header[0] = strings.TrimPrefix(header[0], "\ufeff")
	}
	return header
}

func csvColumn(rows []CSVRecord, col string) []string {
	out := make([]string, 0, len(rows))
	for _, r := range rows {
		if v, ok := r[col]; ok {
			out = append(out, v)
		}
	}
	return out
}

func csvDedupKey(csvType string, r CSVRecord) string {
	if csvType == CSVTypeAI {
		return r["date"] + "|" + r["username"] + "|" + r["model"] + "|" + r["organization"]
	}
	return r["date"] + "|" + r["username"] + "|" + r["sku"] + "|" + r["organization"]
}

// IngestCSVText validates and merges one CSV document into the type's latest file.
func IngestCSVText(text string) jx.M {
	fields, rows, err := parseCSV(strings.NewReader(strings.TrimPrefix(text, "\ufeff")))
	if len(fields) == 0 {
		return jx.M{"error": "CSV file has no headers."}
	}
	if err != nil && len(rows) == 0 {
		return jx.M{"error": "CSV file is empty."}
	}
	csvType := DetectCSVType(fields)
	if csvType == "" {
		return jx.M{"error": "Unrecognised CSV format. Expected an AI usage CSV (with a 'model' column) " +
			"or a usage report CSV (with 'product' and 'sku' columns)."}
	}
	if len(rows) == 0 {
		return jx.M{"error": "CSV file is empty."}
	}
	dates := []string{}
	for _, r := range rows {
		if r["date"] != "" {
			dates = append(dates, r["date"])
		}
	}
	dateMin, dateMax := "unknown", "unknown"
	if lo, hi, ok := jx.MinMax(dates); ok {
		dateMin, dateMax = lo, hi
	}

	csvMu.Lock()
	defer csvMu.Unlock()
	ensureMigratedLocked(csvType)
	latest := LatestCSVPath(csvType)
	// Reuse the dashboards' parsed rows instead of parsing the file again.
	var oldFields []string
	oldRows, cached := statCSVCached(latest)
	if cached {
		oldFields = csvHeader(latest)
	} else {
		oldFields, oldRows = readCSVFile(latest)
	}
	oldKeys := jx.StrSet{}
	for _, r := range oldRows {
		oldKeys.Add(csvDedupKey(csvType, r))
	}
	mergedFields, merged, superseded := mergeByDate(oldFields, oldRows, fields, rows)
	if err := writeCSVFile(latest, mergedFields, merged); err != nil {
		return jx.M{"error": "Failed to save CSV: " + err.Error()}
	}
	// The merged rows are what reading the new file back returns when every
	// row has every column, so cache them for the dashboard that follows.
	if st, err := os.Stat(latest); err == nil && slices.Equal(mergedFields, fields) && (len(oldRows) == 0 || slices.Equal(oldFields, fields)) {
		csvCache.put(latest, st, merged)
	}
	newRows := 0
	for _, r := range rows {
		if !oldKeys.Has(csvDedupKey(csvType, r)) {
			newRows++
		}
	}
	status := "ok"
	if newRows == 0 && superseded == len(rows) {
		status = "no_new_data"
	}
	return jx.M{
		"status":        status,
		"csv_type":      csvType,
		"date_range":    jx.M{"start": dateMin, "end": dateMax},
		"total_rows":    len(rows),
		"new_rows":      newRows,
		"replaced_rows": superseded,
		"stored_rows":   len(merged),
		"file_saved":    filepath.Base(latest),
	}
}

// ScanCSVType summarises what has been ingested for one CSV flavour.
func ScanCSVType(csvType string) jx.M {
	records := LoadAllCSVRecords(csvType)
	dates := []string{}
	orgs := jx.StrSet{}
	users := jx.StrSet{}
	for _, r := range records {
		if d := r["date"]; d != "" {
			dates = append(dates, d)
		}
		if o := r["organization"]; o != "" {
			orgs.Add(o)
		}
		if u := r["username"]; u != "" {
			users.Add(u)
		}
	}
	var latest, earliest any
	if lo, hi, ok := jx.MinMax(dates); ok {
		earliest, latest = lo, hi
	}
	fileCount := 0
	if len(records) > 0 {
		fileCount = 1
	}
	orgList := orgs.Sorted()
	return jx.M{
		"has_data":      len(records) > 0,
		"latest_date":   latest,
		"earliest_date": earliest,
		"file_count":    fileCount,
		"total_records": len(records),
		"orgs":          orgList,
		"user_count":    len(users),
	}
}
