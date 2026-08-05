import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { ServerSettings } from '../types'

function StatusDot({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs">
      <span
        className={`inline-block h-2 w-2 rounded-full ${ok ? 'bg-emerald-400' : 'bg-red-400'}`}
      />
      <span className={ok ? 'text-emerald-400' : 'text-red-400'}>{label}</span>
    </span>
  )
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between border-b border-[var(--border)] py-2 text-sm last:border-0">
      <span className="text-[var(--muted)]">{label}</span>
      <span className="font-mono text-[var(--fg)]">{value}</span>
    </div>
  )
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-4">
      <h2 className="mb-3 text-sm font-semibold text-[var(--fg)]">{title}</h2>
      <div className="flex flex-col">{children}</div>
    </div>
  )
}

export function SettingsRoute() {
  const [settings, setSettings] = useState<ServerSettings | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [prefs, setPrefs] = useState(() => {
    const raw = localStorage.getItem('melo_prefs')
    return raw ? (JSON.parse(raw) as { default_agent_id: string; auto_play_tts: boolean }) : { default_agent_id: '', auto_play_tts: true }
  })

  useEffect(() => {
    api.getSettings().then(setSettings).catch((e) => setError((e as Error).message))
  }, [])

  const savePrefs = (next: typeof prefs) => {
    setPrefs(next)
    localStorage.setItem('melo_prefs', JSON.stringify(next))
  }

  return (
    <div className="mx-auto flex h-full max-w-4xl flex-col gap-4 overflow-auto p-6">
      <div>
        <h1 className="text-2xl font-bold text-[var(--fg)]">设置</h1>
        <p className="text-xs text-[var(--muted)]">
          查看 Melo 运行时配置；服务端配置为只读，需修改 <code className="rounded bg-[var(--card)] px-1">.env</code> 后重启后端
        </p>
      </div>

      {error && (
        <div className="rounded border border-red-900/50 bg-red-950/30 px-3 py-2 text-xs text-red-300">
          {error}
        </div>
      )}

      {settings ? (
        <>
          <Card title="应用">
            <Row label="名称" value={settings.app.name} />
            <Row label="版本" value={settings.app.version} />
            <Row label="后端端口" value={settings.app.backend_port} />
          </Card>

          <Card title="LLM 大语言模型">
            <Row
              label="当前 Provider"
              value={
                <span
                  className={`rounded px-2 py-0.5 text-xs ${
                    settings.llm.provider === 'stub'
                      ? 'bg-amber-900/40 text-amber-300'
                      : 'bg-emerald-900/40 text-emerald-300'
                  }`}
                >
                  {settings.llm.provider}
                </span>
              }
            />
            <Row label="OpenAI 模型" value={settings.llm.openai.default_model} />
            <Row label="OpenAI Base URL" value={settings.llm.openai.base_url} />
            <Row
              label="OpenAI API Key"
              value={<StatusDot ok={settings.llm.openai.has_api_key} label={settings.llm.openai.has_api_key ? '已配置' : '未配置'} />}
            />
            <Row label="Anthropic 模型" value={settings.llm.anthropic.default_model} />
            <Row label="Anthropic Base URL" value={settings.llm.anthropic.base_url} />
            <Row
              label="Anthropic API Key"
              value={<StatusDot ok={settings.llm.anthropic.has_api_key} label={settings.llm.anthropic.has_api_key ? '已配置' : '未配置'} />}
            />
          </Card>

          <Card title="语音管线">
            <Row label="ASR Provider" value={settings.voice.asr_provider} />
            <Row label="Whisper 模型尺寸" value={settings.voice.whisper_model_size} />
            <Row label="TTS Provider" value={settings.voice.tts_provider} />
            <Row label="Piper 默认声音" value={settings.voice.piper_default_voice ?? '—'} />
            <Row label="声音克隆 Provider" value={settings.voice.clone_provider} />
            <Row
              label="ElevenLabs API Key"
              value={<StatusDot ok={settings.voice.has_elevenlabs_key} label={settings.voice.has_elevenlabs_key ? '已配置' : '未配置'} />}
            />
            <Row
              label="Deepgram API Key"
              value={<StatusDot ok={settings.voice.has_deepgram_key} label={settings.voice.has_deepgram_key ? '已配置' : '未配置'} />}
            />
          </Card>

          <Card title="WebSocket 语音通道">
            <Row label="采样率" value={`${settings.websocket.sample_rate} Hz`} />
            <Row label="VAD 阈值" value={settings.websocket.vad_threshold} />
            <Row label="静默填充" value={`${settings.websocket.silence_pad_ms} ms`} />
          </Card>
        </>
      ) : (
        <div className="text-sm text-[var(--muted)]">加载配置中…</div>
      )}

      <Card title="本地偏好（仅当前浏览器）">
        <div className="flex items-center justify-between border-b border-[var(--border)] py-2 text-sm">
          <span className="text-[var(--muted)]">默认 Agent</span>
          <input
            type="text"
            value={prefs.default_agent_id}
            onChange={(e) => savePrefs({ ...prefs, default_agent_id: e.target.value })}
            placeholder="Agent ID（可选）"
            className="w-48 rounded border border-[var(--border)] bg-[var(--bg)] px-2 py-1 text-xs text-[var(--fg)] focus:border-[var(--accent)] focus:outline-none"
          />
        </div>
        <div className="flex items-center justify-between py-2 text-sm">
          <span className="text-[var(--muted)]">TTS 自动播放</span>
          <button
            type="button"
            onClick={() => savePrefs({ ...prefs, auto_play_tts: !prefs.auto_play_tts })}
            className={`relative h-5 w-10 rounded-full transition-colors ${
              prefs.auto_play_tts ? 'bg-[var(--accent)]' : 'bg-[var(--border)]'
            }`}
          >
            <span
              className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform ${
                prefs.auto_play_tts ? 'translate-x-5' : 'translate-x-0.5'
              }`}
            />
          </button>
        </div>
      </Card>

      <div className="rounded border border-dashed border-[var(--border)] p-4 text-xs text-[var(--muted)]">
        <div className="mb-2 font-semibold text-[var(--fg)]">配置提示</div>
        <ul className="list-disc space-y-1 pl-4">
          <li>服务端配置通过环境变量 / <code>.env</code> 文件读取，需重启后端生效</li>
          <li>API Key 仅以布尔值返回前端，明文不会暴露</li>
          <li>LLM provider 为 <code>stub</code> 时不消耗 token，仅用于开发调试</li>
          <li>本地偏好存储在浏览器 localStorage，跨设备不同步</li>
        </ul>
      </div>
    </div>
  )
}
