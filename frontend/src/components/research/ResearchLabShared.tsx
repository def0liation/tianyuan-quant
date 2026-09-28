import { type ElementType, type ReactNode } from 'react'
import { AlertCircle, Inbox, Loader2 } from 'lucide-react'
import { EmptyState, MetricTile, PageHeader } from '../common/Material'

interface ResearchPageHeaderProps {
  eyebrow: string
  title: string
  subtitle: string
  icon: ElementType
  tags?: string[]
  actions?: ReactNode
}

export function ResearchPageHeader({
  eyebrow,
  title,
  subtitle,
  icon: Icon,
  tags = [],
  actions,
}: ResearchPageHeaderProps) {
  return (
    <PageHeader
      eyebrow={(
        <span className="flex max-w-full min-w-0 flex-wrap items-center gap-2">
          <Icon size={14} className="shrink-0" />
          <span className="min-w-0 break-words">{eyebrow}</span>
          {tags.map((tag) => <span key={tag} className="material-status-pill">{tag}</span>)}
        </span>
      )}
      title={title}
      description={subtitle}
      icon={Icon}
      actions={actions}
    />
  )
}

interface ResearchMetricCardProps {
  label: string
  value: ReactNode
  helper: string
  icon: ElementType
  tone?: string
}

export function ResearchMetricCard({
  label,
  value,
  helper,
  icon: Icon,
  tone = 'bg-slate-100 text-slate-700',
}: ResearchMetricCardProps) {
  return (
    <MetricTile label={label} value={value} helper={helper} icon={Icon} className={tone.includes('cyan') ? 'border-[#d2e3fc]' : ''} />
  )
}

export function ResearchLoading({ label }: { label: string }) {
  return (
    <div className="flex min-h-48 items-center justify-center rounded-lg border border-slate-200 bg-slate-50 text-sm text-slate-500">
      <Loader2 size={16} className="mr-2 animate-spin text-cyan-700" />
      {label}
    </div>
  )
}

export function ResearchError({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
      <AlertCircle size={16} className="mt-0.5 shrink-0" />
      <span>{message}</span>
    </div>
  )
}

interface ResearchEmptyStateProps {
  title: string
  description: string
  icon?: ElementType
  action?: ReactNode
}

export function ResearchEmptyState({
  title,
  description,
  icon: Icon = Inbox,
  action,
}: ResearchEmptyStateProps) {
  return (
    <EmptyState
      title={<span className="inline-flex items-center justify-center gap-2"><Icon size={18} />{title}</span>}
      description={description}
      action={action}
    />
  )
}

interface ResearchSegmentedTabsProps {
  tabs: Array<{ value: string; label: string; icon?: ElementType; count?: number }>
  active: string
  onChange: (value: string) => void
}

export function ResearchSegmentedTabs({ tabs, active, onChange }: ResearchSegmentedTabsProps) {
  return (
    <div className="flex flex-wrap gap-2 rounded-lg border border-slate-200 bg-slate-50 p-1">
      {tabs.map((tab) => {
        const Icon = tab.icon
        const isActive = active === tab.value
        return (
          <button
            key={tab.value}
            type="button"
            onClick={() => onChange(tab.value)}
            className={`inline-flex h-10 items-center gap-2 rounded-md px-3 text-sm font-medium transition ${
              isActive
                ? 'bg-white text-slate-950 shadow-sm ring-1 ring-cyan-200'
                : 'text-slate-600 hover:bg-white hover:text-slate-950'
            }`}
          >
            {Icon ? <Icon size={15} /> : null}
            {tab.label}
            {typeof tab.count === 'number' ? (
              <span className={`rounded px-1.5 py-0.5 text-[11px] ${isActive ? 'bg-cyan-50 text-cyan-700' : 'bg-white text-slate-500'}`}>
                {tab.count}
              </span>
            ) : null}
          </button>
        )
      })}
    </div>
  )
}
