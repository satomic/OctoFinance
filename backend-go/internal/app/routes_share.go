package app

// Cost center report sharing (Python routers/share.py).
//
// Admin endpoints (under /api, behind the auth middleware) manage the share
// configuration per cost center; the public /share/cc/{token} pages serve the
// shared report (public or password-protected) without an OctoFinance account.
// Share configuration is persisted in data/cc_shares.json.

import (
	"bytes"
	"crypto/pbkdf2"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"os"
	"regexp"
	"strconv"
	"strings"
	"sync"

	"github.com/satomic/octofinance/backend-go/internal/jx"
)

func init() { registerRoutes(registerShareRoutes) }

func registerShareRoutes(r *Router) {
	r.Handle("GET /api/data/cost-center-shares", shareList)
	r.Handle("POST /api/data/cost-center-share", shareUpsert)
	r.Handle("DELETE /api/data/cost-center-share", shareDelete)
	r.Handle("GET /share/cc/{token}", shareView)
	r.Handle("POST /share/cc/{token}/verify", shareVerify)
	r.Handle("GET /share/cc/{token}/download", shareDownload)
}

// In-memory verified password sessions: entries of "{token}:{cookie_value}".
var (
	shareVerifiedMu sync.Mutex
	shareVerified   = map[string]struct{}{}
)

func shareDropSessions(token string) {
	shareVerifiedMu.Lock()
	defer shareVerifiedMu.Unlock()
	for s := range shareVerified {
		if strings.HasPrefix(s, token+":") {
			delete(shareVerified, s)
		}
	}
}

// ---------------------------------------------------------------------------
// Storage helpers
// ---------------------------------------------------------------------------

func shareFile() string { return dataPath("cc_shares.json") }

// shareEntry keeps the dict order of data/cc_shares.json.
type shareEntry struct {
	key   string
	share jx.M
}

func shareLoad() []shareEntry {
	raw, err := jx.ReadJSON(shareFile())
	if err != nil {
		return nil
	}
	data := jx.Map(raw)
	if data == nil {
		return nil
	}
	shares := jx.Map(data["shares"])
	if shares == nil {
		return nil
	}
	order := shareKeyOrder(shareFile())
	out := make([]shareEntry, 0, len(shares))
	seen := jx.StrSet{}
	for _, k := range order {
		if v, ok := shares[k]; ok && !seen.Has(k) {
			seen.Add(k)
			out = append(out, shareEntry{k, jx.Map(v)})
		}
	}
	for _, k := range jx.SortedKeys(shares) {
		if !seen.Has(k) {
			out = append(out, shareEntry{k, jx.Map(shares[k])})
		}
	}
	return out
}

// shareKeyOrder returns the keys of the "shares" object in file order.
func shareKeyOrder(path string) []string {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil
	}
	return shareObjectKeys(b)
}

func shareSave(entries []shareEntry) {
	var b strings.Builder
	b.WriteString("{\n  \"shares\": {")
	for i, e := range entries {
		if i > 0 {
			b.WriteString(",")
		}
		k, _ := jx.Marshal(e.key)
		v, _ := jx.MarshalIndent(shareOrdered(e.share))
		b.WriteString("\n    " + string(k) + ": " + strings.ReplaceAll(string(v), "\n", "\n    "))
	}
	if len(entries) > 0 {
		b.WriteString("\n  ")
	}
	b.WriteString("}\n}")
	_ = jx.WriteFileAtomic(shareFile(), []byte(b.String()))
}

// shareFieldOrder is the insertion order Python produces for a share dict.
var shareFieldOrder = []string{"enterprise", "cc_id", "token", "created_at", "cc_name", "mode", "updated_at", "password_hash", "salt"}

// shareOrdered renders a share as an ordered JSON object (Python key order).
func shareOrdered(share jx.M) shareOrderedObj {
	out := shareOrderedObj{}
	seen := jx.StrSet{}
	for _, k := range shareFieldOrder {
		if v, ok := share[k]; ok {
			out = append(out, shareKV{k, v})
			seen.Add(k)
		}
	}
	for _, k := range jx.SortedKeys(share) {
		if !seen.Has(k) {
			out = append(out, shareKV{k, share[k]})
		}
	}
	return out
}

func shareKey(enterprise, ccID string) string { return enterprise + "::" + ccID }

func shareFindByToken(token string) jx.M {
	for _, e := range shareLoad() {
		if t, ok := e.share["token"].(string); ok && t == token {
			return e.share
		}
	}
	return nil
}

func shareHashPassword(password string, salt []byte) string {
	key, _ := pbkdf2.Key(sha256.New, password, salt, 100_000, sha256.Size)
	return hex.EncodeToString(key)
}

func sharePublicInfo(share jx.M) jx.M {
	return jx.M{
		"cc_id":      share["cc_id"],
		"cc_name":    jx.GetOr(share, "cc_name", ""),
		"token":      share["token"],
		"mode":       jx.GetOr(share, "mode", "public"),
		"url":        "/share/cc/" + jx.Str(share["token"]),
		"created_at": jx.GetOr(share, "created_at", ""),
		"updated_at": jx.GetOr(share, "updated_at", ""),
	}
}

func shareRandBytes(n int) []byte {
	b := make([]byte, n)
	_, _ = rand.Read(b)
	return b
}

// ---------------------------------------------------------------------------
// Admin endpoints
// ---------------------------------------------------------------------------

func shareList(c *Ctx) any {
	enterprise := c.Query("enterprise", "")
	out := jx.M{}
	for _, e := range shareLoad() {
		if enterprise != "" && jx.Str(e.share["enterprise"]) != enterprise {
			continue
		}
		out[jx.Str(e.share["cc_id"])] = sharePublicInfo(e.share)
	}
	return jx.M{"shares": out}
}

var shareModePattern = regexp.MustCompile(`^(public|password)$`)

func shareUpsert(c *Ctx) any {
	body, resp := c.BindMap()
	if resp != nil {
		return resp
	}
	v := ccoValidator{body: body}
	enterprise := v.str("enterprise", nil)
	ccID := v.str("cc_id", nil)
	ccName := v.str("cc_name", ccoStrPtr(""))
	mode := v.str("mode", ccoStrPtr("public"))
	if _, isStr := body["mode"].(string); isStr && !shareModePattern.MatchString(mode) {
		v.add(jx.M{"type": "string_pattern_mismatch", "loc": jx.L{"body", "mode"},
			"msg": "String should match pattern '^(public|password)$'", "input": mode,
			"ctx": jx.M{"pattern": "^(public|password)$"}})
	}
	password := v.str("password", ccoStrPtr(""))
	if r := v.result(); r != nil {
		return r
	}
	if enterprise == "" || ccID == "" {
		return jx.M{"error": "enterprise and cc_id are required"}
	}

	mu := jx.FileLock(shareFile())
	mu.Lock()
	defer mu.Unlock()
	entries := shareLoad()
	key := shareKey(enterprise, ccID)
	idx := -1
	for i, e := range entries {
		if e.key == key {
			idx = i
			break
		}
	}
	now := jx.NowISO()
	var share jx.M
	if idx >= 0 && jx.Truthy(entries[idx].share) {
		share = entries[idx].share
	} else {
		share = jx.M{
			"enterprise": enterprise,
			"cc_id":      ccID,
			"token":      base64.RawURLEncoding.EncodeToString(shareRandBytes(24)),
			"created_at": now,
		}
	}
	if ccName != "" {
		share["cc_name"] = ccName
	} else {
		share["cc_name"] = jx.GetOr(share, "cc_name", "")
	}
	share["mode"] = mode
	share["updated_at"] = now

	if mode == "password" {
		if password != "" {
			salt := shareRandBytes(32)
			share["password_hash"] = shareHashPassword(password, salt)
			share["salt"] = hex.EncodeToString(salt)
			shareDropSessions(jx.Str(share["token"]))
		} else if !jx.Truthy(share["password_hash"]) {
			return jx.M{"error": "Password is required for password-protected sharing"}
		}
	} else {
		delete(share, "password_hash")
		delete(share, "salt")
	}

	if idx >= 0 {
		entries[idx].share = share
	} else {
		entries = append(entries, shareEntry{key, share})
	}
	shareSave(entries)
	return jx.M{"share": sharePublicInfo(share)}
}

func shareDelete(c *Ctx) any {
	key := shareKey(c.Query("enterprise", ""), c.Query("cc_id", ""))
	mu := jx.FileLock(shareFile())
	mu.Lock()
	defer mu.Unlock()
	entries := shareLoad()
	idx := -1
	for i, e := range entries {
		if e.key == key {
			idx = i
			break
		}
	}
	if idx < 0 {
		return jx.M{"error": "Share not found"}
	}
	share := entries[idx].share
	entries = append(entries[:idx], entries[idx+1:]...)
	token := jx.Str(jx.GetOr(share, "token", ""))
	shareDropSessions(token)
	shareSave(entries)
	return jx.M{"ok": true}
}

// ---------------------------------------------------------------------------
// Public endpoints (no OctoFinance auth)
// ---------------------------------------------------------------------------

const sharePageCSS = `
:root{--bg:#0d1117;--card:#161b22;--border:#30363d;--text:#e6edf3;
--muted:#768390;--accent:#539bf5;--red:#e5534b}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
background:var(--bg);color:var(--text);
font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif}
.card{background:var(--card);border:1px solid var(--border);border-radius:12px;
padding:32px;width:380px;max-width:90vw;text-align:center}
.brand{font-size:12px;color:var(--muted);letter-spacing:.4px;margin-bottom:8px}
h1{font-size:18px;margin:0 0 6px}
p{font-size:13px;color:var(--muted);margin:0 0 20px}
input[type=password]{width:100%;padding:10px 12px;border-radius:8px;
border:1px solid var(--border);background:var(--bg);color:var(--text);
font-size:14px;outline:none;margin-bottom:12px}
input[type=password]:focus{border-color:var(--accent)}
button{width:100%;padding:10px;border:none;border-radius:8px;background:var(--accent);
color:#fff;font-size:14px;font-weight:600;cursor:pointer}
button:hover{filter:brightness(1.1)}
.err{color:var(--red);font-size:13px;margin:0 0 12px}
`

// shareHTML writes an HTMLResponse.
func shareHTML(w http.ResponseWriter, status int, html string, headers map[string]string) {
	h := w.Header()
	for k, v := range headers {
		h.Set(k, v)
	}
	h.Set("Content-Type", "text/html; charset=utf-8")
	h.Set("Content-Length", strconv.Itoa(len(html)))
	w.WriteHeader(status)
	_, _ = w.Write([]byte(html))
}

func sharePasswordPage(w http.ResponseWriter, token, ccName, errMsg string) {
	errHTML := ""
	if errMsg != "" {
		errHTML = `<p class="err">` + rptEscape(errMsg) + `</p>`
	}
	html := `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Cost Center Report · ` + rptEscape(ccName) + `</title>
<style>` + sharePageCSS + `</style>
</head>
<body>
<div class="card">
  <div class="brand">OctoFinance · Cost Center Report</div>
  <h1>` + rptEscape(ccName) + `</h1>
  <p>This report is password protected.</p>
  ` + errHTML + `
  <form method="post" action="/share/cc/` + rptEscape(token) + `/verify">
    <input type="password" name="password" placeholder="Password" autofocus required>
    <button type="submit">View Report</button>
  </form>
</div>
</body>
</html>`
	status := 200
	if errMsg != "" {
		status = 401
	}
	shareHTML(w, status, html, nil)
}

func shareErrorPage(w http.ResponseWriter, message string, status int) {
	html := `<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>OctoFinance</title><style>` + sharePageCSS + `</style></head>
<body><div class="card">
  <div class="brand">OctoFinance · Cost Center Report</div>
  <h1>Unavailable</h1><p>` + rptEscape(message) + `</p>
</div></body></html>`
	shareHTML(w, status, html, nil)
}

func shareCookieName(token string) string {
	if r := []rune(token); len(r) > 16 {
		token = string(r[:16])
	}
	return "ccshare_" + token
}

func shareHasAccess(share jx.M, r *http.Request) bool {
	if jx.GetOr(share, "mode", "public") == "public" {
		return true
	}
	token := jx.Str(share["token"])
	ck, err := r.Cookie(shareCookieName(token))
	if err != nil || ck.Value == "" {
		return false
	}
	shareVerifiedMu.Lock()
	defer shareVerifiedMu.Unlock()
	_, ok := shareVerified[token+":"+ck.Value]
	return ok
}

func shareCCName(share jx.M) string { return jx.Str(jx.GetOr(share, "cc_name", "Cost Center")) }

// shareRender builds the report HTML for a shared cost center ("" if data is gone).
func shareRender(share jx.M, forDownload bool) (string, bool) {
	enterprise := jx.Str(share["enterprise"])
	ccData := Collector.LoadLatestMap("cost_centers", enterprise)
	if !jx.Truthy(ccData) {
		return "", false
	}
	var cc jx.M
	for _, c := range jx.GetMaps(ccData, "cost_centers") {
		if shareIDStr(c["id"]) == shareIDStr(share["cc_id"]) {
			cc = c
			break
		}
	}
	if cc == nil {
		return "", false
	}
	downloadURL := ""
	if !forDownload {
		downloadURL = "/share/cc/" + jx.Str(share["token"]) + "/download"
	}
	return GenerateSingleReportHTML(
		enterprise,
		jx.Str(jx.GetOr(ccData, "enterprise_name", enterprise)),
		cc,
		LoadAllCSVRecords(CSVTypeAI),
		LoadAllCSVRecords(CSVTypeUsage),
		downloadURL,
		APIs.WebBaseForEnterprise(enterprise),
	), true
}

// shareIDStr is Python str() for an id (None -> "None").
func shareIDStr(v any) string {
	if v == nil {
		return "None"
	}
	return jx.Str(v)
}

const shareMissingMsg = "This share link does not exist or has been disabled."
const shareGoneMsg = "Report data is not available. Please contact the administrator."

func shareView(c *Ctx) any {
	token := c.Path("token")
	share := shareFindByToken(token)
	if share == nil {
		shareErrorPage(c.W, shareMissingMsg, 404)
		return nil
	}
	if !shareHasAccess(share, c.R) {
		sharePasswordPage(c.W, token, shareCCName(share), "")
		return nil
	}
	html, ok := shareRender(share, false)
	if !ok {
		shareErrorPage(c.W, shareGoneMsg, 503)
		return nil
	}
	shareHTML(c.W, 200, html, nil)
	return nil
}

// shareRedirect mirrors Starlette's RedirectResponse(url, 303).
func shareRedirect(w http.ResponseWriter, location string, cookie string) {
	h := w.Header()
	h.Set("Location", shareQuoteURL(location))
	h.Set("Content-Length", "0")
	if cookie != "" {
		h.Add("Set-Cookie", cookie)
	}
	w.WriteHeader(http.StatusSeeOther)
}

// shareQuoteURL is urllib.parse.quote(url, safe=":/%#?=@[]!$&'()*+,;").
func shareQuoteURL(s string) string {
	const safe = ":/%#?=@[]!$&'()*+,;"
	var b strings.Builder
	for i := 0; i < len(s); i++ {
		ch := s[i]
		if (ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z') || (ch >= '0' && ch <= '9') ||
			strings.IndexByte("_.-~", ch) >= 0 || strings.IndexByte(safe, ch) >= 0 {
			b.WriteByte(ch)
		} else {
			b.WriteString("%" + strings.ToUpper(hex.EncodeToString([]byte{ch})))
		}
	}
	return b.String()
}

func shareFormPassword(r *http.Request) string {
	ct := r.Header.Get("Content-Type")
	if strings.HasPrefix(ct, "multipart/form-data") {
		if err := r.ParseMultipartForm(32 << 20); err != nil {
			return ""
		}
		return r.PostFormValue("password")
	}
	if strings.HasPrefix(ct, "application/x-www-form-urlencoded") {
		if err := r.ParseForm(); err != nil {
			return ""
		}
		return r.PostFormValue("password")
	}
	return ""
}

func shareVerify(c *Ctx) any {
	token := c.Path("token")
	password := shareFormPassword(c.R)
	share := shareFindByToken(token)
	if share == nil {
		shareErrorPage(c.W, shareMissingMsg, 404)
		return nil
	}
	if jx.AsString(share["mode"]) != "password" {
		shareRedirect(c.W, "/share/cc/"+token, "")
		return nil
	}
	saltHex := jx.Str(jx.GetOr(share, "salt", ""))
	stored := jx.Str(jx.GetOr(share, "password_hash", ""))
	ok := false
	if saltHex != "" && stored != "" {
		if salt, err := hex.DecodeString(saltHex); err == nil {
			ok = subtle.ConstantTimeCompare([]byte(shareHashPassword(password, salt)), []byte(stored)) == 1
		}
	}
	if !ok {
		sharePasswordPage(c.W, token, shareCCName(share), "Incorrect password.")
		return nil
	}
	session := hex.EncodeToString(shareRandBytes(16))
	shareVerifiedMu.Lock()
	shareVerified[token+":"+session] = struct{}{}
	shareVerifiedMu.Unlock()
	cookie := shareCookieName(token) + "=" + session +
		"; HttpOnly; Max-Age=86400; Path=/share/cc/" + token + "; SameSite=lax"
	shareRedirect(c.W, "/share/cc/"+token, cookie)
	return nil
}

func shareDownload(c *Ctx) any {
	token := c.Path("token")
	share := shareFindByToken(token)
	if share == nil {
		shareErrorPage(c.W, shareMissingMsg, 404)
		return nil
	}
	if !shareHasAccess(share, c.R) {
		sharePasswordPage(c.W, token, shareCCName(share), "")
		return nil
	}
	html, ok := shareRender(share, true)
	if !ok {
		shareErrorPage(c.W, shareGoneMsg, 503)
		return nil
	}
	safe := "cost-center"
	if jx.Truthy(share["cc_name"]) {
		safe = jx.Str(share["cc_name"])
	}
	safe = strings.NewReplacer("/", "_", "\\", "_", " ", "_").Replace(safe)
	var ascii strings.Builder
	for _, r := range safe {
		if r < 128 {
			ascii.WriteRune(r)
		}
	}
	name := ascii.String()
	if name == "" {
		name = "cost-center"
	}
	shareHTML(c.W, 200, html, map[string]string{
		"Content-Disposition": `attachment; filename="` + name + `-report.html"`,
	})
	return nil
}

// shareKV / shareOrderedObj encode a JSON object with a fixed key order.
type shareKV struct {
	k string
	v any
}

type shareOrderedObj []shareKV

func (o shareOrderedObj) MarshalJSON() ([]byte, error) {
	var b bytes.Buffer
	b.WriteByte('{')
	for i, kv := range o {
		if i > 0 {
			b.WriteByte(',')
		}
		k, err := jx.Marshal(kv.k)
		if err != nil {
			return nil, err
		}
		v, err := jx.Marshal(kv.v)
		if err != nil {
			return nil, err
		}
		b.Write(k)
		b.WriteByte(':')
		b.Write(v)
	}
	b.WriteByte('}')
	return b.Bytes(), nil
}

// shareObjectKeys returns the keys of the top-level "shares" object in file order.
func shareObjectKeys(data []byte) []string {
	dec := json.NewDecoder(bytes.NewReader(data))
	if t, err := dec.Token(); err != nil || t != json.Delim('{') {
		return nil
	}
	for dec.More() {
		t, err := dec.Token()
		if err != nil {
			return nil
		}
		name, _ := t.(string)
		if name != "shares" {
			var skip json.RawMessage
			if dec.Decode(&skip) != nil {
				return nil
			}
			continue
		}
		if t, err := dec.Token(); err != nil || t != json.Delim('{') {
			return nil
		}
		keys := []string{}
		for dec.More() {
			t, err := dec.Token()
			if err != nil {
				return keys
			}
			keys = append(keys, t.(string))
			var skip json.RawMessage
			if dec.Decode(&skip) != nil {
				return keys
			}
		}
		return keys
	}
	return nil
}
