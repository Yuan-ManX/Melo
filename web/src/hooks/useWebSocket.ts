/**
 * useWebSocket — manages the Melo voice WebSocket connection.
 *
 * Responsibilities:
 *   - Open / close the connection to `/api/ws/voice/{agentId}?token=...`.
 *   - Dispatch incoming text JSON events to a handler callback.
 *   - Dispatch incoming binary frames (TTS audio) to a separate handler.
 *   - Expose `sendControl` (JSON) and `sendAudio` (binary PCM) helpers.
 *   - Track connection state for UI feedback.
 *
 * The hook does NOT know about audio capture or playback — those concerns
 * belong to `useAudioCapture` / `useAudioPlayback`. Composition is via
 * the `onEvent` / `onAudio` callbacks.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import type { ClientControlMessage, ServerEvent } from '../types/ws'

export type WsConnectionState = 'idle' | 'connecting' | 'open' | 'closed' | 'error'

interface UseWebSocketOptions {
  agentId: string | null
  // Auth is disabled — token is ignored and may be omitted.
  token?: string | null
  onEvent?: (event: ServerEvent) => void
  onAudio?: (audio: ArrayBuffer) => void
  // Disable auto-connect (e.g. until the user clicks "start"); default false.
  manual?: boolean
}

interface UseWebSocketApi {
  state: WsConnectionState
  error: string | null
  connect: () => void
  disconnect: () => void
  sendControl: (msg: ClientControlMessage) => void
  sendAudio: (pcm: ArrayBuffer) => void
  /** Send the barge_in control message — convenience wrapper. */
  bargeIn: () => void
}

/**
 * Build the WebSocket URL. In dev, Vite proxies `/api` and `/ws` to the
 * backend on :7200, so we just use a relative URL.
 */
function buildUrl(agentId: string, token: string): string {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  // Token is ignored by the server (auth disabled); we still append it
  // when present so the URL shape stays stable for future re-enablement.
  const tokenQuery = token ? `?token=${encodeURIComponent(token)}` : ''
  return `${proto}//${window.location.host}/api/ws/voice/${agentId}${tokenQuery}`
}

export function useWebSocket(opts: UseWebSocketOptions): UseWebSocketApi {
  const { agentId, token, onEvent, onAudio, manual } = opts
  const [state, setState] = useState<WsConnectionState>('idle')
  const [error, setError] = useState<string | null>(null)

  // Keep refs to the latest callbacks so the WebSocket listeners, which
  // are attached once, always call the freshest handler.
  const onEventRef = useRef(onEvent)
  const onAudioRef = useRef(onAudio)
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    onEventRef.current = onEvent
  }, [onEvent])
  useEffect(() => {
    onAudioRef.current = onAudio
  }, [onAudio])

  const handleOpen = useCallback(() => {
    setState('open')
    setError(null)
  }, [])

  const handleMessage = useCallback((event: MessageEvent) => {
    if (typeof event.data === 'string') {
      try {
        const parsed: unknown = JSON.parse(event.data)
        onEventRef.current?.(parsed as ServerEvent)
      } catch {
        // Ignore malformed payloads — server should always send valid JSON.
      }
    } else if (event.data instanceof ArrayBuffer) {
      onAudioRef.current?.(event.data)
    } else if (event.data instanceof Blob) {
      // Some browsers deliver binary as Blob — convert to ArrayBuffer.
      event.data
        .arrayBuffer()
        .then((buf) => onAudioRef.current?.(buf))
        .catch(() => {
          /* swallow — caller will simply miss this chunk */
        })
    }
  }, [])

  const handleClose = useCallback(() => {
    setState('closed')
  }, [])

  const handleError = useCallback(() => {
    setState('error')
    setError('WebSocket connection failed')
  }, [])

  const connect = useCallback(() => {
    if (!agentId) {
      setError('Missing agentId')
      setState('error')
      return
    }
    // Tear down any previous socket.
    if (wsRef.current) {
      try {
        wsRef.current.onopen = null
        wsRef.current.onmessage = null
        wsRef.current.onclose = null
        wsRef.current.onerror = null
        wsRef.current.close()
      } catch {
        /* ignore */
      }
      wsRef.current = null
    }
    setState('connecting')
    setError(null)
    const ws = new WebSocket(buildUrl(agentId, token ?? ''))
    ws.binaryType = 'arraybuffer'
    ws.onopen = handleOpen
    ws.onmessage = handleMessage
    ws.onclose = handleClose
    ws.onerror = handleError
    wsRef.current = ws
  }, [agentId, token, handleOpen, handleMessage, handleClose, handleError])

  const disconnect = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.onclose = null
      wsRef.current.close()
      wsRef.current = null
    }
    setState('idle')
  }, [])

  const sendControl = useCallback((msg: ClientControlMessage) => {
    const ws = wsRef.current
    if (!ws || ws.readyState !== WebSocket.OPEN) return
    ws.send(JSON.stringify(msg))
  }, [])

  const sendAudio = useCallback((pcm: ArrayBuffer) => {
    const ws = wsRef.current
    if (!ws || ws.readyState !== WebSocket.OPEN) return
    // Binary frame → raw PCM on the wire.
    ws.send(pcm)
  }, [])

  const bargeIn = useCallback(() => {
    sendControl({ type: 'barge_in' })
  }, [sendControl])

  // Auto-connect unless the caller opted into manual mode.
  useEffect(() => {
    if (manual) return
    if (!agentId) return
    connect()
    return () => {
      if (wsRef.current) {
        wsRef.current.onclose = null
        wsRef.current.close()
        wsRef.current = null
      }
    }
  }, [agentId, manual, connect])

  return { state, error, connect, disconnect, sendControl, sendAudio, bargeIn }
}
