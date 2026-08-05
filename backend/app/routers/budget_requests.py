"""
User request workflow.

Regular (non-admin) GitHub SSO users can submit two kinds of request:

- ``budget``      — a personal Copilot AI-credit budget. GitHub budgets run on a
                    single monthly billing cycle, so there is no period to pick.
- ``cost_center`` — move to a different enterprise cost center. GitHub allows a
                    user to belong to at most one, so this is a single choice.

Administrators review them and may approve (amending the amount where relevant)
or reject. Approving applies the change against the real GitHub API.

All data is persisted as JSON in ``data/budget_requests.json``.
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..config import DATA_DIR
from ..services.budget_provisioner import provision_user_budget
from ..services.cost_center_provisioner import apply_membership_change, diff_membership
from .auth import require_user

router = APIRouter(tags=["budget-requests"])

REQUESTS_FILE = DATA_DIR / "budget_requests.json"

TYPE_BUDGET = "budget"
TYPE_COST_CENTER = "cost_center"
VALID_TYPES = {TYPE_BUDGET, TYPE_COST_CENTER}

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
VALID_STATUSES = {STATUS_PENDING, STATUS_APPROVED, STATUS_REJECTED}

_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> list[dict]:
    if not REQUESTS_FILE.exists():
        return []
    try:
        raw = json.loads(REQUESTS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        return raw.get("requests", [])
    return []


def _save(requests: list[dict]) -> None:
    REQUESTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = REQUESTS_FILE.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps({"requests": requests}, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    tmp.replace(REQUESTS_FILE)


def load_requests_for(login: str) -> list[dict]:
    """All requests submitted by a given user (newest first)."""
    return [r for r in _load() if r.get("user_login", "").lower() == login.lower()]


# ---------------------------------------------------------------------------
# Param models
# ---------------------------------------------------------------------------

class CreateBudgetRequest(BaseModel):
    """A new user request.

    ``request_type="budget"`` uses ``amount`` (+ optional ``org``);
    ``request_type="cost_center"`` uses ``cost_center_id`` — the single cost
    center the user wants to be assigned to ("" to be unassigned).
    """

    request_type: str = Field(default=TYPE_BUDGET, description="budget | cost_center")
    # Copilot budgets are always per monthly billing cycle — no period to choose.
    amount: float | None = Field(default=None, description="Requested budget amount in USD")
    org: str = Field(default="")
    # A user belongs to at most one cost center; "" means "unassign me".
    cost_center_id: str = Field(default="")
    reason: str = Field(default="")


class ReviewBudgetRequest(BaseModel):
    request_id: str
    decision: str = Field(description="approve | reject")
    approved_amount: float | None = None
    comment: str = Field(default="")
    apply_to_github: bool = Field(
        default=True,
        description="Apply the approved change to GitHub (budget or cost center membership)",
    )
    prevent_further_usage: bool = Field(
        default=True,
        description="Hard-limit the GitHub budget (block usage once exhausted)",
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/budget-requests")
async def list_budget_requests(request: Request, status: str = Query(default="all")):
    """List budget requests.

    Admins see every request; regular users only see their own.
    """
    user = require_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Authentication required"})

    admin = bool(user.get("is_admin"))
    requests = _load()
    if not admin:
        requests = [r for r in requests if r.get("user_login", "").lower() == user["login"].lower()]

    if status and status != "all":
        requests = [r for r in requests if r.get("status") == status]

    requests.sort(key=lambda r: r.get("created_at", ""), reverse=True)

    all_for_stats = _load() if admin else requests
    summary = {
        "total": len(all_for_stats),
        "pending": sum(1 for r in all_for_stats if r.get("status") == STATUS_PENDING),
        "approved": sum(1 for r in all_for_stats if r.get("status") == STATUS_APPROVED),
        "rejected": sum(1 for r in all_for_stats if r.get("status") == STATUS_REJECTED),
        "approved_amount": round(
            sum(
                float(r.get("approved_amount") or 0)
                for r in all_for_stats
                if r.get("status") == STATUS_APPROVED
            ),
            2,
        ),
        "pending_amount": round(
            sum(
                float(r.get("requested_amount") or 0)
                for r in all_for_stats
                if r.get("status") == STATUS_PENDING
            ),
            2,
        ),
        "budget_requests": sum(
            1 for r in all_for_stats if r.get("request_type", TYPE_BUDGET) == TYPE_BUDGET
        ),
        "cost_center_requests": sum(
            1 for r in all_for_stats if r.get("request_type") == TYPE_COST_CENTER
        ),
    }

    return {"requests": requests, "is_admin": admin, "summary": summary}


@router.post("/budget-requests")
async def create_budget_request(payload: CreateBudgetRequest, request: Request):
    """Submit a new budget or cost center request for the logged-in user."""
    user = require_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Authentication required"})

    login = user.get("login", "")
    request_type = (payload.request_type or TYPE_BUDGET).strip().lower()
    if request_type not in VALID_TYPES:
        return {"error": "request_type must be 'budget' or 'cost_center'"}

    requested_amount = None
    cost_center_id = ""
    cost_center_plan: dict | None = None

    if request_type == TYPE_BUDGET:
        if payload.amount is None or float(payload.amount) <= 0:
            return {"error": "A budget amount greater than 0 is required."}
        requested_amount = round(float(payload.amount), 2)
    else:
        cost_center_id = payload.cost_center_id.strip()
        plan = diff_membership(login, cost_center_id)
        if plan.get("invalid"):
            return {"error": "The selected cost center no longer exists."}
        if not plan["add"] and not plan["remove"]:
            return {"error": "Your cost center selection matches your current assignment."}

        def _entry(c):
            return {"id": c["id"], "name": c["name"], "enterprise": c["enterprise"]}

        cost_center_plan = {
            "from": _entry(plan["current"]) if plan["current"] else None,
            "to": _entry(plan["target"]) if plan["target"] else None,
        }

    entry = {
        "id": uuid.uuid4().hex[:12],
        "request_type": request_type,
        "user_login": login,
        "user_name": user.get("name", ""),
        "avatar_url": user.get("avatar_url", ""),
        "requested_amount": requested_amount,
        "approved_amount": None,
        "currency": "USD",
        "org": payload.org.strip(),
        "cost_center_id": cost_center_id,
        "cost_center_plan": cost_center_plan,
        "reason": payload.reason.strip(),
        "status": STATUS_PENDING,
        "created_at": _now(),
        "updated_at": _now(),
        "reviewed_by": "",
        "reviewed_at": "",
        "review_comment": "",
        "history": [
            {
                "action": "created",
                "by": login,
                "at": _now(),
                "amount": requested_amount,
            }
        ],
    }

    with _lock:
        requests = _load()
        requests.append(entry)
        _save(requests)

    return {"ok": True, "request": entry}


@router.post("/budget-requests/review")
async def review_budget_request(payload: ReviewBudgetRequest, request: Request):
    """Approve or reject a request. Admins only.

    Approving provisions a **real** GitHub `user`-scope AI-credit budget for the
    requester (created, or updated when one already exists), so the approved
    number actually takes effect on GitHub rather than only inside OctoFinance.
    """
    user = require_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Authentication required"})
    if not user.get("is_admin"):
        return JSONResponse(status_code=403, content={"error": "Administrator access required"})

    decision = payload.decision.strip().lower()
    if decision not in {"approve", "reject"}:
        return {"error": "decision must be 'approve' or 'reject'"}

    # Locate the request first (outside the write lock, GitHub calls are slow)
    target = next((r for r in _load() if r.get("id") == payload.request_id), None)
    if target is None:
        return JSONResponse(status_code=404, content={"error": "Request not found"})

    github_result: dict | None = None
    cost_center_result: dict | None = None
    approved_amount: float | None = None
    request_type = target.get("request_type", TYPE_BUDGET)

    if decision == "approve":
        if request_type == TYPE_COST_CENTER:
            if payload.apply_to_github:
                cost_center_result = await apply_membership_change(
                    target.get("user_login", ""),
                    target.get("cost_center_id", "") or "",
                )
            else:
                cost_center_result = {
                    "status": "skipped", "added": [], "removed": [], "errors": [],
                    "reason": "apply_to_github=false", "synced_at": _now(),
                }
        else:
            amount = payload.approved_amount
            if amount is None:
                amount = float(target.get("requested_amount") or 0)
            if float(amount) < 0:
                return {"error": "Approved amount cannot be negative"}
            approved_amount = round(float(amount), 2)

            if payload.apply_to_github:
                github_result = await provision_user_budget(
                    target.get("user_login", ""),
                    approved_amount,
                    preferred_org=target.get("org", ""),
                    prevent_further_usage=payload.prevent_further_usage,
                )
            else:
                github_result = {"status": "skipped", "reason": "apply_to_github=false", "synced_at": _now()}

    with _lock:
        requests = _load()
        target = next((r for r in requests if r.get("id") == payload.request_id), None)
        if target is None:
            return JSONResponse(status_code=404, content={"error": "Request not found"})

        if decision == "approve":
            target["status"] = STATUS_APPROVED
            if request_type == TYPE_COST_CENTER:
                target["cost_center_result"] = cost_center_result
            else:
                target["approved_amount"] = approved_amount
                target["github_budget"] = github_result
        else:
            target["status"] = STATUS_REJECTED
            target["approved_amount"] = None

        applied = github_result or cost_center_result or {}
        target["reviewed_by"] = user.get("login", "")
        target["reviewed_at"] = _now()
        target["review_comment"] = payload.comment.strip()
        target["updated_at"] = _now()
        target.setdefault("history", []).append({
            "action": STATUS_APPROVED if decision == "approve" else STATUS_REJECTED,
            "by": user.get("login", ""),
            "at": _now(),
            "amount": target.get("approved_amount"),
            "comment": payload.comment.strip(),
            "github_budget_status": applied.get("status"),
            "github_budget_error": applied.get("error"),
        })
        _save(requests)

    if github_result and github_result.get("status") == "failed":
        return {
            "ok": True,
            "request": target,
            "warning": (
                "Approved in OctoFinance, but the GitHub budget could not be created: "
                f"{github_result.get('error')}"
            ),
        }
    if cost_center_result and cost_center_result.get("status") in ("failed", "partial"):
        return {
            "ok": True,
            "request": target,
            "warning": (
                "Approved, but the cost center membership change did not fully apply: "
                f"{cost_center_result.get('error')}"
            ),
        }

    return {"ok": True, "request": target}


@router.post("/budget-requests/amount")
async def update_budget_amount(payload: ReviewBudgetRequest, request: Request):
    """Adjust the approved amount of an already-reviewed request. Admins only.

    Re-applies the new amount to the real GitHub budget.
    """
    user = require_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Authentication required"})
    if not user.get("is_admin"):
        return JSONResponse(status_code=403, content={"error": "Administrator access required"})
    if payload.approved_amount is None or payload.approved_amount < 0:
        return {"error": "A non-negative approved_amount is required"}

    target = next((r for r in _load() if r.get("id") == payload.request_id), None)
    if target is None:
        return JSONResponse(status_code=404, content={"error": "Request not found"})
    if target.get("request_type", TYPE_BUDGET) != TYPE_BUDGET:
        return {"error": "Only budget requests have an amount"}

    amount = round(float(payload.approved_amount), 2)
    github_result: dict
    if payload.apply_to_github:
        github_result = await provision_user_budget(
            target.get("user_login", ""),
            amount,
            preferred_org=target.get("org", ""),
            prevent_further_usage=payload.prevent_further_usage,
        )
    else:
        github_result = {"status": "skipped", "reason": "apply_to_github=false", "synced_at": _now()}

    with _lock:
        requests = _load()
        target = next((r for r in requests if r.get("id") == payload.request_id), None)
        if target is None:
            return JSONResponse(status_code=404, content={"error": "Request not found"})

        target["approved_amount"] = amount
        target["status"] = STATUS_APPROVED
        target["github_budget"] = github_result
        target["reviewed_by"] = user.get("login", "")
        target["reviewed_at"] = _now()
        target["updated_at"] = _now()
        if payload.comment.strip():
            target["review_comment"] = payload.comment.strip()
        target.setdefault("history", []).append({
            "action": "amount_updated",
            "by": user.get("login", ""),
            "at": _now(),
            "amount": amount,
            "comment": payload.comment.strip(),
            "github_budget_status": github_result.get("status"),
            "github_budget_error": github_result.get("error"),
        })
        _save(requests)

    if github_result.get("status") == "failed":
        return {
            "ok": True,
            "request": target,
            "warning": f"Amount updated, but the GitHub budget could not be updated: {github_result.get('error')}",
        }

    return {"ok": True, "request": target}


@router.post("/budget-requests/resync")
async def resync_budget_request(payload: ReviewBudgetRequest, request: Request):
    """Retry pushing an approved request's amount to GitHub. Admins only."""
    user = require_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Authentication required"})
    if not user.get("is_admin"):
        return JSONResponse(status_code=403, content={"error": "Administrator access required"})

    target = next((r for r in _load() if r.get("id") == payload.request_id), None)
    if target is None:
        return JSONResponse(status_code=404, content={"error": "Request not found"})
    if target.get("status") != STATUS_APPROVED:
        return {"error": "Only approved requests can be synced to GitHub"}

    is_cost_center = target.get("request_type", TYPE_BUDGET) == TYPE_COST_CENTER
    amount = float(target.get("approved_amount") or 0)

    if is_cost_center:
        result = await apply_membership_change(
            target.get("user_login", ""), target.get("cost_center_id", "") or ""
        )
    else:
        result = await provision_user_budget(
            target.get("user_login", ""),
            amount,
            preferred_org=target.get("org", ""),
            prevent_further_usage=payload.prevent_further_usage,
        )

    with _lock:
        requests = _load()
        target = next((r for r in requests if r.get("id") == payload.request_id), None)
        if target is None:
            return JSONResponse(status_code=404, content={"error": "Request not found"})
        if is_cost_center:
            target["cost_center_result"] = result
        else:
            target["github_budget"] = result
        target["updated_at"] = _now()
        target.setdefault("history", []).append({
            "action": "github_resync",
            "by": user.get("login", ""),
            "at": _now(),
            "amount": None if is_cost_center else amount,
            "github_budget_status": result.get("status"),
            "github_budget_error": result.get("error"),
        })
        _save(requests)

    return {"ok": True, "request": target, "github_budget": result}


@router.get("/budget-requests/audit")
async def budget_request_audit(request: Request, limit: int = Query(default=200)):
    """Flat, newest-first audit trail of every decision. Admins only."""
    user = require_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Authentication required"})
    if not user.get("is_admin"):
        return JSONResponse(status_code=403, content={"error": "Administrator access required"})

    entries: list[dict] = []
    for req in _load():
        for event in req.get("history", []) or []:
            entries.append({
                "request_id": req.get("id", ""),
                "request_type": req.get("request_type", TYPE_BUDGET),
                "user_login": req.get("user_login", ""),
                "avatar_url": req.get("avatar_url", ""),
                "requested_amount": req.get("requested_amount"),
                "org": req.get("org", ""),
                "cost_center_plan": req.get("cost_center_plan"),
                "reason": req.get("reason", ""),
                "action": event.get("action", ""),
                "by": event.get("by", ""),
                "at": event.get("at", ""),
                "amount": event.get("amount"),
                "comment": event.get("comment", ""),
                "github_budget_status": event.get("github_budget_status"),
                "github_budget_error": event.get("github_budget_error"),
            })

    entries.sort(key=lambda e: e.get("at", ""), reverse=True)
    return {"entries": entries[: max(1, limit)], "total": len(entries)}


@router.delete("/budget-requests/{request_id}")
async def delete_budget_request(request_id: str, request: Request):
    """Withdraw a pending request (owner) or delete any request (admin)."""
    user = require_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Authentication required"})

    with _lock:
        requests = _load()
        target = next((r for r in requests if r.get("id") == request_id), None)
        if target is None:
            return JSONResponse(status_code=404, content={"error": "Request not found"})

        is_owner = target.get("user_login", "").lower() == user.get("login", "").lower()
        if not user.get("is_admin"):
            if not is_owner:
                return JSONResponse(status_code=403, content={"error": "Not allowed"})
            if target.get("status") != STATUS_PENDING:
                return JSONResponse(
                    status_code=400, content={"error": "Only pending requests can be withdrawn"}
                )

        _save([r for r in requests if r.get("id") != request_id])

    return {"ok": True, "deleted": request_id}
