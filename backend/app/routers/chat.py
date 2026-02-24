"""
Chat router - SSE endpoint for AI-powered FinOps conversations.
"""

import json
import time

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from ..services.copilot_engine import copilot_engine
from ..services.session_manager import session_manager, SESSIONS_DIR

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"


@router.post("/chat")
async def chat(request: ChatRequest):
    """Send a message to the AI FinOps engine and receive streaming response via SSE."""

    sid = request.session_id

    # Auto-create session if it doesn't exist
    if not session_manager.session_exists(sid):
        title = request.message[:50].strip()
        if len(request.message) > 50:
            title += "..."
        session_manager.create_session(session_id=sid, title=title)

    # Persist user message
    user_msg = {
        "id": str(int(time.time() * 1000)),
        "role": "user",
        "content": request.message,
        "timestamp": int(time.time() * 1000),
    }
    session_manager.append_message(sid, user_msg)

    session_dir = str(SESSIONS_DIR / sid)

    async def event_generator():
        full_content = ""
        try:
            async for event in copilot_engine.chat(request.message, sid, working_directory=session_dir):
                # Track assistant text
                if event["type"] == "delta":
                    full_content += event.get("content", "")
                elif event["type"] == "message":
                    if event.get("content"):
                        full_content = event["content"]

                # Persist tool call data
                if event["type"] == "tool_start":
                    session_manager.append_tool_call(sid, {
                        "event": "tool_start",
                        "tool_name": event.get("content"),
                        "tool_call_id": event.get("tool_call_id"),
                        "arguments": event.get("detail"),
                        "timestamp": int(time.time() * 1000),
                    })
                elif event["type"] == "tool_complete":
                    session_manager.append_tool_call(sid, {
                        "event": "tool_complete",
                        "tool_name": event.get("content"),
                        "tool_call_id": event.get("tool_call_id"),
                        "result": event.get("detail"),
                        "timestamp": int(time.time() * 1000),
                    })

                yield {
                    "event": event["type"],
                    "data": json.dumps(event),
                }
        except Exception as e:
            yield {
                "event": "error",
                "data": json.dumps({"type": "error", "content": str(e)}),
            }
        finally:
            # Persist assistant message
            if full_content:
                assistant_msg = {
                    "id": str(int(time.time() * 1000) + 1),
                    "role": "assistant",
                    "content": full_content,
                    "timestamp": int(time.time() * 1000),
                }
                session_manager.append_message(sid, assistant_msg)

    return EventSourceResponse(event_generator())


@router.post("/chat/simple")
async def chat_simple(request: ChatRequest):
    """Send a message and get a simple text response (non-streaming)."""
    sid = request.session_id

    # Auto-create session if it doesn't exist
    if not session_manager.session_exists(sid):
        title = request.message[:50].strip()
        if len(request.message) > 50:
            title += "..."
        session_manager.create_session(session_id=sid, title=title)

    # Persist user message
    user_msg = {
        "id": str(int(time.time() * 1000)),
        "role": "user",
        "content": request.message,
        "timestamp": int(time.time() * 1000),
    }
    session_manager.append_message(sid, user_msg)

    session_dir = str(SESSIONS_DIR / sid)
    response = await copilot_engine.chat_simple(request.message, sid, working_directory=session_dir)

    # Persist assistant message
    if response:
        assistant_msg = {
            "id": str(int(time.time() * 1000) + 1),
            "role": "assistant",
            "content": response,
            "timestamp": int(time.time() * 1000),
        }
        session_manager.append_message(sid, assistant_msg)

    return {"response": response, "session_id": sid}
