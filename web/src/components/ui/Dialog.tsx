import { useEffect } from 'react'
import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'

interface DialogProps {
  open: boolean
  onClose: () => void
  title?: ReactNode
  description?: ReactNode
  children?: ReactNode
  /** Footer area, typically action buttons. */
  footer?: ReactNode
  /** Disable closing by clicking the backdrop. Default false. */
  disableBackdropClose?: boolean
  /** Optional max-width class. Default `max-w-md`. */
  maxWidthClassName?: string
}

export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  disableBackdropClose = false,
  maxWidthClassName = 'max-w-md',
}: DialogProps) {
  // Close on Escape + lock body scroll while the dialog is open.
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose()
      }
    }
    window.addEventListener('keydown', onKey)
    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = prevOverflow
    }
  }, [open, onClose])

  if (!open) return null

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
      onClick={disableBackdropClose ? undefined : onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        onClick={(e) => e.stopPropagation()}
        className={`relative w-full ${maxWidthClassName} rounded-2xl border border-[var(--border)] bg-[var(--card)] p-6 shadow-[var(--shadow-soft)]`}
      >
        <button
          type="button"
          aria-label="关闭"
          onClick={onClose}
          className="absolute right-4 top-4 flex h-7 w-7 items-center justify-center rounded-full text-[var(--muted)] transition hover:bg-[var(--card-hover)] hover:text-[var(--fg)]"
        >
          ×
        </button>
        {title != null && (
          <h2 className="pr-8 text-base font-semibold text-[var(--fg)]">{title}</h2>
        )}
        {description != null && (
          <p className="mt-1 text-sm text-[var(--muted)]">{description}</p>
        )}
        {children != null && <div className="mt-4">{children}</div>}
        {footer != null && (
          <div className="mt-6 flex justify-end gap-2">{footer}</div>
        )}
      </div>
    </div>,
    document.body,
  )
}
