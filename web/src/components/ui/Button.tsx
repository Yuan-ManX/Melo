import type { ButtonHTMLAttributes, CSSProperties, ReactNode } from 'react'

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger'
type ButtonSize = 'sm' | 'md' | 'lg'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
  loading?: boolean
  /** Optional leading icon node — rendered before children. */
  leadingIcon?: ReactNode
}

const BASE_CLASS =
  'inline-flex items-center justify-center gap-2 font-medium transition disabled:cursor-not-allowed disabled:opacity-50'

const VARIANT_BASE: Record<ButtonVariant, string> = {
  primary: 'text-white shadow-[var(--shadow-soft)]',
  secondary:
    'bg-[var(--card)] border border-[var(--border)] text-[var(--fg)] hover:bg-[var(--card-hover)]',
  ghost:
    'bg-transparent text-[var(--muted)] hover:bg-[var(--card-hover)]/40 hover:text-[var(--fg)]',
  danger:
    'bg-red-500/15 border border-red-400/40 text-red-400 hover:bg-red-500/25',
}

const SIZE_CLASS: Record<ButtonSize, string> = {
  sm: 'text-xs px-3 py-1.5 rounded-md',
  md: 'text-sm px-4 py-2 rounded-lg',
  lg: 'text-base px-6 py-3 rounded-xl',
}

export function Button({
  variant = 'primary',
  size = 'md',
  loading = false,
  leadingIcon,
  className = '',
  children,
  disabled,
  style,
  ...rest
}: ButtonProps) {
  const isDisabled = disabled || loading
  const primaryStyle: CSSProperties | undefined =
    variant === 'primary'
      ? { backgroundImage: 'linear-gradient(135deg, var(--accent), var(--accent-2))' }
      : undefined
  // Hover/active scale only applies to the primary variant, and is suppressed
  // when the button is disabled or in a loading state.
  const interact =
    variant === 'primary' && !isDisabled ? 'hover:scale-105 active:scale-95' : ''

  const classes = [
    BASE_CLASS,
    SIZE_CLASS[size],
    VARIANT_BASE[variant],
    interact,
    className,
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <button
      type="button"
      disabled={isDisabled}
      className={classes}
      style={{ ...primaryStyle, ...style }}
      {...rest}
    >
      {loading && (
        <span
          aria-hidden="true"
          className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-transparent border-t-current"
        />
      )}
      {leadingIcon}
      {children}
    </button>
  )
}
