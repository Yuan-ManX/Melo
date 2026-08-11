"""VoiceAgentRuntime — full-duplex voice conversation loop.

Pipeline: VAD → ASR → LLM → TTS → audio out, with barge-in cancelling
any in-flight stage the moment the user starts speaking.

Providers resolve lazily through their plugin managers on first use;
`RuntimeConfig.stub_llm=True` forces StubLLM for CI / dev. Barge-in is
guarded by `min_speech_for_barge_ms` so short glitches don't abort turns.

`RuntimeCallbacks` emits the wire protocol: agent_state, asr_partial/
final, llm_chunk, tts_chunk, error, interruption, planning.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, AsyncIterator, Awaitable, Callable, Optional, Protocol

if TYPE_CHECKING:
    from melo.agents.memory import MemorySystem
    from melo.agents.planner import Planner
    from melo.agents.tools.registry import ToolRegistry

from melo.llm.base import (
    ChatMessage,
    LLMOptions,
    LLMProvider,
    LLMProviderUnavailable,
)
from melo.llm.manager import get_llm_manager
from melo.voice.base import (
    ASRProvider,
    TTSOptions,
    TTSProvider,
    VoiceProviderUnavailable,
)
from melo.voice.manager import get_voice_manager
from melo.voice.vad import VoiceActivityDetector

logger = logging.getLogger(__name__)

#: Regex matching an inline voice tool-call block. Non-greedy so the
#: first closing `]]` terminates the block, consistent with the
#: AgentToolLoop wire protocol so the voice and studio channels share
#: one format.
_TOOL_CALL_RE = re.compile(r"\[\[tool_call:\s*(.+?)\]\]", flags=re.DOTALL)

#: Matches a `${p<index>.<key>}` reference to an earlier plan step's
#: output. `?P<ref>` is the full placeholder; `?P<idx>` and `?P<key>`
#: capture the step position and the field to pull out of its result.
_PLACEHOLDER_RE = re.compile(r"\$\{p(?P<idx>\d+)\.(?P<key>[a-zA-Z0-9_]+)\}")


def _resolve_step_args(args: dict, step_results: list[dict]) -> dict:
    """Replace `${p<i>.<key>}` placeholders in `args` using step results.

    Lets a rule-based plan chain dependent steps without an LLM: e.g. a
    step that creates a project can have a following step reference
    `${p0.id}` to feed the returned project id into its own args. When
    a referenced step is out of range or lacks the key, the placeholder
    is left as-is so the tool receives a visible, fail-fast value rather
    than a silent empty string.
    """
    if not step_results:
        return args

    def resolve(value: object) -> object:
        if isinstance(value, str) and "{p" in value:
            def _sub(match: re.Match) -> str:
                idx = int(match.group("idx"))
                key = match.group("key")
                if idx < len(step_results) and isinstance(
                    step_results[idx], dict
                ):
                    resolved = step_results[idx].get(key)
                    if resolved is not None:
                        return str(resolved)
                return match.group(0)

            return _PLACEHOLDER_RE.sub(_sub, value)
        if isinstance(value, dict):
            return {k: resolve(v) for k, v in value.items()}
        if isinstance(value, list):
            return [resolve(v) for v in value]
        return value

    return {k: resolve(v) for k, v in args.items()}


class AgentState(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"


class RuntimeCallbacks(Protocol):
    """Sink for runtime-emitted events.

    The WebSocket route implements this protocol to push messages back to
    the browser. Methods are async to allow back-pressure on slow sockets.
    """

    async def on_state(self, state: AgentState) -> None: ...

    async def on_asr_partial(self, text: str) -> None: ...

    async def on_asr_final(self, text: str) -> None: ...

    async def on_llm_chunk(self, text: str) -> None: ...

    async def on_tts_chunk(self, audio: bytes) -> None: ...

    async def on_error(self, message: str) -> None: ...

    async def on_tool_call(self, name: str, args: dict) -> None: ...

    async def on_tool_result(self, name: str, result: dict) -> None: ...

    async def on_tool_retry(
        self, name: str, attempt: int, max_retries: int, error: str
    ) -> None: ...

    async def on_interruption(self, reason: str) -> None: ...

    async def on_voice_changed(self, voice_id: str) -> None: ...

    async def on_planning(self, plan: dict) -> None: ...


# Type aliases for clarity.
AudioFeeder = Callable[[], Awaitable[Optional[bytes]]]
"""Async callable that returns the next audio chunk, or None on EOF."""


# Reasons emitted with on_interruption so clients can differentiate the
# interruption source without string-matching state values.
INTERRUPT_REASON_BARGE_IN = "barge_in"          # user started speaking
INTERRUPT_REASON_CLIENT_STOP = "client_stop"    # caller invoked stop()


@dataclass
class RuntimeConfig:
    """Tuning knobs for the runtime loop."""

    vad_threshold: float = 0.5
    vad_silence_pad_ms: int = 600
    vad_min_speech_ms: int = 250
    asr_partial_flush_ms: int = 400
    # When True, the runtime forces the StubLLM provider regardless of
    # the configured `llm_provider`. Useful for dev / CI without API keys.
    stub_llm: bool = False
    stub_llm_text: str = "I heard you."
    # LLM model override (None = use provider default).
    llm_model: str | None = None
    llm_temperature: float = 0.7
    llm_max_tokens: int | None = None
    # System prompt injected as the first chat message when present.
    system_prompt: str | None = None
    # TTS voice id forwarded to the TTS provider on synthesis.
    voice_id: str | None = None
    # -- barge-in tuning --------------------------------------------------
    # Master switch for interrupting turns when new speech arrives during
    # THINKING or SPEAKING. Turning this off gives a strict turn-based
    # behaviour useful for CI tests that don't feed overlapping audio.
    barge_in_enabled: bool = True
    # Require this many ms of VAD-speech before treating a new utterance
    # as a real interruption. Short blips (mic pop, cough, bg laugh)
    # often trigger VAD momentarily and shouldn't abort the turn.
    min_speech_for_barge_ms: int = 120
    # Audio frame duration the runtime assumes when converting
    # min_speech_for_barge_ms into a speech-frame counter. The actual
    # frame size varies by the client, but 30 ms matches the 480-sample
    # @ 16 kHz PCM windows the test helpers use.
    barge_frame_ms: int = 30
    # -- Stage 16: planner step -------------------------------------------
    # When True, an explicit planner step runs BEFORE the LLM stream:
    # the planner decomposes the user transcript into an ordered list
    # of tool calls, the runtime executes each call upfront, and the
    # collected results are injected into the LLM system prompt as
    # context. Defaults to False so existing tests / sessions that
    # don't attach a planner behave identically.
    planner_enabled: bool = False


@dataclass
class _ConversationTurn:
    """Tracks state of a single user-utterance turn."""

    audio: bytearray = field(default_factory=bytearray)
    started_at_frame: int = 0
    ended_at_frame: int = 0


class VoiceAgentRuntime:
    """Drives a single WebSocket session's voice loop.

    Lifecycle:
      * `feed_audio(bytes)` is called by the WebSocket handler whenever a
        new `audio_chunk` arrives.
      * Internally, audio is queued into a VAD detector; speech segments
        are accumulated and forwarded to ASR.
      * On speech end, ASR is finalised → LLM is invoked → TTS streams.
      * `barge_in()` interrupts the current turn (ASR / LLM / TTS) and
        resets to LISTENING so the new user utterance can be captured.
      * `stop()` drains all in-flight tasks and resets state to IDLE.

    Task tracking:
      * `_main_task` drives the VAD loop for all audio (never cancelled
        except on `stop()`).
      * `_turn_task` is one background task per utterance and covers the
        entire ASR → LLM → TTS pipeline. Barge-in cancels `_turn_task`,
        which cascades into cancelling an in-flight LLM stream or TTS
        stream via `asyncio.Task.cancel()`. This guarantees stale turn
        output never reaches the client after interruption.
      * `_tts_task` (legacy) is additionally tracked inside `_run_tts`
        so `_cancel_tts()` can be invoked standalone by callers who only
        want to abort playback without aborting the rest of the turn.
    """

    def __init__(
        self,
        *,
        agent_id: str,
        asr: ASRProvider | None = None,
        tts: TTSProvider | None = None,
        llm: LLMProvider | None = None,
        vad: VoiceActivityDetector | None = None,
        callbacks: RuntimeCallbacks | None = None,
        config: RuntimeConfig | None = None,
        history: list[ChatMessage] | None = None,
        memory: MemorySystem | None = None,
        tools: Optional["ToolRegistry"] | None = None,
        planner: Optional["Planner"] | None = None,
    ) -> None:
        self.agent_id = agent_id
        self._callbacks = callbacks
        self._config = config or RuntimeConfig()
        self._memory = memory
        self._tools = tools
        self._planner = planner
        # Stage 18: per-runtime tool allowlist. When set, the attached
        # registry is filtered to these names so the runtime never
        # executes a disallowed tool. None means no restriction.
        self._tool_allowlist: set[str] | None = None

        # Resolve providers lazily through the manager so that an unset
        # ASR/TTS/LLM doesn't crash construction (only first-use matters).
        self._asr = asr
        self._tts = tts
        self._llm = llm
        self._vad = vad or VoiceActivityDetector(
            threshold=self._config.vad_threshold,
            silence_pad_ms=self._config.vad_silence_pad_ms,
            min_speech_ms=self._config.vad_min_speech_ms,
        )

        self._state = AgentState.IDLE
        self._audio_queue: asyncio.Queue[Optional[bytes]] = asyncio.Queue()
        self._current_turn: _ConversationTurn | None = None
        self._tts_task: asyncio.Task | None = None
        self._turn_task: asyncio.Task | None = None
        self._main_task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._speech_active = False
        # Count of consecutive speech frames delivered while the current
        # utterance was classified as a potential barge-in. Used to
        # implement `min_speech_for_barge_ms` so a single cough frame
        # doesn't abort the current turn.
        self._barge_speech_frames = 0
        # When True, `_process_turn` knows its async context is being
        # cancelled and must not append to history or emit final events.
        # The flag is set by `_cancel_turn` before cancelling the task.
        self._turn_cancelled = False
        # Conversation history — accumulates user + assistant turns so
        # the LLM sees prior context. Bounded by `history_limit`.
        self._history: list[ChatMessage] = list(history or [])
        self._history_limit = 32
        # Cross-token buffer for stripping inline tool-call markers from
        # the streaming LLM output (handled by `_filter_tool_markers`).
        self._tool_filter_buf = ""
        # Per-turn state for tool-call streaming (Stage 22): calls are
        # announced and executed as their markers close mid-stream, then
        # awaited by `_finish_streamed_tools` once the stream ends.
        self._stream_tool_calls: list[tuple[str, dict]] = []
        self._stream_tool_tasks: list[asyncio.Task] = []

    # -- public API --------------------------------------------------------

    @property
    def state(self) -> AgentState:
        return self._state

    @property
    def history(self) -> list[ChatMessage]:
        """Snapshot of conversation history (read-only view)."""
        return list(self._history)

    def attach_callbacks(self, callbacks: RuntimeCallbacks) -> None:
        self._callbacks = callbacks

    def set_system_prompt(self, prompt: str | None) -> None:
        """Update the system prompt used for subsequent LLM calls."""
        self._config.system_prompt = prompt

    def apply_agent_profile(
        self,
        *,
        persona: str | None = None,
        system_prompt: str | None = None,
        voice_id: str | None = None,
        history_limit: int | None = None,
        max_tokens: int | None = None,
    ) -> None:
        """Bind an agent's persona / voice / LLM bounds to this runtime.

        System prompt resolution is explicit-first: a non-empty
        `system_prompt` wins; otherwise `persona` is used. When both are
        absent the prompt stays None so no system message is injected.
        """
        if system_prompt:
            self._config.system_prompt = system_prompt
        elif persona:
            self._config.system_prompt = persona
        if voice_id:
            self._config.voice_id = voice_id
        if history_limit is not None:
            self._history_limit = history_limit
        if max_tokens is not None:
            self._config.llm_max_tokens = max_tokens

    async def set_voice(self, voice_id: str) -> None:
        """Switch the TTS voice used by future turns at runtime.

        Lets the user (or the agent itself, via a tool) swap voices
        without restarting the session. The next TTS synthesis will
        use the new voice_id; in-flight TTS playback is NOT cancelled
        — call `barge_in()` separately if you want to abort the
        current playback too. Emits `on_voice_changed(voice_id)` so
        clients can update their UI badge / dropdown selection.

        Empty / whitespace-only voice_ids are ignored (no-op) so a
        buggy client can't clear the configured voice by accident.
        """
        if not voice_id or not voice_id.strip():
            return
        # Normalize + dedupe: skip the work + event if the voice is
        # already active. This makes the call idempotent, which the
        # voice picker UI relies on (it sends `set_voice` on every
        # dropdown change, including back to the currently-selected
        # voice when the user cancels the picker).
        normalized = voice_id.strip()
        if self._config.voice_id == normalized:
            return
        self._config.voice_id = normalized
        await self._emit_voice_changed(normalized)

    def attach_memory(self, memory: MemorySystem) -> None:
        """Attach a shared memory system for long-term recall."""
        self._memory = memory

    def attach_tools(self, tools: "ToolRegistry") -> None:
        """Attach a tool registry the LLM can invoke inline via tool_call.

        Stage 18: when a tool allowlist is active (set via
        `set_tool_allowlist`), the registry is filtered to the allowed
        names before being stored so the runtime never executes a
        disallowed tool — neither via inline `[[tool_call]]` markers
        nor via the planner step.
        """
        if self._tool_allowlist is not None:
            tools = tools.filter(list(self._tool_allowlist))
        self._tools = tools

    def set_tool_allowlist(self, names: list[str] | None) -> None:
        """Stage 18: restrict which attached tools this runtime may invoke.

        `names` is the list of tool names permitted for this runtime's
        agent. None or an empty list clears the restriction so every
        tool in the attached registry is callable. When a registry is
        already attached, it is re-filtered immediately so the new
        restriction takes effect for in-flight turns. A subsequent
        `attach_tools()` call is also filtered through this allowlist.
        """
        self._tool_allowlist = set(names) if names else None
        if self._tools is not None:
            self._tools = self._tools.filter(names)

    def attach_planner(self, planner: "Planner") -> None:
        """Attach a planner whose `plan()` runs before each LLM stream.

        Stage 16: when `RuntimeConfig.planner_enabled` is True and a
        planner is attached, every turn first decomposes the user
        transcript into an ordered list of tool calls, executes them
        upfront, and feeds the collected results into the LLM system
        prompt as context. Without this call the runtime behaves
        identically to pre-Stage-16 releases.
        """
        self._planner = planner

    async def recall_for_turn(self, query: str, *, k: int = 3) -> list:
        """Retrieve long-term memory facts relevant to the current turn.

        Returns an empty list when no memory system is attached, so the
        LLM path degrades gracefully to plain conversation history.
        """
        if self._memory is None:
            return []
        return await self._memory.recall(query, k=k)

    def reset_history(self) -> None:
        """Clear conversation history (e.g. on session reset)."""
        self._history.clear()

    def start(self) -> None:
        """Kick off the background VAD + dispatch loop."""
        if self._main_task is not None and not self._main_task.done():
            return
        self._stop_event.clear()
        self._main_task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        """Stop the runtime, drain in-flight tasks, and reset state.

        Emits an `on_interruption("client_stop")` event so callers can
        distinguish a graceful shutdown from a mid-turn interruption.
        """
        self._stop_event.set()
        # Cancel the in-flight turn (if any) first so no more TTS/LLM
        # callbacks fire into a closing socket.
        await self._cancel_turn(reason=INTERRUPT_REASON_CLIENT_STOP, emit_event=True)
        # Signal end-of-stream to the audio queue consumer.
        await self._audio_queue.put(None)
        if self._main_task is not None:
            try:
                await asyncio.wait_for(self._main_task, timeout=2.0)
            except asyncio.TimeoutError:
                self._main_task.cancel()
            self._main_task = None
        await self._cancel_tts()
        await self._set_state(AgentState.IDLE)

    async def feed_audio(self, chunk: bytes) -> None:
        """Enqueue incoming PCM audio for the VAD loop."""
        await self._audio_queue.put(chunk)

    async def barge_in(self) -> None:
        """User interrupted the agent — abort turn + drop pending output, go LISTENING.

        Cancels the whole ASR → LLM → TTS pipeline (not just TTS) so
        stale assistant output never reaches the client. Then fires
        `on_interruption("barge_in")` so the client knows to stop
        buffering any audio that was already pushed before the cancel
        was observed.
        """
        if self._stop_event.is_set():
            return
        await self._cancel_turn(reason=INTERRUPT_REASON_BARGE_IN, emit_event=True)
        self._current_turn = None
        self._barge_speech_frames = 0
        await self._set_state(AgentState.LISTENING)

    # -- main loop ---------------------------------------------------------

    async def _run_loop(self) -> None:
        """Consume audio from the queue, feed VAD, drive turn lifecycle.

        Each VAD `start` event marks a potential new utterance. If the
        runtime is already THINKING or SPEAKING when the event arrives,
        this is a barge-in. To avoid cancelling turns on short glitches,
        we count consecutive speech frames via `_audio_iter`; once the
        threshold is crossed, `barge_in()` is invoked. If the user
        stops before crossing the threshold, we leave the in-flight
        turn alone and drop the short utterance.
        """
        await self._set_state(AgentState.LISTENING)
        try:
            async for event in self._vad.feed(self._audio_iter()):
                if self._stop_event.is_set():
                    break
                if event.kind == "start":
                    self._speech_active = True
                    self._current_turn = _ConversationTurn(
                        started_at_frame=event.ts and 0 or 0,
                    )
                    # If we're mid-turn (THINKING or SPEAKING), treat
                    # this as a candidate barge-in. The actual barge
                    # fires once `_barge_speech_frames` crosses the
                    # threshold below, so a single glitched frame
                    # doesn't abort output.
                    if (
                        self._config.barge_in_enabled
                        and self._state in {AgentState.THINKING, AgentState.SPEAKING}
                    ):
                        self._barge_speech_frames = 0
                    else:
                        # Not an interruption — go straight to LISTENING.
                        await self._set_state(AgentState.LISTENING)
                elif event.kind == "speech":
                    # VAD emits `speech` events for every audio frame
                    # classified as speech; count them for the threshold.
                    if (
                        self._config.barge_in_enabled
                        and self._speech_active
                        and self._state in {AgentState.THINKING, AgentState.SPEAKING}
                    ):
                        self._barge_speech_frames += 1
                        frames_required = max(
                            1,
                            int(
                                self._config.min_speech_for_barge_ms
                                / max(1, self._config.barge_frame_ms)
                            ),
                        )
                        if self._barge_speech_frames == frames_required:
                            # Passed threshold — perform the actual
                            # interruption now. Further speech frames
                            # this utterance are user talking.
                            await self.barge_in()
                elif event.kind == "end":
                    self._speech_active = False
                    # Hand off accumulated audio to the turn processor.
                    turn = self._current_turn
                    self._current_turn = None
                    # Drop short utterances that were counting toward a
                    # barge-in threshold — they're noise, not speech.
                    if self._config.barge_in_enabled and turn is not None:
                        frames_required = max(
                            1,
                            int(
                                self._config.min_speech_for_barge_ms
                                / max(1, self._config.barge_frame_ms)
                            ),
                        )
                        if (
                            self._barge_speech_frames > 0
                            and self._barge_speech_frames < frames_required
                        ):
                            self._barge_speech_frames = 0
                            continue
                    self._barge_speech_frames = 0
                    if turn is not None and len(turn.audio) > 0:
                        # Cancel any existing turn task so only the
                        # newest utterance drives output. Without this,
                        # two near-simultaneous VAD end events would
                        # spawn two turn tasks that race.
                        if self._turn_task is not None and not self._turn_task.done():
                            await self._cancel_turn(
                                reason=INTERRUPT_REASON_BARGE_IN, emit_event=False
                            )
                        # Spawn turn processing in the background so the
                        # VAD loop keeps listening for the next utterance.
                        self._turn_task = asyncio.create_task(self._process_turn(turn))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("VoiceAgentRuntime main loop crashed")
            await self._emit_error(f"runtime crashed: {exc}")

    async def _audio_iter(self) -> AsyncIterator[bytes]:
        """Adapt the asyncio queue into an async iterator for VAD.feed."""
        while True:
            chunk = await self._audio_queue.get()
            if chunk is None:
                return
            # Buffer for current turn if active.
            if self._speech_active and self._current_turn is not None:
                self._current_turn.audio.extend(chunk)
            yield chunk

    # -- turn processing ---------------------------------------------------

    async def _process_turn(self, turn: _ConversationTurn) -> None:
        """ASR → LLM → TTS for one user utterance.

        Cancellation semantics:
          * `_cancel_turn` sets `_turn_cancelled = True` and cancels the
            wrapping `_turn_task` asyncio task. That propagates
            CancelledError into whichever await in this chain is active.
          * CancelledError is re-raised so the task finishes in the
            cancelled state (important for the main loop's "task done"
            checks).
          * History is NOT appended for cancelled turns so a half-spoken
            "What's the wea" doesn't poison subsequent turns.
          * `_turn_cancelled` is reset at the top so a cancelled turn
            never interferes with the next turn's state.
        """
        self._turn_cancelled = False
        try:
            transcript = await self._run_asr(turn)
            if self._turn_cancelled:
                return
            if transcript:
                await self._callbacks.on_asr_final(transcript)
            else:
                # Nothing recognised — back to listening.
                await self._set_state(AgentState.LISTENING)
                return

            await self._set_state(AgentState.THINKING)
            # Stage 16: optional planner step runs BEFORE the LLM stream
            # so the LLM final response can reason about real tool
            # outputs rather than emit inline tool_call markers and wait
            # for a second iteration. Returns "" when disabled / no
            # planner attached / empty plan — keeps the path identical
            # to pre-Stage-16 in those cases.
            plan_context = await self._run_planner(transcript)
            if self._turn_cancelled:
                return
            llm_text = await self._run_llm(transcript, plan_context=plan_context)
            if self._turn_cancelled:
                return

            await self._set_state(AgentState.SPEAKING)
            await self._run_tts(llm_text)
        except (VoiceProviderUnavailable, LLMProviderUnavailable) as exc:
            if self._turn_cancelled:
                return
            logger.warning("Provider unavailable: %s", exc)
            await self._emit_error(f"provider unavailable: {exc}")
            await self._set_state(AgentState.LISTENING)
        except asyncio.CancelledError:
            self._turn_cancelled = True
            raise
        except Exception as exc:
            if self._turn_cancelled:
                return
            logger.exception("Turn processing failed")
            await self._emit_error(f"turn failed: {exc}")
            await self._set_state(AgentState.LISTENING)
        finally:
            if not self._turn_cancelled and self._state == AgentState.SPEAKING:
                await self._set_state(AgentState.LISTENING)

    async def _run_asr(self, turn: _ConversationTurn) -> str:
        """Stream audio through ASR, emit partials, return final transcript."""
        asr = self._resolve_asr()

        async def gen() -> AsyncIterator[bytes]:
            yield bytes(turn.audio)

        final_text = ""
        async for partial in asr.transcribe_stream(gen()):
            if partial:
                await self._callbacks.on_asr_partial(partial)
                final_text = partial
        return final_text.strip()

    async def _run_planner(self, transcript: str) -> str:
        """Stage 16 planner step — runs BEFORE the LLM stream.

        When `planner_enabled` is False or no planner is attached, this
        is a no-op returning "" so the runtime behaves identically to
        pre-Stage-16 releases. When enabled:

          1. The planner decomposes `transcript` (+ history context)
             into an ordered `Plan` of tool-call steps.
          2. The plan is emitted via `on_planning(plan.to_dict())` so
             the client can surface a transient "正在规划…" indicator.
          3. Each plan step is executed in order against the attached
             tool registry. Tool calls + results are surfaced via the
             existing `on_tool_call` / `on_tool_result` callbacks so
             clients show progress. Steps whose tool name is not in
             the registry are skipped with an `ok:False` result so the
             planner never silently no-ops.
          4. Each step's result is summarised into a context string
             that is returned for injection into the LLM system prompt,
             letting the final response reason about real outputs.

        Planner exceptions are logged and treated as an empty plan so a
        broken planner never aborts the turn — the LLM still streams its
        best-effort response without plan context.
        """
        if self._planner is None or not self._config.planner_enabled:
            return ""
        try:
            plan = await self._planner.plan(
                transcript, context=list(self._history)
            )
        except asyncio.CancelledError:
            self._turn_cancelled = True
            raise
        except Exception as exc:
            logger.warning("Planner raised; falling back to no-plan: %s", exc)
            return ""
        if self._turn_cancelled:
            return ""
        if plan.is_empty:
            # Conversational turn — no planning event, no tool calls.
            # The LLM streams its response as if no planner existed.
            return ""
        await self._emit_planning(plan.to_dict())

        # Build the set of registered tool names once so unknown tools
        # are skipped per-step without re-querying the registry.
        available: set[str] = set()
        if self._tools is not None:
            try:
                available = {t["name"] for t in self._tools.schemas()}
            except Exception:  # pragma: no cover - defensive
                available = set()

        context_parts: list[str] = []
        # Per-step results (keyed by position) so later steps can pull
        # values out of earlier outputs via `${p<i>.<key>}` placeholders.
        step_results: list[dict] = []
        for index, step in enumerate(plan.steps):
            if self._turn_cancelled:
                break
            await self._emit_tool_call(step.tool, step.args)
            if step.tool not in available:
                # Planner asked for a tool the runtime doesn't have —
                # surface as a failed result so the client sees the
                # mismatch rather than a silent skip.
                result = {
                    "ok": False,
                    "error": f"tool not registered: {step.tool}",
                }
                await self._emit_tool_result(step.tool, result)
                context_parts.append(
                    f"[planned tool {step.tool}: NOT AVAILABLE]"
                )
                step_results.append(result)
                continue
            # Resolve references to earlier step outputs before running,
            # enabling dependent orchestration (e.g. create a project,
            # then add a track to the returned project id).
            resolved_args = _resolve_step_args(step.args, step_results)
            try:
                raw = await self._tools.execute(
                    step.tool,
                    on_retry=self._exec_retry_listener,
                    **resolved_args,
                )
            except asyncio.CancelledError:
                self._turn_cancelled = True
                raise
            except Exception as exc:
                raw = {"ok": False, "error": str(exc)}
            if not isinstance(raw, dict) or "ok" not in raw:
                raw = {"ok": True, "result": raw}
            await self._emit_tool_result(step.tool, raw)
            payload = json.dumps(raw, ensure_ascii=False)
            context_parts.append(
                f"[planned tool {step.tool}: {payload}]"
            )
            step_results.append(raw)
        return "\n".join(context_parts)

    async def _run_llm(self, transcript: str, *, plan_context: str = "") -> str:
        """Produce LLM response, emit llm_chunk events.

        Builds the chat messages from the conversation history + the new
        user transcript, streams tokens from the LLM provider, emits
        each token as `on_llm_chunk`, and (on a non-cancelled turn)
        accumulates the full text back into history.

        `plan_context` (Stage 16) carries the pre-executed tool results
        produced by `_run_planner`. When non-empty it is appended to the
        system message so the LLM final response can reference real
        tool outputs rather than re-issuing tool_call markers.
        """
        llm = self._resolve_llm()
        facts = await self.recall_for_turn(transcript)
        tool_prompt = self._build_tool_prompt()
        messages = self._build_messages(
            transcript,
            memory_facts=facts,
            tool_prompt=tool_prompt,
            plan_context=plan_context,
        )
        options = LLMOptions(
            model=self._config.llm_model,
            temperature=self._config.llm_temperature,
            max_tokens=self._config.llm_max_tokens,
        )

        full_text_parts: list[str] = []
        # Reset per-turn stream state so a leftover unclosed block or a
        # previous turn's tool tasks never bleed into this turn.
        self._tool_filter_buf = ""
        self._stream_tool_calls = []
        self._stream_tool_tasks = []
        try:
            async for token in llm.stream_chat(messages, options=options):
                if self._turn_cancelled:
                    # Stop emitting chunks mid-stream so the client
                    # never sees a half-finished response.
                    break
                if not token:
                    continue
                # Keep the raw token for the final display text, but emit a
                # marker-free version so the client / TTS never speaks
                # protocol. Tool-call blocks are detected mid-stream and
                # executed immediately (Stage 22) rather than waiting for
                # the whole LLM response to finish.
                full_text_parts.append(token)
                await self._callbacks.on_llm_chunk(
                    self._filter_tool_markers(token, on_block=self._on_stream_block)
                )
        except asyncio.CancelledError:
            self._turn_cancelled = True
            self._cancel_stream_tools()
            raise

        if self._turn_cancelled:
            self._cancel_stream_tools()
            return ""
        full_text = "".join(full_text_parts).strip()
        if self._stream_tool_calls:
            llm_text = await self._finish_streamed_tools(full_text)
        else:
            llm_text = full_text
        # Persist the turn into history so the next turn sees context.
        # The assistant entry stores the final spoken text (tool markers
        # stripped) rather than the raw stream. If the turn was cancelled
        # after the stream finished (race), never persist.
        if not self._turn_cancelled:
            self._append_history(ChatMessage(role="user", content=transcript))
            if llm_text:
                self._append_history(ChatMessage(role="assistant", content=llm_text))
        return llm_text

    def _build_messages(
        self,
        user_transcript: str,
        *,
        memory_facts: list | None = None,
        tool_prompt: str | None = None,
        plan_context: str = "",
    ) -> list[ChatMessage]:
        """Assemble the message list for the LLM call.

        Order: [system?] + history (excluding the just-added user
        message — it's appended here) + new user message.

        When `memory_facts` are supplied they are appended to the system
        content as a long-term-memory block, so the base system_prompt
        remains intact and recall is folded in as supplementary context.
        A `tool_prompt` (when present) is appended after the memory block
        so the LLM knows it may emit inline tool-call blocks.
        `plan_context` (Stage 16) is appended last as the planner's
        pre-executed tool outputs, so the LLM final response can reason
        about real results rather than re-issuing tool_call markers.
        """
        sys = self._config.system_prompt
        if memory_facts:
            recall = (
                "[Long-term memory: "
                + "; ".join(f"{f.role}: {f.content}" for f in memory_facts)
                + "]"
            )
            sys = f"{sys}\n\n{recall}" if sys else recall
        if tool_prompt:
            sys = f"{sys}\n\n{tool_prompt}" if sys else tool_prompt
        if plan_context:
            sys = f"{sys}\n\n{plan_context}" if sys else plan_context

        msgs: list[ChatMessage] = []
        if sys:
            msgs.append(ChatMessage(role="system", content=sys))
        msgs.extend(self._history)
        msgs.append(ChatMessage(role="user", content=user_transcript))
        return msgs

    def _append_history(self, msg: ChatMessage) -> None:
        self._history.append(msg)
        # Trim oldest entries to keep memory bounded.
        if len(self._history) > self._history_limit:
            # Always preserve a leading system message if present in history.
            del self._history[: len(self._history) - self._history_limit]

    async def _run_tts(self, text: str) -> None:
        """Synthesize + stream TTS audio to the client."""
        if not text.strip():
            return
        tts = self._resolve_tts()
        # Track the active task so barge-in can cancel it.
        async def _stream() -> None:
            try:
                async for chunk in tts.synthesize_stream(
                    text, options=TTSOptions(voice_id=self._config.voice_id)
                ):
                    if self._stop_event.is_set() or self._turn_cancelled:
                        break
                    await self._callbacks.on_tts_chunk(chunk)
            except asyncio.CancelledError:
                raise

        self._tts_task = asyncio.create_task(_stream())
        try:
            await self._tts_task
        except asyncio.CancelledError:
            # Propagate so the wrapping turn task sees cancellation.
            raise
        finally:
            self._tts_task = None

    # -- provider resolution ----------------------------------------------

    def _resolve_asr(self) -> ASRProvider:
        if self._asr is not None:
            return self._asr
        return get_voice_manager().get_asr()

    def _resolve_tts(self) -> TTSProvider:
        if self._tts is not None:
            return self._tts
        return get_voice_manager().get_tts()

    def _resolve_llm(self) -> LLMProvider:
        if self._llm is not None:
            return self._llm
        if self._config.stub_llm:
            # Bypass the manager — always emit the stub text.
            from melo.llm.providers.stub import StubLLM

            return StubLLM(response=self._config.stub_llm_text)
        return get_llm_manager().get()

    # -- helpers -----------------------------------------------------------

    async def _cancel_turn(self, *, reason: str, emit_event: bool) -> None:
        """Cancel the in-flight turn task + TTS + set cancelled flag.

        * `reason` — one of the `INTERRUPT_REASON_*` constants. Used as
          the payload of `on_interruption` when `emit_event=True`.
        * `emit_event` — if True, calls `on_interruption(reason)` so the
          client can reset its UI. Set to False when the interruption is
          a side-effect of another event (e.g. the VAD end-of-utterance
          cancelling a previous turn) to avoid spamming interruption
          events during normal speech flow.
        """
        if not self._turn_cancelled:
            self._turn_cancelled = True
        if self._turn_task is not None and not self._turn_task.done():
            self._turn_task.cancel()
            try:
                await self._turn_task
            except (asyncio.CancelledError, Exception):
                pass
            self._turn_task = None
        await self._cancel_tts()
        if emit_event:
            await self._emit_interruption(reason)

    async def _cancel_tts(self) -> None:
        if self._tts_task is not None and not self._tts_task.done():
            self._tts_task.cancel()
            try:
                await self._tts_task
            except (asyncio.CancelledError, Exception):
                pass
            self._tts_task = None

    async def _set_state(self, state: AgentState) -> None:
        if self._state == state:
            return
        self._state = state
        if self._callbacks is not None:
            try:
                await self._callbacks.on_state(state)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("on_state callback failed: %s", exc)

    async def _emit_error(self, message: str) -> None:
        if self._callbacks is None:
            return
        try:
            await self._callbacks.on_error(message)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("on_error callback failed: %s", exc)

    async def _emit_interruption(self, reason: str) -> None:
        """Fire the interruption callback if implemented.

        Older callers might not implement `on_interruption` so we
        check hasattr rather than requiring it on the Protocol (the
        Protocol method includes a `...` default body which allows
        omission at runtime).
        """
        if self._callbacks is None:
            return
        cb = getattr(self._callbacks, "on_interruption", None)
        if cb is None:
            return
        try:
            await cb(reason)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("on_interruption callback failed: %s", exc)

    async def _emit_voice_changed(self, voice_id: str) -> None:
        """Fire the voice-changed callback so clients can sync their UI.

        Uses getattr for the same reason `_emit_interruption` does —
        older callback implementations may not implement the method.
        """
        if self._callbacks is None:
            return
        cb = getattr(self._callbacks, "on_voice_changed", None)
        if cb is None:
            return
        try:
            await cb(voice_id)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("on_voice_changed callback failed: %s", exc)

    async def _emit_planning(self, plan: dict) -> None:
        """Fire the planning callback so clients can surface a transient
        "正在规划…" indicator above the transcript.

        Uses getattr so older callback implementations (pre-Stage-16)
        that don't implement `on_planning` keep working.
        """
        if self._callbacks is None:
            return
        cb = getattr(self._callbacks, "on_planning", None)
        if cb is None:
            return
        try:
            await cb(plan)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("on_planning callback failed: %s", exc)

    # -- inline tool-call support -----------------------------------------

    def _build_tool_prompt(self) -> str | None:
        """Render the available-tools description for the system message.

        Returns None when no registry is attached or it holds no tools,
        so the LLM prompt stays clean in plain voice-only sessions.
        """
        if self._tools is None:
            return None
        available = self._tools.schemas()
        if not available:
            return None
        lines = "\n".join(
            f"{t['name']}: {t['description']}" for t in available
        )
        rules = (
            "[Voice tools available — call them inline with the "
            "[[tool_call: name]] protocol. Rules: "
            "emit [[tool_call: {\"tool\": \"<name>\", \"args\": {...}}]] "
            "for each call, and keep a short spoken confirmation around it.]"
        )
        return f"{rules}\n{lines}"

    def _parse_tool_calls(self, text: str) -> list[tuple[str, dict]]:
        """Extract (tool_name, args) pairs from inline tool-call blocks.

        Mirrors the AgentToolLoop wire protocol: each block is a JSON
        object with `tool` and `args` keys. Malformed blocks are skipped
        so a bad emission can't abort the turn.
        """
        calls: list[tuple[str, dict]] = []
        for raw in _TOOL_CALL_RE.findall(text):
            try:
                data = json.loads(raw.strip())
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict):
                continue
            name = data.get("tool")
            if not name:
                continue
            args = data.get("args")
            if not isinstance(args, dict):
                args = {}
            calls.append((name, args))
        return calls

    def _strip_tool_calls(self, text: str) -> str:
        """Remove all inline tool-call blocks, leaving readable text."""
        return _TOOL_CALL_RE.sub("", text)

    def _filter_tool_markers(self, token: str, *, on_block=None) -> str:
        """Strip inline tool-call markers from a streaming token.

        Tool-call blocks can be split across arbitrary token boundaries,
        so a per-turn buffer tracks an in-progress block. Normal text
        outside a block is passed through unchanged; block content is
        dropped. A block that opens and closes within one token is
        handled inline, and the tail after a closing marker is itself
        re-scanned in case it opens another block.

        When `on_block` is supplied it is called with each completed
        block body ('tool_call: {...}') so callers can act on a tool as
        soon as its marker closes — this is what enables tool-call
        streaming in `_run_llm`.
        """
        if self._tool_filter_buf:
            # Mid-block: keep buffering until the closing marker.
            self._tool_filter_buf += token
            if "]]" in self._tool_filter_buf:
                block, tail = self._tool_filter_buf.split("]]", 1)
                self._tool_filter_buf = ""
                if on_block:
                    on_block(block)
                return self._filter_tool_markers(tail, on_block=on_block)
            return ""
        if "[[" in token:
            head, rest = token.split("[[", 1)
            if "]]" in rest:
                block, tail = rest.split("]]", 1)
                if on_block:
                    on_block(block)
                return head + self._filter_tool_markers(tail, on_block=on_block)
            # Opening marker not closed in this token — buffer the rest.
            self._tool_filter_buf = rest
            return head
        return token

    async def _emit_tool_call(self, name: str, args: dict) -> None:
        if self._callbacks is None:
            return
        try:
            await self._callbacks.on_tool_call(name, args)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("on_tool_call callback failed: %s", exc)

    async def _emit_tool_result(self, name: str, result: dict) -> None:
        if self._callbacks is None:
            return
        try:
            await self._callbacks.on_tool_result(name, result)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("on_tool_result callback failed: %s", exc)

    async def _emit_tool_retry(
        self, name: str, attempt: int, max_retries: int, error: str
    ) -> None:
        """Surface a tool re-attempt so clients can show retry progress.

        Uses getattr so callback implementations that predate Stage 23
        (no `on_tool_retry`) keep working without a change.
        """
        if self._callbacks is None:
            return
        cb = getattr(self._callbacks, "on_tool_retry", None)
        if cb is None:
            return
        try:
            await cb(name, attempt, max_retries, error)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("on_tool_retry callback failed: %s", exc)

    async def _execute_tools(
        self, full_text: str, tool_calls: list[tuple[str, dict]]
    ) -> str:
        """Run every parsed tool call and return the text to speak.

        The spoken text is the marker-free remainder of the stream. When
        the model emitted only tool calls (no plain text), a short
        confirmation is synthesised from the tool results so the TTS
        still has something to say.

        Tool calls are executed in parallel via `asyncio.gather` so
        independent calls don't serialize. All `on_tool_call` events are
        emitted up-front (so the client can render pending indicators
        for every call without waiting), then `on_tool_result` streams
        as each call completes. Confirmations are reassembled in the
        original call order so the summary stays coherent. Cancellation
        (barge-in) propagates through gather to all in-flight tool tasks.

        This batch path is used when the full call list is already known
        (direct dispatch); the live-streaming path (`_on_stream_block`)
        executes calls as their markers close mid-stream. Both share
        `_exec_core` so execution semantics stay identical.
        """
        display_text = self._strip_tool_calls(full_text).strip()
        if self._tools is None:
            # No registry attached — just surface the readable text.
            return display_text

        # Emit every tool-call event up-front so clients can show all
        # pending calls immediately rather than waiting for each to
        # finish before the next is announced.
        for name, args in tool_calls:
            await self._emit_tool_call(name, args)

        async def _run_ordered(idx: int, name: str, args: dict) -> tuple[int, dict]:
            raw = await self._exec_core(name, args)
            return idx, raw

        # All calls are independent (no inter-call dependencies yet),
        # so gather runs them concurrently. If any raises CancelledError
        # (barge-in), gather cancels the rest and re-raises so the turn
        # task unwinds cleanly.
        pairs = await asyncio.gather(
            *(_run_ordered(i, name, args) for i, (name, args) in enumerate(tool_calls))
        )

        # Reassemble confirmations in the ORIGINAL call order so the
        # spoken summary is deterministic and matches the call sequence
        # the client saw via on_tool_call.
        results_by_idx = dict(pairs)
        confirmations = [
            self._summarize_tool_result(name, results_by_idx[i])
            for i, (name, _args) in enumerate(tool_calls)
        ]

        if display_text:
            return display_text
        return " ".join(confirmations)

    def _parse_single_tool_block(self, block: str) -> tuple[str, dict] | None:
        """Parse one completed 'tool_call: {...}' block into (name, args).

        Returns None for a malformed block so a bad emission can't abort
        the turn — the same tolerance as `_parse_tool_calls`.
        """
        marker = "tool_call:"
        pos = block.find(marker)
        if pos == -1:
            return None
        try:
            data = json.loads(block[pos + len(marker):].strip())
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        name = data.get("tool")
        if not name:
            return None
        args = data.get("args")
        if not isinstance(args, dict):
            args = {}
        return name, args

    def _on_stream_block(self, block: str) -> None:
        """Mid-stream hook — a tool-call block just closed.

        Records the call in order and launches its execution immediately
        so the tool runs while the LLM is still generating the rest of
        its response, rather than waiting for the full stream. Tasks are
        fire-and-forget here; `_finish_streamed_tools` awaits them after
        the stream ends so the turn completes with every result in hand.
        """
        parsed = self._parse_single_tool_block(block)
        if parsed is None:
            return
        name, args = parsed
        idx = len(self._stream_tool_calls)
        self._stream_tool_calls.append((name, args))
        if self._tools is None:
            return
        task = asyncio.create_task(self._exec_one_stream(idx, name, args))
        self._stream_tool_tasks.append(task)

    async def _exec_one_stream(
        self, idx: int, name: str, args: dict
    ) -> tuple[int, dict]:
        """Streaming execution: announce the call, run it, stream result."""
        await self._emit_tool_call(name, args)
        raw = await self._exec_core(name, args)
        return idx, raw

    async def _exec_retry_listener(
        self, name: str, attempt: int, max_retries: int, error: str
    ) -> None:
        """Stage 23: bridge registry retry progress to the wire protocol."""
        await self._emit_tool_retry(name, attempt, max_retries, error)

    async def _exec_core(self, name: str, args: dict) -> dict:
        """Execute one tool and produce its wire result (never raises).

        Failure retry (Stage 23) runs inside the registry's `execute`:
        tools declaring `retry > 0` are re-attempted with exponential
        backoff, and each re-attempt is surfaced via `on_tool_retry`.
        A tool that still fails after all attempts yields an `ok:False`
        result so the turn degrades gracefully instead of aborting.
        """
        try:
            raw = await self._tools.execute(
                name, on_retry=self._exec_retry_listener, **args
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raw = {"ok": False, "error": str(exc)}
        if not isinstance(raw, dict) or "ok" not in raw:
            raw = {"ok": True, "result": raw}
        # Stream the result as soon as this call completes — clients
        # receive results in completion order, not submission order.
        await self._emit_tool_result(name, raw)
        return raw

    async def _finish_streamed_tools(self, full_text: str) -> str:
        """Await tools launched mid-stream and build the spoken text.

        Reassembles confirmations in the order the calls were announced
        (call order), and keeps the readable text when the model emitted
        any. Falls back to the raw text when no tools were scheduled.
        """
        display_text = self._strip_tool_calls(full_text).strip()
        if not self._stream_tool_tasks:
            return display_text or full_text
        pairs = await asyncio.gather(*self._stream_tool_tasks)
        results_by_idx = dict(pairs)
        confirmations = [
            self._summarize_tool_result(name, results_by_idx[i])
            for i, (name, _args) in enumerate(self._stream_tool_calls)
        ]
        if display_text:
            return display_text
        return " ".join(confirmations)

    def _cancel_stream_tools(self) -> None:
        """Cancel any tool tasks still running when a turn is aborted."""
        for task in self._stream_tool_tasks:
            if not task.done():
                task.cancel()

    @staticmethod
    def _summarize_tool_result(name: str, result: dict) -> str:
        """Build a short spoken confirmation from a tool result.

        Stage 23 error fallback: an `ok:False` result is spoken as a
        graceful failure notice (with the error text when present) so
        the turn degrades honestly instead of claiming success.
        """
        if isinstance(result, dict):
            if result.get("ok") is False:
                error = result.get("error")
                if error:
                    return f"[工具 {name} 执行失败: {error}]"
                return f"[工具 {name} 执行失败]"
            for key in ("message", "text", "name", "status"):
                val = result.get(key)
                if isinstance(val, str) and val:
                    return f"[工具 {name}: {val}]"
        return f"[工具 {name} 已执行]"
