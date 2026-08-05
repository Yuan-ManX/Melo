"""LLM provider plugin layer.

Mirrors `melo.voice`: pluggable LLM providers behind a unified
`LLMPluginManager`. Concrete implementations live under
`melo/llm/providers/` and are selected via `settings.llm_provider`.

Design notes:
  * All providers stream chat-completion tokens (`AsyncIterator[str]`).
  * HTTP-based providers (OpenAI / Anthropic) use `httpx.AsyncClient`
    directly — no SDK dependency — so the surface stays minimal.
  * Missing API keys raise `LLMProviderUnavailable` on first use rather
    than at import time, mirroring the voice layer's behaviour.
"""

from melo.llm.base import (
    ChatMessage,
    LLMOptions,
    LLMProvider,
    LLMProviderUnavailable,
    MeloLLMError,
)
from melo.llm.manager import LLMPluginManager, get_llm_manager, reset_llm_manager

__all__ = [
    "ChatMessage",
    "LLMOptions",
    "LLMProvider",
    "LLMProviderUnavailable",
    "MeloLLMError",
    "LLMPluginManager",
    "get_llm_manager",
    "reset_llm_manager",
]
