// Package jx holds helpers for working with schemaless JSON the way the Python
// backend does with dicts: tolerant getters, Python-compatible rounding and
// truthiness, and atomic JSON file persistence.
//
// Data files under data/ are shared with the Python backend, so everything
// read or written here must stay format-compatible with it.
package jx

import (
	"bytes"
	"encoding/json"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

// M is a JSON object, L a JSON array.
type (
	M = map[string]any
	L = []any
)

// ---------------------------------------------------------------------------
// Type coercion
// ---------------------------------------------------------------------------

// Map returns v as an object, or nil.
func Map(v any) M {
	m, _ := v.(map[string]any)
	return m
}

// List returns v as an array, or nil. A []M is converted.
func List(v any) L {
	switch t := v.(type) {
	case []any:
		return t
	case []M:
		out := make(L, len(t))
		for i, m := range t {
			out[i] = m
		}
		return out
	case []string:
		out := make(L, len(t))
		for i, s := range t {
			out[i] = s
		}
		return out
	}
	return nil
}

// Maps returns the object elements of an array, skipping anything else.
func Maps(v any) []M {
	l := List(v)
	out := make([]M, 0, len(l))
	for _, e := range l {
		if m, ok := e.(map[string]any); ok {
			out = append(out, m)
		}
	}
	return out
}

// Str converts v to a string the way Python's str() would for JSON values,
// except that nil becomes "".
func Str(v any) string {
	switch t := v.(type) {
	case nil:
		return ""
	case string:
		return t
	case bool:
		if t {
			return "True"
		}
		return "False"
	case float64:
		if t == math.Trunc(t) && math.Abs(t) < 1e15 {
			return strconv.FormatInt(int64(t), 10)
		}
		return strconv.FormatFloat(t, 'f', -1, 64)
	case int:
		return strconv.Itoa(t)
	case int64:
		return strconv.FormatInt(t, 10)
	case json.Number:
		return t.String()
	}
	return fmt.Sprint(v)
}

// AsString returns v when it is a string, otherwise "".
func AsString(v any) string {
	s, _ := v.(string)
	return s
}

// Float mirrors Python's “float(value or 0)“ with a 0 fallback on errors.
func Float(v any) float64 {
	f, _ := FloatOK(v)
	return f
}

// FloatOK converts numbers and numeric strings; ok is false for anything else.
func FloatOK(v any) (float64, bool) {
	switch t := v.(type) {
	case nil:
		return 0, false
	case float64:
		return t, true
	case float32:
		return float64(t), true
	case int:
		return float64(t), true
	case int64:
		return float64(t), true
	case json.Number:
		f, err := t.Float64()
		return f, err == nil
	case bool:
		if t {
			return 1, true
		}
		return 0, true
	case string:
		s := strings.TrimSpace(t)
		if s == "" {
			return 0, false
		}
		f, err := strconv.ParseFloat(s, 64)
		if err != nil {
			return 0, false
		}
		return f, true
	}
	return 0, false
}

// Int mirrors Python's “int(float(value or 0))“.
func Int(v any) int {
	return int(Float(v))
}

// Truthy mirrors Python truthiness for JSON values.
func Truthy(v any) bool {
	switch t := v.(type) {
	case nil:
		return false
	case bool:
		return t
	case string:
		return t != ""
	case float64:
		return t != 0
	case int:
		return t != 0
	case int64:
		return t != 0
	case []any:
		return len(t) > 0
	case map[string]any:
		return len(t) > 0
	case []M:
		return len(t) > 0
	case []string:
		return len(t) > 0
	}
	return true
}

// ---------------------------------------------------------------------------
// Object getters
// ---------------------------------------------------------------------------

// Get returns m[key] (nil-safe).
func Get(m M, key string) any {
	if m == nil {
		return nil
	}
	return m[key]
}

// GetStr returns m[key] as a string when it is one, else def.
func GetStr(m M, key string, def ...string) string {
	if v, ok := Get(m, key).(string); ok {
		return v
	}
	if len(def) > 0 {
		return def[0]
	}
	return ""
}

// GetOr returns m[key] if present (even when null) else def — Python's dict.get(key, def).
func GetOr(m M, key string, def any) any {
	if m == nil {
		return def
	}
	if v, ok := m[key]; ok {
		return v
	}
	return def
}

// OrStr is Python's “m.get(key) or def“ for strings.
func OrStr(m M, key, def string) string {
	if s := Str(Get(m, key)); s != "" && Truthy(Get(m, key)) {
		return s
	}
	return def
}

// GetMap returns m[key] as an object; never nil.
func GetMap(m M, key string) M {
	if v := Map(Get(m, key)); v != nil {
		return v
	}
	return M{}
}

// GetList returns m[key] as an array (nil when absent or not an array).
func GetList(m M, key string) L {
	return List(Get(m, key))
}

// GetMaps returns the object elements of m[key].
func GetMaps(m M, key string) []M {
	return Maps(Get(m, key))
}

// GetFloat returns float(m.get(key) or 0).
func GetFloat(m M, key string) float64 {
	return Float(Get(m, key))
}

// GetInt returns int(m.get(key) or 0).
func GetInt(m M, key string) int {
	return Int(Get(m, key))
}

// GetBool returns bool(m.get(key)).
func GetBool(m M, key string) bool {
	return Truthy(Get(m, key))
}

// GetBoolDef is “m.get(key, def)“ coerced with bool().
func GetBoolDef(m M, key string, def bool) bool {
	if m == nil {
		return def
	}
	v, ok := m[key]
	if !ok {
		return def
	}
	return Truthy(v)
}

// Has reports whether key is present in m.
func Has(m M, key string) bool {
	if m == nil {
		return false
	}
	_, ok := m[key]
	return ok
}

// Path walks nested objects: Path(m, "a", "b") == m["a"]["b"].
func Path(m M, keys ...string) any {
	var cur any = m
	for _, k := range keys {
		cm := Map(cur)
		if cm == nil {
			return nil
		}
		cur = cm[k]
	}
	return cur
}

// Strings converts an array of strings (skipping non-strings).
func Strings(v any) []string {
	l := List(v)
	out := make([]string, 0, len(l))
	for _, e := range l {
		if s, ok := e.(string); ok {
			out = append(out, s)
		}
	}
	return out
}

// Copy returns a shallow copy of m.
func Copy(m M) M {
	out := make(M, len(m)+4)
	for k, v := range m {
		out[k] = v
	}
	return out
}

// Merge returns a shallow copy of a with b's keys applied ({**a, **b}).
func Merge(a M, bs ...M) M {
	out := Copy(a)
	for _, b := range bs {
		for k, v := range b {
			out[k] = v
		}
	}
	return out
}

// DeepCopy clones any JSON value.
func DeepCopy(v any) any {
	switch t := v.(type) {
	case map[string]any:
		out := make(M, len(t))
		for k, e := range t {
			out[k] = DeepCopy(e)
		}
		return out
	case []any:
		out := make(L, len(t))
		for i, e := range t {
			out[i] = DeepCopy(e)
		}
		return out
	}
	return v
}

// Normalize round-trips a Go value through JSON so it only contains
// map[string]any / []any / float64 / string / bool / nil.
func Normalize(v any) any {
	b, err := Marshal(v)
	if err != nil {
		return nil
	}
	var out any
	if err := json.Unmarshal(b, &out); err != nil {
		return nil
	}
	return out
}

// ---------------------------------------------------------------------------
// Numbers
// ---------------------------------------------------------------------------

// Round matches Python's round(x, n): correctly rounded on the binary value.
func Round(x float64, n int) float64 {
	if math.IsNaN(x) || math.IsInf(x, 0) {
		return x
	}
	f, err := strconv.ParseFloat(strconv.FormatFloat(x, 'f', n, 64), 64)
	if err != nil {
		return x
	}
	if f == 0 {
		return 0 // avoid -0
	}
	return f
}

// RoundInt matches Python's round(x) (banker's rounding, returns int).
func RoundInt(x float64) int {
	return int(math.RoundToEven(x))
}

// ---------------------------------------------------------------------------
// Time
// ---------------------------------------------------------------------------

// NowISO is “datetime.now(timezone.utc).isoformat()“.
func NowISO() string {
	return ISO(time.Now())
}

// ISO formats t like Python's aware-datetime isoformat() in UTC.
func ISO(t time.Time) string {
	t = t.UTC()
	if t.Nanosecond()/1000 == 0 {
		return t.Format("2006-01-02T15:04:05+00:00")
	}
	return t.Format("2006-01-02T15:04:05.000000+00:00")
}

// ParseISO parses the ISO-8601 variants Python's fromisoformat accepts
// (with "Z" replaced). Naive timestamps are treated as UTC.
func ParseISO(s string) (time.Time, bool) {
	s = strings.TrimSpace(s)
	if s == "" {
		return time.Time{}, false
	}
	s = strings.Replace(s, "Z", "+00:00", 1)
	layouts := []string{
		time.RFC3339Nano,
		"2006-01-02T15:04:05.999999999-07:00",
		"2006-01-02T15:04:05-07:00",
		"2006-01-02T15:04:05.999999999",
		"2006-01-02T15:04:05",
		"2006-01-02 15:04:05.999999999-07:00",
		"2006-01-02 15:04:05-07:00",
		"2006-01-02 15:04:05",
		"2006-01-02T15:04-07:00",
		"2006-01-02T15:04",
		"2006-01-02",
	}
	for _, l := range layouts {
		if t, err := time.Parse(l, s); err == nil {
			return t, true
		}
	}
	return time.Time{}, false
}

// DaysBetween is Python's “(a - b).days“ (floor of whole days).
func DaysBetween(a, b time.Time) int {
	d := a.Sub(b)
	days := int(d / (24 * time.Hour))
	if d < 0 && d%(24*time.Hour) != 0 {
		days--
	}
	return days
}

// Today returns the current UTC date as YYYY-MM-DD.
func Today() string {
	return time.Now().UTC().Format("2006-01-02")
}

// ---------------------------------------------------------------------------
// JSON encoding / files
// ---------------------------------------------------------------------------

// Marshal encodes v compactly without HTML escaping.
func Marshal(v any) ([]byte, error) {
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(v); err != nil {
		return nil, err
	}
	return bytes.TrimRight(buf.Bytes(), "\n"), nil
}

// MarshalIndent encodes v with a 2-space indent (Python's indent=2).
func MarshalIndent(v any) ([]byte, error) {
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false)
	enc.SetIndent("", "  ")
	if err := enc.Encode(v); err != nil {
		return nil, err
	}
	return bytes.TrimRight(buf.Bytes(), "\n"), nil
}

// Dumps is json.dumps for tool results; encoding errors become an error object.
func Dumps(v any) string {
	b, err := Marshal(v)
	if err != nil {
		b, _ = Marshal(M{"error": err.Error()})
	}
	return string(b)
}

// ReadJSON decodes a file. Missing or invalid files return (nil, err).
func ReadJSON(path string) (any, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	b = bytes.TrimPrefix(b, []byte("\xef\xbb\xbf"))
	var v any
	if err := json.Unmarshal(b, &v); err != nil {
		return nil, err
	}
	return v, nil
}

// ReadJSONOr returns the decoded file or fallback when missing/invalid.
func ReadJSONOr(path string, fallback any) any {
	v, err := ReadJSON(path)
	if err != nil {
		return fallback
	}
	return v
}

// WriteJSON writes v (indent=2) atomically through a temp file + rename.
func WriteJSON(path string, v any) error {
	b, err := MarshalIndent(v)
	if err != nil {
		return err
	}
	return WriteFileAtomic(path, b)
}

// WriteFileAtomic writes data through a temp file in the same directory.
func WriteFileAtomic(path string, data []byte) error {
	dir := filepath.Dir(path)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return err
	}
	tmp, err := os.CreateTemp(dir, filepath.Base(path)+".*.tmp")
	if err != nil {
		return err
	}
	name := tmp.Name()
	if _, err := tmp.Write(data); err != nil {
		tmp.Close()
		os.Remove(name)
		return err
	}
	if err := tmp.Close(); err != nil {
		os.Remove(name)
		return err
	}
	if err := os.Chmod(name, 0o644); err != nil {
		os.Remove(name)
		return err
	}
	if err := os.Rename(name, path); err != nil {
		os.Remove(name)
		return err
	}
	return nil
}

// Exists reports whether path exists.
func Exists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}

var (
	fileLocksMu sync.Mutex
	fileLocks   = map[string]*sync.Mutex{}
)

// FileLock returns a process-wide mutex for a file path, for read-modify-write
// sequences on the JSON stores (Python ran them on a single event loop).
func FileLock(path string) *sync.Mutex {
	fileLocksMu.Lock()
	defer fileLocksMu.Unlock()
	mu, ok := fileLocks[path]
	if !ok {
		mu = &sync.Mutex{}
		fileLocks[path] = mu
	}
	return mu
}

// ---------------------------------------------------------------------------
// Collections
// ---------------------------------------------------------------------------

// SortedKeys returns m's keys in ascending order.
func SortedKeys[V any](m map[string]V) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}

// StrSet is a set of strings.
type StrSet map[string]struct{}

// Add inserts s.
func (s StrSet) Add(v string) { s[v] = struct{}{} }

// Has reports membership.
func (s StrSet) Has(v string) bool { _, ok := s[v]; return ok }

// Sorted returns the members in ascending order.
func (s StrSet) Sorted() []string {
	out := make([]string, 0, len(s))
	for k := range s {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

// MinMax returns the lexical min and max of non-empty strings.
func MinMax(values []string) (string, string, bool) {
	var lo, hi string
	found := false
	for _, v := range values {
		if v == "" {
			continue
		}
		if !found || v < lo {
			lo = v
		}
		if !found || v > hi {
			hi = v
		}
		found = true
	}
	return lo, hi, found
}

// Errorf builds the {"error": msg} object most endpoints and tools return.
func Errorf(format string, args ...any) M {
	return M{"error": fmt.Sprintf(format, args...)}
}
