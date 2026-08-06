"""Agent schemas."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from melo.models.schemas.conversation import ConversationOut


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    persona: str | None = None
    system_prompt: str | None = None
    voice_id: str | None = None
    llm_config: dict[str, Any] = Field(default_factory=dict)


class AgentUpdate(BaseModel):
    name: str | None = None
    persona: str | None = None
    system_prompt: str | None = None
    voice_id: str | None = None
    llm_config: dict[str, Any] | None = None


class AgentOut(BaseModel):
    id: str
    name: str
    persona: str | None
    system_prompt: str | None
    voice_id: str | None
    llm_config: dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}


class AgentDetail(AgentOut):
    conversations: list[ConversationOut] = []
