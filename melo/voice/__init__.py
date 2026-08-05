"""Voice model plugin layer.

Provides pluggable ASR / TTS / Clone providers behind a unified
`VoicePluginManager`. All providers degrade gracefully — if a model
runtime (faster-whisper / piper / torch) is not installed, the provider
raises a clear `VoiceProviderUnavailable` error on first use rather than
crashing the application at import time.
"""

from melo.voice.base import (
    CloneProvider,
    CloneResult,
    MeloVoiceError,
    TTSOptions,
    TTSProvider,
    ASRProvider,
    VoiceProviderUnavailable,
)
from melo.voice.manager import VoicePluginManager, get_voice_manager

__all__ = [
    "ASRProvider",
    "TTSProvider",
    "CloneProvider",
    "TTSOptions",
    "CloneResult",
    "MeloVoiceError",
    "VoiceProviderUnavailable",
    "VoicePluginManager",
    "get_voice_manager",
]
