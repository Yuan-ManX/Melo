import { useEffect, useState } from 'react'
import type { Clip } from '../../types'
import { useStudioStore } from '../../stores/studioStore'

interface ClipEditorProps {
  clip: Clip | null
}

export function ClipEditor({ clip }: ClipEditorProps) {
  const {
    updateClip,
    generateClipAudio,
    editClip,
    deleteClip,
    isGenerating,
    isEditing,
    isReverting,
    versions,
    fetchClipVersions,
    revertClipVersion,
  } = useStudioStore()

  const [text, setText] = useState('')
  const [startTime, setStartTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [instruction, setInstruction] = useState('')
  const [dirty, setDirty] = useState(false)

  // Re-sync local state when the selected clip changes.
  useEffect(() => {
    if (!clip) {
      setText('')
      setStartTime(0)
      setDuration(0)
      setDirty(false)
      return
    }
    setText(clip.text)
    setStartTime(clip.start_time)
    setDuration(clip.duration)
    setDirty(false)
    // Load the version history for this clip — the right pane shows
    // them so the user can revert to a prior render.
    fetchClipVersions(clip.id)
  }, [clip?.id, fetchClipVersions])

  if (!clip) {
    return (
      <div className="flex items-center justify-center py-8 text-sm text-[var(--muted)]">
        Select a clip from the timeline to edit it.
      </div>
    )
  }

  const save = async () => {
    await updateClip(clip.id, {
      text,
      start_time: startTime,
      duration,
    })
    setDirty(false)
  }

  const onGenerate = async () => {
    if (dirty) await save()
    await generateClipAudio(clip.id)
  }

  const onEdit = async () => {
    if (!instruction.trim()) return
    await editClip(clip.id, instruction.trim())
    setInstruction('')
  }

  const onDelete = async () => {
    if (confirm('Delete this clip?')) {
      await deleteClip(clip.id)
    }
  }

  const statusColor =
    {
      pending: 'text-[var(--muted)]',
      generating: 'text-amber-400',
      ready: 'text-emerald-400',
      error: 'text-red-400',
    }[clip.status] ?? 'text-[var(--muted)]'

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <div className="text-xs">
          <span className="text-[var(--muted)]">clip </span>
          <code className="text-[var(--fg)]">{clip.id.slice(0, 8)}</code>
          <span className={`ml-2 ${statusColor}`}>● {clip.status}</span>
        </div>
        <button
          type="button"
          onClick={onDelete}
          className="rounded px-2 py-1 text-xs text-[var(--muted)] hover:bg-red-900/30 hover:text-red-300"
        >
          Delete
        </button>
      </div>

      <label className="flex flex-col gap-1">
        <span className="text-xs text-[var(--muted)]">Text</span>
        <textarea
          value={text}
          onChange={(e) => {
            setText(e.target.value)
            setDirty(true)
          }}
          rows={4}
          className="rounded-md border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-sm text-[var(--fg)] focus:border-[var(--accent)] focus:outline-none"
        />
      </label>

      <div className="grid grid-cols-2 gap-3">
        <label className="flex flex-col gap-1">
          <span className="text-xs text-[var(--muted)]">Start (s)</span>
          <input
            type="number"
            min={0}
            step={0.1}
            value={startTime}
            onChange={(e) => {
              setStartTime(parseFloat(e.target.value) || 0)
              setDirty(true)
            }}
            className="rounded-md border border-[var(--border)] bg-[var(--card)] px-3 py-1.5 text-sm text-[var(--fg)] focus:border-[var(--accent)] focus:outline-none"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-[var(--muted)]">Duration (s)</span>
          <input
            type="number"
            min={0}
            step={0.1}
            value={duration}
            onChange={(e) => {
              setDuration(parseFloat(e.target.value) || 0)
              setDirty(true)
            }}
            className="rounded-md border border-[var(--border)] bg-[var(--card)] px-3 py-1.5 text-sm text-[var(--fg)] focus:border-[var(--accent)] focus:outline-none"
          />
        </label>
      </div>

      <div className="flex gap-2">
        <button
          type="button"
          onClick={save}
          disabled={!dirty}
          className="flex-1 rounded-md border border-[var(--border)] px-3 py-1.5 text-sm text-[var(--fg)] hover:bg-[var(--card)] disabled:opacity-40"
        >
          Save
        </button>
        <button
          type="button"
          onClick={onGenerate}
          disabled={isGenerating}
          className="flex-1 rounded-md bg-[var(--accent)] px-3 py-1.5 text-sm font-medium text-black disabled:opacity-40"
        >
          {isGenerating ? 'Generating…' : 'Generate TTS'}
        </button>
      </div>

      {clip.audio_url && (
        <audio controls src={clip.audio_url} className="w-full" preload="metadata" />
      )}

      <div className="mt-2 border-t border-[var(--border)] pt-3">
        <span className="text-xs text-[var(--muted)]">Natural-language edit</span>
        <div className="mt-1 flex gap-2">
          <input
            type="text"
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && onEdit()}
            placeholder="e.g. speed up to 1.3, trim silence, regenerate…"
            className="flex-1 rounded-md border border-[var(--border)] bg-[var(--card)] px-3 py-1.5 text-sm text-[var(--fg)] placeholder:text-[var(--muted)] focus:border-[var(--accent)] focus:outline-none"
          />
          <button
            type="button"
            onClick={onEdit}
            disabled={isEditing || !instruction.trim()}
            className="rounded-md border border-[var(--border)] px-3 py-1.5 text-sm text-[var(--fg)] hover:bg-[var(--card)] disabled:opacity-40"
          >
            {isEditing ? '…' : 'Apply'}
          </button>
        </div>
        <div className="mt-1 text-[10px] text-[var(--muted)]">
          Supported: regenerate · speed up / slow down [to N] · replace text with … · trim silence · delete
        </div>
      </div>

      {versions.length > 0 && (
        <div className="mt-2 border-t border-[var(--border)] pt-3">
          <div className="flex items-center justify-between">
            <span className="text-xs text-[var(--muted)]">
              Versions ({versions.length})
            </span>
          </div>
          <ul className="mt-2 flex flex-col gap-1">
            {[...versions].reverse().map((v) => {
              const isCurrent =
                clip.audio_url != null && v.audio_url === clip.audio_url
              return (
                <li
                  key={v.index}
                  className="flex items-center justify-between rounded border border-[var(--border)] bg-[var(--card)] px-2 py-1 text-xs"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-[var(--fg)]">#{v.index}</span>
                      {v.speed != null && (
                        <span className="text-[var(--muted)]">{v.speed.toFixed(2)}×</span>
                      )}
                      {v.bytes != null && (
                        <span className="text-[var(--muted)]">
                          {(v.bytes / 1024).toFixed(0)} KB
                        </span>
                      )}
                      {isCurrent && (
                        <span className="text-emerald-400">● current</span>
                      )}
                    </div>
                    {v.created_at && (
                      <div className="mt-0.5 truncate text-[10px] text-[var(--muted)]">
                        {v.created_at}
                      </div>
                    )}
                  </div>
                  <button
                    type="button"
                    onClick={() => revertClipVersion(clip.id, v.index)}
                    disabled={isReverting || isCurrent}
                    className="ml-2 shrink-0 rounded border border-[var(--border)] px-2 py-0.5 text-[10px] text-[var(--fg)] hover:bg-[var(--bg)] disabled:opacity-30"
                    title={isCurrent ? 'Already active' : 'Revert to this version'}
                  >
                    {isReverting ? '…' : 'Revert'}
                  </button>
                </li>
              )
            })}
          </ul>
        </div>
      )}
    </div>
  )
}
