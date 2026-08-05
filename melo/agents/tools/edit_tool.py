"""edit_audio tool — conversational audio editing via studio_service.

The studio agent dispatches natural-language edit instructions through
this tool. The tool resolves the clip (verifying ownership) and calls
`studio_service.apply_edit`, which interprets the instruction, mutates
the clip + metadata, and may trigger a TTS regeneration when text or
speed changes.

The DB session + user_id are bound at construction time so the tool
can be registered once per request lifecycle. When constructed without
a session (e.g. by `default_registry()` for the voice runtime), it
raises a clear `ToolError` instructing the caller to bind a session.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from melo.agents.tools.registry import Tool, ToolError

logger = logging.getLogger(__name__)


class EditAudioTool(Tool):
    """Apply a natural-language edit instruction to an audio clip."""

    name = "edit_audio"
    description = (
        "Apply a natural-language instruction to an audio clip. Args: "
        "clip_id (str), instruction (str). Supported: regenerate, speed up/slow down, "
        "replace text with ..., trim silence, delete. Returns: {clip_id, status, applied}."
    )

    def __init__(
        self,
        *,
        db: AsyncSession | None = None,
        user_id: str | None = None,
    ) -> None:
        self._db = db
        self._user_id = user_id

    def bind(self, *, db: AsyncSession, user_id: str) -> "EditAudioTool":
        """Return a new tool instance bound to a DB session + user.

        Used by the StudioAgent when configuring a per-request runtime.
        """
        return EditAudioTool(db=db, user_id=user_id)

    async def run(self, **kwargs: Any) -> dict:
        clip_id = kwargs.get("clip_id")
        instruction = kwargs.get("instruction")
        if not clip_id or not instruction:
            raise ToolError("edit_audio requires 'clip_id' and 'instruction'")
        if self._db is None or self._user_id is None:
            raise ToolError(
                "edit_audio requires a bound DB session + user_id; "
                "construct via EditAudioTool(db=..., user_id=...) or .bind(...)"
            )

        # Lazy import avoids a circular dependency at module load time
        # (studio_service imports from melo.voice, which is fine, but
        # keeping the indirection makes the tool easier to unit-test).
        from melo.services import studio_service

        try:
            result = await studio_service.apply_edit(
                self._db, clip_id, self._user_id, instruction
            )
            return result
        except Exception as exc:
            # studio_service raises HTTPException-shaped not_found errors;
            # surface them as ToolError so the planner / agent loop can
            # react gracefully.
            raise ToolError(f"edit_audio failed: {exc}") from exc
