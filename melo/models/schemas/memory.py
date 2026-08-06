"""Memory schemas — Pydantic models for the memories table.

CRUD schemas are defined here alongside the FTS5 search schema so the
memory route can import them from a single module.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class MemoryCreate(BaseModel):
    """Payload for creating a new memory."""
    user_id: str
    agent_id: str | None = None
    content: str = Field(min_length=1)
    role: str = Field(default="system", max_length=32)
    metadata_: dict[str, Any] = {}


class MemoryUpdate(BaseModel):
    """Partial update for a memory."""
    content: str | None = Field(default=None, min_length=1)
    role: str | None = Field(default=None, max_length=32)
    metadata_: dict[str, Any] | None = None


class MemoryOut(BaseModel):
    """Memory as returned by the API."""
    id: str
    user_id: str
    agent_id: str | None
    content: str
    role: str
    metadata_: dict[str, Any] = {}
    created_at: datetime

    model_config = {"from_attributes": True}


class MemorySearch(BaseModel):
    """FTS5 search query for the memory route.

    Defined here so the memory route can import it from this module
    alongside the CRUD schemas.
    """
    query: str = Field(min_length=1)
    user_id: str
    agent_id: str | None = None
    limit: int = Field(default=10, ge=1, le=100)
