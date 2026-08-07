"""Stub ASR provider — zero-dependency dev/test fallback.

Echoes a canned phrase so the rest of the pipeline (VAD → ASR → LLM →
TTS → WS transport) can be exercised end-to-end without any ASR
dependencies installed. The "transcript" is deterministic per text
input hash so test assertions can be made stable.

Activate by setting `ASR_PROVIDER=stub` in `.env` (or registering
directly via `VoicePluginManager.register_asr("stub", StubASR())`).
"""

from __future__ import annotations

import hashlib
import logging
from typing import AsyncIterator

from melo.voice.base import ASRProvider

logger = logging.getLogger(__name__)


class StubASR(ASRProvider):
    """Dev/test ASR that yields a canned transcript per session."""

    name = "stub"

    def __init__(self, *, fixed_phrase: str = "[stub transcription]") -> None:
        self._fixed_phrase = fixed_phrase

    async def transcribe_stream(
        self,
        audio_stream: AsyncIterator[bytes],
    ) -> AsyncIterator[str]:
        # Drain the audio (no model) and compute a short hash so each
        # distinct input yields a distinct-looking transcript for tests.
        total = 0
        sample = b""
        async for chunk in audio_stream:
            total += len(chunk)
            if len(sample) < 64:
                sample += chunk[: 64 - len(sample)]
        digest = hashlib.sha1(sample or b"").hexdigest()[:6]
        logger.debug("StubASR drained %d bytes (digest=%s)", total, digest)
        # Emit one partial then a final so the runtime emits the
        # full ASR state machine.
        partial = self._fixed_phrase
        final = f"{self._fixed_phrase} (stub#{digest})"
        if partial:
            yield partial
        yield final
