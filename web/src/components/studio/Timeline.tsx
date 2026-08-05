import type { DragEvent } from 'react'
import type { Clip, TrackWithClips } from '../../types'
import { useStudioStore } from '../../stores/studioStore'
import { TRACK_COLORS } from './TransportBar'

interface TimelineProps {
  tracks: TrackWithClips[]
  /** Total duration to display (seconds). */
  duration: number
}

const LABEL_WIDTH = 140 // px reserved for track labels
const ROW_HEIGHT = 56 // px per track lane
const MIN_TRACK_WIDTH = 600 // px minimum total timeline width

/**
 * Drag payload schema — carried via the native clipboard's `text/plain`
 * slot so a single drag can carry both the clip id and its source track.
 */
interface DragPayload {
  clipId: string
  fromTrackId: string
}

function readDragPayload(e: DragEvent): DragPayload | null {
  const raw = e.dataTransfer.getData('text/plain')
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw) as DragPayload
    if (typeof parsed.clipId === 'string' && typeof parsed.fromTrackId === 'string') {
      return parsed
    }
  } catch {
    // Malformed payload — ignore.
  }
  return null
}

export function Timeline({ tracks, duration }: TimelineProps) {
  const { selectedClipId, selectClip, playheadTime, updateClip } = useStudioStore()
  const viewDuration = Math.max(duration, 1)
  // Width-per-second scales so longer projects don't squeeze clips to 0px.
  const containerWidth = Math.max(MIN_TRACK_WIDTH, viewDuration * 40)
  const pxPerSecond = (containerWidth - LABEL_WIDTH) / viewDuration

  const playheadX = LABEL_WIDTH + playheadTime * pxPerSecond

  // Drag handlers — bound to each track lane's drop target. We compute
  // the new start_time from the cursor's X position relative to the
  // lane, snapping to 0.1s to avoid floating-point jitter on the wire.
  const handleDragOver = (e: DragEvent) => {
    // Allow drop — without this the browser would refuse the drop.
    e.preventDefault()
    if (e.dataTransfer.dropEffect !== 'move') {
      e.dataTransfer.dropEffect = 'move'
    }
  }

  const handleDrop = (e: DragEvent, toTrackId: string) => {
    e.preventDefault()
    const payload = readDragPayload(e)
    if (!payload) return
    // X position relative to the lane (subtract label gutter).
    const laneX = e.clientX - e.currentTarget.getBoundingClientRect().left
    const newStart = Math.max(0, Math.round(laneX / pxPerSecond * 10) / 10)
    // Always send both fields — a same-track drag still updates start_time,
    // a cross-track drag additionally moves the clip.
    updateClip(payload.clipId, {
      track_id: toTrackId,
      start_time: newStart,
    })
  }

  if (tracks.length === 0) {
    return (
      <div className="flex items-center justify-center py-12 text-sm text-[var(--muted)]">
        No tracks yet — add one above to get started.
      </div>
    )
  }

  return (
    <div
      className="relative overflow-x-auto border-b border-[var(--border)]"
      style={{ minWidth: containerWidth }}
    >
      {/* Time ruler */}
      <div
        className="flex border-b border-[var(--border)] text-[10px] text-[var(--muted)]"
        style={{ height: 20 }}
      >
        <div style={{ width: LABEL_WIDTH }} className="px-2 py-1 border-r border-[var(--border)]">
          Track
        </div>
        <div className="relative flex-1">
          {Array.from({ length: Math.ceil(viewDuration) + 1 }).map((_, i) => (
            <div
              key={i}
              className="absolute top-0 bottom-0 border-l border-[var(--border)] px-1 py-1"
              style={{ left: i * pxPerSecond }}
            >
              {i}s
            </div>
          ))}
        </div>
      </div>

      {/* Track lanes */}
      {tracks.map((track, idx) => {
        const color = TRACK_COLORS[idx % TRACK_COLORS.length]
        return (
          <div
            key={track.id}
            className="flex border-b border-[var(--border)]"
            style={{ height: ROW_HEIGHT }}
          >
            <div
              className="flex items-center truncate border-r border-[var(--border)] px-2 text-xs"
              style={{ width: LABEL_WIDTH }}
              title={track.name}
            >
              <span className="mr-2 inline-block h-2 w-2 rounded-full" style={{ background: color }} />
              <span className="truncate">{track.name}</span>
            </div>
            <div
              className="relative flex-1"
              onDragOver={handleDragOver}
              onDrop={(e) => handleDrop(e, track.id)}
            >
              {track.clips.map((clip) => (
                <ClipBlock
                  key={clip.id}
                  clip={clip}
                  color={color}
                  pxPerSecond={pxPerSecond}
                  isSelected={clip.id === selectedClipId}
                  onSelect={() => selectClip(clip.id)}
                  fromTrackId={track.id}
                />
              ))}
            </div>
          </div>
        )
      })}

      {/* Playhead overlay */}
      {playheadTime > 0 && playheadTime <= viewDuration && (
        <div
          className="pointer-events-none absolute top-0 bottom-0 w-px bg-[var(--accent)] opacity-80"
          style={{ left: playheadX, height: '100%' }}
        />
      )}
    </div>
  )
}

interface ClipBlockProps {
  clip: Clip
  color: string
  pxPerSecond: number
  isSelected: boolean
  onSelect: () => void
  /** Track the clip currently lives in — carried in the drag payload. */
  fromTrackId: string
}

function ClipBlock({
  clip,
  color,
  pxPerSecond,
  isSelected,
  onSelect,
  fromTrackId,
}: ClipBlockProps) {
  const left = clip.start_time * pxPerSecond
  const width = Math.max(40, clip.duration * pxPerSecond || 80)
  const isReady = clip.status === 'ready'
  const isGenerating = clip.status === 'generating'

  // We keep the native button semantics for click-to-select but layer
  // draggable on top — the browser fires `click` after a drag only if
  // the cursor didn't move, so the two interactions don't conflict.
  const handleDragStart = (e: DragEvent) => {
    const payload: DragPayload = { clipId: clip.id, fromTrackId }
    e.dataTransfer.setData('text/plain', JSON.stringify(payload))
    e.dataTransfer.effectAllowed = 'move'
  }

  return (
    <button
      type="button"
      draggable
      onDragStart={handleDragStart}
      onClick={onSelect}
      className={`absolute top-1 bottom-1 overflow-hidden rounded border px-2 py-1 text-left text-[11px] transition-shadow ${
        isSelected ? 'ring-2 ring-white' : ''
      } cursor-grab active:cursor-grabbing`}
      style={{
        left,
        width,
        background: isGenerating ? `${color}33` : `${color}22`,
        borderColor: color,
      }}
      title={clip.text}
    >
      <div className="truncate font-medium text-[var(--fg)]">
        {clip.text.slice(0, 32) || '(empty)'}
      </div>
      <div className="text-[9px] text-[var(--muted)]">
        {isGenerating ? 'generating…' : isReady ? `${clip.duration.toFixed(1)}s` : clip.status}
      </div>
    </button>
  )
}
