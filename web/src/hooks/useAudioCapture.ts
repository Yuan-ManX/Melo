/**
 * useAudioCapture — microphone capture → 16 kHz mono 16-bit PCM.
 *
 * Pipeline:
 *   getUserMedia(audio) → AudioContext → AudioWorklet →
 *     downsample to 16 kHz → Int16 PCM → onChunk callback
 *
 * The worklet is created from a Blob URL so no separate static asset is
 * needed (Vite serves the bundle but worklets must be loaded via URL).
 *
 * The hook does NOT know about WebSocket — the caller passes an
 * `onChunk` callback (typically `ws.sendAudio`).
 */

import { useCallback, useEffect, useRef, useState } from 'react'

const TARGET_SAMPLE_RATE = 16000
// Capture ~30ms of 16kHz mono 16-bit PCM per chunk = 960 bytes.
// This matches the backend VAD frame size exactly.
const TARGET_FRAME_SAMPLES = 480 // 16 kHz * 30 ms

// Worklet source: downsamples the input to TARGET_SAMPLE_RATE and emits
// Int16 PCM frames via port.postMessage. We keep it as a string so the
// Blob URL approach keeps everything in one file.
const PCM_WORKLET_SOURCE = /* js */ `
class PcmCaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super()
    this._targetRate = ${TARGET_SAMPLE_RATE}
    this._frameSamples = ${TARGET_FRAME_SAMPLES}
    this._leftover = []  // leftover downsampled Float32 samples
    this.port.onmessage = (e) => {
      if (e.data && e.data.type === 'stop') {
        this._stopped = true
      }
    }
  }

  process(inputs) {
    const input = inputs[0]
    if (!input || !input.length) return true
    // Take channel 0 (mono).
    const channel = input[0]
    if (!channel || !channel.length) return true

    const inRate = sampleRate
    const outRate = this._targetRate

    // Linear-interpolation downsample.
    const ratio = inRate / outRate
    const outLen = Math.max(1, Math.floor(channel.length / ratio))
    const down = new Float32Array(outLen)
    for (let i = 0; i < outLen; i++) {
      const srcPos = i * ratio
      const srcIdx = Math.floor(srcPos)
      const frac = srcPos - srcIdx
      const a = channel[srcIdx] || 0
      const b = channel[srcIdx + 1] || 0
      down[i] = a + (b - a) * frac
    }

    // Accumulate and slice into fixed frames.
    this._leftover.push(...down)
    while (this._leftover.length >= this._frameSamples) {
      const frame = this._leftover.splice(0, this._frameSamples)
      // Convert Float32 [-1, 1] to Int16 PCM.
      const pcm = new Int16Array(frame.length)
      for (let i = 0; i < frame.length; i++) {
        let s = Math.max(-1, Math.min(1, frame[i]))
        // Convert to 16-bit signed integer.
        pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff
      }
      // Transfer the underlying buffer (zero-copy).
      this.port.postMessage(pcm.buffer, [pcm.buffer])
    }
    return !this._stopped
  }
}
registerProcessor('pcm-capture-processor', PcmCaptureProcessor)
`

interface UseAudioCaptureOptions {
  onChunk: (pcm: ArrayBuffer) => void
  onError?: (err: Error) => void
}

interface UseAudioCaptureApi {
  /** True when the microphone is actively capturing. */
  recording: boolean
  /** Permission / device availability error from getUserMedia. */
  error: Error | null
  start: () => Promise<void>
  stop: () => void
  /** Live audio level (0..1), updated per worklet frame — for UI viz. */
  level: number
}

let workletUrl: string | null = null
function getWorkletUrl(): string {
  if (workletUrl) return workletUrl
  const blob = new Blob([PCM_WORKLET_SOURCE], { type: 'application/javascript' })
  workletUrl = URL.createObjectURL(blob)
  return workletUrl
}

export function useAudioCapture(opts: UseAudioCaptureOptions): UseAudioCaptureApi {
  const { onChunk, onError } = opts
  const [recording, setRecording] = useState(false)
  const [error, setError] = useState<Error | null>(null)
  const [level, setLevel] = useState(0)

  // Live refs so handlers attached once see the latest callbacks.
  const onChunkRef = useRef(onChunk)
  const onErrorRef = useRef(onError)
  useEffect(() => {
    onChunkRef.current = onChunk
  }, [onChunk])
  useEffect(() => {
    onErrorRef.current = onError
  }, [onError])

  const ctxRef = useRef<AudioContext | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const nodeRef = useRef<AudioWorkletNode | null>(null)
  const levelTimerRef = useRef<number | null>(null)

  const stop = useCallback(() => {
    if (levelTimerRef.current !== null) {
      cancelAnimationFrame(levelTimerRef.current)
      levelTimerRef.current = null
    }
    if (nodeRef.current) {
      try {
        nodeRef.current.port.postMessage({ type: 'stop' })
        nodeRef.current.disconnect()
      } catch {
        /* ignore */
      }
      nodeRef.current = null
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop())
      streamRef.current = null
    }
    // Close the AudioContext to fully release the audio graph.
    if (ctxRef.current) {
      const ctx = ctxRef.current
      ctxRef.current = null
      // `close()` returns a promise; let it settle silently.
      ctx.close().catch(() => {
        /* ignore — already closed */
      })
    }
    setRecording(false)
    setLevel(0)
  }, [])

  const start = useCallback(async () => {
    setError(null)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      })
      streamRef.current = stream

      // Use 48 kHz by default (most browsers' default) — the worklet will
      // downsample to 16 kHz. Safari may report 44.1 kHz; both work.
      const ctx = new AudioContext()
      ctxRef.current = ctx
      await ctx.audioWorklet.addModule(getWorkletUrl())

      const source = ctx.createMediaStreamSource(stream)
      const node = new AudioWorkletNode(ctx, 'pcm-capture-processor')
      node.port.onmessage = (e: MessageEvent) => {
        const data = e.data
        if (data instanceof ArrayBuffer) {
          onChunkRef.current?.(data)
        }
      }
      source.connect(node)
      // We don't connect `node` to `ctx.destination` — there is no
      // audible output, just the worklet's port.postMessage.

      nodeRef.current = node

      // Drive a simple RMS level meter off the source node via an
      // AnalyserNode — kept lightweight so it doesn't compete with the
      // worklet for the audio thread.
      const analyser = ctx.createAnalyser()
      analyser.fftSize = 256
      source.connect(analyser)
      const buf = new Uint8Array(analyser.frequencyBinCount)
      const tick = () => {
        analyser.getByteTimeDomainData(buf)
        let sum = 0
        for (let i = 0; i < buf.length; i++) {
          const v = (buf[i] - 128) / 128
          sum += v * v
        }
        const rms = Math.sqrt(sum / buf.length)
        // Smooth a bit so the UI doesn't jitter.
        setLevel((prev) => prev * 0.6 + rms * 0.4)
        levelTimerRef.current = requestAnimationFrame(tick)
      }
      levelTimerRef.current = requestAnimationFrame(tick)

      setRecording(true)
    } catch (err) {
      const e = err instanceof Error ? err : new Error(String(err))
      setError(e)
      onErrorRef.current?.(e)
      stop()
    }
  }, [stop])

  // Cleanup on unmount.
  useEffect(() => {
    return () => {
      stop()
    }
  }, [stop])

  return { recording, error, start, stop, level }
}
