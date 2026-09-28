import { DataModeBadge } from './DataModeBadge'

interface SectionTitleProps {
  title: string
  subtitle?: string
  dataMode?: string
  eyebrow?: string
}

export function SectionTitle({ title, subtitle, dataMode, eyebrow = 'Module' }: SectionTitleProps) {
  return (
    <div className="material-page-header">
      <div className="min-w-0">
        <div className="material-eyebrow">{eyebrow}</div>
        <h2 className="material-page-title">{title}</h2>
        {subtitle ? <p className="material-page-description">{subtitle}</p> : null}
      </div>
      {dataMode ? <div className="material-header-actions"><DataModeBadge mode={dataMode} /></div> : null}
    </div>
  )
}
