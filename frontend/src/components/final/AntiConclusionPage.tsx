import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useAnalysisStore } from '../../store/useAnalysisStore'
import { displayFinalWriterContent } from '../../utils/conclusionInsights'
import { SectionTitle } from '../common/SectionTitle'
import { Badge } from '../common/Badge'
import { Card } from '../common/Card'
import { MetricTile, TableShell } from '../common/Material'

export function AntiConclusionPage() {
  const { currentRun, currentRunId: storeRunId, refreshRun } = useAnalysisStore()
  const [searchParams] = useSearchParams()
  const [deepLinkError, setDeepLinkError] = useState('')
  const hydrationAttemptRef = useRef('')
  const linkedRunId = searchParams.get('run_id')?.trim() || ''

  useEffect(() => {
    if (!linkedRunId || storeRunId === linkedRunId) return
    if (hydrationAttemptRef.current === linkedRunId) return
    hydrationAttemptRef.current = linkedRunId
    setDeepLinkError('')
    refreshRun(linkedRunId).catch((error) => {
      setDeepLinkError(error instanceof Error ? error.message : '加载运行失败')
    })
  }, [linkedRunId, refreshRun, storeRunId])

  if (!currentRun || (linkedRunId && currentRun.runId !== linkedRunId)) {
    return (
      <div data-testid="anti-conclusion-page-loading" className="text-sm text-slate-500">
        正在加载反结论审查...
        {linkedRunId ? <span className="ml-2 font-mono">{linkedRunId}</span> : null}
        {deepLinkError ? <div className="mt-2 text-red-600">{deepLinkError}</div> : null}
      </div>
    )
  }

  const finalWriter = currentRun.finalWriter
  const execution = currentRun.execution
  const killSwitch = currentRun.killSwitch
  const reviewRows = [
    { label: '门禁一致性', value: killSwitch?.active ? '阻断已触发' : '正常', status: killSwitch?.active ? 'WARN' : 'PASS' },
    { label: '最终动作', value: currentRun.finalAction, status: currentRun.finalAction === 'WAIT' ? 'WARN' : currentRun.finalAction === 'BUY_CANDIDATE' ? 'PASS' : 'WARN' },
    { label: '需人工确认', value: finalWriter?.humanConfirmationRequired !== false ? '是' : '否', status: 'WARN' },
    { label: '禁止动作数', value: execution?.forbiddenActions?.length?.toString() ?? '0', status: execution?.forbiddenActions?.length > 0 ? 'WARN' : 'PASS' },
  ]

  return (
    <div className="space-y-5" data-testid="anti-conclusion-page">
      <SectionTitle title="反结论审查" subtitle="防止后门推理与结论漂移。" dataMode={currentRun?.dataMode} />

      <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-500">
        Run ID: <span data-testid="anti-conclusion-current-run-id" className="break-all font-mono text-slate-700">{currentRun.runId}</span>
      </div>

      <div
        data-testid="anti-conclusion-simulation-boundary"
        className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm leading-6 text-amber-900"
      >
        反结论审查只复核上游门禁与最终输出一致性，不生成实盘指令：
        simulation_only=true / is_real_trade=false / evidence_usage=anti_conclusion_review_only / strong_conclusion_allowed=false / SIM_*
      </div>

      <Card title="结论一致性状态轨" className="!rounded-lg !shadow-none">
        <div className="grid gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
          <div className="rounded-md border border-[#d2e3fc] bg-[#e8f0fe] p-4">
            <div className="text-xs font-semibold uppercase tracking-wide text-[#1967d2]">Anti Conclusion</div>
            <div className="mt-2 text-2xl font-semibold tracking-tight text-slate-950">{currentRun.finalAction}</div>
            <div className="mt-3 text-xs leading-5 text-slate-600">
              最终输出只能复述上游门禁，不允许绕过 Risk、DVG、Execution 重新推理。
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {reviewRows.map((item) => (
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
        {reviewRows.map((item) => (
          <MetricTile
            key={item.label}
            label={item.label}
            value={item.value}
            helper={item.status}
            tone={item.status === 'PASS' ? 'success' : 'warning'}
            className="!rounded-lg !shadow-none"
          />
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="允许动作" className="!rounded-lg !shadow-none">
          {execution?.allowedActions?.length > 0 ? (
            <TableShell className="!rounded-lg !shadow-none">
              <table className="institution-table">
                <thead className="bg-slate-50">
                  <tr className="text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                    <th className="px-3 py-2">动作</th>
                    <th className="px-3 py-2">状态</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 bg-white">
                  {execution.allowedActions.map((a: string, i: number) => (
                    <tr key={i}>
                      <td className="px-3 py-2 text-slate-700">{a}</td>
                      <td className="px-3 py-2"><Badge status="PASS" className="!rounded-md px-2 py-0.5">允许</Badge></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableShell>
          ) : <div className="text-sm text-slate-400">无允许动作</div>}
        </Card>

        <Card title="禁止动作" className="!rounded-lg !shadow-none">
          {execution?.forbiddenActions?.length > 0 ? (
            <TableShell className="!rounded-lg !shadow-none">
              <table className="institution-table">
                <thead className="bg-slate-50">
                  <tr className="text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                    <th className="px-3 py-2">动作</th>
                    <th className="px-3 py-2">状态</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 bg-white">
                  {execution.forbiddenActions.map((a: string, i: number) => (
                    <tr key={i}>
                      <td className="px-3 py-2 text-slate-700">{a}</td>
                      <td className="px-3 py-2"><Badge status="FAIL" className="!rounded-md px-2 py-0.5">禁止</Badge></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableShell>
          ) : <div className="text-sm text-slate-400">无禁止动作</div>}
        </Card>
      </div>

      <Card title="最终输出片段" className="!rounded-lg !shadow-none">
        {finalWriter?.sections?.map((section: any, i: number) => (
          <div key={i} className="mb-3 rounded-md border border-slate-200 bg-white p-4">
            <div className="mb-2 flex items-center justify-between">
              <span className="font-semibold text-slate-900">{section.title}</span>
              <Badge status={section.riskLevel === 'LOW' ? 'PASS' : section.riskLevel === 'MEDIUM' ? 'WARN' : 'FAIL'} className="!rounded-md px-2 py-0.5">
                {section.riskLevel}
              </Badge>
            </div>
            <div className="text-sm leading-6 text-slate-600">{displayFinalWriterContent(section.content)}</div>
          </div>
        ))}
        {(!finalWriter?.sections || finalWriter.sections.length === 0) && (
          <div className="text-sm text-slate-500">暂无最终输出内容</div>
        )}
      </Card>

      {killSwitch?.active && (
        <Card title="熔断开关状态" className="!rounded-lg !shadow-none">
          <div className="space-y-2 text-sm">
            <div className="flex items-center justify-between">
              <span className="text-slate-600">触发级别</span>
              <Badge status={killSwitch.level === 'HARD' ? 'FAIL' : 'WARN'} className="!rounded-md px-2 py-0.5">{killSwitch.level}</Badge>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-600">触发节点</span>
              <span className="font-medium">{killSwitch.triggerNode}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-600">触发规则</span>
              <span className="font-medium">{killSwitch.triggerRule}</span>
            </div>
          </div>
        </Card>
      )}
    </div>
  )
}
