"""Abstract interfaces for voice model providers.

Providers are pluggable: implementations live under `melo/voice/asr`,
`melo/voice/tts`, and `melo/voice/clone`; a `VoicePluginManager`
(`manager.py`) routes requests to the active one via settings.

All providers support streaming where applicable; non-streaming
implementations still expose the async-iterator contract, yielding a
single chunk.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator


class MeloVoiceError(Exception):
    """Base error for the voice layer."""


class VoiceProviderUnavailable(MeloVoiceError):
    """Raised when a provider's runtime / model is not installed.

    Providers should raise this on first use (not at import time) so
    that the rest of the application stays healthy.
    """


@dataclass
class TTSOptions:
    """Per-request TTS options.

    Providers may ignore unsupported fields.
    """

    voice_id: str | None = None
    language: str | None = None
    speed: float = 1.0
    pitch: float = 1.0
    sample_rate: int = 22050
    metadata: dict = field(default_factory=dict)


@dataclass
class CloneResult:
    """Result of a voice cloning operation."""

    voice_id: str
    provider: str
    sample_url: str | None = None
    metadata: dict = field(default_factory=dict)


class ASRProvider(ABC):
    """Streaming speech-to-text provider."""

    name: str = "abstract"

    @abstractmethod
    async def transcribe_stream(
        self,
        audio_stream: AsyncIterator[bytes],
    ) -> AsyncIterator[str]:
        """Yield partial transcription strings as audio streams in.

        Implementations should yield intermediate tokens so the
        caller can render `asr_partial` messages; the final yield (or
        stream end) represents the `asr_final` text.
        """
        ...
        # This async-iterator body never executes — it exists so the
        # signature is a valid async generator from the type checker's
        # perspective. Subclasses override it.
        yield ""  # pragma: no cover


class TTSProvider(ABC):
    """Streaming text-to-speech provider."""

    name: str = "abstract"

    @abstractmethod
    async def synthesize_stream(
        self,
        text: str,
        voice_id: str | None = None,
        options: TTSOptions | None = None,
    ) -> AsyncIterator[bytes]:
        """Yield raw audio bytes (PCM / WAV / MP3 per provider).

        Caller is responsible for chunking frames for the wire protocol.
        """
        ...
        yield b""  # pragma: no cover


class CloneProvider(ABC):
    """Voice cloning provider."""

    name: str = "abstract"

    @abstractmethod
    async def clone(
        self,
        sample_url: str,
        name: str,
    ) -> CloneResult:
        """Create a new voice from `sample_url`, return its voice_id."""
        ...
