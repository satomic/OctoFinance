package app

import (
	"context"
	"fmt"
	"reflect"
	"runtime"
	"sort"
	"strings"

	copilot "github.com/github/copilot-sdk/go"

	"github.com/satomic/octofinance/backend-go/internal/jx"
)

// Tool definitions for the Copilot SDK. Parameters are declared explicitly
// (name, JSON type, description, default) to mirror the Pydantic models of
// the Python tools, defaults included.

// P declares one tool parameter.
type P struct {
	Name     string
	Type     string // "string", "integer", "number", "boolean", "array", "object"
	Items    string // element type for arrays (default "string")
	Desc     string
	Default  any  // used when the argument is absent or null
	Required bool // no default; the LLM must supply it
	Nullable bool // accepts null (Pydantic "X | None")
	Enum     []string
}

// Args are the decoded tool arguments with defaults applied.
type Args struct {
	m jx.M
}

// Raw returns the argument value (nil when absent).
func (a Args) Raw(name string) any { return a.m[name] }

// Has reports whether a non-null value was supplied (or defaulted).
func (a Args) Has(name string) bool { return a.m[name] != nil }

// Str returns a string argument.
func (a Args) Str(name string) string { return jx.Str(a.m[name]) }

// Int returns an integer argument.
func (a Args) Int(name string) int { return jx.Int(a.m[name]) }

// Float returns a number argument.
func (a Args) Float(name string) float64 { return jx.Float(a.m[name]) }

// FloatPtr returns nil for a null/absent number.
func (a Args) FloatPtr(name string) *float64 {
	if a.m[name] == nil {
		return nil
	}
	f := jx.Float(a.m[name])
	return &f
}

// Bool returns a boolean argument.
func (a Args) Bool(name string) bool { return jx.Truthy(a.m[name]) }

// BoolPtr returns nil for a null/absent boolean.
func (a Args) BoolPtr(name string) *bool {
	if a.m[name] == nil {
		return nil
	}
	b := jx.Truthy(a.m[name])
	return &b
}

// Strings returns a string-array argument.
func (a Args) Strings(name string) []string {
	v := a.m[name]
	if s, ok := v.(string); ok && s != "" {
		return []string{s}
	}
	out := []string{}
	for _, e := range jx.List(v) {
		out = append(out, jx.Str(e))
	}
	return out
}

// Map returns an object argument.
func (a Args) Map(name string) jx.M { return jx.Map(a.m[name]) }

// List returns an array argument.
func (a Args) List(name string) jx.L { return jx.List(a.m[name]) }

func paramSchema(p P) jx.M {
	s := jx.M{}
	if p.Desc != "" {
		s["description"] = p.Desc
	}
	switch p.Type {
	case "array":
		item := p.Items
		if item == "" {
			item = "string"
		}
		s["type"] = "array"
		s["items"] = jx.M{"type": item}
	case "":
		s["type"] = "string"
	default:
		s["type"] = p.Type
	}
	if len(p.Enum) > 0 {
		s["enum"] = p.Enum
	}
	if p.Nullable {
		s["type"] = jx.L{s["type"], "null"}
	}
	if !p.Required && p.Default != nil {
		s["default"] = p.Default
	}
	return s
}

func coerce(p P, v any) (any, error) {
	if v == nil {
		return nil, nil
	}
	switch p.Type {
	case "integer":
		f, ok := jx.FloatOK(v)
		if !ok {
			return nil, fmt.Errorf("%s: Input should be a valid integer", p.Name)
		}
		return float64(int64(f)), nil
	case "number":
		f, ok := jx.FloatOK(v)
		if !ok {
			return nil, fmt.Errorf("%s: Input should be a valid number", p.Name)
		}
		return f, nil
	case "boolean":
		switch t := v.(type) {
		case bool:
			return t, nil
		case string:
			switch strings.ToLower(t) {
			case "true", "1", "yes", "on":
				return true, nil
			case "false", "0", "no", "off":
				return false, nil
			}
		case float64:
			return t != 0, nil
		}
		return nil, fmt.Errorf("%s: Input should be a valid boolean", p.Name)
	case "array":
		l, ok := v.([]any)
		if !ok {
			return nil, fmt.Errorf("%s: Input should be a valid list", p.Name)
		}
		if p.Items == "" || p.Items == "string" {
			for i, e := range l {
				if _, isStr := e.(string); !isStr {
					return nil, fmt.Errorf("%s.%d: Input should be a valid string", p.Name, i)
				}
			}
		}
		return l, nil
	case "string", "":
		switch v.(type) {
		case string:
			return v, nil
		case float64, bool:
			return jx.Str(v), nil
		}
		return nil, fmt.Errorf("%s: Input should be a valid string", p.Name)
	}
	return v, nil
}

// defineTool builds a Copilot SDK tool. fn returns a string (passed through)
// or any value (JSON-encoded), like the Python tools returning json.dumps(...).
func defineTool(name, description string, params []P, fn func(a Args) any) copilot.Tool {
	props := jx.M{}
	required := []string{}
	for _, p := range params {
		props[p.Name] = paramSchema(p)
		if p.Required {
			required = append(required, p.Name)
		}
	}
	schema := jx.M{"type": "object", "properties": props}
	if len(required) > 0 {
		schema["required"] = required
	}
	return copilot.Tool{
		Name:        name,
		Description: description,
		Parameters:  schema,
		Handler: func(inv copilot.ToolInvocation) (result copilot.ToolResult, err error) {
			defer func() {
				if r := recover(); r != nil {
					Logger.Error(fmt.Sprintf("tool %s panicked: %v", name, r))
					result = toolFailure(fmt.Sprint(r))
					err = nil
				}
			}()
			raw := jx.Map(jx.Normalize(inv.Arguments))
			if raw == nil {
				raw = jx.M{}
			}
			args := jx.M{}
			missing := []string{}
			for _, p := range params {
				v, ok := raw[p.Name]
				if !ok || v == nil {
					if p.Required && !p.Nullable {
						missing = append(missing, p.Name)
						continue
					}
					args[p.Name] = jx.DeepCopy(p.Default)
					continue
				}
				cv, cerr := coerce(p, v)
				if cerr != nil {
					return validationFailure(name, cerr.Error()), nil
				}
				args[p.Name] = cv
			}
			if len(missing) > 0 {
				return validationFailure(name, "missing required argument(s): "+strings.Join(missing, ", ")), nil
			}
			out := fn(Args{m: args})
			text, ok := out.(string)
			if !ok {
				text = jx.Dumps(out)
			}
			return copilot.ToolResult{TextResultForLLM: text, ResultType: "success"}, nil
		},
	}
}

func validationFailure(tool, msg string) copilot.ToolResult {
	return toolFailure(fmt.Sprintf("Invalid arguments for %s: %s", tool, msg))
}

// toolFailure mirrors the Python SDK: the LLM gets a generic message, the
// detail is kept in Error for debugging.
func toolFailure(detail string) copilot.ToolResult {
	return copilot.ToolResult{
		TextResultForLLM: "Invoking this tool produced an error. Detailed information is not available.",
		ResultType:       "failure",
		Error:            detail,
		ToolTelemetry:    map[string]any{},
	}
}

// RunTool invokes one tool outside a chat (CLI: octofinance -tool NAME -args JSON).
// It loads PATs and runs discovery first, like the server startup does.
func RunTool(name, argsJSON string) (string, error) {
	EnsureDataDirs()
	Syncs.LoadStatus()
	Pats.Load()
	APIs.Rebuild(context.Background())
	var args any = map[string]any{}
	if strings.TrimSpace(argsJSON) != "" {
		if err := jsonDecode(strings.NewReader(argsJSON), &args); err != nil {
			return "", fmt.Errorf("invalid -args JSON: %w", err)
		}
	}
	for _, t := range BuildTools("") {
		if t.Name == name {
			res, err := t.Handler(copilot.ToolInvocation{ToolName: name, Arguments: args})
			if err != nil {
				return "", err
			}
			out := res.TextResultForLLM
			if res.ResultType != "success" {
				out = jx.Dumps(jx.M{"result_type": res.ResultType, "text": res.TextResultForLLM, "error": res.Error})
			}
			return out, nil
		}
	}
	return "", fmt.Errorf("unknown tool %q", name)
}

// ToolNames lists every registered tool name.
func ToolNames() []string {
	out := []string{}
	for _, t := range BuildTools("") {
		out = append(out, t.Name)
	}
	return out
}

// ToolCtx is what tool factories are built with: the session-scoped collector.
type ToolCtx struct {
	Collector *DataCollector
}

// Context returns a background context for API calls made by tools.
func (tc *ToolCtx) Context() context.Context { return context.Background() }

var toolFactories []func(tc *ToolCtx) []copilot.Tool

// registerTools adds a tool factory (called from init()).
func registerTools(fn func(tc *ToolCtx) []copilot.Tool) { toolFactories = append(toolFactories, fn) }

// toolFactoryOrder is the Python registration order (copilot_engine._build_tools_for_session).
var toolFactoryOrder = []string{"seatTools", "usageTools", "billingTools", "actionTools",
	"costCenterTools", "budgetTools", "entTeamTools", "syncTools"}

func orderedToolFactories() []func(tc *ToolCtx) []copilot.Tool {
	rank := func(f func(tc *ToolCtx) []copilot.Tool) int {
		name := runtime.FuncForPC(reflect.ValueOf(f).Pointer()).Name()
		for i, n := range toolFactoryOrder {
			if strings.HasSuffix(name, "."+n) {
				return i
			}
		}
		return len(toolFactoryOrder)
	}
	out := append([]func(tc *ToolCtx) []copilot.Tool{}, toolFactories...)
	sort.SliceStable(out, func(i, j int) bool { return rank(out[i]) < rank(out[j]) })
	return out
}

// BuildTools builds every tool for a session working directory ("" = global data).
func BuildTools(workingDirectory string) []copilot.Tool {
	collector := Collector
	if workingDirectory != "" {
		collector = NewSessionCollector(workingDirectory)
	}
	tc := &ToolCtx{Collector: collector}
	tools := []copilot.Tool{}
	seen := map[string]bool{}
	for _, f := range orderedToolFactories() {
		for _, t := range f(tc) {
			if seen[t.Name] {
				Logger.Warn("duplicate tool name: " + t.Name)
				continue
			}
			seen[t.Name] = true
			tools = append(tools, t)
		}
	}
	return tools
}
