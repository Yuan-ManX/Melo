"""Local Whisper ASR via `faster-whisper`.

If `faster_whisper` is not installed (or the model cannot be loaded),
every call raises `VoiceProviderUnavailable` with a clear message. The
class still imports cleanly so the rest of the app stays healthy.
"""

from __future__ import annotations

import asyncio
import io
import logging
import wave
from typing import AsyncIterator

from melo.voice.base import ASRProvider, VoiceProviderUnavailable
from melo.voice.vad import FRAME_BYTES, FRAME_MS, SAMPLE_RATE

logger = logging.getLogger(__name__)


class WhisperLocalASR(ASRProvider):
    """Streaming ASR backed by `faster-whisper`.

    Implementation note: faster-whisper itself is not natively streaming
    — each segment arrives as the model decodes. We bridge by:

      * Accumulating incoming PCM frames into a rolling buffer.
      * Periodically running transcription and yielding only newly
        generated segments as `asr_partial` text.
      * On stream close, performing a final transcription and yielding
        the consolidated text (the caller treats this as `asr_final`).
    """

    name = "whisper_local"

    def __init__(
        self,
        model_size: str = "base",
        device: str = "cpu",
        compute_type: str = "int8",
        language: str | None = None,
        min_buffer_ms: int = 1200,
    ) -> None:
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.language = language
        self._min_buffer_bytes = SAMPLE_RATE * 2 * (min_buffer_ms // 1000)
        self._model = None  # Lazy-loaded on first call.

    # -- lazy model load ---------------------------------------------------

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        try:
            from faster_whisper import WhisperModel
        except Exception as exc:  # pragma: no cover - import guard
            raise VoiceProviderUnavailable(
                "faster_whisper is not installed. "
                "Install with: pip install faster-whisper"
            ) from exc
        try:
            self._model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
            )
        except Exception as exc:
            raise VoiceProviderUnavailable(
                f"Failed to load Whisper model '{self.model_size}': {exc}"
            ) from exc

    # -- ASRProvider contract ---------------------------------------------

    async def transcribe_stream(
        self,
        audio_stream: AsyncIterator[bytes],
    ) -> AsyncIterator[str]:
        self._ensure_model()
        assert self._model is not None

        buffer = bytearray()
        last_text = ""
        async for chunk in audio_stream:
            buffer.extend(chunk)
            # Wait until we have enough audio to do a useful incremental pass.
            if len(buffer) < self._min_buffer_bytes:
                continue
            partial = await self._transcribe_bytes(bytes(buffer), final=False)
            if partial and partial != last_text:
                last_text = partial
                yield partial

        if buffer:
            final_text = await self._transcribe_bytes(bytes(buffer), final=True)
            if final_text:
                yield final_text

    # -- internal helpers --------------------------------------------------

    async def _transcribe_bytes(self, pcm: bytes, *, final: bool) -> str:
        """Run transcription off the event loop to avoid blocking."""
        wav_bytes = self._pcm_to_wav(pcm)
        return await asyncio.to_thread(self._run_whisper, wav_bytes, final)

    def _run_whisper(self, wav_bytes: bytes, final: bool) -> str:
        assert self._model is not None
        try:
            segments, _info = self._model.transcribe(
                io.BytesIO(wav_bytes),
                language=self.language,
                vad_filter=True,
                # Use beam_size=1 for low latency on partial passes.
                beam_size=1 if not final else 5,
            )
            # `segments` is a generator; force materialisation.
            text = " ".join(seg.text.strip() for seg in segments).strip()
            return text
        except Exception as exc:
            logger.warning("Whisper transcription error: %s", exc)
            return ""

    @staticmethod
    def _pcm_to_wav(pcm: bytes) -> bytes:
        """Wrap raw 16-bit PCM into a WAV container."""
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(SAMPLE_RATE)
            wav.writeframes(pcm)
        return buf.getvalue()


# ---------------------------------------------------------------------------
# Frame-size constant re-exported for convenience; consumers that want to
# size their WebSocket payload chunking can read it from here.
# ---------------------------------------------------------------------------
_ = (FRAME_BYTES, FRAME_MS)
