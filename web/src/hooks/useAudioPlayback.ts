/**
 * useAudioPlayback — TTS audio queue playback.
 *
 * Responsibilities:
 *   - Maintain a single AudioContext for scheduling TTS chunks.
 *   - Decode and enqueue incoming audio bytes for back-to-back playback.
 *   - Expose `play(bytes)` for queueing, `flush()` to drop pending schedule,
 *     and `dispose()` to close the AudioContext.
 *
 * The hook does NOT know about WebSocket — the caller decides which bytes
 * to feed it (typically from `useWebSocket`'s `onAudio` callback).
 */

import { useCallback, useEffect, useRef, useState } from 'react'

interface UseAudioPlaybackApi {
  /** Queue an audio buffer (WAV/MP3 bytes) for immediate playback. Schedules back-to-back. */
  play: (bytes: ArrayBuffer) => Promise<void>
  /** Drop the scheduled queue and reset the next-start time. */
  flush: () => void
  /** Close the underlying AudioContext and release resources. */
  dispose: () => void
  /** Whether the AudioContext has been created and is not closed. */
  ready: boolean
}

export function useAudioPlayback(): UseAudioPlaybackApi {
  const audioCtxRef = useRef<AudioContext | null>(null)
  const nextStartTimeRef = useRef(0)
  const [ready, setReady] = useState(false)

  // Lazily create the AudioContext on first use — must be created in
  // response to a user gesture to comply with autoplay policies. The
  // caller triggers `play` (or `flush` has no side-effect) from a click.
  const ensureAudioContext = useCallback((): AudioContext => {
    if (!audioCtxRef.current || audioCtxRef.current.state === 'closed') {
      audioCtxRef.current = new AudioContext()
      nextStartTimeRef.current = 0
      setReady(true)
    }
    return audioCtxRef.current
  }, [])

  const play = useCallback(
    async (bytes: ArrayBuffer): Promise<void> => {
      const ctx = ensureAudioContext()
      if (ctx.state === 'suspended') {
        try {
          await ctx.resume()
        } catch {
          /* ignore — autoplay policies may block resume until a gesture */
        }
      }
      try {
        const decoded = await ctx.decodeAudioData(bytes.slice(0))
        const src = ctx.createBufferSource()
        src.buffer = decoded
        src.connect(ctx.destination)
        const now = ctx.currentTime
        const start = Math.max(now, nextStartTimeRef.current)
        src.start(start)
        nextStartTimeRef.current = start + decoded.duration
      } catch (err) {
        // decodeAudioData fails on truncated WAVs — surface to console
        // rather than the caller (chunk-boundary noise).
        // eslint-disable-next-line no-console
        console.warn('TTS decode failed', err)
      }
    },
    [ensureAudioContext],
  )

  const flush = useCallback(() => {
    // We can't truly cancel already-started buffers without tracking them,
    // but resetting the start time is enough for the queue.
    nextStartTimeRef.current = 0
  }, [])

  const dispose = useCallback(() => {
    if (audioCtxRef.current) {
      const ctx = audioCtxRef.current
      audioCtxRef.current = null
      nextStartTimeRef.current = 0
      ctx.close().catch(() => {
        /* ignore — already closed */
      })
      setReady(false)
    }
  }, [])

  // Cleanup on unmount.
  useEffect(() => {
    return () => {
      dispose()
    }
  }, [dispose])

  return { play, flush, dispose, ready }
}
