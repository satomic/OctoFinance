package app

import (
	"bytes"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"math"
	"sort"
	"strconv"
	"strings"

	"github.com/satomic/octofinance/backend-go/internal/jx"
)

// User request workflow (Python routers/budget_requests.py): regular users
// submit budget / cost center requests; administrators approve or reject,
// applying the change against the real GitHub API.

const (
	brTypeBudget     = "budget"
	brTypeCostCenter = "cost_center"
	brStatusPending  = "pending"
	brStatusApproved = "approved"
	brStatusRejected = "rejected"
)

func init() { registerRoutes(registerBudgetRequestRoutes) }

func registerBudgetRequestRoutes(r *Router) {
	r.Handle("GET /api/budget-requests", brList)
	r.Handle("POST /api/budget-requests", brCreate)
	r.Handle("POST /api/budget-requests/review", brReview)
	r.Handle("POST /api/budget-requests/amount", brAmount)
	r.Handle("POST /api/budget-requests/resync", brResync)
	r.Handle("GET /api/budget-requests/audit", brAudit)
	r.Handle("DELETE /api/budget-requests/{request_id}", brDelete)
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// brPyStr is Python's str() for JSON values (None, True, 5.0 ...).
func brPyStr(v any) string {
	switch t := v.(type) {
	case nil:
		return "None"
	case float64:
		if math.IsInf(t, 0) || math.IsNaN(t) {
			return jx.Str(t)
		}
		if t == math.Trunc(t) && math.Abs(t) < 1e16 {
			return strconv.FormatFloat(t, 'f', 1, 64)
		}
		return strconv.FormatFloat(t, 'g', -1, 64)
	}
	return jx.Str(v)
}

func brNewID() string {
	b := make([]byte, 6)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}

func brFind(requests []jx.M, id string) jx.M {
	for _, r := range requests {
		if v, ok := r["id"].(string); ok && v == id {
			return r
		}
	}
	return nil
}

func brAppendHistory(target jx.M, event jx.M) {
	hist := jx.List(target["history"])
	if _, ok := target["history"]; !ok || hist == nil {
		hist = jx.L{}
	}
	target["history"] = append(hist, event)
}

func brAdminOnly(c *Ctx) *Resp {
	if !c.IsAdmin() {
		return JSONStatus(403, jx.M{"error": "Administrator access required"})
	}
	return nil
}

func brNotFound() *Resp { return JSONStatus(404, jx.M{"error": "Request not found"}) }

// ---------------------------------------------------------------------------
// Pydantic-style body parsing
// ---------------------------------------------------------------------------

type brFieldKind int

const (
	brStr brFieldKind = iota
	brFloatOpt
	brBool
)

type brField struct {
	name     string
	kind     brFieldKind
	required bool
	def      any
}

func brValErr(typ, field, msg string, input any) jx.M {
	return jx.M{"type": typ, "loc": jx.L{"body", field}, "msg": msg, "input": input}
}

// brParseBody validates the JSON body like a Pydantic v2 model (lax mode) and
// returns the coerced values.
func brParseBody(c *Ctx, fields []brField) (jx.M, *Resp) {
	raw := bytes.TrimSpace(c.Body())
	if len(raw) == 0 {
		return nil, JSONStatus(422, jx.M{"detail": jx.L{jx.M{
			"type": "missing", "loc": jx.L{"body"}, "msg": "Field required", "input": nil}}})
	}
	var anyBody any
	dec := json.NewDecoder(bytes.NewReader(raw))
	if err := dec.Decode(&anyBody); err != nil {
		return nil, JSONStatus(422, jx.M{"detail": jx.L{jx.M{
			"type": "json_invalid", "loc": jx.L{"body", 0}, "msg": "JSON decode error",
			"input": jx.M{}, "ctx": jx.M{"error": err.Error()}}}})
	}
	body, ok := anyBody.(map[string]any)
	if !ok {
		return nil, JSONStatus(422, jx.M{"detail": jx.L{jx.M{
			"type": "model_attributes_type", "loc": jx.L{"body"},
			"msg": "Input should be a valid dictionary or object to extract fields from", "input": anyBody}}})
	}
	out := jx.M{}
	errs := jx.L{}
	for _, f := range fields {
		v, present := body[f.name]
		if !present {
			if f.required {
				errs = append(errs, jx.M{"type": "missing", "loc": jx.L{"body", f.name}, "msg": "Field required", "input": body})
			} else {
				out[f.name] = f.def
			}
			continue
		}
		switch f.kind {
		case brStr:
			s, ok := v.(string)
			if !ok {
				errs = append(errs, brValErr("string_type", f.name, "Input should be a valid string", v))
				continue
			}
			out[f.name] = s
		case brFloatOpt:
			switch t := v.(type) {
			case nil:
				out[f.name] = nil
			case float64:
				out[f.name] = t
			case bool:
				if t {
					out[f.name] = 1.0
				} else {
					out[f.name] = 0.0
				}
			case string:
				x, err := strconv.ParseFloat(strings.TrimSpace(t), 64)
				if err != nil {
					errs = append(errs, brValErr("float_parsing", f.name, "Input should be a valid number, unable to parse string as a number", v))
					continue
				}
				out[f.name] = x
			default:
				errs = append(errs, brValErr("float_type", f.name, "Input should be a valid number", v))
			}
		case brBool:
			switch t := v.(type) {
			case bool:
				out[f.name] = t
			case float64:
				if t == 0 || t == 1 {
					out[f.name] = t == 1
				} else {
					errs = append(errs, brValErr("bool_parsing", f.name, "Input should be a valid boolean, unable to interpret input", v))
				}
			case string:
				switch strings.ToLower(t) {
				case "0", "off", "f", "false", "n", "no":
					out[f.name] = false
				case "1", "on", "t", "true", "y", "yes":
					out[f.name] = true
				default:
					errs = append(errs, brValErr("bool_parsing", f.name, "Input should be a valid boolean, unable to interpret input", v))
				}
			default:
				errs = append(errs, brValErr("bool_type", f.name, "Input should be a valid boolean", v))
			}
		}
	}
	if len(errs) > 0 {
		return nil, JSONStatus(422, jx.M{"detail": errs})
	}
	return out, nil
}

var brCreateFields = []brField{
	{name: "request_type", kind: brStr, def: brTypeBudget},
	{name: "amount", kind: brFloatOpt, def: nil},
	{name: "org", kind: brStr, def: ""},
	{name: "cost_center_id", kind: brStr, def: ""},
	{name: "reason", kind: brStr, def: ""},
}

var brReviewFields = []brField{
	{name: "request_id", kind: brStr, required: true},
	{name: "decision", kind: brStr, required: true},
	{name: "approved_amount", kind: brFloatOpt, def: nil},
	{name: "comment", kind: brStr, def: ""},
	{name: "apply_to_github", kind: brBool, def: true},
	{name: "prevent_further_usage", kind: brBool, def: true},
}

// ---------------------------------------------------------------------------
// Endpoints
// ---------------------------------------------------------------------------

func brList(c *Ctx) any {
	admin := c.IsAdmin()
	status := c.Query("status", "all")
	all := LoadBudgetRequests()
	requests := all
	if !admin {
		mine := []jx.M{}
		for _, r := range all {
			if strings.EqualFold(jx.Str(jx.GetOr(r, "user_login", "")), c.Login()) {
				mine = append(mine, r)
			}
		}
		requests = mine
	}
	if status != "" && status != "all" {
		filtered := []jx.M{}
		for _, r := range requests {
			if v, ok := r["status"].(string); ok && v == status {
				filtered = append(filtered, r)
			}
		}
		requests = filtered
	}
	requests = append([]jx.M{}, requests...)
	sort.SliceStable(requests, func(i, j int) bool {
		return jx.Str(jx.GetOr(requests[i], "created_at", "")) > jx.Str(jx.GetOr(requests[j], "created_at", ""))
	})

	stats := requests
	if admin {
		stats = all
	}
	var pending, approved, rejected, budgets, ccs int
	approvedAmts, pendingAmts := []float64{}, []float64{}
	for _, r := range stats {
		switch jx.Str(r["status"]) {
		case brStatusPending:
			pending++
			pendingAmts = append(pendingAmts, jx.Float(r["requested_amount"]))
		case brStatusApproved:
			approved++
			approvedAmts = append(approvedAmts, jx.Float(r["approved_amount"]))
		case brStatusRejected:
			rejected++
		}
		if rt, ok := r["request_type"]; !ok || rt == brTypeBudget {
			budgets++
		}
		if r["request_type"] == brTypeCostCenter {
			ccs++
		}
	}
	return jx.M{
		"requests": requests,
		"is_admin": admin,
		"summary": jx.M{
			"total":                len(stats),
			"pending":              pending,
			"approved":             approved,
			"rejected":             rejected,
			"approved_amount":      jx.Round(meFSum(approvedAmts), 2),
			"pending_amount":       jx.Round(meFSum(pendingAmts), 2),
			"budget_requests":      budgets,
			"cost_center_requests": ccs,
		},
	}
}

func brCreate(c *Ctx) any {
	p, bad := brParseBody(c, brCreateFields)
	if bad != nil {
		return bad
	}
	login := jx.Str(jx.GetOr(c.User, "login", ""))
	requestType := jx.Str(p["request_type"])
	if requestType == "" {
		requestType = brTypeBudget
	}
	requestType = strings.ToLower(strings.TrimSpace(requestType))
	if requestType != brTypeBudget && requestType != brTypeCostCenter {
		return jx.M{"error": "request_type must be 'budget' or 'cost_center'"}
	}

	var requestedAmount any
	costCenterID := ""
	var plan any
	if requestType == brTypeBudget {
		amt, ok := p["amount"].(float64)
		if !ok || amt <= 0 {
			return jx.M{"error": "A budget amount greater than 0 is required."}
		}
		requestedAmount = jx.Round(amt, 2)
	} else {
		costCenterID = strings.TrimSpace(jx.Str(p["cost_center_id"]))
		d := DiffCostCenterMembership(login, costCenterID)
		if d.Invalid {
			return jx.M{"error": "The selected cost center no longer exists."}
		}
		if len(d.Add) == 0 && len(d.Remove) == 0 {
			return jx.M{"error": "Your cost center selection matches your current assignment."}
		}
		entry := func(cc jx.M) any {
			if cc == nil {
				return nil
			}
			return ccpEntry(cc)
		}
		plan = jx.M{"from": entry(d.Current), "to": entry(d.Target)}
	}

	entry := jx.M{
		"id":               brNewID(),
		"request_type":     requestType,
		"user_login":       login,
		"user_name":        jx.GetOr(c.User, "name", ""),
		"avatar_url":       jx.GetOr(c.User, "avatar_url", ""),
		"requested_amount": requestedAmount,
		"approved_amount":  nil,
		"currency":         "USD",
		"org":              strings.TrimSpace(jx.Str(p["org"])),
		"cost_center_id":   costCenterID,
		"cost_center_plan": plan,
		"reason":           strings.TrimSpace(jx.Str(p["reason"])),
		"status":           brStatusPending,
		"created_at":       jx.NowISO(),
		"updated_at":       jx.NowISO(),
		"reviewed_by":      "",
		"reviewed_at":      "",
		"review_comment":   "",
		"history": jx.L{jx.M{
			"action": "created",
			"by":     login,
			"at":     jx.NowISO(),
			"amount": requestedAmount,
		}},
	}

	BudgetRequestsMu.Lock()
	requests := LoadBudgetRequests()
	requests = append(requests, entry)
	SaveBudgetRequests(requests)
	BudgetRequestsMu.Unlock()

	return jx.M{"ok": true, "request": entry}
}

func brReview(c *Ctx) any {
	p, bad := brParseBody(c, brReviewFields)
	if bad != nil {
		return bad
	}
	if r := brAdminOnly(c); r != nil {
		return r
	}
	requestID := jx.Str(p["request_id"])
	comment := strings.TrimSpace(jx.Str(p["comment"]))
	applyToGitHub := p["apply_to_github"].(bool)
	prevent := p["prevent_further_usage"].(bool)

	decision := strings.ToLower(strings.TrimSpace(jx.Str(p["decision"])))
	if decision != "approve" && decision != "reject" {
		return jx.M{"error": "decision must be 'approve' or 'reject'"}
	}
	target := brFind(LoadBudgetRequests(), requestID)
	if target == nil {
		return brNotFound()
	}

	var githubResult, ccResult jx.M
	var approvedAmount any
	requestType := jx.GetOr(target, "request_type", brTypeBudget)
	isCC := requestType == brTypeCostCenter

	if decision == "approve" {
		if isCC {
			if applyToGitHub {
				ccResult = ApplyCostCenterMembershipChange(c.R.Context(),
					jx.Str(jx.GetOr(target, "user_login", "")), jx.Str(target["cost_center_id"]))
			} else {
				ccResult = jx.M{
					"status": "skipped", "added": jx.L{}, "removed": jx.L{}, "errors": jx.L{},
					"reason": "apply_to_github=false", "synced_at": jx.NowISO(),
				}
			}
		} else {
			amount, ok := p["approved_amount"].(float64)
			if !ok {
				amount = jx.Float(target["requested_amount"])
			}
			if amount < 0 {
				return jx.M{"error": "Approved amount cannot be negative"}
			}
			amt := jx.Round(amount, 2)
			approvedAmount = amt
			if applyToGitHub {
				githubResult = ProvisionUserBudget(c.R.Context(), jx.Str(jx.GetOr(target, "user_login", "")), amt,
					jx.Str(jx.GetOr(target, "org", "")), prevent, false)
			} else {
				githubResult = jx.M{"status": "skipped", "reason": "apply_to_github=false", "synced_at": jx.NowISO()}
			}
		}
	}

	BudgetRequestsMu.Lock()
	requests := LoadBudgetRequests()
	target = brFind(requests, requestID)
	if target == nil {
		BudgetRequestsMu.Unlock()
		return brNotFound()
	}
	if decision == "approve" {
		target["status"] = brStatusApproved
		if isCC {
			target["cost_center_result"] = ccResult
		} else {
			target["approved_amount"] = approvedAmount
			target["github_budget"] = githubResult
		}
	} else {
		target["status"] = brStatusRejected
		target["approved_amount"] = nil
	}
	applied := githubResult
	if len(applied) == 0 {
		applied = ccResult
	}
	action := brStatusRejected
	if decision == "approve" {
		action = brStatusApproved
	}
	target["reviewed_by"] = jx.GetOr(c.User, "login", "")
	target["reviewed_at"] = jx.NowISO()
	target["review_comment"] = comment
	target["updated_at"] = jx.NowISO()
	brAppendHistory(target, jx.M{
		"action":               action,
		"by":                   jx.GetOr(c.User, "login", ""),
		"at":                   jx.NowISO(),
		"amount":               target["approved_amount"],
		"comment":              comment,
		"github_budget_status": jx.Get(applied, "status"),
		"github_budget_error":  jx.Get(applied, "error"),
	})
	SaveBudgetRequests(requests)
	BudgetRequestsMu.Unlock()

	if len(githubResult) > 0 && githubResult["status"] == "failed" {
		return jx.M{
			"ok": true, "request": target,
			"warning": "Approved in OctoFinance, but the GitHub budget could not be created: " + brPyStr(githubResult["error"]),
		}
	}
	if len(ccResult) > 0 && (ccResult["status"] == "failed" || ccResult["status"] == "partial") {
		return jx.M{
			"ok": true, "request": target,
			"warning": "Approved, but the cost center membership change did not fully apply: " + brPyStr(ccResult["error"]),
		}
	}
	return jx.M{"ok": true, "request": target}
}

func brAmount(c *Ctx) any {
	p, bad := brParseBody(c, brReviewFields)
	if bad != nil {
		return bad
	}
	if r := brAdminOnly(c); r != nil {
		return r
	}
	requestID := jx.Str(p["request_id"])
	comment := strings.TrimSpace(jx.Str(p["comment"]))
	approved, ok := p["approved_amount"].(float64)
	if !ok || approved < 0 {
		return jx.M{"error": "A non-negative approved_amount is required"}
	}
	target := brFind(LoadBudgetRequests(), requestID)
	if target == nil {
		return brNotFound()
	}
	if jx.GetOr(target, "request_type", brTypeBudget) != brTypeBudget {
		return jx.M{"error": "Only budget requests have an amount"}
	}
	amount := jx.Round(approved, 2)
	var githubResult jx.M
	if p["apply_to_github"].(bool) {
		githubResult = ProvisionUserBudget(c.R.Context(), jx.Str(jx.GetOr(target, "user_login", "")), amount,
			jx.Str(jx.GetOr(target, "org", "")), p["prevent_further_usage"].(bool), false)
	} else {
		githubResult = jx.M{"status": "skipped", "reason": "apply_to_github=false", "synced_at": jx.NowISO()}
	}

	BudgetRequestsMu.Lock()
	requests := LoadBudgetRequests()
	target = brFind(requests, requestID)
	if target == nil {
		BudgetRequestsMu.Unlock()
		return brNotFound()
	}
	target["approved_amount"] = amount
	target["status"] = brStatusApproved
	target["github_budget"] = githubResult
	target["reviewed_by"] = jx.GetOr(c.User, "login", "")
	target["reviewed_at"] = jx.NowISO()
	target["updated_at"] = jx.NowISO()
	if comment != "" {
		target["review_comment"] = comment
	}
	brAppendHistory(target, jx.M{
		"action":               "amount_updated",
		"by":                   jx.GetOr(c.User, "login", ""),
		"at":                   jx.NowISO(),
		"amount":               amount,
		"comment":              comment,
		"github_budget_status": githubResult["status"],
		"github_budget_error":  githubResult["error"],
	})
	SaveBudgetRequests(requests)
	BudgetRequestsMu.Unlock()

	if githubResult["status"] == "failed" {
		return jx.M{
			"ok": true, "request": target,
			"warning": "Amount updated, but the GitHub budget could not be updated: " + brPyStr(githubResult["error"]),
		}
	}
	return jx.M{"ok": true, "request": target}
}

func brResync(c *Ctx) any {
	p, bad := brParseBody(c, brReviewFields)
	if bad != nil {
		return bad
	}
	if r := brAdminOnly(c); r != nil {
		return r
	}
	requestID := jx.Str(p["request_id"])
	target := brFind(LoadBudgetRequests(), requestID)
	if target == nil {
		return brNotFound()
	}
	if target["status"] != brStatusApproved {
		return jx.M{"error": "Only approved requests can be synced to GitHub"}
	}
	isCC := jx.GetOr(target, "request_type", brTypeBudget) == brTypeCostCenter
	amount := jx.Float(target["approved_amount"])
	var result jx.M
	if isCC {
		result = ApplyCostCenterMembershipChange(c.R.Context(), jx.Str(jx.GetOr(target, "user_login", "")),
			jx.Str(target["cost_center_id"]))
	} else {
		result = ProvisionUserBudget(c.R.Context(), jx.Str(jx.GetOr(target, "user_login", "")), amount,
			jx.Str(jx.GetOr(target, "org", "")), p["prevent_further_usage"].(bool), false)
	}

	BudgetRequestsMu.Lock()
	requests := LoadBudgetRequests()
	target = brFind(requests, requestID)
	if target == nil {
		BudgetRequestsMu.Unlock()
		return brNotFound()
	}
	var histAmount any = amount
	if isCC {
		target["cost_center_result"] = result
		histAmount = nil
	} else {
		target["github_budget"] = result
	}
	target["updated_at"] = jx.NowISO()
	brAppendHistory(target, jx.M{
		"action":               "github_resync",
		"by":                   jx.GetOr(c.User, "login", ""),
		"at":                   jx.NowISO(),
		"amount":               histAmount,
		"github_budget_status": result["status"],
		"github_budget_error":  result["error"],
	})
	SaveBudgetRequests(requests)
	BudgetRequestsMu.Unlock()

	return jx.M{"ok": true, "request": target, "github_budget": result}
}

func brAudit(c *Ctx) any {
	limit := 200
	if c.HasQuery("limit") {
		raw := c.Query("limit")
		n, err := strconv.Atoi(strings.TrimSpace(raw))
		if err != nil {
			return JSONStatus(422, jx.M{"detail": jx.L{jx.M{
				"type": "int_parsing", "loc": jx.L{"query", "limit"},
				"msg": "Input should be a valid integer, unable to parse string as an integer", "input": raw,
			}}})
		}
		limit = n
	}
	if r := brAdminOnly(c); r != nil {
		return r
	}
	entries := []jx.M{}
	for _, req := range LoadBudgetRequests() {
		for _, ev := range jx.GetMaps(req, "history") {
			entries = append(entries, jx.M{
				"request_id":           jx.GetOr(req, "id", ""),
				"request_type":         jx.GetOr(req, "request_type", brTypeBudget),
				"user_login":           jx.GetOr(req, "user_login", ""),
				"avatar_url":           jx.GetOr(req, "avatar_url", ""),
				"requested_amount":     req["requested_amount"],
				"org":                  jx.GetOr(req, "org", ""),
				"cost_center_plan":     req["cost_center_plan"],
				"reason":               jx.GetOr(req, "reason", ""),
				"action":               jx.GetOr(ev, "action", ""),
				"by":                   jx.GetOr(ev, "by", ""),
				"at":                   jx.GetOr(ev, "at", ""),
				"amount":               ev["amount"],
				"comment":              jx.GetOr(ev, "comment", ""),
				"github_budget_status": ev["github_budget_status"],
				"github_budget_error":  ev["github_budget_error"],
			})
		}
	}
	sort.SliceStable(entries, func(i, j int) bool {
		return jx.Str(entries[i]["at"]) > jx.Str(entries[j]["at"])
	})
	n := limit
	if n < 1 {
		n = 1
	}
	total := len(entries)
	if n < total {
		entries = entries[:n]
	}
	return jx.M{"entries": entries, "total": total}
}

func brDelete(c *Ctx) any {
	requestID := c.Path("request_id")
	BudgetRequestsMu.Lock()
	defer BudgetRequestsMu.Unlock()
	requests := LoadBudgetRequests()
	target := brFind(requests, requestID)
	if target == nil {
		return brNotFound()
	}
	isOwner := strings.EqualFold(jx.Str(jx.GetOr(target, "user_login", "")), jx.Str(jx.GetOr(c.User, "login", "")))
	if !c.IsAdmin() {
		if !isOwner {
			return JSONStatus(403, jx.M{"error": "Not allowed"})
		}
		if target["status"] != brStatusPending {
			return JSONStatus(400, jx.M{"error": "Only pending requests can be withdrawn"})
		}
	}
	kept := []jx.M{}
	for _, r := range requests {
		if v, ok := r["id"].(string); ok && v == requestID {
			continue
		}
		kept = append(kept, r)
	}
	SaveBudgetRequests(kept)
	return jx.M{"ok": true, "deleted": requestID}
}
