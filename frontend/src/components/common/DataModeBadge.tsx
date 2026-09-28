import { Database, Wifi, WifiOff } from 'lucide-react'

type DataMode = 'MOCK' | 'LIVE' | 'MIXED' | 'FALLBACK' | 'UNAVAILABLE' | (string & {})

export function DataModeBadge({ mode }: { mode?: DataMode }) {
  const label = mode === 'LIVE'
    ? '真实数据'
    : mode === 'MIXED'
      ? '混合数据'
      : mode === 'FALLBACK'
        ? '降级数据'
        : mode === 'UNAVAILABLE'
          ? '数据不可用'
          : '模拟数据'
  const bg = mode === 'LIVE'
    ? 'bg-[var(--md-sys-color-success-container)] border-[var(--md-sys-color-success-container)] text-[var(--md-sys-color-on-success-container)]'
    : mode === 'MIXED'
      ? 'bg-[var(--institution-data-accent-soft)] border-[var(--institution-data-accent-soft)] text-[var(--md-sys-color-on-tertiary-container)]'
      : mode === 'FALLBACK'
        ? 'bg-[var(--md-sys-color-warning-container)] border-[var(--md-sys-color-warning-container)] text-[var(--md-sys-color-on-warning-container)]'
        : mode === 'UNAVAILABLE'
          ? 'bg-[var(--md-sys-color-error-container)] border-[var(--md-sys-color-error-container)] text-[var(--md-sys-color-on-error-container)]'
          : 'bg-[var(--md-sys-color-secondary-container)] border-[var(--md-sys-color-secondary-container)] text-[var(--md-sys-color-on-secondary-container)]'

  const Icon = mode === 'LIVE' ? Wifi : mode === 'MIXED' || mode === 'FALLBACK' ? Database : WifiOff

  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold ${bg}`}>
      <Icon size={13} />
      {label}
    </span>
  )
}

export function EvidenceBadge({ level }: { level: 'C' | 'I' | 'U' | (string & {}) }) {
  const label = level === 'C' ? '确认' : level === 'I' ? '推断' : '未知'
  const bg = level === 'C'
    ? 'bg-[var(--md-sys-color-success-container)] text-[var(--md-sys-color-on-success-container)] border-[var(--md-sys-color-success-container)]'
    : level === 'I'
      ? 'bg-[var(--md-sys-color-warning-container)] text-[var(--md-sys-color-on-warning-container)] border-[var(--md-sys-color-warning-container)]'
      : 'bg-[var(--md-sys-color-error-container)] text-[var(--md-sys-color-on-error-container)] border-[var(--md-sys-color-error-container)]'

  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-[10px] font-semibold ${bg}`}>
      <span className="font-mono">{level}</span>
      <span>{label}</span>
    </span>
  )
}
