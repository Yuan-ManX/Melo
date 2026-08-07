"""Local Piper TTS provider.

Piper is a fast, lightweight ONNX-based neural TTS engine. This provider
wraps `piper-tts` if available; otherwise every call raises
`VoiceProviderUnavailable`. The module still imports cleanly so the rest
of the application stays healthy in environments without piper.
"""

from __future__ import annotations

import asyncio
import io
import logging
from typing import AsyncIterator

from melo.voice.base import TTSOptions, TTSProvider, VoiceProviderUnavailable

logger = logging.getLogger(__name__)


class PiperLocalTTS(TTSProvider):
    """Streaming TTS backed by Piper.

    Piper synthesises sentence-by-sentence, so streaming here means:
      * Split input text on sentence boundaries.
      * Synthesise each sentence off the event loop.
      * Yield the resulting WAV/PCM bytes per sentence.
    """

    name = "piper_local"

    def __init__(
        self,
        model_path: str | None = None,
        config_path: str | None = None,
        default_voice_id: str | None = None,
    ) -> None:
        self.model_path = model_path
        self.config_path = config_path
        self.default_voice_id = default_voice_id
        self._voice = None  # Lazy-loaded.

    # -- lazy load --------------------------------------------------------

    def _ensure_voice(self) -> None:
        if self._voice is not None:
            return
        try:
            import piper  # type: ignore
        except Exception as exc:  # pragma: no cover - import guard
            raise VoiceProviderUnavailable(
                "piper is not installed. Install with: pip install piper-tts"
            ) from exc
        if not self.model_path:
            raise VoiceProviderUnavailable(
                "PiperTTS requires PIPER_MODEL_PATH to be set."
            )
        try:
            self._voice = piper.PiperVoice.load(
                self.model_path,
                config_path=self.config_path,
            )
        except Exception as exc:
            raise VoiceProviderUnavailable(
                f"Failed to load Piper model '{self.model_path}': {exc}"
            ) from exc

    # -- TTSProvider contract ---------------------------------------------

    async def synthesize_stream(
        self,
        text: str,
        voice_id: str | None = None,
        options: TTSOptions | None = None,
    ) -> AsyncIterator[bytes]:
        self._ensure_voice()
        assert self._voice is not None
        opts = options or TTSOptions(voice_id=voice_id)

        # Split into sentence-ish chunks for streaming output.
        sentences = [s.strip() for s in text.split(". ") if s.strip()]
        if not sentences:
            sentences = [text.strip()]
        # Re-append trailing punctuation that the split removed.
        sentences = [s + ("." if not s.endswith((".", "!", "?")) else "") for s in sentences]

        for sentence in sentences:
            audio_bytes = await self._synthesize_sentence(sentence, opts)
            if audio_bytes:
                yield audio_bytes

    # -- internal helpers --------------------------------------------------

    async def _synthesize_sentence(self, sentence: str, opts: TTSOptions) -> bytes:
        return await asyncio.to_thread(self._run_piper, sentence, opts)

    def _run_piper(self, sentence: str, opts: TTSOptions) -> bytes:
        assert self._voice is not None
        try:
            out = io.BytesIO()
            # Piper's synth API writes WAV bytes to a file-like object.
            self._voice.synthesize(
                sentence,
                out,
                length_scale=1.0 / max(0.5, min(2.0, opts.speed)),
            )
            return out.getvalue()
        except Exception as exc:
            logger.warning("Piper synthesis error: %s", exc)
            return b""
