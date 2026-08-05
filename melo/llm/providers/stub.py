"""Stub LLM provider — returns a fixed response.

Kept for dev/test parity with the stub behaviour. Activate via
`LLM_PROVIDER=stub` (or by leaving the default when no API key is
configured). The stub emits its text in word-sized chunks so callers
exercise the streaming path without a network round-trip.
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

from melo.llm.base import ChatMessage, LLMOptions, LLMProvider


class StubLLM(LLMProvider):
    """Deterministic stub LLM."""

    name = "stub"

    DEFAULT_TEXT = "I heard you."

    def __init__(self, *, response: str | None = None, chunk_delay: float = 0.02) -> None:
        self._response = response or self.DEFAULT_TEXT
        self._chunk_delay = chunk_delay

    async def stream_chat(
        self,
        messages: list[ChatMessage],
        *,
        options: LLMOptions | None = None,
    ) -> AsyncIterator[str]:
        words = self._response.split(" ")
        for i, w in enumerate(words):
            yield w if i == 0 else " " + w
            if self._chunk_delay > 0:
                await asyncio.sleep(self._chunk_delay)
