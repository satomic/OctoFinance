"""
Actions router - execute or manage AI-recommended operations.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from ..services.ops_executor import ops_executor

router = APIRouter(tags=["actions"])


@router.get("/actions/pending")
async def get_pending_actions():
    """Get all pending AI recommendations awaiting admin approval."""
    recs = ops_executor.get_pending_recommendations()
    return {"recommendations": recs, "count": len(recs)}


class ExecuteRequest(BaseModel):
    recommendation_id: str


@router.post("/actions/execute")
async def execute_action(request: ExecuteRequest):
    """Execute a pending recommendation."""
    result = await ops_executor.execute_recommendation(request.recommendation_id)
    return result


@router.post("/actions/approve")
async def approve_action(request: ExecuteRequest):
    """Approve a pending recommendation (mark as approved without executing)."""
    result = await ops_executor.approve_recommendation(request.recommendation_id)
    return result


@router.post("/actions/reject")
async def reject_action(request: ExecuteRequest):
    """Reject a pending recommendation."""
    result = await ops_executor.reject_recommendation(request.recommendation_id)
    return result
