package app

import (
	"bufio"
	"encoding/json"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"sync"

	"github.com/satomic/octofinance/backend-go/internal/jx"
)

// Chat sessions under data/sessions/: index.json plus one folder per session
// with metadata.json, messages.jsonl and tool_calls.jsonl.

const (
	DefaultSessionTitle = "New Session"
	titleMaxLen         = 48
)

var (
	fencedRE = regexp.MustCompile("(?s)```.*?```")
	inlineRE = regexp.MustCompile("`([^`]*)`")
	mdLeadRE = regexp.MustCompile(`(?m)^\s*[#>*\-+]+\s*`)
	spacesRE = regexp.MustCompile(`\s+`)
)

// DeriveTitle turns the first user message into a short session title.
func DeriveTitle(text string) string {
	if text == "" {
		return DefaultSessionTitle
	}
	cleaned := fencedRE.ReplaceAllString(text, " ")
	cleaned = inlineRE.ReplaceAllString(cleaned, "$1")
	cleaned = mdLeadRE.ReplaceAllString(cleaned, "")
	cleaned = strings.TrimSpace(spacesRE.ReplaceAllString(cleaned, " "))
	if cleaned == "" {
		return DefaultSessionTitle
	}
	runes := []rune(cleaned)
	if len(runes) <= titleMaxLen {
		return cleaned
	}
	clipped := runes[:titleMaxLen]
	// Prefer a word boundary if it keeps most of the text (CJK has no spaces).
	if space := lastIndexRune(clipped, ' '); float64(space) > titleMaxLen*0.6 {
		clipped = clipped[:space]
	}
	return strings.TrimRight(string(clipped), " \t\n") + "..."
}

func lastIndexRune(rs []rune, r rune) int {
	for i := len(rs) - 1; i >= 0; i-- {
		if rs[i] == r {
			return i
		}
	}
	return -1
}

// SessionManager persists chat sessions.
type SessionManager struct {
	mu sync.Mutex
}

// Sessions is the global session manager.
var Sessions = &SessionManager{}

// SessionsDir is data/sessions.
func SessionsDir() string { return dataPath("sessions") }

func indexFile() string { return filepath.Join(SessionsDir(), "index.json") }

func (s *SessionManager) ensureDirs() {
	_ = os.MkdirAll(SessionsDir(), 0o755)
	if !jx.Exists(indexFile()) {
		_ = os.WriteFile(indexFile(), []byte("[]"), 0o644)
	}
}

func (s *SessionManager) readIndex() []jx.M {
	v, err := jx.ReadJSON(indexFile())
	if err != nil {
		return []jx.M{}
	}
	return jx.Maps(v)
}

func (s *SessionManager) writeIndex(index []jx.M) {
	if index == nil {
		index = []jx.M{}
	}
	_ = jx.WriteJSON(indexFile(), index)
}

func (s *SessionManager) updateIndexEntry(id string, updates jx.M) {
	index := s.readIndex()
	for _, e := range index {
		if jx.Str(e["session_id"]) == id {
			for k, v := range updates {
				e[k] = v
			}
			break
		}
	}
	s.writeIndex(index)
}

// GenerateSessionID returns an 8-char hex id.
func GenerateSessionID() string { return randHex(4) }

// Create creates a session folder and registers it in the index.
// A blank or placeholder title marks the session as auto-nameable.
func (s *SessionManager) Create(id, title string) jx.M {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.ensureDirs()
	if id == "" {
		id = GenerateSessionID()
	}
	dir := filepath.Join(SessionsDir(), id)
	_ = os.MkdirAll(dir, 0o755)
	title = strings.TrimSpace(title)
	auto := title == "" || title == DefaultSessionTitle
	if title == "" {
		title = DefaultSessionTitle
	}
	now := jx.NowISO()
	meta := jx.M{
		"session_id":    id,
		"title":         title,
		"auto_title":    auto,
		"created_at":    now,
		"updated_at":    now,
		"message_count": 0,
	}
	_ = jx.WriteJSON(filepath.Join(dir, "metadata.json"), meta)
	index := s.readIndex()
	exists := false
	for _, e := range index {
		if jx.Str(e["session_id"]) == id {
			exists = true
			break
		}
	}
	if !exists {
		index = append([]jx.M{jx.Copy(meta)}, index...)
		s.writeIndex(index)
	}
	return meta
}

// List returns all sessions sorted by updated_at descending.
func (s *SessionManager) List() []jx.M {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.ensureDirs()
	index := s.readIndex()
	sort.SliceStable(index, func(i, j int) bool {
		return jx.Str(index[i]["updated_at"]) > jx.Str(index[j]["updated_at"])
	})
	return index
}

// Get returns one session's metadata, or nil.
func (s *SessionManager) Get(id string) jx.M {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.getLocked(id)
}

func (s *SessionManager) getLocked(id string) jx.M {
	for _, e := range s.readIndex() {
		if jx.Str(e["session_id"]) == id {
			return e
		}
	}
	return nil
}

// Exists reports whether a session folder exists.
func (s *SessionManager) Exists(id string) bool {
	return validSessionID(id) && jx.Exists(filepath.Join(SessionsDir(), id, "metadata.json"))
}

// validSessionID rejects ids that could escape the sessions directory.
func validSessionID(id string) bool {
	return id != "" && id != "." && id != ".." && !strings.ContainsAny(id, `/\`)
}

func appendJSONL(path string, v any) {
	b, err := jx.Marshal(v)
	if err != nil {
		return
	}
	f, err := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
	if err != nil {
		return
	}
	defer f.Close()
	_, _ = f.Write(append(b, '\n'))
}

// AppendMessage appends to messages.jsonl and updates counts / auto title.
func (s *SessionManager) AppendMessage(id string, msg jx.M) {
	s.mu.Lock()
	defer s.mu.Unlock()
	dir := filepath.Join(SessionsDir(), id)
	if !validSessionID(id) || !jx.Exists(dir) {
		return
	}
	appendJSONL(filepath.Join(dir, "messages.jsonl"), msg)
	count := len(loadJSONL(filepath.Join(dir, "messages.jsonl")))
	updates := jx.M{"message_count": count, "updated_at": jx.NowISO()}
	if jx.Str(msg["role"]) == "user" && s.isAutoTitledLocked(id) {
		if title := DeriveTitle(jx.Str(msg["content"])); title != DefaultSessionTitle {
			updates["title"] = title
			updates["auto_title"] = false
		}
	}
	s.updateIndexEntry(id, updates)
	metaPath := filepath.Join(dir, "metadata.json")
	if meta := jx.Map(jx.ReadJSONOr(metaPath, nil)); meta != nil {
		for k, v := range updates {
			meta[k] = v
		}
		_ = jx.WriteJSON(metaPath, meta)
	}
}

func (s *SessionManager) isAutoTitledLocked(id string) bool {
	entry := s.getLocked(id)
	if entry == nil {
		entry = jx.M{}
	}
	if v, ok := entry["auto_title"]; ok {
		return jx.Truthy(v)
	}
	t := strings.TrimSpace(jx.Str(entry["title"]))
	return t == "" || t == DefaultSessionTitle
}

// AppendToolCall appends to tool_calls.jsonl.
func (s *SessionManager) AppendToolCall(id string, call jx.M) {
	s.mu.Lock()
	defer s.mu.Unlock()
	dir := filepath.Join(SessionsDir(), id)
	if !validSessionID(id) || !jx.Exists(dir) {
		return
	}
	appendJSONL(filepath.Join(dir, "tool_calls.jsonl"), call)
}

func loadJSONL(path string) []any {
	f, err := os.Open(path)
	if err != nil {
		return []any{}
	}
	defer f.Close()
	out := []any{}
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 1024*1024), 64*1024*1024)
	for sc.Scan() {
		line := strings.TrimSpace(sc.Text())
		if line == "" {
			continue
		}
		var v any
		if json.Unmarshal([]byte(line), &v) == nil {
			out = append(out, v)
		}
	}
	return out
}

// LoadMessages returns all messages of a session.
func (s *SessionManager) LoadMessages(id string) []any {
	if !validSessionID(id) {
		return []any{}
	}
	return loadJSONL(filepath.Join(SessionsDir(), id, "messages.jsonl"))
}

// UpdateTitle renames a session (a manual rename is never overwritten).
func (s *SessionManager) UpdateTitle(id, title string) jx.M {
	s.mu.Lock()
	defer s.mu.Unlock()
	if !validSessionID(id) {
		return nil
	}
	metaPath := filepath.Join(SessionsDir(), id, "metadata.json")
	meta := jx.Map(jx.ReadJSONOr(metaPath, nil))
	if meta == nil {
		return nil
	}
	now := jx.NowISO()
	meta["title"] = title
	meta["auto_title"] = false
	meta["updated_at"] = now
	_ = jx.WriteJSON(metaPath, meta)
	s.updateIndexEntry(id, jx.M{"title": title, "auto_title": false, "updated_at": now})
	return meta
}

// BackfillTitles names sessions still stuck on the placeholder title.
func (s *SessionManager) BackfillTitles() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.ensureDirs()
	renamed := 0
	for _, entry := range s.readIndex() {
		id := jx.Str(entry["session_id"])
		if id == "" || !validSessionID(id) || !s.isAutoTitledLocked(id) {
			continue
		}
		var first jx.M
		for _, m := range jx.Maps(loadJSONL(filepath.Join(SessionsDir(), id, "messages.jsonl"))) {
			if jx.Str(m["role"]) == "user" {
				first = m
				break
			}
		}
		if first == nil {
			continue
		}
		title := DeriveTitle(jx.Str(first["content"]))
		if title == DefaultSessionTitle {
			continue
		}
		s.updateIndexEntry(id, jx.M{"title": title, "auto_title": false})
		metaPath := filepath.Join(SessionsDir(), id, "metadata.json")
		if meta := jx.Map(jx.ReadJSONOr(metaPath, nil)); meta != nil {
			meta["title"] = title
			meta["auto_title"] = false
			_ = jx.WriteJSON(metaPath, meta)
		}
		renamed++
	}
	return renamed
}

// Delete removes a session folder and its index entry.
func (s *SessionManager) Delete(id string) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	if validSessionID(id) {
		_ = os.RemoveAll(filepath.Join(SessionsDir(), id))
	}
	index := []jx.M{}
	for _, e := range s.readIndex() {
		if jx.Str(e["session_id"]) != id {
			index = append(index, e)
		}
	}
	s.writeIndex(index)
	return true
}
