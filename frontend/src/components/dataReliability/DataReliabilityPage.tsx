import { useEffect, useState } from 'react'
import { AlertTriangle, Clock, Database, RefreshCw, Search, ShieldCheck } from 'lucide-react'
import { Card } from '../common/Card'
import { SectionTitle } from '../common/SectionTitle'
import { Badge } from '../common/Badge'
import { DataModeBadge } from '../common/DataModeBadge'
import { MetricTile, SourceFreshnessPanel, TableShell } from '../common/Material'
import {
  checkDataReliabilityAdapters,
  checkSymbolHealth,
  DataReliabilityAdapter,
  DataReliabilityEventItem,
  DataReliabilityExternalMonitorStatus,
  DataReliabilityHistoryItem,
  DataReliabilityMatrix,
  DataReliabilitySnapshot,
  DataReliabilitySummary,
  getDataReliabilitySnapshot,
  SymbolHealthResult,
} from '../../api/dataReliabilityClient'
import { useAnalysisStore } from '../../store/useAnalysisStore'
import { roleAllows, useOperatorContext } from '../../store/operatorContext'
import { formatDateTime } from '../../utils/format'
import { buildDashboardProvenanceSummary } from '../../utils/dataProvenance'

export function DataReliabilityPage() {
  const operator = useOperatorContext()
  const [summary, setSummary] = useState<DataReliabilitySummary | null>(null)
  const [adapters, setAdapters] = useState<DataReliabilityAdapter[]>([])
  const [matrix, setMatrix] = useState<DataReliabilityMatrix | null>(null)
  const [snapshot, setSnapshot] = useState<DataReliabilitySnapshot | null>(null)
  const [history, setHistory] = useState<DataReliabilityHistoryItem[]>([])
  const [events, setEvents] = useState<DataReliabilityEventItem[]>([])
  const [symbol, setSymbol] = useState('002846')
  const [symbolResult, setSymbolResult] = useState<SymbolHealthResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const canRunDataReliabilityChecks = roleAllows(operator.role, 'operator')
  const dataReliabilityCheckDisabledReason = canRunDataReliabilityChecks
    ? undefined
    : `数据可靠性检查需要 operator 权限。当前角色：${operator.role}。`
  const diagnosticBoundaryText = 'diagnostic_only=true / simulation_only=true / is_real_trade=false / evidence_usage=monitoring_only / strong_conclusion_allowed=false / order_namespace=none'

  async function reload() {
    setLoading(true)
    setError('')
    try {
      const nextSnapshot = await getDataReliabilitySnapshot()
      setSnapshot(nextSnapshot)
      setSummary(nextSnapshot.summary)
      setAdapters(nextSnapshot.adapters)
      setMatrix(nextSnapshot.matrix)
      setHistory(nextSnapshot.history)
      setEvents(nextSnapshot.events ?? [])
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载健康状态失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    reload()
  }, [])

  async function runAdapterCheck() {
    if (!canRunDataReliabilityChecks) {
      setError(dataReliabilityCheckDisabledReason || '')
      return
    }
    setLoading(true)
    setError('')
    try {
      await checkDataReliabilityAdapters()
      await reload()
    } catch (err) {
      setError(err instanceof Error ? err.message : '适配器健康检查失败')
    } finally {
      setLoading(false)
    }
  }

  async function runSymbolCheck() {
    if (!canRunDataReliabilityChecks) {
      setError(dataReliabilityCheckDisabledReason || '')
      return
    }
    setLoading(true)
    setError('')
    try {
      setSymbolResult(await checkSymbolHealth(symbol))
      await reload()
    } catch (err) {
      setError(err instanceof Error ? err.message : '标的覆盖检查失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-5 text-slate-900" data-testid="data-reliability-page">
      <SectionTitle title="数据可靠性引擎" subtitle="统一呈现数据获取、数据源健康、适配器可用性、新鲜度、fallback 链路和运行证据。" />

      <div className="flex flex-wrap items-center gap-2 rounded-md border border-slate-200 bg-[#f8fafd] px-3 py-2 text-xs leading-5 text-slate-600" data-testid="data-reliability-diagnostic-boundary">
        <ShieldCheck size={14} className="text-[#0b57d0]" />
        <span>只读诊断，不生成交易结论；{diagnosticBoundaryText}</span>
      </div>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
        <Metric label="整体状态" value={summary?.overallStatus ?? 'UNKNOWN'} status={summary?.overallStatus ?? 'WARN'} />
        <Metric label="已检查源" value={`${summary?.checkedCount ?? 0}/${summary?.adapterCount ?? 0}`} status="WAIT" />
        <Metric label="可用源" value={`${summary?.healthyCount ?? 0}`} status="PASS" />
        <Metric label="部分返回" value={`${summary?.partialCount ?? 0}`} status={(summary?.partialCount ?? 0) > 0 ? 'WARN' : 'PASS'} />
        <Metric label="失败源" value={`${summary?.failedCount ?? 0}`} status={(summary?.failedCount ?? 0) > 0 ? 'WARN' : 'PASS'} />
      </div>

      {error && <div className="rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div>}

      <div className="flex flex-wrap gap-2 rounded-md border border-slate-200 bg-white px-3 py-2 text-xs text-slate-500">
        <span data-testid="data-reliability-check-role">角色：{operator.role}；执行检查：{canRunDataReliabilityChecks ? 'operator+' : '已阻断'}</span>
        {!canRunDataReliabilityChecks ? (
          <span data-testid="data-reliability-check-disabled-reason" className="text-amber-700">{dataReliabilityCheckDisabledReason}</span>
        ) : null}
      </div>

      <DataFreshnessSummary history={history} summary={summary} />

      <DataAdapterEvents events={events} />

      <DataExternalMonitorStatus status={snapshot?.externalMonitorStatus} />

      <RunReliabilityEvidence />

      <Card
        title="配置快照"
        action={
          <button type="button" onClick={reload} disabled={loading} className="inline-flex items-center gap-2 rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50 disabled:opacity-60">
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            只读刷新
          </button>
        }
      >
        <div className="grid gap-4 lg:grid-cols-[260px_1fr]">
          <div className="rounded-md border border-slate-200 bg-[#f8fafd] p-4">
            <div className="text-xs text-slate-500">Tushare Token</div>
            <div className="mt-2 flex items-center gap-2">
              <Badge status={snapshot?.config.dataSources.tushare_token_set ? 'PASS' : 'WARN'}>
                {snapshot?.config.dataSources.tushare_token_set ? '已配置' : '未配置'}
              </Badge>
              <span className="text-sm text-slate-600">{snapshot?.config.dataSources.tushare_token_mask || '-'}</span>
            </div>
          </div>
          <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
            {(snapshot?.config.dataSources.sources ?? []).map((source) => (
              <div key={source.key} className="rounded-md border border-slate-200 bg-white p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium text-slate-900">{source.name}</span>
                  <Badge status={source.enabled ? 'PASS' : 'SKIPPED'}>{source.enabled ? '启用' : '停用'}</Badge>
                </div>
                <div className="mt-1 text-xs text-slate-500">{source.tier_label || `${source.required_credits ?? 0} credits`}</div>
                <div className="mt-1 text-xs text-indigo-600">{sourceProviderSummary(source)}</div>
              </div>
            ))}
          </div>
        </div>
      </Card>

      <Card
        title="适配器状态"
        action={
          <button
            type="button"
            data-testid="data-reliability-adapter-check"
            onClick={runAdapterCheck}
            disabled={loading || !canRunDataReliabilityChecks}
            title={dataReliabilityCheckDisabledReason}
            className="inline-flex items-center gap-2 rounded-md bg-[#0b57d0] px-3 py-2 text-sm font-semibold text-white transition hover:bg-[#0842a0] disabled:opacity-60"
          >
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            执行检查
          </button>
        }
      >
        <TableShell>
          <table className="institution-table">
            <thead className="border-b border-slate-200 bg-[#f8fafd] text-[11px] uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-3 py-2">适配器</th>
                <th className="px-3 py-2">状态</th>
                <th className="px-3 py-2">新鲜度 / 延迟</th>
                <th className="px-3 py-2">能力</th>
                <th className="px-3 py-2">诊断</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {adapters.map((adapter) => {
                const capabilities = Array.isArray(adapter.capabilities) ? adapter.capabilities : []
                const status = adapter.status === 'NOT_CHECKED' ? 'WAIT' : adapter.healthy ? 'PASS' : 'FAIL'
                return (
                  <tr key={adapter.adapterId} className="align-top hover:bg-[#f8fafd]">
                    <td className="px-3 py-3">
                      <div className="font-semibold text-slate-950">{adapter.label || adapter.adapterId}</div>
                      <div className="mt-1 text-slate-500">{adapter.provider} · P{adapter.priority ?? '-'}</div>
                    </td>
                    <td className="px-3 py-3">
                      <Badge status={status}>{adapter.status || (adapter.healthy ? 'READY' : 'FAILED')}</Badge>
                      <div className="mt-2 text-slate-500">{adapter.enabled ? '启用' : '停用'} · {adapter.installed ? '依赖已安装' : '依赖缺失'}</div>
                    </td>
                    <td className="px-3 py-3">
                      <div className="font-semibold text-slate-950">{adapter.freshness || '未知'}</div>
                      <div className="mt-1 flex items-center gap-2 text-slate-500">
                        <span>{adapter.latencyAvgMs ?? 0}ms</span>
                        <span>超时 {adapter.timeoutSeconds ?? '-'}s</span>
                      </div>
                      <div className="mt-1 h-1.5 rounded-full bg-slate-100">
                        <div className="h-1.5 rounded-full bg-[#1a73e8]" style={{ width: `${latencyWidth(adapter.latencyAvgMs)}` }} />
                      </div>
                    </td>
                    <td className="px-3 py-3">
                      <div className="flex flex-wrap gap-1.5">
                        {(capabilities.length ? capabilities : ['未声明能力']).slice(0, 4).map((capability) => (
                          <span key={capability} className="rounded-md border border-slate-200 bg-white px-2 py-0.5 text-[11px] text-slate-600">
                            {capability}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="px-3 py-3 leading-5 text-slate-600">
                      <div>{adapter.message || (adapter.enabled ? '等待检查' : '已禁用')}</div>
                      {adapter.diagnosis ? <div className="mt-1 text-slate-500">诊断：{diagnosisLabel(adapter.diagnosis)}</div> : null}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </TableShell>
      </Card>

      <Card title="能力矩阵">
        <div className="grid gap-3 lg:grid-cols-2">
          {Object.entries(matrix?.categories ?? {}).map(([category, entries]) => (
            <div key={category} className="rounded-md border border-slate-200 bg-[#f8fafd] p-3">
              <div className="mb-2 text-sm font-semibold text-slate-950">{categoryLabel(category)}</div>
              <div className="flex flex-wrap gap-2">
                {Object.values(entries).length ? (
                  Object.values(entries).map((adapter) => (
                    <Badge key={`${category}-${adapter.adapterId}`} status={adapter.enabled ? 'PASS' : 'SKIPPED'}>
                      {adapter.label || adapter.adapterId} · P{adapter.priority ?? '-'}
                    </Badge>
                  ))
                ) : (
                  <Badge status="FAIL">无可用适配器</Badge>
                )}
              </div>
            </div>
          ))}
        </div>
      </Card>

      <Card title="标的覆盖检查">
        <div className="flex flex-wrap gap-3">
          <input
            value={symbol}
            onChange={(event) => setSymbol(event.target.value)}
            className="min-w-[220px] rounded-md border border-slate-200 bg-white px-3 py-2 text-sm outline-none transition focus:border-[#1a73e8] focus:ring-2 focus:ring-[#1a73e8]/15"
            placeholder="输入股票代码，如 002846"
          />
          <button
            type="button"
            data-testid="data-reliability-symbol-check"
            onClick={runSymbolCheck}
            disabled={loading || !canRunDataReliabilityChecks}
            title={dataReliabilityCheckDisabledReason}
            className="inline-flex items-center gap-2 rounded-md bg-[#0b57d0] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#0842a0] disabled:opacity-60"
          >
            <Search size={15} />
            检查
          </button>
        </div>
        {symbolResult && (
          <div className="mt-4 space-y-3">
            <div className="flex items-center gap-2 text-sm">
              <span className="font-medium text-slate-700">{symbolResult.symbol}</span>
              <Badge status={symbolResult.overallStatus === 'READY' ? 'PASS' : symbolResult.overallStatus === 'FAILED' ? 'FAIL' : 'WARN'}>{symbolResult.overallStatus}</Badge>
            </div>
            <TableShell>
              <table className="institution-table">
                <thead className="border-b border-slate-200 bg-[#f8fafd] text-[11px] uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className="px-3 py-2">类别</th>
                    <th className="px-3 py-2">状态</th>
                    <th className="px-3 py-2">来源</th>
                    <th className="px-3 py-2">诊断</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {symbolResult.results.map((item) => (
                    <tr key={item.category} className="align-top">
                      <td className="px-3 py-2.5 font-semibold text-slate-950">{categoryLabel(item.category)}</td>
                      <td className="px-3 py-2.5">
                        <Badge status={item.status === 'SKIPPED' ? 'SKIPPED' : item.healthy ? 'PASS' : 'FAIL'}>{item.status}</Badge>
                      </td>
                      <td className="px-3 py-2.5 text-slate-600">{item.provider} / {item.adapterId} · {item.recordCount} 条 · {item.latencyMs}ms</td>
                      <td data-testid={`data-reliability-symbol-diagnosis-${item.category}`} className="px-3 py-2.5 text-slate-600">
                        {diagnosisLabel(item.diagnosis) || item.diagnosis}{item.message ? ` · ${item.message}` : ''}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableShell>
          </div>
        )}
      </Card>

      <Card title="最近检查">
        {history.length ? (
          <TableShell>
            <table className="institution-table">
              <thead className="border-b border-slate-200 bg-[#f8fafd] text-[11px] uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-3 py-2">来源</th>
                  <th className="px-3 py-2">状态</th>
                  <th className="px-3 py-2">诊断</th>
                  <th className="px-3 py-2">时间</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {history.slice(0, 12).map((item) => (
                  <tr key={item.id} className="align-top hover:bg-[#f8fafd]">
                    <td className="px-3 py-2.5 font-semibold text-slate-950">{item.symbol || item.adapterId || item.provider}</td>
                    <td className="px-3 py-2.5"><Badge status={item.healthy ? 'PASS' : 'FAIL'}>{item.status}</Badge></td>
                    <td className="px-3 py-2.5 text-slate-600">{categoryLabel(item.category || item.checkType)} · {item.message || item.error}</td>
                    <td className="px-3 py-2.5 text-slate-500">{formatDateTime(item.createdAt)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableShell>
        ) : <div className="text-slate-500">暂无检查记录。</div>}
      </Card>
    </div>
  )
}

function RunReliabilityEvidence() {
  const { currentRun } = useAnalysisStore()

  if (!currentRun) {
    return (
      <Card title="当前运行证据" action={<Badge status="WAIT">NO RUN</Badge>}>
        <div data-testid="data-reliability-run-evidence-empty" className="rounded-md border border-dashed border-slate-200 bg-[#f8fafd] p-4 text-sm text-slate-500">
          暂无当前运行；数据源健康快照仍可独立查看。
        </div>
      </Card>
    )
  }

  const marketData = currentRun.marketData ?? {}
  const chipKb = currentRun.chipKb
  const dataSources = currentRun.dataSources
  const sources = dataSources?.sources ?? {}
  const provenanceSummary = buildDashboardProvenanceSummary(currentRun)
  const freshnessRows = provenanceSummary.freshnessItems.length ? provenanceSummary.freshnessItems : [{
    key: 'freshness:none',
    label: 'No source freshness recorded',
    status: 'WAIT' as const,
    freshness: 'unknown',
    detail: 'No source freshness recorded',
  }]

  return (
    <Card
      title="当前运行证据"
      action={<span data-testid="data-reliability-current-run-id" className="max-w-[260px] truncate font-mono text-xs text-slate-500">{currentRun.runId}</span>}
    >
      <div data-testid="data-reliability-data-provenance" className="grid gap-4 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <div className="rounded-md border border-[#d2e3fc] bg-[#e8f0fe] p-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="text-xs font-semibold uppercase tracking-wide text-[#1967d2]">Dashboard / Final Writer 同步口径</div>
              <div className="mt-2 text-lg font-semibold text-slate-950">{provenanceSummary.label}</div>
            </div>
            <Badge status={provenanceSummary.status} className="!rounded-md px-2 py-0.5">{provenanceSummary.level}</Badge>
          </div>
          <div className="mt-2 text-xs leading-5 text-slate-600">{provenanceSummary.headline}</div>
        </div>

        <TableShell>
          <table className="institution-table">
            <thead className="border-b border-slate-200 bg-[#f8fafd] text-[11px] uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-3 py-2">类别</th>
                <th className="px-3 py-2">状态</th>
                <th className="px-3 py-2">细节</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              <tr data-testid="data-reliability-source-freshness">
                <td className="px-3 py-2 font-medium text-slate-900">数据源新鲜度</td>
                <td className="px-3 py-2 text-slate-600">
                  {freshnessRows.slice(0, 3).map((item) => (
                    <div key={item.key}>
                      <span className="font-semibold text-slate-700">{item.label}</span>: {item.freshness}
                      {item.provider ? <span className="text-slate-400"> / {item.provider}</span> : null}
                    </div>
                  ))}
                </td>
                <td className="px-3 py-2 text-slate-500">source freshness</td>
              </tr>
              <tr data-testid="data-reliability-fallback-chain">
                <td className="px-3 py-2 font-medium text-slate-900">降级</td>
                <td className="px-3 py-2 text-slate-600">{provenanceSummary.fallbackChain[0] ?? '无 fallback / 降级链'}</td>
                <td className="px-3 py-2 text-slate-500">fallback chain</td>
              </tr>
              <tr>
                <td className="px-3 py-2 font-medium text-slate-900">缺失与复核</td>
                <td className="px-3 py-2 text-slate-600">{provenanceSummary.missingFields[0] ?? provenanceSummary.reviewPoints[0] ?? '无核心缺失字段'}</td>
                <td className="px-3 py-2 text-slate-500">review point</td>
              </tr>
            </tbody>
          </table>
        </TableShell>
      </div>

      <SourceFreshnessPanel
        className="mt-3"
        sources={freshnessRows.slice(0, 4).map((item) => ({
          label: item.label,
          freshness: item.freshness,
          mode: item.provider || item.status,
        }))}
      />

      <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <MetricTile
          label="行情来源"
          value={String(marketData.provider ?? 'MOCK')}
          helper={String(marketData.status ?? 'UNKNOWN')}
          tone={marketData.status === 'READY' ? 'success' : 'warning'}
        />
        <MetricTile
          label="数据模式"
          value={<DataModeBadge mode={currentRun.dataMode || 'MOCK'} />}
          helper="run data mode"
          tone="info"
        />
        <MetricTile
          label="数据覆盖"
          value={dataSources?.summary?.availableRatio ?? 'N/A'}
          helper={dataSources?.summary?.overallStatus ?? 'UNKNOWN'}
          tone={dataSources?.summary?.overallStatus === 'READY' ? 'success' : 'warning'}
        />
        <MetricTile
          label="筹码置信"
          value={chipKb ? `${(chipKb.dataConfidenceLevel * 100).toFixed(0)}%` : 'N/A'}
          helper={chipKb?.currentPool ?? `${Object.keys(sources).length} sources`}
          tone={(chipKb?.dataConfidenceLevel ?? 0) > 0.85 ? 'success' : 'warning'}
        />
      </div>
    </Card>
  )
}

function DataFreshnessSummary({
  history,
  summary,
}: {
  history: DataReliabilityHistoryItem[]
  summary: DataReliabilitySummary | null
}) {
  const recent = history.slice(0, 12)
  const latest = recent[0]
  const latestIssue = recent.find((item) => !item.healthy || isPartialOrFallback(item))
  const slowest = recent.reduce<DataReliabilityHistoryItem | undefined>((current, item) => {
    if (!current) return item
    return item.latencyMs > current.latencyMs ? item : current
  }, undefined)
  const fallbackCount = recent.filter(isPartialOrFallback).length
  const status = summary?.overallStatus === 'FAILED'
    ? 'FAIL'
    : fallbackCount > 0 || latestIssue
      ? 'WARN'
      : latest
        ? 'PASS'
        : 'WAIT'

  return (
    <Card title="数据新鲜度与降级链" action={<Badge status={status}>{summary?.overallStatus ?? 'UNKNOWN'}</Badge>}>
      <div data-testid="data-reliability-freshness-summary" className="grid gap-3 lg:grid-cols-4">
        <FreshnessTile
          testId="data-reliability-latest-check"
          label="最近检查"
          value={latest ? sourceCheckLabel(latest) : '暂无检查'}
          helper={latest ? formatDateTime(latest.createdAt) : 'Run adapter or symbol checks to record freshness.'}
        />
        <FreshnessTile
          testId="data-reliability-latest-failure"
          label="最近问题"
          value={latestIssue ? sourceCheckLabel(latestIssue) : '近期无问题'}
          helper={latestIssue ? issueDetail(latestIssue) : 'Recent checks have no failed or fallback rows.'}
        />
        <FreshnessTile
          testId="data-reliability-fallback-count"
          label="降级/部分返回行"
          value={String(fallbackCount)}
          helper="Rows with fallbackUsed=true, PARTIAL status, or upstream data that is not live-usable."
        />
        <FreshnessTile
          testId="data-reliability-slowest-check"
          label="近期最慢"
          value={slowest ? `${slowest.latencyMs}ms` : '-'}
          helper={slowest ? sourceCheckLabel(slowest) : 'No latency samples yet.'}
        />
      </div>
    </Card>
  )
}

function DataAdapterEvents({ events }: { events: DataReliabilityEventItem[] }) {
  const recent = events.slice(0, 8)
  const fallbackOrFailureCount = recent.filter((event) => (
    event.fallbackUsed || String(event.eventType || '').includes('FAILED') || String(event.eventType || '').includes('FALLBACK') || String(event.eventType || '').includes('PARTIAL')
  )).length
  const status = fallbackOrFailureCount > 0 ? 'WARN' : recent.length ? 'PASS' : 'WAIT'

  return (
    <Card title="适配器事件轨迹" action={<Badge status={status}>{recent.length ? `${recent.length} 个事件` : '暂无事件'}</Badge>}>
      <div data-testid="data-reliability-adapter-events" className="text-sm">
        {recent.length ? (
          <TableShell>
            <table className="institution-table">
              <thead className="border-b border-slate-200 bg-[#f8fafd] text-[11px] uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-3 py-2">事件</th>
                  <th className="px-3 py-2">来源</th>
                  <th className="px-3 py-2">详情</th>
                  <th className="px-3 py-2">时间</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {recent.map((event) => (
                  <tr key={event.id} className="align-top hover:bg-[#f8fafd]">
                    <td className="px-3 py-2.5">
                      <div className="font-semibold text-slate-950">{eventTypeLabel(event.eventType)}</div>
                      <div className="mt-1 text-slate-500">{event.status || '-'}</div>
                    </td>
                    <td className="px-3 py-2.5 text-slate-700">{sourceEventLabel(event)}</td>
                    <td className="px-3 py-2.5 leading-5 text-slate-600">{event.message || event.error || diagnosisLabel(event.diagnosis || '') || 'No detail'}</td>
                    <td className="px-3 py-2.5 text-slate-500">{formatDateTime(event.createdAt)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableShell>
        ) : <div className="text-slate-500">暂无适配器事件记录。</div>}
      </div>
    </Card>
  )
}

function DataExternalMonitorStatus({ status }: { status?: DataReliabilityExternalMonitorStatus | null }) {
  const current = status ?? null
  const statusText = current?.status || 'NOT_CONFIGURED'
  const provider = [safeDisplayText(current?.provider), safeDisplayText(current?.monitorBackend)].filter(Boolean).join(' / ') || 'No external monitor'
  const retention = [
    safeDisplayText(current?.retentionStatus),
    safeDisplayText(current?.retentionPolicyId),
    typeof current?.retentionDays === 'number' ? `${current.retentionDays}d` : '',
  ].filter(Boolean).join(' / ') || 'No retention report'
  const incidents = `${current?.outageCount ?? 0} outages / ${current?.degradedSourceCount ?? 0} degraded / ${current?.staleSourceCount ?? 0} stale`
  const searchIndex = safeDisplayText(current?.searchIndex)
  const search = current?.searchIndexReady ? 'Search ready' : searchIndex ? 'Search pending' : 'No search index'

  return (
    <Card title="外部监控与保留策略" action={<Badge status={externalMonitorBadgeStatus(statusText)}>{statusText}</Badge>}>
      <div data-testid="data-reliability-external-monitor-status" className="grid gap-3 lg:grid-cols-4">
        <FreshnessTile
          testId="data-reliability-external-monitor-provider"
          label="提供方"
          value={provider}
          helper={current?.reportedAt ? `Reported ${formatDateTime(current.reportedAt)}` : safeDisplayText(current?.message, 'Deployment sidecar not configured.')}
        />
        <FreshnessTile
          testId="data-reliability-external-monitor-retention"
          label="保留策略"
          value={retention}
          helper={current?.retentionExpiresAt ? `Expires ${formatDateTime(current.retentionExpiresAt)}` : 'External retention remains deployment-owned.'}
        />
        <FreshnessTile
          testId="data-reliability-external-monitor-incidents"
          label="事件"
          value={incidents}
          helper={current?.latestIncidentAt ? `Latest ${formatDateTime(current.latestIncidentAt)}` : safeDisplayText(current?.freshnessStatus, 'No incident timestamp reported.')}
        />
        <FreshnessTile
          testId="data-reliability-external-monitor-search"
          label="搜索索引"
          value={search}
          helper={searchIndex || safeDisplayText(current?.localEventTrail, 'Local event trail only.')}
        />
      </div>
    </Card>
  )
}

function FreshnessTile({
  testId,
  label,
  value,
  helper,
}: {
  testId: string
  label: string
  value: string
  helper: string
}) {
  return (
    <div data-testid={testId} className="rounded-md border border-slate-200 bg-[#f8fafd] p-3">
      <div className="flex items-center justify-between gap-3">
        <div className="text-xs font-medium text-slate-500">{label}</div>
        <span className="h-1.5 w-1.5 rounded-full bg-[#1a73e8]" />
      </div>
      <div className="mt-1 break-words text-sm font-semibold text-slate-950">{value}</div>
      <div className="mt-1 text-xs leading-5 text-slate-500">{helper}</div>
    </div>
  )
}

function isPartialOrFallback(item: DataReliabilityHistoryItem) {
  return Boolean(item.fallbackUsed) || item.status === 'PARTIAL' || (item.upstreamHealthy === true && item.liveDataUsable === false)
}

function sourceCheckLabel(item: DataReliabilityHistoryItem) {
  const sourceParts = [item.symbol, item.adapterId, item.provider].filter((value): value is string => Boolean(value))
  const source = Array.from(new Set(sourceParts)).join(' / ') || '-'
  return [
    source,
    categoryLabel(item.category || item.checkType),
    item.status || (item.healthy ? 'READY' : 'FAILED'),
  ].filter(Boolean).join(' / ')
}

function issueDetail(item: DataReliabilityHistoryItem) {
  return item.message || item.error || diagnosisLabel(item.diagnosis || '') || 'No detail'
}

function eventTypeLabel(value: string) {
  const map: Record<string, string> = {
    ADAPTER_READY: 'Adapter ready',
    ADAPTER_PARTIAL: 'Adapter partial',
    ADAPTER_FAILED: 'Adapter failed',
    SOURCE_READY: 'Source ready',
    SOURCE_FALLBACK: 'Source fallback',
    SOURCE_FAILED: 'Source failed',
    SOURCE_SKIPPED: 'Source skipped',
  }
  return map[value] ?? value
}

function sourceEventLabel(event: DataReliabilityEventItem) {
  const sourceParts = [event.symbol, event.adapterId, event.provider].filter((value): value is string => Boolean(value))
  const source = Array.from(new Set(sourceParts)).join(' / ') || '-'
  const category = categoryLabel(event.category)
  const latency = typeof event.latencyMs === 'number' ? ` / ${event.latencyMs}ms` : ''
  return `${source} / ${category}${latency}`
}

function externalMonitorBadgeStatus(value: string) {
  const status = value.toUpperCase()
  if (status === 'READY') return 'PASS'
  if (status === 'FAILED' || status === 'INVALID') return 'FAIL'
  if (status === 'NOT_CONFIGURED' || status === 'NOT_REPORTED') return 'WAIT'
  return 'WARN'
}

function safeDisplayText(value: string | null | undefined, fallback = '') {
  const text = String(value ?? '').trim()
  if (!text) return fallback
  return /(authorization|bearer|token|api[_-]?key|secret|password|credential)/i.test(text) ? '[redacted]' : text
}

function sourceProviderSummary(source: { providers?: string[]; provider_apis?: Record<string, string> }) {
  const providers = source.providers?.length ? source.providers : Object.keys(source.provider_apis || {})
  return providers.length ? providers.join(' / ') : 'tushare'
}

function diagnosisLabel(value: string) {
  const map: Record<string, string> = {
    OK: '可用',
    SOURCE_DISABLED: '数据源未启用',
    TOKEN_OR_PERMISSION: 'Token 缺失、失效或权限不足',
    NETWORK_TIMEOUT: '网络或接口超时',
    ADAPTER_DISABLED_OR_MISSING: '适配器未启用或不可用',
    SYMBOL_NO_DATA: '该标的当前接口无返回',
    ADAPTER_ERROR: '适配器执行失败',
    UNKNOWN: '原因未知',
  }
  return map[value] ?? value
}

function categoryLabel(value: string) {
  const map: Record<string, string> = {
    realtime_quote: '实时行情',
    historical_quote: '历史行情',
    index_sector: '指数板块',
    kline_quote: 'K线行情',
    kline_daily: 'K线日线',
    kline_weekly: 'K线周线',
    kline_monthly: 'K线月线',
    fundamentals: '财务数据',
    announcements: '公告数据',
    moneyflow: '资金流向',
    chip: '筹码数据',
    macro: '宏观指标',
    symbol_coverage_check: '标的覆盖检查',
    adapter_check: '适配器检查',
  }
  return map[value] ?? value
}

function Metric({ label, value, status }: { label: string; value: string; status: string }) {
  return (
    <MetricTile
      label={label}
      value={value}
      helper={<Badge status={status}>{status}</Badge>}
      icon={metricIcon(status)}
      tone={metricTone(status)}
    />
  )
}

function metricTone(status: string) {
  const normalized = String(status || '').toUpperCase()
  if (['PASS', 'READY', 'HEALTHY'].includes(normalized)) return 'success' as const
  if (['FAIL', 'FAILED', 'ERROR'].includes(normalized)) return 'danger' as const
  if (['WARN', 'WARNING', 'PARTIAL'].includes(normalized)) return 'warning' as const
  return 'info' as const
}

function metricIcon(status: string) {
  const normalized = String(status || '').toUpperCase()
  if (['PASS', 'READY', 'HEALTHY'].includes(normalized)) return ShieldCheck
  if (['FAIL', 'FAILED', 'ERROR', 'WARN', 'WARNING', 'PARTIAL'].includes(normalized)) return AlertTriangle
  if (normalized === 'WAIT') return Clock
  return Database
}

function latencyWidth(value?: number | null) {
  const latency = typeof value === 'number' && Number.isFinite(value) ? value : 0
  return `${Math.min(100, Math.max(4, latency / 25))}%`
}
