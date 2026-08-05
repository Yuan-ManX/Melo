"""LLM plugin manager.

Holds the registry of LLM providers and selects the active one based on
`melo.config.settings.llm_provider`. Mirrors `melo.voice.manager`.

Selection precedence (highest first):
  1. Explicit `name` argument to `get_llm(name=...)`.
  2. A provider registered under `settings.llm_provider`.
  3. Auto-built default provider for the configured name.

If no API key is configured for the chosen provider, an
`LLMProviderUnavailable` is raised on first use — not at construction —
so the application boots fine without keys.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

from melo.config import settings
from melo.llm.base import (
    LLMProvider,
    LLMProviderUnavailable,
    MeloLLMError,
)

logger = logging.getLogger(__name__)


class LLMPluginManager:
    """Registry + selector for LLM providers."""

    def __init__(self) -> None:
        self._providers: dict[str, LLMProvider] = {}
        self._default: Optional[LLMProvider] = None
        self._lock = threading.Lock()

    # -- registration ------------------------------------------------------

    def register(self, name: str, provider: LLMProvider) -> None:
        self._providers[name] = provider

    # alias kept consistent with `VoicePluginManager.register_*`
    def register_provider(self, name: str, provider: LLMProvider) -> None:
        self._providers[name] = provider

    # -- lookup ------------------------------------------------------------

    def get(self, name: str | None = None) -> LLMProvider:
        if name and name in self._providers:
            return self._providers[name]
        with self._lock:
            if self._default is None:
                self._default = self._build_default()
            return self._default

    # -- status ------------------------------------------------------------

    def available(self) -> list[str]:
        return list(self._providers.keys())

    # -- defaults ----------------------------------------------------------

    def _build_default(self) -> LLMProvider:
        name = settings.llm_provider.lower()
        if name in self._providers:
            return self._providers[name]
        if name == "stub":
            from melo.llm.providers.stub import StubLLM

            return StubLLM()
        if name == "openai":
            from melo.llm.providers.openai_provider import OpenAILLM

            return OpenAILLM(
                api_key=settings.openai_api_key,
                default_model=settings.openai_default_model,
            )
        if name == "anthropic":
            from melo.llm.providers.anthropic_provider import AnthropicLLM

            return AnthropicLLM(
                api_key=settings.anthropic_api_key,
                default_model=settings.anthropic_default_model,
            )
        raise MeloLLMError(
            f"Unknown LLM provider '{name}'. Register it or set LLM_PROVIDER."
        )


# ---------------------------------------------------------------------------
# Process-wide singleton. Created lazily on first access.
# ---------------------------------------------------------------------------
_manager: LLMPluginManager | None = None
_manager_lock = threading.Lock()


def get_llm_manager() -> LLMPluginManager:
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = LLMPluginManager()
    return _manager


def reset_llm_manager() -> None:
    """Drop the singleton — primarily for tests."""
    global _manager
    _manager = None


__all__ = [
    "LLMPluginManager",
    "get_llm_manager",
    "reset_llm_manager",
    "LLMProviderUnavailable",
]
