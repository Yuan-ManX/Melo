"""VoiceAgentRuntime — full-duplex voice conversation loop.

Pipeline:

    VAD  ──▶  ASR  ──▶  LLM  ──▶  TTS  ──▶  audio out
           │                                ▲
           │ barge-in cancels ASR / LLM / TTS
           └────────────────────────────────┘

The runtime resolves ASR / TTS / LLM providers lazily through their
respective plugin managers (`melo.voice.manager`, `melo.llm.manager`),
so the configured provider is loaded on first use rather than at
construction time. Set `RuntimeConfig.stub_llm=True` to force the
StubLLM provider for CI / dev without API keys; otherwise the real
LLM provider from `melo.config.settings.llm_provider` is used.

Barge-in is the single most-important interaction primitive for a
human-like voice agent. The runtime tracks an in-flight `_turn_task`
(in addition to the legacy `_tts_task`) so any point of the pipeline
(ASR / LLM / TTS) can be cancelled as soon as the user starts talking.
Barge-in is guarded by a `min_speech_for_barge_ms` threshold so short
glitches (cough, mic pop, background laugh) don't abort turns.

Wire protocol produced by `RuntimeCallbacks`:

    agent_state(listening | thinking | speaking)
    asr_partial(text)
    asr_final(text)
    llm_chunk(text)
    tts_chunk(bytes)
    error(message)
    interruption(reason)   ← fired when a turn is cancelled mid-flight
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
#: first closing `]]` terminates the block, mirroring the AgentToolLoop
#: wire protocol so the voice channel and the studio share one format.
_TOOL_CALL_RE = re.compile(r"\[\[tool_call:\s*(.+?)\]\]", flags=re.DOTALL)


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

    async def on_interruption(self, reason: str) -> None: ...

    async def on_voice_changed(self, voice_id: str) -> None: ...


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
    ) -> None:
        self.agent_id = agent_id
        self._callbacks = callbacks
        self._config = config or RuntimeConfig()
        self._memory = memory
        self._tools = tools

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
        # the streaming LLM output (see `_filter_tool_markers`).
        self._tool_filter_buf = ""

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
        """Attach a tool registry the LLM can invoke inline via tool_call."""
        self._tools = tools

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
            llm_text = await self._run_llm(transcript)
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

    async def _run_llm(self, transcript: str) -> str:
        """Produce LLM response, emit llm_chunk events.

        Builds the chat messages from the conversation history + the new
        user transcript, streams tokens from the LLM provider, emits
        each token as `on_llm_chunk`, and (on a non-cancelled turn)
        accumulates the full text back into history.
        """
        llm = self._resolve_llm()
        facts = await self.recall_for_turn(transcript)
        tool_prompt = self._build_tool_prompt()
        messages = self._build_messages(
            transcript, memory_facts=facts, tool_prompt=tool_prompt
        )
        options = LLMOptions(
            model=self._config.llm_model,
            temperature=self._config.llm_temperature,
            max_tokens=self._config.llm_max_tokens,
        )

        full_text_parts: list[str] = []
        try:
            async for token in llm.stream_chat(messages, options=options):
                if self._turn_cancelled:
                    # Stop emitting chunks mid-stream so the client
                    # never sees a half-finished response.
                    break
                if not token:
                    continue
                # Keep the raw token for parsing tool-call blocks, but emit a
                # marker-free version so the client / TTS never speaks protocol.
                full_text_parts.append(token)
                await self._callbacks.on_llm_chunk(self._filter_tool_markers(token))
        except asyncio.CancelledError:
            self._turn_cancelled = True
            raise

        if self._turn_cancelled:
            return ""
        full_text = "".join(full_text_parts).strip()
        tool_calls = self._parse_tool_calls(full_text)
        if tool_calls:
            llm_text = await self._execute_tools(full_text, tool_calls)
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
    ) -> list[ChatMessage]:
        """Assemble the message list for the LLM call.

        Order: [system?] + history (excluding the just-added user
        message — it's appended here) + new user message.

        When `memory_facts` are supplied they are appended to the system
        content as a long-term-memory block, so the base system_prompt
        remains intact and recall is folded in as supplementary context.
        A `tool_prompt` (when present) is appended after the memory block
        so the LLM knows it may emit inline tool-call blocks.
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

    def _filter_tool_markers(self, token: str) -> str:
        """Strip inline tool-call markers from a streaming token.

        Tool-call blocks can be split across arbitrary token boundaries,
        so a per-turn buffer tracks an in-progress block. Normal text
        outside a block is passed through unchanged; block content is
        dropped. A block that opens and closes within one token is
        handled inline, and the tail after a closing marker is itself
        re-scanned in case it opens another block.
        """
        if self._tool_filter_buf:
            # Mid-block: keep buffering until the closing marker.
            self._tool_filter_buf += token
            if "]]" in self._tool_filter_buf:
                tail = self._tool_filter_buf.split("]]", 1)[1]
                self._tool_filter_buf = ""
                return self._filter_tool_markers(tail)
            return ""
        if "[[" in token:
            head, rest = token.split("[[", 1)
            if "]]" in rest:
                tail = rest.split("]]", 1)[1]
                return head + self._filter_tool_markers(tail)
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

    async def _execute_tools(
        self, full_text: str, tool_calls: list[tuple[str, dict]]
    ) -> str:
        """Run every parsed tool call and return the text to speak.

        The spoken text is the marker-free remainder of the stream. When
        the model emitted only tool calls (no plain text), a short
        confirmation is synthesised from the tool results so the TTS
        still has something to say.
        """
        display_text = self._strip_tool_calls(full_text).strip()
        if self._tools is None:
            # No registry attached — just surface the readable text.
            return display_text

        confirmations: list[str] = []
        for name, args in tool_calls:
            await self._emit_tool_call(name, args)
            try:
                result = await self._tools.execute(name, **args)
            except Exception as exc:
                result = {"ok": False, "error": str(exc)}
            if not isinstance(result, dict) or "ok" not in result:
                result = {"ok": True, "result": result}
            await self._emit_tool_result(name, result)
            confirmations.append(self._summarize_tool_result(name, result))

        if display_text:
            return display_text
        return " ".join(confirmations)

    @staticmethod
    def _summarize_tool_result(name: str, result: dict) -> str:
        """Build a short spoken confirmation from a tool result."""
        if isinstance(result, dict):
            for key in ("message", "text", "name", "status"):
                val = result.get(key)
                if isinstance(val, str) and val:
                    return f"[工具 {name}: {val}]"
        return f"[工具 {name} 已执行]"
