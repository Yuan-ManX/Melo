/**
 * VoiceOrb — the animated "M" orb shown in the empty-state placeholder.
 *
 * Renders a circular gradient badge with the melo-bounce animation. The
 * `lg` size is used by the chat empty state; `sm` is reserved for future
 * voice-message bubbles.
 */

interface VoiceOrbProps {
  size?: 'sm' | 'lg'
  letter?: string
  animate?: boolean
}

export function VoiceOrb({
  size = 'lg',
  letter = 'M',
  animate = true,
}: VoiceOrbProps) {
  const className =
    size === 'sm'
      ? 'mb-6 inline-flex h-12 w-12 text-xl items-center justify-center rounded-full font-bold text-white'
      : 'mb-6 inline-flex h-20 w-20 items-center justify-center rounded-full text-3xl font-bold text-white'
  return (
    <div
      className={className}
      style={{
        background: 'linear-gradient(135deg, var(--accent), var(--accent-2))',
        boxShadow: 'var(--shadow-glow)',
        animation: animate ? 'melo-bounce 2.6s ease-in-out infinite' : undefined,
      }}
    >
      {letter}
    </div>
  )
}
