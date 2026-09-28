import { Link, useLocation, useSearchParams } from 'react-router-dom'
import { Ban, Database, Gauge, ShieldCheck } from 'lucide-react'
import { useAnalysisStore } from '../../store/useAnalysisStore'
import { AnalysisRun, GuardrailHubResult } from '../../types'
import { Badge } from '../common/Badge'
import { Card } from '../common/Card'
import { MetricTile, TableShell } from '../common/Material'
import { SectionTitle } from '../common/SectionTitle'

type TabId = 'overview' | 'dvg' | 'risk' | 'micro'

type GuardrailGovernance = {
  contextId: string
  evidenceStrength: 'MEDIUM' | 'LOW'
  blocker: string
  nextAction: string
  simulationOnly: boolean
  isRealTrade: boolean
  evidenceUsage: 'simulation_only'
  strongConclusionAllowed: false
}

const tabs: Array<{ id: TabId; label: string; path: string }> = [
  { id: 'overview', label: '总览', path: '/guardrail-hub' },
  { id: 'dvg', label: 'DVG', path: '/dvg-gate' },
  { id: 'risk', label: '风险熔断', path: '/risk' },
  { id: 'micro', label: '交易微观', path: '/trade-micro' },
]

function currentTab(pathname: string): TabId {
  if (pathname.includes('dvg-gate')) return 'dvg'
  if (pathname.includes('risk')) return 'risk'
  if (pathname.includes('trade-micro')) return 'micro'
  return 'overview'
}

function synthesizeGuardrailHub(run: AnalysisRun): GuardrailHubResult {
  const killSwitch = run.killSwitch
  const status =
    killSwitch.active
      ? killSwitch.level === 'COMPLIANCE' ? 'BLOCK' : 'BLOCK_BUY'
      : run.dvg.allowedOutputLevel === 'REVIEW_ONLY' ? 'REVIEW_ONLY'
        : run.dvg.status === 'WARN' || run.atrade.executionReachability !== 'REACHABLE' ? 'WARN'
          : 'PASS'
  return {
    status,
    finalDecisionCap: killSwitch.active ? 'BLOCK_BUY' : run.dvg.finalDecisionCap,
    killSwitch,
    dvg: run.dvg,
    risk: run.risk,
    atrade: run.atrade,
    gateResults: {},
    warnings: [],
    auditId: killSwitch.auditId,
    synthesizedFromLegacy: true,
  }
}

function list(value: unknown) {
  return Array.isArray(value) ? value.filter(Boolean).map(String) : []
}

function statusTone(status?: string): 'success' | 'warning' | 'danger' {
  if (status === 'PASS' || status === 'FULL' || status === 'REACHABLE' || status === 'ALLOW') return 'success'
  if (status === 'WARN' || status === 'REVIEW_ONLY' || status === 'CONDITIONALLY_REACHABLE' || status === 'ALLOW_WITH_DISCOUNT') return 'warning'
  return 'danger'
}

function pct(value: unknown, digits = 1) {
  return typeof value === 'number' && Number.isFinite(value) ? `${(value * 100).toFixed(digits)}%` : 'N/A'
}

function buildGuardrailGovernance(
  run: AnalysisRun,
  guardrail: GuardrailHubResult,
  riskRows: Array<{ label: string; value: string[] }>,
): GuardrailGovernance {
  const warnings = list(guardrail.warnings)
  const status = String(guardrail.status || '').toUpperCase()
  const finalDecisionCap = String(guardrail.finalDecisionCap || guardrail.dvg?.finalDecisionCap || '').toUpperCase()
  const riskHit = riskRows.find((row) => row.value.length > 0)
  const dvgReliability = String(guardrail.dvg?.dataReliability || '').toUpperCase()
  const dvgOutputLevel = String(guardrail.dvg?.allowedOutputLevel || '').toUpperCase()
  const executionReachability = String(guardrail.atrade?.executionReachability || '').toUpperCase()
  const simulationOnly = run.dashboardSummary?.tradeBoundary?.simulationOnly !== false
  const isRealTrade = run.dashboardSummary?.tradeBoundary?.isRealTrade === true

  let evidenceStrength: GuardrailGovernance['evidenceStrength'] = 'LOW'
  if (!guardrail.synthesizedFromLegacy && status === 'PASS' && dvgReliability === 'HIGH' && dvgOutputLevel === 'FULL' && executionReachability === 'REACHABLE' && warnings.length === 0 && !riskHit) {
    evidenceStrength = 'MEDIUM'
  }

  let blocker = ''
  if (guardrail.synthesizedFromLegacy) {
    blocker = '当前为 legacy 兼容合成，不能作为新 run canonical 强证据'
  } else if (guardrail.killSwitch?.active) {
    blocker = `Kill Switch ${guardrail.killSwitch.level || 'ACTIVE'}：${guardrail.killSwitch.triggerRule || guardrail.killSwitch.triggerNode || '规则命中'}`
  } else if (finalDecisionCap === 'BLOCK_BUY' || status === 'BLOCK' || status === 'BLOCK_BUY' || status === 'ERROR' || status === 'FAIL') {
    blocker = `最终动作上限 ${finalDecisionCap || status}`
  } else if (dvgOutputLevel !== 'FULL') {
    blocker = `DVG 输出上限 ${dvgOutputLevel || 'UNKNOWN'}`
  } else if (riskHit) {
    blocker = `${riskHit.label}：${riskHit.value[0]}`
  } else if (executionReachability !== 'REACHABLE') {
    blocker = `执行可达性 ${executionReachability || 'UNKNOWN'}`
  } else if (warnings.length > 0) {
    blocker = warnings[0]
  } else {
    blocker = '无阻断，保持人工复核'
  }

  const nextAction = guardrail.synthesizedFromLegacy
    ? '启动新 run 生成 canonical guardrail_hub'
    : blocker === '无阻断，保持人工复核'
      ? '进入 quant_core 仅模拟复核'
      : '先处理护栏阻断，再进入 quant_core / SignalOps'

  return {
    contextId: guardrail.auditId || guardrail.killSwitch?.auditId || run.runId,
    evidenceStrength,
    blocker,
    nextAction,
    simulationOnly,
    isRealTrade,
    evidenceUsage: 'simulation_only',
    strongConclusionAllowed: false,
  }
}

export function GuardrailHubPage() {
  const { currentRun } = useAnalysisStore()
  const location = useLocation()
  const [searchParams] = useSearchParams()
  const linkedRunId = (searchParams.get('run_id') || '').trim()
  const isLinkedRunPending = Boolean(linkedRunId && currentRun?.runId !== linkedRunId)

  if (!currentRun || isLinkedRunPending) {
    return (
      <div data-testid="guardrail-hub-page-loading" className="text-sm text-slate-500">
        加载中...
        {linkedRunId ? <span className="ml-2 font-mono">{linkedRunId}</span> : null}
      </div>
    )
  }

  const activeTab = currentTab(location.pathname)
  const guardrail = currentRun.guardrailHub ?? synthesizeGuardrailHub(currentRun)
  const dvg = guardrail.dvg ?? currentRun.dvg
  const risk = guardrail.risk ?? currentRun.risk
  const riskRecord = risk as unknown as Record<string, unknown>
  const atrade = guardrail.atrade ?? currentRun.atrade
  const killSwitch = guardrail.killSwitch ?? currentRun.killSwitch
  const riskRows = [
    { label: '合规红线', value: list(risk.complianceRedLines) },
    { label: '个股硬风险', value: list(risk.f0IndividualHardRisks).concat(list(riskRecord.hardRisks)) },
    { label: '极端筹码风险', value: list(risk.f1ExtremeChipCollapse) },
    { label: '流动性红线', value: list(risk.l0AbsoluteLiquidityRedLine).concat(list(riskRecord.liquidityRisks)) },
    { label: '系统性风险', value: list(risk.m0SystemicRisk).concat(list(riskRecord.systemicRisks)) },
    { label: '执行不可达', value: list(risk.executionUnreachable) },
  ]
  const microRows = [
    { label: 'T+1', value: atrade.t1Status ? '正常' : '受限', status: atrade.t1Status ? 'PASS' : 'FAIL' },
    { label: '涨跌停', value: atrade.priceLimitStatus, status: atrade.priceLimitStatus === 'NORMAL' ? 'PASS' : 'FAIL' },
    { label: 'Level-2', value: atrade.level2Available ? '可用' : '缺失', status: atrade.level2Available ? 'PASS' : 'WARN' },
    { label: '盘口深度', value: atrade.depthAvailable ? '可用' : '缺失', status: atrade.depthAvailable ? 'PASS' : 'WARN' },
    { label: '执行可达性', value: atrade.executionReachability, status: atrade.executionReachability === 'REACHABLE' ? 'PASS' : atrade.executionReachability === 'NOT_REACHABLE' ? 'BLOCK_BUY' : 'WARN' },
    { label: '流动性风险', value: atrade.liquidityRisk, status: atrade.liquidityRisk === 'LOW' ? 'PASS' : atrade.liquidityRisk === 'HIGH' ? 'BLOCK_BUY' : 'WARN' },
  ]
  const permissionRows = [
    { label: 'QIAM', value: dvg.qiamPermission },
    { label: '情景引擎', value: dvg.scenarioPermission },
    { label: '执行', value: dvg.executionPermission },
    { label: '输出上限', value: dvg.allowedOutputLevel },
    { label: '最终动作上限', value: guardrail.finalDecisionCap ?? dvg.finalDecisionCap },
  ]
  const governance = buildGuardrailGovernance(currentRun, guardrail, riskRows)

  return (
    <div className="space-y-5">
      <SectionTitle title="统一护栏中枢" subtitle="DVG、风险熔断和交易微观结构的 canonical 规则节点。" dataMode={currentRun.dataMode} />

      <div data-testid="guardrail-hub-governance" className="grid gap-2 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600 sm:grid-cols-2 xl:grid-cols-5">
        <span className="min-w-0 break-words">
          <span className="text-slate-500">ID：</span>
          <span data-testid="guardrail-hub-governance-id" className="font-mono">{governance.contextId}</span>
        </span>
        <span className="min-w-0 break-words">
          <span className="text-slate-500">证据强度：</span>
          <span data-testid="guardrail-hub-evidence-strength">{governance.evidenceStrength}</span>
        </span>
        <span className="min-w-0 break-words">
          <span className="text-slate-500">阻断：</span>
          <span data-testid="guardrail-hub-blocker">{governance.blocker}</span>
        </span>
        <span className="min-w-0 break-words">
          <span className="text-slate-500">下一步：</span>
          <span data-testid="guardrail-hub-next-action">{governance.nextAction}</span>
        </span>
        <span className="min-w-0 break-words font-medium text-slate-900" data-testid="guardrail-hub-simulation-boundary">
          simulation_only={String(governance.simulationOnly)} / is_real_trade={String(governance.isRealTrade)} / evidence_usage={governance.evidenceUsage} / strong_conclusion_allowed={String(governance.strongConclusionAllowed)} / SIM_*
        </span>
      </div>

      <div className="flex flex-wrap gap-2">
        {tabs.map((tab) => (
          <Link
            key={tab.id}
            to={tab.path}
            className={`rounded-md border px-3 py-1.5 text-sm font-medium ${
              activeTab === tab.id ? 'border-[#1967d2] bg-[#e8f0fe] text-[#1967d2]' : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50'
            }`}
          >
            {tab.label}
          </Link>
        ))}
      </div>

      <Card title="护栏状态轨" className="!rounded-lg !shadow-none">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <MetricTile label="中枢状态" value={guardrail.status} helper={guardrail.auditId ?? 'AUD_GUARDRAIL_HUB'} icon={ShieldCheck} tone={statusTone(guardrail.status)} className="!rounded-md !p-3 !shadow-none" />
          <MetricTile label="最终上限" value={guardrail.finalDecisionCap ?? dvg.finalDecisionCap} helper="finalDecisionCap" icon={Ban} tone={statusTone(String(guardrail.finalDecisionCap ?? dvg.finalDecisionCap))} className="!rounded-md !p-3 !shadow-none" />
          <MetricTile label="DVG 可靠性" value={dvg.dataReliability ?? 'N/A'} helper={dvg.allowedOutputLevel} icon={Database} tone={statusTone(dvg.status)} className="!rounded-md !p-3 !shadow-none" />
          <MetricTile label="执行可达性" value={atrade.executionReachability} helper={atrade.liquidityRisk} icon={Gauge} tone={statusTone(atrade.executionReachability)} className="!rounded-md !p-3 !shadow-none" />
        </div>
      </Card>

      {(activeTab === 'overview' || activeTab === 'risk') && (
        <Card title="风险熔断" className="!rounded-lg !shadow-none">
          <div className="grid gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
            <div className="rounded-md border border-slate-200 bg-slate-50 p-4">
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Kill Switch</div>
              <div className="mt-2 flex items-center gap-2">
                <Badge status={killSwitch.active ? 'BLOCK_BUY' : 'PASS'} className="!rounded-md px-2 py-0.5">
                  {killSwitch.active ? '已激活' : '未激活'}
                </Badge>
                <span className="font-semibold text-slate-950">{killSwitch.level}</span>
              </div>
              <div className="mt-3 break-words text-xs leading-5 text-slate-600">{killSwitch.triggerNode || 'N/A'} / {killSwitch.triggerRule || 'N/A'}</div>
            </div>
            <TableShell className="!rounded-lg !shadow-none">
              <table className="institution-table">
                <thead className="bg-slate-50">
                  <tr className="text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                    <th className="px-3 py-2">分类</th>
                    <th className="px-3 py-2">命中</th>
                    <th className="px-3 py-2">状态</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 bg-white">
                  {riskRows.map((row) => (
                    <tr key={row.label}>
                      <td className="px-3 py-2 font-medium text-slate-900">{row.label}</td>
                      <td className="px-3 py-2 text-slate-600">{row.value.length ? row.value.join('、') : '无'}</td>
                      <td className="px-3 py-2"><Badge status={row.value.length ? 'WARN' : 'PASS'} className="!rounded-md px-2 py-0.5">{row.value.length ? row.value.length : 'PASS'}</Badge></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableShell>
          </div>
        </Card>
      )}

      {(activeTab === 'overview' || activeTab === 'dvg') && (
        <Card title="DVG 数据门禁" className="!rounded-lg !shadow-none">
          <div className="grid gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
            <div className="rounded-md border border-[#d2e3fc] bg-[#e8f0fe] p-4">
              <div className="text-xs font-semibold uppercase tracking-wide text-[#1967d2]">Evidence Gate</div>
              <div className="mt-2 text-2xl font-semibold tracking-tight text-slate-950">{dvg.allowedOutputLevel}</div>
              <div className="mt-2 text-xs leading-5 text-slate-600">{dvg.activeModuleLabel ?? dvg.activeModule ?? 'DVG legacy payload'}</div>
            </div>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <MetricTile label="确认" value={pct(dvg.confirmedRatio)} helper="C" tone="success" className="!rounded-md !p-3 !shadow-none" />
              <MetricTile label="推断" value={pct(dvg.inferredRatio)} helper="I" tone="warning" className="!rounded-md !p-3 !shadow-none" />
              <MetricTile label="未知" value={pct(dvg.unknownRatio)} helper="U" tone={dvg.unknownRatio > 0 ? 'danger' : 'success'} className="!rounded-md !p-3 !shadow-none" />
              <MetricTile label="幻觉风险" value={dvg.hallucinationRiskLevel} helper={String(dvg.hallucinationRiskScore ?? 'N/A')} tone={statusTone(dvg.hallucinationRiskLevel)} className="!rounded-md !p-3 !shadow-none" />
            </div>
          </div>
          <TableShell className="mt-4 !rounded-lg !shadow-none">
            <table className="institution-table">
              <thead className="bg-slate-50">
                <tr className="text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                  <th className="px-3 py-2">权限</th>
                  <th className="px-3 py-2">值</th>
                  <th className="px-3 py-2">状态</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 bg-white">
                {permissionRows.map((row) => (
                  <tr key={row.label}>
                    <td className="px-3 py-2 font-medium text-slate-900">{row.label}</td>
                    <td className="px-3 py-2 text-slate-600">{row.value}</td>
                    <td className="px-3 py-2"><Badge status={statusTone(String(row.value)) === 'success' ? 'PASS' : statusTone(String(row.value)) === 'warning' ? 'WARN' : 'BLOCK_BUY'} className="!rounded-md px-2 py-0.5">{row.value}</Badge></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableShell>
          {list(dvg.ignoredMissingData).length > 0 && (
            <div className="mt-4 flex flex-wrap gap-2">
              {list(dvg.ignoredMissingData).map((item) => <Badge key={item} status="REVIEW_ONLY" className="!rounded-md px-2 py-0.5">{item}</Badge>)}
            </div>
          )}
        </Card>
      )}

      {(activeTab === 'overview' || activeTab === 'micro') && (
        <Card title="交易微观结构" className="!rounded-lg !shadow-none">
          <TableShell className="!rounded-lg !shadow-none">
            <table className="institution-table">
              <thead className="bg-slate-50">
                <tr className="text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                  <th className="px-3 py-2">检查项</th>
                  <th className="px-3 py-2">结果</th>
                  <th className="px-3 py-2">状态</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 bg-white">
                {microRows.map((row) => (
                  <tr key={row.label}>
                    <td className="px-3 py-2 font-medium text-slate-900">{row.label}</td>
                    <td className="px-3 py-2 text-slate-600">{row.value}</td>
                    <td className="px-3 py-2"><Badge status={row.status} className="!rounded-md px-2 py-0.5">{row.status}</Badge></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableShell>
        </Card>
      )}

      {list(guardrail.warnings).length > 0 && (
        <Card title="中枢警告" className="!rounded-lg !shadow-none">
          <div className="space-y-1">
            {list(guardrail.warnings).map((warning) => (
              <div key={warning} className="rounded-md border border-amber-100 bg-amber-50 px-3 py-2 text-sm leading-6 text-amber-800">{warning}</div>
            ))}
          </div>
        </Card>
      )}
    </div>
  )
}
