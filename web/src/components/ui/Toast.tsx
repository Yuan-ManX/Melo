import { useSyncExternalStore } from 'react'
import { createPortal } from 'react-dom'

export type ToastVariant = 'info' | 'success' | 'warning' | 'error'

export interface ToastItem {
  id: string
  title?: string
  message: string
  variant: ToastVariant
  duration: number // ms; 0 = sticky
}

export interface UseToastApi {
  push: (toast: Omit<ToastItem, 'id'>) => string // returns id
  dismiss: (id: string) => void
  clear: () => void
}

// --- module-level singleton store ----------------------------------------

let toasts: ToastItem[] = []
const listeners = new Set<() => void>()
const timers = new Map<string, ReturnType<typeof setTimeout>>()

function emit(): void {
  for (const listener of listeners) {
    listener()
  }
}

function subscribe(callback: () => void): () => void {
  listeners.add(callback)
  return () => {
    listeners.delete(callback)
  }
}

function getSnapshot(): ToastItem[] {
  return toasts
}

function dismiss(id: string): void {
  const timer = timers.get(id)
  if (timer !== undefined) {
    clearTimeout(timer)
    timers.delete(id)
  }
  const exists = toasts.some((t) => t.id === id)
  if (!exists) return
  toasts = toasts.filter((t) => t.id !== id)
  emit()
}

function push(toast: Omit<ToastItem, 'id'>): string {
  const id = crypto.randomUUID()
  // Default to 4000ms when a caller bypasses the type and omits duration.
  const duration = toast.duration ?? 4000
  const item: ToastItem = { ...toast, id, duration }
  toasts = [...toasts, item]
  emit()
  if (duration > 0) {
    const timer = setTimeout(() => {
      dismiss(id)
    }, duration)
    timers.set(id, timer)
  }
  return id
}

function clear(): void {
  for (const timer of timers.values()) {
    clearTimeout(timer)
  }
  timers.clear()
  if (toasts.length === 0) return
  toasts = []
  emit()
}

const api: UseToastApi = { push, dismiss, clear }

export function useToast(): UseToastApi {
  useSyncExternalStore(subscribe, getSnapshot)
  return api
}

const VARIANT_STYLES: Record<ToastVariant, { panel: string; dot: string }> = {
  info: {
    panel: 'border-[var(--c-blue)]/40 bg-[var(--c-blue)]/10',
    dot: 'bg-[var(--c-blue)]',
  },
  success: {
    panel: 'border-[var(--c-mint)]/40 bg-[var(--c-mint)]/10',
    dot: 'bg-[var(--c-mint)]',
  },
  warning: {
    panel: 'border-[var(--c-yellow)]/40 bg-[var(--c-yellow)]/10',
    dot: 'bg-[var(--c-yellow)]',
  },
  error: {
    panel: 'border-red-400/40 bg-red-500/10',
    dot: 'bg-red-400',
  },
}

function ToastPanel({
  toast,
  onClose,
}: {
  toast: ToastItem
  onClose: () => void
}) {
  const styles = VARIANT_STYLES[toast.variant]
  return (
    <div
      className={`flex items-start gap-3 rounded-lg border px-4 py-3 shadow-[var(--shadow-soft)] ${styles.panel}`}
    >
      <span
        aria-hidden="true"
        className={`mt-1 h-2 w-2 shrink-0 rounded-full ${styles.dot}`}
      />
      <div className="min-w-0 flex-1">
        {toast.title != null && (
          <div className="text-sm font-semibold text-[var(--fg)]">{toast.title}</div>
        )}
        <div className="text-sm text-[var(--muted)]">{toast.message}</div>
      </div>
      <button
        type="button"
        aria-label="关闭"
        onClick={onClose}
        className="shrink-0 text-[var(--muted)] transition hover:text-[var(--fg)]"
      >
        ×
      </button>
    </div>
  )
}

export function ToastContainer() {
  const currentToasts = useSyncExternalStore(subscribe, getSnapshot)
  if (currentToasts.length === 0) return null
  return createPortal(
    <div className="fixed right-4 top-4 z-[100] flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-2">
      {currentToasts.map((toast) => (
        <ToastPanel key={toast.id} toast={toast} onClose={() => dismiss(toast.id)} />
      ))}
    </div>,
    document.body,
  )
}
