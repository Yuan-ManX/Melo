"""Voice plugin manager.

Holds the registry of ASR / TTS / Clone providers and routes lookups
based on `melo.config.settings`. Exposes a process-wide singleton via
`get_voice_manager()`.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

from melo.config import settings
from melo.voice.base import (
    ASRProvider,
    CloneProvider,
    MeloVoiceError,
    TTSProvider,
)

logger = logging.getLogger(__name__)


class VoicePluginManager:
    """Registry + selector for voice providers."""

    def __init__(self) -> None:
        self._asr: dict[str, ASRProvider] = {}
        self._tts: dict[str, TTSProvider] = {}
        self._clone: dict[str, CloneProvider] = {}
        # Lazily-instantiated default providers (created on first use).
        self._default_asr: Optional[ASRProvider] = None
        self._default_tts: Optional[TTSProvider] = None
        self._default_clone: Optional[CloneProvider] = None
        self._lock = threading.Lock()

    # -- registration ------------------------------------------------------

    def register_asr(self, name: str, provider: ASRProvider) -> None:
        self._asr[name] = provider

    def register_tts(self, name: str, provider: TTSProvider) -> None:
        self._tts[name] = provider

    def register_clone(self, name: str, provider: CloneProvider) -> None:
        self._clone[name] = provider

    # -- lookup ------------------------------------------------------------

    def get_asr(self, name: str | None = None) -> ASRProvider:
        if name and name in self._asr:
            return self._asr[name]
        with self._lock:
            if self._default_asr is None:
                self._default_asr = self._build_default_asr()
            return self._default_asr

    def get_tts(self, name: str | None = None) -> TTSProvider:
        if name and name in self._tts:
            return self._tts[name]
        with self._lock:
            if self._default_tts is None:
                self._default_tts = self._build_default_tts()
            return self._default_tts

    def get_clone(self, name: str | None = None) -> CloneProvider:
        if name and name in self._clone:
            return self._clone[name]
        with self._lock:
            if self._default_clone is None:
                self._default_clone = self._build_default_clone()
            return self._default_clone

    # -- status ------------------------------------------------------------

    def available_asr(self) -> list[str]:
        return list(self._asr.keys())

    def available_tts(self) -> list[str]:
        return list(self._tts.keys())

    def available_clone(self) -> list[str]:
        return list(self._clone.keys())

    # -- defaults ----------------------------------------------------------

    def _build_default_asr(self) -> ASRProvider:
        name = settings.asr_provider.lower()
        if name in self._asr:
            return self._asr[name]
        if name == "whisper_local":
            from melo.voice.asr.whisper_local import WhisperLocalASR

            return WhisperLocalASR(
                model_size=getattr(settings, "whisper_model_size", "base"),
                language=getattr(settings, "asr_language", None),
            )
        if name == "openai":
            from melo.voice.asr.openai_provider import OpenAIWhisperASR

            return OpenAIWhisperASR(
                api_key=settings.openai_api_key,
                default_model="whisper-1",
                base_url=settings.openai_base_url,
                language=getattr(settings, "asr_language", None),
            )
        if name == "deepgram":
            from melo.voice.asr.deepgram_provider import DeepgramASR

            return DeepgramASR(
                api_key=settings.deepgram_api_key,
                language=getattr(settings, "asr_language", "en") or "en",
            )
        if name == "stub":
            from melo.voice.asr.stub_provider import StubASR

            return StubASR()
        raise MeloVoiceError(
            f"Unknown ASR provider '{name}'. Register it or set ASR_PROVIDER "
            f"(whisper_local | openai | deepgram | stub)."
        )

    def _build_default_tts(self) -> TTSProvider:
        name = settings.tts_provider.lower()
        if name in self._tts:
            return self._tts[name]
        if name == "piper_local":
            from melo.voice.tts.piper_local import PiperLocalTTS

            return PiperLocalTTS(
                model_path=getattr(settings, "piper_model_path", None),
                default_voice_id=getattr(settings, "piper_default_voice", None),
            )
        if name == "openai":
            from melo.voice.tts.openai_provider import OpenAITTS

            return OpenAITTS(
                api_key=settings.openai_api_key,
                default_model="tts-1",
                base_url=settings.openai_base_url,
            )
        if name == "elevenlabs":
            from melo.voice.tts.elevenlabs_provider import ElevenLabsTTS

            return ElevenLabsTTS(
                api_key=settings.elevenlabs_api_key,
                default_voice_id=getattr(settings, "piper_default_voice", None)
                or "21m00Tcm4TlvDq8ikWAM",
            )
        if name == "stub":
            from melo.voice.tts.stub_provider import StubTTS

            return StubTTS()
        raise MeloVoiceError(
            f"Unknown TTS provider '{name}'. Register it or set TTS_PROVIDER "
            f"(piper_local | openai | elevenlabs | stub)."
        )

    def _build_default_clone(self) -> CloneProvider:
        name = settings.clone_provider.lower()
        if name in self._clone:
            return self._clone[name]
        raise MeloVoiceError(
            f"Unknown Clone provider '{name}'. Register it or set CLONE_PROVIDER."
        )


# ---------------------------------------------------------------------------
# Process-wide singleton. Created lazily on first access.
# ---------------------------------------------------------------------------
_manager: VoicePluginManager | None = None
_manager_lock = threading.Lock()


def get_voice_manager() -> VoicePluginManager:
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = VoicePluginManager()
    return _manager


def reset_voice_manager() -> None:
    """Drop the singleton — primarily for tests."""
    global _manager
    _manager = None
