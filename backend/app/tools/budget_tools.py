"""
GitHub Copilot Budget management tools for the AI engine.
Uses the GitHub Billing Budgets REST API (version 2026-03-10).
Supports UBB (Usage-Based Billing) era AI credits budget management.

Budget types:
- Universal user-level budget: Default personal limit for all Copilot users
- Individual user-level budget: Personal limit for specific users (overrides Universal)
- Enterprise budget: Controls overage spending after shared pool exhaustion
- Cost center budget: Controls overage spending per cost center

All budget operations require PAT with manage_billing:copilot scope.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from copilot import define_tool

if TYPE_CHECKING:
    from ..services.api_manager import APIManager
    from ..services.data_collector import DataCollector


# ---------------------------------------------------------------------------
# Pydantic param models
# ---------------------------------------------------------------------------

class GetBudgetsParams(BaseModel):
    entity_type: str = Field(
        description="Entity type: 'enterprise' or 'organization'"
    )
    entity_name: str = Field(
        description="Enterprise slug or organization name"
    )
    scope: str = Field(
        default="",
        description=(
            "Filter by budget scope (optional):\n"
            "- 'multi_user_customer': Universal user-level budget\n"
            "- 'user': Individual user-level budgets\n"
            "- 'enterprise': Enterprise budget\n"
            "- 'cost_center': Cost center budgets\n"
            "- 'organization': Organization budgets\n"
            "- Leave empty for all budgets"
        ),
    )


class GetBudgetDetailParams(BaseModel):
    entity_type: str = Field(
        description="Entity type: 'enterprise' or 'organization'"
    )
    entity_name: str = Field(
        description="Enterprise slug or organization name"
    )
    budget_id: str = Field(
        description="Budget ID to retrieve"
    )


class CreateUserBudgetParams(BaseModel):
    entity_type: str = Field(
        description="Entity type: 'enterprise' or 'organization'"
    )
    entity_name: str = Field(
        description="Enterprise slug or organization name"
    )
    budget_scope: str = Field(
        description=(
            "Budget scope:\n"
            "- 'multi_user_customer': Universal budget (applies to all users)\n"
            "- 'user': Individual budget (specific user override)"
        )
    )
    budget_amount: float = Field(
        description="Budget amount in USD per billing cycle",
        gt=0
    )
    username: str = Field(
        default="",
        description="GitHub username (required for 'user' scope, empty for 'multi_user_customer')"
    )
    prevent_further_usage: bool = Field(
        default=True,
        description="Block usage when limit is reached (hard limit)"
    )
    enable_alerts: bool = Field(
        default=False,
        description="Enable budget threshold alerts"
    )


class UpdateBudgetParams(BaseModel):
    entity_type: str = Field(
        description="Entity type: 'enterprise' or 'organization'"
    )
    entity_name: str = Field(
        description="Enterprise slug or organization name"
    )
    budget_id: str = Field(
        description="Budget ID to update"
    )
    budget_amount: float | None = Field(
        default=None,
        description="New budget amount in USD (optional)",
        gt=0
    )
    prevent_further_usage: bool | None = Field(
        default=None,
        description="Block usage when limit is reached (optional)"
    )


class DeleteBudgetParams(BaseModel):
    entity_type: str = Field(
        description="Entity type: 'enterprise' or 'organization'"
    )
    entity_name: str = Field(
        description="Enterprise slug or organization name"
    )
    budget_id: str = Field(
        description="Budget ID to delete"
    )


class BatchCreateUserBudgetsParams(BaseModel):
    entity_type: str = Field(
        description="Entity type: 'enterprise' or 'organization'"
    )
    entity_name: str = Field(
        description="Enterprise slug or organization name"
    )
    usernames: list[str] = Field(
        description="List of GitHub usernames to create budgets for"
    )
    budget_amount: float = Field(
        description="Budget amount in USD per billing cycle for each user",
        gt=0
    )
    prevent_further_usage: bool = Field(
        default=True,
        description="Block usage when limit is reached"
    )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_budget_tools(
    api_manager: APIManager | None = None,
    collector: DataCollector | None = None,
) -> list:
    """Create budget management tools bound to the given APIManager and DataCollector."""

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_api(entity_type: str, entity_name: str):
        """Get API client for the entity."""
        import logging
        logger = logging.getLogger(__name__)

        if api_manager is None:
            logger.error("api_manager is None")
            return None

        if entity_type == "organization":
            api = api_manager.get_api_for_org(entity_name)
            logger.info(f"get_api_for_org('{entity_name}') returned: {api is not None}")
            return api
        elif entity_type == "enterprise":
            # 先检查是否有这个 enterprise
            enterprises = api_manager.get_all_enterprises()
            logger.info(f"Available enterprises: {[e['slug'] for e in enterprises]}")

            api = api_manager.get_api_for_enterprise(entity_name)
            logger.info(f"get_api_for_enterprise('{entity_name}') returned: {api is not None}")
            return api
        return None

    # ------------------------------------------------------------------
    # Tool definitions
    # ------------------------------------------------------------------

    @define_tool(
        description=(
            "Get all budgets for an enterprise or organization. "
            "Filter by scope to get specific budget types (Universal user-level, Individual user-level, Enterprise, Cost center). "
            "Returns list of budgets with amounts, consumed amounts, and blocking settings."
        )
    )
    async def get_all_budgets(params: GetBudgetsParams) -> str:
        import logging
        logger = logging.getLogger(__name__)

        logger.info(f"get_all_budgets called with entity_type={params.entity_type}, entity_name={params.entity_name}, scope={params.scope}")

        api = _get_api(params.entity_type, params.entity_name)
        if not api:
            error_msg = {
                "error": f"No API client available for {params.entity_type} '{params.entity_name}'. "
                        f"Ensure PAT is configured with manage_billing:copilot scope."
            }
            logger.error(f"get_all_budgets error: {error_msg}")
            return json.dumps(error_msg)

        logger.info(f"API client obtained successfully")

        result = await api.get_budgets(
            entity_type=params.entity_type,
            entity_name=params.entity_name,
            scope=params.scope if params.scope else None,
        )

        logger.info(f"API call result type: {type(result)}, result: {result if result else 'None'}")

        if not result:
            error_msg = {
                "error": f"No budget data for {params.entity_type} '{params.entity_name}'. "
                        f"Ensure PAT has manage_billing:copilot scope."
            }
            logger.error(f"get_all_budgets: API returned None")
            return json.dumps(error_msg)

        if "error" in result:
            logger.error(f"get_all_budgets: API returned error: {result}")
            return json.dumps(result)

        logger.info(f"get_all_budgets: Success! Found {result.get('total_count', 0)} budgets")
        return json.dumps(result, default=str)

    @define_tool(
        description=(
            "Get detailed information for a specific budget by ID. "
            "Shows budget amount, consumed amount, scope, entity name, and alert settings."
        )
    )
    async def get_budget_detail(params: GetBudgetDetailParams) -> str:
        api = _get_api(params.entity_type, params.entity_name)
        if not api:
            return json.dumps({
                "error": f"No API client available for {params.entity_type} '{params.entity_name}'."
            })

        result = await api.get_budget(
            entity_type=params.entity_type,
            entity_name=params.entity_name,
            budget_id=params.budget_id,
        )

        if not result:
            return json.dumps({
                "error": f"Budget '{params.budget_id}' not found for {params.entity_type} '{params.entity_name}'."
            })

        if "error" in result:
            return json.dumps(result)

        return json.dumps(result, default=str)

    @define_tool(
        description=(
            "Create a user-level budget for Copilot AI credits. "
            "Use 'multi_user_customer' scope for Universal budget (applies to all users) "
            "or 'user' scope for Individual budget (specific user override). "
            "Universal budget is the default personal limit for all Copilot users. "
            "Individual budget overrides Universal budget for specific users (e.g., high-frequency users, core engineers). "
            "Each enterprise/org can only have one Universal budget. Returns 409 if already exists."
        )
    )
    async def create_user_budget(params: CreateUserBudgetParams) -> str:
        api = _get_api(params.entity_type, params.entity_name)
        if not api:
            return json.dumps({
                "error": f"No API client available for {params.entity_type} '{params.entity_name}'."
            })

        if params.budget_scope == "user" and not params.username:
            return json.dumps({
                "error": "username is required for Individual user budget (scope='user')."
            })

        budget_data = {
            "budget_type": "BundlePricing",
            "budget_product_sku": "ai_credits",
            "budget_scope": params.budget_scope,
            "budget_entity_name": params.username if params.budget_scope == "user" else params.entity_name,
            "budget_amount": params.budget_amount,
            "prevent_further_usage": params.prevent_further_usage,
            "budget_alerting": {
                "will_alert": params.enable_alerts,
                "alert_recipients": ["billing-admin"] if params.enable_alerts else [],
            },
        }

        if params.budget_scope == "user":
            budget_data["user"] = params.username
            budget_data["consumed_amount"] = 0

        if params.budget_scope == "multi_user_customer" and params.enable_alerts:
            budget_data["budget_thresholds"] = {"75": 0, "90": 0, "100": 0}

        result = await api.create_budget(
            entity_type=params.entity_type,
            entity_name=params.entity_name,
            budget_data=budget_data,
        )

        if result and "error" in result:
            if result.get("status_code") == 409:
                return json.dumps({
                    "error": "Budget already exists. Use update_budget to modify or delete first.",
                    "hint": "Each enterprise/org can only have one Universal budget. For user-specific budgets, check if budget already exists for this user.",
                    "result": result
                })
            return json.dumps(result)

        return json.dumps(result, default=str)

    @define_tool(
        description=(
            "Update an existing budget. Can modify budget amount and usage blocking setting. "
            "Cannot change budget_scope - delete and recreate if scope needs to change. "
            "Commonly used to: increase limits for high-frequency users, adjust Universal budget based on usage patterns, "
            "enable/disable hard blocking when budget is reached."
        )
    )
    async def update_budget(params: UpdateBudgetParams) -> str:
        api = _get_api(params.entity_type, params.entity_name)
        if not api:
            return json.dumps({
                "error": f"No API client available for {params.entity_type} '{params.entity_name}'."
            })

        budget_data = {}
        if params.budget_amount is not None:
            budget_data["budget_amount"] = params.budget_amount
        if params.prevent_further_usage is not None:
            budget_data["prevent_further_usage"] = params.prevent_further_usage

        if not budget_data:
            return json.dumps({
                "error": "No fields to update. Provide budget_amount or prevent_further_usage."
            })

        result = await api.update_budget(
            entity_type=params.entity_type,
            entity_name=params.entity_name,
            budget_id=params.budget_id,
            budget_data=budget_data,
        )

        if not result or "error" in result:
            return json.dumps(result or {"error": "Failed to update budget."})

        return json.dumps(result, default=str)

    @define_tool(
        description=(
            "Delete a budget. Destructive operation - use after admin confirmation. "
            "IMPORTANT: Requires ENTERPRISE ADMIN role (not just billing manager). "
            "WARNING: Ensure there is another budget as fallback before deleting. "
            "Deleting Universal user-level budget removes the default limit for all users. "
            "Deleting Individual user-level budget reverts user to Universal budget. "
            "Only delete after verifying impact on budget governance."
        )
    )
    async def delete_budget(params: DeleteBudgetParams) -> str:
        import logging
        logger = logging.getLogger(__name__)

        logger.info(f"delete_budget called: entity_type={params.entity_type}, entity_name={params.entity_name}, budget_id={params.budget_id}")

        api = _get_api(params.entity_type, params.entity_name)
        if not api:
            error_msg = {
                "error": f"No API client available for {params.entity_type} '{params.entity_name}'."
            }
            logger.error(f"delete_budget: {error_msg}")
            return json.dumps(error_msg)

        result = await api.delete_budget(
            entity_type=params.entity_type,
            entity_name=params.entity_name,
            budget_id=params.budget_id,
        )

        logger.info(f"delete_budget API result: {result}")

        # Check for errors and provide detailed information
        if "error" in result:
            status_code = result.get("status_code")
            error_detail = {
                "success": False,
                "error": result.get("error"),
                "status_code": status_code,
                "details": result.get("response", {}),
                "budget_id": params.budget_id,
            }

            # Provide specific hints based on status code
            if status_code is None:
                error_detail["hint"] = (
                    "The request did not reach GitHub or no HTTP response was received. "
                    "Check network/proxy/VPN connectivity from the backend process, then retry."
                )
            elif status_code == 403:
                error_detail["hint"] = (
                    "❌ 403 Forbidden - Delete budget requires ENTERPRISE ADMIN role.\n"
                    "The authenticated user must be an Enterprise Admin (not just Billing Manager).\n"
                    "Please verify:\n"
                    "1. Your account has Enterprise Admin role in the satomic enterprise\n"
                    "2. PAT has 'admin:enterprise' scope (manage_billing:copilot is not enough)\n"
                    "3. You're using the correct enterprise slug"
                )
            elif status_code == 404:
                error_detail["hint"] = (
                    "❌ 404 Not Found - Budget doesn't exist or already deleted.\n"
                    "Check the budget ID is correct."
                )
            elif status_code == 422:
                error_detail["hint"] = (
                    "❌ 422 Unprocessable Entity - Cannot delete due to business rules.\n"
                    "Possible reasons:\n"
                    "- This is the last remaining budget (need at least one)\n"
                    "- Budget has active dependencies\n"
                    "- Budget is currently in use"
                )
            else:
                error_detail["hint"] = (
                    "Common issues:\n"
                    "- 403 Forbidden: Requires ENTERPRISE ADMIN role\n"
                    "- 404 Not Found: Budget ID doesn't exist\n"
                    "- 422 Unprocessable: Cannot delete due to business rules"
                )

            logger.error(f"delete_budget failed: {error_detail}")
            return json.dumps(error_detail, default=str)

        logger.info(f"delete_budget succeeded for budget_id={params.budget_id}")
        return json.dumps(result, default=str)

    @define_tool(
        description=(
            "Batch create Individual user-level budgets for multiple users. "
            "Useful for onboarding new team members, setting limits for specific project teams, "
            "or applying uniform budgets to high-frequency user groups. "
            "Skips users who already have Individual budgets (409 conflict). "
            "Returns summary with created, skipped, and failed users."
        )
    )
    async def batch_create_user_budgets(params: BatchCreateUserBudgetsParams) -> str:
        api = _get_api(params.entity_type, params.entity_name)
        if not api:
            return json.dumps({
                "error": f"No API client available for {params.entity_type} '{params.entity_name}'."
            })

        # First, get existing user budgets to avoid duplicates
        existing_result = await api.get_budgets(
            entity_type=params.entity_type,
            entity_name=params.entity_name,
            scope="user",
        )

        existing_users = set()
        if existing_result and "budgets" in existing_result:
            for budget in existing_result["budgets"]:
                if "user" in budget:
                    existing_users.add(budget["user"])

        results = {
            "created": [],
            "skipped": [],
            "failed": [],
        }

        for username in params.usernames:
            if username in existing_users:
                results["skipped"].append({
                    "user": username,
                    "reason": "Budget already exists"
                })
                continue

            budget_data = {
                "budget_type": "BundlePricing",
                "budget_product_sku": "ai_credits",
                "budget_scope": "user",
                "budget_entity_name": username,
                "user": username,
                "budget_amount": params.budget_amount,
                "prevent_further_usage": params.prevent_further_usage,
                "consumed_amount": 0,
                "budget_alerting": {
                    "will_alert": False,
                    "alert_recipients": [],
                },
            }

            result = await api.create_budget(
                entity_type=params.entity_type,
                entity_name=params.entity_name,
                budget_data=budget_data,
            )

            if result and "error" not in result:
                budget_id = result.get("budget", {}).get("id") if isinstance(result, dict) else None
                results["created"].append({
                    "user": username,
                    "budget_id": budget_id,
                    "amount": params.budget_amount
                })
            else:
                error_msg = result.get("error", "Unknown error") if result else "No response"
                status_code = result.get("status_code") if result else None

                if status_code == 409:
                    results["skipped"].append({
                        "user": username,
                        "reason": "Budget already exists (conflict)"
                    })
                else:
                    results["failed"].append({
                        "user": username,
                        "error": error_msg,
                        "status_code": status_code
                    })

        summary = {
            "total_requested": len(params.usernames),
            "created_count": len(results["created"]),
            "skipped_count": len(results["skipped"]),
            "failed_count": len(results["failed"]),
            "results": results,
        }

        return json.dumps(summary, default=str)

    return [
        get_all_budgets,
        get_budget_detail,
        create_user_budget,
        update_budget,
        delete_budget,
        batch_create_user_budgets,
    ]
