"""
Data query router - provides read access to collected data.
Supports enterprise grouping for org display.
"""

from collections import defaultdict

from fastapi import APIRouter

from ..services.api_manager import api_manager
from ..services.data_collector import data_collector

router = APIRouter(tags=["data"])


@router.get("/data/orgs")
async def get_orgs():
    """Get all discovered organizations with their Copilot status, grouped by enterprise."""
    all_orgs = api_manager.get_all_orgs()
    orgs_list = []

    for org_info in all_orgs:
        org_name = org_info["login"]
        billing = data_collector.load_latest("billing", org_name)

        org_data = {
            "login": org_name,
            "avatar_url": org_info.get("avatar_url"),
            "description": org_info.get("description"),
            "has_copilot": billing is not None,
            "enterprise": org_info.get("enterprise", "Independent"),
            "pat_user": org_info.get("pat_user", ""),
        }

        if billing:
            org_data["plan_type"] = billing.get("_detected_plan_type", "unknown")
            org_data["price_per_seat"] = billing.get("_detected_price_per_seat", 0)
            seat_breakdown = billing.get("seat_breakdown", {})
            org_data["total_seats"] = seat_breakdown.get("total", 0)
            org_data["active_seats"] = seat_breakdown.get("active_this_cycle", 0)

        orgs_list.append(org_data)

    # Group by enterprise
    groups: dict[str, list] = defaultdict(list)
    for org in orgs_list:
        groups[org.get("enterprise", "Independent")].append(org)

    enterprises = [
        {"name": name, "orgs": orgs}
        for name, orgs in sorted(groups.items(), key=lambda x: (x[0] == "Independent", x[0]))
    ]

    return {"enterprises": enterprises, "orgs": orgs_list, "total": len(orgs_list)}


@router.get("/data/overview")
async def get_overview():
    """Get a quick overview across all organizations."""
    all_orgs = api_manager.get_all_orgs()
    total_seats = 0
    total_active = 0
    total_cost = 0.0
    total_waste = 0.0
    orgs_with_copilot = 0

    for org_info in all_orgs:
        org_name = org_info["login"]
        billing = data_collector.load_latest("billing", org_name)
        if not billing:
            continue

        orgs_with_copilot += 1
        price = billing.get("_detected_price_per_seat", 19.0)
        sb = billing.get("seat_breakdown", {})
        seats = sb.get("total", 0)
        active = sb.get("active_this_cycle", 0)

        total_seats += seats
        total_active += active
        total_cost += seats * price
        total_waste += (seats - active) * price

    return {
        "total_organizations": len(all_orgs),
        "orgs_with_copilot": orgs_with_copilot,
        "total_seats": total_seats,
        "total_active_seats": total_active,
        "total_inactive_seats": total_seats - total_active,
        "utilization_pct": round(total_active / total_seats * 100, 1) if total_seats > 0 else 0,
        "monthly_cost": total_cost,
        "monthly_waste": total_waste,
        "annual_waste": total_waste * 12,
    }


@router.get("/data/seats/{org}")
async def get_seats(org: str):
    """Get seat data for a specific organization."""
    data = data_collector.load_latest("seats", org)
    if not data:
        return {"error": f"No seat data for {org}"}
    return data


@router.get("/data/billing/{org}")
async def get_billing(org: str):
    """Get billing data for a specific organization."""
    data = data_collector.load_latest("billing", org)
    if not data:
        return {"error": f"No billing data for {org}"}
    return data
