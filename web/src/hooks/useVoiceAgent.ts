/**
 * useVoiceAgent — composes WebSocket + mic capture + TTS playback into a
 * single voice-agent session hook.
 *
 * Responsibilities:
 *   - Drive connection / session lifecycle (start, stop).
 *   - Track agent runtime state (idle / listening / thinking / speaking).
 *   - Wire mic PCM chunks → WebSocket, and WebSocket TTS bytes → playback.
 *   - Forward all server events (and raw audio) to optional caller hooks so
 *     transcript / chat-store logic can live in the consumer.
 *
 * The hook does NOT track transcripts or LLM text — that is the caller's
 * job (via `onEvent`). It only manages session + agent state.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import type { AgentRuntimeState, ServerEvent } from '../types/ws'
import { useAudioCapture } from './useAudioCapture'
import { useAudioPlayback } from './useAudioPlayback'
import { useWebSocket } from './useWebSocket'

interface UseVoiceAgentOptions {
  agentId: string | null
  // Optional override hooks for callers that want to observe events
  // (e.g. to push transcripts into a store). All optional.
  onEvent?: (event: ServerEvent) => void
  onAudio?: (audio: ArrayBuffer) => void
}

interface UseVoiceAgentApi {
  // Connection / agent state
  connectionState: 'idle' | 'connecting' | 'open' | 'closed' | 'error'
  agentState: AgentRuntimeState
  error: string | null
  // Session
  sessionActive: boolean
  start: () => Promise<void>
  stop: () => void
  // Mic
  micRecording: boolean
  toggleMic: () => void
  // Barge-in
  bargeIn: () => void
  canBargeIn: boolean
  // Most recent interruption reason — callers can show a transient
  // "interrupted" indicator in the UI. Cleared on the next agent_state
  // transition so the flag stays visible for the brief moment between
  // the interruption event and the new listening state.
  lastInterruption: 'barge_in' | 'client_stop' | null
  // Active voice_id — initialised from the connected event, kept in
  // sync with `voice_changed` events. null when no voice is configured.
  // Callers can pass this to a voice picker dropdown's value prop.
  activeVoiceId: string | null
  // Switch the runtime's TTS voice mid-session. Sends a `set_voice`
  // control message; the server echoes back `voice_changed`, which
  // updates `activeVoiceId`. Optimistic local update hides network
  // latency in the UI.
  setVoice: (voiceId: string) => void
  // Raw WS / capture / playback (escape hatches)
  ws: ReturnType<typeof useWebSocket>
  capture: ReturnType<typeof useAudioCapture>
  playback: ReturnType<typeof useAudioPlayback>
}

export function useVoiceAgent(opts: UseVoiceAgentOptions): UseVoiceAgentApi {
  const { agentId, onEvent, onAudio } = opts

  const [agentState, setAgentState] = useState<AgentRuntimeState>('idle')
  const [sessionActive, setSessionActive] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [lastInterruption, setLastInterruption] = useState<
    'barge_in' | 'client_stop' | null
  >(null)
  const [activeVoiceId, setActiveVoiceId] = useState<string | null>(null)

  // Keep refs to the latest caller callbacks so the handlers we hand to
  // useWebSocket (attached once) always see the freshest values.
  const onEventRef = useRef(onEvent)
  const onAudioRef = useRef(onAudio)
  useEffect(() => {
    onEventRef.current = onEvent
  }, [onEvent])
  useEffect(() => {
    onAudioRef.current = onAudio
  }, [onAudio])

  // -- TTS playback (must exist before handleAudio) ----------------------
  const playback = useAudioPlayback()

  // -- WebSocket event handling ------------------------------------------
  const handleEvent = useCallback(
    (event: ServerEvent) => {
      switch (event.type) {
        case 'connected':
          setError(null)
          setAgentState('listening')
          setLastInterruption(null)
          // Seed the active voice from the agent's configured voice_id
          // so the voice picker shows the correct initial selection.
          setActiveVoiceId(event.voice_id ?? null)
          onEventRef.current?.(event)
          break
        case 'agent_state':
          setAgentState(event.state)
          // Clear the interruption indicator once we're back in a
          // non-thinking/non-speaking state — by then the UI should
          // show the new state and the brief "interrupted" flash is
          // no longer relevant.
          if (event.state === 'listening' || event.state === 'idle') {
            setLastInterruption(null)
          }
          onEventRef.current?.(event)
          break
        case 'interruption':
          // The server cancelled the in-flight turn. Hard-flush the
          // playback queue so any buffered TTS audio is silenced
          // immediately — without this the user would hear ghost
          // playback for ~200-500ms until the server's stop signal
          // arrives via the next TTS frame boundary.
          playback.flush()
          setLastInterruption(event.reason)
          onEventRef.current?.(event)
          break
        case 'voice_changed':
          // Server confirmed a voice switch (either from our own
          // `set_voice` message or from an agent tool). Update the
          // local state so the picker reflects the active voice.
          setActiveVoiceId(event.voice_id)
          onEventRef.current?.(event)
          break
        case 'asr_partial':
        case 'asr_final':
        case 'llm_chunk':
        case 'error':
        case 'tool_call':
        case 'tool_result':
        case 'tool_retry':
        case 'planning':
        case 'studio_changed':
          // Forward only — transcript / chat logic is the caller's job.
          onEventRef.current?.(event)
          break
        default:
          // Unexpected event type — no-op.
          break
      }
    },
    [playback],
  )

  const handleAudio = useCallback(
    (audio: ArrayBuffer) => {
      void playback.play(audio)
      onAudioRef.current?.(audio)
    },
    [playback.play],
  )

  const ws = useWebSocket({
    agentId,
    manual: true, // start the socket only when the user begins a session
    onEvent: handleEvent,
    onAudio: handleAudio,
  })

  // -- audio capture -----------------------------------------------------
  const onChunk = useCallback(
    (pcm: ArrayBuffer) => {
      ws.sendAudio(pcm)
    },
    [ws.sendAudio],
  )
  const capture = useAudioCapture({ onChunk })

  // -- session control ---------------------------------------------------
  const start = useCallback(async () => {
    if (!agentId) {
      setError('Missing agentId')
      return
    }
    setError(null)
    setLastInterruption(null)
    // activeVoiceId is seeded from the `connected` event — clear it
    // here so a stale voice from a previous session doesn't leak into
    // the picker while the new connection is being established.
    setActiveVoiceId(null)
    ws.connect()
    try {
      await capture.start()
      setSessionActive(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setSessionActive(false)
    }
  }, [agentId, ws, capture])

  const stop = useCallback(() => {
    capture.stop()
    ws.disconnect()
    playback.flush()
    setSessionActive(false)
    setAgentState('idle')
    setLastInterruption(null)
    setActiveVoiceId(null)
  }, [capture, ws, playback])

  const toggleMic = useCallback(() => {
    if (capture.recording) {
      capture.stop()
    } else {
      void capture.start()
    }
  }, [capture])

  const bargeIn = useCallback(() => {
    // Optimistic local flush — the server-side cancellation can take
    // a network round-trip (10-100ms typical), during which the user
    // would still hear the in-flight TTS audio. Flushing locally first
    // gives instant silence; the server's `interruption` event later
    // arrives and re-flushes (idempotent) for symmetry.
    playback.flush()
    ws.bargeIn()
    setLastInterruption('barge_in')
  }, [ws, playback])

  const setVoice = useCallback(
    (voiceId: string) => {
      // Optimistic local update so the picker UI snaps to the new
      // selection immediately. The server's `voice_changed` event
      // later confirms + re-sets the same value (idempotent).
      setActiveVoiceId(voiceId)
      ws.sendControl({ type: 'set_voice', voice_id: voiceId })
    },
    [ws],
  )

  const canBargeIn = agentState === 'thinking' || agentState === 'speaking'

  // Cleanup on unmount — stop everything. The individual hooks also clean
  // themselves up, but we explicitly disconnect the WS (manual mode does
  // not auto-close) and tear down capture / playback for good measure.
  useEffect(() => {
    return () => {
      capture.stop()
      ws.disconnect()
      playback.dispose()
    }
  }, [capture.stop, ws.disconnect, playback.dispose])

  return {
    connectionState: ws.state,
    agentState,
    error,
    sessionActive,
    start,
    stop,
    micRecording: capture.recording,
    toggleMic,
    bargeIn,
    canBargeIn,
    lastInterruption,
    activeVoiceId,
    setVoice,
    ws,
    capture,
    playback,
  }
}
