import { useAnalysisStore } from '../../store/useAnalysisStore'
import type { AnalysisRun } from '../../types'
import { SectionTitle } from '../common/SectionTitle'
import { Badge } from '../common/Badge'
import { Card } from '../common/Card'
import { MetricTile, TableShell } from '../common/Material'

type ExecutionEvidenceStrength = 'LOW' | 'MEDIUM'

interface ExecutionGovernance {
  contextId: string
  evidenceStrength: ExecutionEvidenceStrength
  blocker: string
  nextAction: string
  simulationOnly: boolean
  isRealTrade: boolean
  evidenceUsage: 'simulation_only'
  strongConclusionAllowed: false
}

function actionNeedsManualConfirmation(action: string) {
  const normalized = action.toUpperCase()
  return normalized.includes('BUY') || normalized.includes('ADD') || normalized.includes('EXECUTION_PLAN')
}

function buildExecutionGovernance(run: AnalysisRun): ExecutionGovernance {
  const execution = run.execution
  const paperTrading = run.paperTrading
  const namespace = paperTrading.allowed_order_namespace ?? paperTrading.orderNamespace ?? paperTrading.order_namespace ?? ''
  const latestAction = paperTrading.latest_action ?? paperTrading.action ?? paperTrading.paper_action ?? ''
  const simulationOnly = paperTrading.simulation_only === true
  const isRealTrade = paperTrading.is_real_trade === true
  const boundaryBroken = !simulationOnly || isRealTrade || namespace !== 'SIM_*' || (latestAction ? !latestAction.startsWith('SIM_') : false)
  const hasForbiddenActions = execution.forbiddenActions.length > 0 || execution.prohibitedActions.length > 0
  const reviewActionMissing = execution.allowedActions.some(actionNeedsManualConfirmation) && execution.manualConfirmationItems.length === 0
  const executionReachabilityBlocked = execution.executionReachability !== 'REACHABLE'
  const blocker = boundaryBroken
    ? 'SIMULATION_BOUNDARY_VIOLATED'
    : run.status !== 'COMPLETED'
      ? 'RUN_NOT_COMPLETED'
      : executionReachabilityBlocked
        ? `EXECUTION_${execution.executionReachability}`
        : hasForbiddenActions
          ? 'FORBIDDEN_ACTION_PRESENT'
          : reviewActionMissing
            ? 'MANUAL_CONFIRMATION_REQUIRED'
            : 'NONE'
  const evidenceStrength: ExecutionEvidenceStrength = boundaryBroken || run.status !== 'COMPLETED' || executionReachabilityBlocked || hasForbiddenActions || reviewActionMissing
    ? 'LOW'
    : 'MEDIUM'
  const nextAction = blocker === 'NONE'
    ? '可进入 SignalOps / Backtest 仅模拟复核'
    : blocker === 'MANUAL_CONFIRMATION_REQUIRED'
      ? '补齐人工确认；Execution 不得直接生成真实交易'
      : '先修复执行可达性、禁止动作或模拟边界'

  return {
    contextId: `${run.runId}:execution`,
    evidenceStrength,
    blocker,
    nextAction,
    simulationOnly,
    isRealTrade,
    evidenceUsage: 'simulation_only',
    strongConclusionAllowed: false,
  }
}

export function ExecutionPage() {
  const { currentRun } = useAnalysisStore()

  if (!currentRun) {
    return <div className="text-sm text-slate-500">加载中...</div>
  }

  const execution = currentRun.execution
  const executionGovernance = buildExecutionGovernance(currentRun)
  const reachability =
    execution.executionReachability === 'REACHABLE'
      ? { label: '完全可达', status: 'PASS' }
      : execution.executionReachability === 'CONDITIONALLY_REACHABLE'
        ? { label: '有条件可达', status: 'WARN' }
        : { label: '不可达', status: 'FAIL' }
  const actionRows = [
    { label: '允许动作', items: execution.allowedActions, status: 'PASS' },
    { label: '禁止动作', items: execution.prohibitedActions, status: execution.prohibitedActions.length > 0 ? 'FAIL' : 'PASS' },
    { label: '禁止动作明细', items: execution.forbiddenActions, status: execution.forbiddenActions.length > 0 ? 'FAIL' : 'PASS' },
  ]

  return (
    <div className="space-y-5">
      <SectionTitle title="执行复核" subtitle="执行策略与风险复核" dataMode={currentRun?.dataMode} />

      <Card title="执行状态轨" className="!rounded-lg !shadow-none">
        <div className="grid gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
          <div className="rounded-md border border-[#d2e3fc] bg-[#e8f0fe] p-4">
            <div className="text-xs font-semibold uppercase tracking-wide text-[#1967d2]">Execution Reachability</div>
            <div className="mt-2 flex items-center justify-between gap-3">
              <div className="text-2xl font-semibold tracking-tight text-slate-950">{reachability.label}</div>
              <Badge status={reachability.status} className="!rounded-md px-2 py-0.5">{reachability.status}</Badge>
            </div>
            <div className="mt-3 text-xs leading-5 text-slate-600">
              执行可达性只说明成交条件，不代表可以买入；买入候选必须同时出现在允许动作中，并且仍需人工确认。
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <MetricTile label="滑点限制" value={`${(execution.slippageLimit * 100).toFixed(2)}%`} tone="info" className="!rounded-md !p-3 !shadow-none" />
            <MetricTile label="参与度限制" value={`${(execution.participationLimit * 100).toFixed(0)}%`} tone="info" className="!rounded-md !p-3 !shadow-none" />
            <MetricTile label="允许动作" value={execution.allowedActions.length} tone="success" className="!rounded-md !p-3 !shadow-none" />
            <MetricTile label="人工确认" value={execution.manualConfirmationItems.length} tone="warning" className="!rounded-md !p-3 !shadow-none" />
          </div>
        </div>
      </Card>
      <div data-testid="execution-governance" className="grid gap-2 rounded-md border border-cyan-200 bg-white/80 p-3 text-xs text-slate-700 sm:grid-cols-2 xl:grid-cols-5">
        <span data-testid="execution-governance-id" className="min-w-0 break-words font-mono">
          Execution: {executionGovernance.contextId}
        </span>
        <span data-testid="execution-evidence-strength" className="min-w-0 break-words">
          Evidence: {executionGovernance.evidenceStrength}
        </span>
        <span data-testid="execution-blocker" className="min-w-0 break-words">
          Blocker: {executionGovernance.blocker}
        </span>
        <span data-testid="execution-next-action" className="min-w-0 break-words">
          Next: {executionGovernance.nextAction}
        </span>
        <span data-testid="execution-simulation-boundary" className="min-w-0 break-words font-medium text-slate-900">
          simulation_only={String(executionGovernance.simulationOnly)} / is_real_trade={String(executionGovernance.isRealTrade)} / evidence_usage={executionGovernance.evidenceUsage} / strong_conclusion_allowed={String(executionGovernance.strongConclusionAllowed)} / SIM_*
        </span>
      </div>

      <Card title="执行动作矩阵" className="!rounded-lg !shadow-none">
        <TableShell className="!rounded-lg !shadow-none">
          <table className="institution-table">
            <thead className="bg-slate-50">
              <tr className="text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                <th className="px-3 py-2">类型</th>
                <th className="px-3 py-2">数量</th>
                <th className="px-3 py-2">状态</th>
                <th className="px-3 py-2">动作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 bg-white">
              {actionRows.map((row) => (
                <tr key={row.label} className="align-top">
                  <td className="px-3 py-2 font-medium text-slate-900">{row.label}</td>
                  <td className="px-3 py-2 font-mono text-xs text-slate-700">{row.items.length}</td>
                  <td className="px-3 py-2">
                    <Badge status={row.status} className="!rounded-md px-2 py-0.5">{row.status}</Badge>
                  </td>
                  <td className="px-3 py-2 text-slate-600">{row.items.join(', ') || '无'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableShell>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="执行路径" className="!rounded-lg !shadow-none">
          <div className="space-y-3">
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">分批路径</div>
            <div className="flex flex-wrap gap-2">
              {execution.batchPaths.map((path, index) => (
                <Badge key={index} status="PASS" className="!rounded-md px-2 py-0.5">{path}</Badge>
              ))}
            </div>
          </div>
        </Card>

        <Card title="人工确认项目" className="!rounded-lg !shadow-none">
          <div className="divide-y divide-slate-100">
            {execution.manualConfirmationItems.map((item, index) => (
              <div key={index} className="flex items-start gap-2 py-2 text-sm text-slate-600">
                <div className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-[#1a73e8]" />
                <span className="min-w-0 break-words">{item}</span>
              </div>
            ))}
          </div>
        </Card>
      </div>

      <Card title="禁止动作" className="!rounded-lg !shadow-none">
        <div className="grid gap-2 sm:grid-cols-2">
          {execution.forbiddenActions.map((action, index) => (
            <div key={index} className="flex items-start gap-2 rounded-md border border-rose-100 bg-white p-3 text-sm text-slate-700">
              <div className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-rose-500" />
              <span className="min-w-0 break-words">{action}</span>
            </div>
          ))}
        </div>
      </Card>
    </div>
  )
}
