"""Conversation and Message schemas."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ConversationOut(BaseModel):
    id: str
    agent_id: str
    title: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MessageOut(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    audio_url: str | None
    metadata_: dict[str, Any] = {}
    created_at: datetime

    model_config = {"from_attributes": True}
