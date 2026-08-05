"""VoiceAgentRuntime — full-duplex voice conversation loop.

Pipeline:

    VAD  ──▶  ASR  ──▶  LLM  ──▶  TTS  ──▶  audio out
                                ▲
                                │ barge-in interrupts TTS

The runtime resolves ASR / TTS / LLM providers lazily through their
respective plugin managers (`melo.voice.manager`, `melo.llm.manager`),
so the configured provider is loaded on first use rather than at
construction time. Set `RuntimeConfig.stub_llm=True` to force the
StubLLM provider for CI / dev without API keys; otherwise the real
LLM provider from `melo.config.settings.llm_provider` is used.

Wire protocol produced by `RuntimeCallbacks`:

    agent_state(listening | thinking | speaking)
    asr_partial(text)
    asr_final(text)
    llm_chunk(text)
    tts_chunk(bytes)
    error(message)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import AsyncIterator, Awaitable, Callable, Optional, Protocol

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


# Type aliases for clarity.
AudioFeeder = Callable[[], Awaitable[Optional[bytes]]]
"""Async callable that returns the next audio chunk, or None on EOF."""


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
      * `barge_in()` interrupts the current TTS playback and resets to
        LISTENING.
      * `stop()` drains all in-flight tasks and resets state to IDLE.
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
    ) -> None:
        self.agent_id = agent_id
        self._callbacks = callbacks
        self._config = config or RuntimeConfig()

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
        self._main_task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._speech_active = False
        # Conversation history — accumulates user + assistant turns so
        # the LLM sees prior context. Bounded by `history_limit`.
        self._history: list[ChatMessage] = list(history or [])
        self._history_limit = 32

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
        """Stop the runtime, drain in-flight TTS, and reset state."""
        self._stop_event.set()
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
        """User interrupted Agent — abort TTS, drop pending turn, go LISTENING."""
        await self._cancel_tts()
        self._current_turn = None
        await self._set_state(AgentState.LISTENING)

    # -- main loop ---------------------------------------------------------

    async def _run_loop(self) -> None:
        """Consume audio from the queue, feed VAD, drive turn lifecycle."""
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
                    # Make sure we're in LISTENING while user is talking.
                    if self._state == AgentState.SPEAKING:
                        # Implicit barge-in: user started speaking during TTS.
                        await self._cancel_tts()
                    await self._set_state(AgentState.LISTENING)
                elif event.kind == "end":
                    self._speech_active = False
                    # Hand off accumulated audio to the turn processor.
                    turn = self._current_turn
                    self._current_turn = None
                    if turn is not None and len(turn.audio) > 0:
                        # Spawn turn processing in the background so the
                        # VAD loop keeps listening for the next utterance.
                        asyncio.create_task(self._process_turn(turn))
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
        """ASR → LLM → TTS for one user utterance."""
        try:
            transcript = await self._run_asr(turn)
            if transcript:
                await self._callbacks.on_asr_final(transcript)
            else:
                # Nothing recognised — back to listening.
                await self._set_state(AgentState.LISTENING)
                return

            await self._set_state(AgentState.THINKING)
            llm_text = await self._run_llm(transcript)

            await self._set_state(AgentState.SPEAKING)
            await self._run_tts(llm_text)
        except (VoiceProviderUnavailable, LLMProviderUnavailable) as exc:
            logger.warning("Provider unavailable: %s", exc)
            await self._emit_error(f"provider unavailable: {exc}")
            await self._set_state(AgentState.LISTENING)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Turn processing failed")
            await self._emit_error(f"turn failed: {exc}")
            await self._set_state(AgentState.LISTENING)
        finally:
            if self._state == AgentState.SPEAKING:
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
        each token as `on_llm_chunk`, and accumulates the full text
        back into history.
        """
        llm = self._resolve_llm()
        messages = self._build_messages(transcript)
        options = LLMOptions(
            model=self._config.llm_model,
            temperature=self._config.llm_temperature,
            max_tokens=self._config.llm_max_tokens,
        )

        full_text_parts: list[str] = []
        async for token in llm.stream_chat(messages, options=options):
            if not token:
                continue
            full_text_parts.append(token)
            await self._callbacks.on_llm_chunk(token)

        full_text = "".join(full_text_parts).strip()
        # Persist the turn into history so the next turn sees context.
        self._append_history(ChatMessage(role="user", content=transcript))
        if full_text:
            self._append_history(ChatMessage(role="assistant", content=full_text))
        return full_text

    def _build_messages(self, user_transcript: str) -> list[ChatMessage]:
        """Assemble the message list for the LLM call.

        Order: [system?] + history (excluding the just-added user
        message — it's appended here) + new user message.
        """
        msgs: list[ChatMessage] = []
        if self._config.system_prompt:
            msgs.append(ChatMessage(role="system", content=self._config.system_prompt))
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
                    text, options=TTSOptions()
                ):
                    if self._stop_event.is_set():
                        break
                    await self._callbacks.on_tts_chunk(chunk)
            except asyncio.CancelledError:
                raise

        self._tts_task = asyncio.create_task(_stream())
        try:
            await self._tts_task
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
