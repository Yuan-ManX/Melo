"""Memory tools — let the agent read and write its long-term memory.

The agentic tool loop gives the LLM two new levers over its own
three-tier memory system:

  * `recall_memory` — pull relevant facts back out of long-term storage
    so the model can ground its answer in what it already knows.
  * `remember` — persist a new fact so it survives across turns and
    sessions.

Both tools are bound to a `MemorySystem` at construction time. When
constructed without one (e.g. by the shared default registry), they
raise a clear `ToolError` on first use so the caller knows to bind a
memory instance — mirroring how `edit_audio` handles its DB session.
"""

from __future__ import annotations

import logging
from typing import Any

from melo.agents.tools.registry import Tool, ToolError

logger = logging.getLogger(__name__)


class RecallMemoryTool(Tool):
    """Retrieve facts relevant to a query from long-term memory."""

    name = "recall_memory"
    description = (
        "检索长期记忆中的相关事实. Search long-term memory for facts "
        "matching a query. Args: query (str), k (int, optional, default 5). "
        "Returns a list of {id, content, role, score} or an empty recall."
    )

    def __init__(self, *, memory=None) -> None:
        self._memory = memory

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        query = kwargs.get("query")
        if not query:
            raise ToolError("recall_memory requires a 'query'")
        k = int(kwargs.get("k", 5))
        if self._memory is None:
            raise ToolError(
                "recall_memory requires a bound MemorySystem; "
                "construct via RecallMemoryTool(memory=...) "
                "or via a StudioAgent that owns a memory"
            )
        try:
            facts = await self._memory.recall(query, k=k)
        except Exception as exc:
            raise ToolError(f"recall_memory failed: {exc}") from exc
        if not facts:
            return {"recalled": 0, "facts": []}
        return {
            "recalled": len(facts),
            "facts": [
                {
                    "id": f.id,
                    "content": f.content,
                    "role": getattr(f, "role", "user"),
                    "score": getattr(f, "score", 0.0),
                }
                for f in facts
            ],
        }


class RememberTool(Tool):
    """Persist a single fact into long-term memory."""

    name = "remember"
    description = (
        "将一条事实存入长期记忆. Store a fact into long-term memory. "
        "Args: content (str), role (str, optional, default 'user'). "
        "Returns {stored: true, id}."
    )

    def __init__(self, *, memory=None) -> None:
        self._memory = memory

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        content = kwargs.get("content")
        if not content:
            raise ToolError("remember requires 'content'")
        role = kwargs.get("role", "user")
        if self._memory is None:
            raise ToolError(
                "remember requires a bound MemorySystem; "
                "construct via RememberTool(memory=...) "
                "or via a StudioAgent that owns a memory"
            )
        try:
            fact = await self._memory.remember(content, role=role)
        except Exception as exc:
            raise ToolError(f"remember failed: {exc}") from exc
        return {"stored": True, "id": fact.id}