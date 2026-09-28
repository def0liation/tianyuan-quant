type SourceKind = 'LIVE' | 'DERIVED' | 'MOCK' | 'MISSING' | 'USER_INPUT' | 'LEGACY_TEMPLATE' | (string & {})

const SOURCE_STYLE: Record<string, string> = {
  LIVE: 'border-[var(--md-sys-color-success-container)] bg-[var(--md-sys-color-success-container)] text-[var(--md-sys-color-on-success-container)]',
  DERIVED: 'border-[var(--md-sys-color-primary-container)] bg-[var(--md-sys-color-primary-container)] text-[var(--md-sys-color-on-primary-container)]',
  USER_INPUT: 'border-[var(--md-sys-color-primary-container)] bg-[var(--md-sys-color-primary-container)] text-[var(--md-sys-color-on-primary-container)]',
  MOCK: 'border-[var(--md-sys-color-warning-container)] bg-[var(--md-sys-color-warning-container)] text-[var(--md-sys-color-on-warning-container)]',
  LEGACY_TEMPLATE: 'border-[var(--md-sys-color-warning-container)] bg-[var(--md-sys-color-warning-container)] text-[var(--md-sys-color-on-warning-container)]',
  MISSING: 'border-[var(--md-sys-color-error-container)] bg-[var(--md-sys-color-error-container)] text-[var(--md-sys-color-on-error-container)]',
}

const SOURCE_LABEL: Record<string, string> = {
  LIVE: '真实接入',
  DERIVED: '规则推算',
  USER_INPUT: '用户输入',
  MOCK: '模板默认',
  LEGACY_TEMPLATE: '历史模板',
  MISSING: '未接入',
}

export function SourceBadge({ kind }: { kind?: SourceKind }) {
  const normalized = String(kind || 'MISSING').toUpperCase()
  const className = SOURCE_STYLE[normalized] ?? SOURCE_STYLE.MISSING
  const label = SOURCE_LABEL[normalized] ?? SOURCE_LABEL.MISSING

  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold ${className}`}>
      {label}
    </span>
  )
}

export function SourceNote({ kind, note }: { kind?: SourceKind; note: string }) {
  return (
    <div className="mt-3 flex flex-wrap items-center gap-2 rounded-[var(--institution-radius-md)] border border-[var(--md-sys-color-outline-variant)] bg-[var(--md-sys-color-surface-container-low)] px-3 py-2 text-xs text-[var(--md-sys-color-on-surface-variant)]">
      <SourceBadge kind={kind} />
      <span>{note}</span>
    </div>
  )
}
