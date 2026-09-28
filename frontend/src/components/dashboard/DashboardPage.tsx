import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { Activity, AlertTriangle, Database, GitBranch, ShieldCheck, Target, SkipForward, Wifi, WifiOff, Clock, FileText, Layers, BarChart3, RefreshCw, PauseCircle, PlayCircle, XCircle, ChevronDown, ChevronUp, Cpu, ArrowRight } from 'lucide-react'
import { useAnalysisStore } from '../../store/useAnalysisStore'
import { buildConclusionInsights, buildQiamProbabilityView } from '../../utils/conclusionInsights'
import { buildDashboardWorkbench } from '../../utils/dashboardWorkbench'
import { buildRunFailureNotice } from '../../utils/runFailure'
import { formatDateTime } from '../../utils/format'
import { canonicalAgentFor } from '../../utils/agentCanonical'
import { SectionTitle } from '../common/SectionTitle'
import { Card } from '../common/Card'
import { Badge } from '../common/Badge'
import { DataModeBadge } from '../common/DataModeBadge'
import { MetricTile } from '../common/Material'
import { Skeleton } from '../common/Skeleton'
import { KlineChartCard } from './KlineChartCard'
import { TechnicalKlineSummaryCard } from '../technical/TechnicalKlineSummaryCard'
import { AgentResult, AgentNode, AnalysisRun, BottomResearchResult, DataSourceStatus, KnowledgeVersionItem, PostPublishRegressionReport, QuantCoreInterpretation } from '../../types'
import { buildDashboardProvenanceSummary } from '../../utils/dataProvenance'
import { getKnowledgeVersions } from '../../api/caseLibraryClient'
import { getBackendMetrics, type ProductionHealth, type ProductionHealthMetric } from '../../api/analysisClient'
import { createP2ClosedLoopSample, type P2ClosedLoopSampleResponse } from '../../api/researchClient'
import { roleAllows, useOperatorContext } from '../../store/operatorContext'
import { useCachedResource } from '../../hooks/useCachedResource'

const iconMap: Record<string, React.ElementType> = {
  BarChart3, FileText, Clock, Layers, Target,
}

const DATA_SOURCE_PREVIEW_LIMIT = 3
const CORE_PLACEHOLDER_VALUES = new Set(['', 'N/A', 'NONE', 'NULL', 'UNKNOWN', 'NOT_AVAILABLE'])

function dataSourceIcon(iconName: string): React.ElementType {
  return iconMap[iconName] || Database
}

function dataSourceStatusLabel(status: string): string {
  const map: Record<string, string> = {
    READY: '已就绪',
    FAILED: '拉取失败',
    NOT_CONFIGURED: '未配置',
  }
  return map[status] ?? status
}

function taskTypeLabel(taskType?: string) {
  const value = String(taskType || '').trim()
  const map: Record<string, string> = {
    STOCK_ANALYSIS: '个股分析',
    SINGLE_STOCK: '个股分析',
    A_SHARE: 'A 股分析',
    A_SHARE_STOCK: 'A 股分析',
  }
  if (!value || /^\?+$/.test(value)) return '个股分析'
  return map[value] ?? value
}

function runModeLabel(mode?: string) {
  const value = String(mode || '').trim()
  const map: Record<string, string> = {
    FAST_MODE: '快速模式',
    STANDARD_MODE: '标准模式',
    DEEP_MODE: '深度模式',
  }
  return map[value] ?? value
}

function buildDataSourceList(
  run: NonNullable<ReturnType<typeof useAnalysisStore.getState>['currentRun']>
): Array<DataSourceStatus & { key: string }> {
  if (!run?.dataSources?.sources) return []
  return Object.entries(run.dataSources.sources).map(([key, source]) => ({
    key,
    ...source,
  }))
}

const DAG_ORDER: Record<string, number> = {
  orchestrator: 1, data_reliability_engine: 2, data_engine: 2, guardrail_hub: 3,
  dvg_gate: 3, risk_firewall: 3, trade_micro: 3, quant_core: 4, execution: 5,
  anti_conclusion: 6, signalops: 7, final_writer: 8,
  market_technical_analyst: 60, bottom_research: 61, quant_engine: 62,
  scenario_engine: 63,
  market_regime: 60, technical_kline_analyst: 61,
}

interface SortedAgent {
  node: string
  name: string
  status: string
  reason: string
  isSkipped: boolean
  isBlocked: boolean
  hardStop: boolean
  skippedReason?: string
  auditId: string
  legacyCompatibilityOnly?: boolean
  canonicalNode?: string
  activeNode?: boolean
}

function normalizeSortedAgent(agent: SortedAgent): SortedAgent {
  const inferredCanonicalNode = canonicalAgentFor(agent.node)
  const legacyCompatibilityOnly = agent.legacyCompatibilityOnly === true
    || agent.activeNode === false
    || Boolean(inferredCanonicalNode)
  return {
    ...agent,
    legacyCompatibilityOnly,
    canonicalNode: agent.canonicalNode || inferredCanonicalNode,
    activeNode: legacyCompatibilityOnly ? false : agent.activeNode ?? true,
  }
}

function isDashboardCompatibilityOnly(agent: SortedAgent) {
  return agent.legacyCompatibilityOnly === true || agent.activeNode === false
}

function dashboardAgentOrder(agent: SortedAgent) {
  const canonicalOrder = isDashboardCompatibilityOnly(agent) && agent.canonicalNode
    ? DAG_ORDER[agent.canonicalNode]
    : undefined
  return canonicalOrder ?? DAG_ORDER[agent.node] ?? 999
}

function buildSortedAgents(
  agentResults: AgentResult[] | undefined,
  nodes: AgentNode[],
): SortedAgent[] {
  if (agentResults && agentResults.length > 0) {
    const agents = agentResults.map((ar) => normalizeSortedAgent({
      node: ar.node,
      name: ar.name,
      status: ar.status,
      reason: ar.skipped_reason || ar.reasons[0] || '',
      isSkipped: ar.status === 'SKIPPED',
      isBlocked: ar.status === 'BLOCK' || ar.hard_stop,
      hardStop: ar.hard_stop,
      skippedReason: ar.skipped_reason,
      auditId: ar.audit_id,
      legacyCompatibilityOnly: ar.legacyCompatibilityOnly,
      canonicalNode: ar.canonicalNode,
      activeNode: ar.activeNode,
    }))
    agents.sort((a, b) => dashboardAgentOrder(a) - dashboardAgentOrder(b))
    return agents
  }
  const agents = nodes.map((node) => normalizeSortedAgent({
    node: node.id,
    name: node.name,
    status: node.status,
    reason: node.outputSummary || node.inputSummary || '',
    isSkipped: node.isSkipped,
    isBlocked: node.isBlocked,
    hardStop: false,
    skippedReason: undefined,
    auditId: node.auditId,
    legacyCompatibilityOnly: false,
    canonicalNode: undefined,
    activeNode: true,
  }))
  agents.sort((a, b) => dashboardAgentOrder(a) - dashboardAgentOrder(b))
  return agents
}

function numberValue(value: unknown) {
  if (typeof value === 'number' && Number.isFinite(value)) return value.toLocaleString()
  if (typeof value === 'string' && value.trim()) return value
  return 'N/A'
}

function compactMarketNumber(value: unknown) {
  const numeric = numericValue(value)
  if (numeric == null) return numberValue(value)
  if (Math.abs(numeric) >= 100000000) return `${(numeric / 100000000).toFixed(2)}亿`
  if (Math.abs(numeric) >= 10000) return `${(numeric / 10000).toFixed(1)}万`
  return Math.round(numeric).toLocaleString()
}

function numericValue(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string') {
    const normalized = Number(value.replace(/[% ,]/g, '').trim())
    if (Number.isFinite(normalized)) return normalized
  }
  return undefined
}

function percentValue(value: unknown) {
  const numeric = numericValue(value)
  if (numeric == null) return 'N/A'
  const percent = Math.abs(numeric) <= 1 ? numeric * 100 : numeric
  return `${percent.toFixed(1)}%`
}

function signedPercentValue(value: unknown) {
  const numeric = numericValue(value)
  if (numeric == null) return 'N/A'
  const percent = Math.abs(numeric) <= 1 ? numeric * 100 : numeric
  const sign = percent > 0 ? '+' : ''
  return `${sign}${percent.toFixed(1)}%`
}

function probabilityPercentNumber(value: unknown): number | null {
  const numeric = numericValue(value)
  if (numeric == null) return null
  return Math.abs(numeric) <= 1 ? numeric * 100 : numeric
}

function compactCount(value: unknown) {
  const numeric = numericValue(value)
  if (numeric == null) return '0'
  return Math.round(numeric).toLocaleString()
}

function regressionStatusLabel(status: unknown) {
  const raw = String(status || '').trim()
  if (!raw) return 'UNKNOWN'
  return raw.toUpperCase()
}

function regressionBadgeStatus(
  regression: { status?: unknown; regression_rate?: unknown; review_required_cases?: unknown } | undefined | null,
) {
  const status = regressionStatusLabel(regression?.status)
  const regressionRate = numericValue(regression?.regression_rate) ?? 0
  const reviewRequiredCases = numericValue(regression?.review_required_cases) ?? 0
  if (['FAIL', 'FAILED', 'REGRESSED', 'REGRESSION', 'BLOCKED'].includes(status)) return 'FAIL'
  if (['REVIEW', 'WARN', 'WARNING'].includes(status)) return 'WARN'
  if (['PASS', 'PASSED', 'OK', 'HEALTHY'].includes(status) && regressionRate <= 0 && reviewRequiredCases <= 0) return 'PASS'
  if (reviewRequiredCases > 0 || regressionRate > 0) return 'WARN'
  return status
}

function latestKnowledgeRegressionVersion(versions: KnowledgeVersionItem[]) {
  return versions.find((version) => hasPostPublishRegressionReport(version.post_publish_regression))
}

function hasPostPublishRegressionReport(
  report: KnowledgeVersionItem['post_publish_regression'] | undefined,
): report is PostPublishRegressionReport {
  return Boolean(report?.report_id && report?.status)
}

function KnowledgeRegressionCard({
  loading,
  error,
  version,
  regression,
  affectedModules,
  warnings,
}: {
  loading: boolean
  error: string | null
  version?: KnowledgeVersionItem
  regression?: PostPublishRegressionReport | null
  affectedModules: string[]
  warnings: string[]
}) {
  const qualityPolicy = regression?.case_set_quality_policy
  const qualityRemediation = qualityPolicy?.remediation
  const qualityNextAction = Array.isArray(qualityRemediation?.next_actions)
    ? qualityRemediation.next_actions.map((item) => String(item)).filter(Boolean)[0]
    : ''
  const knowledgeImpact = regression?.knowledge_impact

  return (
    <Card
      title="知识版本回归"
      action={
        regression ? (
          <Badge status={regressionBadgeStatus(regression)}>
            {regressionStatusLabel(regression.status)}
          </Badge>
        ) : undefined
      }
    >
      <div data-testid="dashboard-knowledge-regression">
        {loading ? (
          <div role="status" className="grid gap-4 xl:grid-cols-[0.72fr_0.28fr]">
            <span className="sr-only">正在读取知识版本回归摘要...</span>
            <div>
              <div className="mb-3 flex flex-wrap items-center gap-2">
                <Skeleton className="h-3 w-16" />
                <Skeleton className="h-3 w-32" />
              </div>
              <div className="grid gap-3 sm:grid-cols-3">
                {Array.from({ length: 3 }).map((_, index) => (
                  <div key={index} className="rounded-md border border-slate-200 bg-slate-50 p-3">
                    <Skeleton className="h-3 w-20" />
                    <Skeleton className="mt-2 h-7 w-16" />
                  </div>
                ))}
              </div>
              <Skeleton className="mt-3 h-4 w-full" />
            </div>
            <div className="space-y-2 rounded-md border border-slate-200 bg-slate-50 p-3">
              <Skeleton className="h-3 w-full" />
              <Skeleton className="h-3 w-5/6" />
              <Skeleton className="h-3 w-2/3" />
            </div>
          </div>
        ) : error ? (
          <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-500">
            {error}
          </div>
        ) : !regression ? (
          <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-500">
            暂无已发布知识版本回归摘要。
          </div>
        ) : (
          <div className="grid gap-4 xl:grid-cols-[0.72fr_0.28fr]">
            <div>
              <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                <span>{version?.version_label || `v${version?.version_number ?? '-'}`}</span>
                {regression.generated_at != null && String(regression.generated_at).trim() !== '' ? (
                  <span>generated {formatDateTime(String(regression.generated_at))}</span>
                ) : null}
                {regression.active_patch_count != null && <span>{compactCount(regression.active_patch_count)} active patches</span>}
              </div>
              <div className="grid gap-3 sm:grid-cols-3">
                <div className="rounded-md border border-emerald-200 bg-emerald-50/70 p-3">
                  <div className="text-xs font-medium text-emerald-700">改善率 / Improvement</div>
                  <div className="mt-1 text-2xl font-semibold text-emerald-900">{percentValue(regression.improvement_rate)}</div>
                </div>
                <div className="rounded-md border border-red-200 bg-red-50/70 p-3">
                  <div className="text-xs font-medium text-red-700">退化率 / Regression</div>
                  <div className="mt-1 text-2xl font-semibold text-red-900">{percentValue(regression.regression_rate)}</div>
                </div>
                <div className="rounded-md border border-amber-200 bg-amber-50/70 p-3">
                  <div className="text-xs font-medium text-amber-700">待复核 / Review required</div>
                  <div className="mt-1 text-2xl font-semibold text-amber-900">{compactCount(regression.review_required_cases)}</div>
                  <div className="mt-1 text-xs text-amber-700">{percentValue(regression.review_required_rate)} of cases</div>
                </div>
              </div>
              {regression.summary ? (
                <div className="mt-3 line-clamp-2 text-sm leading-6 text-slate-600">{String(regression.summary)}</div>
              ) : null}
            </div>
            <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
              <div className="grid gap-2 text-xs text-slate-600">
                <div className="flex items-center justify-between gap-3">
                  <span>代表案例</span>
                  <span className="font-semibold text-slate-900">{compactCount(regression.representative_case_count)}</span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span>影响模块</span>
                  <span className="font-semibold text-slate-900">{affectedModules.length}</span>
                </div>
              </div>
              {qualityPolicy ? (
                <div data-testid="dashboard-knowledge-regression-quality-policy" className="mt-3 rounded border border-slate-200 bg-white px-2 py-2 text-[11px] leading-5 text-slate-600">
                  <div className="flex items-center justify-between gap-3">
                    <span>案例集策略</span>
                    <span className="font-semibold text-slate-900">{qualityPolicy.mode || 'UNKNOWN'}</span>
                  </div>
                  <div className="mt-1 text-slate-500">
                    动作：{qualityPolicy.action || 'N/A'}；阻断：{qualityPolicy.blocking ? '是' : '否'}；覆盖：{qualityPolicy.override_required ? '需要' : '不需要'}
                  </div>
                  {qualityRemediation ? (
                    <div data-testid="dashboard-knowledge-regression-remediation" className="mt-2 rounded bg-amber-50 px-2 py-1 text-amber-800">
                      {qualityRemediation.status || 'UNKNOWN'} / {qualityRemediation.owner || 'case_library_reviewer'}
                      {qualityNextAction ? <span className="block text-[10px] leading-4">{qualityNextAction}</span> : null}
                    </div>
                  ) : null}
                </div>
              ) : null}
              {knowledgeImpact ? (
                <div data-testid="dashboard-knowledge-regression-impact" className="mt-3 rounded border border-slate-200 bg-white px-2 py-2 text-[11px] leading-5 text-slate-600">
                  <div className="flex items-center justify-between gap-3">
                    <span>知识影响</span>
                    <span className="font-semibold text-slate-900">{knowledgeImpact.status || 'UNKNOWN'}</span>
                  </div>
                  <div className="mt-1 text-slate-500">
                    Risk: {knowledgeImpact.risk_level || 'UNKNOWN'}; mode: {knowledgeImpact.mode || 'OBSERVATION_ONLY'}; auto block: {knowledgeImpact.auto_blocks_promotion ? 'yes' : 'no'}
                  </div>
                  <div className="mt-1 text-slate-500">
                    动作：{knowledgeImpact.action || 'monitor_post_publish_impact'}；净改善：{compactCount(knowledgeImpact.net_improvement_cases)}
                  </div>
                </div>
              ) : null}
              {affectedModules.length > 0 ? (
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {affectedModules.slice(0, 4).map((module) => (
                    <span key={module} className="rounded border border-slate-200 bg-white px-2 py-0.5 text-[11px] text-slate-600">
                      {module}
                    </span>
                  ))}
                </div>
              ) : null}
              {warnings.length > 0 ? (
                <div className="mt-3 space-y-1">
                  {warnings.slice(0, 2).map((warning) => (
                    <div key={warning} className="line-clamp-2 rounded bg-amber-100 px-2 py-1 text-[11px] leading-4 text-amber-800">
                      {warning}
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          </div>
        )}
      </div>
    </Card>
  )
}

function productionHealthWindow24h(health?: ProductionHealth | null) {
  if (!health?.windows) return null
  return health.windows['24h'] ?? Object.values(health.windows).filter(Boolean)[0] ?? null
}

function llmHealthStatus(metric: ProductionHealthMetric | undefined, loading: boolean, error: string | null) {
  if (loading) return 'WAIT'
  if (error) return 'WARN'
  const total = numericValue(metric?.total) ?? 0
  const failed = numericValue(metric?.failed) ?? 0
  const failureRate = numericValue(metric?.failureRate) ?? 0
  if (total <= 0) return 'WAIT'
  if (failed <= 0) return 'PASS'
  return failureRate >= 0.2 ? 'FAIL' : 'WARN'
}

function topLlmFailureReason(metric: ProductionHealthMetric | undefined) {
  const reason = metric?.failureReasons?.find((item) => item?.reason)?.reason
    ?? metric?.sampleFailures?.find((item) => item?.reason)?.reason
  return reason || '该窗口内没有失败的实时调用'
}

function LlmLiveCallHealthCard({
  health,
  loading,
  error,
}: {
  health: ProductionHealth | null
  loading: boolean
  error: string | null
}) {
  const window24h = productionHealthWindow24h(health)
  const metric = window24h?.llmCallFailureRate
  const total = numericValue(metric?.total) ?? 0
  const failed = numericValue(metric?.failed) ?? 0
  const succeeded = numericValue(metric?.succeeded) ?? Math.max(0, total - failed)
  const skipped = numericValue(metric?.skipped) ?? 0
  const totalTokens = numericValue(metric?.totalTokens) ?? 0
  const successRate = numericValue(metric?.successRate) ?? (total > 0 ? succeeded / total : null)
  const status = llmHealthStatus(metric, loading, error)
  const topReason = error || topLlmFailureReason(metric)
  const trend = health?.trend
  const longTrend = health?.longTrend
  const baselineWindow = trend?.baselineWindow || '7d'
  const longBaselineWindow = longTrend?.baselineWindow || '30d'

  return (
    <Card
      title="LLM 实时调用健康"
      action={<Badge status={status}>{loading ? 'LOADING' : status}</Badge>}
    >
      <div data-testid="dashboard-llm-live-call-health" className="grid gap-4 lg:grid-cols-[minmax(0,0.7fr)_minmax(260px,0.3fr)]">
        <div className="grid gap-3 sm:grid-cols-4">
          <CompactMetric testId="dashboard-llm-live-call-success-rate" label="24h 成功率" value={loading ? <Skeleton className="h-6 w-16" /> : percentValue(successRate)} helper={`${compactCount(succeeded)}/${compactCount(total)} 已完成`} />
          <CompactMetric label="24h 失败率" value={loading ? <Skeleton className="h-6 w-16" /> : percentValue(metric?.failureRate)} helper={`${compactCount(failed)} 失败`} />
          <CompactMetric label="跳过" value={loading ? <Skeleton className="h-6 w-12" /> : compactCount(skipped)} helper="已降级或未请求" />
          <CompactMetric label="Token" value={loading ? <Skeleton className="h-6 w-12" /> : compactCount(totalTokens)} helper="提供方上报" />
        </div>
        <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs leading-5 text-slate-600">
          <div className="flex items-center justify-between gap-3">
            <span className="font-medium uppercase text-slate-500">首要失败原因</span>
            <span className="font-semibold text-slate-900">{window24h?.window || '24h'}</span>
          </div>
          <div data-testid="dashboard-llm-live-call-failure-reason" className="mt-1 line-clamp-2 break-words text-sm font-semibold text-slate-900">
            {loading ? (
              <>
                <span className="sr-only">正在加载生产健康状态...</span>
                <Skeleton className="h-4 w-40" />
              </>
            ) : topReason}
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5 text-[11px] text-slate-500">
            <span className="rounded border border-slate-200 bg-white px-2 py-0.5">external calls: {health?.externalCalls ? 'yes' : 'no'}</span>
            <span className="rounded border border-slate-200 bg-white px-2 py-0.5">status: {health?.status || 'unknown'}</span>
          </div>
          <div data-testid="dashboard-llm-live-call-trend" className="mt-2 flex flex-wrap gap-1.5 text-[11px] text-slate-500">
            <span className="rounded border border-slate-200 bg-white px-2 py-0.5">vs {baselineWindow}</span>
            <span className="rounded border border-slate-200 bg-white px-2 py-0.5">success {signedPercentValue(trend?.llmSuccessRateDelta)}</span>
            <span className="rounded border border-slate-200 bg-white px-2 py-0.5">failure {signedPercentValue(trend?.llmFailureRateDelta)}</span>
            <span className="rounded border border-slate-200 bg-white px-2 py-0.5">long {longBaselineWindow} success {signedPercentValue(longTrend?.llmSuccessRateDelta)}</span>
            <span className="rounded border border-slate-200 bg-white px-2 py-0.5">long {longBaselineWindow} failure {signedPercentValue(longTrend?.llmFailureRateDelta)}</span>
          </div>
        </div>
      </div>
    </Card>
  )
}

const closedLoopTextLabels: Record<string, string> = {
  'Review evidence': '审核证据',
  'Review knowledge version': '审核知识版本',
  'Promote knowledge version': '发布知识版本',
  'No action required': '无需操作',
  'Knowledge version is review and cannot activate feedback acceptance.': '知识版本仍处于审核状态，不能激活反馈采纳。',
}

const closedLoopStepLabels: Record<string, string> = {
  portfolio: '持仓',
  run: '运行',
  signalops: 'SignalOps',
  backtest: '回测',
  research: '研究',
  knowledge: '知识',
  case: '案例',
  evaluation: '评估',
  knowledge_version: '知识版本',
}

function closedLoopText(value: unknown) {
  const text = String(value || '').trim()
  const backtestStrengthMatch = text.match(/^Backtest evidence strength is ([A-Z_]+); keep it as supporting evidence/i)
  if (backtestStrengthMatch) {
    return `回测证据强度为 ${backtestStrengthMatch[1].toUpperCase()}；仅作为支持材料，需先审核样本、数据源和样本外检查。`
  }
  if (text.includes('mock or fallback market data')) {
    return '回测使用 mock 或 fallback 行情数据，需先审核证据。'
  }
  return closedLoopTextLabels[text] ?? text
}

function dashboardReviewStrength(value?: string | null) {
  const normalized = String(value || '').trim().toUpperCase()
  if (['RESEARCH_GRADE', 'PRIMARY_EVIDENCE_READY'].includes(normalized)) return 'MEDIUM'
  if (['STRONG', 'HIGH', 'PRIMARY', 'PRIMARY_EVIDENCE', 'PASS', 'READY'].includes(normalized)) return 'MEDIUM'
  if (['UNKNOWN', 'SUPPORTING_ONLY', 'WEAK', 'WARN', 'WARNING', 'REVIEW', 'REVIEW_ONLY'].includes(normalized)) return 'LOW'
  if (['MEDIUM', 'LOW', 'MISSING', 'PENDING'].includes(normalized)) return normalized
  return 'LOW'
}

function ResearchClosedLoopEntryCard({
  creating,
  error,
  result,
  canCreate,
  disabledReason,
  operatorRole,
  onCreate,
}: {
  creating: boolean
  error: string | null
  result: P2ClosedLoopSampleResponse | null
  canCreate: boolean
  disabledReason: string
  operatorRole: string
  onCreate: () => void
}) {
  const knowledgeVersionStatus = result?.knowledge_version_status
    ? String(result.knowledge_version_status).toUpperCase()
    : ''
  const ids = [
    ['Run', result?.run_id],
    ['SignalOps', result?.signal_id],
    ['Backtest', result?.backtest_run_id],
    ['Research', result?.iteration_id],
    ['Case', result?.case_id],
    ['Knowledge', result?.knowledge_item_id],
    ['Evaluation', result?.evaluation_id],
    ['Version', result?.knowledge_version_id],
  ].filter(([, value]) => Boolean(value))
  const actionableStep = result?.steps.find(
    (step) => step.missing_items.length > 0 || step.status !== 'PASS',
  )
  const lastStep = result?.steps.length ? result.steps[result.steps.length - 1] : undefined
  const evidenceStrength = dashboardReviewStrength(actionableStep?.evidence_strength || lastStep?.evidence_strength)
  const blocker = actionableStep?.missing_items[0] || result?.warnings?.[0] || '无阻塞；等待人工复核。'
  const nextAction = actionableStep?.next_action_label || (actionableStep ? 'Review evidence' : 'No action required')
  const currentStepLabel = actionableStep
    ? closedLoopStepLabels[actionableStep.key] ?? closedLoopText(actionableStep.label)
    : '全链路'
  const currentStepStatus = actionableStep?.status ?? (result ? 'PASS' : 'WAIT')
  const currentStepRef = actionableStep?.ref_id ? ` · ${actionableStep.ref_id}` : ''
  const currentStepText = `${currentStepLabel} · ${currentStepStatus}${currentStepRef}`

  return (
    <Card
      title="研究实验室闭环样例"
      action={<Badge status={result?.simulation_only === true && result?.is_real_trade === false ? 'PASS' : 'WAIT'}>{result ? 'SIMULATION_ONLY' : 'READY'}</Badge>}
    >
      <div data-testid="dashboard-research-closed-loop-entry" className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto]">
        <div className="min-w-0">
          <div className="text-sm leading-6 text-slate-600">
            {'从 Dashboard 重建可复核的组合 -> 运行 -> SignalOps -> 回测 -> 研究 -> 案例 -> 知识 -> 评估样例链。'}
          </div>
          <div className="mt-2 flex flex-wrap gap-2 text-xs text-slate-500">
            <span className="rounded-md border border-slate-200 bg-slate-50 px-2 py-1">simulation_only=true</span>
            <span className="rounded-md border border-slate-200 bg-slate-50 px-2 py-1">is_real_trade=false</span>
            <span className="rounded-md border border-slate-200 bg-slate-50 px-2 py-1">研究实验室 canonical 路径</span>
            <span data-testid="dashboard-research-closed-loop-role" className="rounded-md border border-slate-200 bg-slate-50 px-2 py-1">
              角色：{operatorRole}；写入：{canCreate ? 'researcher+' : '已阻断 / blocked'}
            </span>
          </div>
          {disabledReason ? (
            <div data-testid="dashboard-research-closed-loop-disabled-reason" className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
              {disabledReason}
            </div>
          ) : null}
          {error ? (
            <div data-testid="dashboard-research-closed-loop-error" className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {error}
            </div>
          ) : null}
          {result ? (
            <div data-testid="dashboard-research-closed-loop-result" className="mt-3 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2">
              <div className="text-xs font-semibold text-emerald-800">样例链已创建</div>
              <div className="mt-2 grid gap-1 text-xs text-emerald-900 sm:grid-cols-2 xl:grid-cols-4">
                {ids.map(([label, value]) => (
                  <div key={label} className="truncate" title={String(value)}>
                    <span className="font-semibold">{label}:</span> {String(value)}
                  </div>
                ))}
              </div>
              {result.knowledge_version_id ? (
                <div data-testid="dashboard-research-closed-loop-version-status" className="mt-2 flex flex-wrap items-center gap-2 text-xs text-emerald-900">
                  <span className="font-semibold">知识版本状态：</span>
                  <Badge status={knowledgeVersionStatus === 'REVIEW' ? 'WARN' : 'PASS'}>{knowledgeVersionStatus || 'UNKNOWN'}</Badge>
                  <span className="text-emerald-800">review-only；不会激活样例补丁。</span>
                </div>
              ) : null}
              <div data-testid="dashboard-research-closed-loop-governance" className="mt-2 grid gap-2 text-xs text-emerald-950 sm:grid-cols-2 xl:grid-cols-4">
                <div className="rounded border border-emerald-200 bg-white/70 px-2 py-1.5">
                  <div className="font-semibold text-emerald-700">当前环节</div>
                  <div
                    data-testid="dashboard-research-closed-loop-current-step"
                    className="mt-0.5 break-words"
                    title={currentStepText}
                  >
                    {currentStepText}
                  </div>
                </div>
                <div className="rounded border border-emerald-200 bg-white/70 px-2 py-1.5">
                  <div className="font-semibold text-emerald-700">证据强度</div>
                  <div data-testid="dashboard-research-closed-loop-evidence-strength" className="mt-0.5">{evidenceStrength}</div>
                </div>
                <div className="rounded border border-emerald-200 bg-white/70 px-2 py-1.5">
                  <div className="font-semibold text-emerald-700">阻塞原因</div>
                  <div data-testid="dashboard-research-closed-loop-blocker" className="mt-0.5 line-clamp-2">{closedLoopText(blocker)}</div>
                </div>
                <div className="rounded border border-emerald-200 bg-white/70 px-2 py-1.5">
                  <div className="font-semibold text-emerald-700">下一步</div>
                  <div data-testid="dashboard-research-closed-loop-next-action" className="mt-0.5">{closedLoopText(nextAction)}</div>
                </div>
              </div>
              {result.warnings?.length ? (
                <div className="mt-2 line-clamp-2 text-xs text-amber-800">{result.warnings.slice(0, 2).map(closedLoopText).join(' / ')}</div>
              ) : null}
            </div>
          ) : null}
        </div>
        <div className="flex flex-col gap-2 sm:flex-row lg:flex-col">
          <button
            type="button"
            data-testid="dashboard-create-closed-loop-sample"
            onClick={onCreate}
            disabled={creating || !canCreate}
            title={disabledReason || undefined}
            className="inline-flex items-center justify-center gap-2 rounded-md bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
          >
            <RefreshCw size={15} />
            {creating ? 'Creating...' : 'Rebuild sample chain'}
          </button>
          <a
            href="/research-lab/research"
            data-testid="dashboard-open-research-lab"
            className="inline-flex items-center justify-center gap-2 rounded-md border border-cyan-200 bg-cyan-50 px-4 py-2 text-sm font-semibold text-cyan-800 transition hover:bg-cyan-100"
          >
            <ArrowRight size={15} />
            打开研究实验室
          </a>
        </div>
      </div>
    </Card>
  )
}

function tradeDateValue(value?: string | null) {
  const raw = String(value || '').trim()
  if (!raw) return ''
  if (/^\d{8}$/.test(raw)) return `${raw.slice(0, 4)}-${raw.slice(4, 6)}-${raw.slice(6, 8)}`
  if (/^\d{4}-\d{2}-\d{2}/.test(raw)) return raw.slice(0, 10)
  return raw
}

function stringValue(value: unknown) {
  if (typeof value === 'string' && value.trim()) return value.trim()
  if (typeof value === 'number' && Number.isFinite(value)) return String(value)
  return ''
}

function bottomCurrentPrediction(bottom?: BottomResearchResult | null) {
  if (bottom?.currentPrediction?.tradeDate) return bottom.currentPrediction
  const tradeDate = tradeDateValue(stringValue(bottom?.provenance?.lastTradeDate))
  const hasProbability =
    typeof bottom?.bottomRepairProbability === 'number' ||
    typeof bottom?.breakdownRiskProbability === 'number'
  if (!tradeDate || !hasProbability) return null
  return {
    tradeDate,
    bottomRepairProbability: bottom?.bottomRepairProbability,
    breakdownRiskProbability: bottom?.breakdownRiskProbability,
    regimeState: bottom?.regimeState,
    labelStatus: 'UNLABELED_NOWCAST_LEGACY',
    horizonDays: Number(bottom?.config?.horizon_days || 0),
    simulation_only: true,
    is_real_trade: false,
  }
}

function isLaterTradeDate(value?: string | null, baseline?: string | null) {
  const current = tradeDateValue(value)
  const previous = tradeDateValue(baseline)
  return Boolean(current && previous && current > previous)
}

function bottomProbabilityWindow(bottom?: BottomResearchResult | null, runUpdatedAt?: string) {
  const series = (bottom?.probabilitySeries || [])
    .filter((item) => typeof item.bottomRepairProbability === 'number' || typeof item.breakdownRiskProbability === 'number')
  const first = series[0]
  const last = series[series.length - 1]
  const current = bottomCurrentPrediction(bottom)
  const currentTradeDate = tradeDateValue(current?.tradeDate)
  const lastHistoricalTradeDate = tradeDateValue(last?.tradeDate)
  const sourceLastTradeDate = tradeDateValue(stringValue(bottom?.provenance?.lastTradeDate))
  const generatedAt = stringValue(bottom?.provenance?.generatedAt) || runUpdatedAt || ''
  const horizonDays = numericValue(current?.horizonDays) ?? numericValue(bottom?.config?.horizon_days) ?? 0
  return {
    sampleCount: series.length,
    firstTradeDate: tradeDateValue(first?.tradeDate),
    lastHistoricalTradeDate,
    labelWindowEnd: tradeDateValue(last?.labelWindowEnd),
    sourceLastTradeDate,
    currentTradeDate: currentTradeDate || sourceLastTradeDate,
    generatedAt,
    horizonDays,
    hasNowcast: isLaterTradeDate(currentTradeDate || sourceLastTradeDate, lastHistoricalTradeDate),
  }
}

function bottomTrendLineData(bottom?: BottomResearchResult | null) {
  const historical = (bottom?.probabilitySeries || [])
    .filter((item) => (
      typeof item.predictionUpProbability === 'number'
      || typeof item.predictionDownProbability === 'number'
      || typeof item.bottomRepairProbability === 'number'
      || typeof item.breakdownRiskProbability === 'number'
    ))
    .slice(-48)
    .map((item) => {
      const fullDate = tradeDateValue(item.tradeDate)
      const fallback = fallbackTrendProbabilities(item.bottomRepairProbability, item.breakdownRiskProbability)
      return {
        date: fullDate ? fullDate.slice(5) : '',
        fullDate,
        historicalUp: probabilityPercentNumber(item.predictionUpProbability ?? fallback?.up),
        historicalDown: probabilityPercentNumber(item.predictionDownProbability ?? fallback?.down),
        actualUp: probabilityPercentNumber(item.actualUpLabel),
        actualDown: probabilityPercentNumber(item.actualDownLabel),
        nowcastUp: null as number | null,
        nowcastDown: null as number | null,
      }
    })
  const current = bottomCurrentPrediction(bottom)
  const latest = historical[historical.length - 1]
  if (!latest || !current || !isLaterTradeDate(current.tradeDate, latest.fullDate)) {
    return historical
  }
  const currentDate = tradeDateValue(current.tradeDate)
  return [
    ...historical.slice(0, -1),
    {
      ...latest,
      nowcastUp: latest.historicalUp,
      nowcastDown: latest.historicalDown,
    },
    {
      date: currentDate ? currentDate.slice(5) : '',
      fullDate: currentDate,
      historicalUp: null,
      historicalDown: null,
      actualUp: null,
      actualDown: null,
      nowcastUp: probabilityPercentNumber(fallbackTrendProbabilities(current.bottomRepairProbability, current.breakdownRiskProbability)?.up),
      nowcastDown: probabilityPercentNumber(fallbackTrendProbabilities(current.bottomRepairProbability, current.breakdownRiskProbability)?.down),
    },
  ]
}

function bottomResearchStatusBadge(status?: string) {
  const value = String(status || '').toUpperCase()
  if (value === 'PASS') return 'PASS'
  if (value === 'WARN' || value === 'SKIPPED') return 'WARN'
  if (value === 'FAIL' || value === 'FAILED') return 'FAIL'
  return 'WAIT'
}

function bottomResearchRegimeLabel(value?: string) {
  const map: Record<string, string> = {
    BOTTOM_REPAIR_ZONE: 'MFE有利区间',
    BOTTOM_REPAIR_WATCH: 'MFE观察区',
    BREAKDOWN_RISK: 'MAE跌破风险',
    SUPPORTING_ONLY: '仅作支持证据',
  }
  return map[String(value || '').toUpperCase()] ?? (value || '未识别')
}

function trendBiasLabel(value?: string) {
  const map: Record<string, string> = {
    UP: 'MFE偏有利',
    SIDEWAYS: '震荡观察',
    DOWN: 'MAE风险偏高',
    INSUFFICIENT_DATA: '样本不足',
  }
  return map[String(value || '').toUpperCase()] ?? (value || '未识别')
}

function horizonAlignmentLabel(value?: string) {
  const map: Record<string, string> = {
    ALIGNED: '周期一致',
    MIXED: '周期混合',
    CONFLICT: '周期冲突',
    INSUFFICIENT_DATA: '样本不足',
  }
  return map[String(value || '').toUpperCase()] ?? (value || '未识别')
}

function qiamAdjustmentLabel(adjustment?: AnalysisRun['qiam']['bottomResearchAdjustment']) {
  if (!adjustment?.observed) return '未观察到 MFE/MAE 校准'
  const direction = String(adjustment.direction || 'NONE').toUpperCase()
  if (adjustment.applied && direction === 'UP') return 'QIAM 上调一档'
  if (adjustment.applied && direction === 'DOWN') return 'QIAM 下调一档'
  if (direction === 'UP' && adjustment.blockedReasons?.length) return '正向校准被门禁拦截'
  if (direction === 'DOWN') return '负向校准待确认'
  return 'QIAM 保持不变'
}

function fallbackTrendProbabilities(repair?: number | null, breakdown?: number | null) {
  const repairValue = numericValue(repair)
  const breakdownValue = numericValue(breakdown)
  if (repairValue == null || breakdownValue == null) return undefined
  const up = Math.max(0.05, 0.25 + repairValue * 0.55 - breakdownValue * 0.25)
  const down = Math.max(0.05, 0.20 + breakdownValue * 0.65 - repairValue * 0.20)
  const sideways = Math.max(0.05, 0.35 + Math.max(0, 0.50 - Math.abs(repairValue - breakdownValue)) * 0.20)
  const total = up + sideways + down
  return {
    up: up / total,
    sideways: sideways / total,
    down: down / total,
  }
}

function bottomHorizonForecasts(bottom?: BottomResearchResult | null) {
  const forecasts = (bottom?.horizonForecasts || [])
    .filter((item) => typeof item?.horizonDays === 'number')
    .slice()
    .sort((left, right) => left.horizonDays - right.horizonDays)
  if (forecasts.length > 0) return forecasts
  const current = bottomCurrentPrediction(bottom)
  if (!bottom || !current) return []
  const repair = current.bottomRepairProbability ?? bottom.bottomRepairProbability
  const breakdown = current.breakdownRiskProbability ?? bottom.breakdownRiskProbability
  return [
    {
      horizonDays: numericValue(current.horizonDays) ?? numericValue(bottom.config?.horizon_days) ?? 20,
      status: bottom.status,
      bottomRepairProbability: repair,
      breakdownRiskProbability: breakdown,
      trendProbabilities: fallbackTrendProbabilities(repair, breakdown),
      trendBias: current.regimeState === 'BREAKDOWN_RISK' ? 'DOWN' : current.regimeState === 'BOTTOM_REPAIR_ZONE' ? 'UP' : 'SIDEWAYS',
      confidence: undefined,
      sampleCount: bottom.modelDiagnostics?.sampleCount,
      evidenceGrade: bottom.modelDiagnostics?.evidenceGrade,
      currentPrediction: current,
    },
  ]
}

function bottomEvidenceConflict(run: AnalysisRun, bottom?: BottomResearchResult | null) {
  if (!bottom) return false
  const current = bottomCurrentPrediction(bottom)
  const repair = numericValue(current?.bottomRepairProbability ?? bottom.bottomRepairProbability)
  const threshold = numericValue(bottom.config?.repair_probability_threshold) ?? 0.6
  const technicalBias = String(run.technicalKline?.technicalBias || '').toUpperCase()
  const qiamFinal = String(run.qiam?.finalBuySuitability || '').toUpperCase()
  return Boolean(
    bottom.trendSynthesis?.evidenceConflict ||
    (repair != null && repair >= threshold && technicalBias === 'BEARISH') ||
    (repair != null && repair >= threshold && ['REVIEW_ONLY', 'BLOCK_BUY'].includes(qiamFinal)),
  )
}

function bottomResearchConclusion(run: AnalysisRun, bottom?: BottomResearchResult | null) {
  if (!bottom) return '暂无MFE/MAE路径研究输出'
  const status = String(bottom.status || '').toUpperCase()
  if (status === 'SKIPPED') return 'MFE/MAE样本或数据不足，暂不形成概率结论'
  if (bottomEvidenceConflict(run, bottom)) return '证据冲突，维持观察'
  if (bottom.trendSynthesis?.mainConclusion) return bottom.trendSynthesis.mainConclusion
  const current = bottomCurrentPrediction(bottom)
  const repair = numericValue(current?.bottomRepairProbability ?? bottom.bottomRepairProbability)
  const breakdown = numericValue(current?.breakdownRiskProbability ?? bottom.breakdownRiskProbability)
  const threshold = numericValue(bottom.config?.repair_probability_threshold) ?? 0.6
  if (repair != null && repair >= threshold && (breakdown == null || breakdown < 0.35)) {
    return 'MFE有利概率占优，但仍仅作为研究证据'
  }
  if (repair != null && repair >= threshold) {
    return 'MFE有利概率偏高，需结合MAE风险复核'
  }
  if (breakdown != null && breakdown >= 0.5) {
    return 'MAE跌破风险仍高，维持观察与复核'
  }
  return 'MFE/MAE路径研究暂未改变最终动作'
}

function CompactMetric({
  label,
  value,
  helper,
  testId,
}: {
  label: string
  value: React.ReactNode
  helper?: React.ReactNode
  testId?: string
}) {
  return (
    <div data-testid={testId} className="min-w-0">
      <MetricTile
        label={label}
        value={value}
        helper={helper}
        className="!rounded-md !bg-[#f8fafd] !px-2.5 !py-1.5 !shadow-none"
      />
    </div>
  )
}

function BottomResearchConclusionCard({
  run,
  conclusionInsights,
}: {
  run: AnalysisRun
  conclusionInsights: ReturnType<typeof buildConclusionInsights>
}) {
  const bottom = run.mfeMaeResearch ?? run.bottomResearch
  const current = bottomCurrentPrediction(bottom)
  const window = bottomProbabilityWindow(bottom, run.updatedAt)
  const repairProbability = current?.bottomRepairProbability ?? bottom?.bottomRepairProbability
  const breakdownProbability = current?.breakdownRiskProbability ?? bottom?.breakdownRiskProbability
  const threshold = numericValue(bottom?.config?.repair_probability_threshold)
  const sampleCount = numericValue(bottom?.modelDiagnostics?.sampleCount) ?? window.sampleCount
  const compactChecks = conclusionInsights.slice(0, 4)
  const forecasts = bottomHorizonForecasts(bottom)
  const adjustment = run.qiam?.mfeMaePathResearchAdjustment ?? run.qiam?.bottomResearchAdjustment ?? bottom?.qiamAdjustmentPreview
  const conflict = bottomEvidenceConflict(run, bottom)
  const technicalBias = String(run.technicalKline?.technicalBias || '').toUpperCase()
  const synthesis = bottom?.trendSynthesis
  const trendLineData = bottomTrendLineData(bottom)

  return (
    <Card
      title="未来趋势综合研判"
      action={<Badge status={conflict ? 'WARN' : bottomResearchStatusBadge(bottom?.status)}>{conflict ? 'CONFLICT' : bottom?.status || 'WAIT'}</Badge>}
    >
      {!bottom ? (
        <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-500">
          当前分析尚未生成 MFE/MAE 路径研究输出。
        </div>
      ) : (
        <div className="min-w-0">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="break-words text-lg font-semibold leading-7 text-slate-950">
                {bottomResearchConclusion(run, bottom)}
              </div>
              <div className="mt-1 text-xs leading-5 text-slate-500">
                {horizonAlignmentLabel(synthesis?.horizonAlignment)} · {bottomResearchRegimeLabel(current?.regimeState ?? bottom.regimeState)} · {qiamAdjustmentLabel(adjustment)}
              </div>
            </div>
            <a
              href="/quant-core"
              className="inline-flex h-8 items-center rounded-md border border-slate-300 bg-white px-3 text-xs font-semibold text-slate-700 transition hover:bg-slate-50"
            >
              查看概率路径
            </a>
          </div>

          <div className="mt-3 grid gap-2 md:grid-cols-3">
            {forecasts.slice(0, 3).map((forecast) => (
              <div key={forecast.horizonDays} className="min-w-0 rounded-md border border-slate-200 bg-white px-3 py-2">
                <div className="flex items-center justify-between gap-2">
                  <div className="text-xs font-semibold text-slate-900">{forecast.horizonDays}日趋势</div>
                  <Badge status={String(forecast.trendBias || '').toUpperCase() === 'DOWN' ? 'WARN' : forecast.status === 'READY' ? 'PASS' : 'WARN'}>
                    {trendBiasLabel(forecast.trendBias)}
                  </Badge>
                </div>
                <div className="mt-2 grid grid-cols-3 gap-2 text-xs">
                  <div>
                    <div className="text-slate-500">上涨</div>
                    <div className="mt-0.5 font-semibold text-slate-950">{percentValue(forecast.trendProbabilities?.up)}</div>
                  </div>
                  <div>
                    <div className="text-slate-500">MFE</div>
                    <div className="mt-0.5 font-semibold text-slate-950">{percentValue(forecast.bottomRepairProbability)}</div>
                  </div>
                  <div>
                    <div className="text-slate-500">MAE</div>
                    <div className="mt-0.5 font-semibold text-slate-950">{percentValue(forecast.breakdownRiskProbability)}</div>
                  </div>
                </div>
                <div className="mt-2 text-[11px] leading-4 text-slate-500">
                  置信 {forecast.confidence == null ? '-' : percentValue(forecast.confidence)} · 样本 {compactCount(forecast.sampleCount)}
                </div>
              </div>
            ))}
            {forecasts.length === 0 ? (
              <>
                <CompactMetric
                  label="MFE有利概率"
                  value={percentValue(repairProbability)}
                  helper={threshold != null ? `阈值 ${percentValue(threshold)}` : '最新未标注预测'}
                />
                <CompactMetric
                  label="MAE跌破风险"
                  value={percentValue(breakdownProbability)}
                  helper="越高越需要继续等待"
                />
                <CompactMetric
                  label="样本 / 窗口"
                  value={sampleCount ? `${compactCount(sampleCount)} / ${compactCount(window.horizonDays)}日` : `${compactCount(window.horizonDays)}日`}
                  helper="历史标签窗口完整后才进入可回测线"
                />
              </>
            ) : null}
          </div>

          {trendLineData.length > 1 ? (
            <div className="mt-3 rounded-md border border-slate-200 bg-white px-3 py-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="text-xs font-semibold text-slate-900">历史预测概率 / 实际涨跌校正依据</div>
                <div className="flex flex-wrap items-center gap-3 text-[11px] text-slate-500">
                  <span className="inline-flex items-center gap-1">
                    <span className="h-0.5 w-5 rounded-full bg-teal-700" />
                    预测上涨
                  </span>
                  <span className="inline-flex items-center gap-1">
                    <span className="h-0.5 w-5 rounded-full bg-red-600" />
                    预测下跌
                  </span>
                  <span className="inline-flex items-center gap-1">
                    <span className="h-0.5 w-5 rounded-full border-t-2 border-dashed border-slate-500" />
                    实际标签
                  </span>
                </div>
              </div>
              <div className="mt-2 h-40">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={trendLineData} margin={{ top: 8, right: 12, bottom: 0, left: -18 }}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="date" minTickGap={24} tick={{ fontSize: 10 }} />
                    <YAxis domain={[0, 100]} tick={{ fontSize: 10 }} tickFormatter={(value) => `${value}%`} width={42} />
                    <Tooltip
                      formatter={(value: unknown, name: unknown) => [
                        typeof value === 'number' ? `${value.toFixed(1)}%` : String(value ?? ''),
                        String(name ?? ''),
                      ]}
                      labelFormatter={(_, payload) => String(payload?.[0]?.payload?.fullDate || '')}
                    />
                    <Line
                      type="monotone"
                      dataKey="historicalUp"
                      name="历史预测上涨"
                      stroke="#0f766e"
                      strokeWidth={2}
                      dot={false}
                      isAnimationActive={false}
                    />
                    <Line
                      type="monotone"
                      dataKey="nowcastUp"
                      name="最新上涨概率"
                      stroke="#0f766e"
                      strokeDasharray="5 4"
                      strokeWidth={2}
                      dot={{ r: 3 }}
                      isAnimationActive={false}
                    />
                    <Line
                      type="monotone"
                      dataKey="historicalDown"
                      name="历史预测下跌"
                      stroke="#dc2626"
                      strokeWidth={2}
                      dot={false}
                      isAnimationActive={false}
                    />
                    <Line
                      type="monotone"
                      dataKey="nowcastDown"
                      name="最新下跌概率"
                      stroke="#dc2626"
                      strokeDasharray="5 4"
                      strokeWidth={2}
                      dot={{ r: 3 }}
                      isAnimationActive={false}
                    />
                    <Line type="stepAfter" dataKey="actualUp" name="实际上涨标签" stroke="#64748b" strokeWidth={1.5} strokeDasharray="3 3" dot={false} isAnimationActive={false} />
                    <Line type="stepAfter" dataKey="actualDown" name="实际下跌标签" stroke="#334155" strokeWidth={1.5} strokeDasharray="3 3" dot={false} isAnimationActive={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
          ) : null}

          <div className="mt-3 grid gap-2 text-xs leading-5 text-slate-600 md:grid-cols-4">
            <div className="rounded-md bg-slate-50 px-3 py-2">
              <span className="font-medium text-slate-900">可回测线</span>
              <div>{window.firstTradeDate || '-'} 至 {window.lastHistoricalTradeDate || '-'}</div>
            </div>
            <div className="rounded-md bg-blue-50 px-3 py-2 text-blue-900">
              <span className="font-medium">最新预测</span>
              <div>
                {window.currentTradeDate || '-'}
                {window.hasNowcast ? '（已对齐当前未标注样本）' : '（与历史线一致）'}
              </div>
            </div>
            <div className="rounded-md bg-amber-50 px-3 py-2 text-amber-900">
              <span className="font-medium">同步时间</span>
              <div>{window.generatedAt ? formatDateTime(window.generatedAt) : '待同步'}</div>
            </div>
            <div className={conflict ? 'rounded-md bg-red-50 px-3 py-2 text-red-900' : 'rounded-md bg-emerald-50 px-3 py-2 text-emerald-900'}>
              <span className="font-medium">证据关系</span>
              <div>{conflict ? `冲突：技术面 ${technicalBias || 'UNKNOWN'} / QIAM ${run.qiam?.finalBuySuitability}` : '未发现主要冲突'}</div>
            </div>
          </div>

          <div className="mt-3 grid gap-2 text-xs leading-5 md:grid-cols-3">
            <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-slate-600">
              <span className="font-medium text-slate-900">QIAM校准</span>
              <div>{qiamAdjustmentLabel(adjustment)}</div>
              {adjustment?.blockedReasons?.length ? (
                <div className="mt-1 line-clamp-1 text-slate-500">{adjustment.blockedReasons.join('、')}</div>
              ) : null}
            </div>
            <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-slate-600">
              <span className="font-medium text-slate-900">技术面约束</span>
              <div>{technicalBias ? technicalBias : 'UNKNOWN'} · {run.technicalKline?.confidence == null ? '置信未知' : `置信 ${percentValue(run.technicalKline.confidence)}`}</div>
            </div>
            <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-slate-600">
              <span className="font-medium text-slate-900">门禁边界</span>
              <div>受控一档校准，不生成 BUY/ADD/SELL 指令。</div>
            </div>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3">
            <span className="text-xs font-semibold text-slate-600">核验摘要（压缩）</span>
            <Badge status={run.finalWriter?.finalAction ?? run.finalAction}>
              {finalActionLabel(run.finalWriter?.finalAction ?? run.finalAction)}
            </Badge>
            <div className="flex min-w-0 flex-wrap gap-1.5">
              {compactChecks.map((section) => (
                <span key={section.title} className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-slate-50 px-2 py-1 text-xs text-slate-600">
                  <span>{section.title}</span>
                  <span className="font-semibold text-slate-900">{section.riskLevel}</span>
                </span>
              ))}
            </div>
          </div>
          {window.labelWindowEnd ? (
            <div className="mt-2 text-xs leading-5 text-slate-500">
              为避免未来函数，历史可回测概率停在 {window.lastHistoricalTradeDate || '-'}，其标签窗口补齐至 {window.labelWindowEnd}；当前概率使用最新行情生成未标注 nowcast。
            </div>
          ) : null}
        </div>
      )}
    </Card>
  )
}

function quoteValue(record: Record<string, unknown> | undefined, key: string) {
  return record?.[key] ?? record?.[key.toLowerCase()]
}

function statusBadgeLabel(status: string): string {
  if (status === 'BLOCK_BUY') return 'BLOCK'
  if (status === 'FAIL') return 'ERROR'
  return status
}

function finalActionLabel(action: string) {
  const map: Record<string, string> = {
    WAIT: '等待观察',
    HOLD: '继续持有',
    REVIEW_ONLY: '仅复核',
    BUY_CANDIDATE: '买入候选',
    ADD_CANDIDATE: '加仓候选',
    FAILED: '分析失败',
  }
  return map[action] ?? action
}

function runStatusLabel(status: string) {
  const map: Record<string, string> = {
    CREATED: '已创建',
    RUNNING: '运行中',
    COMPLETED: '已完成',
    FAILED: '运行失败',
    STALE: '已恢复为过期失败',
    PASS: '正常',
    FAIL: '失败',
  }
  return map[status] ?? status
}

function killSwitchLevelLabel(level: string) {
  const map: Record<string, string> = {
    NONE: '未触发',
    SOFT: '软限制',
    HARD: '硬阻断',
    COMPLIANCE: '合规阻断',
  }
  return map[level] ?? level
}

function reachabilityView(raw?: string) {
  if (raw === 'REACHABLE') {
    return {
      label: '完全可达',
      status: 'PASS',
      note: '仅表示成交条件可达，不代表系统允许实盘买入。',
    }
  }
  if (raw === 'CONDITIONALLY_REACHABLE') {
    return {
      label: '有条件可达',
      status: 'WARN',
      note: '存在数据缺口、滑点或盘口不确定性，只能观察或复核。',
    }
  }
  return {
    label: '不可达',
    status: 'BLOCK_BUY',
    note: '执行层禁止生成买入或加仓路径。',
  }
}

function dataSourceDetail(source: DataSourceStatus & { key: string }) {
  if (source.status !== 'FAILED') return source.detail
  const chain = source.fallbackChain ?? source.degradationChain ?? []
  const chainErrors = chain
    .filter((step) => !step.success && step.error)
    .map((step) => `${step.provider || step.adapterId}: ${step.error}`)
  if (chainErrors.length > 0) {
    return `本标的拉取失败：${chainErrors.slice(0, 2).join('；')}`
  }
  if (source.error === 'All adapters failed' || source.detail.includes('All adapters failed')) {
    return '本标的拉取失败：可用适配器均未返回该项数据。配置页只验证接口/Token 连通性，个股分析会按当前股票重新取数。'
  }
  return source.detail
}

function probabilitySourceLabel(source: ReturnType<typeof buildQiamProbabilityView>['source']) {
  if (source === 'MODEL_OUTPUT') return '模型输出'
  if (source === 'LEGACY_TEMPLATE') return '历史模板'
  return '规则推算'
}

function statusToneClass(status: string) {
  const value = String(status || '').toUpperCase()
  if (['PASS', 'NONE', 'LOW', 'READY', 'QUALIFIED', 'COMPLETED', 'BUY_CANDIDATE', 'ADD_CANDIDATE'].includes(value)) {
    return {
      rail: 'border-l-[#34a853]',
      soft: 'bg-[#e6f4ea] text-[#137333]',
      dot: 'bg-[#34a853]',
      text: 'text-[#137333]',
    }
  }
  if (['WARN', 'WARNING', 'MEDIUM', 'SOFT', 'REVIEW', 'REVIEW_ONLY', 'CONDITIONALLY_REACHABLE', 'RUNNING'].includes(value)) {
    return {
      rail: value === 'RUNNING' ? 'border-l-[#1a73e8]' : 'border-l-[#fbbc04]',
      soft: value === 'RUNNING' ? 'bg-[#e8f0fe] text-[#1967d2]' : 'bg-[#fef7e0] text-[#b06000]',
      dot: value === 'RUNNING' ? 'bg-[#1a73e8]' : 'bg-[#fbbc04]',
      text: value === 'RUNNING' ? 'text-[#1967d2]' : 'text-[#b06000]',
    }
  }
  if (['FAIL', 'FAILED', 'ERROR', 'STALE', 'BLOCK', 'BLOCKED', 'BLOCK_BUY', 'HARD', 'HIGH', 'COMPLIANCE', 'REJECT'].includes(value)) {
    return {
      rail: 'border-l-[#ea4335]',
      soft: 'bg-[#fce8e6] text-[#c5221f]',
      dot: 'bg-[#ea4335]',
      text: 'text-[#c5221f]',
    }
  }
  return {
    rail: 'border-l-slate-300',
    soft: 'bg-slate-100 text-slate-700',
    dot: 'bg-slate-400',
    text: 'text-slate-700',
  }
}

type DashboardRunGovernance = {
  contextId: string
  evidenceStrength: 'MEDIUM' | 'LOW'
  blocker: string
  nextAction: string
  simulationOnly: boolean
  isRealTrade: boolean
  evidenceUsage: string
  strongConclusionAllowed: boolean
}

function dashboardRunEvidenceStrength(level: string): DashboardRunGovernance['evidenceStrength'] {
  const normalized = String(level || '').trim().toUpperCase()
  if (normalized === 'LOW') return 'LOW'
  if (['UNKNOWN', 'SUPPORTING_ONLY', 'WEAK', 'WARN', 'WARNING', 'REVIEW', 'REVIEW_ONLY'].includes(normalized)) return 'LOW'
  if (normalized === 'MEDIUM') return 'MEDIUM'
  if (['RESEARCH_GRADE', 'PRIMARY_EVIDENCE_READY'].includes(normalized)) return 'MEDIUM'
  if (['STRONG', 'HIGH', 'PRIMARY', 'PRIMARY_EVIDENCE', 'PASS', 'READY'].includes(normalized)) return 'MEDIUM'
  return 'LOW'
}

function buildDashboardRunGovernance(
  run: AnalysisRun,
  workbench: ReturnType<typeof buildDashboardWorkbench>,
  provenance: ReturnType<typeof buildDashboardProvenanceSummary>,
): DashboardRunGovernance {
  const simulationOnly = workbench.summary.tradeBoundary.simulationOnly === true
  const isRealTrade = workbench.summary.tradeBoundary.isRealTrade === true
  const tradeBoundaryEvidence = workbench.summary.tradeBoundary as typeof workbench.summary.tradeBoundary & {
    evidenceUsage?: string
    evidence_usage?: string
    strongConclusionAllowed?: boolean
    strong_conclusion_allowed?: boolean
  }
  const paperTradingEvidence = run.paperTrading as typeof run.paperTrading & {
    evidenceUsage?: string
    evidence_usage?: string
    strongConclusionAllowed?: boolean
    strong_conclusion_allowed?: boolean
  }
  const evidenceUsage =
    tradeBoundaryEvidence.evidenceUsage
    ?? tradeBoundaryEvidence.evidence_usage
    ?? paperTradingEvidence.evidenceUsage
    ?? paperTradingEvidence.evidence_usage
    ?? 'simulation_only'
  const strongConclusionAllowed =
    tradeBoundaryEvidence.strongConclusionAllowed === true
    || tradeBoundaryEvidence.strong_conclusion_allowed === true
    || paperTradingEvidence.strongConclusionAllowed === true
    || paperTradingEvidence.strong_conclusion_allowed === true
  const hasBoundaryViolation = !simulationOnly || isRealTrade || evidenceUsage !== 'simulation_only' || strongConclusionAllowed
  const failedStatus = ['FAILED', 'STALE', 'CANCELLED'].includes(String(run.status || '').toUpperCase())
  const noBlockingReason = '无阻断，保持人工复核'
  const blocker = hasBoundaryViolation
    ? 'Analysis run simulation-only boundary violated'
    : failedStatus
      ? `分析状态 ${run.status}`
      : workbench.summary.blockers[0] ?? provenance.warnings[0] ?? noBlockingReason
  const nextAction = hasBoundaryViolation
    ? '停止移交，先修复 simulation-only boundary'
    : blocker === noBlockingReason
      ? '进入 Agent DAG / guardrail_hub / quant_core 仅模拟复核'
      : '先处理 analysis run 阻断，再进入 Agent DAG'
  const dashboardEvidenceStrength = hasBoundaryViolation || failedStatus ? 'LOW' : dashboardRunEvidenceStrength(provenance.level)

  return {
    contextId: run.runId,
    evidenceStrength: dashboardEvidenceStrength,
    blocker,
    nextAction,
    simulationOnly,
    isRealTrade,
    evidenceUsage,
    strongConclusionAllowed,
  }
}

function coreDisplayText(value: unknown, fallback = '暂无内容') {
  if (typeof value === 'number' && Number.isFinite(value)) return String(value)
  if (typeof value === 'boolean') return value ? '是' : '否'
  const raw = typeof value === 'string' ? value.trim() : ''
  if (!raw || CORE_PLACEHOLDER_VALUES.has(raw.toUpperCase())) return fallback
  return raw
    .replace(/QIAM\s*适宜性/g, '量化适宜性')
    .replace(/\bQIAM\b/g, '量化适宜性')
    .replace(/\bDVG\b/g, '数据门禁')
    .replace(/\bBottom Research\b/g, 'MFE/MAE路径研究')
    .replace(/\bQuant Engine\b/g, '量化引擎')
    .replace(/\bScenario\b/g, '情景')
    .replace(/\bfinalBuySuitability=/g, '最终适宜性=')
    .replace(/\btechnicalBias=/g, '技术偏向=')
    .replace(/\bbottomBias=/g, 'MFE/MAE偏向=')
    .replace(/\bregimeState=/g, 'MFE/MAE状态=')
    .replace(/\bmarketSentiment=/g, '市场情绪=')
    .replace(/\bconfidence=/g, '置信度=')
    .replace(/\bBLOCK_BUY\b/g, '阻断买入')
    .replace(/\bBOTTOM_REPAIR_ZONE\b/g, 'MFE有利区间')
    .replace(/\bBOTTOM_REPAIR_WATCH\b/g, 'MFE观察')
    .replace(/\bBREAKDOWN_RISK\b/g, 'MAE跌破风险')
    .replace(/\bBULLISH\b/g, '偏多')
    .replace(/\bBEARISH\b/g, '偏空')
    .replace(/\bSIDEWAYS\b/g, '震荡')
    .replace(/\bMIXED\b/g, '分歧')
    .replace(/\bREAD_ONLY_NO_PERMISSION_CHANGE\b/g, '只读，不改变交易权限')
}

function coreCodeLabel(value: unknown, fallback = '未知') {
  const raw = coreDisplayText(value, '')
  if (!raw) return fallback
  const map: Record<string, string> = {
    PASS: '通过',
    WARN: '需关注',
    REVIEW_ONLY: '仅复核',
    SKIPPED: '已跳过',
    WAIT: '等待',
    BULLISH: '偏多',
    BEARISH: '偏空',
    SIDEWAYS: '震荡',
    MIXED: '分歧',
    UNKNOWN: '未知',
    INFO: '提示',
    BLOCKING_CONTEXT: '解释强冲突',
    READ_ONLY_NO_PERMISSION_CHANGE: '只读，不改变交易权限',
  }
  return map[raw.toUpperCase()] ?? raw
}

function coreScoreText(value: unknown) {
  const numeric = numericValue(value)
  if (numeric == null) return 'N/A'
  const score = numeric >= 0 && numeric <= 1 ? numeric * 100 : numeric
  return `${score.toFixed(1)} / 100`
}

function coreScorePercent(value: unknown) {
  const numeric = numericValue(value)
  if (numeric == null) return 0
  const score = numeric >= 0 && numeric <= 1 ? numeric * 100 : numeric
  return Math.max(0, Math.min(100, score))
}

function coreBiasStatus(value: unknown) {
  const normalized = String(value || '').toUpperCase()
  if (normalized === 'BULLISH') return 'PASS'
  if (normalized === 'BEARISH') return 'WARN'
  if (['SIDEWAYS', 'MIXED'].includes(normalized)) return 'WARN'
  return 'WAIT'
}

function coreConflictStatus(value: unknown) {
  const normalized = String(value || '').toUpperCase()
  if (normalized === 'INFO') return 'WAIT'
  if (normalized === 'BLOCKING_CONTEXT') return 'WARN'
  return 'WARN'
}

function CoreOverviewMetric({
  label,
  value,
  status,
  helper,
}: {
  label: string
  value: React.ReactNode
  status?: string
  helper?: React.ReactNode
}) {
  const metricTone = status === 'PASS' ? 'success' : status === 'FAIL' ? 'danger' : status === 'WARN' ? 'warning' : 'neutral'
  return (
    <MetricTile
      label={label}
      value={value}
      helper={helper}
      tone={metricTone}
      className="!rounded-md !px-3 !py-2.5 !shadow-none"
    />
  )
}

function CoreInterpretationOverview({ interpretation }: { interpretation?: QuantCoreInterpretation | null }) {
  const dimensions = Array.isArray(interpretation?.dimensions) ? interpretation.dimensions.slice(0, 5) : []
  const conflicts = Array.isArray(interpretation?.conflicts) ? interpretation.conflicts.slice(0, 3) : []
  const riskFlags = Array.isArray(interpretation?.riskFlags) ? interpretation.riskFlags.slice(0, 6) : []
  const weightAdjustmentReasons = Array.isArray(interpretation?.weightAdjustmentReasons)
    ? interpretation.weightAdjustmentReasons.slice(0, 3)
    : []
  const status = interpretation?.status || 'WAIT'

  return (
    <div
      data-testid="dashboard-core-interpretation"
      className="rounded-md border border-[#d2e3fc] bg-white p-4 shadow-sm shadow-slate-200/50"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <div className="grid h-10 w-10 shrink-0 place-items-center rounded-md bg-[#e8f0fe] text-[#1967d2]">
            <Cpu size={20} />
          </div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-base font-semibold text-slate-950">量化核心解读</h2>
              <Badge status={status}>{coreCodeLabel(status)}</Badge>
            </div>
            <p className="mt-1 text-sm leading-6 text-slate-500">
              汇总市场、技术面、MFE/MAE路径、因子和情景证据；只读展示，不改变最终动作。
            </p>
          </div>
        </div>
        <a
          href="/quant-core"
          className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-md border border-slate-300 bg-white px-3 text-xs font-semibold text-slate-700 transition hover:bg-slate-50"
        >
          查看量化核心
          <ArrowRight size={14} />
        </a>
      </div>

      {!interpretation ? (
        <div data-testid="dashboard-core-interpretation-empty" className="mt-4 rounded-md border border-dashed border-slate-200 bg-slate-50 px-3 py-3 text-sm text-slate-500">
          当前 run 尚未生成量化核心核心解读。
        </div>
      ) : (
        <div className="mt-4 min-w-0 space-y-4">
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
            <CoreOverviewMetric label="综合分" value={coreScoreText(interpretation.overallScore)} status={status} />
            <CoreOverviewMetric label="综合偏向" value={coreCodeLabel(interpretation.overallBias)} status={coreBiasStatus(interpretation.overallBias)} />
            <CoreOverviewMetric label="证据置信度" value={percentValue(interpretation.confidence)} status={status} />
            <CoreOverviewMetric label="解释边界" value={coreCodeLabel(interpretation.actionBoundary)} status="READ_ONLY" />
          </div>

          <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-3 text-sm leading-6 text-slate-700">
            {coreDisplayText(interpretation.summary)}
          </div>

          {dimensions.length > 0 ? (
            <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-5">
              {dimensions.map((dimension) => {
                const evidenceItems = Array.isArray(dimension.evidence) ? dimension.evidence : []
                const warningItems = Array.isArray(dimension.warnings) ? dimension.warnings : []
                const score = coreScorePercent(dimension.score)
                return (
                  <div key={dimension.key} className="min-w-0 rounded-md border border-slate-200 bg-white px-3 py-2.5">
                    <div className="flex min-h-[42px] items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="break-words text-sm font-semibold leading-5 text-slate-950">{coreDisplayText(dimension.label, '维度')}</div>
                        <div className="mt-0.5 text-[11px] leading-4 text-slate-500">
                          权重 {percentValue(dimension.weight)} · 置信 {percentValue(dimension.confidence)}
                        </div>
                      </div>
                      <Badge status={coreBiasStatus(dimension.bias)} className="shrink-0 px-2 py-0.5">
                        {coreCodeLabel(dimension.bias)}
                      </Badge>
                    </div>
                    <div className="mt-3 h-2 rounded-full bg-slate-100">
                      <div className="h-2 rounded-full bg-[#1a73e8]" style={{ width: `${score}%` }} />
                    </div>
                    <div className="mt-2 text-xs font-semibold text-slate-900">{coreScoreText(dimension.score)}</div>
                    <div className="mt-2 min-h-[40px] break-words text-[11px] leading-5 text-slate-600">
                      {coreDisplayText(evidenceItems[0], coreDisplayText(warningItems[0], '等待维度证据'))}
                    </div>
                  </div>
                )
              })}
            </div>
          ) : null}

          {(conflicts.length > 0 || riskFlags.length > 0 || weightAdjustmentReasons.length > 0) ? (
            <div className="grid gap-3 border-t border-slate-100 pt-4 xl:grid-cols-[minmax(0,1fr)_minmax(260px,0.45fr)]">
              <div className="min-w-0">
                <div className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">冲突提醒</div>
                {conflicts.length > 0 ? (
                  <div className="grid gap-2">
                    {conflicts.map((conflict, index) => {
                      const evidenceItems = Array.isArray(conflict.evidence) ? conflict.evidence : []
                      return (
                        <div key={`${conflict.key}-${index}`} className="rounded-md border border-amber-200 bg-[#fef7e0] px-3 py-2 text-xs leading-5 text-[#5f4700]">
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <span className="break-words font-semibold">{coreDisplayText(conflict.message, '解释层冲突需要复核')}</span>
                            <Badge status={coreConflictStatus(conflict.severity)} className="shrink-0 px-2 py-0.5">
                              {coreCodeLabel(conflict.severity)}
                            </Badge>
                          </div>
                          {evidenceItems.length > 0 ? (
                            <div className="mt-1 break-words text-[#6f5500]">{evidenceItems.map((item) => coreDisplayText(item)).join(' · ')}</div>
                          ) : null}
                        </div>
                      )
                    })}
                  </div>
                ) : (
                  <div className="rounded-md border border-emerald-200 bg-[#e6f4ea] px-3 py-2 text-xs leading-5 text-[#137333]">
                    当前核心解读未报告主要冲突。
                  </div>
                )}
              </div>

              <div className="min-w-0">
                <div className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">边界与调整</div>
                <div className="flex flex-wrap gap-2">
                  {riskFlags.length > 0 ? riskFlags.map((flag, index) => (
                    <Badge key={`${flag}-${index}`} status={flag === 'READ_ONLY_NO_PERMISSION_CHANGE' ? 'READ_ONLY' : 'WARN'}>
                      {coreCodeLabel(flag)}
                    </Badge>
                  )) : (
                    <Badge status="READ_ONLY">只读，不改变交易权限</Badge>
                  )}
                  {interpretation.weightAdjusted ? weightAdjustmentReasons.map((reason, index) => (
                    <Badge key={`${reason}-${index}`} status="WARN">{coreDisplayText(reason)}</Badge>
                  )) : null}
                </div>
              </div>
            </div>
          ) : null}
        </div>
      )}
    </div>
  )
}

function MetricCell({
  label,
  value,
  helper,
}: {
  label: string
  value: React.ReactNode
  helper?: React.ReactNode
}) {
  return (
    <MetricTile
      label={label}
      value={value}
      helper={helper}
      className="!border-0 !bg-transparent !px-0 !py-3 !shadow-none sm:!px-4 sm:first:!pl-0 sm:last:!pr-0"
    />
  )
}

function DecisionTile({
  label,
  value,
  helper,
  status,
  icon: Icon,
}: {
  label: string
  value: React.ReactNode
  helper: React.ReactNode
  status: string
  icon: React.ElementType
}) {
  const tone = statusToneClass(status)
  return (
    <div className={`h-full min-w-0 rounded-md border border-[#dfe3eb] border-l-4 bg-white ${tone.rail} px-3 py-3 shadow-[0_1px_2px_rgba(60,64,67,0.08)]`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</div>
          <div className="mt-1 break-words text-lg font-semibold text-[#0b1f44]">{value}</div>
        </div>
        <div className={`grid h-9 w-9 shrink-0 place-items-center rounded-md ${tone.soft}`}>
          <Icon size={18} />
        </div>
      </div>
      <div className="mt-3 line-clamp-2 text-xs leading-5 text-slate-500">{helper}</div>
    </div>
  )
}

function StatusRow({
  label,
  value,
  status,
  badgeLabel,
  note,
  icon: Icon,
}: {
  label: string
  value: React.ReactNode
  status: string
  badgeLabel?: React.ReactNode
  note?: React.ReactNode
  icon?: React.ElementType
}) {
  const tone = statusToneClass(status)
  return (
    <div className="flex gap-3 border-b border-slate-100 py-3 last:border-b-0">
      <div className={`mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-md ${tone.soft}`}>
        {Icon ? <Icon size={16} /> : <span className={`h-2 w-2 rounded-full ${tone.dot}`} />}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</div>
          <Badge status={status}>{badgeLabel ?? String(value)}</Badge>
        </div>
        <div className="mt-1 break-words text-sm font-semibold text-slate-950">{value}</div>
        {note ? <div className="mt-1 text-xs leading-5 text-slate-500">{note}</div> : null}
      </div>
    </div>
  )
}

export function DashboardPage() {
  const { currentRun, currentRunId, refreshRun, fallbackToMock, autoRefreshEnabled, autoRefreshInterval, setAutoRefresh } = useAnalysisStore()
  const [searchParams] = useSearchParams()
  const linkedRunId = (searchParams.get('run_id') || '').trim()
  const isLinkedRunPending = Boolean(linkedRunId && currentRun?.runId !== linkedRunId)
  const [dataSourcesExpanded, setDataSourcesExpanded] = useState(false)
  const [closedLoopCreating, setClosedLoopCreating] = useState(false)
  const [closedLoopError, setClosedLoopError] = useState<string | null>(null)
  const [closedLoopResult, setClosedLoopResult] = useState<P2ClosedLoopSampleResponse | null>(null)
  const operator = useOperatorContext()
  const canCreateResearchClosedLoop = roleAllows(operator.role, 'researcher')
  const closedLoopDisabledReason = canCreateResearchClosedLoop
    ? ''
    : `研究实验室样例重建需要研究员权限。当前角色：${operator.role}。`

  // Stale-while-revalidate: show last-known knowledge regression + LLM health
  // instantly on dashboard revisit, then refresh in the background.
  const {
    data: knowledgeVersionsData,
    error: knowledgeVersionsError,
  } = useCachedResource<KnowledgeVersionItem[]>('dashboard:knowledge-versions', () => getKnowledgeVersions(30))
  const knowledgeVersions = useMemo(() => knowledgeVersionsData ?? [], [knowledgeVersionsData])
  const knowledgeRegressionError = knowledgeVersionsError ? '知识版本回归摘要暂不可用' : null
  const knowledgeRegressionLoading = knowledgeVersionsData === undefined && !knowledgeRegressionError

  const { data: backendMetrics, error: backendMetricsError } = useCachedResource(
    `dashboard:metrics:${operator.apiTokenSet ? 'authed' : 'anon'}`,
    () => getBackendMetrics(),
  )
  const productionHealth = backendMetrics?.productionHealth ?? null
  const productionHealthError = backendMetricsError
    ? backendMetricsError instanceof Error
      ? backendMetricsError.message
      : 'Production health is not available'
    : null
  const productionHealthLoading = backendMetrics === undefined && !productionHealthError

  useEffect(() => {
    if (!currentRunId || currentRun?.status !== 'RUNNING' || !autoRefreshEnabled) return
    const timer = window.setInterval(() => {
      refreshRun(currentRunId).catch(() => undefined)
    }, autoRefreshInterval)
    return () => window.clearInterval(timer)
  }, [currentRunId, currentRun?.status, refreshRun, autoRefreshEnabled, autoRefreshInterval])

  useEffect(() => {
    setDataSourcesExpanded(false)
  }, [currentRunId])

  async function handleCreateClosedLoopSample() {
    if (!canCreateResearchClosedLoop) {
      setClosedLoopResult(null)
      setClosedLoopError(closedLoopDisabledReason || '当前角色不可重建研究实验室样例。')
      return
    }
    setClosedLoopCreating(true)
    setClosedLoopError(null)
    try {
      const result = await createP2ClosedLoopSample({
        symbol: currentRun?.stockCode || undefined,
        stock_name: currentRun?.stockName || undefined,
        materialize_artifacts: true,
        run_evaluation: true,
        promote_knowledge_version: true,
        reviewer: 'dashboard',
      })
      setClosedLoopResult(result)
      if (result.simulation_only !== true || result.is_real_trade !== false) {
        setClosedLoopError('Closed-loop sample returned an unexpected trading boundary.')
      }
    } catch (err) {
      setClosedLoopResult(null)
      setClosedLoopError(err instanceof Error ? err.message : '无法创建研究实验室闭环样例')
    } finally {
      setClosedLoopCreating(false)
    }
  }

  const sortedAgents = useMemo(() => {
    if (!currentRun) return []
    return buildSortedAgents(currentRun.agentResults, currentRun.nodes)
  }, [currentRun])

  const dataSourceList = useMemo(() => {
    if (!currentRun) return []
    return buildDataSourceList(currentRun)
  }, [currentRun])

  const dataSourcesSummary = currentRun?.dataSources?.summary
  const knowledgeRegressionVersion = useMemo(
    () => latestKnowledgeRegressionVersion(knowledgeVersions),
    [knowledgeVersions],
  )
  const knowledgeRegression = knowledgeRegressionVersion?.post_publish_regression
  const knowledgeRegressionAffectedModules = Array.isArray(knowledgeRegression?.affected_modules)
    ? knowledgeRegression.affected_modules.map((item) => String(item)).filter(Boolean)
    : []
  const knowledgeRegressionWarnings = Array.isArray(knowledgeRegression?.warnings)
    ? knowledgeRegression.warnings.map((item) => String(item)).filter(Boolean)
    : []
  const knowledgeRegressionQualityWarnings = Array.isArray(knowledgeRegression?.quality_warnings)
    ? knowledgeRegression.quality_warnings.map((item) => String(item)).filter(Boolean)
    : Array.isArray(knowledgeRegression?.case_set_quality?.warnings)
      ? knowledgeRegression.case_set_quality.warnings.map((item) => String(item)).filter(Boolean)
      : []
  const knowledgeRegressionAllWarnings = Array.from(new Set([
    ...knowledgeRegressionWarnings,
    ...knowledgeRegressionQualityWarnings,
  ]))

  if (isLinkedRunPending) {
    return (
      <div data-testid="dashboard-page-loading" className="space-y-6">
        <SectionTitle title="分析总览" subtitle="把行情、风险门禁、Agent 链路和最终动作放在同一张工作台里。" />
        <div className="text-sm text-slate-500">
          正在加载分析总览...
          {linkedRunId ? <span className="ml-2 font-mono">{linkedRunId}</span> : null}
        </div>
        <KnowledgeRegressionCard
          loading={knowledgeRegressionLoading}
          error={knowledgeRegressionError}
          version={knowledgeRegressionVersion}
          regression={knowledgeRegression}
          affectedModules={knowledgeRegressionAffectedModules}
          warnings={knowledgeRegressionAllWarnings}
        />
        <LlmLiveCallHealthCard
          health={productionHealth}
          loading={productionHealthLoading}
          error={productionHealthError}
        />
      </div>
    )
  }

  if (!currentRun) {
    return (
      <div data-testid="dashboard-empty-state" className="space-y-6">
        <SectionTitle title="分析总览" subtitle="把行情、风险门禁、Agent 链路和最终动作放在同一张工作台里。" />
        <div className="flex flex-wrap items-center gap-3">
          <div className="text-sm text-slate-500">正在加载分析总览...</div>
          <button
            type="button"
            data-testid="dashboard-load-local-sample"
            onClick={fallbackToMock}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700 transition hover:border-slate-300 hover:bg-slate-50"
          >
            <Database size={16} />
            载入本地示例
          </button>
        </div>
        <KnowledgeRegressionCard
          loading={knowledgeRegressionLoading}
          error={knowledgeRegressionError}
          version={knowledgeRegressionVersion}
          regression={knowledgeRegression}
          affectedModules={knowledgeRegressionAffectedModules}
          warnings={knowledgeRegressionAllWarnings}
        />
        <LlmLiveCallHealthCard
          health={productionHealth}
          loading={productionHealthLoading}
          error={productionHealthError}
        />
        <ResearchClosedLoopEntryCard
          creating={closedLoopCreating}
          error={closedLoopError}
          result={closedLoopResult}
          canCreate={canCreateResearchClosedLoop}
          disabledReason={closedLoopDisabledReason}
          operatorRole={operator.role}
          onCreate={handleCreateClosedLoopSample}
        />
      </div>
    )
  }

  const finalAction = currentRun.finalWriter?.finalAction ?? currentRun.finalAction
  const reachability = reachabilityView(currentRun.execution?.executionReachability)
  const finalActionNote = ['BUY_CANDIDATE', 'ADD_CANDIDATE'].includes(finalAction)
    ? '候选不等于下单：必须满足上游门禁并人工确认。'
    : '当前不构成买入指令，系统不会自动下单。'
  const quote = currentRun.marketData?.quote as Record<string, unknown> | undefined
  const price = quoteValue(quote, 'price')
  const changePercent = quoteValue(quote, 'changePercent') ?? quoteValue(quote, 'pct_change')
  const volume = quoteValue(quote, 'volume')
  const conclusionInsights = buildConclusionInsights(currentRun)
  const frameworkInsights = conclusionInsights.slice(0, 4)
  const failureNotice =
    ['FAILED', 'STALE'].includes(currentRun.status) ? buildRunFailureNotice(currentRun, '分析结果需复核') : undefined
  const qiamProbability = buildQiamProbabilityView(currentRun)
  const provenanceSummary = buildDashboardProvenanceSummary(currentRun)
  const workbench = buildDashboardWorkbench(currentRun, provenanceSummary)
  const dashboardGovernance = buildDashboardRunGovernance(currentRun, workbench, provenanceSummary)
  const boundarySimulationLabel = `simulationOnly=${String(workbench.summary.tradeBoundary.simulationOnly)}`
  const boundaryRealTradeLabel = `isRealTrade=${String(workbench.summary.tradeBoundary.isRealTrade)}`
  const boundaryHelper = `${boundarySimulationLabel}；${boundaryRealTradeLabel}；首页只展示研究/模拟工作台状态。`

  const currentPositionPct = (currentRun.userPosition?.currentPositionRatio ?? 0) * 100
  const maxDrawdownPct = (currentRun.userPosition?.maxAcceptableDrawdown ?? 0) * 100
  const singleStockCapPct = (currentRun.portfolio?.singleStockPositionCap ?? 0) * 100
  const capGapPct = singleStockCapPct - currentPositionPct
  const positionScaleMax = Math.max(20, currentPositionPct, maxDrawdownPct, singleStockCapPct, 1)
  const positionBudgetPct = singleStockCapPct > 0 ? Math.min(100, (currentPositionPct / singleStockCapPct) * 100) : 0

  const positionData = [
    {
      label: '当前仓位',
      value: currentPositionPct,
      helper: currentRun.userPosition?.currentShares != null
        ? `持有 ${currentRun.userPosition.currentShares.toLocaleString()} 股`
        : '来自任务仓位输入',
    },
    {
      label: '最大回撤',
      value: maxDrawdownPct,
      helper: '用户可承受风险阈值',
    },
    {
      label: '单股上限',
      value: singleStockCapPct,
      helper: '组合层单标的上限',
    },
  ]
  const activeCanonicalAgents = sortedAgents.filter((agent) => !isDashboardCompatibilityOnly(agent))
  const compatibilityAgentCount = sortedAgents.length - activeCanonicalAgents.length
  const activeAgentCount = activeCanonicalAgents.filter((agent) => !agent.isSkipped).length
  const blockedAgentCount = activeCanonicalAgents.filter((agent) => agent.isBlocked).length
  const activeAgentTotal = activeCanonicalAgents.length
  const runStatus = currentRun.status === 'RUNNING' ? 'RUNNING' : ['FAILED', 'STALE'].includes(currentRun.status) ? 'FAIL' : 'PASS'
  const dataSourceReadyRatio = dataSourcesSummary?.availableRatio ?? `${dataSourceList.filter((source) => source.available).length}/${dataSourceList.length}`
  const visibleDataSourceList = dataSourcesExpanded ? dataSourceList : dataSourceList.slice(0, DATA_SOURCE_PREVIEW_LIMIT)
  const hiddenDataSourceCount = Math.max(0, dataSourceList.length - DATA_SOURCE_PREVIEW_LIMIT)
  const decisionTiles = [
    {
      label: '最终动作',
      value: finalActionLabel(finalAction),
      helper: workbench.summary.headline || finalActionNote,
      status: finalAction,
      icon: Target,
    },
    {
      label: '数据可信度',
      value: provenanceSummary.label,
      helper: `${workbench.evidenceScorePercent}% · 来源 ${workbench.sourceRatioLabel}`,
      status: provenanceSummary.status,
      icon: Database,
    },
    {
      label: '风险门禁',
      value: killSwitchLevelLabel(currentRun.killSwitch?.level ?? 'NONE'),
      helper: workbench.primaryBlocker,
      status: currentRun.killSwitch?.level ?? 'NONE',
      icon: ShieldCheck,
    },
    {
      label: '执行可达性',
      value: reachability.label,
      helper: reachability.note,
      status: reachability.status,
      icon: Activity,
    },
    {
      label: '人工确认',
      value: workbench.summary.tradeBoundary.humanConfirmationRequired ? '必须确认' : '不需要',
      helper: '候选动作不会绕过人工复核直接转为实盘指令。',
      status: workbench.summary.tradeBoundary.humanConfirmationRequired ? 'WARN' : 'PASS',
      icon: AlertTriangle,
    },
    {
      label: '模拟边界',
      value: workbench.boundaryStatus === 'PASS' ? '模拟锁定' : '边界异常',
      helper: boundaryHelper,
      status: workbench.boundaryStatus,
      icon: ShieldCheck,
    },
  ]
  const positionBudgetCard = (
    <Card
      title="仓位与风险预算"
      action={
        <span className={`rounded-md border px-2 py-1 text-xs font-semibold ${capGapPct >= 0 ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-red-200 bg-red-50 text-red-700'}`}>
          {capGapPct >= 0 ? `剩余额度 ${capGapPct.toFixed(1)}%` : `超限 ${Math.abs(capGapPct).toFixed(1)}%`}
        </span>
      }
    >
      <div className="grid gap-3 md:grid-cols-3">
        {positionData.map((item) => (
          <div key={item.label} className="min-w-0 rounded-md border border-[#dfe3eb] bg-[#f8fafd] px-3 py-2.5">
            <div className="text-xs font-medium text-slate-500">{item.label}</div>
            <div className="mt-1 text-2xl font-semibold tracking-tight text-[#0b1f44]">{item.value.toFixed(1)}%</div>
            <div className="mt-1 text-xs leading-5 text-slate-500">{item.helper}</div>
          </div>
        ))}
      </div>

      <div className="mt-5 grid gap-4 border-t border-slate-100 pt-4 lg:grid-cols-2">
        <div>
          <div className="mb-2 flex items-center justify-between gap-3 text-xs">
            <span className="font-medium text-slate-600">单股仓位预算占用</span>
            <span className="text-slate-500">{currentPositionPct.toFixed(1)}% / {singleStockCapPct.toFixed(1)}%</span>
          </div>
          <div className="relative h-3 rounded-full bg-slate-100">
            <div
              className={`h-3 rounded-full ${capGapPct >= 0 ? 'bg-teal-600' : 'bg-red-500'}`}
              style={{ width: `${positionBudgetPct}%` }}
            />
            <div className="absolute -top-1 bottom-[-4px] right-0 w-px bg-slate-400" />
          </div>
          <div className="mt-2 flex justify-between text-[11px] text-slate-400">
            <span>0%</span>
            <span>上限 {singleStockCapPct.toFixed(1)}%</span>
          </div>
        </div>

        <div>
          <div className="mb-2 flex items-center justify-between gap-3 text-xs">
            <span className="font-medium text-slate-600">风险容忍刻度</span>
            <span className="text-slate-500">最大回撤 {maxDrawdownPct.toFixed(1)}%</span>
          </div>
          <div className="h-2 rounded-full bg-slate-100">
            <div
              className="h-2 rounded-full bg-amber-500"
              style={{ width: `${Math.min(100, (maxDrawdownPct / positionScaleMax) * 100)}%` }}
            />
          </div>
          <div className="mt-2 flex justify-between text-[11px] text-slate-400">
            <span>0%</span>
            <span>{positionScaleMax.toFixed(0)}%</span>
          </div>
        </div>
      </div>
    </Card>
  )

  return (
    <div data-testid="dashboard-page" className="space-y-6">
      <section data-testid="dashboard-decision-workbench" className="overflow-hidden rounded-md border border-[#dfe3eb] bg-white shadow-[0_2px_8px_rgba(60,64,67,0.08)]">
        <div className="border-b border-[#dfe3eb] bg-white px-4 py-4 sm:px-5 lg:px-6">
          <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
            <div className="min-w-0">
              <div className="mb-2 text-sm font-semibold text-slate-950">分析总览</div>
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded-md bg-[#e8f0fe] px-2.5 py-1 text-xs font-semibold text-[#1967d2]">A 股</span>
                <span className="text-sm text-slate-500">{taskTypeLabel(currentRun.taskType)}</span>
                <span className="text-sm text-slate-300">/</span>
                <span className="text-sm text-slate-500">{runModeLabel(currentRun.runMode)}</span>
                {currentRun.dataMode ? <DataModeBadge mode={currentRun.dataMode} /> : null}
              </div>
              <div className="mt-3 flex flex-wrap items-end gap-x-4 gap-y-2">
                <h1 className="break-words text-3xl font-semibold tracking-tight text-slate-950 sm:text-4xl">
                  {currentRun.stockName || '未命名标的'}
                </h1>
                <span className="pb-1 text-sm font-medium text-slate-500">{currentRun.stockCode}</span>
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-slate-500">
                <span className={`h-2 w-2 rounded-full ${statusToneClass(runStatus).dot}`} />
                <span>{runStatusLabel(currentRun.status)}</span>
                <span data-testid="dashboard-current-run-id" className="font-mono text-xs text-slate-400">{currentRun.runId}</span>
                <span>Agent {activeAgentCount}/{activeAgentTotal}</span>
                {compatibilityAgentCount > 0 ? <span>兼容 {compatibilityAgentCount}</span> : null}
                <span>证据 {workbench.evidenceScorePercent}%</span>
                <span>来源 {workbench.sourceRatioLabel}</span>
                {blockedAgentCount > 0 ? <span className="text-[#c5221f]">{blockedAgentCount} 个阻断</span> : null}
              </div>
            </div>

            {currentRun.status === 'RUNNING' ? (
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={() => setAutoRefresh(!autoRefreshEnabled)}
                  className="inline-flex h-9 items-center gap-2 rounded-md border border-slate-300 bg-white px-3 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
                >
                  {autoRefreshEnabled ? <PauseCircle size={16} /> : <PlayCircle size={16} />}
                  {autoRefreshEnabled ? '暂停刷新' : '自动刷新'}
                </button>
                <button
                  type="button"
                  onClick={() => currentRunId && refreshRun(currentRunId)}
                  className="inline-flex h-9 items-center gap-2 rounded-md bg-[#1a73e8] px-3 text-sm font-medium text-white transition hover:bg-[#1967d2]"
                >
                  <RefreshCw size={16} />
                  立即刷新
                </button>
              </div>
            ) : null}
          </div>
        </div>

        {failureNotice ? (
          <div className="border-b border-red-100 bg-[#fce8e6] px-4 py-4 sm:px-5 lg:px-6">
            <div className="flex items-start gap-3">
              <XCircle className="mt-0.5 h-5 w-5 shrink-0 text-[#c5221f]" />
              <div className="min-w-0 flex-1">
                <h2 className="text-sm font-semibold text-[#c5221f]">{failureNotice.title}</h2>
                <p className="mt-1 text-sm leading-6 text-[#5f2120]">{failureNotice.description}</p>
                <div className="mt-2 flex flex-wrap gap-2">
                  {failureNotice.tags.map((tag) => (
                    <span key={tag} className="rounded-md bg-white/70 px-2 py-1 text-xs font-medium text-[#c5221f]">
                      {tag}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          </div>
        ) : null}

        <div data-testid="dashboard-run-governance" className="grid gap-2 border-t border-[#dfe3eb] bg-white px-4 py-3 text-xs text-slate-600 sm:grid-cols-2 lg:grid-cols-5 lg:px-6">
          <div className="min-w-0">
            <div className="font-semibold text-slate-500">ID</div>
            <div data-testid="dashboard-run-governance-id" className="mt-1 break-all font-mono text-slate-800">{dashboardGovernance.contextId}</div>
          </div>
          <div className="min-w-0">
            <div className="font-semibold text-slate-500">证据强度</div>
            <div data-testid="dashboard-run-evidence-strength" className="mt-1 font-semibold text-slate-800">{dashboardGovernance.evidenceStrength}</div>
          </div>
          <div className="min-w-0">
            <div className="font-semibold text-slate-500">阻断</div>
            <div data-testid="dashboard-run-blocker" className="mt-1 break-words text-slate-800">{dashboardGovernance.blocker}</div>
          </div>
          <div className="min-w-0">
            <div className="font-semibold text-slate-500">下一步</div>
            <div data-testid="dashboard-run-next-action" className="mt-1 break-words text-slate-800">{dashboardGovernance.nextAction}</div>
          </div>
          <div className="min-w-0">
            <div className="font-semibold text-slate-500">模拟边界</div>
            <div data-testid="dashboard-run-simulation-boundary" className="mt-1 break-words font-mono text-[11px] text-slate-800">
              simulation_only={String(dashboardGovernance.simulationOnly)} / is_real_trade={String(dashboardGovernance.isRealTrade)} / evidence_usage={dashboardGovernance.evidenceUsage} / strong_conclusion_allowed={String(dashboardGovernance.strongConclusionAllowed)} / SIM_*
            </div>
          </div>
        </div>

        <div data-testid="dashboard-trade-boundary" className="grid gap-4 border-t border-[#dfe3eb] bg-[#f8fafd] px-4 py-4 sm:px-5 lg:grid-cols-[minmax(0,1fr)_minmax(260px,0.48fr)] lg:px-6">
          <div className="min-w-0">
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">操盘判断</div>
            <div className="mt-2 break-words text-lg font-semibold leading-7 text-slate-950">{workbench.summary.headline}</div>
            <div className="mt-3 flex flex-wrap gap-2">
              <Badge status={workbench.decisionStatus}>决策 {finalActionLabel(finalAction)}</Badge>
              <Badge status={provenanceSummary.status}>证据 {provenanceSummary.label}</Badge>
              <Badge status={workbench.boundaryStatus}>{boundarySimulationLabel}</Badge>
              <Badge status={workbench.boundaryStatus}>{boundaryRealTradeLabel}</Badge>
            </div>
          </div>
          <div className="min-w-0 rounded-md border border-[#dfe3eb] bg-white px-3 py-3">
            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">下一步复核</div>
            <div className="space-y-1.5 text-xs leading-5 text-slate-600">
              {workbench.nextReviewRows.slice(0, 3).map((item) => (
                <div key={item} className="flex min-w-0 gap-2">
                  <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-[#1a73e8]" />
                  <span className="min-w-0 break-words">{item}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="grid gap-3 border-t border-[#dfe3eb] bg-white p-4 sm:grid-cols-2 sm:p-5 lg:grid-cols-3 lg:p-6 xl:grid-cols-6">
          {decisionTiles.map((tile) => (
            <DecisionTile key={tile.label} {...tile} />
          ))}
        </div>

        <div className="grid border-t border-[#dfe3eb] lg:grid-cols-[minmax(0,1.2fr)_minmax(360px,0.8fr)]">
          <div className="min-w-0 p-4 sm:p-5 lg:p-6">
            <CoreInterpretationOverview interpretation={currentRun.quantCore?.coreInterpretation} />

            <div className="mt-5 rounded-md border border-[#d2e3fc] bg-[#e8f0fe] p-4">
              <div className="mb-2 text-xs font-medium uppercase tracking-wide text-[#1967d2]">行情快照</div>
              <div className="grid gap-3 sm:grid-cols-3">
                <div className="rounded-md border border-[#d2e3fc] bg-white/85 px-4">
                  <MetricCell label="最新价" value={numberValue(price)} />
                </div>
                <div className="rounded-md border border-[#d2e3fc] bg-white/85 px-4">
                  <MetricCell label="涨跌幅" value={numberValue(changePercent)} />
                </div>
                <div className="rounded-md border border-[#d2e3fc] bg-white/85 px-4">
                  <MetricCell label="成交量" value={compactMarketNumber(volume)} helper={numberValue(volume)} />
                </div>
              </div>
            </div>

            <div className="mt-5">
              <div className="mb-2 flex items-center justify-between gap-3">
                <h2 className="text-base font-semibold text-slate-950">关键核验</h2>
                <span className="text-xs text-slate-500">按结论框架聚合</span>
              </div>
              <div className="divide-y divide-slate-100">
                {frameworkInsights.map((section) => (
                  <div key={section.title} className="py-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="font-medium text-slate-950">{section.title}</div>
                      <Badge status={section.riskLevel === 'LOW' ? 'PASS' : section.riskLevel === 'MEDIUM' ? 'WARN' : 'FAIL'}>
                        {section.riskLevel}
                      </Badge>
                    </div>
                    <div className="mt-2 grid gap-1 text-sm leading-6 text-slate-600">
                      {section.items.slice(0, 2).map((item) => (
                        <div key={item} className="flex min-w-0 gap-2">
                          <span className={`mt-2 h-1.5 w-1.5 shrink-0 rounded-full ${statusToneClass(section.riskLevel).dot}`} />
                          <span className="min-w-0 break-words">{item}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <aside className="border-t border-slate-200 bg-slate-50/50 p-4 sm:p-5 lg:border-l lg:border-t-0 lg:p-6">
            <div className="mb-3 flex items-center justify-between gap-3">
              <h2 className="text-base font-semibold text-slate-950">运行约束</h2>
              <span className="text-xs text-slate-500">本次分析</span>
            </div>
            <div className="divide-y divide-slate-100">
              <StatusRow
                label="数据可信摘要"
                value={provenanceSummary.label}
                status={provenanceSummary.status}
                badgeLabel={provenanceSummary.level}
                note={(
                  <div>
                    <div>{provenanceSummary.headline}</div>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {(['LIVE', 'FALLBACK', 'MOCK', 'MISSING', 'USER_INPUT'] as const).map((kind) => (
                        provenanceSummary.sourceCounts[kind] > 0 ? (
                          <span key={kind} className="rounded-md border border-slate-200 bg-white px-2 py-0.5 text-[11px] text-slate-600">
                            {kind === 'USER_INPUT' ? 'USER_INPUT_ONLY' : kind}: {provenanceSummary.sourceCounts[kind]}
                          </span>
                        ) : null
                      ))}
                    </div>
                  </div>
                )}
                icon={Database}
              />
              <StatusRow
                label="DVG 数据可靠性"
                value={currentRun.dvg?.dataReliability ?? 'MEDIUM'}
                status={currentRun.dvg?.status ?? 'MEDIUM'}
                badgeLabel={currentRun.dvg?.status ?? 'MEDIUM'}
                note="数据验证门禁决定后续 Agent 是否可以引用该证据。"
                icon={ShieldCheck}
              />
              <StatusRow
                label="执行可达性"
                value={reachability.label}
                status={reachability.status}
                note={reachability.note}
                icon={Target}
              />
              <StatusRow
                label="人工确认"
                value={currentRun.finalWriter?.humanConfirmationRequired === false ? '不需要' : '必须确认'}
                status={currentRun.finalWriter?.humanConfirmationRequired === false ? 'PASS' : 'WARN'}
                note="候选动作不会绕过人工复核直接转为实盘指令。"
                icon={AlertTriangle}
              />
              <StatusRow
                label="Agent 覆盖"
                value={`${activeAgentCount}/${activeAgentTotal}`}
                status={blockedAgentCount ? 'WARN' : 'PASS'}
                badgeLabel={blockedAgentCount ? '需复核' : '正常'}
                note={blockedAgentCount
                  ? `${blockedAgentCount} 个节点阻断或硬停止。`
                  : compatibilityAgentCount > 0
                    ? `${compatibilityAgentCount} 个兼容别名不计入覆盖。`
                    : 'DAG 节点按当前任务正常推进。'}
                icon={GitBranch}
              />
            </div>
          </aside>
        </div>
      </section>

      <KlineChartCard symbol={currentRun.stockCode} />

      <div className="grid gap-4 xl:grid-cols-[minmax(320px,0.58fr)_minmax(0,1fr)]">
        <Card
          title="QIAM 概率分布"
          action={<Badge status={qiamProbability.source === 'LEGACY_TEMPLATE' ? 'WARN' : 'PASS'}>{probabilitySourceLabel(qiamProbability.source)}</Badge>}
        >
          <div className="text-sm leading-6 text-slate-600">{qiamProbability.note}</div>
          <div className="mt-4 h-72">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={qiamProbability.rows}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="name" />
                <YAxis unit="%" />
                <Tooltip formatter={(value: number) => `${value.toFixed(1)}%`} />
                <Bar dataKey="value" radius={[4, 4, 0, 0]} fill="#1a73e8" />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-3 grid gap-2 sm:grid-cols-3">
            {qiamProbability.rows.map((row) => (
              <CompactMetric key={row.name} label={row.name} value={`${row.value.toFixed(1)}%`} helper="可见值，不依赖 hover" />
            ))}
          </div>
        </Card>
        <BottomResearchConclusionCard run={currentRun} conclusionInsights={conclusionInsights} />
      </div>

      <TechnicalKlineSummaryCard symbol={currentRun.stockCode} compact />

      <Card
        title="证据与数据"
        action={<Badge status={provenanceSummary.status}>{provenanceSummary.level}</Badge>}
      >
        <div data-testid="dashboard-data-provenance" className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(360px,0.95fr)]">
          <div className="min-w-0">
            <div data-testid="dashboard-evidence-spine" className="grid gap-4 lg:grid-cols-[minmax(0,0.95fr)_minmax(260px,0.55fr)]">
              <div className="min-w-0 rounded-md border border-[#dfe3eb] bg-[#f8fafd] px-4 py-4">
                <div className="text-xs font-medium uppercase tracking-wide text-slate-500">证据摘要</div>
                <div className="mt-2 text-2xl font-semibold text-slate-950">{provenanceSummary.label}</div>
                <div className="mt-4">
                  <div className="mb-1 flex items-center justify-between text-xs text-slate-500">
                    <span>证据分</span>
                    <span>{workbench.evidenceScorePercent}%</span>
                  </div>
                  <div className="h-2 rounded-full bg-white">
                    <div
                      className={`h-2 rounded-full ${statusToneClass(provenanceSummary.status).dot}`}
                      style={{ width: `${workbench.evidenceScorePercent}%` }}
                    />
                  </div>
                </div>
                <div className="mt-3 break-words text-xs leading-5 text-slate-500">{provenanceSummary.reason}</div>
                <div className="mt-2 break-words text-sm leading-6 text-slate-700">{provenanceSummary.headline}</div>
                <div className="mt-4 grid gap-2 sm:grid-cols-3">
                  <CompactMetric label="来源就绪" value={workbench.sourceRatioLabel} helper="本次实际拉取" />
                  <CompactMetric label="数据分" value={`${workbench.evidenceScorePercent}%`} helper="门禁输入可信度" />
                  <CompactMetric
                    label="Agent 覆盖"
                    value={`${activeAgentCount}/${activeAgentTotal}`}
                    helper={blockedAgentCount > 0
                      ? `${blockedAgentCount} 个阻断`
                      : compatibilityAgentCount > 0
                        ? `${compatibilityAgentCount} 个兼容别名`
                        : '正常推进'}
                  />
                </div>
              </div>

              <div className="min-w-0 rounded-md border border-[#dfe3eb] bg-white px-4 py-4">
                <div className="text-xs font-medium uppercase tracking-wide text-slate-500">阻断 / 警告 / 复核</div>
                <div className="mt-3 space-y-3">
                  <div>
                    <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">主要阻断</div>
                    <div className="mt-1 break-words text-sm leading-6 text-slate-700">{workbench.primaryBlocker}</div>
                  </div>
                  <div>
                    <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">主要警告</div>
                    <div className="mt-1 break-words text-sm leading-6 text-slate-700">{workbench.primaryWarning}</div>
                  </div>
                  <div>
                    <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">下一个复核动作</div>
                    <div className="mt-1 break-words text-sm leading-6 text-slate-700">{workbench.nextReviewRows[0]}</div>
                  </div>
                </div>
              </div>
            </div>

            <div className="mt-5 grid gap-3 border-t border-[#dfe3eb] pt-4 lg:grid-cols-4">
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">数据源新鲜度</div>
                <div data-testid="dashboard-source-freshness" className="mt-2 space-y-1.5 text-xs leading-5 text-slate-600">
                  {(provenanceSummary.freshnessItems.length ? provenanceSummary.freshnessItems : [{
                    key: 'freshness:none',
                    label: 'No source freshness recorded',
                    status: 'WAIT',
                    freshness: 'unknown',
                    detail: 'No source freshness recorded',
                  }]).slice(0, 4).map((item) => (
                    <div key={item.key} className="rounded-md border border-slate-200 bg-white px-2.5 py-2">
                      <div className="flex items-center justify-between gap-2">
                        <span className="min-w-0 truncate font-semibold text-slate-700">{item.label}</span>
                        <span className={`shrink-0 font-semibold ${statusToneClass(item.status).text}`}>{item.freshness}</span>
                      </div>
                      <div className="mt-0.5 line-clamp-1 text-[11px] text-slate-500">{item.detail}</div>
                    </div>
                  ))}
                </div>
              </div>
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Fallback 链</div>
                <div className="mt-2 space-y-1.5 text-xs leading-5 text-slate-600">
                  {(provenanceSummary.fallbackChain.length ? provenanceSummary.fallbackChain : ['无 fallback / 降级链']).slice(0, 4).map((item) => (
                    <div key={item} className="rounded-md border border-slate-200 bg-white px-2.5 py-2">{item}</div>
                  ))}
                </div>
              </div>
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">缺失字段</div>
                <div className="mt-2 space-y-1.5 text-xs leading-5 text-slate-600">
                  {(provenanceSummary.missingFields.length ? provenanceSummary.missingFields : ['无核心缺失字段']).slice(0, 6).map((item) => (
                    <div key={item} className="rounded-md border border-slate-200 bg-white px-2.5 py-2">{item}</div>
                  ))}
                </div>
              </div>
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">人工复核点</div>
                <div className="mt-2 space-y-1.5 text-xs leading-5 text-slate-600">
                  {(provenanceSummary.reviewPoints.length ? provenanceSummary.reviewPoints : ['当前无额外人工复核点']).slice(0, 5).map((item) => (
                    <div key={item} className="rounded-md border border-slate-200 bg-white px-2.5 py-2">{item}</div>
                  ))}
                </div>
              </div>
            </div>
          </div>

          <div className="min-w-0 border-t border-[#dfe3eb] pt-5 xl:border-l xl:border-t-0 xl:pl-6 xl:pt-0">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div>
                <div className="text-xs font-medium uppercase tracking-wide text-slate-500">数据源状态</div>
                <div className="mt-1 text-sm text-slate-600">
                  本次个股拉取：{dataSourceReadyRatio} 已就绪。配置页验证连通性，分析页显示当前股票的实际拉取结果。
                </div>
              </div>
            </div>
            {dataSourceList.length === 0 ? (
              <div className="border-y border-slate-100 py-4 text-sm text-slate-500">暂无数据源状态信息。</div>
            ) : (
              <div>
                <div className="overflow-hidden rounded-md border border-[#dfe3eb] bg-white">
                  {visibleDataSourceList.map((source) => {
                    const Icon = dataSourceIcon(source.icon)
                    const isFailed = source.status === 'FAILED'
                    const isNotConfigured = source.status === 'NOT_CONFIGURED'
                    const toneStatus = isFailed ? 'FAIL' : isNotConfigured ? 'WARN' : 'PASS'
                    const tone = statusToneClass(toneStatus)
                    const WifiIcon = isFailed ? WifiOff : isNotConfigured ? WifiOff : Wifi

                    return (
                      <div key={source.key} className="grid gap-3 border-b border-slate-100 px-3 py-3 last:border-b-0 sm:grid-cols-[auto_minmax(0,1fr)_auto]">
                        <div className={`grid h-8 w-8 shrink-0 place-items-center rounded-md ${tone.soft}`}>
                          <Icon size={16} />
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="break-words text-sm font-medium text-slate-950">{source.name}</span>
                            <span className={`rounded-md px-1.5 py-0.5 text-[10px] font-semibold ${tone.soft}`}>
                              {dataSourceStatusLabel(source.status)}
                            </span>
                            {source.category ? <span className="text-[10px] text-slate-400">{source.category}</span> : null}
                          </div>
                          <div className="mt-1 text-xs leading-5 text-slate-500">{dataSourceDetail(source)}</div>
                          {source.fetchedAt ? (
                            <div className="mt-0.5 text-[10px] text-slate-400">获取时间：{formatDateTime(source.fetchedAt)}</div>
                          ) : null}
                        </div>
                        <WifiIcon size={14} className={`mt-1 shrink-0 ${tone.text}`} />
                      </div>
                    )
                  })}
                </div>
                {hiddenDataSourceCount > 0 ? (
                  <button
                    type="button"
                    onClick={() => setDataSourcesExpanded((value) => !value)}
                    className="mt-3 inline-flex h-8 w-full items-center justify-center gap-2 rounded-md border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-600 transition hover:bg-slate-50"
                  >
                    {dataSourcesExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                    {dataSourcesExpanded ? '收起数据源' : `展开其余 ${hiddenDataSourceCount} 个数据源`}
                  </button>
                ) : null}
              </div>
            )}

            <div className="mt-4 border-t border-[#dfe3eb] pt-4">
              <div className="text-xs font-medium uppercase tracking-wide text-slate-500">来源明细</div>
              <div className="mt-2 overflow-hidden rounded-md border border-[#dfe3eb] bg-white">
                {provenanceSummary.items.slice(0, 6).map((item) => (
                  <div key={item.key} className="border-b border-slate-100 px-3 py-2.5 last:border-b-0">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="min-w-0">
                        <div className="break-words text-sm font-medium text-slate-950">{item.label}</div>
                        <div className="mt-0.5 break-words text-xs text-slate-500">{item.provider || item.detail}</div>
                      </div>
                      <Badge status={item.status}>{item.kindLabel}</Badge>
                    </div>
                    <div className="mt-1 line-clamp-2 text-xs leading-5 text-slate-500">{item.detail}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </Card>

      <div className="grid gap-4">
        <Card title="Agent 执行链">
          <div data-testid="dashboard-agent-chain">
          {sortedAgents.length === 0 ? (
            <div className="rounded-md bg-slate-50 p-4 text-sm text-slate-500">
              暂无 Agent 执行数据。创建或刷新一次分析任务后会自动生成。
            </div>
          ) : (
            <div className="max-h-[300px] sm:max-h-[420px] overflow-y-auto space-y-2 pr-1">
              {sortedAgents.map((agent, index) => {
                const isSkipped = agent.isSkipped
                const isBlocked = agent.isBlocked
                const isCompatibilityOnly = agent.legacyCompatibilityOnly === true || agent.activeNode === false
                const bgClass = isSkipped
                  ? 'bg-slate-100/70 border-slate-200'
                  : isCompatibilityOnly
                    ? 'bg-slate-100/80 border-slate-200'
                    : isBlocked
                      ? 'bg-red-50/60 border-red-200'
                      : 'bg-slate-50 border-slate-200'
                const agentReason = agent.skippedReason
                  || (isCompatibilityOnly ? `兼容别名 -> ${agent.canonicalNode || 'canonical'}` : '')
                  || agent.reason
                  || agent.node

                return (
                  <div
                    key={agent.node}
                    className={`flex items-center gap-3 rounded-md border px-3 py-2 transition-colors ${bgClass}`}
                  >
                    <div
                      className={`grid h-7 w-7 shrink-0 place-items-center rounded-md text-xs font-semibold ${
                        isSkipped
                          ? 'bg-slate-200 text-slate-400'
                          : isBlocked
                            ? 'bg-red-100 text-red-600'
                            : 'bg-white text-slate-500'
                      }`}
                    >
                      {isSkipped ? <SkipForward size={12} /> : index + 1}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className={`truncate text-sm font-semibold ${isSkipped || isCompatibilityOnly ? 'text-slate-400' : 'text-slate-950'}`}>
                        {agent.name}
                      </div>
                      <div className={`truncate text-xs ${isSkipped || isCompatibilityOnly ? 'text-slate-400 italic' : 'text-slate-500'}`}>
                        {agentReason}
                      </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-1.5">
                      {isCompatibilityOnly && (
                        <span data-testid={`dashboard-agent-compatibility-${agent.node}`} className="rounded-full bg-slate-200 px-1.5 py-0.5 text-[10px] font-medium text-slate-500">
                          兼容
                        </span>
                      )}
                      {isSkipped && (
                        <span className="rounded-full bg-slate-200 px-1.5 py-0.5 text-[10px] font-medium text-slate-500">
                          跳过
                        </span>
                      )}
                      {isBlocked && !isSkipped && (
                        <span className="rounded-full bg-red-100 px-1.5 py-0.5 text-[10px] font-medium text-red-600">
                          阻断
                        </span>
                      )}
                      <Badge status={statusBadgeLabel(agent.status)}>{statusBadgeLabel(agent.status)}</Badge>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
          </div>
        </Card>
      </div>

      {positionBudgetCard}

      <KnowledgeRegressionCard
        loading={knowledgeRegressionLoading}
        error={knowledgeRegressionError}
        version={knowledgeRegressionVersion}
        regression={knowledgeRegression}
        affectedModules={knowledgeRegressionAffectedModules}
        warnings={knowledgeRegressionAllWarnings}
      />
      <LlmLiveCallHealthCard
        health={productionHealth}
        loading={productionHealthLoading}
        error={productionHealthError}
      />
      <ResearchClosedLoopEntryCard
        creating={closedLoopCreating}
        error={closedLoopError}
        result={closedLoopResult}
        canCreate={canCreateResearchClosedLoop}
        disabledReason={closedLoopDisabledReason}
        operatorRole={operator.role}
        onCreate={handleCreateClosedLoopSample}
      />
    </div>
  )
}
