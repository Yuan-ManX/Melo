import { useStudioStore } from '../../stores/studioStore'

const TRACK_COLORS = ['#4a8cff', '#22c55e', '#f59e0b', '#ec4899', '#a855f7', '#14b8a6']

interface TransportBarProps {
  /** Total duration of the timeline (seconds). */
  duration: number
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

export function TransportBar({ duration }: TransportBarProps) {
  const { isPlaying, playheadTime, play, pause, stop, seek } = useStudioStore()

  return (
    <div className="flex items-center gap-4 border-b border-[var(--border)] px-4 py-3">
      <button
        type="button"
        onClick={isPlaying ? pause : play}
        disabled={duration <= 0}
        className="rounded-md bg-[var(--accent)] px-3 py-1.5 text-sm font-medium text-black transition-colors hover:brightness-110 disabled:opacity-40"
      >
        {isPlaying ? 'Pause' : 'Play'}
      </button>
      <button
        type="button"
        onClick={stop}
        className="rounded-md border border-[var(--border)] px-3 py-1.5 text-sm text-[var(--fg)] hover:bg-[var(--card)]"
      >
        Stop
      </button>
      <div className="text-xs text-[var(--muted)] tabular-nums">
        {formatTime(playheadTime)} / {formatTime(duration)}
      </div>
      <input
        type="range"
        min={0}
        max={Math.max(duration, 0.1)}
        step={0.05}
        value={playheadTime}
        onChange={(e) => seek(parseFloat(e.target.value))}
        className="flex-1 accent-[var(--accent)]"
        disabled={duration <= 0}
      />
    </div>
  )
}

export { TRACK_COLORS }
