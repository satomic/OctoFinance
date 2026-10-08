package app

// Port of backend/app/tools/budget_tools.py: GitHub Copilot budget management
// tools (Billing Budgets REST API, version 2026-03-10). The Python module logs
// through the "app.tools.budget_tools" logger, which is attached to the
// api_requests log; here that is ghapi.Logger.

import (
	"fmt"
	"strings"

	copilot "github.com/github/copilot-sdk/go"

	"github.com/satomic/octofinance/backend-go/internal/ghapi"
	"github.com/satomic/octofinance/backend-go/internal/jx"
)

func init() { registerTools(budgetTools) }

const (
	budgetToolEntityTypeDesc = "Entity type: 'enterprise' or 'organization'"
	budgetToolEntityNameDesc = "Enterprise slug or organization name"
)

// budgetToolEntityParams are the entity_type/entity_name params shared by most tools.
func budgetToolEntityParams() []P {
	return []P{
		{Name: "entity_type", Type: "string", Required: true, Desc: budgetToolEntityTypeDesc},
		{Name: "entity_name", Type: "string", Required: true, Desc: budgetToolEntityNameDesc},
	}
}

// budgetToolGt0 mirrors Pydantic's Field(gt=0): it adds exclusiveMinimum to
// the JSON schema of the named numeric parameter.
func budgetToolGt0(t copilot.Tool, name string) copilot.Tool {
	if schema := jx.Map(t.Parameters); schema != nil {
		if prop := jx.Map(jx.GetMap(schema, "properties")[name]); prop != nil {
			prop["exclusiveMinimum"] = 0
		}
	}
	return t
}

// budgetToolRequireGt0 mirrors the Pydantic gt=0 validation: a supplied
// amount that is not > 0 fails the tool call. defineTool's handler turns the
// panic into the generic failure result (detail kept in Error), like the
// Python SDK does for a pydantic ValidationError.
func budgetToolRequireGt0(tool string, v *float64) {
	if v != nil && !(*v > 0) {
		panic(fmt.Sprintf("Invalid arguments for %s: budget_amount: Input should be greater than 0", tool))
	}
}

// budgetToolStrings returns a list[str] argument, failing the call like
// Pydantic when the value is not an array of strings (the shared Args.Strings
// would accept a bare string).
func budgetToolStrings(tool string, a Args, name string) []string {
	v := a.Raw(name)
	if v == nil {
		return []string{}
	}
	l, ok := v.([]any)
	if !ok {
		panic(fmt.Sprintf("Invalid arguments for %s: %s: Input should be a valid list", tool, name))
	}
	out := make([]string, 0, len(l))
	for _, e := range l {
		s, ok := e.(string)
		if !ok {
			panic(fmt.Sprintf("Invalid arguments for %s: %s: Input should be a valid string", tool, name))
		}
		out = append(out, s)
	}
	return out
}

func budgetTools(tc *ToolCtx) []copilot.Tool {
	ctx := tc.Context()
	collector := tc.Collector
	log := ghapi.Logger

	getAPI := func(entityType, entityName string) *ghapi.Client {
		switch entityType {
		case "organization":
			api := APIs.APIForOrg(entityName)
			log.Info(fmt.Sprintf("get_api_for_org('%s') returned: %s", entityName, budgetToolPyBool(api != nil)))
			return api
		case "enterprise":
			slugs := []string{}
			for _, e := range APIs.AllEnterprises() {
				slugs = append(slugs, jx.Str(e["slug"]))
			}
			log.Info(fmt.Sprintf("Available enterprises: %s", budgetToolPyStrList(slugs)))
			api := APIs.APIForEnterprise(entityName)
			log.Info(fmt.Sprintf("get_api_for_enterprise('%s') returned: %s", entityName, budgetToolPyBool(api != nil)))
			return api
		}
		return nil
	}

	resolveEnterprise := func(requested string) string {
		if requested != "" {
			return requested
		}
		enterprises := APIs.AllEnterprises()
		if len(enterprises) == 0 && collector != nil {
			enterprises = jx.Maps(collector.LoadLatest("enterprise", "all"))
		}
		if len(enterprises) == 1 {
			return jx.Str(enterprises[0]["slug"])
		}
		return ""
	}

	findCostCenter := func(enterprise, wanted string) jx.M {
		if collector == nil {
			return nil
		}
		data := collector.LoadLatestMap("cost_centers", enterprise)
		if data == nil {
			return nil
		}
		target := strings.ToLower(strings.TrimSpace(wanted))
		for _, cc := range jx.Maps(jx.GetOr(data, "cost_centers", jx.L{})) {
			if strings.ToLower(jx.Str(jx.GetOr(cc, "id", ""))) == target || strings.ToLower(jx.Str(cc["name"])) == target {
				return cc
			}
		}
		return nil
	}

	noAPI := func(entityType, entityName string) string {
		return jx.Dumps(jx.M{"error": fmt.Sprintf("No API client available for %s '%s'.", entityType, entityName)})
	}

	tools := []copilot.Tool{
		defineTool("get_all_budgets",
			"Get all budgets for an enterprise or organization. "+
				"Filter by scope to get specific budget types (Universal user-level, Individual user-level, Enterprise, Cost center). "+
				"Returns list of budgets with amounts, consumed amounts, and blocking settings.",
			append(budgetToolEntityParams(),
				P{Name: "scope", Type: "string", Default: "", Desc: "Filter by budget scope (optional):\n" +
					"- 'multi_user_customer': Universal user-level budget\n" +
					"- 'user': Individual user-level budgets\n" +
					"- 'enterprise': Enterprise budget\n" +
					"- 'cost_center': Cost center budgets\n" +
					"- 'organization': Organization budgets\n" +
					"- Leave empty for all budgets"},
			),
			func(a Args) any {
				et, en, scope := a.Str("entity_type"), a.Str("entity_name"), a.Str("scope")
				log.Info(fmt.Sprintf("get_all_budgets called with entity_type=%s, entity_name=%s, scope=%s", et, en, scope))
				api := getAPI(et, en)
				if api == nil {
					msg := jx.M{"error": fmt.Sprintf("No API client available for %s '%s'. "+
						"Ensure PAT is configured with manage_billing:copilot scope.", et, en)}
					log.Error(fmt.Sprintf("get_all_budgets error: %v", msg))
					return jx.Dumps(msg)
				}
				log.Info("API client obtained successfully")
				result := api.GetBudgets(ctx, et, en, scope, 0, 0)
				if len(result) == 0 {
					log.Error("get_all_budgets: API returned None")
					return jx.Dumps(jx.M{"error": fmt.Sprintf("No budget data for %s '%s'. "+
						"Ensure PAT has manage_billing:copilot scope.", et, en)})
				}
				if jx.Has(result, "error") {
					log.Error(fmt.Sprintf("get_all_budgets: API returned error: %v", result))
					return jx.Dumps(result)
				}
				log.Info(fmt.Sprintf("get_all_budgets: Success! Found %s budgets", jx.Str(jx.GetOr(result, "total_count", 0))))
				return jx.Dumps(result)
			}),

		defineTool("get_budget_detail",
			"Get detailed information for a specific budget by ID. "+
				"Shows budget amount, consumed amount, scope, entity name, and alert settings.",
			append(budgetToolEntityParams(),
				P{Name: "budget_id", Type: "string", Required: true, Desc: "Budget ID to retrieve"},
			),
			func(a Args) any {
				et, en, id := a.Str("entity_type"), a.Str("entity_name"), a.Str("budget_id")
				api := getAPI(et, en)
				if api == nil {
					return noAPI(et, en)
				}
				result := api.GetBudget(ctx, et, en, id)
				if len(result) == 0 {
					return jx.Dumps(jx.M{"error": fmt.Sprintf("Budget '%s' not found for %s '%s'.", id, et, en)})
				}
				return jx.Dumps(result)
			}),

		budgetToolGt0(defineTool("create_user_budget",
			"Create a user-level budget for Copilot AI credits. "+
				"Use 'multi_user_customer' scope for Universal budget (applies to all users) "+
				"or 'user' scope for Individual budget (specific user override). "+
				"Universal budget is the default personal limit for all Copilot users. "+
				"Individual budget overrides Universal budget for specific users (e.g., high-frequency users, core engineers). "+
				"Each enterprise/org can only have one Universal budget. Returns 409 if already exists. "+
				"For cost center budgets use create_cost_center_budget instead.",
			append(budgetToolEntityParams(),
				P{Name: "budget_scope", Type: "string", Required: true, Desc: "Budget scope:\n" +
					"- 'multi_user_customer': Universal budget (applies to all users)\n" +
					"- 'user': Individual budget (specific user override)"},
				P{Name: "budget_amount", Type: "number", Required: true, Desc: "Budget amount in USD per billing cycle"},
				P{Name: "username", Type: "string", Default: "", Desc: "GitHub username (required for 'user' scope, empty for 'multi_user_customer')"},
				P{Name: "prevent_further_usage", Type: "boolean", Default: true, Desc: "Block usage when limit is reached (hard limit)"},
				P{Name: "enable_alerts", Type: "boolean", Default: false, Desc: "Enable budget threshold alerts"},
			),
			func(a Args) any {
				amount := a.Float("budget_amount")
				budgetToolRequireGt0("create_user_budget", &amount)
				et, en := a.Str("entity_type"), a.Str("entity_name")
				scope, username := a.Str("budget_scope"), a.Str("username")
				alerts := a.Bool("enable_alerts")
				api := getAPI(et, en)
				if api == nil {
					return noAPI(et, en)
				}
				if scope != "multi_user_customer" && scope != "user" {
					return jx.Dumps(jx.M{"error": fmt.Sprintf("budget_scope '%s' is not supported by this tool. "+
						"Use 'multi_user_customer' or 'user' here, or create_cost_center_budget "+
						"for 'cost_center' / 'multi_user_cost_center' budgets.", scope)})
				}
				if scope == "user" && username == "" {
					return jx.Dumps(jx.M{"error": "username is required for Individual user budget (scope='user')."})
				}
				entityName := en
				if scope == "user" {
					entityName = username
				}
				recipients := jx.L{}
				if alerts {
					recipients = jx.L{"billing-admin"}
				}
				data := jx.M{
					"budget_type":           "BundlePricing",
					"budget_product_sku":    "ai_credits",
					"budget_scope":          scope,
					"budget_entity_name":    entityName,
					"budget_amount":         amount,
					"prevent_further_usage": a.Bool("prevent_further_usage"),
					"budget_alerting": jx.M{
						"will_alert":       alerts,
						"alert_recipients": recipients,
					},
				}
				if scope == "user" {
					data["user"] = username
					data["consumed_amount"] = 0
				}
				if scope == "multi_user_customer" && alerts {
					data["budget_thresholds"] = jx.M{"75": 0, "90": 0, "100": 0}
				}
				result := api.CreateBudget(ctx, et, en, data)
				if len(result) > 0 && jx.Has(result, "error") {
					if code, _ := jx.FloatOK(jx.Get(result, "status_code")); code == 409 {
						return jx.Dumps(jx.M{
							"error":  "Budget already exists. Use update_budget to modify or delete first.",
							"hint":   "Each enterprise/org can only have one Universal budget. For user-specific budgets, check if budget already exists for this user.",
							"result": result,
						})
					}
					return jx.Dumps(result)
				}
				return jx.Dumps(result)
			}), "budget_amount"),

		budgetToolGt0(defineTool("update_budget",
			"Update an existing budget. Can modify budget amount and usage blocking setting. "+
				"Cannot change budget_scope - delete and recreate if scope needs to change. "+
				"Commonly used to: increase limits for high-frequency users, adjust Universal budget based on usage patterns, "+
				"enable/disable hard blocking when budget is reached.",
			append(budgetToolEntityParams(),
				P{Name: "budget_id", Type: "string", Required: true, Desc: "Budget ID to update"},
				P{Name: "budget_amount", Type: "number", Nullable: true, Desc: "New budget amount in USD (optional)"},
				P{Name: "prevent_further_usage", Type: "boolean", Nullable: true, Desc: "Block usage when limit is reached (optional)"},
			),
			func(a Args) any {
				amount := a.FloatPtr("budget_amount")
				budgetToolRequireGt0("update_budget", amount)
				et, en, id := a.Str("entity_type"), a.Str("entity_name"), a.Str("budget_id")
				api := getAPI(et, en)
				if api == nil {
					return noAPI(et, en)
				}
				data := jx.M{}
				if amount != nil {
					data["budget_amount"] = *amount
				}
				if p := a.BoolPtr("prevent_further_usage"); p != nil {
					data["prevent_further_usage"] = *p
				}
				if len(data) == 0 {
					return jx.Dumps(jx.M{"error": "No fields to update. Provide budget_amount or prevent_further_usage."})
				}
				result := api.UpdateBudget(ctx, et, en, id, data)
				if len(result) == 0 {
					return jx.Dumps(jx.M{"error": "Failed to update budget."})
				}
				return jx.Dumps(result)
			}), "budget_amount"),

		defineTool("delete_budget",
			"Delete a budget. Destructive operation - use after admin confirmation. "+
				"IMPORTANT: Requires ENTERPRISE ADMIN role (not just billing manager). "+
				"WARNING: Ensure there is another budget as fallback before deleting. "+
				"Deleting Universal user-level budget removes the default limit for all users. "+
				"Deleting Individual user-level budget reverts user to Universal budget. "+
				"Only delete after verifying impact on budget governance.",
			append(budgetToolEntityParams(),
				P{Name: "budget_id", Type: "string", Required: true, Desc: "Budget ID to delete"},
			),
			func(a Args) any {
				et, en, id := a.Str("entity_type"), a.Str("entity_name"), a.Str("budget_id")
				log.Info(fmt.Sprintf("delete_budget called: entity_type=%s, entity_name=%s, budget_id=%s", et, en, id))
				api := getAPI(et, en)
				if api == nil {
					log.Error(fmt.Sprintf("delete_budget: No API client available for %s '%s'.", et, en))
					return noAPI(et, en)
				}
				result := api.DeleteBudget(ctx, et, en, id)
				log.Info(fmt.Sprintf("delete_budget API result: %v", result))
				if jx.Has(result, "error") {
					status := jx.Get(result, "status_code")
					detail := jx.M{
						"success":     false,
						"error":       jx.Get(result, "error"),
						"status_code": status,
						"details":     jx.GetOr(result, "response", jx.M{}),
						"budget_id":   id,
					}
					code, _ := jx.FloatOK(status)
					switch {
					case status == nil:
						detail["hint"] = "The request did not reach GitHub or no HTTP response was received. " +
							"Check network/proxy/VPN connectivity from the backend process, then retry."
					case code == 403:
						detail["hint"] = "❌ 403 Forbidden - Delete budget requires ENTERPRISE ADMIN role.\n" +
							"The authenticated user must be an Enterprise Admin (not just Billing Manager).\n" +
							"Please verify:\n" +
							"1. Your account has Enterprise Admin role in the satomic enterprise\n" +
							"2. PAT has 'admin:enterprise' scope (manage_billing:copilot is not enough)\n" +
							"3. You're using the correct enterprise slug"
					case code == 404:
						detail["hint"] = "❌ 404 Not Found - Budget doesn't exist or already deleted.\n" +
							"Check the budget ID is correct."
					case code == 422:
						detail["hint"] = "❌ 422 Unprocessable Entity - Cannot delete due to business rules.\n" +
							"Possible reasons:\n" +
							"- This is the last remaining budget (need at least one)\n" +
							"- Budget has active dependencies\n" +
							"- Budget is currently in use"
					default:
						detail["hint"] = "Common issues:\n" +
							"- 403 Forbidden: Requires ENTERPRISE ADMIN role\n" +
							"- 404 Not Found: Budget ID doesn't exist\n" +
							"- 422 Unprocessable: Cannot delete due to business rules"
					}
					log.Error(fmt.Sprintf("delete_budget failed: %v", detail))
					return jx.Dumps(detail)
				}
				log.Info(fmt.Sprintf("delete_budget succeeded for budget_id=%s", id))
				return jx.Dumps(result)
			}),

		budgetToolGt0(defineTool("create_cost_center_budget",
			"Create a cost center budget for Copilot AI credits. "+
				"Use budget_scope='cost_center' for one shared budget covering the whole cost center, "+
				"or 'multi_user_cost_center' to give every member of the cost center the same personal budget "+
				"(that scope requires the cost center to already have at least one user member). "+
				"The cost center can be given by name or ID; it is resolved against the synced cost center data, "+
				"so call sync_data(dataset='cost_centers') first if the cost center was just created. "+
				"Requires a PAT with the manage_billing:copilot scope.",
			[]P{
				{Name: "enterprise", Type: "string", Default: "", Desc: "Enterprise slug. Leave empty to auto-detect when only one enterprise is configured."},
				{Name: "cost_center", Type: "string", Required: true, Desc: "Cost center name or ID to apply the budget to"},
				{Name: "budget_amount", Type: "number", Required: true, Desc: "Budget amount in whole USD per billing cycle"},
				{Name: "budget_scope", Type: "string", Default: "cost_center", Desc: "Budget scope:\n" +
					"- 'cost_center' (default): one shared budget for the whole cost center\n" +
					"- 'multi_user_cost_center': the same per-user budget for every member of the cost center " +
					"(the cost center must already have at least one user member)"},
				{Name: "prevent_further_usage", Type: "boolean", Default: true, Desc: "Block usage when the limit is reached (hard limit)"},
				{Name: "enable_alerts", Type: "boolean", Default: false, Desc: "Enable budget threshold alerts"},
				{Name: "alert_recipients", Type: "array", Items: "string", Desc: "GitHub logins that receive alerts when enable_alerts is true"},
			},
			func(a Args) any {
				amount := a.Float("budget_amount")
				budgetToolRequireGt0("create_cost_center_budget", &amount)
				alertRecipients := budgetToolStrings("create_cost_center_budget", a, "alert_recipients")
				enterprise := resolveEnterprise(a.Str("enterprise"))
				if enterprise == "" {
					return jx.Dumps(jx.M{"error": "Could not determine the enterprise. Pass the enterprise slug explicitly."})
				}
				scope := a.Str("budget_scope")
				if scope != "cost_center" && scope != "multi_user_cost_center" {
					return jx.Dumps(jx.M{"error": "budget_scope must be 'cost_center' or 'multi_user_cost_center'."})
				}
				wanted := a.Str("cost_center")
				cc := findCostCenter(enterprise, wanted)
				if cc == nil {
					return jx.Dumps(jx.M{"error": fmt.Sprintf("Cost center '%s' not found in enterprise '%s'. "+
						"If it was just created, call sync_data(dataset='cost_centers') and retry; "+
						"otherwise use list_cost_centers to see the available cost centers.", wanted, enterprise)})
				}
				api := getAPI("enterprise", enterprise)
				if api == nil {
					return jx.Dumps(jx.M{"error": fmt.Sprintf("No API client available for enterprise '%s'.", enterprise)})
				}
				alerts := a.Bool("enable_alerts")
				recipients := jx.L{}
				if alerts {
					for _, r := range alertRecipients {
						recipients = append(recipients, r)
					}
				}
				// GitHub matches the cost center by ID here, and echoes its name back in the response.
				data := jx.M{
					"budget_type":           "BundlePricing",
					"budget_product_sku":    "ai_credits",
					"budget_scope":          scope,
					"budget_entity_name":    cc["id"],
					"budget_amount":         int(amount),
					"prevent_further_usage": a.Bool("prevent_further_usage"),
					"budget_alerting": jx.M{
						"will_alert":       alerts,
						"alert_recipients": recipients,
					},
				}
				result := api.CreateBudget(ctx, "enterprise", enterprise, data)
				ccInfo := jx.M{"id": cc["id"], "name": jx.GetOr(cc, "name", "")}
				if len(result) > 0 && jx.Has(result, "error") {
					if code, _ := jx.FloatOK(jx.Get(result, "status_code")); code == 409 {
						return jx.Dumps(jx.M{
							"error":  "A budget with this scope already exists for the cost center.",
							"hint":   "Use update_budget to change the amount, or delete_budget first.",
							"result": result,
						})
					}
				}
				out := jx.Copy(result)
				if out == nil {
					out = jx.M{}
				}
				out["cost_center"] = ccInfo
				return jx.Dumps(out)
			}), "budget_amount"),

		budgetToolGt0(defineTool("batch_create_user_budgets",
			"Batch create Individual user-level budgets for multiple users. "+
				"Useful for onboarding new team members, setting limits for specific project teams, "+
				"or applying uniform budgets to high-frequency user groups. "+
				"Skips users who already have Individual budgets (409 conflict). "+
				"Returns summary with created, skipped, and failed users.",
			append(budgetToolEntityParams(),
				P{Name: "usernames", Type: "array", Items: "string", Required: true, Desc: "List of GitHub usernames to create budgets for"},
				P{Name: "budget_amount", Type: "number", Required: true, Desc: "Budget amount in USD per billing cycle for each user"},
				P{Name: "prevent_further_usage", Type: "boolean", Default: true, Desc: "Block usage when limit is reached"},
			),
			func(a Args) any {
				amount := a.Float("budget_amount")
				budgetToolRequireGt0("batch_create_user_budgets", &amount)
				et, en := a.Str("entity_type"), a.Str("entity_name")
				usernames := budgetToolStrings("batch_create_user_budgets", a, "usernames")
				api := getAPI(et, en)
				if api == nil {
					return noAPI(et, en)
				}
				// First, get existing user budgets to avoid duplicates
				existing := api.GetBudgets(ctx, et, en, "user", 0, 0)
				existingUsers := map[string]bool{}
				if len(existing) > 0 && jx.Has(existing, "budgets") {
					for _, b := range jx.GetMaps(existing, "budgets") {
						if u, ok := b["user"].(string); ok {
							existingUsers[u] = true
						}
					}
				}
				created, skipped, failed := jx.L{}, jx.L{}, jx.L{}
				for _, username := range usernames {
					if existingUsers[username] {
						skipped = append(skipped, jx.M{"user": username, "reason": "Budget already exists"})
						continue
					}
					data := jx.M{
						"budget_type":           "BundlePricing",
						"budget_product_sku":    "ai_credits",
						"budget_scope":          "user",
						"budget_entity_name":    username,
						"user":                  username,
						"budget_amount":         amount,
						"prevent_further_usage": a.Bool("prevent_further_usage"),
						"consumed_amount":       0,
						"budget_alerting": jx.M{
							"will_alert":       false,
							"alert_recipients": jx.L{},
						},
					}
					result := api.CreateBudget(ctx, et, en, data)
					if len(result) > 0 && !jx.Has(result, "error") {
						created = append(created, jx.M{
							"user":      username,
							"budget_id": jx.Get(jx.GetMap(result, "budget"), "id"),
							"amount":    amount,
						})
						continue
					}
					var errMsg any = "No response"
					var status any
					if len(result) > 0 {
						errMsg = jx.GetOr(result, "error", "Unknown error")
						status = jx.Get(result, "status_code")
					}
					if code, _ := jx.FloatOK(status); status != nil && code == 409 {
						skipped = append(skipped, jx.M{"user": username, "reason": "Budget already exists (conflict)"})
					} else {
						failed = append(failed, jx.M{"user": username, "error": errMsg, "status_code": status})
					}
				}
				return jx.Dumps(jx.M{
					"total_requested": len(usernames),
					"created_count":   len(created),
					"skipped_count":   len(skipped),
					"failed_count":    len(failed),
					"results": jx.M{
						"created": created,
						"skipped": skipped,
						"failed":  failed,
					},
				})
			}), "budget_amount"),
	}
	return tools
}

func budgetToolPyBool(b bool) string {
	if b {
		return "True"
	}
	return "False"
}

// budgetToolPyStrList renders a list of strings like Python's repr(list[str]).
func budgetToolPyStrList(items []string) string {
	parts := make([]string, len(items))
	for i, s := range items {
		parts[i] = budgetToolPyRepr(s)
	}
	return "[" + strings.Join(parts, ", ") + "]"
}

// budgetToolPyRepr renders a string like Python's repr(str) (common cases).
func budgetToolPyRepr(s string) string {
	quote := "'"
	if strings.Contains(s, "'") && !strings.Contains(s, "\"") {
		quote = "\""
	}
	var b strings.Builder
	b.WriteString(quote)
	for _, r := range s {
		switch {
		case r == '\\':
			b.WriteString(`\\`)
		case string(r) == quote:
			b.WriteString(`\` + quote)
		case r == '\n':
			b.WriteString(`\n`)
		case r == '\r':
			b.WriteString(`\r`)
		case r == '\t':
			b.WriteString(`\t`)
		case r < 0x20 || r == 0x7f:
			fmt.Fprintf(&b, `\x%02x`, r)
		default:
			b.WriteRune(r)
		}
	}
	b.WriteString(quote)
	return b.String()
}
