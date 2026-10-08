package app

import (
	"errors"
	"fmt"
	"os"
	"sort"
	"strings"
	"sync"
	"syscall"

	"github.com/satomic/octofinance/backend-go/internal/jx"
)

// Saved AI chat prompts (data/saved_prompts.json). Each prompt belongs to the
// admin who saved it; a shared prompt is visible read-only to every admin.

const (
	maxPromptTitleLength = 80
	maxPromptLength      = 8000
)

var (
	errPromptNotFound  = errors.New("prompt not found")
	errPromptForbidden = errors.New("prompt forbidden")
	promptsMu          sync.Mutex
)

func promptsFile() string { return dataPath("saved_prompts.json") }

func loadPrompts() []jx.M {
	v, err := jx.ReadJSON(promptsFile())
	if err != nil {
		return []jx.M{}
	}
	return jx.GetMaps(jx.Map(v), "prompts")
}

// withFlock runs fn under an exclusive flock on lockPath (shared with the Python backend).
func withFlock(lockPath string, fn func()) {
	_ = os.MkdirAll(DataDir, 0o755)
	f, err := os.OpenFile(lockPath, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
	if err == nil {
		defer f.Close()
		_ = syscall.Flock(int(f.Fd()), syscall.LOCK_EX)
		defer syscall.Flock(int(f.Fd()), syscall.LOCK_UN)
	}
	fn()
}

func lockedPrompts(mutate func(prompts *[]jx.M) (jx.M, error)) (jx.M, error) {
	promptsMu.Lock()
	defer promptsMu.Unlock()
	var result jx.M
	var err error
	withFlock(strings.TrimSuffix(promptsFile(), ".json")+".lock", func() {
		prompts := loadPrompts()
		result, err = mutate(&prompts)
		if err == nil {
			_ = jx.WriteJSON(promptsFile(), jx.M{"prompts": prompts})
		}
	})
	return result, err
}

func cleanPrompt(title, prompt string) (string, string, error) {
	title, prompt = strings.TrimSpace(title), strings.TrimSpace(prompt)
	if prompt == "" {
		return "", "", fmt.Errorf("Prompt text is required")
	}
	if len([]rune(prompt)) > maxPromptLength {
		return "", "", fmt.Errorf("Prompt text must be at most %d characters", maxPromptLength)
	}
	if title == "" {
		r := []rune(strings.Join(strings.Fields(prompt), " "))
		if len(r) > maxPromptTitleLength {
			r = r[:maxPromptTitleLength]
		}
		title = string(r)
	}
	if len([]rune(title)) > maxPromptTitleLength {
		return "", "", fmt.Errorf("Title must be at most %d characters", maxPromptTitleLength)
	}
	return title, prompt, nil
}

func promptView(e jx.M, login string) jx.M {
	return jx.Merge(e, jx.M{"is_owner": strings.EqualFold(jx.Str(e["owner"]), login)})
}

func findPrompt(prompts []jx.M, id string) (jx.M, int) {
	for i, e := range prompts {
		if jx.Str(e["id"]) == id {
			return e, i
		}
	}
	return nil, -1
}

func listPrompts(login string) []jx.M {
	visible := []jx.M{}
	for _, e := range loadPrompts() {
		if jx.GetBool(e, "shared") || strings.EqualFold(jx.Str(e["owner"]), login) {
			visible = append(visible, promptView(e, login))
		}
	}
	sort.SliceStable(visible, func(i, j int) bool {
		a, b := jx.Str(visible[i]["last_used_at"]), jx.Str(visible[j]["last_used_at"])
		if a != b {
			return a > b
		}
		return jx.Str(visible[i]["updated_at"]) > jx.Str(visible[j]["updated_at"])
	})
	return visible
}

func init() { registerRoutes(registerPromptRoutes) }

func registerPromptRoutes(r *Router) {
	r.Handle("GET /api/prompts", func(c *Ctx) any {
		login := c.Login()
		if login == "" {
			return HTTPError(401, "Authentication required")
		}
		return jx.M{"prompts": listPrompts(login)}
	})
	r.Handle("POST /api/prompts", createPromptRoute)
	r.Handle("PUT /api/prompts/{prompt_id}", updatePromptRoute)
	r.Handle("DELETE /api/prompts/{prompt_id}", deletePromptRoute)
	r.Handle("POST /api/prompts/{prompt_id}/use", usePromptRoute)
}

func promptResult(entry jx.M, err error, login string) any {
	switch {
	case errors.Is(err, errPromptNotFound):
		return HTTPError(404, "Prompt not found")
	case errors.Is(err, errPromptForbidden):
		return HTTPError(403, "Only the admin who saved this prompt can change it")
	case err != nil:
		return HTTPError(400, err.Error())
	}
	return promptView(entry, login)
}

func createPromptRoute(c *Ctx) any {
	login := c.Login()
	if login == "" {
		return HTTPError(401, "Authentication required")
	}
	var body struct {
		Title  string  `json:"title"`
		Prompt *string `json:"prompt"`
		Shared bool    `json:"shared"`
	}
	if r := c.Bind(&body); r != nil {
		return r
	}
	if body.Prompt == nil {
		return Missing("prompt")
	}
	title, prompt, err := cleanPrompt(body.Title, *body.Prompt)
	if err != nil {
		return HTTPError(400, err.Error())
	}
	now := jx.NowISO()
	entry := jx.M{
		"id": randHex(6), "title": title, "prompt": prompt, "owner": login, "shared": body.Shared,
		"use_count": 0, "created_at": now, "updated_at": now, "last_used_at": nil,
	}
	_, err = lockedPrompts(func(prompts *[]jx.M) (jx.M, error) {
		*prompts = append(*prompts, entry)
		return entry, nil
	})
	return promptResult(entry, err, login)
}

func updatePromptRoute(c *Ctx) any {
	login := c.Login()
	if login == "" {
		return HTTPError(401, "Authentication required")
	}
	var body struct {
		Title  *string `json:"title"`
		Prompt *string `json:"prompt"`
		Shared *bool   `json:"shared"`
	}
	if r := c.Bind(&body); r != nil {
		return r
	}
	id := c.Path("prompt_id")
	entry, err := lockedPrompts(func(prompts *[]jx.M) (jx.M, error) {
		e, _ := findPrompt(*prompts, id)
		if e == nil {
			return nil, errPromptNotFound
		}
		if !strings.EqualFold(jx.Str(e["owner"]), login) {
			return nil, errPromptForbidden
		}
		title, prompt := jx.Str(e["title"]), jx.Str(e["prompt"])
		if body.Title != nil {
			title = *body.Title
		}
		if body.Prompt != nil {
			prompt = *body.Prompt
		}
		t, p, err := cleanPrompt(title, prompt)
		if err != nil {
			return nil, err
		}
		e["title"], e["prompt"], e["updated_at"] = t, p, jx.NowISO()
		if body.Shared != nil {
			e["shared"] = *body.Shared
		}
		return e, nil
	})
	return promptResult(entry, err, login)
}

func deletePromptRoute(c *Ctx) any {
	login := c.Login()
	if login == "" {
		return HTTPError(401, "Authentication required")
	}
	id := c.Path("prompt_id")
	_, err := lockedPrompts(func(prompts *[]jx.M) (jx.M, error) {
		e, i := findPrompt(*prompts, id)
		if e == nil {
			return nil, errPromptNotFound
		}
		if !strings.EqualFold(jx.Str(e["owner"]), login) {
			return nil, errPromptForbidden
		}
		*prompts = append((*prompts)[:i], (*prompts)[i+1:]...)
		return nil, nil
	})
	if err != nil {
		return promptResult(nil, err, login)
	}
	return jx.M{"ok": true}
}

func usePromptRoute(c *Ctx) any {
	login := c.Login()
	if login == "" {
		return HTTPError(401, "Authentication required")
	}
	id := c.Path("prompt_id")
	entry, err := lockedPrompts(func(prompts *[]jx.M) (jx.M, error) {
		e, _ := findPrompt(*prompts, id)
		if e == nil || (!jx.GetBool(e, "shared") && !strings.EqualFold(jx.Str(e["owner"]), login)) {
			return nil, errPromptNotFound
		}
		e["use_count"] = jx.GetInt(e, "use_count") + 1
		e["last_used_at"] = jx.NowISO()
		return e, nil
	})
	return promptResult(entry, err, login)
}
