"""Conversation routes — list, create, append message, delete.

Wires the voice UI to a REST persistence layer:

  * POST   /api/conversations            — create (called at session start)
  * POST   /api/conversations/{id}/messages — append a transcript entry
  * GET    /api/conversations?agent_id=... — list, optionally by agent
  * GET    /api/conversations/{id}/messages — chronological restore
  * DELETE /api/conversations/{id}       — remove (cascades messages)

All reads/writes verify ownership through the Agent.user_id chain — a
stale id from another user returns 404 rather than leaking data.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from melo.api.deps import get_current_user
from melo.models.database import get_db
from melo.models.db import Agent, Conversation, Message, User
from melo.models.schemas.conversation import (
    ConversationCreate,
    ConversationOut,
    MessageCreate,
    MessageOut,
)

router = APIRouter(prefix="/conversations", tags=["conversations"])


def _owned_conversation_stmt(conversation_id: str, user_id: str):
    """SELECT a Conversation joined to its Agent, filtered by both the
    conversation id AND the agent's owner. Used by every read/write
    path below so the ownership check is in one place."""
    return (
        select(Conversation)
        .join(Agent, Agent.id == Conversation.agent_id)
        .where(
            Conversation.id == conversation_id,
            Agent.user_id == user_id,
        )
    )


@router.get("", response_model=list[ConversationOut])
async def list_all(
    agent_id: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List conversations for the current user, newest first.

    Optional `agent_id` query param filters to one agent so the voice
    UI can load the most recent conversation when an agent is selected.
    """
    stmt = (
        select(Conversation)
        .join(Agent, Agent.id == Conversation.agent_id)
        .where(Agent.user_id == user.id)
        .order_by(Conversation.updated_at.desc())
    )
    if agent_id is not None:
        stmt = stmt.where(Conversation.agent_id == agent_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post("", response_model=ConversationOut, status_code=201)
async def create(
    data: ConversationCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a conversation under an agent owned by the current user."""
    result = await db.execute(
        select(Agent).where(Agent.id == data.agent_id, Agent.user_id == user.id)
    )
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")
    title = (data.title or "").strip() or "New conversation"
    conv = Conversation(agent_id=data.agent_id, title=title)
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return conv


@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
async def messages(
    conversation_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List a conversation's messages in chronological order."""
    result = await db.execute(_owned_conversation_stmt(conversation_id, user.id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    msg_result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
    )
    return list(msg_result.scalars().all())


@router.post(
    "/{conversation_id}/messages",
    response_model=MessageOut,
    status_code=201,
)
async def append_message(
    conversation_id: str,
    data: MessageCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Append a message to a conversation owned by the current user.

    The voice UI calls this whenever a transcript entry finalizes:
    asr_final → role='user', LLM finalize → role='assistant',
    tool_call/tool_result/voice_changed → role='system'. The parent
    conversation's updated_at bumps via onupdate so the conversations
    list ordering stays accurate.
    """
    result = await db.execute(_owned_conversation_stmt(conversation_id, user.id))
    conv = result.scalar_one_or_none()
    if conv is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    if data.role not in ("user", "assistant", "system"):
        raise HTTPException(status_code=422, detail=f"invalid role: {data.role}")
    if not data.content.strip():
        raise HTTPException(status_code=422, detail="content must not be empty")
    msg = Message(
        conversation_id=conversation_id,
        role=data.role,
        content=data.content,
        audio_url=data.audio_url,
        metadata_=data.metadata_ or {},
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)
    return msg


@router.delete("/{conversation_id}", status_code=204)
async def delete(
    conversation_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a conversation owned by the current user."""
    result = await db.execute(_owned_conversation_stmt(conversation_id, user.id))
    conv = result.scalar_one_or_none()
    if conv:
        await db.delete(conv)
        await db.commit()
