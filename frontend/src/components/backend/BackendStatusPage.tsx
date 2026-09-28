import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { SectionTitle } from '../common/SectionTitle'
import { Card } from '../common/Card'
import { Badge } from '../common/Badge'
import { DataModeBadge } from '../common/DataModeBadge'
import { EvidenceLedger, MetricTile, SourceFreshnessPanel, TableShell } from '../common/Material'
import {
  dispatchProductionAlerts,
  getAnalysisJobAttempts,
  getAnalysisJobs,
  getAnalysisJobSummary,
  getBackendHealth,
  getBackendMetrics,
  getOpsLogExport,
  getOpsLogStatus,
  getProductionAlertExport,
  getProductionAlertStatus,
  getStartupStatus,
  handoffProductionAlertExport,
  handoffOpsLogExport,
  queryOpsLogs,
  type OpsLogExportBundle,
  type OpsLogExportHandoff,
  type OpsLogQueryResult,
  type OpsLogStatus,
  type ProductionHealthMetric,
  type ProductionAlertChannelStatus,
  type ProductionAlertExportBundle,
  type ProductionAlertExportHandoff,
  type ProductionHealth,
  type ProductionHealthWindow,
} from '../../api/analysisClient'
import { getMarketDataAdapters } from '../../api/agentRuntimeClient'
import { useAnalysisStore } from '../../store/useAnalysisStore'
import { clearOperatorApiToken, operatorRoles, roleAllows, setOperatorApiToken, setOperatorContext, useOperatorContext } from '../../store/operatorContext'
import { AnalysisJob, AnalysisJobAttempt, AnalysisJobSummary, BackendHealth, DataSourceHealth, DataSourceStatus, FallbackStep, StartupStatus } from '../../types'
import { Activity, ArrowDown, CheckCircle2, Clock, Cpu, Database, GitBranch, Layers, TrendingUp, XCircle, Zap, AlertTriangle } from 'lucide-react'

const ANALYSIS_JOB_PAGE_SIZE = 12
const ANALYSIS_JOB_STATUS_FILTERS: Record<string, { label: string; statuses: string[] }> = {
  all: { label: 'All jobs', statuses: [] },
  active: { label: 'Active', statuses: ['PENDING', 'QUEUED', 'RUNNING', 'CANCEL_REQUESTED'] },
  failed: { label: 'Failed / stale', statuses: ['FAILED', 'STALE'] },
  completed: { label: 'Completed', statuses: ['COMPLETED'] },
  cancelled: { label: 'Cancelled', statuses: ['CANCELLED'] },
}

function formatDuration(ms: number) {
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

function PerformanceBar({ label, value, max, color = 'bg-cyan-500' }: { label: string; value: number; max: number; color?: string }) {
  const pct = Math.min(100, Math.max(0, (value / max) * 100))
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className="text-slate-600">{label}</span>
        <span className="font-mono text-slate-500">{formatDuration(value)}</span>
      </div>
      <div className="h-1.5 w-full rounded-full bg-slate-100">
        <div className={`h-1.5 rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

function ConfidenceBar({ value, label }: { value: number; label?: string }) {
  const pct = Math.min(100, Math.max(0, value * 100))
  const color = pct >= 85 ? 'bg-emerald-500' : pct >= 60 ? 'bg-amber-500' : 'bg-red-500'
  return (
    <div className="space-y-1">
      {label && <div className="text-xs text-slate-500">{label}</div>}
      <div className="h-2 w-full rounded-full bg-slate-100">
        <div className={`h-2 rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <div className="text-xs font-mono text-slate-600">{pct.toFixed(0)}%</div>
    </div>
  )
}

function FreshnessBadge({ freshness }: { freshness?: string }) {
  const map: Record<string, { label: string; color: string }> = {
    REALTIME: { label: '实时', color: 'bg-emerald-100 text-emerald-700' },
    DELAYED_15MIN: { label: '延迟15分', color: 'bg-cyan-100 text-cyan-700' },
    EOD: { label: '日终', color: 'bg-amber-100 text-amber-700' },
    STALE: { label: '过期', color: 'bg-red-100 text-red-700' },
    UNKNOWN: { label: '未知', color: 'bg-slate-100 text-slate-500' },
  }
  const m = freshness ? map[freshness] : map.UNKNOWN
  return <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${m?.color ?? map.UNKNOWN.color}`}>{m?.label ?? freshness ?? '未知'}</span>
}

function percentLabel(value?: number | null) {
  return typeof value === 'number' ? `${(value * 100).toFixed(1)}%` : 'N/A'
}

function signedPercentLabel(value?: number | null) {
  return typeof value === 'number' ? `${value > 0 ? '+' : ''}${(value * 100).toFixed(1)}%` : 'N/A'
}

function directPercentLabel(value?: number | null) {
  return typeof value === 'number' ? `${value.toFixed(1)}%` : 'N/A'
}

function percentWidth(value?: number | null) {
  return typeof value === 'number' && Number.isFinite(value) ? Math.max(0, Math.min(100, value * 100)) : 0
}

function directPercentWidth(value?: number | null) {
  return typeof value === 'number' && Number.isFinite(value) ? Math.max(0, Math.min(100, value)) : 0
}

function errorBudgetTrendLabel(window: ProductionHealthWindow) {
  const status = window.errorBudget.status ?? 'unknown'
  const consumed = directPercentLabel(window.errorBudget.consumedPercent)
  return `${status} / ${consumed}`
}

function llmFailureReasonRows(metric?: ProductionHealthMetric) {
  const reasons = Array.isArray(metric?.failureReasons)
    ? metric.failureReasons
        .map((item) => ({
          reason: String(item?.reason || '').trim(),
          count: Number.isFinite(Number(item?.count)) ? Number(item?.count) : 0,
        }))
        .filter((item) => item.reason)
    : []
  if (reasons.length > 0) return reasons.slice(0, 4)
  const seen = new Set<string>()
  return (metric?.sampleFailures ?? [])
    .map((item) => String(item?.reason || '').trim())
    .filter((reason) => {
      if (!reason || seen.has(reason)) return false
      seen.add(reason)
      return true
    })
    .slice(0, 4)
    .map((reason) => ({ reason, count: 1 }))
}

function ProductionHealthPanel({ health, onRefresh }: { health: ProductionHealth | null; onRefresh: () => void }) {
  const window24h = health?.windows?.['24h']
  const healthTrendRows = (['24h', '7d', '30d'] as const)
    .map((label) => ({ label, window: health?.windows?.[label] }))
    .filter((row): row is { label: '24h' | '7d' | '30d'; window: ProductionHealthWindow } => Boolean(row.window))
  const sourceErrorEntries = Object.entries(health?.sourceErrors ?? {})
  const llmFailureRows = llmFailureReasonRows(window24h?.llmCallFailureRate)
  const llmSampleFailures = (window24h?.llmCallFailureRate.sampleFailures ?? []).slice(0, 3)
  const trend = health?.trend
  const longTrend = health?.longTrend
  const trendBaselineWindow = trend?.baselineWindow || 'N/A'
  const longTrendBaselineWindow = longTrend?.baselineWindow || 'N/A'
  const badge = health?.status === 'healthy' ? 'PASS' : health?.status === 'critical' ? 'FAIL' : health ? 'WARN' : 'WAIT'
  const healthRailRows = [
    { label: '运行成功', value: percentWidth(window24h?.runSuccessRate.successRate), display: percentLabel(window24h?.runSuccessRate.successRate), color: 'bg-emerald-500' },
    { label: 'LLM 成功', value: 100 - percentWidth(window24h?.llmCallFailureRate.failureRate), display: percentLabel(window24h ? 1 - (window24h.llmCallFailureRate.failureRate ?? 0) : null), color: 'bg-cyan-500' },
    { label: '错误预算', value: 100 - directPercentWidth(window24h?.errorBudget.consumedPercent), display: errorBudgetTrendLabel(window24h ?? ({ errorBudget: { status: 'unknown' } } as ProductionHealthWindow)), color: 'bg-blue-500' },
    { label: '行情降级', value: 100 - percentWidth(window24h?.marketDataFallbackRate.fallbackRate), display: percentLabel(window24h?.marketDataFallbackRate.fallbackRate), color: 'bg-amber-500' },
    { label: 'SignalOps 轮询', value: percentWidth(window24h?.signalOpsTickSuccessRate.successRate), display: percentLabel(window24h?.signalOpsTickSuccessRate.successRate), color: 'bg-teal-500' },
  ]
  const llmFailureLedgerRows = llmFailureRows.map((item) => ({
    label: item.reason,
    source: 'LLM',
    status: `${item.count}x`,
    detail: `24h failed ${window24h?.llmCallFailureRate.failed ?? 0} / total ${window24h?.llmCallFailureRate.total ?? 0}`,
    strength: window24h?.llmCallFailureRate.failed ? Math.round((item.count / window24h.llmCallFailureRate.failed) * 100) : 0,
  }))
  return (
    <Card
      title="生产健康"
      action={(
        <button
          type="button"
          data-testid="backend-production-health-refresh"
          onClick={onRefresh}
          className="rounded-md border border-slate-200 bg-white px-3 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50"
        >
          刷新
        </button>
      )}
    >
      {health && window24h ? (
        <div data-testid="backend-production-health" className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <Badge status={badge}>{health.status}</Badge>
            <span className="text-xs text-slate-500">Generated {health.generatedAt}</span>
            <span className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
              external calls: {health.externalCalls ? 'yes' : 'no'}
            </span>
          </div>
          <div className="rounded-lg border border-slate-200 bg-white px-3 py-3">
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">运行健康条 / 24h</div>
              <span className="text-xs text-slate-500">错误、降级和轮询以越满越健康展示</span>
            </div>
            <div className="grid gap-2 md:grid-cols-5">
              {healthRailRows.map((row) => (
                <div key={row.label} className="min-w-0 rounded-md border border-slate-100 bg-slate-50 px-2 py-2">
                  <div className="flex items-center justify-between gap-2 text-xs">
                    <span className="truncate font-medium text-slate-700">{row.label}</span>
                    <span className="shrink-0 font-mono text-slate-500">{row.display}</span>
                  </div>
                  <div className="mt-2 h-1.5 rounded-full bg-white">
                    <div className={`h-1.5 rounded-full ${row.color}`} style={{ width: `${row.value}%` }} />
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div className="grid gap-3 md:grid-cols-3">
            <MetricTile className="!rounded-lg !p-3 !shadow-none" label="运行成功 / 24h" value={percentLabel(window24h.runSuccessRate.successRate)} helper={`${window24h.runSuccessRate.succeeded ?? 0}/${window24h.runSuccessRate.total ?? 0} completed`} tone="success" />
            <MetricTile className="!rounded-lg !p-3 !shadow-none" label="LLM 失败 / 24h" value={percentLabel(window24h.llmCallFailureRate.failureRate)} helper={`${window24h.llmCallFailureRate.failed ?? 0}/${window24h.llmCallFailureRate.total ?? 0} failed`} tone={window24h.llmCallFailureRate.failureRate ? 'warning' : 'success'} />
            <MetricTile className="!rounded-lg !p-3 !shadow-none" label="错误预算" value={window24h.errorBudget.status ?? 'unknown'} helper={`${window24h.errorBudget.consumedPercent ?? 'N/A'}% consumed`} tone={window24h.errorBudget.status === 'ok' ? 'success' : 'warning'} />
          </div>
          <div data-testid="backend-production-health-trend-deltas" className="rounded-md border border-slate-200 bg-white p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="text-xs font-medium text-slate-500">生产趋势变化</div>
              <span className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-500">基线 {trendBaselineWindow}</span>
            </div>
            <div className="mt-2 grid gap-2 md:grid-cols-5">
              <div className="min-h-16 rounded-md bg-slate-50 p-2">
                <div className="text-xs text-slate-500">运行成功</div>
                <div className="mt-1 font-mono text-sm font-semibold text-slate-900">{signedPercentLabel(trend?.runSuccessRateDelta)}</div>
                <div className="mt-1 text-[11px] text-slate-500">对比 / vs {longTrendBaselineWindow}: {signedPercentLabel(longTrend?.runSuccessRateDelta)}</div>
              </div>
              <div className="min-h-16 rounded-md bg-slate-50 p-2">
                <div className="text-xs text-slate-500">LLM 成功</div>
                <div className="mt-1 font-mono text-sm font-semibold text-slate-900">{signedPercentLabel(trend?.llmSuccessRateDelta)}</div>
                <div className="mt-1 text-[11px] text-slate-500">对比 / vs {longTrendBaselineWindow}: {signedPercentLabel(longTrend?.llmSuccessRateDelta)}</div>
              </div>
              <div className="min-h-16 rounded-md bg-slate-50 p-2">
                <div className="text-xs text-slate-500">LLM 失败</div>
                <div className="mt-1 font-mono text-sm font-semibold text-slate-900">{signedPercentLabel(trend?.llmFailureRateDelta)}</div>
                <div className="mt-1 text-[11px] text-slate-500">对比 / vs {longTrendBaselineWindow}: {signedPercentLabel(longTrend?.llmFailureRateDelta)}</div>
              </div>
              <div className="min-h-16 rounded-md bg-slate-50 p-2">
                <div className="text-xs text-slate-500">行情降级</div>
                <div className="mt-1 font-mono text-sm font-semibold text-slate-900">{signedPercentLabel(trend?.marketDataFallbackRateDelta)}</div>
                <div className="mt-1 text-[11px] text-slate-500">对比 / vs {longTrendBaselineWindow}: {signedPercentLabel(longTrend?.marketDataFallbackRateDelta)}</div>
              </div>
              <div className="min-h-16 rounded-md bg-slate-50 p-2">
                <div className="text-xs text-slate-500">SignalOps 轮询</div>
                <div className="mt-1 font-mono text-sm font-semibold text-slate-900">{signedPercentLabel(trend?.signalOpsTickSuccessRateDelta)}</div>
                <div className="mt-1 text-[11px] text-slate-500">对比 / vs {longTrendBaselineWindow}: {signedPercentLabel(longTrend?.signalOpsTickSuccessRateDelta)}</div>
              </div>
            </div>
          </div>
          {llmFailureRows.length > 0 ? (
            <div data-testid="backend-production-health-llm-failure-reasons" className="rounded-md border border-slate-200 bg-slate-50 p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="text-xs font-medium text-slate-500">LLM 失败原因 / 24h</div>
                <span className="text-xs text-slate-500">{window24h.llmCallFailureRate.failed ?? 0} 失败 / {window24h.llmCallFailureRate.total ?? 0} 总数</span>
              </div>
              <EvidenceLedger rows={llmFailureLedgerRows} className="mt-2 !rounded-lg !shadow-none" />
              {llmSampleFailures.length > 0 ? (
                <div className="mt-2 space-y-1">
                  {llmSampleFailures.map((item, index) => (
                    <div key={`${item.runId || 'run'}-${item.node || 'node'}-${index}`} className="text-[11px] leading-4 text-slate-500">
                      sample: {item.runId || 'unknown run'} / {item.node || 'unknown node'} / {item.status || 'FAILED'}
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}
          <div className="grid gap-3 md:grid-cols-3">
            <MetricTile className="!rounded-lg !p-3 !shadow-none" label="行情降级" value={percentLabel(window24h.marketDataFallbackRate.fallbackRate)} tone={window24h.marketDataFallbackRate.fallbackRate ? 'warning' : 'success'} />
            <MetricTile className="!rounded-lg !p-3 !shadow-none" label="SignalOps 轮询成功率" value={percentLabel(window24h.signalOpsTickSuccessRate.successRate)} tone="info" />
            <MetricTile className="!rounded-lg !p-3 !shadow-none" label="停滞任务" value={window24h.staleJobs.currentCount ?? 0} tone={window24h.staleJobs.currentCount ? 'warning' : 'success'} />
          </div>
          {healthTrendRows.length > 0 ? (
            <div className="space-y-2">
              <div className="text-xs font-medium text-slate-500">健康趋势</div>
              <div data-testid="backend-production-health-trends">
                <TableShell className="!rounded-lg !shadow-none">
                <table className="institution-table min-w-[760px]">
                  <thead>
                    <tr>
                      <th>窗口</th>
                      <th>运行成功</th>
                      <th>LLM 失败</th>
                      <th>行情降级</th>
                      <th>SignalOps 轮询</th>
                      <th>停滞任务</th>
                      <th>错误预算</th>
                    </tr>
                  </thead>
                  <tbody>
                    {healthTrendRows.map((row) => (
                      <tr key={row.label}>
                        <td className="font-medium text-slate-900">{row.label}</td>
                        <td>{percentLabel(row.window.runSuccessRate.successRate)}</td>
                        <td>{percentLabel(row.window.llmCallFailureRate.failureRate)}</td>
                        <td>{percentLabel(row.window.marketDataFallbackRate.fallbackRate)}</td>
                        <td>{percentLabel(row.window.signalOpsTickSuccessRate.successRate)}</td>
                        <td>{row.window.staleJobs.currentCount ?? 0}</td>
                        <td>{errorBudgetTrendLabel(row.window)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                </TableShell>
              </div>
            </div>
          ) : null}
          {health.alerts.length > 0 && (
            <div data-testid="backend-production-health-alerts" className="space-y-2">
              <div className="text-xs font-medium text-slate-500">告警</div>
              {health.alerts.slice(0, 4).map((alert, index) => (
                <div key={`${alert.metric}-${alert.window}-${index}`} className="rounded-md bg-amber-50 p-2 text-xs text-amber-800">
                  {alert.severity.toUpperCase()} / {alert.window} / {alert.metric}: {alert.message}
                </div>
              ))}
            </div>
          )}
          {sourceErrorEntries.length > 0 && (
            <div data-testid="backend-production-health-source-errors" className="space-y-2">
              <div className="text-xs font-medium text-slate-500">数据源错误</div>
              {sourceErrorEntries.slice(0, 4).map(([source, message]) => (
                <div key={source} className="rounded-md bg-rose-50 p-2 text-xs text-rose-700">
                  <span className="font-medium">{source}</span>: {message}
                </div>
              ))}
            </div>
          )}
        </div>
      ) : (
        <div className="text-sm text-slate-500">生产健康指标暂不可用。</div>
      )}
    </Card>
  )
}

function ProductionAlertChannelPanel({
  status,
  role,
  loading,
  error,
  canDispatch,
  adminDisabledReason,
  dispatching,
  dispatchSummary,
  exportBundle,
  exporting,
  exportSummary,
  handoffResult,
  handoffBusy,
  handoffSummary,
  canHandoff,
  onDispatch,
  onExport,
  onHandoff,
  onRefresh,
}: {
  status: ProductionAlertChannelStatus | null
  role: string
  loading: boolean
  error: string | null
  canDispatch: boolean
  adminDisabledReason?: string
  dispatching: boolean
  dispatchSummary: string
  exportBundle: ProductionAlertExportBundle | null
  exporting: boolean
  exportSummary: string
  handoffResult: ProductionAlertExportHandoff | null
  handoffBusy: boolean
  handoffSummary: string
  canHandoff: boolean
  onDispatch: () => void
  onExport: () => void
  onHandoff: () => void
  onRefresh: () => void
}) {
  const latest = status?.latest?.[0]
  const criticalCount = status?.counts_by_severity?.critical ?? 0
  const warningCount = status?.counts_by_severity?.warning ?? 0
  const retention = status?.retention_policy
  const alertRulePolicy = status?.alert_rule_policy
  const alertRuleProviderAcceptance = alertRulePolicy?.provider_acceptance
  const alertShipperStatus = status?.handoff_status?.shipper_status
  const primaryAlertRule = alertRulePolicy?.rules?.[0]
  return (
    <Card title="生产告警通道">
      <div data-testid="backend-production-alert-channel" className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <Badge status={status?.enabled ? 'PASS' : 'WAIT'}>{status?.channel ?? 'local_file_outbox'}</Badge>
          <span className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
            external delivery: {status?.external_delivery_enabled ? 'enabled' : 'disabled'}
          </span>
          <span data-testid="backend-production-alert-provider" className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
            提供方：{status?.external_provider ?? '未启用'} / {status?.external_delivery_status ?? '未启用'}
          </span>
          <span data-testid="backend-production-alert-retry" className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
            attempts: {status?.external_delivery_attempt_limit ?? 0}
          </span>
          <span data-testid="backend-production-alert-export-ready" className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
            外部聚合：{status ? (status.external_aggregation_ready ? '可导出 / export-ready' : '仅本地 / local-only') : '加载中'}
          </span>
          <span data-testid="backend-production-alert-admin-role" className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
            角色：{role}；派发/交接：{canHandoff ? 'admin' : '已阻断'}
          </span>
          <span className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
            queued: {status?.queue_size ?? 0}
          </span>
          <span data-testid="backend-production-alert-admin-disabled-reason" className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
            {adminDisabledReason || '生产告警派发和交接需要 admin 权限。'}
          </span>
        </div>
        <div className="grid gap-2 text-xs text-slate-600 sm:grid-cols-3">
          <div className="rounded-md border border-slate-200 p-2">
            <div className="font-medium text-slate-900">{criticalCount}</div>
            <div>已记录严重告警</div>
          </div>
          <div className="rounded-md border border-slate-200 p-2">
            <div className="font-medium text-slate-900">{warningCount}</div>
            <div>已记录警告</div>
          </div>
          <div className="rounded-md border border-slate-200 p-2">
            <div className="font-medium text-slate-900">{status?.last_event_at || '无'}</div>
            <div>最近事件</div>
          </div>
        </div>
        <div className="break-all rounded-md bg-slate-50 p-2 text-xs text-slate-500">
          {status?.outbox_file ?? '发件箱路径暂不可用。'}
        </div>
        <div data-testid="backend-production-alert-export-policy" className="grid gap-2 text-xs text-slate-600 sm:grid-cols-3">
          <div className="rounded-md border border-slate-200 p-2">
            <div className="font-medium text-slate-900">导出</div>
            <div data-testid="backend-production-alert-export-endpoint" className="mt-1 break-all text-slate-500">
              {status?.export_endpoint ?? '/api/ops/alerts/export'} / {status?.export_schema ?? 'production_alert_outbox_export_v1'}
            </div>
            <div data-testid="backend-production-alert-handoff-status" className="mt-1 break-all text-slate-500">
              交接：{status?.handoff_status?.status ?? 'NOT_CONFIGURED'} / {status?.handoff_status?.handoff_destination ?? 'NOT_CONFIGURED'} / {status?.handoff_status?.manifest_schema ?? 'production_alert_outbox_export_handoff_manifest_v1'}
            </div>
            <div data-testid="backend-production-alert-handoff-integrity" className="mt-1 break-all text-slate-500">
              完整性：{status?.handoff_status?.inventory?.status ?? 'NOT_CONFIGURED'} / verified {status?.handoff_status?.inventory?.verified_count ?? 0}/{status?.handoff_status?.inventory?.manifest_count ?? 0} / 不匹配 {status?.handoff_status?.inventory?.checksum_mismatch_count ?? 0}
            </div>
            <div data-testid="backend-production-alert-shipper-status" className="mt-1 break-all text-slate-500">
              shipper: {alertShipperStatus?.status ?? 'NOT_CONFIGURED'} / {alertShipperStatus?.provider || alertShipperStatus?.source || 'deployment-sidecar'} / latest match {alertShipperStatus?.matches_latest_inventory ? 'yes' : 'no'}
            </div>
            <div data-testid="backend-production-alert-shipper-readiness" className="mt-1 break-all text-slate-500">
              提供方就绪：search ready {alertShipperStatus?.search_index_ready ? 'yes' : 'no'}
              {' '} / 留存 {alertShipperStatus?.retention_status || alertShipperStatus?.retention_policy_id || '未上报'}
              {' '} / 托管 {alertShipperStatus?.custody_status || '未上报'}
              {alertShipperStatus?.remote_object_key ? ` / 对象 ${alertShipperStatus.remote_object_key}` : ''}
            </div>
          </div>
          <div className="rounded-md border border-slate-200 p-2">
            <div className="font-medium text-slate-900">保留策略</div>
            <div className="mt-1 text-slate-500">
              {retention?.mode ?? 'local_bounded_event_count'} / max {retention?.max_events ?? 'N/A'} events
            </div>
          </div>
          <div data-testid="backend-production-alert-rule-policy" className="rounded-md border border-slate-200 p-2">
            <div className="font-medium text-slate-900">告警规则</div>
            <div className="mt-1 break-all text-slate-500">
              策略：{alertRulePolicy?.status ?? 'DEFAULT'} / {alertRulePolicy?.schema ?? 'production_alert_rule_policy_v1'}
            </div>
            <div className="mt-1 break-all text-slate-500">
              提供方 {alertRulePolicy?.provider ?? status?.external_provider ?? '未启用'} / 规则 {alertRulePolicy?.rule_count ?? alertRulePolicy?.rules?.length ?? 0}
            </div>
            <div className="mt-1 break-all text-slate-500">
              路由 {primaryAlertRule?.routing_key ?? 'ops-default'} / 升级 {primaryAlertRule?.escalation_target ?? 'operator_review'}
            </div>
            <div data-testid="backend-production-alert-rule-provider-acceptance" className="mt-1 break-all text-slate-500">
              提供方验收：{alertRuleProviderAcceptance?.status ?? 'NOT_CONFIGURED'} / {alertRuleProviderAcceptance?.schema ?? 'production_alert_rule_provider_acceptance_v1'}
              {' '} / {alertRuleProviderAcceptance?.provider || alertRuleProviderAcceptance?.source || 'deployment-sidecar'}
              {' '} / policy match {alertRuleProviderAcceptance?.matches_policy ? 'yes' : 'no'}
              {' '} / rules {alertRuleProviderAcceptance?.rules_accepted ?? 0}/{alertRuleProviderAcceptance?.rules_total ?? alertRulePolicy?.rule_count ?? 0}
            </div>
          </div>
        </div>
        {latest ? (
          <div data-testid="backend-production-alert-latest" className="rounded-md bg-amber-50 p-2 text-xs text-amber-800">
            {latest.severity.toUpperCase()} / {latest.window} / {latest.metric}: {latest.message}
            <div className="mt-1 text-amber-700">
              投递：{latest.delivery_status}{latest.external_provider ? ` / ${latest.external_provider}` : ''}
              {latest.delivery_attempt_count ? ` / attempts ${latest.delivery_attempt_count}/${latest.delivery_attempt_limit ?? latest.delivery_attempt_count}` : ''}
            </div>
            {latest.alert_rule_id ? (
              <div className="mt-1 text-amber-700">
                规则：{latest.alert_rule_id} / 路由 {latest.alert_routing_key || 'ops-default'} / 升级 {latest.alert_escalation_target || 'operator_review'}
              </div>
            ) : null}
            {latest.delivery_error ? <div className="mt-1 break-words text-rose-700">{latest.delivery_error}</div> : null}
          </div>
        ) : (
          <div className="rounded-md border border-dashed border-slate-200 p-3 text-sm text-slate-500">
            本地发件箱尚未记录生产告警。
          </div>
        )}
        {dispatchSummary ? <div data-testid="backend-production-alert-dispatch-result" className="text-xs text-slate-600">{dispatchSummary}</div> : null}
        {(exportSummary || exportBundle) ? (
          <div data-testid="backend-production-alert-export-result" className="break-all text-xs text-slate-600">
            {exportSummary || `${exportBundle?.schema ?? 'production_alert_outbox_export_v1'} / ${exportBundle?.checksum ?? ''}`}
          </div>
        ) : null}
        {(handoffSummary || handoffResult) ? (
          <div data-testid="backend-production-alert-handoff-result" className="break-all text-xs text-slate-600">
            {handoffSummary || `${handoffResult?.schema ?? 'production_alert_outbox_export_handoff_v1'} / ${handoffResult?.status ?? 'DISABLED'} / ${handoffResult?.handoff_destination ?? 'NOT_CONFIGURED'} / ${handoffResult?.bundle_checksum ?? ''}`}
          </div>
        ) : null}
        {error ? <div className="rounded-md border border-rose-100 bg-rose-50 px-3 py-2 text-xs text-rose-700">{error}</div> : null}
        {loading ? <div className="text-xs text-slate-500">正在加载告警通道...</div> : null}
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            data-testid="backend-production-alert-dispatch"
            onClick={onDispatch}
            disabled={!canDispatch || dispatching}
            title={adminDisabledReason}
            className="rounded-md border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {dispatching ? '派发中...' : '派发告警快照'}
          </button>
          <button
            type="button"
            data-testid="backend-production-alert-export"
            onClick={onExport}
            disabled={exporting}
            className="rounded-md border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {exporting ? '导出中...' : '导出包'}
          </button>
          <button
            type="button"
            data-testid="backend-production-alert-handoff"
            onClick={onHandoff}
            disabled={!canHandoff || handoffBusy}
            title={adminDisabledReason}
            className="rounded-md border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {handoffBusy ? '交接中...' : '交接导出'}
          </button>
          <button
            type="button"
            data-testid="backend-production-alert-refresh"
            onClick={onRefresh}
            className="rounded-md border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
          >
            刷新
          </button>
          {!canDispatch || !canHandoff ? <span className="self-center text-xs text-slate-500">派发和交接需要 admin 角色。</span> : null}
        </div>
      </div>
    </Card>
  )
}

function OpsLogPanel({
  status,
  role,
  loading,
  error,
  exportBundle,
  exporting,
  exportSummary,
  handoffResult,
  handoffBusy,
  handoffSummary,
  queryResult,
  querying,
  queryText,
  canHandoff,
  handoffDisabledReason,
  onExport,
  onHandoff,
  onQuery,
  onQueryTextChange,
  onRefresh,
}: {
  status: OpsLogStatus | null
  role: string
  loading: boolean
  error: string | null
  exportBundle: OpsLogExportBundle | null
  exporting: boolean
  exportSummary: string
  handoffResult: OpsLogExportHandoff | null
  handoffBusy: boolean
  handoffSummary: string
  queryResult: OpsLogQueryResult | null
  querying: boolean
  queryText: string
  canHandoff: boolean
  handoffDisabledReason?: string
  onExport: () => void
  onHandoff: () => void
  onQuery: () => void
  onQueryTextChange: (value: string) => void
  onRefresh: () => void
}) {
  const latest = status?.latest?.[0]
  const levelEntries = Object.entries(status?.counts_by_level ?? {})
  const typeEntries = Object.entries(status?.counts_by_type ?? {})
  const retention = status?.retention_policy
  const shipperStatus = status?.handoff_status?.shipper_status
  return (
    <Card title="运维事件日志">
      <div data-testid="backend-ops-log-status" className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <Badge status={status?.enabled ? 'PASS' : 'WAIT'}>{status?.channel ?? 'local_file_jsonl'}</Badge>
          <span className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
            external delivery: {status?.external_delivery_enabled ? 'enabled' : 'disabled'}
          </span>
          <span data-testid="backend-ops-log-export-ready" className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
            外部聚合：{status ? (status.external_aggregation_ready ? '可导出 / export-ready' : '仅本地 / local-only') : '加载中'}
          </span>
          <span data-testid="backend-ops-log-handoff-role" className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
            角色：{role}；交接：{canHandoff ? 'admin' : '已阻断'}
          </span>
          <span className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
            events: {status?.event_count ?? 0}
          </span>
          <span data-testid="backend-ops-log-handoff-disabled-reason" className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
            {handoffDisabledReason || '运维日志交接需要 admin 权限。'}
          </span>
        </div>
        <div className="grid gap-2 text-xs text-slate-600 sm:grid-cols-2">
          <div className="rounded-md border border-slate-200 p-2">
            <div className="font-medium text-slate-900">级别</div>
            <div className="mt-1 flex flex-wrap gap-1">
              {levelEntries.length > 0 ? levelEntries.map(([level, count]) => (
                <span key={level} className="rounded bg-slate-100 px-2 py-0.5">{level}: {count}</span>
              )) : <span className="text-slate-400">无</span>}
            </div>
          </div>
          <div className="rounded-md border border-slate-200 p-2">
            <div className="font-medium text-slate-900">类型</div>
            <div className="mt-1 flex flex-wrap gap-1">
              {typeEntries.length > 0 ? typeEntries.slice(0, 5).map(([type, count]) => (
                <span key={type} className="rounded bg-slate-100 px-2 py-0.5">{type}: {count}</span>
              )) : <span className="text-slate-400">无</span>}
            </div>
          </div>
        </div>
        <div className="break-all rounded-md bg-slate-50 p-2 text-xs text-slate-500">
          {status?.log_file ?? '运维日志路径暂不可用。'}
        </div>
        <div data-testid="backend-ops-log-retention-policy" className="grid gap-2 text-xs text-slate-600 sm:grid-cols-3">
          <div className="rounded-md border border-slate-200 p-2">
            <div className="font-medium text-slate-900">导出</div>
            <div data-testid="backend-ops-log-export-endpoint" className="mt-1 break-all text-slate-500">
              {status?.export_endpoint ?? '/api/ops/logs/export'} / {status?.export_schema ?? 'ops_log_export_v1'}
            </div>
            <div data-testid="backend-ops-log-handoff-status" className="mt-1 break-all text-slate-500">
              交接：{status?.handoff_status?.status ?? 'NOT_CONFIGURED'} / {status?.handoff_status?.handoff_destination ?? 'NOT_CONFIGURED'} / {status?.handoff_status?.manifest_schema ?? 'ops_log_export_handoff_manifest_v1'}
            </div>
            <div data-testid="backend-ops-log-handoff-integrity" className="mt-1 break-all text-slate-500">
              完整性：{status?.handoff_status?.inventory?.status ?? 'NOT_CONFIGURED'} / verified {status?.handoff_status?.inventory?.verified_count ?? 0}/{status?.handoff_status?.inventory?.manifest_count ?? 0} / 不匹配 {status?.handoff_status?.inventory?.checksum_mismatch_count ?? 0}
            </div>
            <div data-testid="backend-ops-log-shipper-status" className="mt-1 break-all text-slate-500">
              shipper: {shipperStatus?.status ?? 'NOT_CONFIGURED'} / {shipperStatus?.provider || shipperStatus?.source || 'deployment-sidecar'} / latest match {shipperStatus?.matches_latest_inventory ? 'yes' : 'no'}
            </div>
            <div data-testid="backend-ops-log-shipper-readiness" className="mt-1 break-all text-slate-500">
              提供方就绪：search ready {shipperStatus?.search_index_ready ? 'yes' : 'no'}
              {' '} / retention {shipperStatus?.retention_status || shipperStatus?.retention_policy_id || 'not reported'}
              {' '} / custody {shipperStatus?.custody_status || 'not reported'}
              {shipperStatus?.remote_object_key ? ` / object ${shipperStatus.remote_object_key}` : ''}
            </div>
          </div>
          <div className="rounded-md border border-slate-200 p-2">
            <div className="font-medium text-slate-900">保留策略</div>
            <div className="mt-1 text-slate-500">
              {retention?.mode ?? 'local_bounded_event_count'} / max {retention?.max_events ?? 'N/A'} events
              {retention?.time_based_retention_enabled ? ` / ${retention.max_age_days ?? 'N/A'} days` : ''}
            </div>
          </div>
          <div className="rounded-md border border-slate-200 p-2">
            <div className="font-medium text-slate-900">查询</div>
            <div data-testid="backend-ops-log-query-endpoint" className="mt-1 break-all text-slate-500">
              {status?.query_endpoint ?? '/api/ops/logs/query'} / {status?.query_schema ?? 'ops_log_query_v1'}
            </div>
            <div className="mt-2 flex flex-wrap gap-2">
              <input
                type="search"
                data-testid="backend-ops-log-query-text"
                value={queryText}
                onChange={(event) => onQueryTextChange(event.target.value)}
                className="min-w-0 flex-1 rounded-md border border-slate-200 px-2 py-1 text-xs text-slate-900 outline-none focus:border-cyan-400"
                placeholder="事件类型、请求 ID 或路径"
              />
              <button
                type="button"
                data-testid="backend-ops-log-query"
                onClick={onQuery}
                disabled={querying}
                className="rounded-md border border-slate-200 px-2 py-1 text-xs font-medium text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {querying ? 'Querying...' : 'Query'}
              </button>
            </div>
          </div>
        </div>
        {latest ? (
          <div data-testid="backend-ops-log-latest" className="rounded-md bg-slate-50 p-2 text-xs text-slate-700">
            <div className="font-medium text-slate-900">
              {latest.level.toUpperCase()} / {latest.event_type} / {latest.source}
            </div>
            <div className="mt-1 break-words">{latest.message}</div>
            <div className="mt-1 text-slate-500">
              {latest.method || 'EVENT'} {latest.path || 'system'} {latest.status_code ? `-> ${latest.status_code}` : ''}
            </div>
          </div>
        ) : (
          <div className="rounded-md border border-dashed border-slate-200 p-3 text-sm text-slate-500">
            No ops events have been recorded in the local log.
          </div>
        )}
        {(exportSummary || exportBundle) ? (
          <div data-testid="backend-ops-log-export-result" className="break-all text-xs text-slate-600">
            {exportSummary || `${exportBundle?.schema ?? 'ops_log_export_v1'} / ${exportBundle?.checksum ?? ''}`}
          </div>
        ) : null}
        {(handoffSummary || handoffResult) ? (
          <div data-testid="backend-ops-log-handoff-result" className="break-all text-xs text-slate-600">
            {handoffSummary || `${handoffResult?.status ?? 'DISABLED'} / ${handoffResult?.handoff_destination ?? 'NOT_CONFIGURED'} / ${handoffResult?.bundle_checksum ?? ''}`}
          </div>
        ) : null}
        {queryResult ? (
          <div data-testid="backend-ops-log-query-result" className="break-all rounded-md bg-slate-50 p-2 text-xs text-slate-600">
            {queryResult.schema} / {queryResult.returned_count}/{queryResult.matched_count} returned / {queryResult.text_filter || 'all'}
            {queryResult.events[0] ? ` / latest ${queryResult.events[0].event_type} ${queryResult.events[0].path || queryResult.events[0].source}` : ' / no matches'}
          </div>
        ) : null}
        {error ? <div className="rounded-md border border-rose-100 bg-rose-50 px-3 py-2 text-xs text-rose-700">{error}</div> : null}
        {loading ? <div className="text-xs text-slate-500">正在加载运维日志...</div> : null}
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            data-testid="backend-ops-log-export"
            onClick={onExport}
            disabled={exporting}
            className="rounded-md border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {exporting ? '导出中...' : '导出包'}
          </button>
          <button
            type="button"
            data-testid="backend-ops-log-handoff"
            onClick={onHandoff}
            disabled={!canHandoff || handoffBusy}
            title={handoffDisabledReason}
            className="rounded-md border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {handoffBusy ? '交接中...' : '交接导出'}
          </button>
          <button
            type="button"
            data-testid="backend-ops-log-refresh"
            onClick={onRefresh}
            className="rounded-md border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
          >
            刷新
          </button>
          {!canHandoff ? <span className="self-center text-xs text-slate-500">交接需要 admin 角色。</span> : null}
        </div>
      </div>
    </Card>
  )
}

function StartupStatusPanel({ status }: { status: StartupStatus | null }) {
  const badge = status?.ready ? 'PASS' : status?.phase === 'DEGRADED' ? 'WARN' : status?.coreReady ? 'WARN' : 'WAIT'
  return (
    <Card title="启动阶段">
      {status ? (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <Badge status={badge}>{status.phase}</Badge>
            <span className="text-xs text-slate-500">core: {status.coreReady ? 'ready' : 'waiting'}</span>
            <span className="text-xs text-slate-500">optional: {status.ready ? 'ready' : 'warming'}</span>
          </div>
          <div className="space-y-2">
            {status.components.map((component) => (
              <div key={component.name} className="rounded-md border border-slate-200 p-2 text-xs">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="font-medium text-slate-800">{component.name}</div>
                  <Badge status={component.status === 'OK' ? 'PASS' : component.status === 'ERROR' ? 'FAIL' : 'WAIT'}>
                    {component.status}
                  </Badge>
                </div>
                <div className="mt-1 flex flex-wrap gap-2 text-slate-500">
                  <span>{component.tier}</span>
                  {typeof component.elapsedMs === 'number' ? <span>{formatDuration(component.elapsedMs)}</span> : null}
                  {component.required ? <span>必需</span> : null}
                </div>
                {component.error ? <div className="mt-1 break-words text-rose-600">{component.error}</div> : null}
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="text-sm text-slate-500">启动状态暂不可用。</div>
      )}
    </Card>
  )
}

function formatTimestamp(value?: string) {
  if (!value) return 'N/A'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleString()
}

function jobAttemptStatus(status?: string) {
  const normalized = (status || 'WAIT').toUpperCase()
  if (normalized === 'COMPLETED') return 'PASS'
  if (normalized === 'FAILED' || normalized === 'STALE') return 'FAIL'
  if (normalized === 'CANCELLED' || normalized === 'CANCEL_REQUESTED') return 'WARN'
  if (normalized === 'RUNNING' || normalized === 'QUEUED') return normalized
  return 'WAIT'
}

function jobStatusCount(jobs: AnalysisJob[], status: string) {
  return jobs.filter((job) => String(job.status || '').toUpperCase() === status).length
}

function leaseBadgeStatus(status?: string) {
  const normalized = (status || 'UNKNOWN').toUpperCase()
  if (normalized === 'ACTIVE' || normalized === 'RELEASED' || normalized === 'UNCLAIMED') return 'PASS'
  if (normalized === 'EXPIRED' || normalized === 'UNLEASED') return 'WARN'
  return 'WAIT'
}

function externalQueueBadgeStatus(status?: string) {
  const normalized = (status || 'UNKNOWN').toUpperCase()
  if (normalized === 'READY') return 'PASS'
  if (normalized === 'FAILED' || normalized === 'INVALID') return 'FAIL'
  if (normalized === 'DEGRADED' || normalized === 'NOT_REPORTED' || normalized === 'NOT_CONFIGURED') return 'WARN'
  return 'WAIT'
}

function AnalysisJobQueuePanel({
  jobs,
  summary,
  offset,
  statusFilter,
  loading,
  error,
  onRefresh,
  onPreviousPage,
  onNextPage,
  onStatusFilterChange,
}: {
  jobs: AnalysisJob[]
  summary: AnalysisJobSummary | null
  offset: number
  statusFilter: string
  loading: boolean
  error: string | null
  onRefresh: () => void
  onPreviousPage: () => void
  onNextPage: () => void
  onStatusFilterChange: (value: string) => void
}) {
  const countsByStatus = summary?.counts_by_status ?? {}
  const queuedCount = countsByStatus.QUEUED ?? jobStatusCount(jobs, 'QUEUED')
  const runningCount = countsByStatus.RUNNING ?? jobStatusCount(jobs, 'RUNNING')
  const staleCount = countsByStatus.STALE ?? jobStatusCount(jobs, 'STALE')
  const failedCount = countsByStatus.FAILED ?? jobStatusCount(jobs, 'FAILED')
  const expiredLeaseCount = jobs.filter((job) => String(job.lease_status || '').toUpperCase() === 'EXPIRED').length
  const activeGroups = new Set(jobs.map((job) => job.concurrency_group).filter(Boolean)).size
  const filteredTotal = summary?.filtered_count ?? jobs.length
  const hasOlder = summary ? summary.has_more : jobs.length >= ANALYSIS_JOB_PAGE_SIZE
  const externalQueueStatus = summary?.external_queue_status

  return (
    <Card title="分析任务队列">
      <div data-testid="backend-analysis-job-queue" className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap gap-2">
            <Badge status={queuedCount > 0 ? 'QUEUED' : 'WAIT'}>{queuedCount} queued</Badge>
            <Badge status={runningCount > 0 ? 'RUNNING' : 'WAIT'}>{runningCount} running</Badge>
              <Badge status={staleCount > 0 || failedCount > 0 ? 'WARN' : 'PASS'}>
                {staleCount} stale / {failedCount} failed
              </Badge>
              <Badge status={expiredLeaseCount > 0 ? 'WARN' : 'PASS'}>{expiredLeaseCount} 个过期租约</Badge>
              <span className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-500">{activeGroups} 个并发组</span>
            </div>
          <div className="flex flex-wrap items-center gap-2">
            <select
              data-testid="backend-analysis-job-queue-filter"
              value={statusFilter}
              onChange={(event) => onStatusFilterChange(event.target.value)}
              className="rounded-md border border-slate-200 bg-white px-2 py-2 text-sm text-slate-700"
            >
              {Object.entries(ANALYSIS_JOB_STATUS_FILTERS).map(([value, option]) => (
                <option key={value} value={value}>{option.label}</option>
              ))}
            </select>
            <span data-testid="backend-analysis-job-queue-page" className="rounded bg-slate-100 px-2 py-1 text-xs text-slate-500">
              {jobs.length ? `${offset + 1}-${offset + jobs.length}` : '0-0'} / {filteredTotal}
            </span>
            <span data-testid="backend-analysis-job-queue-total" className="rounded bg-slate-100 px-2 py-1 text-xs text-slate-500">
              total {summary?.total_count ?? jobs.length}
            </span>
            <button
              type="button"
              data-testid="backend-analysis-job-queue-prev"
              disabled={offset <= 0 || loading}
              onClick={onPreviousPage}
              className="rounded-md border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:opacity-50"
            >
              Newer
            </button>
            <button
              type="button"
              data-testid="backend-analysis-job-queue-next"
              disabled={!hasOlder || loading}
              onClick={onNextPage}
              className="rounded-md border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:opacity-50"
            >
              Older
            </button>
            <button
              type="button"
              data-testid="backend-analysis-job-queue-refresh"
              onClick={onRefresh}
              className="rounded-md border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
            >
              刷新
            </button>
          </div>
        </div>
        {loading ? <div className="text-xs text-slate-500">正在加载分析任务队列...</div> : null}
        {error ? <div className="rounded-md border border-rose-100 bg-rose-50 px-3 py-2 text-xs text-rose-700">{error}</div> : null}
        {externalQueueStatus ? (
          <div data-testid="backend-analysis-job-external-queue-status" className="flex flex-wrap items-center gap-2 rounded-md bg-slate-50 px-3 py-2 text-xs text-slate-600">
            <Badge status={externalQueueBadgeStatus(externalQueueStatus.status)}>
              外部队列：{externalQueueStatus.status || 'UNKNOWN'}
            </Badge>
            <span>提供方 {externalQueueStatus.provider || '未上报'}</span>
            <span>队列 {externalQueueStatus.queue_name || 'analysis'}</span>
            <span>工作器 {externalQueueStatus.active_workers ?? 0}</span>
            <span>待处理 {externalQueueStatus.pending_jobs ?? 0}</span>
            <span>运行中 {externalQueueStatus.running_jobs ?? 0}</span>
            <span>租约 {externalQueueStatus.lease_backend || '未上报'}</span>
            <span>本地模式 {externalQueueStatus.local_queue_mode || 'LOCAL_JSON_SQLITE_DIAGNOSTIC'}</span>
            {externalQueueStatus.message ? <span>{externalQueueStatus.message}</span> : null}
          </div>
        ) : null}
        {externalQueueStatus ? (
          <div data-testid="backend-analysis-job-external-queue-readiness" className="flex flex-wrap items-center gap-2 rounded-md bg-slate-50 px-3 py-2 text-xs text-slate-600">
            <span>认领 {externalQueueStatus.claim_status || '未上报'}</span>
            <span>后端 {externalQueueStatus.claim_backend || externalQueueStatus.lease_backend || '未上报'}</span>
            <span>幂等范围 {externalQueueStatus.idempotency_scope || '未上报'}</span>
            <span>审计流 {externalQueueStatus.audit_stream || '未上报'}</span>
            <span>死信队列 {externalQueueStatus.dead_letter_queue || '未上报'} / {externalQueueStatus.dead_letter_count ?? 0}</span>
            <span>可见性 {externalQueueStatus.visibility_timeout_seconds ?? '未上报'}s</span>
            <span>租约续期 {externalQueueStatus.lease_renewal_status || '未上报'}</span>
          </div>
        ) : null}
        {jobs.length > 0 ? (
          <TableShell className="!rounded-lg !shadow-none">
            <table className="institution-table min-w-[980px]">
              <thead>
                <tr>
                  <th>运行</th>
                  <th>状态</th>
                  <th>队列</th>
                  <th>工作器</th>
                  <th>租约</th>
                  <th>心跳</th>
                  <th>更新时间</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((job) => (
                  <tr key={`${job.run_id}-${job.job_id}`} data-testid={`backend-analysis-job-queue-row-${job.run_id}`}>
                    <td>
                      <div className="break-all font-mono font-medium text-slate-900">{job.run_id}</div>
                      <div className="mt-1 text-slate-400">attempt #{job.attempt}</div>
                    </td>
                    <td><Badge status={jobAttemptStatus(job.status)}>{job.status}</Badge></td>
                    <td>
                      <div>{job.queue_name || 'analysis'}</div>
                      <div className="text-slate-400">
                        group {job.concurrency_group || 'analysis'} / limit {job.concurrency_limit ?? 1}
                      </div>
                    </td>
                    <td className="break-all font-mono">{job.worker_id || 'unclaimed'}</td>
                    <td>
                      <Badge status={leaseBadgeStatus(job.lease_status)}>{job.lease_status || 'UNKNOWN'}</Badge>
                      <div data-testid={`backend-analysis-job-lease-${job.run_id}`} className="mt-1 text-slate-400">
                        expires {formatTimestamp(job.lease_expires_at)}
                      </div>
                    </td>
                    <td>{formatTimestamp(job.worker_heartbeat_at)}</td>
                    <td>{formatTimestamp(job.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableShell>
        ) : (
          <div className="rounded-md border border-dashed border-slate-200 p-4 text-sm text-slate-500">
            No analysis jobs are currently mirrored in the local queue.
          </div>
        )}
      </div>
    </Card>
  )
}

function AnalysisJobAttemptsPanel({
  attempts,
  offset,
  runFilter,
  appliedRunFilter,
  loading,
  error,
  currentRunId,
  onRunFilterChange,
  onApplyRunFilter,
  onClearRunFilter,
  onUseCurrentRun,
  onRefresh,
  onPreviousPage,
  onNextPage,
}: {
  attempts: AnalysisJobAttempt[]
  offset: number
  runFilter: string
  appliedRunFilter: string
  loading: boolean
  error: string | null
  currentRunId?: string
  onRunFilterChange: (value: string) => void
  onApplyRunFilter: () => void
  onClearRunFilter: () => void
  onUseCurrentRun: () => void
  onRefresh: () => void
  onPreviousPage: () => void
  onNextPage: () => void
}) {
  return (
    <Card title="分析任务尝试">
      <div data-testid="backend-analysis-job-attempts" className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="text-sm text-slate-600">
            {appliedRunFilter ? `Persisted execution attempts for ${appliedRunFilter}` : 'Recent persisted execution attempts'}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge status={attempts.length > 0 ? 'PASS' : 'WAIT'}>{attempts.length} attempts</Badge>
            <span data-testid="backend-analysis-job-attempt-page" className="rounded bg-slate-100 px-2 py-1 text-xs text-slate-500">
              {attempts.length ? `${offset + 1}-${offset + attempts.length}` : '0-0'}
            </span>
          </div>
        </div>
        <form
          className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto_auto_auto]"
          onSubmit={(event) => {
            event.preventDefault()
            onApplyRunFilter()
          }}
        >
          <label className="text-xs text-slate-500">
            <span className="mb-1 block font-medium">运行 ID 下钻</span>
            <input
              data-testid="backend-analysis-job-attempt-filter"
              value={runFilter}
              onChange={(event) => onRunFilterChange(event.target.value)}
              placeholder="RUN_..."
              className="h-9 w-full rounded-md border border-slate-200 px-3 font-mono text-sm text-slate-900 outline-none focus:border-cyan-400"
            />
          </label>
          <button
            type="submit"
            data-testid="backend-analysis-job-attempt-apply"
            className="self-end rounded-md border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
          >
            应用
          </button>
          <button
            type="button"
            data-testid="backend-analysis-job-attempt-clear"
            onClick={onClearRunFilter}
            className="self-end rounded-md border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
          >
            Clear
          </button>
          <button
            type="button"
            data-testid="backend-analysis-job-attempt-refresh"
            onClick={onRefresh}
            className="self-end rounded-md border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
          >
            刷新
          </button>
        </form>
        {currentRunId ? (
          <button
            type="button"
            onClick={onUseCurrentRun}
            className="rounded-md border border-cyan-100 bg-cyan-50 px-3 py-2 text-xs font-medium text-cyan-700 transition hover:bg-cyan-100"
          >
            Use current run: <span className="font-mono">{currentRunId}</span>
          </button>
        ) : null}
        {loading ? <div className="text-xs text-slate-500">正在加载尝试诊断...</div> : null}
        {error ? <div className="rounded-md border border-rose-100 bg-rose-50 px-3 py-2 text-xs text-rose-700">{error}</div> : null}
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            data-testid="backend-analysis-job-attempt-prev"
            disabled={offset <= 0 || loading}
            onClick={onPreviousPage}
            className="rounded-md border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:opacity-50"
          >
            Newer attempts
          </button>
          <button
            type="button"
            data-testid="backend-analysis-job-attempt-next"
            disabled={attempts.length < ANALYSIS_JOB_PAGE_SIZE || loading}
            onClick={onNextPage}
            className="rounded-md border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:opacity-50"
          >
            Older attempts
          </button>
        </div>
        {attempts.length > 0 ? (
          <div className="space-y-2">
            {attempts.map((attempt) => (
              <div
                key={`${attempt.run_id}-${attempt.attempt}-${attempt.job_id}`}
                className="rounded-md border border-slate-200 p-3 text-xs text-slate-600"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="min-w-0">
                    <div className="break-all font-mono font-medium text-slate-900">{attempt.run_id}</div>
                    <div className="mt-1 flex flex-wrap gap-2 text-slate-500">
                      <span>attempt #{attempt.attempt}</span>
                      <span>{attempt.queue_name || 'analysis'}</span>
                      {attempt.concurrency_group ? <span>group {attempt.concurrency_group}</span> : null}
                    </div>
                  </div>
                  <Badge status={jobAttemptStatus(attempt.status)}>{attempt.status}</Badge>
                </div>
                <div className="mt-2 grid gap-2 sm:grid-cols-3">
                  <div>
                    <div className="text-slate-400">工作器</div>
                    <div className="break-all font-mono text-slate-700">{attempt.worker_id || '未认领'}</div>
                  </div>
                  <div>
                    <div className="text-slate-400">更新时间</div>
                    <div>{formatTimestamp(attempt.updated_at)}</div>
                  </div>
                  <div>
                    <div className="text-slate-400">心跳</div>
                    <div>{formatTimestamp(attempt.worker_heartbeat_at)}</div>
                  </div>
                </div>
                {(attempt.failed_node_id || attempt.retry_from_node_id || attempt.last_error) ? (
                  <div className="mt-2 rounded bg-slate-50 p-2 text-slate-600">
                    {attempt.failed_node_id ? <div>失败节点：<span className="font-mono">{attempt.failed_node_id}</span></div> : null}
                    {attempt.retry_from_node_id ? <div>重试起点：<span className="font-mono">{attempt.retry_from_node_id}</span></div> : null}
                    {attempt.last_error ? <div className="break-words text-rose-700">Error: {attempt.last_error}</div> : null}
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        ) : (
          <div className="rounded-md border border-dashed border-slate-200 p-4 text-sm text-slate-500">
            No analysis job attempts have been mirrored yet.
          </div>
        )}
      </div>
    </Card>
  )
}

function OperatorContextPanel({ onTokenApplied }: { onTokenApplied?: () => void }) {
  const operator = useOperatorContext()
  const [tokenInput, setTokenInput] = useState('')
  return (
    <Card title="操作员上下文">
      <div className="grid gap-3 sm:grid-cols-[1fr_180px]">
        <label className="text-sm text-slate-600">
          <span className="mb-1 block text-xs font-medium text-slate-500">操作员 ID</span>
          <input
            value={operator.id}
            onChange={(event) => setOperatorContext({ id: event.target.value })}
            className="h-9 w-full rounded-md border border-slate-200 px-3 text-sm text-slate-900 outline-none focus:border-cyan-400"
          />
        </label>
        <label className="text-sm text-slate-600">
          <span className="mb-1 block text-xs font-medium text-slate-500">角色</span>
          <select
            value={operator.role}
            onChange={(event) => setOperatorContext({ role: event.target.value as typeof operator.role })}
            className="h-9 w-full rounded-md border border-slate-200 px-3 text-sm text-slate-900 outline-none focus:border-cyan-400"
          >
            {operatorRoles.map((role) => <option key={role} value={role}>{role}</option>)}
          </select>
        </label>
      </div>
      <div className="mt-4 grid gap-3 sm:grid-cols-[1fr_auto_auto]">
        <label className="text-sm text-slate-600">
          <span className="mb-1 block text-xs font-medium text-slate-500">API 令牌</span>
          <input
            type="password"
            value={tokenInput}
            onChange={(event) => setTokenInput(event.target.value)}
            className="h-9 w-full rounded-md border border-slate-200 px-3 text-sm text-slate-900 outline-none focus:border-cyan-400"
            autoComplete="off"
          />
        </label>
        <button
          type="button"
          data-testid="backend-operator-token-apply"
          onClick={() => {
            setOperatorApiToken(tokenInput)
            setTokenInput('')
            onTokenApplied?.()
          }}
          className="self-end rounded-md border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
        >
          应用
        </button>
        <button
          type="button"
          data-testid="backend-operator-token-clear"
          onClick={() => {
            clearOperatorApiToken()
            setTokenInput('')
          }}
          className="self-end rounded-md border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
        >
          Clear
        </button>
      </div>
      <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-500">
        <span>请求头：X-Operator-ID / X-Operator-Role{operator.apiTokenSet ? ' / Authorization' : ''}</span>
        <span>令牌：{operator.apiTokenSet ? '当前标签页已设置' : '未设置'}</span>
      </div>
    </Card>
  )
}

function DegradationChain({ source }: { source: DataSourceStatus }) {
  if (!source.fallbackChain || source.fallbackChain.length === 0) return null
  return (
    <div className="mt-2 rounded-md bg-slate-50 p-2 text-xs">
      <div className="mb-1 font-medium text-slate-500">容错链</div>
      <div className="flex flex-wrap items-center gap-1">
        {source.fallbackChain.map((step: FallbackStep, i: number) => (
          <span key={i} className="flex items-center gap-1">
            {i > 0 && <ArrowDown size={10} className="text-slate-300" />}
            <span className={`inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 ${step.success ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-700'}`}>
              {step.success ? <CheckCircle2 size={10} /> : <XCircle size={10} />}
              {step.provider || step.adapterId}
              <span className="text-slate-400">({step.latencyMs}ms)</span>
            </span>
          </span>
        ))}
      </div>
      {source.degradationReason && (
        <div className="mt-1 text-slate-400">原因: {source.degradationReason}</div>
      )}
    </div>
  )
}

export function BackendStatusPage() {
  const [health, setHealth] = useState<BackendHealth | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [adapters, setAdapters] = useState<DataSourceHealth[]>([])
  const [productionHealth, setProductionHealth] = useState<ProductionHealth | null>(null)
  const [productionAlertStatus, setProductionAlertStatus] = useState<ProductionAlertChannelStatus | null>(null)
  const [productionAlertLoading, setProductionAlertLoading] = useState(false)
  const [productionAlertError, setProductionAlertError] = useState<string | null>(null)
  const [productionAlertDispatching, setProductionAlertDispatching] = useState(false)
  const [productionAlertDispatchSummary, setProductionAlertDispatchSummary] = useState('')
  const [productionAlertExport, setProductionAlertExport] = useState<ProductionAlertExportBundle | null>(null)
  const [productionAlertExporting, setProductionAlertExporting] = useState(false)
  const [productionAlertExportSummary, setProductionAlertExportSummary] = useState('')
  const [productionAlertHandoff, setProductionAlertHandoff] = useState<ProductionAlertExportHandoff | null>(null)
  const [productionAlertHandoffing, setProductionAlertHandoffing] = useState(false)
  const [productionAlertHandoffSummary, setProductionAlertHandoffSummary] = useState('')
  const [opsLogStatus, setOpsLogStatus] = useState<OpsLogStatus | null>(null)
  const [opsLogLoading, setOpsLogLoading] = useState(false)
  const [opsLogError, setOpsLogError] = useState<string | null>(null)
  const [opsLogExport, setOpsLogExport] = useState<OpsLogExportBundle | null>(null)
  const [opsLogExporting, setOpsLogExporting] = useState(false)
  const [opsLogExportSummary, setOpsLogExportSummary] = useState('')
  const [opsLogHandoff, setOpsLogHandoff] = useState<OpsLogExportHandoff | null>(null)
  const [opsLogHandoffing, setOpsLogHandoffing] = useState(false)
  const [opsLogHandoffSummary, setOpsLogHandoffSummary] = useState('')
  const [opsLogQuery, setOpsLogQuery] = useState<OpsLogQueryResult | null>(null)
  const [opsLogQuerying, setOpsLogQuerying] = useState(false)
  const [opsLogQueryText, setOpsLogQueryText] = useState('http_request')
  const [startupStatus, setStartupStatus] = useState<StartupStatus | null>(null)
  const [analysisJobs, setAnalysisJobs] = useState<AnalysisJob[]>([])
  const [analysisJobSummary, setAnalysisJobSummary] = useState<AnalysisJobSummary | null>(null)
  const [analysisJobsOffset, setAnalysisJobsOffset] = useState(0)
  const [analysisJobStatusFilter, setAnalysisJobStatusFilter] = useState('all')
  const [analysisJobsLoading, setAnalysisJobsLoading] = useState(false)
  const [analysisJobsError, setAnalysisJobsError] = useState<string | null>(null)
  const analysisJobsRequestIdRef = useRef(0)
  const [jobAttempts, setJobAttempts] = useState<AnalysisJobAttempt[]>([])
  const [jobAttemptsOffset, setJobAttemptsOffset] = useState(0)
  const [jobAttemptsLoading, setJobAttemptsLoading] = useState(false)
  const [jobAttemptsError, setJobAttemptsError] = useState<string | null>(null)
  const [attemptRunFilter, setAttemptRunFilter] = useState('')
  const [appliedAttemptRunFilter, setAppliedAttemptRunFilter] = useState('')
  const { currentRun } = useAnalysisStore()
  const operator = useOperatorContext()
  const canDispatchProductionAlerts = roleAllows(operator.role, 'admin')
  const canHandoffProductionAlertExport = roleAllows(operator.role, 'admin')
  const canHandoffOpsLogExport = roleAllows(operator.role, 'admin')
  const productionAlertAdminDisabledReason = canDispatchProductionAlerts
    ? undefined
    : `当前角色 ${operator.role} 不能派发生产告警或交接告警导出。`
  const opsLogHandoffDisabledReason = canHandoffOpsLogExport
    ? undefined
    : `当前角色 ${operator.role} 不能交接运维日志导出。`

  const fetchHealth = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const response = await getBackendHealth()
      setHealth(response)
      getStartupStatus()
        .then(setStartupStatus)
        .catch(() => setStartupStatus(null))
    } catch {
      setError('无法获取后端健康状态，请检查后端服务是否启动。Failed to fetch backend health.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchHealth()
  }, [fetchHealth])

  const loadProductionHealth = useCallback(() => {
    getBackendMetrics()
      .then((metrics) => setProductionHealth(metrics.productionHealth ?? null))
      .catch(() => setProductionHealth(null))
  }, [])

  useEffect(() => {
    loadProductionHealth()
  }, [loadProductionHealth, operator.apiTokenRevision, operator.apiTokenSet, operator.id, operator.role])

  const loadProductionAlertStatus = useCallback(() => {
    setProductionAlertLoading(true)
    setProductionAlertError(null)
    return getProductionAlertStatus(10)
      .then(setProductionAlertStatus)
      .catch((err) => {
        setProductionAlertStatus(null)
        setProductionAlertError(err instanceof Error ? err.message : '无法加载生产告警通道')
      })
      .finally(() => setProductionAlertLoading(false))
  }, [])

  useEffect(() => {
    void loadProductionAlertStatus()
  }, [loadProductionAlertStatus, operator.apiTokenRevision, operator.apiTokenSet, operator.id, operator.role])

  const loadOpsLogStatus = useCallback(() => {
    setOpsLogLoading(true)
    setOpsLogError(null)
    return getOpsLogStatus(10)
      .then(setOpsLogStatus)
      .catch((err) => {
        setOpsLogStatus(null)
        setOpsLogError(err instanceof Error ? err.message : 'Unable to load ops event log')
      })
      .finally(() => setOpsLogLoading(false))
  }, [])

  useEffect(() => {
    void loadOpsLogStatus()
  }, [loadOpsLogStatus, operator.apiTokenRevision, operator.apiTokenSet, operator.id, operator.role])

  const handleProductionAlertDispatch = useCallback(() => {
    if (!canDispatchProductionAlerts) return
    setProductionAlertDispatching(true)
    setProductionAlertError(null)
    dispatchProductionAlerts()
      .then((result) => {
        setProductionAlertStatus(result.status)
        setProductionAlertDispatchSummary(`${result.dispatched} 条已记录 / ${result.deduplicated} 条已去重`)
        void loadOpsLogStatus()
      })
      .catch((err) => {
        setProductionAlertError(err instanceof Error ? err.message : '无法派发生产告警')
      })
      .finally(() => setProductionAlertDispatching(false))
  }, [canDispatchProductionAlerts, loadOpsLogStatus])

  const handleProductionAlertExport = useCallback(() => {
    setProductionAlertExporting(true)
    setProductionAlertError(null)
    getProductionAlertExport(50)
      .then((bundle) => {
        setProductionAlertExport(bundle)
        setProductionAlertExportSummary(`${bundle.schema} / 已导出 ${bundle.exported_count} 条 / ${bundle.checksum}`)
      })
      .catch((err) => {
        setProductionAlertExport(null)
        setProductionAlertExportSummary('')
        setProductionAlertError(err instanceof Error ? err.message : '无法导出生产告警包')
      })
      .finally(() => setProductionAlertExporting(false))
  }, [])

  const handleProductionAlertHandoff = useCallback(() => {
    if (!canHandoffProductionAlertExport) return
    setProductionAlertHandoffing(true)
    setProductionAlertError(null)
    handoffProductionAlertExport(50)
      .then((result) => {
        setProductionAlertHandoff(result)
        setProductionAlertHandoffSummary(`${result.schema} / ${result.status} / ${result.handoff_destination} / ${result.bundle_checksum}`)
        void loadProductionAlertStatus()
      })
      .catch((err) => {
        setProductionAlertHandoff(null)
        setProductionAlertHandoffSummary('')
        setProductionAlertError(err instanceof Error ? err.message : '无法交接生产告警导出')
      })
      .finally(() => setProductionAlertHandoffing(false))
  }, [canHandoffProductionAlertExport, loadProductionAlertStatus])

  const handleOpsLogExport = useCallback(() => {
    setOpsLogExporting(true)
    setOpsLogError(null)
    getOpsLogExport(50)
      .then((bundle) => {
        setOpsLogExport(bundle)
        setOpsLogExportSummary(`${bundle.schema} / 已导出 ${bundle.exported_count} 条 / ${bundle.checksum}`)
      })
      .catch((err) => {
        setOpsLogExport(null)
        setOpsLogExportSummary('')
        setOpsLogError(err instanceof Error ? err.message : '无法导出运维事件包')
      })
      .finally(() => setOpsLogExporting(false))
  }, [])

  const handleOpsLogHandoff = useCallback(() => {
    if (!canHandoffOpsLogExport) return
    setOpsLogHandoffing(true)
    setOpsLogError(null)
    handoffOpsLogExport(50)
      .then((result) => {
        setOpsLogHandoff(result)
        setOpsLogHandoffSummary(`${result.status} / ${result.handoff_destination} / ${result.bundle_checksum}`)
        void loadOpsLogStatus()
      })
      .catch((err) => {
        setOpsLogHandoff(null)
        setOpsLogHandoffSummary('')
        setOpsLogError(err instanceof Error ? err.message : '无法交接运维事件导出')
      })
      .finally(() => setOpsLogHandoffing(false))
  }, [canHandoffOpsLogExport, loadOpsLogStatus])

  const handleOpsLogQuery = useCallback(() => {
    setOpsLogQuerying(true)
    setOpsLogError(null)
    queryOpsLogs({ limit: 20, text: opsLogQueryText.trim() })
      .then(setOpsLogQuery)
      .catch((err) => {
        setOpsLogQuery(null)
        setOpsLogError(err instanceof Error ? err.message : 'Unable to query ops log')
      })
      .finally(() => setOpsLogQuerying(false))
  }, [opsLogQueryText])

  const analysisJobFilterStatuses = useMemo(
    () => ANALYSIS_JOB_STATUS_FILTERS[analysisJobStatusFilter]?.statuses ?? [],
    [analysisJobStatusFilter],
  )

  const loadAnalysisJobs = useCallback((offset = analysisJobsOffset) => {
    const requestId = analysisJobsRequestIdRef.current + 1
    analysisJobsRequestIdRef.current = requestId
    const isCurrentRequest = () => analysisJobsRequestIdRef.current === requestId
    setAnalysisJobsLoading(true)
    setAnalysisJobsError(null)
    const jobsRequest = getAnalysisJobs(ANALYSIS_JOB_PAGE_SIZE, offset, analysisJobFilterStatuses)
      .then((jobs) => {
        if (!isCurrentRequest()) return jobs
        setAnalysisJobs(jobs)
        return jobs
      })
    const summaryRequest = getAnalysisJobSummary(ANALYSIS_JOB_PAGE_SIZE, offset, analysisJobFilterStatuses)
      .then((summary) => {
        if (!isCurrentRequest()) return summary
        setAnalysisJobSummary(summary)
        return summary
      })
    return Promise.allSettled([jobsRequest, summaryRequest])
      .then(([jobsResult, summaryResult]) => {
        if (!isCurrentRequest()) return
        if (jobsResult.status === 'rejected') {
          setAnalysisJobs([])
          setAnalysisJobsError(jobsResult.reason instanceof Error ? jobsResult.reason.message : 'Unable to load analysis jobs')
        }
        if (summaryResult.status === 'rejected') {
          setAnalysisJobSummary(null)
        }
      })
      .finally(() => {
        if (isCurrentRequest()) {
          setAnalysisJobsLoading(false)
        }
      })
  }, [analysisJobFilterStatuses, analysisJobsOffset])

  const loadJobAttempts = useCallback((runId = appliedAttemptRunFilter, offset = jobAttemptsOffset) => {
    const normalizedRunId = runId.trim()
    setJobAttemptsLoading(true)
    setJobAttemptsError(null)
    return getAnalysisJobAttempts({ limit: ANALYSIS_JOB_PAGE_SIZE, offset, runId: normalizedRunId || undefined })
      .then(setJobAttempts)
      .catch((err) => {
        setJobAttempts([])
        setJobAttemptsError(err instanceof Error ? err.message : 'Unable to load analysis job attempts')
      })
      .finally(() => setJobAttemptsLoading(false))
  }, [appliedAttemptRunFilter, jobAttemptsOffset])

  useEffect(() => {
    void loadAnalysisJobs()
  }, [loadAnalysisJobs, operator.apiTokenRevision, operator.apiTokenSet, operator.id, operator.role])

  useEffect(() => {
    void loadJobAttempts()
  }, [loadJobAttempts, operator.apiTokenRevision, operator.apiTokenSet, operator.id, operator.role])

  useEffect(() => {
    getMarketDataAdapters()
      .then(setAdapters)
      .catch(() => setAdapters([]))
  }, [operator.apiTokenRevision, operator.apiTokenSet, operator.id, operator.role])

  const tokenUsage = currentRun?.tokenUsage
  const agentResults = currentRun?.agentResults

  const performanceStats = useMemo(() => {
    if (!agentResults || agentResults.length === 0) return null
    const totalMs = agentResults.reduce((sum, ar) => sum + (ar.elapsed_ms || 0), 0)
    const avgMs = totalMs / agentResults.length
    const maxAgent = agentResults.reduce((a, b) => ((a.elapsed_ms || 0) > (b.elapsed_ms || 0) ? a : b))
    const minAgent = agentResults.reduce((a, b) => ((a.elapsed_ms || 0) < (b.elapsed_ms || 0) ? a : b))
    return { totalMs, avgMs, maxAgent, minAgent, count: agentResults.length }
  }, [agentResults])

  const tokenStats = useMemo(() => {
    if (!tokenUsage) return null
    return {
      total: tokenUsage.totals.total_tokens,
      prompt: tokenUsage.totals.prompt_tokens,
      completion: tokenUsage.totals.completion_tokens,
      latency: tokenUsage.totals.latency_ms,
      topAgent: tokenUsage.top_agent,
    }
  }, [tokenUsage])

  if (loading && !health) {
    return <div>加载中...</div>
  }

  return (
    <div className="space-y-6">
      <SectionTitle title="后端状态" subtitle="后端健康、启动状态与运行环境。" />

      {error ? (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-rose-100 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          <span>{error}</span>
          <button type="button" onClick={fetchHealth} className="rounded-md border border-rose-200 bg-white px-3 py-1 text-xs font-medium text-rose-700">重试</button>
        </div>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[1fr_360px]">
        <ProductionHealthPanel health={productionHealth} onRefresh={loadProductionHealth} />
        <OperatorContextPanel
          onTokenApplied={() => {
            loadProductionHealth()
            void loadProductionAlertStatus()
            void loadOpsLogStatus()
          }}
        />
      </div>

      <ProductionAlertChannelPanel
        status={productionAlertStatus}
        role={operator.role}
        loading={productionAlertLoading}
        error={productionAlertError}
        canDispatch={canDispatchProductionAlerts}
        adminDisabledReason={productionAlertAdminDisabledReason}
        dispatching={productionAlertDispatching}
        dispatchSummary={productionAlertDispatchSummary}
        exportBundle={productionAlertExport}
        exporting={productionAlertExporting}
        exportSummary={productionAlertExportSummary}
        handoffResult={productionAlertHandoff}
        handoffBusy={productionAlertHandoffing}
        handoffSummary={productionAlertHandoffSummary}
        canHandoff={canHandoffProductionAlertExport}
        onDispatch={handleProductionAlertDispatch}
        onExport={handleProductionAlertExport}
        onHandoff={handleProductionAlertHandoff}
        onRefresh={() => { void loadProductionAlertStatus() }}
      />

      <OpsLogPanel
        status={opsLogStatus}
        role={operator.role}
        loading={opsLogLoading}
        error={opsLogError}
        exportBundle={opsLogExport}
        exporting={opsLogExporting}
        exportSummary={opsLogExportSummary}
        handoffResult={opsLogHandoff}
        handoffBusy={opsLogHandoffing}
        handoffSummary={opsLogHandoffSummary}
        queryResult={opsLogQuery}
        querying={opsLogQuerying}
        queryText={opsLogQueryText}
        canHandoff={canHandoffOpsLogExport}
        handoffDisabledReason={opsLogHandoffDisabledReason}
        onExport={handleOpsLogExport}
        onHandoff={handleOpsLogHandoff}
        onQuery={handleOpsLogQuery}
        onQueryTextChange={setOpsLogQueryText}
        onRefresh={() => { void loadOpsLogStatus() }}
      />

      <StartupStatusPanel status={startupStatus} />

      <AnalysisJobQueuePanel
        jobs={analysisJobs}
        summary={analysisJobSummary}
        offset={analysisJobsOffset}
        statusFilter={analysisJobStatusFilter}
        loading={analysisJobsLoading}
        error={analysisJobsError}
        onRefresh={() => { void loadAnalysisJobs() }}
        onPreviousPage={() => setAnalysisJobsOffset((value) => Math.max(0, value - ANALYSIS_JOB_PAGE_SIZE))}
        onNextPage={() => setAnalysisJobsOffset((value) => value + ANALYSIS_JOB_PAGE_SIZE)}
        onStatusFilterChange={(value) => {
          setAnalysisJobStatusFilter(value)
          setAnalysisJobsOffset(0)
        }}
      />

      <AnalysisJobAttemptsPanel
        attempts={jobAttempts}
        offset={jobAttemptsOffset}
        runFilter={attemptRunFilter}
        appliedRunFilter={appliedAttemptRunFilter}
        loading={jobAttemptsLoading}
        error={jobAttemptsError}
        currentRunId={currentRun?.runId}
        onRunFilterChange={setAttemptRunFilter}
        onApplyRunFilter={() => {
          setJobAttemptsOffset(0)
          setAppliedAttemptRunFilter(attemptRunFilter.trim())
        }}
        onClearRunFilter={() => {
          setAttemptRunFilter('')
          setJobAttemptsOffset(0)
          setAppliedAttemptRunFilter('')
        }}
        onUseCurrentRun={() => {
          const runId = currentRun?.runId ?? ''
          setAttemptRunFilter(runId)
          setJobAttemptsOffset(0)
          setAppliedAttemptRunFilter(runId)
        }}
        onRefresh={() => { void loadJobAttempts() }}
        onPreviousPage={() => setJobAttemptsOffset((value) => Math.max(0, value - ANALYSIS_JOB_PAGE_SIZE))}
        onNextPage={() => setJobAttemptsOffset((value) => value + ANALYSIS_JOB_PAGE_SIZE)}
      />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card>
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="text-xs font-medium text-slate-500">总体状态</div>
              <div className="mt-2 text-2xl font-semibold text-slate-950">{health?.status === 'ok' ? '正常' : health ? '异常' : '未知'}</div>
            </div>
            <div className={`grid h-10 w-10 place-items-center rounded-md ${health?.status === 'ok' ? 'bg-emerald-100 text-emerald-600' : 'bg-red-100 text-red-600'}`}>
              <Activity size={18} />
            </div>
          </div>
          <div className="mt-4">
            <Badge status={health?.status === 'ok' ? 'PASS' : 'FAIL'}>{health?.status ?? 'offline'}</Badge>
          </div>
        </Card>

        <Card>
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="text-xs font-medium text-slate-500">响应延迟</div>
              <div className="mt-2 text-2xl font-semibold text-slate-950">{health ? `${health.latency}ms` : 'n/a'}</div>
            </div>
            <div className="grid h-10 w-10 place-items-center rounded-md bg-cyan-100 text-cyan-600">
              <Clock size={18} />
            </div>
          </div>
          <div className="mt-4 text-xs text-slate-500">最后检查：{health?.lastCheck ?? '暂无数据'}</div>
        </Card>

        <Card>
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="text-xs font-medium text-slate-500">运行模式</div>
              <div className="mt-2 text-2xl font-semibold text-slate-950">{health?.mode?.toUpperCase() ?? 'N/A'}</div>
            </div>
            <div className="grid h-10 w-10 place-items-center rounded-md bg-purple-100 text-purple-600">
              <Cpu size={18} />
            </div>
          </div>
          <div className="mt-4 text-xs text-slate-500">版本：{health?.version ?? '未知'}</div>
        </Card>

        <Card>
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="text-xs font-medium text-slate-500">Agent 数量</div>
              <div className="mt-2 text-2xl font-semibold text-slate-950">{performanceStats?.count ?? 0}</div>
            </div>
            <div className="grid h-10 w-10 place-items-center rounded-md bg-amber-100 text-amber-600">
              <GitBranch size={18} />
            </div>
          </div>
          <div className="mt-4 text-xs text-slate-500">总耗时: {performanceStats ? formatDuration(performanceStats.totalMs) : 'N/A'}</div>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Agent 执行性能">
          {performanceStats ? (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div className="rounded-md bg-slate-50 p-3">
                  <div className="text-slate-500">平均耗时</div>
                  <div className="mt-1 text-lg font-semibold text-slate-950">{formatDuration(performanceStats.avgMs)}</div>
                </div>
                <div className="rounded-md bg-slate-50 p-3">
                  <div className="text-slate-500">总耗时</div>
                  <div className="mt-1 text-lg font-semibold text-slate-950">{formatDuration(performanceStats.totalMs)}</div>
                </div>
              </div>
              <div className="space-y-3">
                <div className="text-xs font-medium text-slate-500">各 Agent 耗时分布</div>
                {agentResults?.map((ar) => (
                  <PerformanceBar
                    key={ar.node}
                    label={ar.name}
                    value={ar.elapsed_ms || 0}
                    max={performanceStats.maxAgent.elapsed_ms || 1}
                    color={ar.elapsed_ms > performanceStats.avgMs * 1.5 ? 'bg-amber-500' : 'bg-cyan-500'}
                  />
                ))}
              </div>
              <div className="flex items-center gap-2 rounded-md bg-amber-50 p-3 text-xs text-amber-700">
                <AlertTriangle size={14} />
                最慢: {performanceStats.maxAgent.name} ({formatDuration(performanceStats.maxAgent.elapsed_ms || 0)})
                {' / '}最快: {performanceStats.minAgent.name} ({formatDuration(performanceStats.minAgent.elapsed_ms || 0)})
              </div>
            </div>
          ) : (
            <div className="text-sm text-slate-500">暂无 Agent 执行数据</div>
          )}
        </Card>

        <Card title="Token 用量统计">
          {tokenStats ? (
            <div className="space-y-4">
              <div className="grid grid-cols-3 gap-3 text-sm">
                <div className="rounded-md bg-slate-50 p-3">
                  <div className="text-slate-500">总 Token</div>
                  <div className="mt-1 text-lg font-semibold text-slate-950">{tokenStats.total.toLocaleString()}</div>
                </div>
                <div className="rounded-md bg-slate-50 p-3">
                  <div className="text-slate-500">提示词</div>
                  <div className="mt-1 text-lg font-semibold text-slate-950">{tokenStats.prompt.toLocaleString()}</div>
                </div>
                <div className="rounded-md bg-slate-50 p-3">
                  <div className="text-slate-500">补全</div>
                  <div className="mt-1 text-lg font-semibold text-slate-950">{tokenStats.completion.toLocaleString()}</div>
                </div>
              </div>

              <div className="space-y-3">
                <div className="text-xs font-medium text-slate-500">Token 分布</div>
                <PerformanceBar
                  label="提示词"
                  value={tokenStats.prompt}
                  max={tokenStats.total}
                  color="bg-blue-500"
                />
                <PerformanceBar
                  label="补全"
                  value={tokenStats.completion}
                  max={tokenStats.total}
                  color="bg-emerald-500"
                />
              </div>

              {tokenStats.topAgent && (
                <div className="flex items-center gap-2 rounded-md bg-cyan-50 p-3 text-xs text-cyan-700">
                  <Zap size={14} />
                  最高消耗: {tokenStats.topAgent.name} ({tokenStats.topAgent.total_tokens.toLocaleString()} tokens, {formatDuration(tokenStats.topAgent.latency_ms)})
                </div>
              )}

              <div className="text-xs text-slate-400">
                计量状态: {tokenUsage?.metering_status} — {tokenUsage?.note}
              </div>
            </div>
          ) : (
            <div className="text-sm text-slate-500">暂无 Token 用量数据</div>
          )}
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="数据源状态">
          <div className="space-y-3 text-sm text-slate-600">
            <div className="flex items-center gap-2">
              <Database size={14} className="text-slate-400" />
              数据模式: <DataModeBadge mode={currentRun?.dataMode || 'MOCK'} />
              {currentRun?.dataSources?.summary?.overallDataMode && (
                <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-500">{currentRun.dataSources.summary.overallDataMode}</span>
              )}
            </div>
            <div className="flex items-center gap-2">
              <Layers size={14} className="text-slate-400" />
              数据源就绪: <span className="font-medium text-slate-900">{currentRun?.dataSources?.summary?.availableRatio || 'N/A'}</span>
              <Badge status={currentRun?.dataSources?.summary?.overallStatus === 'READY' ? 'PASS' : 'WARN'}>
                {currentRun?.dataSources?.summary?.overallStatus === 'READY' ? 'READY' : currentRun?.dataSources?.summary?.overallStatus || 'N/A'}
              </Badge>
            </div>
            <div className="flex items-center gap-2">
              <TrendingUp size={14} className="text-slate-400" />
              行情状态: <span className="font-medium text-slate-900">{currentRun?.marketData?.status || 'N/A'}</span>
              {currentRun?.marketData?.freshness && <FreshnessBadge freshness={currentRun.marketData.freshness} />}
            </div>

            {currentRun?.dataSources?.sources && Object.entries(currentRun.dataSources.sources).length > 0 && (
              <div className="border-t border-slate-100 pt-3">
                <div className="mb-2 text-xs font-medium text-slate-500">数据源详情</div>
                <SourceFreshnessPanel
                  sources={Object.entries(currentRun.dataSources.sources).map(([key, s]) => ({
                    label: s.name || key,
                    freshness: s.freshness ? <FreshnessBadge freshness={s.freshness} /> : s.status,
                    value: typeof s.confidence === 'number' ? s.confidence * 100 : s.status === 'READY' ? 100 : s.status === 'FAILED' ? 20 : 45,
                    mode: (
                      <div className="space-y-2">
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge status={s.status === 'READY' ? 'PASS' : s.status === 'FAILED' ? 'FAIL' : 'WARN'}>
                            {s.status === 'READY' ? '就绪' : s.status === 'FAILED' ? '失败' : '未配置'}
                          </Badge>
                          <span className="break-words">{s.detail}</span>
                        </div>
                        {typeof s.confidence === 'number' ? <ConfidenceBar value={s.confidence} /> : null}
                        <DegradationChain source={s} />
                      </div>
                    ),
                  }))}
                />
              </div>
            )}

            {adapters.length > 0 && (
              <div className="border-t border-slate-100 pt-3">
                <div className="mb-2 text-xs font-medium text-slate-500">适配器健康</div>
                <div className="space-y-1.5">
                  {adapters.map((a) => (
                    <div key={a.adapterId} className="flex items-center gap-2 rounded bg-slate-50 px-2 py-1.5 text-xs">
                      <div className={`h-1.5 w-1.5 rounded-full ${a.healthy ? 'bg-emerald-500' : 'bg-red-500'}`} />
                      <span className="font-medium text-slate-700">{a.label || a.adapterId}</span>
                      {!a.installed && <span className="text-amber-600">(未安装)</span>}
                      <span className="ml-auto text-slate-400">{a.latencyAvgMs}ms</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </Card>

        <Card title="安全边界">
          <div className="space-y-2 text-sm text-slate-600">
            <div className="flex items-center gap-2">
              <div className={`h-2 w-2 rounded-full ${health?.tradingEnabled ? 'bg-red-500' : 'bg-emerald-500'}`} />
              真实交易: {health?.tradingEnabled ? '已启用 ⚠️' : '已禁用'}
            </div>
            <div className="flex items-center gap-2">
              <div className={`h-2 w-2 rounded-full ${health?.autoOrderEnabled ? 'bg-red-500' : 'bg-emerald-500'}`} />
              自动下单: {health?.autoOrderEnabled ? '已启用 ⚠️' : '已禁用'}
            </div>
            <div className="flex items-center gap-2">
              <div className="h-2 w-2 rounded-full bg-emerald-500" />
              熔断开关：{currentRun?.killSwitch?.active ? '已触发' : '未触发'}
            </div>
          </div>
        </Card>
      </div>
    </div>
  )
}
