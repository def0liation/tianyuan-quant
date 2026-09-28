import { clsx } from 'clsx'
import { CSSProperties, ElementType, ReactNode } from 'react'

type Tone = 'primary' | 'neutral' | 'success' | 'warning' | 'danger' | 'info' | 'data'

const toneClasses: Record<Tone, string> = {
  primary: 'bg-[var(--md-sys-color-primary-container)] text-[var(--md-sys-color-on-primary-container)]',
  neutral: 'bg-[var(--md-sys-color-surface-container-high)] text-[var(--md-sys-color-on-surface)]',
  success: 'bg-[var(--md-sys-color-success-container)] text-[var(--md-sys-color-on-success-container)]',
  warning: 'bg-[var(--md-sys-color-warning-container)] text-[var(--md-sys-color-on-warning-container)]',
  danger: 'bg-[var(--md-sys-color-error-container)] text-[var(--md-sys-color-on-error-container)]',
  info: 'bg-[var(--md-sys-color-tertiary-container)] text-[var(--md-sys-color-on-tertiary-container)]',
  data: 'bg-[var(--institution-data-accent-soft)] text-[var(--md-sys-color-on-tertiary-container)]',
}

interface PageHeaderProps {
  eyebrow?: ReactNode
  title: ReactNode
  description?: ReactNode
  icon?: ElementType
  actions?: ReactNode
}

export function PageHeader({ eyebrow, title, description, icon: Icon, actions }: PageHeaderProps) {
  return (
    <section className="material-page-header">
      <div className="flex min-w-0 items-start gap-3">
        {Icon ? (
          <div className="material-icon-container material-icon-container-primary">
            <Icon size={21} />
          </div>
        ) : null}
        <div className="min-w-0">
          {eyebrow ? <div className="material-eyebrow">{eyebrow}</div> : null}
          <h1 className="material-page-title">{title}</h1>
          {description ? <p className="material-page-description">{description}</p> : null}
        </div>
      </div>
      {actions ? <div className="material-header-actions">{actions}</div> : null}
    </section>
  )
}

interface SurfaceProps {
  children: ReactNode
  className?: string
  title?: ReactNode
  description?: ReactNode
  action?: ReactNode
  elevated?: boolean
}

export function Surface({ children, className, title, description, action, elevated = false }: SurfaceProps) {
  return (
    <section className={clsx(elevated ? 'material-surface-elevated' : 'material-surface', className)}>
      {(title || description || action) ? (
        <div className="material-surface-header">
          <div className="min-w-0">
            {title ? <h2 className="material-surface-title">{title}</h2> : null}
            {description ? <p className="material-surface-description">{description}</p> : null}
          </div>
          {action ? <div className="shrink-0">{action}</div> : null}
        </div>
      ) : null}
      {children}
    </section>
  )
}

interface MetricTileProps {
  label: ReactNode
  value: ReactNode
  helper?: ReactNode
  icon?: ElementType
  tone?: Tone
  className?: string
}

export function MetricTile({ label, value, helper, icon: Icon, tone = 'neutral', className }: MetricTileProps) {
  return (
    <div className={clsx('material-metric-tile', className)}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="material-metric-label">{label}</div>
          <div className="material-metric-value">{value}</div>
        </div>
        {Icon ? (
          <div className={clsx('material-icon-container', toneClasses[tone])}>
            <Icon size={18} />
          </div>
        ) : null}
      </div>
      {helper ? <div className="material-metric-helper">{helper}</div> : null}
    </div>
  )
}

interface ActionButtonProps {
  children: ReactNode
  icon?: ElementType
  trailingIcon?: ElementType
  variant?: 'filled' | 'tonal' | 'outlined' | 'text'
  className?: string
  type?: 'button' | 'submit' | 'reset'
  disabled?: boolean
  onClick?: () => void
}

export function ActionButton({
  children,
  icon: Icon,
  trailingIcon: TrailingIcon,
  variant = 'filled',
  className,
  type = 'button',
  disabled,
  onClick,
}: ActionButtonProps) {
  return (
    <button
      type={type}
      disabled={disabled}
      onClick={onClick}
      className={clsx('material-button', `material-button-${variant}`, className)}
    >
      {Icon ? <Icon size={16} /> : null}
      <span>{children}</span>
      {TrailingIcon ? <TrailingIcon size={16} /> : null}
    </button>
  )
}

interface IconButtonProps {
  label: string
  icon: ElementType
  variant?: 'standard' | 'tonal' | 'outlined' | 'filled'
  className?: string
  disabled?: boolean
  onClick?: () => void
}

export function IconButton({ label, icon: Icon, variant = 'standard', className, disabled, onClick }: IconButtonProps) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className={clsx('material-icon-button', `material-icon-button-${variant}`, className)}
    >
      <Icon size={18} />
    </button>
  )
}

interface StatusPillProps {
  children: ReactNode
  tone?: Tone
  className?: string
}

export function StatusPill({ children, tone = 'neutral', className }: StatusPillProps) {
  return (
    <span className={clsx('material-status-pill', toneClasses[tone], className)}>
      {children}
    </span>
  )
}

export function TableShell({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={clsx('material-table-shell', className)}>{children}</div>
}

export function EmptyState({ title, description, action }: { title: ReactNode; description?: ReactNode; action?: ReactNode }) {
  return (
    <div className="material-empty-state">
      <div className="text-base font-semibold text-[var(--md-sys-color-on-surface)]">{title}</div>
      {description ? <p className="mt-2 text-sm leading-6 text-[var(--md-sys-color-on-surface-variant)]">{description}</p> : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  )
}

interface InlineSparklineProps {
  values: number[]
  tone?: 'primary' | 'data' | 'warning' | 'danger' | 'success'
  height?: number
  className?: string
}

const sparklineStroke: Record<NonNullable<InlineSparklineProps['tone']>, string> = {
  primary: 'var(--md-sys-color-primary)',
  data: 'var(--institution-data-accent)',
  warning: 'var(--md-sys-color-warning)',
  danger: 'var(--md-sys-color-error)',
  success: 'var(--md-sys-color-success)',
}

export function InlineSparkline({ values, tone = 'data', height = 28, className }: InlineSparklineProps) {
  const cleanValues = values.filter((value) => Number.isFinite(value))
  const width = Math.max(80, cleanValues.length * 18)
  const min = cleanValues.length ? Math.min(...cleanValues) : 0
  const max = cleanValues.length ? Math.max(...cleanValues) : 1
  const span = max - min || 1
  const points = cleanValues
    .map((value, index) => {
      const x = cleanValues.length <= 1 ? width / 2 : (index / (cleanValues.length - 1)) * width
      const y = height - ((value - min) / span) * (height - 6) - 3
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className={clsx('block h-7 w-full min-w-[72px]', className)}
      role="img"
      aria-label="趋势线"
    >
      <polyline
        fill="none"
        stroke={sparklineStroke[tone]}
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="2"
        points={points}
      />
    </svg>
  )
}

interface FactorBarRow {
  label: ReactNode
  value: number
  helper?: ReactNode
  tone?: 'positive' | 'negative' | 'neutral' | 'data'
}

const factorTone: Record<NonNullable<FactorBarRow['tone']>, string> = {
  positive: 'var(--md-sys-color-success)',
  negative: 'var(--md-sys-color-error)',
  neutral: 'var(--md-sys-color-primary)',
  data: 'var(--institution-data-accent)',
}

export function FactorBarStack({ rows, maxAbs = 1, className }: { rows: FactorBarRow[]; maxAbs?: number; className?: string }) {
  const denominator = Math.max(Math.abs(maxAbs), ...rows.map((row) => Math.abs(row.value)), 1)

  return (
    <div className={clsx('space-y-3', className)}>
      {rows.map((row, index) => {
        const width = Math.min(100, (Math.abs(row.value) / denominator) * 100)
        const tone = row.tone ?? (row.value > 0 ? 'positive' : row.value < 0 ? 'negative' : 'neutral')
        const style = {
          '--factor-color': factorTone[tone],
          '--factor-width': `${width}%`,
        } as CSSProperties

        return (
          <div key={index} className="min-w-0">
            <div className="mb-1 flex items-center justify-between gap-3 text-xs">
              <span className="truncate font-semibold text-[var(--md-sys-color-on-surface)]">{row.label}</span>
              <span className="font-mono text-[var(--md-sys-color-on-surface-variant)]">{row.value.toFixed(2)}</span>
            </div>
            <div className="institution-progress-track" style={style}>
              <div className="institution-progress-fill" style={{ width: 'var(--factor-width)', background: 'var(--factor-color)' }} />
            </div>
            {row.helper ? <div className="mt-1 text-xs leading-5 text-[var(--md-sys-color-on-surface-variant)]">{row.helper}</div> : null}
          </div>
        )
      })}
    </div>
  )
}

interface MatrixHeatmapRow {
  label: ReactNode
  cells: Array<{ label: ReactNode; value: number; helper?: ReactNode }>
}

export function MatrixHeatmap({ rows, className }: { rows: MatrixHeatmapRow[]; className?: string }) {
  return (
    <div className={clsx('grid gap-2', className)}>
      {rows.map((row, rowIndex) => (
        <div key={rowIndex} className="grid gap-2 sm:grid-cols-[140px_1fr] sm:items-center">
          <div className="truncate text-xs font-semibold text-[var(--md-sys-color-on-surface-variant)]">{row.label}</div>
          <div className="grid gap-2 sm:grid-cols-3 lg:grid-cols-4">
            {row.cells.map((cell, cellIndex) => {
              const intensity = Math.max(8, Math.min(92, Math.round(cell.value * 100)))
              const style = {
                backgroundColor: `color-mix(in srgb, var(--institution-data-accent) ${intensity}%, white)`,
              }
              return (
                <div
                  key={cellIndex}
                  style={style}
                  className="rounded-[var(--institution-radius-sm)] border border-[var(--md-sys-color-outline-variant)] px-2 py-1.5"
                >
                  <div className="truncate text-[11px] font-semibold text-[var(--md-sys-color-on-surface)]">{cell.label}</div>
                  <div className="font-mono text-xs text-[var(--md-sys-color-on-surface-variant)]">{Math.round(cell.value * 100)}%</div>
                  {cell.helper ? <div className="mt-1 truncate text-[10px] text-[var(--md-sys-color-on-surface-variant)]">{cell.helper}</div> : null}
                </div>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}

interface SourceFreshnessItem {
  label: ReactNode
  freshness: ReactNode
  value?: number
  mode?: ReactNode
}

export function SourceFreshnessPanel({ sources, className }: { sources: SourceFreshnessItem[]; className?: string }) {
  return (
    <div className={clsx('space-y-2', className)}>
      {sources.map((source, index) => {
        const value = Math.max(0, Math.min(100, source.value ?? 0))
        return (
          <div key={index} className="rounded-[var(--institution-radius-sm)] border border-[var(--md-sys-color-outline-variant)] bg-[var(--md-sys-color-surface-container-low)] px-3 py-2">
            <div className="flex items-center justify-between gap-3 text-xs">
              <span className="truncate font-semibold text-[var(--md-sys-color-on-surface)]">{source.label}</span>
              <span className="shrink-0 font-mono text-[var(--md-sys-color-on-surface-variant)]">{source.freshness}</span>
            </div>
            <div className="mt-2 institution-progress-track">
              <div className="institution-progress-fill" style={{ width: `${value}%` }} />
            </div>
            {source.mode ? <div className="mt-2 text-[11px] text-[var(--md-sys-color-on-surface-variant)]">{source.mode}</div> : null}
          </div>
        )
      })}
    </div>
  )
}

interface AgentTimelineItem {
  label: ReactNode
  status: ReactNode
  detail?: ReactNode
  tone?: Tone
}

export function AgentTimeline({ items, className }: { items: AgentTimelineItem[]; className?: string }) {
  return (
    <ol className={clsx('space-y-3', className)}>
      {items.map((item, index) => (
        <li key={index} className="grid grid-cols-[28px_1fr] gap-3">
          <div className="relative flex justify-center">
            <span className={clsx('mt-0.5 grid h-7 w-7 place-items-center rounded-full text-xs font-bold', toneClasses[item.tone ?? 'neutral'])}>
              {index + 1}
            </span>
            {index < items.length - 1 ? <span className="absolute top-8 h-[calc(100%+0.25rem)] w-px bg-[var(--md-sys-color-outline-variant)]" /> : null}
          </div>
          <div className="min-w-0 rounded-[var(--institution-radius-sm)] border border-[var(--md-sys-color-outline-variant)] bg-[var(--md-sys-color-surface)] px-3 py-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="truncate text-sm font-semibold text-[var(--md-sys-color-on-surface)]">{item.label}</div>
              <span className="institution-chip">{item.status}</span>
            </div>
            {item.detail ? <div className="mt-1 text-xs leading-5 text-[var(--md-sys-color-on-surface-variant)]">{item.detail}</div> : null}
          </div>
        </li>
      ))}
    </ol>
  )
}

interface EvidenceLedgerRow {
  label: ReactNode
  source: ReactNode
  status: ReactNode
  detail?: ReactNode
  strength?: number
}

export function EvidenceLedger({ rows, className }: { rows: EvidenceLedgerRow[]; className?: string }) {
  return (
    <TableShell className={className}>
      <table className="institution-table">
        <thead>
          <tr>
            <th>Evidence</th>
            <th>Source</th>
            <th>Status</th>
            <th>Strength</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => {
            const strength = Math.max(0, Math.min(100, row.strength ?? 0))
            return (
              <tr key={index}>
                <td>
                  <div className="font-semibold">{row.label}</div>
                  {row.detail ? <div className="mt-1 text-xs leading-5 text-[var(--md-sys-color-on-surface-variant)]">{row.detail}</div> : null}
                </td>
                <td>{row.source}</td>
                <td>{row.status}</td>
                <td>
                  <div className="flex min-w-[120px] items-center gap-2">
                    <div className="institution-progress-track flex-1">
                      <div className="institution-progress-fill" style={{ width: `${strength}%` }} />
                    </div>
                    <span className="font-mono text-xs text-[var(--md-sys-color-on-surface-variant)]">{strength}%</span>
                  </div>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </TableShell>
  )
}
