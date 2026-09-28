import { buildConclusionInsights } from '../../utils/conclusionInsights'
import { Badge } from '../common/Badge'
import { Card } from '../common/Card'

type ConclusionModule = ReturnType<typeof buildConclusionInsights>[number]

interface ConclusionModulesProps {
  modules: ConclusionModule[]
  previewItems?: number
  columns?: string
}

export function ConclusionModules({
  modules,
  previewItems,
  columns = 'xl:grid-cols-2',
}: ConclusionModulesProps) {
  return (
    <div className={`grid gap-6 ${columns}`}>
      {modules.map((section) => {
        const items = previewItems ? section.items.slice(0, previewItems) : section.items
        return (
          <Card key={section.title} title={section.title}>
            <div className="space-y-4">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <p className="text-sm leading-6 text-slate-600">{section.content}</p>
                <Badge
                  status={section.riskLevel === 'LOW' ? 'PASS' : section.riskLevel === 'MEDIUM' ? 'WARN' : 'FAIL'}
                  className="shrink-0"
                >
                  {section.riskLevel}
                </Badge>
              </div>
              <ul className="space-y-2 text-sm text-slate-600">
                {items.map((item) => (
                  <li key={item} className="rounded-lg bg-slate-50 px-3 py-2 leading-6">
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          </Card>
        )
      })}
    </div>
  )
}
