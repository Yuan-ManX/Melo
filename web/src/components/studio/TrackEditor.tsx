import { useState } from 'react'
import type { Track, Voice } from '../../types'
import { useStudioStore } from '../../stores/studioStore'
import { TRACK_COLORS } from './TransportBar'

interface TrackEditorProps {
  tracks: Track[]
  voices: Voice[]
}

export function TrackEditor({ tracks, voices }: TrackEditorProps) {
  const { addTrack, updateTrack, deleteTrack, addClip, selectClip } = useStudioStore()
  const [newName, setNewName] = useState('')

  const handleAdd = async () => {
    if (!newName.trim()) return
    await addTrack(newName.trim())
    setNewName('')
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex gap-2">
        <input
          type="text"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          placeholder="New track name…"
          onKeyDown={(e) => e.key === 'Enter' && handleAdd()}
          className="flex-1 rounded-md border border-[var(--border)] bg-[var(--card)] px-3 py-1.5 text-sm text-[var(--fg)] placeholder:text-[var(--muted)] focus:border-[var(--accent)] focus:outline-none"
        />
        <button
          type="button"
          onClick={handleAdd}
          disabled={!newName.trim()}
          className="rounded-md bg-[var(--accent)] px-3 py-1.5 text-sm font-medium text-black disabled:opacity-40"
        >
          + Track
        </button>
      </div>

      <div className="flex flex-col gap-2">
        {tracks.map((track, idx) => (
          <TrackRow
            key={track.id}
            track={track}
            voices={voices}
            colorIndex={idx}
            onRename={(name) => updateTrack(track.id, { name })}
            onVoiceChange={(voiceId) => updateTrack(track.id, { voice_id: voiceId || null })}
            onDelete={() => deleteTrack(track.id)}
            onAddClip={() => addClip(track.id, '新片段', 0).then((c) => c && selectClip(c.id))}
          />
        ))}
        {tracks.length === 0 && (
          <div className="text-xs text-[var(--muted)] py-4 text-center">
            Add a track to start arranging clips.
          </div>
        )}
      </div>
    </div>
  )
}

interface TrackRowProps {
  track: Track
  voices: Voice[]
  colorIndex: number
  onRename: (name: string) => void
  onVoiceChange: (voiceId: string) => void
  onDelete: () => void
  onAddClip: () => void
}

function TrackRow({ track, voices, colorIndex, onRename, onVoiceChange, onDelete, onAddClip }: TrackRowProps) {
  const color = TRACK_COLORS[colorIndex % TRACK_COLORS.length]
  const [editingName, setEditingName] = useState(false)
  const [draftName, setDraftName] = useState(track.name)

  const commit = () => {
    if (draftName.trim() && draftName !== track.name) {
      onRename(draftName.trim())
    } else {
      setDraftName(track.name)
    }
    setEditingName(false)
  }

  return (
    <div className="flex items-center gap-2 rounded-md border border-[var(--border)] bg-[var(--card)] px-3 py-2">
      <span className="inline-block h-3 w-3 rounded-full" style={{ background: color }} />
      {editingName ? (
        <input
          autoFocus
          type="text"
          value={draftName}
          onChange={(e) => setDraftName(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === 'Enter') commit()
            if (e.key === 'Escape') {
              setDraftName(track.name)
              setEditingName(false)
            }
          }}
          className="flex-1 rounded border border-[var(--accent)] bg-[var(--bg)] px-2 py-0.5 text-sm text-[var(--fg)]"
        />
      ) : (
        <button
          type="button"
          onClick={() => setEditingName(true)}
          className="flex-1 text-left text-sm text-[var(--fg)] hover:underline"
          title="Click to rename"
        >
          {track.name}
        </button>
      )}
      <select
        value={track.voice_id ?? ''}
        onChange={(e) => onVoiceChange(e.target.value)}
        className="rounded border border-[var(--border)] bg-[var(--bg)] px-2 py-1 text-xs text-[var(--fg)]"
      >
        <option value="">— no voice —</option>
        {voices.map((v) => (
          <option key={v.id} value={v.id}>
            {v.name}
          </option>
        ))}
      </select>
      <button
        type="button"
        onClick={onAddClip}
        className="rounded px-2 py-1 text-xs text-[var(--fg)] hover:bg-[var(--bg)]"
        style={{ color }}
        title="Add a clip to this track"
      >
        + 片段
      </button>
      <button
        type="button"
        onClick={onDelete}
        className="rounded px-2 py-1 text-xs text-[var(--muted)] hover:bg-red-900/30 hover:text-red-300"
        title="Delete track"
      >
        ×
      </button>
    </div>
  )
}
