package app

import (
	"github.com/satomic/octofinance/backend-go/internal/jx"
)

// Chat session CRUD.

func init() { registerRoutes(registerSessionRoutes) }

func registerSessionRoutes(r *Router) {
	r.Handle("GET /api/sessions", func(c *Ctx) any { return Sessions.List() })
	r.Handle("POST /api/sessions", func(c *Ctx) any {
		body := struct {
			Title *string `json:"title"`
		}{}
		if r := c.Bind(&body); r != nil {
			return r
		}
		title := DefaultSessionTitle
		if body.Title != nil {
			title = *body.Title
		}
		return Sessions.Create("", title)
	})
	r.Handle("GET /api/sessions/{session_id}", func(c *Ctx) any {
		s := Sessions.Get(c.Path("session_id"))
		if s == nil {
			return HTTPError(404, "Session not found")
		}
		return s
	})
	r.Handle("GET /api/sessions/{session_id}/messages", func(c *Ctx) any {
		id := c.Path("session_id")
		if !Sessions.Exists(id) {
			return HTTPError(404, "Session not found")
		}
		return Sessions.LoadMessages(id)
	})
	r.Handle("PUT /api/sessions/{session_id}", func(c *Ctx) any {
		body := struct {
			Title *string `json:"title"`
		}{}
		if r := c.Bind(&body); r != nil {
			return r
		}
		if body.Title == nil {
			return Missing("title")
		}
		meta := Sessions.UpdateTitle(c.Path("session_id"), *body.Title)
		if meta == nil {
			return HTTPError(404, "Session not found")
		}
		return meta
	})
	r.Handle("DELETE /api/sessions/{session_id}", func(c *Ctx) any {
		id := c.Path("session_id")
		Engine.DestroySession(id)
		Sessions.Delete(id)
		return jx.M{"ok": true}
	})
}
