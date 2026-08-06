"""Voice schemas."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class VoiceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    provider: str = "rvc"
    sample_url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class VoiceOut(BaseModel):
    id: str
    name: str
    provider: str
    provider_voice_id: str | None
    sample_url: str | None
    metadata_: dict[str, Any] = {}
    created_at: datetime

    model_config = {"from_attributes": True}
