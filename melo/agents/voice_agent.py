"""VoiceAgent — daily conversational companion.

The simplest agent: a persona + system prompt + memory bound to a
`VoiceAgentRuntime`. It doesn't drive tools on its own — that's the
planner's job. Its job is to give the runtime a personality and a
starting memory state.
"""

from __future__ import annotations

from melo.agents.base import AgentConfig, BaseAgent
from melo.agents.memory import MemorySystem

DEFAULT_PERSONA = (
    "You are Melo — a warm, attentive voice companion. "
    "You listen carefully, remember what matters to the user, and "
    "reply in natural, conversational sentences. Keep answers short "
    "unless the user asks for detail."
)


class VoiceAgent(BaseAgent):
    """Default conversational agent."""

    kind = "voice"

    def __init__(
        self,
        *,
        config: AgentConfig | None = None,
        memory: MemorySystem | None = None,
    ) -> None:
        cfg = config or AgentConfig()
        if not cfg.persona:
            cfg.persona = DEFAULT_PERSONA
        super().__init__(config=cfg, memory=memory)

    def build_system_prompt(self) -> str:
        parts: list[str] = []
        if self.config.system_prompt:
            parts.append(self.config.system_prompt)
        else:
            parts.append(self.config.persona or DEFAULT_PERSONA)
        # Hint the agent about available memory context.
        facts = self.memory.short_term
        if facts:
            parts.append(
                f"\n\n[You have {len(facts)} recent messages in short-term "
                "memory. Recall long-term facts via the recall tool when "
                "relevant.]"
            )
        return "\n".join(parts)
