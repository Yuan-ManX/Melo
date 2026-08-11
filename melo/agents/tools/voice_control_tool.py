"""voice_control tool — let the agent switch its own voice mid-session.

Bridges the agent's natural-language request straight to the runtime's
`set_voice`: the tool holds a `setter` callable (bound in the WS route
to `runtime.set_voice`) so the agent can say "change your voice to a
calmer one" and immediately re-tune how it speaks to the user. A voice
catalog lets it (and the user) see what voices the provider offers.

Stateless — no DB binding; the setter is injected at registration time.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from melo.agents.tools.registry import Tool, ToolError

#: Optional async callable that switches the active voice for a runtime.
VoiceSetter = Callable[[str], Awaitable[None]]


class VoiceControlTool(Tool):
    """Switch the agent's own TTS voice on request."""

    name = "voice_control"
    description = (
        "Change the agent's speaking voice. Args: action ('set' | "
        "'list'), voice_id (str, required for 'set'). set switches the "
        "live voice; list returns the available voices. Returns: "
        "{ok, voice_id?, voices?}."
    )

    def __init__(self, *, setter: VoiceSetter | None = None) -> None:
        self._setter = setter

    async def run(self, **kwargs: Any) -> dict:
        action = kwargs.get("action") or "set"
        voice_id = kwargs.get("voice_id")
        if action == "list":
            return {"ok": True, "voices": self._catalog()}
        if action != "set":
            raise ToolError(
                f"voice_control: unknown action '{action}' (use 'set' or 'list')"
            )
        if not voice_id:
            raise ToolError("voice_control 'set' requires 'voice_id'")
        if self._setter is None:
            raise ToolError("voice_control: no voice setter bound")
        await self._setter(voice_id)
        return {"ok": True, "voice_id": voice_id}

    def _catalog(self) -> list[dict]:
        """Return the provider's voice catalog (name + id) when available."""
        try:
            from melo.voice.manager import get_voice_manager

            manager = get_voice_manager()
            voices = getattr(manager, "voices", None)
            if callable(voices):
                voices = voices()
            if not voices:
                return []
            out = []
            for v in voices:
                if isinstance(v, dict):
                    out.append({"id": v.get("id"), "name": v.get("name")})
                else:
                    out.append({"id": v, "name": v})
            return out
        except Exception:  # pragma: no cover - defensive, catalog is best-effort
            return []
