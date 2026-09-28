import { useAnalysisStore } from '../../store/useAnalysisStore'
import { SectionTitle } from '../common/SectionTitle'
import { Badge } from '../common/Badge'
import { Card } from '../common/Card'
import { EvidenceBadge } from '../common/DataModeBadge'
import { MetricTile, TableShell } from '../common/Material'
import { SourceBadge, SourceNote } from '../common/SourceBadge'
import { sourceKindFromProvenance } from '../../utils/dataProvenance'

function railDot(status: string) {
  if (status === 'PASS' || status === 'ALLOW' || status === 'FULL' || status === 'HIGH' || status === 'LOW') return 'bg-emerald-500'
  if (status === 'WARN' || status === 'REVIEW_ONLY' || status === 'ALLOW_WITH_DISCOUNT' || status === 'MEDIUM' || status === 'MODERATE') return 'bg-amber-500'
  return 'bg-rose-500'
}

export function DvgGatePage() {
  const { currentRun } = useAnalysisStore()

  if (!currentRun) return <div className="text-sm text-slate-500">加载中...</div>

  const { dvg } = currentRun
  const dvgSourceKind = sourceKindFromProvenance(dvg.provenance, currentRun.dataSources ? 'DERIVED' : 'LEGACY_TEMPLATE')
  const dvgModuleEntries = Object.values(dvg.dvgModules ?? {}).map((module) => ({
    ...module,
    ignoredMissingData: Array.isArray(module.ignoredMissingData) ? module.ignoredMissingData : [],
  }))
  const activeModule = dvgModuleEntries.find((module) => module.moduleId === dvg.activeModule)
  const ignoredMissingData = dvg.ignoredMissingData ?? []
  const metricRows = [
    { label: '可靠性', value: dvg.dataReliability, status: dvg.dataReliability === 'HIGH' ? 'PASS' : dvg.dataReliability === 'MEDIUM' ? 'WARN' : 'FAIL' },
    { label: '幻觉风险', value: dvg.hallucinationRiskLevel, status: dvg.hallucinationRiskLevel === 'LOW' ? 'PASS' : dvg.hallucinationRiskLevel === 'MEDIUM' ? 'WARN' : 'FAIL' },
    { label: '幻觉评分', value: dvg.hallucinationRiskScore.toFixed(0), status: dvg.hallucinationRiskScore < 30 ? 'PASS' : dvg.hallucinationRiskScore < 60 ? 'WARN' : 'FAIL' },
    { label: '硬停止', value: dvg.hardStop ? '已触发' : '未触发', status: dvg.hardStop ? 'FAIL' : 'PASS' },
  ]
  const permissionRows = [
    {
      label: '允许输出级别',
      value: dvg.allowedOutputLevel === 'FULL' ? '完整输出' : dvg.allowedOutputLevel === 'REVIEW_ONLY' ? '仅审查' : '阻断买入',
      status: dvg.allowedOutputLevel === 'FULL' ? 'PASS' : dvg.allowedOutputLevel === 'REVIEW_ONLY' ? 'WARN' : 'FAIL',
      raw: dvg.allowedOutputLevel,
    },
    {
      label: 'QIAM 权限',
      value: dvg.qiamPermission === 'ALLOW' ? '允许' : dvg.qiamPermission === 'ALLOW_WITH_DISCOUNT' ? '允许折扣' : dvg.qiamPermission === 'BLOCKED' ? '禁止' : '仅审查',
      status: dvg.qiamPermission === 'ALLOW' ? 'PASS' : dvg.qiamPermission === 'BLOCKED' ? 'FAIL' : 'WARN',
      raw: dvg.qiamPermission,
    },
    {
      label: '场景权限',
      value: dvg.scenarioPermission === 'ALLOW' ? '允许' : '仅审查',
      status: dvg.scenarioPermission === 'ALLOW' ? 'PASS' : dvg.scenarioPermission === 'BLOCKED' ? 'FAIL' : 'WARN',
      raw: dvg.scenarioPermission,
    },
    {
      label: '执行权限',
      value: dvg.executionPermission === 'ALLOW' ? '允许' : '仅审查',
      status: dvg.executionPermission === 'ALLOW' ? 'PASS' : dvg.executionPermission === 'BLOCKED' ? 'FAIL' : 'WARN',
      raw: dvg.executionPermission,
    },
    { label: '最终决策限制', value: dvg.finalDecisionCap ?? 'NONE', status: 'WARN', raw: dvg.finalDecisionCap ?? 'NONE' },
  ]
  const freshnessRows = [
    {
      label: '新鲜度',
      value: dvg.freshnessStatus === 'FRESH' ? '新鲜' : dvg.freshnessStatus === 'MODERATE' ? '正常' : '过期',
      status: dvg.freshnessStatus === 'FRESH' ? 'PASS' : dvg.freshnessStatus === 'MODERATE' ? 'WARN' : 'FAIL',
      raw: dvg.freshnessStatus,
    },
    {
      label: '来源完整性',
      value: dvg.sourceIntegrity === 'COMPLETE' ? '完整' : dvg.sourceIntegrity === 'COMPLETE_FOR_MODE' ? '当前模式完整' : '部分',
      status: dvg.sourceIntegrity === 'COMPLETE' || dvg.sourceIntegrity === 'COMPLETE_FOR_MODE' ? 'PASS' : 'WARN',
      raw: dvg.sourceIntegrity,
    },
    { label: '未知核心项数', value: String(dvg.coreUnknownCount), status: dvg.coreUnknownCount === 0 ? 'PASS' : 'WARN', raw: String(dvg.coreUnknownCount) },
  ]

  return (
    <div className="space-y-5">
      <SectionTitle title="DVG 门禁" subtitle="数据验证门禁：证据分级 (C/I/U)、幻觉检测和下游权限限制。" dataMode={currentRun?.dataMode} />
      <div className="flex flex-wrap items-center gap-2">
        <SourceBadge kind={dvgSourceKind} />
        <span className="text-sm text-slate-500">
          DVG 现在按本次数据源可用性计算；旧历史记录若缺少来源报告会标为历史模板。
        </span>
      </div>

      <Card title="证据护栏状态轨" className="!rounded-lg !shadow-none">
        <div className="grid gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
          <div className="rounded-md border border-[#d2e3fc] bg-[#e8f0fe] p-4">
            <div className="text-xs font-semibold uppercase tracking-wide text-[#1967d2]">DVG Gate</div>
            <div className="mt-2 flex items-center gap-3">
              <span className={`h-3 w-3 rounded-full ${railDot(dvg.hardStop ? 'FAIL' : dvg.dataReliability)}`} />
              <div className="text-2xl font-semibold tracking-tight text-slate-950">{dvg.allowedOutputLevel}</div>
            </div>
            <div className="mt-3 text-xs leading-5 text-slate-600">{activeModule?.gatePolicy ?? '按本次数据源可用性计算输出权限。'}</div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {metricRows.map((item) => (
              <div key={item.label} className="rounded-md border border-slate-200 bg-white p-3">
                <div className="text-xs font-semibold text-slate-500">{item.label}</div>
                <div className="mt-2 flex items-center justify-between gap-2">
                  <span className="text-sm font-semibold text-slate-950">{item.value}</span>
                  <Badge status={item.status} className="!rounded-md px-2 py-0.5">{item.status}</Badge>
                </div>
              </div>
            ))}
          </div>
        </div>
      </Card>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {metricRows.map((item) => (
          <MetricTile
            key={item.label}
            label={item.label}
            value={item.value}
            helper={item.status}
            tone={item.status === 'PASS' ? 'success' : item.status === 'WARN' ? 'warning' : 'danger'}
            className="!rounded-lg !shadow-none"
          />
        ))}
      </div>

      {(dvg.activeModule || dvgModuleEntries.length > 0) && (
        <Card title="量化引擎适配模块" className="!rounded-lg !shadow-none">
          <div className="mb-4 flex flex-wrap items-center gap-3 text-sm">
            <Badge status={dvg.allowedOutputLevel === 'FULL' ? 'PASS' : dvg.allowedOutputLevel === 'BLOCK_BUY' ? 'FAIL' : 'WARN'} className="!rounded-md px-2 py-0.5">
              {dvg.activeModuleLabel ?? activeModule?.label ?? dvg.activeModule}
            </Badge>
            <span className="text-slate-500">{dvg.quantEngineMode ?? currentRun.quantEngine?.mode ?? 'UNKNOWN'}</span>
          </div>
          {activeModule?.gatePolicy && <div className="mb-4 text-sm text-slate-600">{activeModule.gatePolicy}</div>}
          <TableShell className="!rounded-lg !shadow-none">
            <table className="institution-table">
              <thead className="bg-slate-50">
                <tr className="text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                  <th className="px-3 py-2">模块</th>
                  <th className="px-3 py-2">状态</th>
                  <th className="px-3 py-2">有效缺失</th>
                  <th className="px-3 py-2">可靠性</th>
                  <th className="px-3 py-2">QIAM</th>
                  <th className="px-3 py-2">输出</th>
                  <th className="px-3 py-2">忽略项</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 bg-white">
                {dvgModuleEntries.map((module) => {
                  const moduleIgnoredMissingData = Array.isArray(module.ignoredMissingData) ? module.ignoredMissingData : []
                  return (
                    <tr key={module.moduleId} className={module.moduleId === dvg.activeModule ? 'bg-slate-50' : ''}>
                      <td className="px-3 py-2 font-medium text-slate-900">{module.label}</td>
                      <td className="px-3 py-2"><Badge status={module.status} className="!rounded-md px-2 py-0.5">{module.status}</Badge></td>
                      <td className="px-3 py-2 font-mono text-xs text-slate-700">{module.coreUnknownCount}</td>
                      <td className="px-3 py-2 text-slate-600">{module.dataReliability}</td>
                      <td className="px-3 py-2 text-slate-600">{module.qiamPermission}</td>
                      <td className="px-3 py-2 text-slate-600">{module.allowedOutputLevel}</td>
                      <td className="px-3 py-2 text-slate-500">{moduleIgnoredMissingData.join('、') || '无'}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </TableShell>
          {ignoredMissingData.length > 0 && (
            <div className="mt-4 flex flex-wrap gap-2">
              {ignoredMissingData.map((item, index) => (
                <span key={`${item}-${index}`} className="rounded border border-slate-200 bg-slate-50 px-2 py-1 text-xs text-slate-600">
                  {item}
                </span>
              ))}
            </div>
          )}
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="证据分级" className="!rounded-lg !shadow-none">
          <div className="mb-3 flex flex-wrap gap-2">
            <EvidenceBadge level="C" />
            <EvidenceBadge level="I" />
            <EvidenceBadge level="U" />
          </div>
          <div className="space-y-3 text-sm">
            <div className="flex items-center justify-between">
              <span className="text-slate-600">确认 (C级)</span>
              <span className="font-semibold text-emerald-600">{(dvg.confirmedRatio * 100).toFixed(1)}%</span>
            </div>
            <div className="h-2 w-full rounded-full bg-slate-100">
              <div className="h-2 rounded-full bg-emerald-500" style={{ width: `${dvg.confirmedRatio * 100}%` }} />
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-600">推断 (I级)</span>
              <span className="font-semibold text-amber-600">{(dvg.inferredRatio * 100).toFixed(1)}%</span>
            </div>
            <div className="h-2 w-full rounded-full bg-slate-100">
              <div className="h-2 rounded-full bg-amber-500" style={{ width: `${dvg.inferredRatio * 100}%` }} />
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-600">未知 (U级)</span>
              <span className="font-semibold text-rose-600">{(dvg.unknownRatio * 100).toFixed(1)}%</span>
            </div>
            <div className="h-2 w-full rounded-full bg-slate-100">
              <div className="h-2 rounded-full bg-rose-500" style={{ width: `${dvg.unknownRatio * 100}%` }} />
            </div>
          </div>
          <SourceNote kind={dvgSourceKind} note="C/I/U 比例由实时行情、财务、公告、资金流、筹码和宏观数据源的可用性计算，不再跨案例复用固定比例。" />
        </Card>

        <Card title="下游权限" className="!rounded-lg !shadow-none">
          <TableShell className="!rounded-lg !shadow-none">
            <table className="institution-table">
              <thead className="bg-slate-50">
                <tr className="text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                  <th className="px-3 py-2">权限</th>
                  <th className="px-3 py-2">文案</th>
                  <th className="px-3 py-2">原始值</th>
                  <th className="px-3 py-2">状态</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 bg-white">
                {permissionRows.map((row) => (
                  <tr key={row.label}>
                    <td className="px-3 py-2 font-medium text-slate-900">{row.label}</td>
                    <td className="px-3 py-2 text-slate-600">{row.value}</td>
                    <td className="px-3 py-2 font-mono text-xs text-slate-700">{row.raw}</td>
                    <td className="px-3 py-2"><Badge status={row.status} className="!rounded-md px-2 py-0.5">{row.status}</Badge></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableShell>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="数据新鲜度 & 完整性" className="!rounded-lg !shadow-none">
          <div className="divide-y divide-slate-100">
            {freshnessRows.map((row) => (
              <div key={row.label} className="grid gap-2 py-2 text-sm sm:grid-cols-[120px_1fr_auto]">
                <span className="font-medium text-slate-900">{row.label}</span>
                <span className="text-slate-600">{row.value}</span>
                <Badge status={row.status} className="justify-self-start !rounded-md px-2 py-0.5 sm:justify-self-end">{row.raw}</Badge>
              </div>
            ))}
          </div>
        </Card>

        {dvg.dataConflicts.length > 0 && (
          <Card title="数据冲突" className="!rounded-lg !shadow-none">
            <div className="space-y-1">
              {dvg.dataConflicts.map((c, i) => (
                <div key={i} className="flex items-center gap-2 rounded border border-amber-100 bg-amber-50 p-2 text-sm text-amber-800">
                  <div className="h-1.5 w-1.5 rounded-full bg-amber-500" />{c}
                </div>
              ))}
            </div>
          </Card>
        )}
      </div>

      {dvg.criticalMissingData.length > 0 && (
        <Card title="关键缺失数据" className="!rounded-lg !shadow-none">
          <div className="space-y-1">
            {dvg.criticalMissingData.map((item, i) => (
              <div key={i} className="flex items-center gap-2 rounded border border-rose-100 bg-rose-50 p-2 text-sm text-rose-800">
                <div className="h-1.5 w-1.5 rounded-full bg-rose-500" />{item}
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  )
}
