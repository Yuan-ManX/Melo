"""transcribe_audio tool — speech-to-text via the ASR plugin manager.

Resolves an audio source (a studio clip_id or a raw audio_url), reads
the bytes, streams them to the active ASR provider, and returns the
transcript. The DB session + user_id are bound at construction; without
a session it raises `ToolError`.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from melo.agents.tools.registry import Tool, ToolError
from melo.voice.manager import get_voice_manager

logger = logging.getLogger(__name__)

# Bytes per chunk when feeding the audio stream into the ASR provider.
# Small enough to exercise the streaming contract, large enough to
# avoid per-chunk overhead dominating the test path.
_AUDIO_CHUNK_SIZE = 4096


async def _iter_file_bytes(path: Path) -> AsyncIterator[bytes]:
    """Yield a file's bytes in fixed-size chunks as an async stream."""
    data = path.read_bytes()
    if not data:
        return
    for i in range(0, len(data), _AUDIO_CHUNK_SIZE):
        yield data[i : i + _AUDIO_CHUNK_SIZE]


class TranscribeAudioTool(Tool):
    """Transcribe an audio clip (or raw audio file) to text via ASR."""

    name = "transcribe_audio"
    description = (
        "Transcribe speech in an audio clip to text. Args: "
        "clip_id (str, preferred — resolves the clip's audio_url) or "
        "audio_url (str, e.g. '/audio/foo.wav'). Returns: "
        "{text, provider, clip_id?, audio_url?}."
    )

    def __init__(
        self,
        *,
        db: AsyncSession | None = None,
        user_id: str | None = None,
    ) -> None:
        self._db = db
        self._user_id = user_id

    def bind(self, *, db: AsyncSession, user_id: str) -> "TranscribeAudioTool":
        """Return a new tool instance bound to a DB session + user."""
        return TranscribeAudioTool(db=db, user_id=user_id)

    async def run(self, **kwargs: Any) -> dict:
        clip_id = kwargs.get("clip_id")
        audio_url = kwargs.get("audio_url")
        if not clip_id and not audio_url:
            raise ToolError(
                "transcribe_audio requires 'clip_id' or 'audio_url'"
            )
        if self._db is None or self._user_id is None:
            raise ToolError(
                "transcribe_audio requires a bound DB session + user_id; "
                "construct via TranscribeAudioTool(db=..., user_id=...) "
                "or .bind(...)"
            )

        # Resolve the audio source to a disk path + record provenance.
        path: Path
        result: dict[str, Any] = {}
        if clip_id:
            # Lazy import avoids a circular dependency at module load time.
            from melo.services import studio_service

            clip = await studio_service.get_clip(self._db, clip_id, self._user_id)
            if not clip.audio_url:
                raise ToolError(
                    f"clip {clip_id} has no audio_url; generate audio first"
                )
            path = _audio_path_from_url(clip.audio_url)
            result["clip_id"] = clip_id
            result["audio_url"] = clip.audio_url
        else:
            path = _audio_path_from_url(audio_url)
            result["audio_url"] = audio_url

        if not path.exists():
            raise ToolError(f"audio file not found on disk: {path}")

        asr = get_voice_manager().get_asr()
        # Drain the ASR stream — the final yielded value is the canonical
        # transcript. Intermediate yields are partials (kept for debugging).
        final_text = ""
        async for chunk in asr.transcribe_stream(_iter_file_bytes(path)):
            if chunk:
                final_text = chunk
        result["text"] = final_text
        result["provider"] = asr.name
        return result


def _audio_path_from_url(audio_url: str) -> Path:
    """Resolve a '/audio/<file>' URL back to its on-disk cache path."""
    from melo.services.studio_service import AUDIO_CACHE_DIR

    filename = audio_url.rsplit("/", 1)[-1]
    return AUDIO_CACHE_DIR / filename
