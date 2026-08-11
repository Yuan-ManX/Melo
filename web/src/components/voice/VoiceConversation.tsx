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

import { useCallback, useEffect, useReducer, useRef, useState } from 'react'

import { useVoiceAgent } from '../../hooks/useVoiceAgent'
import { useConversationStore } from '../../stores/conversationStore'
import { useStudioStore } from '../../stores/studioStore'
import { useVoiceStore } from '../../stores/voiceStore'
import type { Agent } from '../../types'
import type { ServerEvent } from '../../types/ws'
import { AgentStatus } from '../chat/AgentStatus'
import { ChatPanel } from '../chat/ChatPanel'
import type { TranscriptEntry } from '../chat/MessageBubble'
import { PlanRail, planRailReducer } from '../chat/PlanRail'
import type { PlanRailState } from '../chat/PlanRail'
import { summarizeToolResult } from '../chat/summarizeToolResult'
import { ToolActivity } from '../chat/ToolActivity'
import type { ToolRun } from '../chat/ToolActivity'
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
  // Stage 20: live tool-activity cards. Populated by `tool_call` events
  // (all pending calls appear immediately) and updated in place by
  // `tool_result` events as each parallel call completes. Cleared at the
  // start of the next user turn so it only reflects the current turn.
  const [toolRuns, setToolRuns] = useState<ToolRun[]>([])
  // Plan rail — the current agent orchestration plan (goal + step
  // statuses). Null until a `planning` event arrives; replaced per turn.
  const [planRail, dispatchPlanRail] = useReducer(planRailReducer, null)

  // -- voice library (loaded once for the voice picker dropdown) ----------
  const voices = useVoiceStore((s) => s.voices)
  const fetchVoices = useVoiceStore((s) => s.fetchVoices)
  useEffect(() => {
    // Lazy-load on mount — the store is shared so if the user already
    // visited the Voices page this is a no-op cache hit.
    if (voices.length === 0) {
      void fetchVoices()
    }
  }, [voices.length, fetchVoices])

  // -- conversation persistence (Stage 15) --------------------------------
  // The store is the source of truth for the active conversation id and
  // its persisted messages. The transcript UI state below is rebuilt
  // from `messages` whenever a conversation is reopened, so a refresh
  // or agent-select shows the prior history. New finalizations during a
  // live session are appended both to the UI transcript (for instant
  // feedback) AND to the store (for persistence).
  const currentConversationId = useConversationStore((s) => s.currentConversationId)
  const messages = useConversationStore((s) => s.messages)
  const openLastConversation = useConversationStore((s) => s.openLastConversation)
  const startNewConversation = useConversationStore((s) => s.startNewConversation)
  const appendMessage = useConversationStore((s) => s.appendMessage)
  const clearCurrent = useConversationStore((s) => s.clearCurrent)

  // When the user picks a different agent (or first lands on the voice
  // page), load that agent's conversations and reopen the most recent
  // one. If none exists, leave currentConversationId null so the next
  // session start will create a fresh one.
  useEffect(() => {
    if (!selectedAgentId) {
      clearCurrent()
      setTranscript([])
      setAsrPartial('')
      setLlmText('')
      setToolRuns([])
      llmTextRef.current = ''
      return
    }
    setToolRuns([])
    void openLastConversation(selectedAgentId)
  }, [selectedAgentId, openLastConversation, clearCurrent])

  // Rebuild the transcript UI state whenever the store loads a fresh
  // set of messages (open / clear / delete). The empty case is ignored
  // — `startSession` and `newConversation` reset the transcript on
  // their own, so we don't want this effect to wipe a freshly-started
  // session's transcript.
  useEffect(() => {
    if (messages.length === 0) return
    setTranscript(
      messages.map((m) => ({
        id: m.id,
        role: m.role,
        text: m.content,
        ts: new Date(m.created_at).getTime(),
      })),
    )
    setAsrPartial('')
    setLlmText('')
    llmTextRef.current = ''
  }, [messages])

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

  // pushAndPersist — UI transcript + REST persistence in one call.
  // The store guards against null currentConversationId and empty
  // content, so callers can invoke unconditionally. The persist call
  // is fire-and-forget: a network failure must NOT break the live
  // transcript (the store catches and drops silently).
  const pushAndPersist = useCallback(
    (role: TranscriptEntry['role'], text: string) => {
      pushTranscript(role, text)
      void appendMessage(role, text)
    },
    [pushTranscript, appendMessage],
  )

  // -- WebSocket event handling (transcript / chat logic) -----------------
  // The hook drives agentState / sessionActive; this handler only owns
  // the transcript, ASR partial, and LLM streaming text.
  //
  // Refs are declared BEFORE handleEvent because the handler closes
  // over them — declaring them after would yield TDZ errors at runtime
  // when the first event arrives.
  const lastInterruptionRef = useRef<'barge_in' | 'client_stop' | null>(null)
  const asrPartialRef = useRef('')

  // -- Stage 20 tool-activity handlers -------------------------------------
  // Each `tool_call` adds a running card; each `tool_result` updates the
  // earliest still-running card with the same tool name (FIFO), which
  // stays correct for distinct-name or sequential same-name calls.
  const handleToolCall = useCallback((name: string) => {
    setToolRuns((prev) => [
      ...prev,
      { key: crypto.randomUUID(), name, status: 'running', detail: '' },
    ])
  }, [])

  const handleToolResult = useCallback(
    (name: string, result: Record<string, unknown>) => {
      const ok = result.ok
      const detail = summarizeToolResult(result)
      setToolRuns((prev) => {
        const idx = prev.findIndex((r) => r.name === name && r.status === 'running')
        if (idx === -1) return prev
        const next = [...prev]
        next[idx] = {
          ...next[idx],
          status: ok === false ? 'fail' : 'ok',
          detail,
        }
        return next
      })
    },
    [],
  )

  // Stage 23: a failing tool is being re-attempted with exponential
  // backoff. Update the matching running card with the retry progress
  // label so the user sees the agent recovering instead of hanging.
  const handleToolRetry = useCallback(
    (name: string, attempt: number, maxRetries: number) => {
      setToolRuns((prev) => {
        const idx = prev.findIndex((r) => r.name === name && r.status === 'running')
        if (idx === -1) return prev
        const next = [...prev]
        next[idx] = { ...next[idx], retry: `${attempt}/${maxRetries}` }
        return next
      })
    },
    [],
  )

  const handleEvent = useCallback(
    (event: ServerEvent) => {
      switch (event.type) {
        case 'connected':
          setWsError(null)
          setAsrPartial('')
          llmTextRef.current = ''
          setLlmText('')
          lastInterruptionRef.current = null
          break
        case 'agent_state':
          // agentState is tracked by useVoiceAgent; finalize in-flight
          // text only when transitioning out of speaking AND we're not
          // mid-interruption (the interruption event itself drops the
          // in-flight text — finalising here too would double-publish
          // a truncated assistant message).
          if (
            event.state !== 'speaking' &&
            llmTextRef.current &&
            lastInterruptionRef.current === null
          ) {
            pushAndPersist('assistant', llmTextRef.current)
            llmTextRef.current = ''
            setLlmText('')
          }
          // Clear the interruption flag once we've safely returned to
          // a stable state — by then any in-flight text has been
          // finalised or dropped, so the guard above is no longer
          // needed.
          if (event.state === 'listening' || event.state === 'idle') {
            lastInterruptionRef.current = null
          }
          break
        case 'interruption':
          // The server cancelled the turn mid-flight. Drop any
          // partial LLM text so it doesn't get finalised into the
          // transcript on the next agent_state event — a half-spoken
          // "The weather in China is..." would otherwise leak into
          // history. A short system note tells the user what happened.
          lastInterruptionRef.current = event.reason
          // Clear any in-flight tool-activity cards — the turn was
          // aborted, so their results will never arrive.
          setToolRuns([])
          if (llmTextRef.current) {
            pushAndPersist(
              'assistant',
              llmTextRef.current + ' …（已打断）',
            )
            llmTextRef.current = ''
            setLlmText('')
          }
          if (asrPartialRef.current) {
            setAsrPartial('')
          }
          pushAndPersist(
            'system',
            event.reason === 'barge_in'
              ? '⚡ 已打断'
              : '⏹ 对话已停止',
          )
          break
        case 'voice_changed':
          // Surface voice switches in the transcript so the user has
          // an audit trail of which voice was active when. The voice
          // picker UI also updates via the hook's `activeVoiceId`.
          pushAndPersist(
            'system',
            `🔊 已切换音色: ${event.voice_id}`,
          )
          break
        case 'asr_partial':
          setAsrPartial(event.text)
          asrPartialRef.current = event.text
          break
        case 'asr_final':
          if (event.text.trim()) {
            pushAndPersist('user', event.text)
          }
          setAsrPartial('')
          asrPartialRef.current = ''
          // A new user turn begins — reset the tool-activity cards from
          // the previous assistant turn and start collecting a fresh
          // LLM reply. The plan rail also resets so the next plan (if
          // any) replaces the completed one.
          setToolRuns([])
          dispatchPlanRail({ type: 'reset' })
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
          // Add a live running card (all pending calls show at once,
          // matching the parallel execution the server performs) and
          // advance the plan rail to the matching step.
          handleToolCall(event.name)
          dispatchPlanRail({ type: 'tool_call', name: event.name })
          pushAndPersist('system', `🔧 ${event.name}`)
          break
        case 'tool_result': {
          const ok = event.result.ok
          const success = ok === true
          const fail = ok === false
          const detail = summarizeToolResult(event.result)
          const mark = fail ? '✗' : '✓'
          const status = success ? ' 成功' : fail ? ' 失败' : ''
          // Update the corresponding live card in place.
          handleToolResult(event.name, event.result)
          dispatchPlanRail({ type: 'tool_result', name: event.name, ok: ok !== false })
          pushAndPersist(
            'system',
            `${mark} ${event.name}${status}${detail ? ` • ${detail}` : ''}`,
          )
          break
        }
        case 'tool_retry':
          // Stage 23: the tool is being re-attempted — reflect the
          // progress on its running card and the plan rail so the user
          // sees recovery.
          handleToolRetry(event.name, event.attempt, event.max_retries)
          dispatchPlanRail({
            type: 'tool_retry',
            name: event.name,
            attempt: event.attempt,
            maxRetries: event.max_retries,
          })
          break
        case 'planning': {
          // Stage 16: the runtime decomposed the user transcript into
          // an ordered tool-call plan BEFORE streaming the LLM response.
          // Render the rail so the user watches each step light up.
          const { goal, steps } = event.plan
          const stepCount = steps.length
          dispatchPlanRail({ type: 'plan', goal, steps })
          pushAndPersist(
            'system',
            `🧠 正在规划：${goal}（${stepCount} 步）`,
          )
          break
        }
        case 'studio_changed': {
          // The voice agent ran a tool that mutated the studio editor
          // (created a project, added a clip…). Refresh the store so any
          // open studio view reflects the change the agent just made.
          const { currentProject } = useStudioStore.getState()
          if (currentProject) {
            void useStudioStore.getState().openProject(currentProject.id)
          }
          void useStudioStore.getState().fetchProjects()
          break
        }
      }
    },
    // handleToolCall / handleToolResult / handleToolRetry are stable
    // (memoised on []), so including them keeps handleEvent's identity
    // stable across renders.
    [pushAndPersist, handleToolCall, handleToolResult, handleToolRetry],
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
    lastInterruption,
    activeVoiceId,
    setVoice,
    micRecording,
  } = useVoiceAgent({
    agentId: selectedAgentId,
    onEvent: handleEvent,
  })

  // Sync the React-state view of `lastInterruption` back into the ref
  // so the WS event handler (which is memoised on `pushAndPersist` only)
  // sees the freshest value without re-subscribing on every state change.
  useEffect(() => {
    lastInterruptionRef.current = lastInterruption
  }, [lastInterruption])

  // -- session control ----------------------------------------------------
  // `resumingRef` distinguishes a fresh session from a resumed one. When
  // the user picks an agent, the store reopens the agent's most recent
  // conversation and the transcript UI state is rebuilt from its messages.
  // If the user then clicks "开始对话", we should CONTINUE that
  // conversation — append subsequent finalizations to it — rather than
  // wipe the transcript and create a new one. The flag is set when the
  // messages effect loads a non-empty history, and consumed (then reset)
  // by startSession.
  const resumingRef = useRef(false)
  useEffect(() => {
    if (messages.length > 0) {
      resumingRef.current = true
    }
  }, [messages])

  const startSession = useCallback(async () => {
    if (!selectedAgentId) return
    setWsError(null)
    const resuming = resumingRef.current
    resumingRef.current = false
    if (!resuming || !currentConversationId) {
      // Fresh session: create a new conversation and start with an
      // empty transcript. The store's startNewConversation prepends the
      // new conversation to the list and sets currentConversationId so
      // subsequent appendMessage calls find a destination.
      setTranscript([])
      setLlmText('')
      llmTextRef.current = ''
      const conv = await startNewConversation(selectedAgentId)
      if (!conv) {
        setWsError('无法创建对话，请稍后重试')
        return
      }
    }
    await start()
    const agent = agents.find((a) => a.id === selectedAgentId)
    if (agent) {
      const note = resuming && currentConversationId
        ? `继续与 ${agent.name} 对话`
        : `开始与 ${agent.name} 对话`
      pushAndPersist('system', note)
    }
  }, [
    selectedAgentId,
    currentConversationId,
    start,
    agents,
    startNewConversation,
    pushAndPersist,
  ])

  const stopSession = useCallback(() => {
    stop()
    if (sessionActive) {
      pushAndPersist('system', '对话已结束')
    }
  }, [stop, sessionActive, pushAndPersist])

  // -- new conversation ---------------------------------------------------
  // Clears the active conversation pointer and the transcript so the
  // next "开始对话" creates a fresh conversation rather than appending
  // to the reopened one. Disabled mid-session — starting a new chat
  // mid-call would silently drop the in-flight turn's persistence.
  const newConversation = useCallback(() => {
    if (sessionActive) return
    clearCurrent()
    setTranscript([])
    setAsrPartial('')
    setLlmText('')
    llmTextRef.current = ''
  }, [sessionActive, clearCurrent])

  // Resolve the active identity: prefer the explicitly selected agent,
  // fall back to the first available one so the persona preview stays useful.
  const currentAgent =
    agents.find((a) => a.id === selectedAgentId) ?? agents[0] ?? null

  // WS error events take precedence over session-level errors for display.
  const displayError = wsError ?? error

  return (
    <div className="flex h-full flex-col">
      {/* Top bar — agent picker + voice picker + session controls */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border)] bg-[var(--bg-soft)]/40 px-6 py-3">
        <div className="flex items-center gap-3">
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

          {/* Voice picker — only visible during an active session so
              the picker doesn't clutter the pre-session layout. The
              dropdown sends `set_voice` on change; the server confirms
              via `voice_changed`, which snaps `activeVoiceId` to the
              new value. Switching is mid-conversation safe: in-flight
              TTS finishes with the old voice, the next synthesis uses
              the new one. */}
          {sessionActive && (
            <div className="flex items-center gap-2">
              <label className="text-sm text-[var(--muted)]">音色</label>
              <select
                value={activeVoiceId ?? ''}
                onChange={(e) => {
                  const v = e.target.value
                  if (v) setVoice(v)
                }}
                className="rounded-full border border-[var(--border)] bg-[var(--card)] px-3 py-1.5 text-sm focus:border-[var(--accent)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/30"
              >
                {voices.length === 0 && (
                  <option value="">未配置音色</option>
                )}
                {/* The empty option represents "agent default" — when
                    activeVoiceId is null we show this so the user can
                    see the agent is using its configured voice without
                    forcing them to pick a specific one. */}
                {activeVoiceId === null && voices.length > 0 && (
                  <option value="">默认</option>
                )}
                {voices.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.name}
                    {v.provider ? ` · ${v.provider}` : ''}
                  </option>
                ))}
              </select>
            </div>
          )}

          {/* New conversation — clears the active conversation pointer
              and the transcript so the next "开始对话" starts a fresh
              chat. Disabled mid-session to avoid silently dropping the
              in-flight turn's persistence. */}
          <button
            type="button"
            onClick={newConversation}
            disabled={sessionActive || !selectedAgentId}
            className="rounded-full border border-[var(--border)] bg-[var(--card)] px-3 py-1.5 text-sm text-[var(--fg)] transition hover:scale-105 hover:border-[var(--accent)]/40 active:scale-95 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:scale-100"
          >
            新对话
          </button>
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

      {/* Interruption banner — flashes briefly when the server
          cancelled the in-flight turn (either the user started
          speaking, or the session was stopped). The banner fades
          once `lastInterruption` clears (next agent_state event). */}
      {lastInterruption && (
        <div
          role="status"
          aria-live="polite"
          className="border-b border-amber-400/30 bg-amber-400/10 px-6 py-2 text-xs text-amber-300"
        >
          {lastInterruption === 'barge_in'
            ? '⚡ 已打断输出，正在聆听你的新输入…'
            : '⏹ 输出已停止'}
        </div>
      )}

      {/* Live tool-activity — transient cards for the current turn's
          tool executions (Stage 20). Shows all pending calls at once
          and updates each in place as its result streams. */}
      <ToolActivity runs={toolRuns} />

      {/* Plan rail — real-time visualisation of the agent's orchestration
          steps (goal + step statuses) as they run and complete. */}
      {planRail && (
        <PlanRail state={planRail} onDismiss={() => dispatchPlanRail({ type: 'reset' })} />
      )}

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
            // When the user just interrupted, briefly highlight the
            // button in red to signal the active interruption state.
            className={
              lastInterruption === 'barge_in'
                ? 'rounded-full border border-red-400/60 bg-red-400/10 px-4 py-2 text-sm font-medium text-red-300 transition hover:scale-105'
                : 'rounded-full border border-amber-400/50 px-4 py-2 text-sm font-medium text-amber-400 transition hover:scale-105 hover:bg-amber-400/10'
            }
          >
            {lastInterruption === 'barge_in' ? '正在打断…' : '打断'}
          </button>
        )}
      </div>
    </div>
  )
}
