import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Voice } from '../types'

const PROVIDERS = [
  { value: 'rvc', label: 'RVC（本地克隆）' },
  { value: 'elevenlabs', label: 'ElevenLabs（云端）' },
  { value: 'openai', label: 'OpenAI TTS' },
  { value: 'piper', label: 'Piper（本地）' },
]

interface VoiceDraft {
  name: string
  provider: string
  sample_url: string
}

const EMPTY_DRAFT: VoiceDraft = { name: '', provider: 'rvc', sample_url: '' }

export function VoicesRoute() {
  const [voices, setVoices] = useState<Voice[]>([])
  const [loading, setLoading] = useState(true)
  const [draft, setDraft] = useState<VoiceDraft>(EMPTY_DRAFT)
  const [showForm, setShowForm] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [cloneStatus, setCloneStatus] = useState<string | null>(null)

  const reload = async () => {
    setLoading(true)
    try {
      setVoices(await api.listVoices())
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    reload()
  }, [])

  const save = async () => {
    setError(null)
    if (!draft.name.trim()) {
      setError('名称不能为空')
      return
    }
    try {
      const created = await api.createVoice({
        name: draft.name.trim(),
        provider: draft.provider,
        sample_url: draft.sample_url.trim() || null,
      })
      setVoices([created, ...voices])
      setDraft(EMPTY_DRAFT)
      setShowForm(false)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const remove = async (id: string) => {
    if (!confirm('删除该声音？绑定此声音的 Agent 将解除绑定。')) return
    try {
      await api.deleteVoice(id)
      setVoices(voices.filter((v) => v.id !== id))
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const tryClone = async (voice: Voice) => {
    setCloneStatus(`声音克隆功能即将上线。当前声音「${voice.name}」的元数据已保存，可绑定到 Agent。`)
    setTimeout(() => setCloneStatus(null), 4000)
  }

  return (
    <div className="mx-auto flex h-full max-w-5xl flex-col p-6">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[var(--fg)]">声音库</h1>
          <p className="text-xs text-[var(--muted)]">
            管理 TTS 声音模型，支持 RVC 本地克隆 / ElevenLabs 云端 / OpenAI TTS / Piper
          </p>
        </div>
        {!showForm && (
          <button
            type="button"
            onClick={() => setShowForm(true)}
            className="rounded-md bg-[var(--accent)] px-3 py-1.5 text-sm font-medium text-black hover:brightness-110"
          >
            + 新建声音
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

      {cloneStatus && (
        <div className="mb-3 rounded border border-amber-900/50 bg-amber-950/30 px-3 py-2 text-xs text-amber-300">
          {cloneStatus}
        </div>
      )}

      {showForm && (
        <div className="mb-4 rounded-lg border border-[var(--border)] bg-[var(--card)] p-4">
          <h2 className="mb-3 text-sm font-semibold text-[var(--fg)]">新建声音</h2>
          <div className="grid grid-cols-2 gap-3">
            <label className="col-span-2 flex flex-col gap-1">
              <span className="text-xs text-[var(--muted)]">名称 *</span>
              <input
                type="text"
                value={draft.name}
                onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                className="rounded border border-[var(--border)] bg-[var(--bg)] px-3 py-1.5 text-sm text-[var(--fg)] focus:border-[var(--accent)] focus:outline-none"
                placeholder="如：温柔女声"
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-[var(--muted)]">提供商</span>
              <select
                value={draft.provider}
                onChange={(e) => setDraft({ ...draft, provider: e.target.value })}
                className="rounded border border-[var(--border)] bg-[var(--bg)] px-3 py-1.5 text-sm text-[var(--fg)]"
              >
                {PROVIDERS.map((p) => (
                  <option key={p.value} value={p.value}>
                    {p.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-[var(--muted)]">样本 URL（可选）</span>
              <input
                type="text"
                value={draft.sample_url}
                onChange={(e) => setDraft({ ...draft, sample_url: e.target.value })}
                className="rounded border border-[var(--border)] bg-[var(--bg)] px-3 py-1.5 text-sm text-[var(--fg)] focus:border-[var(--accent)] focus:outline-none"
                placeholder="https://.../sample.wav（用于克隆）"
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
              onClick={() => {
                setShowForm(false)
                setDraft(EMPTY_DRAFT)
              }}
              className="rounded-md border border-[var(--border)] px-3 py-1.5 text-sm text-[var(--muted)] hover:bg-[var(--bg)]"
            >
              取消
            </button>
          </div>
        </div>
      )}

      {loading ? (
        <div className="text-sm text-[var(--muted)]">加载中…</div>
      ) : voices.length === 0 ? (
        <div className="rounded border border-dashed border-[var(--border)] px-6 py-12 text-center text-sm text-[var(--muted)]">
          还没有声音，点击右上角"新建声音"开始
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
          {voices.map((voice) => {
            const providerMeta = PROVIDERS.find((p) => p.value === voice.provider)
            return (
              <div
                key={voice.id}
                className="flex flex-col gap-2 rounded-lg border border-[var(--border)] bg-[var(--card)] p-4"
              >
                <div className="flex items-start justify-between">
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-semibold text-[var(--fg)]">{voice.name}</div>
                    <div className="mt-1 text-[10px] text-[var(--muted)]">
                      {providerMeta?.label ?? voice.provider}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => remove(voice.id)}
                    className="rounded px-2 py-1 text-xs text-[var(--muted)] hover:bg-red-900/30 hover:text-red-300"
                  >
                    ×
                  </button>
                </div>
                {voice.sample_url && (
                  <audio
                    controls
                    src={voice.sample_url}
                    className="h-8 w-full"
                    preload="metadata"
                  />
                )}
                <button
                  type="button"
                  onClick={() => tryClone(voice)}
                  className="mt-1 rounded border border-[var(--border)] px-2 py-1 text-xs text-[var(--muted)] hover:bg-[var(--bg)] hover:text-[var(--fg)]"
                >
                  克隆 / 微调
                </button>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
