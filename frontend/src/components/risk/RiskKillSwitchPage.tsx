import { useAnalysisStore } from '../../store/useAnalysisStore'
import { SectionTitle } from '../common/SectionTitle'
import { Card } from '../common/Card'
import { Badge } from '../common/Badge'
import { MetricTile, TableShell } from '../common/Material'

function gateTone(status: string) {
  if (status === 'PASS' || status === 'NONE') return 'bg-emerald-500'
  if (status === 'SOFT' || status === 'WARN') return 'bg-amber-500'
  return 'bg-rose-500'
}

export function RiskKillSwitchPage() {
  const { currentRun } = useAnalysisStore()

  if (!currentRun) {
    return <div className="text-sm text-slate-500">加载中...</div>
  }

  const { risk, killSwitch } = currentRun
  const riskRows = [
    { label: '合规红线', value: risk.complianceRedLines.length, detail: risk.complianceRedLines.join('、') || '无' },
    { label: '个股硬风险', value: risk.f0IndividualHardRisks.length, detail: risk.f0IndividualHardRisks.join('、') || '无' },
    { label: '极端筹码风险', value: risk.f1ExtremeChipCollapse.length, detail: risk.f1ExtremeChipCollapse.join('、') || '无' },
    { label: '系统性风险', value: risk.m0SystemicRisk.length, detail: risk.m0SystemicRisk.join('、') || '无' },
  ]
  const guardrailRows = [
    { label: '激活', value: killSwitch.active ? '已激活' : '未激活', status: killSwitch.active ? 'BLOCK_BUY' : 'PASS' },
    { label: '级别', value: killSwitch.level, status: killSwitch.level },
    { label: '触发节点', value: killSwitch.triggerNode || 'N/A', status: killSwitch.active ? 'WARN' : 'PASS' },
    { label: '触发规则', value: killSwitch.triggerRule || 'N/A', status: killSwitch.active ? 'WARN' : 'PASS' },
  ]

  return (
    <div className="space-y-5">
      <SectionTitle title="风险与熔断开关" subtitle="风险审查与熔断开关控制" dataMode={currentRun?.dataMode} />

      <Card title="熔断状态轨" className="!rounded-lg !shadow-none">
        <div className="grid gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
          <div className="rounded-md border border-[#d2e3fc] bg-[#e8f0fe] p-4">
            <div className="text-xs font-semibold uppercase tracking-wide text-[#1967d2]">Kill Switch</div>
            <div className="mt-2 flex items-center gap-3">
              <span className={`h-3 w-3 rounded-full ${gateTone(killSwitch.active ? killSwitch.level : 'PASS')}`} />
              <div className="text-2xl font-semibold text-slate-950">{killSwitch.active ? '已激活' : '未激活'}</div>
            </div>
            <div className="mt-2 text-xs leading-5 text-slate-600">风险、执行和最终输出链路以此开关为最高约束。</div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {guardrailRows.map((row) => (
              <MetricTile
                key={row.label}
                label={row.label}
                value={row.value}
                helper={row.status}
                tone={row.status === 'PASS' ? 'success' : row.status === 'WARN' ? 'warning' : 'danger'}
                className="!rounded-md !p-3 !shadow-none"
              />
            ))}
          </div>
        </div>
      </Card>

      <Card title="风险分类矩阵" className="!rounded-lg !shadow-none">
        <TableShell className="!rounded-lg !shadow-none">
          <table className="institution-table">
            <thead className="bg-slate-50">
              <tr className="text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                <th className="px-3 py-2">风险分类</th>
                <th className="px-3 py-2">命中数</th>
                <th className="px-3 py-2">状态</th>
                <th className="px-3 py-2">证据</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 bg-white">
              {riskRows.map((row) => (
                <tr key={row.label} className="align-top">
                  <td className="px-3 py-2 font-medium text-slate-900">{row.label}</td>
                  <td className="px-3 py-2 font-mono text-xs text-slate-700">{row.value}</td>
                  <td className="px-3 py-2">
                    <Badge status={row.value > 0 ? 'WARN' : 'PASS'} className="!rounded-md px-2 py-0.5">
                      {row.value > 0 ? '需复核' : '无命中'}
                    </Badge>
                  </td>
                  <td className="px-3 py-2 text-slate-600">{row.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableShell>
      </Card>

      <Card title="阻断路径与允许路径" className="!rounded-lg !shadow-none">
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="rounded-md border border-rose-100 bg-white p-3">
            <div className="font-medium text-slate-900">阻断路径</div>
            <div className="mt-2 flex flex-wrap gap-2">
              {killSwitch.blockedPaths.length === 0 ? (
                <Badge status="PASS" className="!rounded-md px-2 py-0.5">无</Badge>
              ) : (
                killSwitch.blockedPaths.map((path) => <Badge key={path} status="BLOCK_BUY" className="!rounded-md px-2 py-0.5">{path}</Badge>)
              )}
            </div>
          </div>

          <div className="rounded-md border border-emerald-100 bg-white p-3">
            <div className="font-medium text-slate-900">允许路径</div>
            <div className="mt-2 flex flex-wrap gap-2">
              {killSwitch.allowedPaths.map((path) => (
                <Badge key={path} status="ALLOW" className="!rounded-md px-2 py-0.5">{path}</Badge>
              ))}
            </div>
          </div>
        </div>
      </Card>
    </div>
  )
}
