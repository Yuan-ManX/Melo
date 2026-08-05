"""generate_speech tool — TTS via the voice plugin manager."""

from __future__ import annotations

import logging
from typing import Any

from melo.agents.tools.registry import Tool, ToolError
from melo.voice.base import TTSOptions
from melo.voice.manager import get_voice_manager

logger = logging.getLogger(__name__)


class GenerateSpeechTool(Tool):
    """Synthesize speech for the given text.

    Returns a dict describing the synthesized audio (provider name +
    byte length). The actual audio bytes are streamed to the caller's
    sink (WebSocket / file) by the TTS provider itself; this tool is
    used when an agent wants to *trigger* synthesis as part of a plan.
    """

    name = "generate_speech"
    description = (
        "Generate speech audio from text. Args: text (str), "
        "voice_id (str, optional), speed (float, default 1.0)."
    )

    async def run(self, **kwargs: Any) -> dict:
        text = kwargs.get("text")
        if not text:
            raise ToolError("generate_speech requires 'text'")
        voice_id = kwargs.get("voice_id")
        speed = float(kwargs.get("speed", 1.0))

        tts = get_voice_manager().get_tts()
        options = TTSOptions(voice_id=voice_id, speed=speed)

        chunks: list[bytes] = []
        async for chunk in tts.synthesize_stream(
            text, voice_id=voice_id, options=options
        ):
            chunks.append(chunk)
        audio = b"".join(chunks)
        return {
            "provider": tts.name,
            "voice_id": voice_id,
            "bytes": len(audio),
            "text": text,
        }
