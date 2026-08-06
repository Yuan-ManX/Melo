"""Stub voice style-transfer provider — returns the input unchanged.

No actual model is loaded; this exists so the rest of the app can
exercise the style-transfer flow end-to-end without external dependencies.
RVC-backed style transfer implements the same provider interface.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from melo.voice.base import MeloVoiceError


class StyleProviderUnavailable(MeloVoiceError):
    """Raised when a style-transfer provider's runtime / model is not installed."""


@dataclass
class StyleResult:
    """Result of a voice style-transfer operation."""

    voice_id: str
    provider: str
    sample_url: str | None = None
    metadata: dict = field(default_factory=dict)


class StubStyleProvider:
    """Pass-through style provider — returns the input voice id unchanged."""

    name = "stub"

    async def transfer(
        self,
        voice_id: str,
        target_style: str,
    ) -> StyleResult:
        return StyleResult(
            voice_id=voice_id,
            provider=self.name,
            sample_url=None,
            metadata={"target_style": target_style, "stub": True},
        )
