/**
 * StudioChatPanel — AI-native assistant panel for the Melo studio.
 *
 * This is the natural-language control surface for the whole workspace:
 * the user types a request (create a project, add a track, generate voice,
 * edit a clip…) and the backend agent streams a reply while executing tools.
 *
 * Panel anatomy (top → bottom):
 *   - Header: title + connection indicator + collapse toggle.
 *   - Transcript: user / assistant bubbles and system tool-call prompts.
 *   - Live LLM stream: incremental assistant text for the in-flight turn.
 *   - Input: textarea + send / clear controls.
 *
 * When the agent executes a tool that mutates studio state, the panel
 * notifies the parent via `onToolApplied` so the timeline can refresh.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { useStudioAgent, type StudioAgentEvent } from '../../hooks/useStudioAgent'
import { useStudioStore } from '../../stores/studioStore'
import { MessageBubble, type TranscriptEntry } from '../chat/MessageBubble'
import { summarizeToolResult } from '../chat/summarizeToolResult'

export interface StudioChatPanelProps {
  open: boolean
  onToggle: () => void
  agentId: string | null
  onToolApplied: () => void
}

interface ChatMessage extends TranscriptEntry {
  /** Emitted when the message is a tool-call prompt. */
  toolName?: string
  /** Whether the tool reported a successful result. */
  ok?: boolean
}

let uidCounter = 0
function nextId(): string {
  uidCounter += 1
  return `studio-msg-${uidCounter}`
}

export function StudioChatPanel({
  open,
  onToggle,
  agentId,
  onToolApplied,
}: StudioChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [streamText, setStreamText] = useState('')
  const [input, setInput] = useState('')
  const [agentName, setAgentName] = useState<string | null>(null)

  const currentProjectId = useStudioStore((s) => s.currentProject?.id)

  // Accumulator for the in-flight assistant turn. Kept in a ref so the
  // `done` handler commits the full text even though the stream chunks are
  // delivered asynchronously.
  const pendingRef = useRef('')

  const scrollRef = useRef<HTMLDivElement | null>(null)
  const onToolAppliedRef = useRef(onToolApplied)
  useEffect(() => {
    onToolAppliedRef.current = onToolApplied
  }, [onToolApplied])

  const handleEvent = useCallback((e: StudioAgentEvent) => {
    switch (e.type) {
      case 'connected':
        setAgentName(e.agent_name ?? null)
        break

      case 'llm_chunk': {
        pendingRef.current += e.text ?? ''
        setStreamText(pendingRef.current)
        break
      }

      case 'tool_call': {
        const ok = (e.result as { ok?: boolean } | undefined)?.ok === true
        const label = ok ? '✓' : '✗'
        const detail = summarizeToolResult(e.result)
        const text = `${label} 工具「${e.name ?? '未知'}」${ok ? '执行成功' : '执行失败'}${detail ? ` — ${detail}` : ''}`
        setMessages((prev) => [
          ...prev,
          { id: nextId(), role: 'system', text, ts: Date.now(), toolName: e.name, ok },
        ])
        // A successful tool may have mutated the workspace — let the parent
        // refresh the store so the change lands on the timeline immediately.
        if (ok) onToolAppliedRef.current()
        break
      }

      case 'done': {
        const text = pendingRef.current
        pendingRef.current = ''
        setStreamText('')
        if (text.trim()) {
          setMessages((prev) => [
            ...prev,
            { id: nextId(), role: 'assistant', text: text.trim(), ts: Date.now() },
          ])
        }
        break
      }

      case 'error':
        setMessages((prev) => [
          ...prev,
          {
            id: nextId(),
            role: 'system',
            text: `✗ ${e.message ?? '发生错误'}`,
            ts: Date.now(),
            ok: false,
          },
        ])
        pendingRef.current = ''
        setStreamText('')
        break
    }
  }, [])

  const { connected, sendChat, reset } = useStudioAgent({
    agentId,
    onEvent: handleEvent,
  })

  const handleSend = useCallback(() => {
    const text = input.trim()
    if (!text || !connected) return
    // Commit the user's message and start a fresh assistant turn.
    setMessages((prev) => [
      ...prev,
      { id: nextId(), role: 'user', text, ts: Date.now() },
    ])
    pendingRef.current = ''
    setStreamText('')
    setInput('')
    sendChat(text, currentProjectId)
  }, [input, connected, sendChat, currentProjectId])

  const handleReset = useCallback(() => {
    setMessages([])
    pendingRef.current = ''
    setStreamText('')
    reset()
  }, [reset])

  // Auto-scroll to the newest content as the transcript grows.
  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages, streamText])

  // Collapsed state — a slim rail with the expand toggle.
  if (!open) {
    return (
      <aside className="flex w-10 shrink-0 flex-col items-center border-r border-[var(--border)] bg-[var(--bg-soft)]/40 py-3">
        <button
          type="button"
          onClick={onToggle}
          title="展开 AI 助手"
          className="flex h-12 w-8 items-center justify-center rounded-lg text-[var(--muted)] transition hover:bg-[var(--card)] hover:text-[var(--fg)]"
        >
          <span className="text-lg">🤖</span>
        </button>
        <button
          type="button"
          onClick={onToggle}
          title="展开 AI 助手"
          className="mt-1 flex h-8 w-8 -rotate-90 items-center justify-center text-[var(--muted)] transition hover:bg-[var(--card)] hover:text-[var(--fg)]"
        >
          <span className="text-xs font-medium">助手</span>
        </button>
      </aside>
    )
  }

  return (
    <aside className="flex w-80 shrink-0 flex-col border-r border-[var(--border)] bg-[var(--bg-soft)]/40">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[var(--border)] px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="text-base">🤖</span>
          <div>
            <h2 className="text-sm font-semibold text-[var(--fg)]">AI 助手</h2>
            <div className="flex items-center gap-1.5 text-[10px] text-[var(--muted)]">
              <span
                className={`inline-block h-1.5 w-1.5 rounded-full ${
                  connected ? 'bg-[var(--c-mint)]' : 'bg-[var(--muted)]'
                }`}
              />
              {connected ? '已连接' : '未连接'}
              {agentName ? ` · ${agentName}` : ''}
            </div>
          </div>
        </div>
        <button
          type="button"
          onClick={onToggle}
          title="折叠 AI 助手"
          className="rounded-full px-2 py-1 text-xs text-[var(--muted)] transition hover:bg-[var(--card)] hover:text-[var(--fg)]"
        >
          «
        </button>
      </div>

      {/* Transcript + live stream */}
      <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
        {messages.length === 0 && !streamText && (
          <div className="mt-8 text-center text-xs text-[var(--muted)]">
            <p className="text-lg">♪</p>
            <p className="mt-1">用一句话指挥整个工作室</p>
            <p className="mt-0.5 text-[10px]">「新建项目」/「添加音轨」/「生成语音」…</p>
          </div>
        )}

        {messages.map((entry) => (
          <MessageBubble key={entry.id} entry={entry} />
        ))}

        {streamText && (
          <div className="flex justify-start">
            <div className="max-w-[80%] rounded-2xl rounded-bl-sm bg-[var(--accent)]/15 px-4 py-2 text-sm text-[var(--fg)] shadow-[var(--shadow-soft)]">
              {streamText}
              <span className="ml-1 inline-block h-3 w-1 animate-pulse bg-[var(--accent-2)] align-middle" />
            </div>
          </div>
        )}
      </div>

      {/* Input */}
      <div className="border-t border-[var(--border)] p-3">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              handleSend()
            }
          }}
          rows={3}
          placeholder={connected ? '描述你想做什么…' : '等待连接…'}
          disabled={!connected}
          className="w-full resize-none rounded-xl border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-xs text-[var(--fg)] placeholder:text-[var(--muted)] focus:border-[var(--accent)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/30 disabled:opacity-50"
        />
        <div className="mt-2 flex items-center justify-between">
          <button
            type="button"
            onClick={handleReset}
            className="rounded-lg px-2 py-1 text-[11px] text-[var(--muted)] transition hover:bg-[var(--card)] hover:text-[var(--fg)]"
          >
            清空
          </button>
          <button
            type="button"
            onClick={handleSend}
            disabled={!input.trim() || !connected}
            className="rounded-lg px-4 py-1.5 text-xs font-bold text-white transition hover:scale-105 disabled:opacity-40 disabled:hover:scale-100"
            style={{ background: 'linear-gradient(135deg, var(--accent), var(--c-blue))' }}
          >
            发送
          </button>
        </div>
      </div>
    </aside>
  )
}