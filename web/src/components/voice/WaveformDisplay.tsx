/**
 * WaveformDisplay — live recording indicator (pulse dot + label).
 *
 * Renders nothing when the session is inactive. Otherwise shows a red
 * pulsing dot when the mic is recording, or a blue static dot when paused.
 */

interface WaveformDisplayProps {
  active: boolean
  recording: boolean
}

export function WaveformDisplay({ active, recording }: WaveformDisplayProps) {
  if (!active) return null
  return (
    <div className="flex items-center gap-2 text-sm">
      <span
        className={`h-2 w-2 rounded-full ${
          recording ? 'bg-red-400 animate-pulse' : 'bg-[var(--c-blue)]'
        }`}
      />
      <span className="text-[var(--muted)]">
        {recording ? '录音中' : '已暂停'}
      </span>
    </div>
  )
}
