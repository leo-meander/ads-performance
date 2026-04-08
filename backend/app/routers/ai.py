"""AI Chat endpoints: streaming Claude responses with hotel marketing context."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.ai_conversation import AIConversation
from app.services.ai_client import build_context, chat_stream

router = APIRouter()


def _api_response(data=None, error=None):
    return {
        "success": error is None,
        "data": data,
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


class ChatRequest(BaseModel):
    session_id: str | None = None  # None = new session
    message: str


@router.post("/ai/chat")
def chat(body: ChatRequest, db: Session = Depends(get_db)):
    """Send a message and get a streaming response from Claude."""
    session_id = body.session_id or str(uuid.uuid4())

    # Save user message
    user_msg = AIConversation(session_id=session_id, role="user", content=body.message)
    db.add(user_msg)
    db.commit()

    # Load conversation history
    history_rows = (
        db.query(AIConversation)
        .filter(AIConversation.session_id == session_id)
        .order_by(AIConversation.created_at)
        .all()
    )
    messages = [{"role": r.role, "content": r.content} for r in history_rows]

    # Build context from DB
    context = build_context(db)

    # Collect full response for saving
    response_parts: list[str] = []

    def stream_and_save():
        for chunk in chat_stream(db, messages, context):
            response_parts.append(chunk)
            # SSE format
            yield f"data: {chunk}\n\n"

        # Save assistant response after streaming completes
        full_response = "".join(response_parts)
        assistant_msg = AIConversation(session_id=session_id, role="assistant", content=full_response)
        db_save = next(get_db_for_save())
        db_save.add(assistant_msg)
        db_save.commit()
        db_save.close()

        yield f"data: [DONE]\n\n"

    # We need a separate db session for saving after stream (original may be closed)
    def get_db_for_save():
        from app.database import SessionLocal
        s = SessionLocal()
        try:
            yield s
        finally:
            s.close()

    return StreamingResponse(
        stream_and_save(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Session-Id": session_id,
        },
    )


@router.get("/ai/sessions")
def list_sessions(db: Session = Depends(get_db)):
    """List all chat sessions with first message preview."""
    try:
        # Get distinct session_ids with their first message
        from sqlalchemy import func
        sessions = (
            db.query(
                AIConversation.session_id,
                func.min(AIConversation.created_at).label("started_at"),
                func.count(AIConversation.id).label("message_count"),
            )
            .group_by(AIConversation.session_id)
            .order_by(func.max(AIConversation.created_at).desc())
            .all()
        )

        result = []
        for s in sessions:
            # Get first user message as preview
            first_msg = (
                db.query(AIConversation)
                .filter(AIConversation.session_id == s.session_id, AIConversation.role == "user")
                .order_by(AIConversation.created_at)
                .first()
            )
            result.append({
                "session_id": s.session_id,
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "message_count": s.message_count,
                "preview": first_msg.content[:100] if first_msg else "",
            })

        return _api_response(data=result)
    except Exception as e:
        return _api_response(error=str(e))


@router.get("/ai/sessions/{session_id}")
def get_session(session_id: str, db: Session = Depends(get_db)):
    """Get full conversation history for a session."""
    try:
        messages = (
            db.query(AIConversation)
            .filter(AIConversation.session_id == session_id)
            .order_by(AIConversation.created_at)
            .all()
        )
        return _api_response(data=[{
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        } for m in messages])
    except Exception as e:
        return _api_response(error=str(e))


@router.delete("/ai/sessions/{session_id}")
def delete_session(session_id: str, db: Session = Depends(get_db)):
    """Delete a chat session."""
    try:
        deleted = db.query(AIConversation).filter(AIConversation.session_id == session_id).delete()
        db.commit()
        return _api_response(data={"session_id": session_id, "deleted": deleted})
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))
