"""BaseAgent — abstract base class for Melo agents.

An `Agent` is the *personality + configuration* layer that sits on top
of the `VoiceAgentRuntime` (the *transport* layer). It owns:

  * `system_prompt` — personality / persona instructions
  * `llm_options` — model / temperature / token budget
  * `memory` — three-tier memory system (short / working / long)
  * `tools` — tool registry this agent is allowed to invoke

Subclasses (VoiceAgent, StudioAgent, BuilderAgent) override
`build_system_prompt()` to inject persona-specific instructions, and
optionally override `wire_runtime()` to attach extra hooks.

The runtime itself is agnostic to agent identity — `BaseAgent`
configures a runtime and hands it back to the caller (typically the
WebSocket handler). This keeps the runtime reusable for tests.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from melo.agents.memory import MemorySystem
from melo.agents.runtime import RuntimeConfig, VoiceAgentRuntime
from melo.agents.tools.registry import ToolRegistry
from melo.llm.base import LLMOptions

if TYPE_CHECKING:
    from melo.models.db import Agent as AgentRow


@dataclass
class AgentConfig:
    """Knobs that define an agent's behaviour."""

    name: str = "Melo"
    persona: str = ""
    system_prompt: str = ""
    voice_id: str | None = None
    llm_options: LLMOptions = field(default_factory=LLMOptions)
    history_limit: int = 32


class BaseAgent(ABC):
    """Abstract base class for all Melo agents."""

    #: Short label used in logs / UI.
    kind: str = "base"

    def __init__(
        self,
        *,
        config: AgentConfig | None = None,
        memory: MemorySystem | None = None,
        tools: ToolRegistry | None = None,
    ) -> None:
        self.config = config or AgentConfig()
        self.memory = memory or MemorySystem()
        self.tools = tools or ToolRegistry()

    # -- runtime wiring ----------------------------------------------------

    def configure_runtime(
        self,
        runtime: VoiceAgentRuntime,
        *,
        override_system_prompt: str | None = None,
    ) -> None:
        """Apply this agent's config to an existing runtime.

        Called by the WebSocket handler after constructing the runtime.
        Subclasses can override to attach extra behaviour (e.g.
        subscribing to tool-call events).
        """
        prompt = override_system_prompt or self.build_system_prompt()
        runtime.set_system_prompt(prompt)
        runtime._history_limit = self.config.history_limit
        # Replace LLM options on the runtime config.
        # We mutate the existing RuntimeConfig so external references
        # (e.g. the WS handler's `runtime._config`) stay valid.
        runtime._config.llm_model = self.config.llm_options.model
        runtime._config.llm_temperature = self.config.llm_options.temperature
        runtime._config.llm_max_tokens = self.config.llm_options.max_tokens

    def make_runtime_config(self) -> RuntimeConfig:
        """Build a RuntimeConfig reflecting this agent's settings."""
        return RuntimeConfig(
            system_prompt=self.build_system_prompt(),
            llm_model=self.config.llm_options.model,
            llm_temperature=self.config.llm_options.temperature,
            llm_max_tokens=self.config.llm_options.max_tokens,
        )

    # -- persona -----------------------------------------------------------

    @abstractmethod
    def build_system_prompt(self) -> str:
        """Return the system prompt injected into every LLM call."""
        ...

    # -- factory -----------------------------------------------------------

    @classmethod
    def from_db_row(cls, row: "AgentRow") -> "BaseAgent":
        """Construct an agent from a DB `Agent` row.

        Calling on `BaseAgent` directly falls back to `VoiceAgent`
        (the default agent kind). Subclasses override to specialise.
        """
        from melo.agents.voice_agent import VoiceAgent

        target_cls: type[BaseAgent] = VoiceAgent if cls is BaseAgent else cls
        llm_cfg: dict = getattr(row, "llm_config", None) or {}
        options = LLMOptions(
            model=llm_cfg.get("model"),
            temperature=float(llm_cfg.get("temperature", 0.7)),
            max_tokens=llm_cfg.get("max_tokens"),
        )
        config = AgentConfig(
            name=row.name,
            persona=getattr(row, "persona", "") or "",
            system_prompt=getattr(row, "system_prompt", "") or "",
            voice_id=getattr(row, "voice_id", None),
            llm_options=options,
            history_limit=llm_cfg.get("history_limit") or 32,
        )
        return target_cls(config=config)
