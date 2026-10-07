"""
Prompts router - the admin's library of saved AI chat prompts.
"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..services import prompt_library
from .auth import require_user

router = APIRouter(tags=["prompts"])


class CreatePromptRequest(BaseModel):
    title: str = ""
    prompt: str
    shared: bool = False


class UpdatePromptRequest(BaseModel):
    title: str | None = None
    prompt: str | None = None
    shared: bool | None = None


def _login(request: Request) -> str:
    user = require_user(request)
    if not user or not user.get("login"):
        raise HTTPException(status_code=401, detail="Authentication required")
    return user["login"]


def _run(action):
    try:
        return action()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except prompt_library.PromptNotFound:
        raise HTTPException(status_code=404, detail="Prompt not found")
    except prompt_library.PromptForbidden:
        raise HTTPException(status_code=403, detail="Only the admin who saved this prompt can change it")


@router.get("/prompts")
async def list_prompts(request: Request):
    """List the current admin's prompts and those shared by other admins."""
    return {"prompts": prompt_library.list_prompts(_login(request))}


@router.post("/prompts")
async def create_prompt(body: CreatePromptRequest, request: Request):
    login = _login(request)
    return _run(lambda: prompt_library.create_prompt(login, body.title, body.prompt, body.shared))


@router.put("/prompts/{prompt_id}")
async def update_prompt(prompt_id: str, body: UpdatePromptRequest, request: Request):
    login = _login(request)
    return _run(lambda: prompt_library.update_prompt(login, prompt_id, body.title, body.prompt, body.shared))


@router.delete("/prompts/{prompt_id}")
async def delete_prompt(prompt_id: str, request: Request):
    login = _login(request)
    _run(lambda: prompt_library.delete_prompt(login, prompt_id))
    return {"ok": True}


@router.post("/prompts/{prompt_id}/use")
async def use_prompt(prompt_id: str, request: Request):
    """Record that a prompt was used, so the library lists it first next time."""
    login = _login(request)
    return _run(lambda: prompt_library.mark_used(login, prompt_id))
