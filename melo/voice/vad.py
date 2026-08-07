"""Voice Activity Detection (VAD).

Primary implementation uses Silero VAD via torch. If `torch` or the
Silero model is unavailable, the system transparently falls back to an
energy-based VAD so the rest of the pipeline keeps working in dev
environments without heavyweight ML deps.

Both implementations expose the same async-friendly interface:

    vad = VoiceActivityDetector()
    async for event in vad.feed(stream_of_pcm_bytes):
        ...

Events are `VadEvent(kind=START | END, ts=..., confidence=...)`.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import AsyncIterator

logger = logging.getLogger(__name__)

# Audio frame contract used across the pipeline: 16 kHz, mono, 16-bit PCM.
SAMPLE_RATE = 16000
FRAME_MS = 30  # Silero expects 30 ms frames
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000  # 480 samples
FRAME_BYTES = FRAME_SAMPLES * 2  # 960 bytes per 30 ms frame


class VadState(str, Enum):
    SILENCE = "silence"
    SPEECH = "speech"


@dataclass
class VadEvent:
    kind: str  # "start" | "end"
    ts: float
    confidence: float = 0.0
    state: VadState = VadState.SILENCE


class VoiceActivityDetector:
    """Detects speech start/end on a stream of 16 kHz PCM frames.

    The constructor chooses between Silero and an energy-based fallback
    based on availability. Subclassing is discouraged — instantiate the
    base class and let it pick the right backend.
    """

    def __init__(
        self,
        *,
        threshold: float = 0.5,
        silence_pad_ms: int = 600,
        min_speech_ms: int = 250,
        backend: str | None = None,
        emit_speech_events: bool = True,
    ) -> None:
        self.threshold = threshold
        # Number of trailing silence frames required before declaring SPEECH-END.
        self._silence_pad_frames = max(1, silence_pad_ms // FRAME_MS)
        self._min_speech_frames = max(1, min_speech_ms // FRAME_MS)

        self._backend_name = backend or self._pick_backend()
        self._model = None  # Lazily initialised for the silero backend.
        self._state = VadState.SILENCE
        self._speech_frame_count = 0
        self._silence_run = 0
        self._frame_idx = 0
        # When True, the detector yields a `speech` event for every frame
        # classified as speech (after the start event and before the end
        # event). Callers can use these to build an anti-glitch threshold
        # for barge-in — short bursts of 1-2 frames won't interrupt.
        self._emit_speech_events = emit_speech_events
        # Seed the noise floor with zeros so the first loud frames register
        # as speech even without a silence pre-roll. Without this, a
        # uniformly-loud burst sets the 25th-percentile noise floor to the
        # speech level, the SNR ratio becomes 1.0, and the VAD never fires.
        self._energy_history: deque[float] = deque([0.0] * 16, maxlen=32)

    # -- backend selection -------------------------------------------------

    @staticmethod
    def _pick_backend() -> str:
        try:
            import torch  # noqa: F401
        except Exception:
            return "energy"
        return "silero"

    @property
    def backend(self) -> str:
        return self._backend_name

    # -- public API --------------------------------------------------------

    async def feed(self, audio_stream: AsyncIterator[bytes]) -> AsyncIterator[VadEvent]:
        """Consume the audio stream, yielding START / END events.

        The stream yields arbitrary byte buffers; this method reassembles
        them into fixed-size 30 ms frames.
        """
        buf = bytearray()
        async for chunk in audio_stream:
            buf.extend(chunk)
            while len(buf) >= FRAME_BYTES:
                frame = bytes(buf[:FRAME_BYTES])
                del buf[:FRAME_BYTES]
                self._frame_idx += 1
                event = self._process_frame(frame)
                if event is not None:
                    yield event

        # Flush: if we ended mid-speech, emit a final END so callers can
        # finalise their transcripts.
        if self._state == VadState.SPEECH:
            yield VadEvent(
                kind="end",
                ts=self._frame_idx * FRAME_MS / 1000.0,
                confidence=1.0,
                state=VadState.SILENCE,
            )
            self._state = VadState.SILENCE
            self._speech_frame_count = 0
            self._silence_run = 0

    def _process_frame(self, frame: bytes) -> VadEvent | None:
        score = self._score_frame(frame)
        is_speech = score >= self.threshold

        if self._state == VadState.SILENCE:
            if is_speech:
                self._speech_frame_count = 1
                self._silence_run = 0
                if self._speech_frame_count >= self._min_speech_frames:
                    self._state = VadState.SPEECH
                    return VadEvent(
                        kind="start",
                        ts=self._frame_idx * FRAME_MS / 1000.0,
                        confidence=score,
                        state=VadState.SPEECH,
                    )
            return None

        # state == SPEECH
        if is_speech:
            self._speech_frame_count += 1
            self._silence_run = 0
            if self._emit_speech_events:
                return VadEvent(
                    kind="speech",
                    ts=self._frame_idx * FRAME_MS / 1000.0,
                    confidence=score,
                    state=VadState.SPEECH,
                )
            return None

        self._silence_run += 1
        if self._silence_run >= self._silence_pad_frames:
            self._state = VadState.SILENCE
            ended = VadEvent(
                kind="end",
                ts=self._frame_idx * FRAME_MS / 1000.0,
                confidence=score,
                state=VadState.SILENCE,
            )
            self._speech_frame_count = 0
            self._silence_run = 0
            return ended
        return None

    # -- scoring -----------------------------------------------------------

    def _score_frame(self, frame: bytes) -> float:
        """Return a 0..1 confidence that this frame contains speech."""
        if self._backend_name == "silero":
            try:
                return self._score_silero(frame)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Silero VAD failed (%s); falling back to energy", exc)
                self._backend_name = "energy"
        return self._score_energy(frame)

    def _score_silero(self, frame: bytes) -> float:
        if self._model is None:
            try:
                import torch
                from collections import deque as _deque
                model, utils = torch.hub.load(
                    repo_or_dir="snakers4/silero-vad",
                    model="silero_vad",
                    trust_repo=True,
                )
                self._model = model
                # Silero expects a rolling context window.
                self._silero_context = _deque(maxlen=512)  # type: ignore[attr-defined]
                self._silero_utils = utils
                self._torch = torch
            except Exception as exc:
                raise RuntimeError(f"silero load failed: {exc}") from exc

        import array

        torch = self._torch
        # 16-bit PCM → float32 in [-1, 1]
        samples = array.array("h")
        samples.frombytes(frame)
        if len(samples) < FRAME_SAMPLES:
            samples.extend([0] * (FRAME_SAMPLES - len(samples)))
        audio = torch.tensor(list(samples), dtype=torch.float32) / 32768.0
        self._silero_context.extend(audio.tolist())
        ctx = self._model.get_state_ts() if hasattr(self._model, "get_state_ts") else None
        # Inference
        prob = float(self._model(audio, SAMPLE_RATE).item())
        return max(0.0, min(1.0, prob))

    def _score_energy(self, frame: bytes) -> float:
        """RMS-based energy score normalised against recent noise floor."""
        import array
        import math

        samples = array.array("h")
        samples.frombytes(frame)
        if not samples:
            return 0.0
        rms = math.sqrt(sum(s * s for s in samples) / len(samples)) / 32768.0
        self._energy_history.append(rms)
        if len(self._energy_history) < 4:
            noise = min(self._energy_history) if self._energy_history else 0.0
        else:
            # Use 25th percentile of recent history as noise floor.
            sorted_e = sorted(self._energy_history)
            noise = sorted_e[len(sorted_e) // 4]
        # Normalise: speech typically > 3× noise floor.
        if noise <= 0.0001:
            return min(1.0, rms * 8.0)
        ratio = rms / noise
        if ratio < 1.5:
            return 0.0
        # Map ratio 1.5..4 → 0.1..0.95
        return max(0.0, min(1.0, (ratio - 1.5) / 2.5 * 0.85 + 0.1))


async def frame_pcm_stream(
    audio: AsyncIterator[bytes],
    frame_bytes: int = FRAME_BYTES,
) -> AsyncIterator[bytes]:
    """Helper: re-chunk an arbitrary byte stream into fixed-size PCM frames."""
    buf = bytearray()
    async for chunk in audio:
        buf.extend(chunk)
        while len(buf) >= frame_bytes:
            yield bytes(buf[:frame_bytes])
            del buf[:frame_bytes]
    if buf:
        # Pad final partial frame so downstream consumers don't lose samples.
        buf.extend(b"\x00" * (frame_bytes - len(buf)))
        yield bytes(buf)


async def drain_to_list(ait: AsyncIterator) -> list:
    out: list = []
    async for x in ait:
        out.append(x)
    return out


# Convenience for tests / callers that want to feed raw PCM synchronously.
def make_detector(**kwargs) -> VoiceActivityDetector:
    return VoiceActivityDetector(**kwargs)


# Avoid unused-import warnings for asyncio (kept for forward-compat with
# possible future back-pressure needs).
_ = asyncio
