import { useCallback, useEffect, useState } from 'react'
import { Database, Eye, FileJson, Layers, RefreshCw, Upload } from 'lucide-react'
import { getResearchTrace, getResearchTraces, importResearchTrace } from '../../api/researchClient'
import { ResearchTraceDetail, ResearchTraceSummary } from '../../types'
import { Badge } from '../common/Badge'
import { Card } from '../common/Card'
import { JsonViewer } from '../common/JsonViewer'
import { EvidenceLedger, SourceFreshnessPanel } from '../common/Material'
import { ResearchEmptyState, ResearchError, ResearchLoading, ResearchMetricCard, ResearchPageHeader } from './ResearchLabShared'
import { formatDateTime } from '../../utils/format'
import { roleAllows, useOperatorContext } from '../../store/operatorContext'

function traceStatus(status: string) {
  if (['IMPORTED', 'READY', 'COMPLETED'].includes(status)) return 'PASS'
  if (['FAILED', 'ERROR'].includes(status)) return 'FAIL'
  if (['PENDING', 'PROCESSING'].includes(status)) return 'WARN'
  return 'WAIT'
}

function parseTraceJsonObject(raw: string): Record<string, unknown> {
  const parsed = JSON.parse(raw) as unknown
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('Trace JSON 顶层必须是对象。')
  }
  return parsed as Record<string, unknown>
}

function buildTraceGovernance(trace: ResearchTraceDetail) {
  const status = trace.status.toUpperCase()
  const hasEvidence = trace.events.length > 0 || trace.artifacts.length > 0
  const hasLinkedContext = Boolean(trace.loop_id || trace.iteration_id || trace.run_id)
  const failed = status === 'FAILED' || status === 'ERROR'
  const blocker = failed
    ? `轨迹状态 ${trace.status}，需要复核导入错误`
    : !hasEvidence
      ? '缺少事件或产物，不能作为研究闭环证据'
      : !hasLinkedContext
        ? '缺少 loop / iteration / run 关联，只能暂存为外部观察'
        : '无阻塞；外部轨迹仍只能作为研究辅助证据'
  const nextAction = failed
    ? '修正源 trace 后重新导入'
    : !hasEvidence
      ? '补齐事件或产物后再关联研究循环'
      : !hasLinkedContext
        ? '关联到 Research Loop / iteration / run 后进入闭环复核'
        : '进入 Research Loop 复核，并在 Case / Knowledge 前保留 supporting-only 边界'

  return {
    contextId: trace.trace_id,
    evidenceStrength: 'LOW',
    blocker,
    nextAction,
    evidenceUsage: 'supporting_only',
    strongConclusionAllowed: false,
    simulationOnly: true,
    isRealTrade: false,
  }
}

export function ResearchTracesPage() {
  const operator = useOperatorContext()
  const canImportResearchTrace = roleAllows(operator.role, 'researcher')
  const traceImportDisabledReason = canImportResearchTrace
    ? ''
    : `研究轨迹导入需要 researcher 权限。当前角色：${operator.role}。`
  const [traces, setTraces] = useState<ResearchTraceSummary[]>([])
  const [selectedTrace, setSelectedTrace] = useState<ResearchTraceDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [importError, setImportError] = useState<string | null>(null)
  const [source, setSource] = useState('rd-agent')
  const [title, setTitle] = useState('')
  const [loopId, setLoopId] = useState('')
  const [iterationId, setIterationId] = useState('')
  const [runId, setRunId] = useState('')
  const [traceText, setTraceText] = useState('{\n  "events": [],\n  "artifacts": []\n}')

  const load = useCallback(async (preferredTraceId?: string) => {
    setLoading(true)
    setError(null)
    try {
      const nextTraces = await getResearchTraces()
      setTraces(nextTraces)
      const nextTraceId = preferredTraceId || selectedTrace?.trace_id || nextTraces[0]?.trace_id
      setSelectedTrace(nextTraceId ? await getResearchTrace(nextTraceId) : null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load research traces')
    } finally {
      setLoading(false)
    }
  }, [selectedTrace?.trace_id])

  useEffect(() => {
    load()
  }, [load])

  async function handleSelect(traceId: string) {
    setSaving(true)
    setError(null)
    try {
      setSelectedTrace(await getResearchTrace(traceId))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load trace detail')
    } finally {
      setSaving(false)
    }
  }

  async function handleImport() {
    if (!canImportResearchTrace) {
      setImportError(traceImportDisabledReason)
      return
    }
    setSaving(true)
    setImportError(null)
    try {
      const parsed = parseTraceJsonObject(traceText)
      const normalizedSource = source.trim() || 'rd-agent'
      const result = await importResearchTrace({
        source: normalizedSource,
        title: title.trim() || undefined,
        loop_id: loopId.trim() || undefined,
        iteration_id: iterationId.trim() || undefined,
        run_id: runId.trim() || undefined,
        trace: parsed,
      })
      setTitle('')
      setTraceText('{\n  "events": [],\n  "artifacts": []\n}')
      await load(result.trace.trace_id)
    } catch (err) {
      setImportError(err instanceof Error ? err.message : '轨迹导入失败')
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <ResearchLoading label="正在加载 RD-Agent 轨迹..." />

  return (
    <div className="space-y-6">
      <ResearchPageHeader
        eyebrow="RD-Agent 轨迹"
        title="轨迹导入"
        subtitle="导入 RD-Agent 执行轨迹，保留轻量索引，并在关联到研究循环前检查事件、产物和原始 JSON。"
        icon={Upload}
        tags={['导入', '轨迹视图', '产物复核']}
        actions={
          <button type="button" onClick={() => load()} disabled={saving} className="inline-flex items-center gap-2 rounded-md border border-slate-600 bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:opacity-60">
            <RefreshCw size={16} />
            刷新轨迹
          </button>
        }
      />

      {error ? <ResearchError message={error} /> : null}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <ResearchMetricCard label="轨迹总数" value={traces.length} helper="已导入索引" icon={Upload} tone="bg-cyan-50 text-cyan-700" />
        <ResearchMetricCard label="已选事件" value={selectedTrace?.events.length ?? 0} helper="当前轨迹事件" icon={Layers} tone="bg-emerald-50 text-emerald-700" />
        <ResearchMetricCard label="已选产物" value={selectedTrace?.artifacts.length ?? 0} helper="当前轨迹产物" icon={Database} tone="bg-amber-50 text-amber-700" />
        <ResearchMetricCard label="轨迹状态" value={selectedTrace?.status ?? '-'} helper="当前选择" icon={FileJson} tone="bg-slate-100 text-slate-700" />
      </div>

      <div className="grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
        <div className="space-y-6">
          <Card title="导入轨迹">
            <div className="space-y-3">
              <div className="flex flex-wrap gap-2 text-xs text-slate-500">
                <span data-testid="research-trace-import-role">角色：{operator.role}；导入：{canImportResearchTrace ? 'researcher+' : '已阻断'}</span>
                {!canImportResearchTrace ? (
                  <span data-testid="research-trace-import-disabled-reason" className="text-amber-700">{traceImportDisabledReason}</span>
                ) : null}
              </div>
              {importError ? <ResearchError message={importError} /> : null}
              <div className="grid gap-3 md:grid-cols-2">
                <input value={source} onChange={(event) => setSource(event.target.value)} placeholder="来源" className="rounded-md border border-slate-200 px-3 py-2 text-sm" />
                <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="标题" className="rounded-md border border-slate-200 px-3 py-2 text-sm" />
                <input value={loopId} onChange={(event) => setLoopId(event.target.value)} placeholder="循环 ID" className="rounded-md border border-slate-200 px-3 py-2 text-sm" />
                <input value={iterationId} onChange={(event) => setIterationId(event.target.value)} placeholder="轮次 ID" className="rounded-md border border-slate-200 px-3 py-2 text-sm" />
                <input value={runId} onChange={(event) => setRunId(event.target.value)} placeholder="运行 ID" className="rounded-md border border-slate-200 px-3 py-2 text-sm md:col-span-2" />
              </div>
              <textarea value={traceText} onChange={(event) => setTraceText(event.target.value)} rows={12} spellCheck={false} className="w-full rounded-md border border-slate-200 px-3 py-2 font-mono text-xs" />
              <button type="button" data-testid="research-trace-import-submit" onClick={handleImport} disabled={saving || !traceText.trim() || !canImportResearchTrace} title={traceImportDisabledReason || undefined} className="inline-flex items-center gap-2 rounded-md bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:opacity-60">
                <Upload size={16} />
                导入
              </button>
            </div>
          </Card>

          <Card title="轨迹列表">
            <div className="space-y-3">
              {traces.length === 0 ? (
                <ResearchEmptyState title="暂无轨迹" description="导入 RD-Agent trace JSON 后，会在这里形成可复核的轨迹索引。" icon={Upload} />
              ) : traces.map((trace) => (
                <button key={trace.trace_id} type="button" onClick={() => handleSelect(trace.trace_id)} className={`w-full rounded-md border p-4 text-left transition ${trace.trace_id === selectedTrace?.trace_id ? 'border-cyan-400 bg-cyan-50' : 'border-slate-200 hover:bg-slate-50'}`}>
                  <div className="flex items-center justify-between gap-3">
                    <div className="min-w-0 font-semibold text-slate-950">{trace.title || trace.trace_id}</div>
                    <Badge status={traceStatus(trace.status)}>{trace.status}</Badge>
                  </div>
                  <div className="mt-2 line-clamp-2 text-sm text-slate-500">{trace.summary || trace.source}</div>
                  <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-500">
                    <span>{trace.source}</span>
                    {trace.loop_id ? <span>Loop: {trace.loop_id}</span> : null}
                    {trace.iteration_id ? <span>Iteration: {trace.iteration_id}</span> : null}
                    <span>{formatDateTime(trace.updated_at || trace.imported_at)}</span>
                  </div>
                </button>
              ))}
            </div>
          </Card>
        </div>

        <Card title="轨迹详情" action={selectedTrace ? <Badge status={traceStatus(selectedTrace.status)}>{selectedTrace.status}</Badge> : null}>
          {selectedTrace ? (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                <span className="inline-flex items-center gap-1 rounded bg-slate-100 px-2 py-1"><Eye size={13} /> {selectedTrace.trace_id}</span>
                <span className="rounded bg-slate-100 px-2 py-1">{selectedTrace.source}</span>
                {selectedTrace.run_id ? <span className="rounded bg-slate-100 px-2 py-1">运行：{selectedTrace.run_id}</span> : null}
              </div>
              <div>
                <div className="text-base font-semibold text-slate-950">{selectedTrace.title}</div>
                {selectedTrace.summary ? <div className="mt-1 text-sm text-slate-600">{selectedTrace.summary}</div> : null}
              </div>
              <TraceGovernancePanel trace={selectedTrace} />
              <div className="grid gap-3 md:grid-cols-2">
                <TraceCount label="事件" value={selectedTrace.events.length} />
                <TraceCount label="产物" value={selectedTrace.artifacts.length} />
              </div>
              <SourceFreshnessPanel
                sources={[
                  {
                    label: 'Trace index',
                    freshness: `${traces.length} imported`,
                    value: Math.min(100, traces.length * 12),
                    mode: selectedTrace.source,
                  },
                  {
                    label: 'Selected trace',
                    freshness: formatDateTime(selectedTrace.updated_at || selectedTrace.imported_at),
                    value: selectedTrace.status === 'IMPORTED' || selectedTrace.status === 'READY' ? 100 : 58,
                    mode: selectedTrace.trace_id,
                  },
                ]}
              />
              {buildTraceLedgerRows(selectedTrace).length ? (
                <EvidenceLedger rows={buildTraceLedgerRows(selectedTrace)} />
              ) : null}
              <JsonViewer data={{
                events: selectedTrace.events,
                artifacts: selectedTrace.artifacts,
                metadata: selectedTrace.metadata,
                raw_trace: selectedTrace.raw_trace,
              }} />
            </div>
          ) : (
            <ResearchEmptyState title="尚未选择轨迹" description="从左侧选择一条轨迹，或先导入新的 RD-Agent trace JSON。" icon={Eye} />
          )}
        </Card>
      </div>
    </div>
  )
}

function TraceGovernancePanel({ trace }: { trace: ResearchTraceDetail }) {
  const governance = buildTraceGovernance(trace)
  return (
    <div data-testid="research-trace-governance" className="grid gap-2 rounded-md border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600 sm:grid-cols-2 xl:grid-cols-5">
      <span className="min-w-0 break-words">
        ID：
        <span data-testid="research-trace-governance-id" className="break-all font-mono text-slate-500">{governance.contextId}</span>
      </span>
      <span data-testid="research-trace-evidence-strength" className="min-w-0 break-words">
        证据强度：{governance.evidenceStrength}
      </span>
      <span data-testid="research-trace-blocker" className="min-w-0 break-words">
        阻塞：{governance.blocker}
      </span>
      <span data-testid="research-trace-next-action" className="min-w-0 break-words">
        下一步：{governance.nextAction}
      </span>
      <span data-testid="research-trace-simulation-boundary" className="min-w-0 break-words font-medium text-slate-900">
        simulation_only={String(governance.simulationOnly)} / is_real_trade={String(governance.isRealTrade)} / evidence_usage={governance.evidenceUsage} / strong_conclusion_allowed={String(governance.strongConclusionAllowed)} / SIM_*
      </span>
    </div>
  )
}

function buildTraceLedgerRows(trace: ResearchTraceDetail) {
  const eventRows = trace.events.slice(0, 3).map((event, index) => ({
    label: traceRecordLabel(event, `Event ${index + 1}`),
    source: 'event',
    status: <Badge status={traceStatus(traceRecordStatus(event, trace.status))}>{traceRecordStatus(event, trace.status)}</Badge>,
    detail: traceRecordDetail(event),
    strength: traceStrength(traceRecordStatus(event, trace.status)),
  }))
  const artifactRows = trace.artifacts.slice(0, 3).map((artifact, index) => ({
    label: traceRecordLabel(artifact, `Artifact ${index + 1}`),
    source: 'artifact',
    status: <Badge status={traceStatus(traceRecordStatus(artifact, trace.status))}>{traceRecordStatus(artifact, trace.status)}</Badge>,
    detail: traceRecordDetail(artifact),
    strength: traceStrength(traceRecordStatus(artifact, trace.status)),
  }))
  return [...eventRows, ...artifactRows]
}

function traceRecordLabel(record: Record<string, unknown>, fallback: string) {
  return stringRecordValue(record, 'title')
    || stringRecordValue(record, 'name')
    || stringRecordValue(record, 'type')
    || stringRecordValue(record, 'event')
    || fallback
}

function traceRecordStatus(record: Record<string, unknown>, fallback: string) {
  return stringRecordValue(record, 'status') || fallback
}

function traceRecordDetail(record: Record<string, unknown>) {
  const parts = ['id', 'event_id', 'artifact_id', 'path', 'created_at', 'timestamp']
    .map((key) => {
      const value = stringRecordValue(record, key)
      return value ? `${key}: ${value}` : ''
    })
    .filter(Boolean)
  return parts.join(' / ') || Object.entries(record)
    .slice(0, 3)
    .map(([key, value]) => `${key}: ${traceDetailValue(value)}`)
    .join(' / ')
}

function stringRecordValue(record: Record<string, unknown>, key: string) {
  const value = record[key]
  if (typeof value === 'string') return value.trim()
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return ''
}

function traceDetailValue(value: unknown) {
  if (value === null || value === undefined) return '-'
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value)
  return JSON.stringify(value)
}

function traceStrength(status: string) {
  const normalized = status.toUpperCase()
  if (['IMPORTED', 'READY', 'COMPLETED'].includes(normalized)) return 100
  if (['PENDING', 'PROCESSING'].includes(normalized)) return 62
  if (['FAILED', 'ERROR'].includes(normalized)) return 28
  return 45
}

function TraceCount({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md border border-slate-200 bg-slate-50 p-4">
      <div className="text-xs font-medium text-slate-500">{label}</div>
      <div className="mt-2 text-2xl font-semibold text-slate-950">{value}</div>
    </div>
  )
}
