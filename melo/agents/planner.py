"""Planner — task decomposition for multi-step agent actions.

Given a user request, the planner produces a `Plan`: an ordered list
of `PlanStep`s, each describing a tool invocation or a sub-goal.

Melo ships a rule-based planner (keyword-driven decomposition for
multi-step execution without an LLM) and an LLM-backed planner that
implements the same `Planner.plan()` interface.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol

from melo.llm.base import ChatMessage, LLMProvider

logger = logging.getLogger(__name__)


@dataclass
class PlanStep:
    """A single step in a plan."""

    tool: str
    args: dict = field(default_factory=dict)
    description: str = ""
    #: Optional: the agent reasoning that produced this step, useful for
    #: debugging or for surfacing "why am I doing this" in the UI.
    rationale: str = ""

    def to_dict(self) -> dict:
        return {
            "tool": self.tool,
            "args": self.args,
            "description": self.description,
            "rationale": self.rationale,
        }


@dataclass
class Plan:
    """An ordered list of steps + shared context."""

    goal: str
    steps: list[PlanStep] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not self.steps

    def to_dict(self) -> dict:
        return {
            "goal": self.goal,
            "steps": [s.to_dict() for s in self.steps],
            "metadata": self.metadata,
        }


class Planner(Protocol):
    """Protocol every planner implements."""

    async def plan(self, request: str, *, context: list[ChatMessage] | None = None) -> Plan:
        """Decompose `request` into a `Plan`."""
        ...


class RuleBasedPlanner:
    """Keyword-driven planner.

    Not a real LLM planner — just enough to map a few obvious intents
    (generate speech, clone voice, edit audio) to single-step plans so
    the agent layer can exercise the full tool registry end-to-end.
    """

    name = "rule_based"

    async def plan(self, request: str, *, context: list[ChatMessage] | None = None) -> Plan:
        text = request.lower()
        # Studio-read intents — the voice channel uses these to let the
        # user drive the editor by speaking. Single-step plans cover
        # self-contained actions; dependent flows (create → track → clip)
        # are orchestrated by the LLM via inline [[tool_call]] blocks.
        # Multi-step studio orchestration: create a project AND add a
        # track to it in one request. The second step references the
        # first step's returned project id via `${p0.id}` — dependency
        # resolution in the runtime wires the two together. Must run
        # BEFORE the single-step "create project" check below.
        if "create" in text and "project" in text and (
            "track" in text or "音轨" in text
        ):
            return Plan(
                goal=request,
                steps=[
                    PlanStep(
                        tool="studio_ops",
                        args={"action": "create_project", "name": request},
                        description="Create a new studio project",
                    ),
                    PlanStep(
                        tool="studio_ops",
                        args={
                            "action": "add_track",
                            "project_id": "${p0.id}",
                            "name": "voice-track",
                        },
                        description="Add a voice track to the new project",
                    ),
                ],
            )
        # Full studio pipeline: create project → add track → add a clip →
        # generate speech for it. Each step pulls the id the previous one
        # returned, so a single spoken sentence builds a real project.
        if "create" in text and "project" in text and (
            "clip" in text or "片段" in text or "配音" in text
        ):
            return Plan(
                goal=request,
                steps=[
                    PlanStep(
                        tool="studio_ops",
                        args={"action": "create_project", "name": request},
                        description="Create a new studio project",
                    ),
                    PlanStep(
                        tool="studio_ops",
                        args={
                            "action": "add_track",
                            "project_id": "${p0.id}",
                            "name": "voice-track",
                        },
                        description="Add a voice track to the new project",
                    ),
                    PlanStep(
                        tool="studio_ops",
                        args={
                            "action": "add_clip",
                            "track_id": "${p1.id}",
                            "text": "Hello from Melo",
                        },
                        description="Add a clip to the track",
                    ),
                    PlanStep(
                        tool="studio_ops",
                        args={"action": "generate_clip", "clip_id": "${p2.id}"},
                        description="Generate speech for the clip",
                    ),
                ],
            )
        if any(k in text for k in ("create project", "make a project", "new project")):
            return Plan(
                goal=request,
                steps=[
                    PlanStep(
                        tool="studio_ops",
                        args={"action": "create_project", "name": request},
                        description="Create a new studio project",
                    )
                ],
            )
        if "list" in text and "project" in text and "voice" not in text:
            return Plan(
                goal=request,
                steps=[
                    PlanStep(
                        tool="studio_ops",
                        args={"action": "list_projects"},
                        description="List the user's studio projects",
                    )
                ],
            )
        if any(k in text for k in ("change your voice", "switch your voice")):
            return Plan(
                goal=request,
                steps=[
                    PlanStep(
                        tool="voice_control",
                        args={"action": "set", "voice_id": ""},
                        description="Switch the agent's speaking voice",
                    )
                ],
            )
        if ("voices" in text or "library" in text) and "voice" in text:
            return Plan(
                goal=request,
                steps=[
                    PlanStep(
                        tool="studio_ops",
                        args={"action": "list_voices"},
                        description="List the user's voice library",
                    )
                ],
            )
        if "clone" in text and "voice" in text:
            return Plan(
                goal=request,
                steps=[
                    PlanStep(
                        tool="clone_voice",
                        args={"sample_url": "", "name": "cloned"},
                        description="Clone a voice from the provided sample",
                    )
                ],
            )
        if "generate" in text and ("speech" in text or "audio" in text or "tts" in text):
            return Plan(
                goal=request,
                steps=[
                    PlanStep(
                        tool="generate_speech",
                        args={"text": request, "voice_id": None},
                        description="Generate speech audio for the requested text",
                    )
                ],
            )
        if "edit" in text and "audio" in text:
            return Plan(
                goal=request,
                steps=[
                    PlanStep(
                        tool="edit_audio",
                        args={"clip_id": "", "instruction": request},
                        description="Apply the requested edit to the audio clip",
                    )
                ],
            )
        # No tool needed — this is a conversational turn.
        return Plan(goal=request, steps=[])


class LLMPlanner:
    """LLM-backed planner.

    Uses a `LLMProvider` to decompose the request into steps. The
    output is expected to be a JSON object matching `Plan.to_dict()`;
    malformed output falls back to an empty plan with a warning.
    """

    name = "llm"

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def plan(self, request: str, *, context: list[ChatMessage] | None = None) -> Plan:
        import json

        from melo.llm.base import LLMOptions

        system_msg = ChatMessage(
            role="system",
            content=(
                "You are a task planner. Decompose the user's request into a "
                'JSON object: {"goal": str, "steps": [{"tool": str, "args": '
                'dict, "description": str}]}. If no tools are needed, return '
                'an empty steps list. Available tools: generate_speech, '
                "clone_voice, edit_audio, call_mcp."
            ),
        )
        user_msg = ChatMessage(role="user", content=request)
        messages = [system_msg] + list(context or []) + [user_msg]

        chunks: list[str] = []
        async for tok in self._llm.stream_chat(messages, options=LLMOptions(temperature=0.2)):
            chunks.append(tok)
        raw = "".join(chunks).strip()

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # Strip code fences if the model wrapped output in ```json.
            if raw.startswith("```"):
                inner = raw.strip("`").split("\n", 1)[-1]
                try:
                    data = json.loads(inner)
                except json.JSONDecodeError:
                    logger.warning("LLM planner returned non-JSON: %r", raw[:200])
                    return Plan(
                        goal=request,
                        steps=[],
                        metadata={"planner": "llm", "error": "non-json", "raw": raw[:200]},
                    )
            else:
                logger.warning("LLM planner returned non-JSON: %r", raw[:200])
                return Plan(
                    goal=request,
                    steps=[],
                    metadata={"planner": "llm", "error": "non-json", "raw": raw[:200]},
                )

        steps = [
            PlanStep(
                tool=s.get("tool", ""),
                args=s.get("args", {}) or {},
                description=s.get("description", ""),
                rationale=s.get("rationale", ""),
            )
            for s in (data.get("steps") or [])
            if s.get("tool")
        ]
        return Plan(
            goal=data.get("goal", request),
            steps=steps,
            metadata={"planner": "llm", "raw": raw},
        )


__all__ = ["Plan", "PlanStep", "Planner", "RuleBasedPlanner", "LLMPlanner"]
