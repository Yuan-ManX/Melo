/**
 * VoiceConversation — orchestrator for the voice chat session.
 *
 * Wires the `useVoiceAgent` hook (WS + capture + playback) to the chat
 * sub-components. Owns the transcript / ASR partial / LLM streaming text
 * state and the auto-scroll ref, since those are chat-panel concerns.
 *
 * The hook drives connection / agent state; this component drives the
 * transcript via the `onEvent` callback forwarded to the hook.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import { useVoiceAgent } from '../../hooks/useVoiceAgent'
import type { Agent } from '../../types'
import type { ServerEvent } from '../../types/ws'
import { AgentStatus } from '../chat/AgentStatus'
import { ChatPanel } from '../chat/ChatPanel'
import type { TranscriptEntry } from '../chat/MessageBubble'
import { summarizeToolResult } from '../chat/summarizeToolResult'
import { AudioRecorder } from './AudioRecorder'
import { WaveformDisplay } from './WaveformDisplay'

interface VoiceConversationProps {
  agents: Agent[]
  agentsLoading: boolean
  selectedAgentId: string | null
  onSelectAgent: (id: string) => void
}

export function VoiceConversation({
  agents,
  agentsLoading,
  selectedAgentId,
  onSelectAgent,
}: VoiceConversationProps) {
  // -- transcript state (chat-panel state, kept in the orchestrator) -------
  const [asrPartial, setAsrPartial] = useState('')
  const [transcript, setTranscript] = useState<TranscriptEntry[]>([])
  const [llmText, setLlmText] = useState('')
  const [wsError, setWsError] = useState<string | null>(null)

  const transcriptRef = useRef<HTMLDivElement | null>(null)
  // Auto-scroll transcript to bottom on new entries.
  useEffect(() => {
    if (transcriptRef.current) {
      transcriptRef.current.scrollTop = transcriptRef.current.scrollHeight
    }
  }, [transcript, asrPartial, llmText])

  // -- mutable refs shared with the WS event handler ----------------------
  // Keep the live LLM text in a ref so the handler (attached once per
  // connect) always sees the latest value without re-subscribing.
  const llmTextRef = useRef('')

  const pushTranscript = useCallback(
    (role: TranscriptEntry['role'], text: string) => {
      setTranscript((prev) => [
        ...prev,
        { id: crypto.randomUUID(), role, text, ts: Date.now() },
      ])
    },
    [],
  )

  // -- WebSocket event handling (transcript / chat logic) -----------------
  // The hook drives agentState / sessionActive; this handler only owns
  // the transcript, ASR partial, and LLM streaming text.
  const handleEvent = useCallback(
    (event: ServerEvent) => {
      switch (event.type) {
        case 'connected':
          setWsError(null)
          setAsrPartial('')
          llmTextRef.current = ''
          setLlmText('')
          break
        case 'agent_state':
          // agentState is tracked by useVoiceAgent; finalize in-flight text.
          if (event.state !== 'speaking' && llmTextRef.current) {
            pushTranscript('assistant', llmTextRef.current)
            llmTextRef.current = ''
            setLlmText('')
          }
          break
        case 'asr_partial':
          setAsrPartial(event.text)
          break
        case 'asr_final':
          if (event.text.trim()) {
            pushTranscript('user', event.text)
          }
          setAsrPartial('')
          // Start collecting a fresh LLM reply.
          llmTextRef.current = ''
          setLlmText('')
          break
        case 'llm_chunk':
          llmTextRef.current = (llmTextRef.current || '') + event.text
          setLlmText(llmTextRef.current)
          break
        case 'error':
          setWsError(event.message)
          break
        case 'tool_call':
          pushTranscript('system', `🔧 ${event.name}`)
          break
        case 'tool_result': {
          const ok = event.result.ok
          const success = ok === true
          const fail = ok === false
          const detail = summarizeToolResult(event.result)
          const mark = fail ? '✗' : '✓'
          const status = success ? ' 成功' : fail ? ' 失败' : ''
          pushTranscript(
            'system',
            `${mark} ${event.name}${status}${detail ? ` • ${detail}` : ''}`,
          )
          break
        }
      }
    },
    [pushTranscript],
  )

  // -- voice agent session (WS + capture + playback) ----------------------
  const {
    connectionState,
    agentState,
    error,
    sessionActive,
    start,
    stop,
    toggleMic,
    bargeIn,
    canBargeIn,
    micRecording,
  } = useVoiceAgent({
    agentId: selectedAgentId,
    onEvent: handleEvent,
  })

  // -- session control ----------------------------------------------------
  const startSession = useCallback(async () => {
    if (!selectedAgentId) return
    setWsError(null)
    setTranscript([])
    setLlmText('')
    llmTextRef.current = ''
    await start()
    const agent = agents.find((a) => a.id === selectedAgentId)
    if (agent) {
      pushTranscript('system', `开始与 ${agent.name} 对话`)
    }
  }, [selectedAgentId, start, agents, pushTranscript])

  const stopSession = useCallback(() => {
    stop()
    if (sessionActive) {
      pushTranscript('system', '对话已结束')
    }
  }, [stop, sessionActive, pushTranscript])

  // Resolve the active identity: prefer the explicitly selected agent,
  // fall back to the first available one so the persona preview stays useful.
  const currentAgent =
    agents.find((a) => a.id === selectedAgentId) ?? agents[0] ?? null

  // WS error events take precedence over session-level errors for display.
  const displayError = wsError ?? error

  return (
    <div className="flex h-full flex-col">
      {/* Top bar — agent picker + session controls */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border)] bg-[var(--bg-soft)]/40 px-6 py-3">
        <div className="flex items-center gap-2">
          <label className="text-sm text-[var(--muted)]">Agent</label>
          <select
            value={selectedAgentId ?? ''}
            onChange={(e) => onSelectAgent(e.target.value)}
            disabled={sessionActive || agentsLoading}
            className="rounded-full border border-[var(--border)] bg-[var(--card)] px-3 py-1.5 text-sm focus:border-[var(--accent)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/30"
          >
            {agents.length === 0 && <option value="">无可用 Agent</option>}
            {agents.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </div>

        <div className="flex items-center gap-3">
          <WaveformDisplay active={sessionActive} recording={micRecording} />
          <button
            type="button"
            onClick={sessionActive ? stopSession : startSession}
            disabled={!selectedAgentId}
            className="rounded-full px-5 py-2 text-sm font-medium text-white transition hover:scale-105 active:scale-95 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:scale-100"
            style={{
              background: 'linear-gradient(135deg, var(--accent-2), var(--c-peach))',
              boxShadow: 'var(--shadow-soft)',
            }}
          >
            {sessionActive ? '结束对话' : '开始对话'}
          </button>
        </div>
      </div>

      {/* Identity block — who the user is talking to */}
      <div className="border-b border-[var(--border)] bg-[var(--bg-soft)]/40 px-6 py-3">
        {currentAgent ? (
          <>
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-semibold text-[var(--fg)]">
                {currentAgent.name}
              </h2>
              {sessionActive && (
                <span className="text-xs text-[var(--muted)]">
                  正在与 {currentAgent.name} 对话
                </span>
              )}
            </div>
            {currentAgent.persona && (
              <p className="mt-1 line-clamp-2 text-xs text-[var(--muted)]">
                {currentAgent.persona}
              </p>
            )}
          </>
        ) : (
          <h2 className="text-lg font-semibold text-[var(--muted)]">
            未选择 Agent
          </h2>
        )}
      </div>

      {/* Status row — connection + agent state + errors */}
      <AgentStatus
        connectionState={connectionState}
        agentState={agentState}
        error={displayError}
      />

      {/* Transcript — scrolling history */}
      <ChatPanel
        ref={transcriptRef}
        transcript={transcript}
        asrPartial={asrPartial}
        llmText={llmText}
      />

      {/* Bottom control — mic + barge-in */}
      <div className="flex items-center justify-center gap-4 border-t border-[var(--border)] bg-[var(--bg-soft)]/40 px-6 py-4">
        <AudioRecorder
          recording={micRecording}
          disabled={!sessionActive}
          onToggle={toggleMic}
        />

        {canBargeIn && (
          <button
            type="button"
            onClick={bargeIn}
            className="rounded-full border border-amber-400/50 px-4 py-2 text-sm font-medium text-amber-400 transition hover:scale-105 hover:bg-amber-400/10"
          >
            打断
          </button>
        )}
      </div>
    </div>
  )
}
