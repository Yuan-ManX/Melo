/**
 * AudioRecorder — mic toggle button + MicIcon.
 *
 * The bottom-left circular button that starts/stops microphone capture.
 * Visual state reflects whether the mic is currently recording.
 */

interface AudioRecorderProps {
  recording: boolean
  disabled: boolean
  onToggle: () => void
}

function MicIcon({ recording }: { recording: boolean }) {
  return (
    <svg
      width="22"
      height="22"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {recording ? (
        <rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor" />
      ) : (
        <>
          <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
          <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
          <line x1="12" y1="19" x2="12" y2="23" />
          <line x1="8" y1="23" x2="16" y2="23" />
        </>
      )}
    </svg>
  )
}

export function AudioRecorder({
  recording,
  disabled,
  onToggle,
}: AudioRecorderProps) {
  return (
    <button
      type="button"
      onClick={onToggle}
      disabled={disabled}
      className={`flex h-14 w-14 items-center justify-center rounded-full border-2 shadow-[var(--shadow-soft)] transition hover:scale-110 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:scale-100 ${
        recording
          ? 'border-red-400 bg-red-500/15 text-red-400'
          : 'border-[var(--c-mint)] bg-[var(--c-mint)]/10 text-[var(--c-mint)] hover:bg-[var(--c-mint)]/20'
      }`}
      title={recording ? '暂停麦克风' : '开启麦克风'}
    >
      <MicIcon recording={recording} />
    </button>
  )
}
