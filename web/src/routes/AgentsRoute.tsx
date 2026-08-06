import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Agent, Voice } from '../types'

interface AgentDraft {
  name: string
  persona: string
  system_prompt: string
  voice_id: string
  llm_model: string
  llm_temperature: string
  llm_history_limit: string
  llm_max_tokens: string
}

const EMPTY_DRAFT: AgentDraft = {
  name: '',
  persona: '',
  system_prompt: '',
  voice_id: '',
  llm_model: '',
  llm_temperature: '0.7',
  llm_history_limit: '',
  llm_max_tokens: '',
}

function toDraft(agent: Agent): AgentDraft {
  const cfg = (agent.llm_config ?? {}) as Record<string, unknown>
  return {
    name: agent.name,
    persona: agent.persona ?? '',
    system_prompt: agent.system_prompt ?? '',
    voice_id: agent.voice_id ?? '',
    llm_model: (cfg.model as string) ?? '',
    llm_temperature: String(cfg.temperature ?? 0.7),
    llm_history_limit: cfg.history_limit != null ? String(cfg.history_limit) : '',
    llm_max_tokens: cfg.max_tokens != null ? String(cfg.max_tokens) : '',
  }
}

function draftToPayload(draft: AgentDraft) {
  const llm_config: Record<string, unknown> = {}
  if (draft.llm_model) llm_config.model = draft.llm_model
  const temp = parseFloat(draft.llm_temperature)
  if (!Number.isNaN(temp)) llm_config.temperature = temp
  const historyLimit = parseInt(draft.llm_history_limit, 10)
  if (!Number.isNaN(historyLimit) && historyLimit > 0) llm_config.history_limit = historyLimit
  const maxTokens = parseInt(draft.llm_max_tokens, 10)
  if (!Number.isNaN(maxTokens) && maxTokens > 0) llm_config.max_tokens = maxTokens
  return {
    name: draft.name,
    persona: draft.persona || null,
    system_prompt: draft.system_prompt || null,
    voice_id: draft.voice_id || null,
    llm_config,
  }
}

export function AgentsRoute() {
  const [agents, setAgents] = useState<Agent[]>([])
  const [voices, setVoices] = useState<Voice[]>([])
  const [loading, setLoading] = useState(true)
  const [editingId, setEditingId] = useState<string | null>(null) // null = list view, '' = new, '<id>' = edit
  const [draft, setDraft] = useState<AgentDraft>(EMPTY_DRAFT)
  const [error, setError] = useState<string | null>(null)

  const reload = async () => {
    setLoading(true)
    try {
      const [a, v] = await Promise.all([api.listAgents(), api.listVoices()])
      setAgents(a)
      setVoices(v)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    reload()
  }, [])

  const startNew = () => {
    setDraft(EMPTY_DRAFT)
    setEditingId('')
  }
  const startEdit = (agent: Agent) => {
    setDraft(toDraft(agent))
    setEditingId(agent.id)
  }
  const cancel = () => {
    setEditingId(null)
    setDraft(EMPTY_DRAFT)
  }

  const save = async () => {
    setError(null)
    if (!draft.name.trim()) {
      setError('名称不能为空')
      return
    }
    try {
      const payload = draftToPayload(draft)
      if (editingId === '') {
        const created = await api.createAgent(payload)
        setAgents([created, ...agents])
      } else if (editingId) {
        const updated = await api.updateAgent(editingId, payload)
        setAgents(agents.map((a) => (a.id === updated.id ? updated : a)))
      }
      cancel()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const remove = async (id: string) => {
    if (!confirm('删除该 Agent？')) return
    try {
      await api.deleteAgent(id)
      setAgents(agents.filter((a) => a.id !== id))
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <div className="mx-auto flex h-full max-w-5xl flex-col p-6">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[var(--fg)]">Agent 管理</h1>
          <p className="text-xs text-[var(--muted)]">
            配置语音对话伙伴的人格、系统提示、声音模型与 LLM 参数
          </p>
        </div>
        {editingId === null && (
          <button
            type="button"
            onClick={startNew}
            className="rounded-md bg-[var(--accent)] px-3 py-1.5 text-sm font-medium text-black hover:brightness-110"
          >
            + 新建 Agent
          </button>
        )}
      </div>

      {error && (
        <div className="mb-3 rounded border border-red-900/50 bg-red-950/30 px-3 py-2 text-xs text-red-300">
          {error}
          <button type="button" onClick={() => setError(null)} className="ml-2 float-right">
            ×
          </button>
        </div>
      )}

      {/* Editor (new / edit) */}
      {editingId !== null && (
        <div className="mb-4 rounded-lg border border-[var(--border)] bg-[var(--card)] p-4">
          <h2 className="mb-3 text-sm font-semibold text-[var(--fg)]">
            {editingId === '' ? '创建新 Agent' : '编辑 Agent'}
          </h2>
          <div className="grid grid-cols-2 gap-3">
            <label className="col-span-2 flex flex-col gap-1">
              <span className="text-xs text-[var(--muted)]">名称 *</span>
              <input
                type="text"
                value={draft.name}
                onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                className="rounded border border-[var(--border)] bg-[var(--bg)] px-3 py-1.5 text-sm text-[var(--fg)] focus:border-[var(--accent)] focus:outline-none"
                placeholder="如：日常对话伙伴"
              />
            </label>
            <label className="col-span-2 flex flex-col gap-1">
              <span className="text-xs text-[var(--muted)]">Persona（人设）</span>
              <textarea
                value={draft.persona}
                onChange={(e) => setDraft({ ...draft, persona: e.target.value })}
                rows={3}
                className="rounded border border-[var(--border)] bg-[var(--bg)] px-3 py-1.5 text-sm text-[var(--fg)] focus:border-[var(--accent)] focus:outline-none"
                placeholder="如：你是一位温暖耐心的朋友，擅长倾听和共情..."
              />
            </label>
            <label className="col-span-2 flex flex-col gap-1">
              <span className="text-xs text-[var(--muted)]">System Prompt（系统提示）</span>
              <textarea
                value={draft.system_prompt}
                onChange={(e) => setDraft({ ...draft, system_prompt: e.target.value })}
                rows={4}
                className="rounded border border-[var(--border)] bg-[var(--bg)] px-3 py-1.5 text-sm text-[var(--fg)] focus:border-[var(--accent)] focus:outline-none"
                placeholder="完整覆盖 persona 的指令；空则用 persona 作为 system prompt"
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-[var(--muted)]">绑定声音</span>
              <select
                value={draft.voice_id}
                onChange={(e) => setDraft({ ...draft, voice_id: e.target.value })}
                className="rounded border border-[var(--border)] bg-[var(--bg)] px-3 py-1.5 text-sm text-[var(--fg)]"
              >
                <option value="">— 不绑定 —</option>
                {voices.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.name} ({v.provider})
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-[var(--muted)]">LLM 模型</span>
              <input
                type="text"
                value={draft.llm_model}
                onChange={(e) => setDraft({ ...draft, llm_model: e.target.value })}
                className="rounded border border-[var(--border)] bg-[var(--bg)] px-3 py-1.5 text-sm text-[var(--fg)] focus:border-[var(--accent)] focus:outline-none"
                placeholder="如：gpt-4o-mini / claude-3-5-haiku-latest（空=用默认）"
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-[var(--muted)]">Temperature</span>
              <input
                type="number"
                min={0}
                max={2}
                step={0.1}
                value={draft.llm_temperature}
                onChange={(e) => setDraft({ ...draft, llm_temperature: e.target.value })}
                className="rounded border border-[var(--border)] bg-[var(--bg)] px-3 py-1.5 text-sm text-[var(--fg)] focus:border-[var(--accent)] focus:outline-none"
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-[var(--muted)]">记忆深度（轮）</span>
              <input
                type="number"
                min={1}
                value={draft.llm_history_limit}
                onChange={(e) => setDraft({ ...draft, llm_history_limit: e.target.value })}
                className="rounded border border-[var(--border)] bg-[var(--bg)] px-3 py-1.5 text-sm text-[var(--fg)] focus:border-[var(--accent)] focus:outline-none"
                placeholder="如：16（空=默认32）"
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-[var(--muted)]">Max tokens</span>
              <input
                type="number"
                min={1}
                value={draft.llm_max_tokens}
                onChange={(e) => setDraft({ ...draft, llm_max_tokens: e.target.value })}
                className="rounded border border-[var(--border)] bg-[var(--bg)] px-3 py-1.5 text-sm text-[var(--fg)] focus:border-[var(--accent)] focus:outline-none"
                placeholder="如：512（空=默认）"
              />
            </label>
          </div>
          <div className="mt-3 flex gap-2">
            <button
              type="button"
              onClick={save}
              className="rounded-md bg-[var(--accent)] px-3 py-1.5 text-sm font-medium text-black hover:brightness-110"
            >
              保存
            </button>
            <button
              type="button"
              onClick={cancel}
              className="rounded-md border border-[var(--border)] px-3 py-1.5 text-sm text-[var(--muted)] hover:bg-[var(--bg)]"
            >
              取消
            </button>
          </div>
        </div>
      )}

      {/* List */}
      {loading ? (
        <div className="text-sm text-[var(--muted)]">加载中…</div>
      ) : agents.length === 0 ? (
        <div className="rounded border border-dashed border-[var(--border)] px-6 py-12 text-center text-sm text-[var(--muted)]">
          还没有 Agent，点击右上角"新建 Agent"开始
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {agents.map((agent) => {
            const voice = voices.find((v) => v.id === agent.voice_id)
            const cfg = (agent.llm_config ?? {}) as Record<string, unknown>
            return (
              <div
                key={agent.id}
                className="flex flex-col gap-2 rounded-lg border border-[var(--border)] bg-[var(--card)] p-4"
              >
                <div className="flex items-start justify-between">
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-semibold text-[var(--fg)]">{agent.name}</div>
                    {agent.persona && (
                      <div className="mt-1 line-clamp-2 text-xs text-[var(--muted)]">
                        {agent.persona}
                      </div>
                    )}
                  </div>
                  <div className="ml-2 flex gap-1">
                    <button
                      type="button"
                      onClick={() => startEdit(agent)}
                      className="rounded px-2 py-1 text-xs text-[var(--muted)] hover:bg-[var(--bg)] hover:text-[var(--fg)]"
                    >
                      编辑
                    </button>
                    <button
                      type="button"
                      onClick={() => remove(agent.id)}
                      className="rounded px-2 py-1 text-xs text-[var(--muted)] hover:bg-red-900/30 hover:text-red-300"
                    >
                      删除
                    </button>
                  </div>
                </div>
                <div className="flex flex-wrap gap-2 text-[10px]">
                  {voice ? (
                    <span className="rounded bg-[var(--accent)]/15 px-2 py-0.5 text-[var(--accent)]">
                      🎙 {voice.name}
                    </span>
                  ) : (
                    <span className="rounded bg-[var(--border)]/40 px-2 py-0.5 text-[var(--muted)]">
                      未绑定声音
                    </span>
                  )}
                  {cfg.model ? (
                    <span className="rounded bg-[var(--border)]/40 px-2 py-0.5 text-[var(--muted)]">
                      🧠 {String(cfg.model)}
                    </span>
                  ) : null}
                  {typeof cfg.temperature === 'number' ? (
                    <span className="rounded bg-[var(--border)]/40 px-2 py-0.5 text-[var(--muted)]">
                      T={cfg.temperature}
                    </span>
                  ) : null}
                  {typeof cfg.history_limit === 'number' ? (
                    <span className="rounded bg-[var(--border)]/40 px-2 py-0.5 text-[var(--muted)]">
                      记忆{cfg.history_limit}轮
                    </span>
                  ) : null}
                  {typeof cfg.max_tokens === 'number' ? (
                    <span className="rounded bg-[var(--border)]/40 px-2 py-0.5 text-[var(--muted)]">
                      {cfg.max_tokens}tok
                    </span>
                  ) : null}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
