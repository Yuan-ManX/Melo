"""Tool registry — name → async callable mapping.

Tools are simple: a `name`, a `description` (for LLM tool prompts),
and an async `run(**kwargs)` method. The registry is just a dict with
helpers for declarative registration via `@register`.

Melo deliberately keeps a JSON-schema validator out of this layer:
built-in tools are called directly by the planner / agent, and
schema validation lives with the LLM tool-call emission path.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class ToolError(Exception):
    """Raised when a tool fails to execute."""


class Tool(ABC):
    """Abstract tool base class."""

    name: str = "abstract"
    description: str = ""

    @abstractmethod
    async def run(self, **kwargs: Any) -> Any:
        """Execute the tool with keyword arguments. Return a JSON-able result."""
        ...


class ToolRegistry:
    """Holds tools by name; dispatches `execute()` calls."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if not tool.name or tool.name == "abstract":
            raise ToolError("Tool must define a non-empty name")
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def has(self, name: str) -> bool:
        return name in self._tools

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise ToolError(f"Unknown tool: {name}")
        return self._tools[name]

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def schemas(self) -> list[dict]:
        """Lightweight schema descriptions for LLM tool prompts."""
        return [
            {"name": t.name, "description": t.description}
            for t in self._tools.values()
        ]

    async def execute(self, name: str, **kwargs: Any) -> Any:
        tool = self.get(name)
        try:
            return await tool.run(**kwargs)
        except ToolError:
            raise
        except Exception as exc:
            raise ToolError(f"{name} failed: {exc}") from exc


def default_registry() -> ToolRegistry:
    """Build a registry pre-populated with the built-in tools.

    Each tool lazily resolves its voice / clone provider via the
    singleton managers, so missing models surface their error on
    first use rather than at registry construction.
    """
    from melo.agents.tools.clone_tool import CloneVoiceTool
    from melo.agents.tools.edit_tool import EditAudioTool
    from melo.agents.tools.mcp_tool import CallMCPTool
    from melo.agents.tools.tts_tool import GenerateSpeechTool

    reg = ToolRegistry()
    reg.register(GenerateSpeechTool())
    reg.register(CloneVoiceTool())
    reg.register(EditAudioTool())
    reg.register(CallMCPTool())
    return reg


__all__ = ["Tool", "ToolError", "ToolRegistry", "default_registry"]
