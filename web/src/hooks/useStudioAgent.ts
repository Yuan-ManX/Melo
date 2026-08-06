/**
 * useStudioAgent — manages the Melo studio-assistant WebSocket connection.
 *
 * This hook drives the natural-language control channel between the studio
 * chat panel and the backend agent. Wire protocol (JSON text frames):
 *
 *   Client → Server:
 *     { type: "chat", text, project_id? }
 *     { type: "reset" }
 *
 *   Server → Client:
 *     { type: "connected", agent_id, agent_name }
 *     { type: "llm_chunk", text }
 *     { type: "tool_call", name, args, result }
 *     { type: "done" }
 *     { type: "error", message }
 *
 * The hook owns the WebSocket lifecycle and re-establishes the connection
 * whenever the target agent changes. It does not render anything — the
 * caller supplies an `onEvent` callback to consume parsed events.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * A normalized studio agent event. Only the fields relevant to a given
 * `type` are populated; the rest stay undefined.
 */
export interface StudioAgentEvent {
  type: 'connected' | 'llm_chunk' | 'tool_call' | 'done' | 'error'
  text?: string
  name?: string
  agent_id?: string
  agent_name?: string
  args?: unknown
  result?: unknown
  message?: string
}

interface UseStudioAgentOptions {
  agentId: string | null
  onEvent?: (e: StudioAgentEvent) => void
}

interface UseStudioAgentApi {
  connected: boolean
  sendChat: (text: string, projectId?: string) => void
  reset: () => void
  close: () => void
}

/**
 * Build the WebSocket URL. In dev, Vite proxies `/api` to the backend on
 * :7200, so we use a relative URL against the current host.
 */
function buildUrl(agentId: string): string {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}/api/ws/studio/${encodeURIComponent(agentId)}`
}

export function useStudioAgent(opts: UseStudioAgentOptions): UseStudioAgentApi {
  const { agentId, onEvent } = opts
  const [connected, setConnected] = useState(false)

  // Keep the latest callback in a ref so the WebSocket listeners, which are
  // attached once per connection, always invoke the freshest handler.
  const onEventRef = useRef(onEvent)
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    onEventRef.current = onEvent
  }, [onEvent])

  const handleMessage = useCallback((event: MessageEvent) => {
    if (typeof event.data !== 'string') return
    let raw: unknown
    try {
      raw = JSON.parse(event.data)
    } catch {
      // Ignore malformed payloads — the server always sends valid JSON.
      return
    }
    const msg = raw as Record<string, unknown>
    const type = msg['type']

    if (type === 'connected') {
      setConnected(true)
      onEventRef.current?.({
        type: 'connected',
        agent_id: msg['agent_id'] as string | undefined,
        agent_name: msg['agent_name'] as string | undefined,
      })
    } else if (type === 'llm_chunk') {
      onEventRef.current?.({
        type: 'llm_chunk',
        text: msg['text'] as string | undefined,
      })
    } else if (type === 'tool_call') {
      onEventRef.current?.({
        type: 'tool_call',
        name: msg['name'] as string | undefined,
        args: msg['args'],
        result: msg['result'],
      })
    } else if (type === 'done') {
      onEventRef.current?.({ type: 'done' })
    } else if (type === 'error') {
      onEventRef.current?.({
        type: 'error',
        message: msg['message'] as string | undefined,
      })
    }
  }, [])

  // Establish a fresh connection whenever the agent changes.
  useEffect(() => {
    if (!agentId) return

    let ws: WebSocket | null = null
    try {
      ws = new WebSocket(buildUrl(agentId))
    } catch {
      setConnected(false)
      return
    }

    ws.onopen = () => setConnected(true)
    ws.onclose = () => setConnected(false)
    ws.onerror = () => setConnected(false)
    ws.onmessage = handleMessage
    wsRef.current = ws

    // Tear down the socket when the agent changes or the component unmounts.
    return () => {
      if (ws) {
        ws.onopen = null
        ws.onmessage = null
        ws.onclose = null
        ws.onerror = null
        ws.close()
      }
      if (wsRef.current === ws) wsRef.current = null
      setConnected(false)
    }
  }, [agentId, handleMessage])

  const sendChat = useCallback((text: string, projectId?: string) => {
    const ws = wsRef.current
    if (!ws || ws.readyState !== WebSocket.OPEN) return
    ws.send(
      JSON.stringify({
        type: 'chat',
        text,
        ...(projectId ? { project_id: projectId } : {}),
      }),
    )
  }, [])

  const reset = useCallback(() => {
    const ws = wsRef.current
    if (!ws || ws.readyState !== WebSocket.OPEN) return
    ws.send(JSON.stringify({ type: 'reset' }))
  }, [])

  const close = useCallback(() => {
    const ws = wsRef.current
    if (ws) {
      ws.onopen = null
      ws.onmessage = null
      ws.onclose = null
      ws.onerror = null
      ws.close()
      wsRef.current = null
    }
    setConnected(false)
  }, [])

  return { connected, sendChat, reset, close }
}