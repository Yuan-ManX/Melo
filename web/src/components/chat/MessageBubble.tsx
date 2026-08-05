/**
 * MessageBubble — transcript row + live ASR/LLM streaming bubbles.
 *
 * Exports:
 *   - TranscriptEntry (shared type)
 *   - MessageBubble (finalized transcript row: system / user / assistant)
 *   - LiveAsrBubble (in-flight ASR partial text)
 *   - LiveLlmBubble (in-flight LLM streaming text)
 */

export interface TranscriptEntry {
  id: string
  role: 'user' | 'assistant' | 'system'
  text: string
  ts: number
}

interface MessageBubbleProps {
  entry: TranscriptEntry
}

export function MessageBubble({ entry }: MessageBubbleProps) {
  if (entry.role === 'system') {
    const isResult = entry.text.startsWith('✓')
    const color = isResult ? 'var(--c-mint)' : 'var(--c-yellow)'
    return (
      <div className="flex justify-center">
        <span
          className="rounded-full px-3 py-1 text-xs font-medium"
          style={{
            color,
            backgroundColor: `color-mix(in srgb, ${color} 14%, transparent)`,
          }}
        >
          {entry.text}
        </span>
      </div>
    )
  }
  if (entry.role === 'user') {
    return (
      <div className="flex justify-end">
        <div
          className="max-w-[80%] rounded-2xl rounded-br-sm px-4 py-2 text-sm text-white shadow-[var(--shadow-soft)]"
          style={{ background: 'linear-gradient(135deg, var(--accent), var(--c-blue))' }}
        >
          {entry.text}
        </div>
      </div>
    )
  }
  return (
    <div className="flex justify-start">
      <div className="max-w-[80%] rounded-2xl rounded-bl-sm border border-[var(--accent)]/25 bg-[var(--accent)]/15 px-4 py-2 text-sm text-[var(--fg)] shadow-[var(--shadow-soft)]">
        {entry.text}
      </div>
    </div>
  )
}

interface LiveAsrBubbleProps {
  text: string
}

export function LiveAsrBubble({ text }: LiveAsrBubbleProps) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[80%] rounded-2xl rounded-br-sm border border-[var(--border)] bg-[var(--card)]/60 px-4 py-2 text-sm text-[var(--muted)] shadow-[var(--shadow-soft)]">
        {text}
        <span className="ml-1 inline-block h-3 w-1 animate-pulse bg-[var(--accent-2)] align-middle" />
      </div>
    </div>
  )
}

interface LiveLlmBubbleProps {
  text: string
}

export function LiveLlmBubble({ text }: LiveLlmBubbleProps) {
  return (
    <div className="flex justify-start">
      <div className="max-w-[80%] rounded-2xl rounded-bl-sm bg-[var(--accent)]/15 px-4 py-2 text-sm text-[var(--fg)] shadow-[var(--shadow-soft)]">
        {text}
        <span className="ml-1 inline-block h-3 w-1 animate-pulse bg-[var(--accent-2)] align-middle" />
      </div>
    </div>
  )
}
