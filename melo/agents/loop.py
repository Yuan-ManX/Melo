"""AgentToolLoop — the omnipotent agentic tool loop for Melo agents.

A single conversational turn can now drive the whole studio: the LLM
streams text tokens while simultaneously emitting structured tool-call
blocks, the loop executes each call, feeds the result back as a system
message, and lets the LLM continue until it produces a final summary.
This turns a chat into a full orchestration — create a project, add a
track, generate speech, clone a voice, edit a clip — all in one turn.

Tool-call wire protocol
-----------------------
When the model wants a tool executed it emits a JSON block wrapped in a
distinctive fenced marker::

    [[tool_call: {"tool": "generate_speech", "args": {"text": "hi"}}]]

Multiple blocks may appear in a single response. After every block is
executed the results are appended to the conversation as system
messages and the loop asks the LLM to continue, so it can reason about
the outcome and either call more tools or summarise.

The loop is transport-agnostic: it pushes events through an optional
async `emit` callback (`{"type": "llm_chunk", "text": ...}` and
`{"type": "tool_call", "name", "args", "result"}`) and returns a plain
dict the caller can forward however it likes.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Awaitable, Callable

from melo.llm.base import ChatMessage

logger = logging.getLogger(__name__)

#: Regex matching a fenced tool-call block. `(.+?)` is non-greedy so the
#: first closing `]]` terminates the block.
_TOOL_CALL_RE = re.compile(r"\[\[tool_call:\s*(.+?)\]\]", flags=re.DOTALL)

#: Result message template injected between iterations so the LLM can
#: reason about what the tool actually did.
_RESULT_TEMPLATE = "[tool_result for {tool}]: {payload}"


class AgentToolLoop:
    """Drive a dialogue turn through repeated LLM → tool → LLM rounds.

    `agent` is any object exposing the StudioAgent surface used here:
    `tools` (a ToolRegistry), `memory`, `config` (with `llm_options`),
    `build_messages`, `append_history`, and `resolve_llm`.
    """

    def __init__(
        self,
        agent,
        *,
        emit: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        max_iterations: int = 6,
    ) -> None:
        self.agent = agent
        self._emit = emit
        self.max_iterations = max_iterations

    # -- public ------------------------------------------------------------

    async def run_turn(self, user_text: str) -> dict[str, Any]:
        """Run one full conversational turn and return the outcome.

        Returns `{"text", "tool_calls", "iterations"}`. The user message
        and the final assistant text are appended to the agent's history
        so the next turn has context; intermediate tool-result system
        messages are kept only for the current turn.
        """
        messages: list[ChatMessage] = list(self.agent.build_messages(user_text))
        tool_calls: list[dict[str, Any]] = []
        final_text = ""
        full_text = ""
        iterations = 0

        while iterations < self.max_iterations:
            iterations += 1
            llm = self.agent.resolve_llm()
            options = self.agent.config.llm_options

            parts: list[str] = []
            async for token in llm.stream_chat(messages, options=options):
                if not token:
                    continue
                parts.append(token)
                if self._emit is not None:
                    await self._emit({"type": "llm_chunk", "text": token})
            full_text = "".join(parts)

            calls = self._extract_tool_calls(full_text)
            if not calls:
                final_text = self._strip_tool_calls(full_text).strip()
                break

            for call in calls:
                tool = call.get("tool")
                args = call.get("args") or {}
                result: Any
                try:
                    result = await self.agent.tools.execute(tool, **args)
                except Exception as exc:  # ToolError or any failure
                    result = {"ok": False, "error": str(exc)}
                record = {"tool": tool, "args": args, "result": result}
                tool_calls.append(record)
                if self._emit is not None:
                    await self._emit(
                        {
                            "type": "tool_call",
                            "name": tool,
                            "args": args,
                            "result": result,
                        }
                    )
                # Feed the outcome back so the LLM can continue from it.
                payload = json.dumps(result, ensure_ascii=False)
                messages.append(
                    ChatMessage(
                        role="system",
                        content=_RESULT_TEMPLATE.format(tool=tool, payload=payload),
                    )
                )
        else:
            # Iteration budget exhausted while tools were still pending —
            # return whatever text the last round produced, stripped of
            # any leftover tool-call markers.
            final_text = self._strip_tool_calls(full_text).strip()

        # Persist the dialogue as a normal user/assistant exchange so the
        # next turn carries context. Tool-result messages are not kept.
        self.agent.append_history(ChatMessage(role="user", content=user_text))
        if final_text:
            self.agent.append_history(ChatMessage(role="assistant", content=final_text))

        return {
            "text": final_text,
            "tool_calls": tool_calls,
            "iterations": iterations,
        }

    # -- parsing helpers ---------------------------------------------------

    @staticmethod
    def _extract_tool_calls(text: str) -> list[dict[str, Any]]:
        """Pull every fenced tool-call block out of a response.

        Only valid JSON objects are returned; malformed blocks are
        skipped so a single bad emission can't abort the whole turn.
        """
        calls: list[dict[str, Any]] = []
        for raw in _TOOL_CALL_RE.findall(text):
            try:
                data = json.loads(raw.strip())
            except json.JSONDecodeError:
                logger.warning("Skipping unparseable tool_call block: %r", raw)
                continue
            if isinstance(data, dict):
                calls.append(data)
        return calls

    @staticmethod
    def _strip_tool_calls(text: str) -> str:
        """Remove all fenced tool-call blocks, leaving readable text."""
        return _TOOL_CALL_RE.sub("", text)