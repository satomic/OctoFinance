"""
Copilot billing and cost analysis tools for the AI engine.
"""

import json
from pydantic import BaseModel, Field

from copilot import define_tool

from ..services.data_collector import DataCollector


class GetCostOverviewParams(BaseModel):
    org: str = Field(default="", description="Organization name. Leave empty for all orgs.")


class CalculateROIParams(BaseModel):
    org: str = Field(default="", description="Organization name. Leave empty for all orgs.")


def create_billing_tools(collector: DataCollector) -> list:
    """Create billing tools bound to a specific DataCollector instance."""

    @define_tool(description="Get cost overview for Copilot across organizations. Shows total seats, active seats, wasted seats, monthly cost, and estimated waste.")
    def get_cost_overview(params: GetCostOverviewParams) -> str:
        orgs_to_check = [params.org] if params.org else list(collector.load_all_latest("billing").keys())
        overview = []

        for org in orgs_to_check:
            billing = collector.load_latest("billing", org)
            seats_data = collector.load_latest("seats", org)

            if not billing:
                continue

            price = billing.get("_detected_price_per_seat", 19.0)
            plan_type = billing.get("_detected_plan_type", "business")
            seat_breakdown = billing.get("seat_breakdown", {})
            total = seat_breakdown.get("total", 0)
            active = seat_breakdown.get("active_this_cycle", 0)
            pending_cancel = seat_breakdown.get("pending_cancellation", 0)
            inactive = total - active

            monthly_cost = total * price
            waste_cost = inactive * price

            org_overview = {
                "org": org,
                "plan_type": plan_type,
                "price_per_seat": price,
                "total_seats": total,
                "active_seats": active,
                "inactive_seats": inactive,
                "pending_cancellation": pending_cancel,
                "monthly_cost": monthly_cost,
                "estimated_monthly_waste": waste_cost,
                "utilization_pct": round(active / total * 100, 1) if total > 0 else 0,
            }
            overview.append(org_overview)

        grand_total_cost = sum(o["monthly_cost"] for o in overview)
        grand_total_waste = sum(o["estimated_monthly_waste"] for o in overview)

        return json.dumps({
            "organizations": overview,
            "grand_total_monthly_cost": grand_total_cost,
            "grand_total_estimated_waste": grand_total_waste,
            "potential_annual_savings": grand_total_waste * 12,
        })

    @define_tool(description="Calculate ROI metrics for Copilot investment. Shows cost per active user, suggestions per dollar, and efficiency metrics.")
    def calculate_roi(params: CalculateROIParams) -> str:
        orgs_to_check = [params.org] if params.org else list(collector.load_all_latest("billing").keys())
        roi_data = []

        for org in orgs_to_check:
            billing = collector.load_latest("billing", org)
            usage_data = collector.load_latest("usage", org)

            if not billing:
                continue

            price = billing.get("_detected_price_per_seat", 19.0)
            seat_breakdown = billing.get("seat_breakdown", {})
            total = seat_breakdown.get("total", 0)
            active = seat_breakdown.get("active_this_cycle", 0)
            monthly_cost = total * price

            total_suggestions = 0
            total_acceptances = 0
            if usage_data and isinstance(usage_data, list):
                total_suggestions = sum(d.get("total_suggestions_count", 0) for d in usage_data)
                total_acceptances = sum(d.get("total_acceptances_count", 0) for d in usage_data)

            cost_per_active_user = monthly_cost / active if active > 0 else 0
            acceptance_rate = total_acceptances / total_suggestions * 100 if total_suggestions > 0 else 0

            roi_data.append({
                "org": org,
                "monthly_cost": monthly_cost,
                "total_seats": total,
                "active_seats": active,
                "cost_per_active_user": round(cost_per_active_user, 2),
                "total_suggestions": total_suggestions,
                "total_acceptances": total_acceptances,
                "acceptance_rate_pct": round(acceptance_rate, 1),
                "suggestions_per_dollar": round(total_suggestions / monthly_cost, 1) if monthly_cost > 0 else 0,
            })

        return json.dumps({"roi_by_org": roi_data})

    return [get_cost_overview, calculate_roi]
