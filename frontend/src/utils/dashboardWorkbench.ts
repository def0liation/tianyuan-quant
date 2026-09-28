import { AnalysisRun, DashboardSummary } from '../types'
import { buildDashboardProvenanceSummary, DashboardProvenanceSummary } from './dataProvenance'

export interface DashboardWorkbenchModel {
  summary: DashboardSummary
  provenance: DashboardProvenanceSummary
  decisionStatus: 'PASS' | 'WARN' | 'FAIL'
  boundaryStatus: 'PASS' | 'FAIL'
  evidenceScorePercent: number
  sourceRatioLabel: string
  primaryBlocker: string
  primaryWarning: string
  nextReviewRows: string[]
}

export function buildDashboardWorkbench(
  run: AnalysisRun,
  provenance = buildDashboardProvenanceSummary(run),
): DashboardWorkbenchModel {
  const fallback = buildFallbackDashboardSummary(run, provenance)
  const summary = normalizeDashboardSummary(run.dashboardSummary, fallback)
  const decisionStatus = summary.blockers.length > 0
    ? 'WARN'
    : ['REJECT', 'REDUCE', 'DEFENSIVE'].includes(String(summary.decisionState).toUpperCase())
      ? 'WARN'
      : 'PASS'
  const boundaryStatus = summary.tradeBoundary.simulationOnly === true && summary.tradeBoundary.isRealTrade === false
    ? 'PASS'
    : 'FAIL'
  const sourceTotal = summary.metrics.sourceTotalCount
  const sourceReady = summary.metrics.sourceReadyCount

  return {
    summary,
    provenance,
    decisionStatus,
    boundaryStatus,
    evidenceScorePercent: Math.round(clamp01(summary.metrics.evidenceScore) * 100),
    sourceRatioLabel: sourceTotal > 0 ? `${sourceReady}/${sourceTotal}` : '0/0',
    primaryBlocker: summary.blockers[0] ?? '当前没有硬阻断；仍需按人工复核流程处理。',
    primaryWarning: summary.warnings[0] ?? '暂无额外数据警告。',
    nextReviewRows: summary.nextReview.length > 0 ? summary.nextReview : ['查看 Agent 链路定位结论来源与失败节点'],
  }
}

function buildFallbackDashboardSummary(run: AnalysisRun, provenance: DashboardProvenanceSummary): DashboardSummary {
  const finalAction = String(run.finalWriter?.finalAction ?? run.finalAction ?? 'WAIT')
  const sourceReadyCount = run.dataSources?.summary?.availableCount ?? Object.values(run.dataSources?.sources ?? {}).filter((source) => source.available).length
  const sourceTotalCount = run.dataSources?.summary?.totalCount ?? Object.keys(run.dataSources?.sources ?? {}).length
  const { activeAgentCount, blockedAgentCount } = agentCounts(run)
  const currentPositionPct = ratioToPercent(run.userPosition?.currentPositionRatio)
  const singleStockCapPct = ratioToPercent(run.portfolio?.singleStockPositionCap)
  const blockers = fallbackBlockers(run, finalAction, blockedAgentCount)
  const warnings = fallbackWarnings(run, provenance)
  const nextReview = fallbackNextReview(finalAction, blockers, warnings, run.finalWriter?.humanConfirmationRequired !== false)

  return {
    schema: 'analysis_dashboard_summary_v1',
    generatedAt: run.updatedAt,
    decisionState: finalAction,
    headline: fallbackHeadline(finalAction, blockers, warnings),
    tradeBoundary: {
      simulationOnly: true,
      isRealTrade: false,
      humanConfirmationRequired: run.finalWriter?.humanConfirmationRequired !== false,
    },
    metrics: {
      evidenceScore: provenance.score,
      sourceReadyCount,
      sourceTotalCount,
      activeAgentCount,
      blockedAgentCount,
      currentPositionPct,
      singleStockCapPct,
      capRemainingPct: singleStockCapPct - currentPositionPct,
    },
    blockers,
    warnings,
    nextReview,
  }
}

function normalizeDashboardSummary(value: DashboardSummary | undefined, fallback: DashboardSummary): DashboardSummary {
  if (!value || value.schema !== 'analysis_dashboard_summary_v1') return fallback
  const tradeBoundary = value.tradeBoundary as Partial<DashboardSummary['tradeBoundary']> | undefined
  return {
    ...fallback,
    ...value,
    tradeBoundary: {
      simulationOnly: typeof tradeBoundary?.simulationOnly === 'boolean' ? tradeBoundary.simulationOnly : fallback.tradeBoundary.simulationOnly,
      isRealTrade: typeof tradeBoundary?.isRealTrade === 'boolean' ? tradeBoundary.isRealTrade : fallback.tradeBoundary.isRealTrade,
      humanConfirmationRequired: typeof tradeBoundary?.humanConfirmationRequired === 'boolean'
        ? tradeBoundary.humanConfirmationRequired
        : fallback.tradeBoundary.humanConfirmationRequired,
    },
    metrics: {
      ...fallback.metrics,
      ...value.metrics,
    },
    blockers: stringList(value.blockers, fallback.blockers),
    warnings: stringList(value.warnings, fallback.warnings),
    nextReview: stringList(value.nextReview, fallback.nextReview),
  }
}

function agentCounts(run: AnalysisRun) {
  const agentResults = run.agentResults ?? []
  if (agentResults.length > 0) {
    return {
      activeAgentCount: agentResults.filter((agent) => String(agent.status).toUpperCase() !== 'SKIPPED').length,
      blockedAgentCount: agentResults.filter((agent) => (
        ['BLOCK', 'BLOCKED', 'FAIL', 'FAILED'].includes(String(agent.status).toUpperCase()) || agent.hard_stop
      )).length,
    }
  }

  return {
    activeAgentCount: run.nodes.filter((node) => !node.isSkipped).length,
    blockedAgentCount: run.nodes.filter((node) => node.isBlocked || ['BLOCK', 'BLOCKED', 'FAIL', 'FAILED'].includes(String(node.status).toUpperCase())).length,
  }
}

function fallbackBlockers(run: AnalysisRun, finalAction: string, blockedAgentCount: number) {
  const rows: string[] = []
  const killLevel = String(run.killSwitch?.level ?? 'NONE').toUpperCase()
  if (run.killSwitch?.active || (killLevel && killLevel !== 'NONE')) rows.push(`Risk/Kill Switch ${killLevel} 限制交易动作`)
  if (run.dvg?.hardStop) rows.push('DVG hard stop 阻断后续动作')
  const outputLevel = String(run.dvg?.allowedOutputLevel ?? '').toUpperCase()
  if (['REVIEW_ONLY', 'BLOCK_BUY'].includes(outputLevel)) rows.push(`DVG 输出级别为 ${outputLevel}`)
  const reachability = String(run.execution?.executionReachability ?? '').toUpperCase()
  if (['NOT_REACHABLE', 'UNREACHABLE'].includes(reachability)) rows.push('Execution 不可达')
  if (blockedAgentCount > 0) rows.push(`${blockedAgentCount} 个 Agent 节点阻断或失败`)
  if (['BUY_CANDIDATE', 'ADD_CANDIDATE'].includes(finalAction)) rows.push('候选动作仍需 DVG、Risk、Execution 与人工确认')
  return dedupe(rows).slice(0, 6)
}

function fallbackWarnings(run: AnalysisRun, provenance: DashboardProvenanceSummary) {
  const rows = [...provenance.warnings]
  const dataSourceStatus = run.dataSources?.summary?.overallStatus
  if (dataSourceStatus && dataSourceStatus !== 'READY') rows.push(`数据源整体状态 ${dataSourceStatus}`)
  if (run.dvg?.dataReliability && run.dvg.dataReliability !== 'HIGH') rows.push(`DVG 数据可靠性 ${run.dvg.dataReliability}`)
  if (provenance.missingFields.length > 0) rows.push(`存在 ${provenance.missingFields.length} 项关键缺失数据`)
  return dedupe(rows).slice(0, 6)
}

function fallbackNextReview(finalAction: string, blockers: string[], warnings: string[], humanConfirmationRequired: boolean) {
  const rows: string[] = []
  if (blockers.length > 0) rows.push('先处理阻断项，再讨论任何候选动作')
  if (warnings.length > 0) rows.push('复核数据源、新鲜度、fallback 链和关键缺失字段')
  if (['BUY_CANDIDATE', 'ADD_CANDIDATE'].includes(finalAction)) rows.push('候选动作只进入人工复核和模拟观察，不触发实盘')
  if (humanConfirmationRequired) rows.push('执行前必须保留人工确认')
  rows.push('查看 Agent 链路定位结论来源与失败节点')
  return dedupe(rows).slice(0, 5)
}

function fallbackHeadline(finalAction: string, blockers: string[], warnings: string[]) {
  if (blockers.length > 0) return `当前为 ${finalAction}，但首要约束是：${blockers[0]}。`
  if (warnings.length > 0) return `当前为 ${finalAction}，需要先复核：${warnings[0]}。`
  return `当前为 ${finalAction}，核心门禁未报告硬阻断；仍只作为模拟/人工复核工作台展示。`
}

function ratioToPercent(value: unknown) {
  const numeric = typeof value === 'number' && Number.isFinite(value) ? value : 0
  return Math.abs(numeric) <= 1 ? numeric * 100 : numeric
}

function stringList(value: unknown, fallback: string[]) {
  return Array.isArray(value) ? value.map(String).filter(Boolean) : fallback
}

function clamp01(value: number) {
  return Math.min(1, Math.max(0, Number.isFinite(value) ? value : 0))
}

function dedupe(values: string[]) {
  return Array.from(new Set(values.filter(Boolean)))
}
