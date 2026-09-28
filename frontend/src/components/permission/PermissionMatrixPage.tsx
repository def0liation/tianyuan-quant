import { useMemo } from 'react'
import { useAnalysisStore } from '../../store/useAnalysisStore'
import type { AnalysisRun } from '../../types'
import { SectionTitle } from '../common/SectionTitle'
import { Card } from '../common/Card'
import { Badge } from '../common/Badge'
import { MetricTile, TableShell } from '../common/Material'

type PermissionMatrixEvidenceStrength = 'LOW' | 'MEDIUM'

interface PermissionMatrixGovernance {
  contextId: string
  evidenceStrength: PermissionMatrixEvidenceStrength
  blocker: string
  nextAction: string
  simulationOnly: boolean
  isRealTrade: boolean
  evidenceUsage: 'simulation_only'
  strongConclusionAllowed: false
}

function finalActionNeedsFullPermission(action: string) {
  return action === 'BUY_CANDIDATE' || action === 'ADD_CANDIDATE'
}

function buildPermissionMatrixGovernance(run: AnalysisRun): PermissionMatrixGovernance {
  const paperTrading = run.paperTrading
  const namespace = paperTrading.allowed_order_namespace ?? paperTrading.orderNamespace ?? paperTrading.order_namespace ?? ''
  const latestAction = paperTrading.latest_action ?? paperTrading.action ?? paperTrading.paper_action ?? ''
  const simulationOnly = paperTrading.simulation_only === true
  const isRealTrade = paperTrading.is_real_trade === true
  const boundaryBroken = !simulationOnly || isRealTrade || namespace !== 'SIM_*' || (latestAction ? !latestAction.startsWith('SIM_') : false)
  const finalAction = run.finalWriter?.finalAction ?? run.finalAction
  const dvgBlocked = run.dvg.allowedOutputLevel !== 'FULL'
  const qiamBlocked = run.qiam.finalBuySuitability === 'BLOCK_BUY' || run.qiam.finalBuySuitability === 'REVIEW_ONLY'
  const executionBlocked = run.execution.executionReachability !== 'REACHABLE' || run.execution.prohibitedActions.length > 0 || run.execution.forbiddenActions.length > 0
  const killSwitchBlocked = run.killSwitch.active
  const finalActionViolatesPermission = finalActionNeedsFullPermission(finalAction) && (dvgBlocked || qiamBlocked || executionBlocked || killSwitchBlocked)
  const reviewMissing = finalActionNeedsFullPermission(finalAction) && run.finalWriter?.humanConfirmationRequired !== true
  const blocker = boundaryBroken
    ? 'SIMULATION_BOUNDARY_VIOLATED'
    : killSwitchBlocked
      ? 'KILL_SWITCH_ACTIVE'
      : dvgBlocked
        ? 'DVG_OUTPUT_NOT_FULL'
        : qiamBlocked
          ? 'QIAM_REVIEW_OR_BLOCK'
          : executionBlocked
            ? 'EXECUTION_PERMISSION_BLOCKED'
            : finalActionViolatesPermission
              ? 'FINAL_ACTION_EXCEEDS_PERMISSION'
              : reviewMissing
                ? 'HUMAN_CONFIRMATION_REQUIRED'
                : 'NONE'
  const evidenceStrength: PermissionMatrixEvidenceStrength = boundaryBroken || killSwitchBlocked || dvgBlocked || qiamBlocked || executionBlocked || finalActionViolatesPermission || reviewMissing || run.status !== 'COMPLETED'
    ? 'LOW'
    : 'MEDIUM'
  const nextAction = blocker === 'NONE'
    ? '可进入 Final Writer / SignalOps / Backtest 仅模拟复核'
    : blocker === 'HUMAN_CONFIRMATION_REQUIRED'
      ? '补齐人工确认；权限矩阵不能升级为真实交易许可'
      : '先修复上游权限、熔断或模拟边界'

  return {
    contextId: `${run.runId}:permission`,
    evidenceStrength,
    blocker,
    nextAction,
    simulationOnly,
    isRealTrade,
    evidenceUsage: 'simulation_only',
    strongConclusionAllowed: false,
  }
}

export function PermissionMatrixPage() {
  const { currentRun } = useAnalysisStore()

  const matrix = useMemo(() => {
    if (!currentRun) return []

    return [
      {
        label: 'DVG 输出权限',
        value: currentRun.dvg.allowedOutputLevel,
        status: currentRun.dvg.status,
        reason: currentRun.dvg.criticalMissingData.length > 0 ? currentRun.dvg.criticalMissingData.join(', ') : '无',
      },
      {
        label: 'QIAM 决策建议',
        value: currentRun.qiam.finalBuySuitability,
        status: currentRun.qiam.discountFactor < 1 ? 'WARN' : 'PASS',
        reason: currentRun.qiam.downgradeReasons.join(', ') || '无',
      },
      {
        label: 'Execution 许可',
        value: currentRun.execution.executionReachability,
        status: currentRun.execution.prohibitedActions.length > 0 ? 'FAIL' : 'PASS',
        reason: currentRun.execution.forbiddenActions.join(', ') || '无',
      },
      {
        label: '熔断开关',
        value: currentRun.killSwitch.level,
        status: currentRun.killSwitch.active ? 'BLOCK_BUY' : 'PASS',
        reason: currentRun.killSwitch.blockedPaths.join(', ') || '无',
      },
    ]
  }, [currentRun])

  if (!currentRun) {
    return <div className="text-sm text-slate-500">加载中...</div>
  }

  const permissionGovernance = buildPermissionMatrixGovernance(currentRun)

  return (
    <div className="space-y-5">
      <SectionTitle title="权限矩阵" subtitle="权限矩阵与决策边界" />

      <Card title="护栏状态轨" className="!rounded-lg !shadow-none">
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_280px]">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {matrix.map((item, index) => (
              <MetricTile
                key={item.label}
                label={`STEP ${index + 1} / ${item.label}`}
                value={item.value}
                helper={item.status}
                tone={item.status === 'PASS' || item.status === 'ALLOW' ? 'success' : item.status === 'FAIL' || item.status === 'BLOCK_BUY' ? 'danger' : 'warning'}
                className="!rounded-md !p-3 !shadow-none"
              />
            ))}
          </div>

          <div className="rounded-md border border-[#d2e3fc] bg-[#e8f0fe] p-3">
            <div className="text-xs font-semibold uppercase tracking-wide text-[#1967d2]">决策边界</div>
            <div className="mt-2 text-2xl font-semibold tracking-tight text-slate-950">{currentRun.finalAction}</div>
            <div className="mt-2 text-xs leading-5 text-slate-600">
              DVG、QIAM、Execution 与熔断开关必须同时允许，最终输出不能越过上游权限。
            </div>
          </div>
        </div>
      </Card>
      <div data-testid="permission-matrix-governance" className="grid gap-2 rounded-md border border-cyan-200 bg-white/80 p-3 text-xs text-slate-700 sm:grid-cols-2 xl:grid-cols-5">
        <span data-testid="permission-matrix-governance-id" className="min-w-0 break-words font-mono">
          Permission: {permissionGovernance.contextId}
        </span>
        <span data-testid="permission-matrix-evidence-strength" className="min-w-0 break-words">
          Evidence: {permissionGovernance.evidenceStrength}
        </span>
        <span data-testid="permission-matrix-blocker" className="min-w-0 break-words">
          Blocker: {permissionGovernance.blocker}
        </span>
        <span data-testid="permission-matrix-next-action" className="min-w-0 break-words">
          Next: {permissionGovernance.nextAction}
        </span>
        <span data-testid="permission-matrix-simulation-boundary" className="min-w-0 break-words font-medium text-slate-900">
          simulation_only={String(permissionGovernance.simulationOnly)} / is_real_trade={String(permissionGovernance.isRealTrade)} / evidence_usage={permissionGovernance.evidenceUsage} / strong_conclusion_allowed={String(permissionGovernance.strongConclusionAllowed)} / SIM_*
        </span>
      </div>

      <Card title="决策矩阵" className="!rounded-lg !shadow-none">
        <TableShell className="!rounded-lg !shadow-none">
          <table className="institution-table">
            <thead className="bg-slate-50">
              <tr className="text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                <th className="px-3 py-2">权限节点</th>
                <th className="px-3 py-2">当前值</th>
                <th className="px-3 py-2">状态</th>
                <th className="px-3 py-2">说明</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 bg-white">
              {matrix.map((item) => (
                <tr key={item.label} className="align-top">
                  <td className="px-3 py-2 font-medium text-slate-900">{item.label}</td>
                  <td className="px-3 py-2 font-mono text-xs text-slate-700">{item.value}</td>
                  <td className="px-3 py-2">
                    <Badge status={item.status} className="!rounded-md px-2 py-0.5">{item.status}</Badge>
                  </td>
                  <td className="px-3 py-2 text-slate-600">{item.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableShell>
      </Card>

      <div className="grid gap-4 lg:grid-cols-4">
        {matrix.map((item) => (
          <MetricTile key={item.label} label={item.label} value={item.value} helper={`说明: ${item.reason}`} className="!rounded-lg !shadow-none" />
        ))}
      </div>
    </div>
  )
}
