"""Conversation routes — list, messages, delete."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from melo.api.deps import get_current_user
from melo.models.database import get_db
from melo.models.db import Conversation, Message, User
from melo.models.schemas.conversation import ConversationOut, MessageOut

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("", response_model=list[ConversationOut])
async def list_all(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Conversation).join(Conversation.agent).where("agents.user_id" == user.id).order_by(Conversation.updated_at.desc())
    )
    return list(result.scalars().all())


@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
async def messages(conversation_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at))
    return list(result.scalars().all())


@router.delete("/{conversation_id}", status_code=204)
async def delete(conversation_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Conversation).where(Conversation.id == conversation_id))
    conv = result.scalar_one_or_none()
    if conv:
        await db.delete(conv)
        await db.commit()
