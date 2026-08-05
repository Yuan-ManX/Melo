"""Abstract interfaces for LLM providers.

Mirrors `melo.voice.base` so the LLM layer feels consistent with the
voice plugin layer. The runtime consumes a `LLMProvider` through
`stream_chat` which yields incremental text tokens.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator


class MeloLLMError(Exception):
    """Base error for the LLM layer."""


class LLMProviderUnavailable(MeloLLMError):
    """Raised when a provider's API key is missing or the SDK is absent.

    Providers raise this on first use (not at import) so the rest of
    the application stays healthy even if no LLM is configured.
    """


@dataclass
class ChatMessage:
    """A single chat message.

    `role` follows the OpenAI convention: `"system" | "user" |
    "assistant" | "tool"`. `content` is plain text for now —
    multimodal content can land later via a `parts: list` field.
    """

    role: str
    content: str
    name: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class LLMOptions:
    """Per-request LLM options.

    Providers may ignore unsupported fields. `tools` and `tool_choice`
    are intentionally opaque dicts so the layer stays neutral across
    tool-calling schemas.
    """

    model: str | None = None
    temperature: float = 0.7
    max_tokens: int | None = None
    top_p: float = 1.0
    stop: list[str] | None = None
    tools: list[dict] | None = None
    tool_choice: str | dict | None = None
    metadata: dict = field(default_factory=dict)


class LLMProvider(ABC):
    """Streaming chat-completion provider.

    Implementations MUST yield incremental text tokens via
    `stream_chat`. Non-streaming responses should still yield a single
    chunk so callers can treat all providers uniformly.
    """

    name: str = "abstract"

    @abstractmethod
    async def stream_chat(
        self,
        messages: list[ChatMessage],
        *,
        options: LLMOptions | None = None,
    ) -> AsyncIterator[str]:
        """Yield incremental text tokens for the chat completion."""
        ...
        yield ""  # pragma: no cover — satisfies async-generator typing
