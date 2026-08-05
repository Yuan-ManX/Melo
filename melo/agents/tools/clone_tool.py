"""clone_voice tool — voice cloning via the voice plugin manager."""

from __future__ import annotations

import logging
from typing import Any

from melo.agents.tools.registry import Tool, ToolError
from melo.voice.manager import get_voice_manager

logger = logging.getLogger(__name__)


class CloneVoiceTool(Tool):
    """Clone a voice from a sample URL.

    Returns the new voice_id (provider-scoped) plus provider metadata.
    """

    name = "clone_voice"
    description = (
        "Clone a voice from an audio sample. Args: sample_url (str), "
        "name (str). Returns: {voice_id, provider}."
    )

    async def run(self, **kwargs: Any) -> dict:
        sample_url = kwargs.get("sample_url")
        name = kwargs.get("name")
        if not sample_url or not name:
            raise ToolError("clone_voice requires 'sample_url' and 'name'")

        clone = get_voice_manager().get_clone()
        result = await clone.clone(sample_url=sample_url, name=name)
        return {
            "voice_id": result.voice_id,
            "provider": result.provider,
            "sample_url": result.sample_url,
        }
