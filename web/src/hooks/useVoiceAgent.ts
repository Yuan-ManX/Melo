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
  const handleEvent = useCallback((event: ServerEvent) => {
    switch (event.type) {
      case 'connected':
        setError(null)
        setAgentState('listening')
        onEventRef.current?.(event)
        break
      case 'agent_state':
        setAgentState(event.state)
        onEventRef.current?.(event)
        break
      case 'asr_partial':
      case 'asr_final':
      case 'llm_chunk':
      case 'error':
      case 'tool_call':
      case 'tool_result':
        // Forward only — transcript / chat logic is the caller's job.
        onEventRef.current?.(event)
        break
      default:
        // Unexpected event type — no-op.
        break
    }
  }, [])

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
  }, [capture, ws, playback])

  const toggleMic = useCallback(() => {
    if (capture.recording) {
      capture.stop()
    } else {
      void capture.start()
    }
  }, [capture])

  const bargeIn = useCallback(() => {
    ws.bargeIn()
  }, [ws])

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
    ws,
    capture,
    playback,
  }
}
