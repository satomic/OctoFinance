package app

import (
	"fmt"
	"path/filepath"
	"strconv"
	"time"

	"github.com/satomic/octofinance/backend-go/internal/jx"
)

// AI chat: SSE streaming, simple request/response, models and chat credentials.

func init() { registerRoutes(registerChatRoutes) }

func registerChatRoutes(r *Router) {
	r.Handle("GET /api/chat/auth", func(c *Ctx) any {
		return jx.M{"config": chatAuthConfig(), "status": Engine.AuthStatus(c.R.Context(), c.QueryBool("refresh", false))}
	})
	r.Handle("PUT /api/chat/auth", updateChatAuth)
	r.Handle("GET /api/chat/models", func(c *Ctx) any {
		models, err := Engine.ListModels(c.R.Context())
		if err != nil {
			return jx.M{"models": jx.L{}, "error": err.Error()}
		}
		return jx.M{"models": models}
	})
	r.Handle("POST /api/chat", chatStream)
	r.Handle("POST /api/chat/simple", chatSimple)
}

func chatAuthConfig() jx.M {
	token, host := ChatAuthGet()
	masked := ""
	if token != "" {
		masked = MaskToken(token)
	}
	return jx.M{"token_set": token != "", "token_masked": masked, "host": host}
}

func updateChatAuth(c *Ctx) any {
	var body struct {
		Token      *string `json:"token"`
		Host       *string `json:"host"`
		ClearToken bool    `json:"clear_token"`
	}
	if r := c.Bind(&body); r != nil {
		return r
	}
	if _, _, err := ChatAuthSave(body.Token, body.Host, body.ClearToken); err != nil {
		return JSONStatus(400, jx.M{"error": err.Error()})
	}
	status := Engine.ApplyAuthSettings(c.R.Context())
	return jx.M{"config": chatAuthConfig(), "status": status}
}

type chatRequest struct {
	Message   *string `json:"message"`
	SessionID string  `json:"session_id"`
	Model     string  `json:"model"`
}

func nowMillis() int64 { return time.Now().UnixMilli() }

// prepareChat validates the request, auto-creates the session and stores the user message.
func prepareChat(c *Ctx) (chatRequest, string, *Resp) {
	var req chatRequest
	if r := c.Bind(&req); r != nil {
		return req, "", r
	}
	if req.Message == nil {
		return req, "", Missing("message")
	}
	if req.SessionID == "" {
		req.SessionID = "default"
	}
	if !validSessionID(req.SessionID) {
		return req, "", HTTPError(400, "Invalid session id")
	}
	sid := req.SessionID
	if !Sessions.Exists(sid) {
		Sessions.Create(sid, "")
	}
	now := nowMillis()
	Sessions.AppendMessage(sid, jx.M{
		"id": strconv.FormatInt(now, 10), "role": "user", "content": *req.Message, "timestamp": now,
	})
	return req, filepath.Join(SessionsDir(), sid), nil
}

func saveAssistantMessage(sid, content string) {
	if content == "" {
		return
	}
	now := nowMillis()
	Sessions.AppendMessage(sid, jx.M{
		"id": strconv.FormatInt(now+1, 10), "role": "assistant", "content": content, "timestamp": now,
	})
}

func chatStream(c *Ctx) any {
	req, wd, r := prepareChat(c)
	if r != nil {
		return r
	}
	sid := req.SessionID
	send, comment := c.SSE()
	fullContent := ""
	defer func() {
		if rec := recover(); rec != nil {
			_ = send("error", jx.Dumps(jx.M{"type": "error", "content": fmt.Sprint(rec)}))
		}
		saveAssistantMessage(sid, fullContent)
	}()

	// sse-starlette pings every 15s; keep proxies from closing an idle stream.
	stop := make(chan struct{})
	pings := make(chan struct{}, 1)
	go func() {
		t := time.NewTicker(15 * time.Second)
		defer t.Stop()
		for {
			select {
			case <-stop:
				return
			case <-t.C:
				select {
				case pings <- struct{}{}:
				default:
				}
			}
		}
	}()
	defer close(stop)

	events := make(chan ChatEvent, 256)
	errCh := make(chan error, 1)
	go func() {
		defer close(events)
		errCh <- Engine.Chat(c.R.Context(), *req.Message, sid, wd, req.Model, func(ce ChatEvent) {
			events <- ce
		})
	}()
	for {
		select {
		case <-pings:
			_ = comment("ping - " + time.Now().UTC().Format("2006-01-02 15:04:05.000000+00:00"))
		case ce, ok := <-events:
			if !ok {
				if err := <-errCh; err != nil && c.R.Context().Err() == nil {
					_ = send("error", jx.Dumps(jx.M{"type": "error", "content": cleanError(err)}))
				}
				return nil
			}
			typ := jx.Str(ce["type"])
			switch typ {
			case "delta":
				fullContent += jx.Str(ce["content"])
			case "message":
				if s := jx.Str(ce["content"]); s != "" {
					fullContent = s
				}
			case "tool_start":
				Sessions.AppendToolCall(sid, jx.M{
					"event": "tool_start", "tool_name": ce["content"], "tool_call_id": ce["tool_call_id"],
					"arguments": ce["detail"], "timestamp": nowMillis(),
				})
			case "tool_complete":
				Sessions.AppendToolCall(sid, jx.M{
					"event": "tool_complete", "tool_name": ce["content"], "tool_call_id": ce["tool_call_id"],
					"result": ce["detail"], "timestamp": nowMillis(),
				})
			}
			if err := send(typ, jx.Dumps(ce)); err != nil {
				// client went away; keep draining so the engine finishes cleanly
				continue
			}
		}
	}
}

func chatSimple(c *Ctx) any {
	req, wd, r := prepareChat(c)
	if r != nil {
		return r
	}
	response, err := Engine.ChatSimple(c.R.Context(), *req.Message, req.SessionID, wd, req.Model)
	if err != nil {
		return HTTPError(500, cleanError(err))
	}
	saveAssistantMessage(req.SessionID, response)
	return jx.M{"response": response, "session_id": req.SessionID}
}
