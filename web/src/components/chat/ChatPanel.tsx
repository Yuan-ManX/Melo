/**
 * ChatPanel — scrolling transcript container + empty-state placeholder.
 *
 * Forwards a ref to the outer scrollable div so the parent can attach
 * an auto-scroll effect.
 */

import { forwardRef } from 'react'
import { VoiceOrb } from '../voice/VoiceOrb'
import { LiveAsrBubble, LiveLlmBubble, MessageBubble } from './MessageBubble'
import type { TranscriptEntry } from './MessageBubble'

interface ChatPanelProps {
  transcript: TranscriptEntry[]
  asrPartial: string
  llmText: string
}

export const ChatPanel = forwardRef<HTMLDivElement, ChatPanelProps>(
  function ChatPanel({ transcript, asrPartial, llmText }, ref) {
    return (
      <div
        ref={ref}
        className="flex-1 overflow-y-auto px-6 py-4 space-y-3"
      >
        {transcript.length === 0 && !asrPartial && !llmText && (
          <div className="mt-12 text-center text-[var(--muted)]">
            <VoiceOrb />
            <p className="text-lg">点击「开始对话」启动语音会话</p>
            <p className="mt-1 text-xs">
              支持实时转写、流式回复、打断式对话。
            </p>
          </div>
        )}

        {transcript.map((entry) => (
          <MessageBubble key={entry.id} entry={entry} />
        ))}

        {/* Live ASR partial */}
        {asrPartial && <LiveAsrBubble text={asrPartial} />}

        {/* Live LLM stream */}
        {llmText && <LiveLlmBubble text={llmText} />}
      </div>
    )
  },
)
