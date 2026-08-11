/**
 * useAudioPlayback — TTS audio queue playback.
 *
 * Responsibilities:
 *   - Maintain a single AudioContext for scheduling TTS chunks.
 *   - Decode and enqueue incoming audio bytes for back-to-back playback.
 *   - Track every scheduled AudioBufferSourceNode so `flush()` can
 *     hard-cancel them when the user (or the server) interrupts the
 *     current turn mid-playback.
 *   - Auto-prune finished sources from the active set so the set
 *     doesn't grow unbounded over a long session.
 *   - Expose `play(bytes)` for queueing, `flush()` to drop pending
 *     schedule + stop active playback, and `dispose()` to close the
 *     AudioContext.
 *
 * The hook does NOT know about WebSocket — the caller decides which bytes
 * to feed it (typically from `useWebSocket`'s `onAudio` callback).
 */

import { useCallback, useEffect, useRef, useState } from 'react'

interface UseAudioPlaybackApi {
  /** Queue an audio buffer (WAV/MP3 bytes) for immediate playback. Schedules back-to-back. */
  play: (bytes: ArrayBuffer) => Promise<void>
  /** Hard-cancel all active + scheduled playback and reset the queue. */
  flush: () => void
  /** Close the underlying AudioContext and release resources. */
  dispose: () => void
  /** Whether the AudioContext has been created and is not closed. */
  ready: boolean
  /** Whether at least one source is currently scheduled or playing. */
  playing: boolean
}

export function useAudioPlayback(): UseAudioPlaybackApi {
  const audioCtxRef = useRef<AudioContext | null>(null)
  const nextStartTimeRef = useRef(0)
  // Active + scheduled sources. We hold them so `flush()` can call
  // `stop()` on each — without this, scheduled-but-not-yet-started
  // buffers would play through even after the user interrupted.
  const activeSourcesRef = useRef<Set<AudioBufferSourceNode>>(new Set())
  const [ready, setReady] = useState(false)
  const [playing, setPlaying] = useState(false)

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

  // Internal: sync the `playing` flag with the active-sources set.
  // Called after every source add + every source end / cancel.
  const syncPlayingFlag = useCallback(() => {
    const n = activeSourcesRef.current.size
    setPlaying((prev) => (prev === (n > 0) ? prev : n > 0))
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
        // Track the source so flush() can hard-cancel it. Auto-remove
        // on `ended` so the set doesn't grow without bound.
        activeSourcesRef.current.add(src)
        syncPlayingFlag()
        src.onended = () => {
          activeSourcesRef.current.delete(src)
          syncPlayingFlag()
        }
      } catch (err) {
        // decodeAudioData fails on truncated WAVs — surface to console
        // rather than the caller (chunk-boundary noise).
        // eslint-disable-next-line no-console
        console.warn('TTS decode failed', err)
      }
    },
    [ensureAudioContext, syncPlayingFlag],
  )

  const flush = useCallback(() => {
    // Hard-cancel every tracked source. `try/catch` guards against
    // sources that already self-ended between the scheduler tick and
    // this loop (calling stop() twice on a source throws).
    activeSourcesRef.current.forEach((src) => {
      try {
        src.stop()
      } catch {
        /* already ended — ignore */
      }
      try {
        src.disconnect()
      } catch {
        /* already disconnected — ignore */
      }
    })
    activeSourcesRef.current.clear()
    // Reset the next-start time so the next `play()` starts immediately
    // rather than at the (now-stale) scheduled tail.
    nextStartTimeRef.current = 0
    syncPlayingFlag()
  }, [syncPlayingFlag])

  const dispose = useCallback(() => {
    if (audioCtxRef.current) {
      const ctx = audioCtxRef.current
      audioCtxRef.current = null
      nextStartTimeRef.current = 0
      activeSourcesRef.current.forEach((src) => {
        try {
          src.stop()
        } catch {
          /* ignore */
        }
      })
      activeSourcesRef.current.clear()
      ctx.close().catch(() => {
        /* ignore — already closed */
      })
      setReady(false)
      setPlaying(false)
    }
  }, [])

  // Cleanup on unmount.
  useEffect(() => {
    return () => {
      dispose()
    }
  }, [dispose])

  return { play, flush, dispose, ready, playing }
}
