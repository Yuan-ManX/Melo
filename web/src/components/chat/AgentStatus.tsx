/**
 * AgentStatus — small status row showing connection state, agent runtime
 * state, and any error message.
 *
 * Renders the thin border-bottom row above the transcript.
 */

import type { AgentRuntimeState } from '../../types/ws'

const AGENT_STATE_LABEL: Record<AgentRuntimeState, string> = {
  idle: '空闲',
  listening: '聆听中',
  thinking: '思考中',
  speaking: '表达中',
}

interface AgentStatusProps {
  connectionState: 'idle' | 'connecting' | 'open' | 'closed' | 'error'
  agentState: AgentRuntimeState
  error: string | null
}

export function AgentStatus({
  connectionState,
  agentState,
  error,
}: AgentStatusProps) {
  return (
    <div className="flex items-center gap-3 border-b border-[var(--border)] px-6 py-2 text-xs text-[var(--muted)]">
      <span>
        连接：
        <span className="ml-1 font-medium text-[var(--fg)]">{connectionState}</span>
      </span>
      <span>
        状态：
        <span
          className={`ml-1 font-medium ${
            agentState === 'speaking'
              ? 'text-[var(--accent-2)]'
              : agentState === 'thinking'
                ? 'text-amber-400'
                : agentState === 'listening'
                  ? 'text-emerald-400'
                  : ''
          }`}
        >
          {AGENT_STATE_LABEL[agentState]}
        </span>
      </span>
      {error && (
        <span className="font-medium text-red-400">错误：{error}</span>
      )}
    </div>
  )
}
