"""
Budget request workflow.

Regular (non-admin) GitHub SSO users can submit budget requests; administrators
review them and may approve (optionally amending the amount) or reject.

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
from .auth import require_user

router = APIRouter(tags=["budget-requests"])

REQUESTS_FILE = DATA_DIR / "budget_requests.json"

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
    amount: float = Field(gt=0, description="Requested budget amount in USD")
    period: str = Field(default="monthly", description="monthly | quarterly | yearly | one_time")
    org: str = Field(default="")
    cost_center: str = Field(default="")
    reason: str = Field(default="")


class ReviewBudgetRequest(BaseModel):
    request_id: str
    decision: str = Field(description="approve | reject")
    approved_amount: float | None = None
    comment: str = Field(default="")
    apply_to_github: bool = Field(
        default=True,
        description="Create/update the real GitHub user budget when approving",
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
    }

    return {"requests": requests, "is_admin": admin, "summary": summary}


@router.post("/budget-requests")
async def create_budget_request(payload: CreateBudgetRequest, request: Request):
    """Submit a new budget request for the currently logged-in user."""
    user = require_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Authentication required"})

    period = payload.period.strip() or "monthly"
    if period not in {"monthly", "quarterly", "yearly", "one_time"}:
        return {"error": "Invalid period. Use monthly, quarterly, yearly or one_time."}

    entry = {
        "id": uuid.uuid4().hex[:12],
        "user_login": user.get("login", ""),
        "user_name": user.get("name", ""),
        "avatar_url": user.get("avatar_url", ""),
        "requested_amount": round(float(payload.amount), 2),
        "approved_amount": None,
        "currency": "USD",
        "period": period,
        "org": payload.org.strip(),
        "cost_center": payload.cost_center.strip(),
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
                "by": user.get("login", ""),
                "at": _now(),
                "amount": round(float(payload.amount), 2),
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
    approved_amount: float | None = None

    if decision == "approve":
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
            target["approved_amount"] = approved_amount
            target["github_budget"] = github_result
        else:
            target["status"] = STATUS_REJECTED
            target["approved_amount"] = None

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
            "github_budget_status": (github_result or {}).get("status"),
            "github_budget_error": (github_result or {}).get("error"),
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

    amount = float(target.get("approved_amount") or 0)
    github_result = await provision_user_budget(
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
        target["github_budget"] = github_result
        target["updated_at"] = _now()
        target.setdefault("history", []).append({
            "action": "github_resync",
            "by": user.get("login", ""),
            "at": _now(),
            "amount": amount,
            "github_budget_status": github_result.get("status"),
            "github_budget_error": github_result.get("error"),
        })
        _save(requests)

    return {"ok": True, "request": target, "github_budget": github_result}


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
                "user_login": req.get("user_login", ""),
                "avatar_url": req.get("avatar_url", ""),
                "requested_amount": req.get("requested_amount"),
                "org": req.get("org", ""),
                "cost_center": req.get("cost_center", ""),
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
