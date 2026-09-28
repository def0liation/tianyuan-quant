import { clsx } from 'clsx'
interface BadgeProps {
  status: string
  children: React.ReactNode
  className?: string
}

const statusColors: Record<string, string> = {
  PASS: 'bg-[var(--md-sys-color-success-container)] text-[var(--md-sys-color-on-success-container)] border-[var(--md-sys-color-success-container)]',
  WARN: 'bg-[var(--md-sys-color-warning-container)] text-[var(--md-sys-color-on-warning-container)] border-[var(--md-sys-color-warning-container)]',
  REVIEW_ONLY: 'bg-[var(--md-sys-color-primary-container)] text-[var(--md-sys-color-on-primary-container)] border-[var(--md-sys-color-primary-container)]',
  BLOCK_BUY: 'bg-[var(--md-sys-color-error-container)] text-[var(--md-sys-color-on-error-container)] border-[var(--md-sys-color-error-container)]',
  BLOCK: 'bg-[var(--md-sys-color-error-container)] text-[var(--md-sys-color-on-error-container)] border-[var(--md-sys-color-error-container)]',
  FAIL: 'bg-[var(--md-sys-color-error-container)] text-[var(--md-sys-color-on-error-container)] border-[var(--md-sys-color-error-container)]',
  ERROR: 'bg-[var(--md-sys-color-error-container)] text-[var(--md-sys-color-on-error-container)] border-[var(--md-sys-color-error-container)]',
  STALE: 'bg-[var(--md-sys-color-error-container)] text-[var(--md-sys-color-on-error-container)] border-[var(--md-sys-color-error-container)]',
  CANCELLED: 'bg-[var(--md-sys-color-secondary-container)] text-[var(--md-sys-color-on-secondary-container)] border-[var(--md-sys-color-secondary-container)]',
  CANCEL_REQUESTED: 'bg-[var(--md-sys-color-warning-container)] text-[var(--md-sys-color-on-warning-container)] border-[var(--md-sys-color-warning-container)]',
  QUEUED: 'bg-[var(--md-sys-color-primary-container)] text-[var(--md-sys-color-on-primary-container)] border-[var(--md-sys-color-primary-container)]',
  SKIPPED: 'bg-[var(--md-sys-color-secondary-container)] text-[var(--md-sys-color-on-secondary-container)] border-[var(--md-sys-color-secondary-container)]',
  RUNNING: 'bg-[var(--md-sys-color-primary-container)] text-[var(--md-sys-color-on-primary-container)] border-[var(--md-sys-color-primary-container)]',
  WAIT: 'bg-[var(--md-sys-color-surface-container)] text-[var(--md-sys-color-on-surface-variant)] border-[var(--md-sys-color-outline-variant)]',
  REJECT: 'bg-[var(--md-sys-color-error-container)] text-[var(--md-sys-color-on-error-container)] border-[var(--md-sys-color-error-container)]',
  HOLD: 'bg-[var(--md-sys-color-secondary-container)] text-[var(--md-sys-color-on-secondary-container)] border-[var(--md-sys-color-secondary-container)]',
  REDUCE: 'bg-[var(--md-sys-color-warning-container)] text-[var(--md-sys-color-on-warning-container)] border-[var(--md-sys-color-warning-container)]',
  LIGHT_WATCH: 'bg-[var(--md-sys-color-primary-container)] text-[var(--md-sys-color-on-primary-container)] border-[var(--md-sys-color-primary-container)]',
  BUY_CANDIDATE: 'bg-[var(--md-sys-color-success-container)] text-[var(--md-sys-color-on-success-container)] border-[var(--md-sys-color-success-container)]',
  ADD_CANDIDATE: 'bg-[var(--md-sys-color-success-container)] text-[var(--md-sys-color-on-success-container)] border-[var(--md-sys-color-success-container)]',
  DEFENSIVE: 'bg-[var(--md-sys-color-tertiary-container)] text-[var(--md-sys-color-on-tertiary-container)] border-[var(--md-sys-color-tertiary-container)]',
  SIGNAL_ONLY: 'bg-[var(--md-sys-color-primary-container)] text-[var(--md-sys-color-on-primary-container)] border-[var(--md-sys-color-primary-container)]',
  PAPER_TEST_ONLY: 'bg-[var(--md-sys-color-warning-container)] text-[var(--md-sys-color-on-warning-container)] border-[var(--md-sys-color-warning-container)]',
  NONE: 'bg-[var(--md-sys-color-success-container)] text-[var(--md-sys-color-on-success-container)] border-[var(--md-sys-color-success-container)]',
  SOFT: 'bg-[var(--md-sys-color-warning-container)] text-[var(--md-sys-color-on-warning-container)] border-[var(--md-sys-color-warning-container)]',
  HARD: 'bg-[var(--md-sys-color-error-container)] text-[var(--md-sys-color-on-error-container)] border-[var(--md-sys-color-error-container)]',
  COMPLIANCE: 'bg-[var(--md-sys-color-surface-container)] text-[var(--md-sys-color-on-surface)] border-[var(--md-sys-color-outline-variant)]',
  IDEA: 'bg-[var(--md-sys-color-secondary-container)] text-[var(--md-sys-color-on-secondary-container)] border-[var(--md-sys-color-secondary-container)]',
  WATCH: 'bg-[var(--md-sys-color-primary-container)] text-[var(--md-sys-color-on-primary-container)] border-[var(--md-sys-color-primary-container)]',
  PAPER_TEST: 'bg-[var(--md-sys-color-warning-container)] text-[var(--md-sys-color-on-warning-container)] border-[var(--md-sys-color-warning-container)]',
  QUALIFIED: 'bg-[var(--md-sys-color-success-container)] text-[var(--md-sys-color-on-success-container)] border-[var(--md-sys-color-success-container)]',
  TRADE_PLAN: 'bg-[var(--md-sys-color-tertiary-container)] text-[var(--md-sys-color-on-tertiary-container)] border-[var(--md-sys-color-tertiary-container)]',
  MANUAL_CONFIRMED: 'bg-[var(--md-sys-color-primary-container)] text-[var(--md-sys-color-on-primary-container)] border-[var(--md-sys-color-primary-container)]',
  EXECUTION_REVIEW: 'bg-[var(--md-sys-color-warning-container)] text-[var(--md-sys-color-on-warning-container)] border-[var(--md-sys-color-warning-container)]',
  CLOSED: 'bg-[var(--md-sys-color-secondary-container)] text-[var(--md-sys-color-on-secondary-container)] border-[var(--md-sys-color-secondary-container)]',
  PATCH_REQUIRED: 'bg-[var(--md-sys-color-error-container)] text-[var(--md-sys-color-on-error-container)] border-[var(--md-sys-color-error-container)]',
  HIGH: 'bg-[var(--md-sys-color-error-container)] text-[var(--md-sys-color-on-error-container)] border-[var(--md-sys-color-error-container)]',
  MEDIUM: 'bg-[var(--md-sys-color-warning-container)] text-[var(--md-sys-color-on-warning-container)] border-[var(--md-sys-color-warning-container)]',
  LOW: 'bg-[var(--md-sys-color-success-container)] text-[var(--md-sys-color-on-success-container)] border-[var(--md-sys-color-success-container)]',
  ENABLED: 'bg-[var(--md-sys-color-success-container)] text-[var(--md-sys-color-on-success-container)] border-[var(--md-sys-color-success-container)]',
  DISABLED: 'bg-[var(--md-sys-color-secondary-container)] text-[var(--md-sys-color-on-secondary-container)] border-[var(--md-sys-color-secondary-container)]',
  READ_ONLY: 'bg-[var(--md-sys-color-primary-container)] text-[var(--md-sys-color-on-primary-container)] border-[var(--md-sys-color-primary-container)]',
  ALLOW: 'bg-[var(--md-sys-color-success-container)] text-[var(--md-sys-color-on-success-container)] border-[var(--md-sys-color-success-container)]',
  BLOCKED: 'bg-[var(--md-sys-color-error-container)] text-[var(--md-sys-color-on-error-container)] border-[var(--md-sys-color-error-container)]',
  FAST_MODE: 'bg-[var(--md-sys-color-primary-container)] text-[var(--md-sys-color-on-primary-container)] border-[var(--md-sys-color-primary-container)]',
  STANDARD_MODE: 'bg-[var(--md-sys-color-success-container)] text-[var(--md-sys-color-on-success-container)] border-[var(--md-sys-color-success-container)]',
  DEEP_MODE: 'bg-[var(--md-sys-color-tertiary-container)] text-[var(--md-sys-color-on-tertiary-container)] border-[var(--md-sys-color-tertiary-container)]',
}

export function Badge({ status, children, className }: BadgeProps) {
  return (
    <span className={clsx('inline-flex items-center rounded-full border px-3 py-1 text-xs font-semibold', statusColors[status] ?? 'bg-[var(--md-sys-color-secondary-container)] text-[var(--md-sys-color-on-secondary-container)] border-[var(--md-sys-color-secondary-container)]', className)}>
      {children}
    </span>
  )
}
