package app

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"strings"

	"github.com/satomic/octofinance/backend-go/internal/jx"
)

// Ctx wraps one request. Handlers return the response body (written as JSON
// with status 200), a *Resp for a custom status, or nil when they already
// wrote the response themselves (streams, files, redirects).
type Ctx struct {
	W    http.ResponseWriter
	R    *http.Request
	User jx.M // session payload; nil on public routes when logged out

	body     []byte
	bodyRead bool
}

// Handler handles a request.
type Handler func(c *Ctx) any

// Resp is a response with an explicit status.
type Resp struct {
	Status int
	Body   any
}

// JSONStatus returns body with the given status.
func JSONStatus(status int, body any) *Resp { return &Resp{Status: status, Body: body} }

// HTTPError mirrors FastAPI's HTTPException: {"detail": msg} with status.
func HTTPError(status int, detail string) *Resp {
	return &Resp{Status: status, Body: jx.M{"detail": detail}}
}

// Query returns a query parameter (def when absent).
func (c *Ctx) Query(name string, def ...string) string {
	q := c.R.URL.Query()
	if q.Has(name) {
		return q.Get(name)
	}
	if len(def) > 0 {
		return def[0]
	}
	return ""
}

// HasQuery reports whether a query parameter is present.
func (c *Ctx) HasQuery(name string) bool { return c.R.URL.Query().Has(name) }

// QueryBool parses a boolean query parameter like FastAPI (true/1/yes/on).
func (c *Ctx) QueryBool(name string, def bool) bool {
	if !c.HasQuery(name) {
		return def
	}
	switch strings.ToLower(strings.TrimSpace(c.Query(name))) {
	case "1", "true", "yes", "on", "t", "y":
		return true
	case "0", "false", "no", "off", "f", "n":
		return false
	}
	return def
}

// QueryInt parses an integer query parameter.
func (c *Ctx) QueryInt(name string, def int) int {
	if !c.HasQuery(name) {
		return def
	}
	v, err := strconv.Atoi(strings.TrimSpace(c.Query(name)))
	if err != nil {
		return def
	}
	return v
}

// Path returns a path parameter.
func (c *Ctx) Path(name string) string { return c.R.PathValue(name) }

// Body returns the raw request body (read once, cached).
func (c *Ctx) Body() []byte {
	if !c.bodyRead {
		c.bodyRead = true
		if c.R.Body != nil {
			c.body, _ = io.ReadAll(io.LimitReader(c.R.Body, 256<<20))
		}
	}
	return c.body
}

// Bind decodes the JSON body into v. On failure it returns a 422 response
// (FastAPI's validation error shape) that the handler should return.
func (c *Ctx) Bind(v any) *Resp {
	b := bytes.TrimSpace(c.Body())
	if len(b) == 0 {
		b = []byte("{}")
	}
	if err := json.Unmarshal(b, v); err != nil {
		return JSONStatus(422, jx.M{"detail": jx.L{jx.M{
			"type": "json_invalid", "loc": jx.L{"body"}, "msg": err.Error(),
		}}})
	}
	return nil
}

// BindMap decodes the body as a JSON object.
func (c *Ctx) BindMap() (jx.M, *Resp) {
	var m jx.M
	if r := c.Bind(&m); r != nil {
		return nil, r
	}
	if m == nil {
		m = jx.M{}
	}
	return m, nil
}

// Missing returns FastAPI's 422 for missing required body fields.
func Missing(fields ...string) *Resp {
	errs := jx.L{}
	for _, f := range fields {
		errs = append(errs, jx.M{"type": "missing", "loc": jx.L{"body", f}, "msg": "Field required"})
	}
	return JSONStatus(422, jx.M{"detail": errs})
}

// Login returns the current user's login ("" when anonymous).
func (c *Ctx) Login() string { return jx.Str(jx.Get(c.User, "login")) }

// IsAdmin reports whether the current user is an administrator.
func (c *Ctx) IsAdmin() bool { return jx.GetBool(c.User, "is_admin") }

// WriteJSON writes a JSON response.
func WriteJSON(w http.ResponseWriter, status int, v any) {
	b, err := jx.Marshal(v)
	if err != nil {
		status = 500
		b, _ = jx.Marshal(jx.M{"detail": "Failed to encode response: " + err.Error()})
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_, _ = w.Write(b)
}

// SSE prepares a text/event-stream response and returns a send function.
// send(event, data) writes "event: e\ndata: d\n\n" (event may be empty).
func (c *Ctx) SSE() (send func(event, data string) error, comment func(text string) error) {
	h := c.W.Header()
	h.Set("Content-Type", "text/event-stream")
	h.Set("Cache-Control", "no-cache")
	h.Set("Connection", "keep-alive")
	h.Set("X-Accel-Buffering", "no")
	c.W.WriteHeader(http.StatusOK)
	flusher, _ := c.W.(http.Flusher)
	flush := func() {
		if flusher != nil {
			flusher.Flush()
		}
	}
	flush()
	send = func(event, data string) error {
		var buf strings.Builder
		if event != "" {
			fmt.Fprintf(&buf, "event: %s\r\n", event)
		}
		for _, line := range strings.Split(data, "\n") {
			fmt.Fprintf(&buf, "data: %s\r\n", line)
		}
		buf.WriteString("\r\n")
		if _, err := io.WriteString(c.W, buf.String()); err != nil {
			return err
		}
		flush()
		return nil
	}
	comment = func(text string) error {
		if _, err := io.WriteString(c.W, ": "+text+"\n\n"); err != nil {
			return err
		}
		flush()
		return nil
	}
	return send, comment
}

// Router registers routes on a ServeMux with the Ctx adapter.
type Router struct {
	mux *http.ServeMux
}

// Handle registers pattern ("GET /api/x/{id}") -> handler.
func (r *Router) Handle(pattern string, h Handler) {
	r.mux.HandleFunc(pattern, func(w http.ResponseWriter, req *http.Request) {
		c := &Ctx{W: w, R: req, User: requestUser(req)}
		defer func() {
			if rec := recover(); rec != nil {
				Logger.Error(fmt.Sprintf("panic in %s: %v", pattern, rec))
				WriteJSON(w, 500, jx.M{"detail": fmt.Sprintf("Internal Server Error: %v", rec)})
			}
		}()
		writeResult(w, h(c))
	})
}

func writeResult(w http.ResponseWriter, out any) {
	switch v := out.(type) {
	case nil:
		return
	case *Resp:
		WriteJSON(w, v.Status, v.Body)
	default:
		WriteJSON(w, 200, v)
	}
}

// routeRegistrars is filled by each routes_*.go file's init().
var routeRegistrars []func(*Router)

// registerRoutes adds a route group (called from init()).
func registerRoutes(fn func(*Router)) { routeRegistrars = append(routeRegistrars, fn) }

func jsonDecode(r io.Reader, v any) error { return json.NewDecoder(r).Decode(v) }
