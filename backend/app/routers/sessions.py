"""
Sessions router - CRUD endpoints for chat session management.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services.copilot_engine import copilot_engine
from ..services.session_manager import session_manager

router = APIRouter(tags=["sessions"])


class CreateSessionRequest(BaseModel):
    title: str = "New Session"


class UpdateSessionRequest(BaseModel):
    title: str


@router.get("/sessions")
async def list_sessions():
    """List all chat sessions."""
    return session_manager.list_sessions()


@router.post("/sessions")
async def create_session(request: CreateSessionRequest):
    """Create a new chat session."""
    return session_manager.create_session(title=request.title)


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """Get a single session's metadata."""
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.get("/sessions/{session_id}/messages")
async def get_session_messages(session_id: str):
    """Load all messages from a session."""
    if not session_manager.session_exists(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return session_manager.load_messages(session_id)


@router.put("/sessions/{session_id}")
async def update_session(session_id: str, request: UpdateSessionRequest):
    """Update a session's title."""
    result = session_manager.update_session_title(session_id, request.title)
    if not result:
        raise HTTPException(status_code=404, detail="Session not found")
    return result


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a session and its data."""
    # Also destroy the Copilot SDK session if it exists
    await copilot_engine.destroy_session(session_id)
    session_manager.delete_session(session_id)
    return {"ok": True}
