"""StudioAgent — creative assistant for the multi-track studio.

Unlike `VoiceAgent` (a daily conversational companion), the StudioAgent
is a *task*-oriented assistant: it knows about the user's open project,
its tracks, and the clips on each track, and can drive them via the
`generate_speech`, `edit_audio`, and `call_mcp` tools.

The agent is constructed per-request (per REST call or WS session) so
it can be bound to:

  * the active `project_id` (and the loaded project tree, so the
    system prompt can describe the current studio state without an
    extra DB round-trip per LLM call).
  * the user's DB session, so `edit_audio` can write back to the
    database via `studio_service.apply_edit`.

The system prompt is rebuilt whenever the project state changes —
call `refresh_project_context()` after edits to inject the latest
snapshot.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from melo.agents.base import AgentConfig, BaseAgent
from melo.agents.memory import MemorySystem
from melo.agents.tools.edit_tool import EditAudioTool
from melo.agents.tools.registry import ToolRegistry
from melo.llm.base import ChatMessage, LLMProvider

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from melo.models.db import Project as ProjectRow

logger = logging.getLogger(__name__)


DEFAULT_PERSONA = (
    "You are Melo Studio — a meticulous creative producer. "
    "You help the user craft multi-track voice pieces: writing and "
    "polishing clip text, picking voices, arranging clips on the "
    "timeline, and applying audio edits. Be concrete and brief; when "
    "you take an action, summarise what changed in one sentence."
)


class StudioAgent(BaseAgent):
    """Creative-studio assistant bound to a project + DB session."""

    kind = "studio"

    def __init__(
        self,
        *,
        config: AgentConfig | None = None,
        memory: MemorySystem | None = None,
        tools: ToolRegistry | None = None,
        user_id: str | None = None,
        db: "AsyncSession | None" = None,
        project: "ProjectRow | None" = None,
        llm: LLMProvider | None = None,
        history_limit: int = 32,
        agent_id: str | None = None,
    ) -> None:
        cfg = config or AgentConfig()
        if not cfg.persona:
            cfg.persona = DEFAULT_PERSONA
        # When no memory is supplied but the agent has an id, reuse the
        # per-agent shared MemorySystem so long-term facts carry across
        # sessions and channels (studio chat + live voice). This unifies
        # memory behaviour with the voice channel, which already shares
        # one MemorySystem per agent via the registry.
        if memory is None and agent_id is not None:
            from melo.agents.memory_registry import get_agent_memory

            memory = get_agent_memory(agent_id)
        # Tools default to a registry that wires the bound edit_audio
        # tool. Subclasses can pass a custom registry to add more.
        own_tools = tools is None
        if own_tools:
            tools = self._build_default_tools(
                user_id=user_id, db=db, memory=memory, voice_id=cfg.voice_id
            )
        super().__init__(config=cfg, memory=memory, tools=tools)
        if own_tools:
            # Bind the memory tools to this agent's own memory instance so
            # recall/remember work regardless of how the agent was built
            # (e.g. via from_db_row, which has no memory to pass yet).
            from melo.agents.tools.memory_tool import RecallMemoryTool, RememberTool

            self.tools.unregister("recall_memory")
            self.tools.unregister("remember")
            self.tools.register(RecallMemoryTool(memory=self.memory))
            self.tools.register(RememberTool(memory=self.memory))
        self._user_id = user_id
        self._agent_id = agent_id
        self._db = db
        self._project = project
        # LLM provider injected for tests; resolved lazily from the
        # plugin manager on first chat otherwise.
        self._llm = llm
        # Conversation history — accumulates user + assistant turns so
        # the LLM sees prior context within a WS session.
        self._history: list[ChatMessage] = []
        self._history_limit = history_limit

    # -- prompt ------------------------------------------------------------

    def build_system_prompt(self) -> str:
        parts: list[str] = []
        if self.config.system_prompt:
            parts.append(self.config.system_prompt)
        else:
            parts.append(self.config.persona or DEFAULT_PERSONA)

        # Inject the studio context — the open project, its tracks, and
        # a per-track summary of clips. This lets the LLM answer
        # "what's on track 2?" without an extra tool round-trip.
        ctx = self._describe_project_context()
        if ctx:
            parts.append("")
            parts.append("[Studio context]")
            parts.append(ctx)

        # Hint about available tools.
        tool_names = self.tools.names()
        if tool_names:
            parts.append("")
            parts.append(
                f"[Available tools: {', '.join(tool_names)}. "
                "Use edit_audio to apply edits, generate_speech to render audio.]"
            )
        return "\n".join(parts)

    def _describe_project_context(self) -> str:
        """Render a compact textual snapshot of the open project."""
        if not self._project:
            return "(No project loaded.)"
        lines: list[str] = []
        proj = self._project
        lines.append(f"Project: {proj.name} (status={proj.status})")
        tracks = getattr(proj, "tracks", None) or []
        if not tracks:
            lines.append("  (no tracks yet)")
        for tr in tracks:
            clips = getattr(tr, "clips", None) or []
            clip_summary = (
                f"{len(clips)} clip(s)"
                if clips
                else "no clips"
            )
            lines.append(
                f"  Track {tr.order}: {tr.name} "
                f"(voice_id={tr.voice_id or 'unassigned'}, {clip_summary})"
            )
            for c in clips[:5]:  # cap to keep the prompt bounded
                lines.append(
                    f"    - clip {c.id[:8]} [{c.status}] "
                    f"start={c.start_time:.1f}s dur={c.duration:.1f}s "
                    f"text={c.text[:40]!r}"
                )
        return "\n".join(lines)

    # -- runtime wiring ----------------------------------------------------

    def configure_runtime(self, runtime, *, override_system_prompt: str | None = None) -> None:
        """Apply studio config to a runtime + bind the edit_audio tool."""
        super().configure_runtime(runtime, override_system_prompt=override_system_prompt)
        # Re-bind the edit_audio tool with the runtime's DB session if
        # we don't already have one. (The runtime is constructed by
        # the WS handler with a fresh session; the agent may have been
        # built without one for testing.)
        if self._db is None:
            # Studio runtime may expose a session; otherwise the tool
            # remains unbound and will raise on first use.
            session = getattr(runtime, "_db_session", None)
            user_id = getattr(runtime, "_user_id", None) or self._user_id
            if session is not None and user_id is not None:
                bound = EditAudioTool(db=session, user_id=user_id)
                self.tools.unregister("edit_audio")
                self.tools.register(bound)

    # -- LLM chat ----------------------------------------------------------

    def build_messages(self, user_text: str) -> list[ChatMessage]:
        """Assemble the message list for an LLM chat call.

        Order: [system] + history + new user message. The system prompt
        is rebuilt every call so the latest project context (after
        `refresh_project_context`) is reflected.
        """
        msgs: list[ChatMessage] = [
            ChatMessage(role="system", content=self.build_system_prompt())
        ]
        msgs.extend(self._history)
        msgs.append(ChatMessage(role="user", content=user_text))
        return msgs

    def append_history(self, msg: ChatMessage) -> None:
        """Record a turn, trimming oldest entries to keep history bounded."""
        self._history.append(msg)
        if len(self._history) > self._history_limit:
            del self._history[: len(self._history) - self._history_limit]

    def resolve_llm(self) -> LLMProvider:
        """Return the injected LLM provider, or the manager's default."""
        if self._llm is not None:
            return self._llm
        from melo.llm.manager import get_llm_manager

        return get_llm_manager().get()

    async def apply_edit_instruction(
        self, clip_id: str, instruction: str
    ) -> dict[str, Any]:
        """Route an edit instruction through the bound `edit_audio` tool.

        The tool in turn calls `studio_service.apply_edit` (without an
        agent) so the keyword dispatcher runs — this keeps the
        deterministic edit behaviour in one place while letting the
        StudioAgent emit tool-call events / log as needed.
        """
        return await self.tools.execute(
            "edit_audio", clip_id=clip_id, instruction=instruction
        )

    # -- factory -----------------------------------------------------------

    @classmethod
    def from_db_row(cls, row) -> "StudioAgent":
        """Construct a StudioAgent from an Agent DB row.

        Mirrors `BaseAgent.from_db_row` but specialises for the studio
        kind. `studio_project_id` and `studio_project` can be attached
        to the row via `setattr` by the caller (e.g. the route handler
        that loaded the project).
        """
        from melo.agents.tools.tts_tool import GenerateSpeechTool
        from melo.agents.tools.mcp_tool import CallMCPTool
        from melo.llm.base import LLMOptions

        llm_cfg: dict = getattr(row, "llm_config", None) or {}
        options = LLMOptions(
            model=llm_cfg.get("model"),
            temperature=float(llm_cfg.get("temperature", 0.6)),
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
        project = getattr(row, "_studio_project", None)
        user_id = getattr(row, "_studio_user_id", None)
        db = getattr(row, "_studio_db", None)
        agent_id = getattr(row, "id", None)
        return cls(
            config=config,
            user_id=user_id,
            db=db,
            project=project,
            agent_id=agent_id,
        )

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _build_default_tools(
        *,
        user_id: str | None,
        db: "AsyncSession | None",
        memory: MemorySystem | None = None,
        voice_id: str | None = None,
    ) -> ToolRegistry:
        """Build the studio's default tool registry.

        `edit_audio`, `studio_ops`, `transcribe_audio`, `export_mixdown`,
        and the memory tools are bound to the user's DB session / memory
        if available; otherwise they're registered unbound and will
        raise on first use (caller must `.bind()` them before invoking).
        `generate_speech` is bound to the agent's voice so rendered
        audio uses the configured voice. `preview_voice` is stateless
        and needs no binding.
        """
        from melo.agents.tools.asr_tool import TranscribeAudioTool
        from melo.agents.tools.clone_tool import CloneVoiceTool
        from melo.agents.tools.mcp_tool import CallMCPTool
        from melo.agents.tools.memory_tool import RecallMemoryTool, RememberTool
        from melo.agents.tools.mixdown_tool import ExportMixdownTool
        from melo.agents.tools.preview_voice_tool import PreviewVoiceTool
        from melo.agents.tools.studio_tool import StudioOpsTool
        from melo.agents.tools.tts_tool import GenerateSpeechTool

        reg = ToolRegistry()
        reg.register(GenerateSpeechTool(voice_id=voice_id))
        reg.register(CloneVoiceTool())
        reg.register(EditAudioTool(db=db, user_id=user_id))
        reg.register(CallMCPTool())
        reg.register(RecallMemoryTool(memory=memory))
        reg.register(RememberTool(memory=memory))
        reg.register(StudioOpsTool(db=db, user_id=user_id))
        reg.register(TranscribeAudioTool(db=db, user_id=user_id))
        reg.register(PreviewVoiceTool())
        reg.register(ExportMixdownTool(db=db, user_id=user_id))
        return reg

    async def refresh_project_context(self, db: "AsyncSession", project_id: str) -> None:
        """Re-fetch the project tree and rebuild the system prompt.

        Call this after the user mutates the studio (adds a track,
        edits a clip) so subsequent LLM turns see the new state.
        """
        from melo.services import studio_service

        if not self._user_id:
            return
        self._db = db
        self._project = await studio_service.get_project_tree(
            db, project_id, self._user_id
        )
        # Re-bind edit_audio with the fresh session.
        bound = EditAudioTool(db=db, user_id=self._user_id)
        self.tools.unregister("edit_audio")
        self.tools.register(bound)
