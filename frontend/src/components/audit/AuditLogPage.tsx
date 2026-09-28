import { useEffect, useMemo, useState } from 'react'
import { ArrowRight, Clock, Download, Filter, Hash, Search } from 'lucide-react'
import { getAuditLog } from '../../api/auditClient'
import { useAnalysisStore } from '../../store/useAnalysisStore'
import { useCachedResource } from '../../hooks/useCachedResource'
import { AuditLogEvent } from '../../types'
import { formatDateTime } from '../../utils/format'
import { Badge } from '../common/Badge'
import { Card } from '../common/Card'
import { SectionTitle } from '../common/SectionTitle'
import { MetricTile, TableShell } from '../common/Material'

const EVENT_TYPE_COLORS: Record<string, string> = {
  RUN_CREATED: 'bg-blue-100 text-blue-700',
  RUN_STARTED: 'bg-emerald-100 text-emerald-700',
  RUN_FINISHED: 'bg-slate-100 text-slate-700',
  RUN_FAILED: 'bg-red-100 text-red-700',
  NODE_STARTED: 'bg-cyan-100 text-cyan-700',
  NODE_FINISHED: 'bg-emerald-100 text-emerald-700',
  NODE_SKIPPED: 'bg-amber-100 text-amber-700',
  NODE_DOWNGRADED: 'bg-orange-100 text-orange-700',
  KILL_SWITCH_TRIGGERED: 'bg-red-100 text-red-700',
  DVG_PERMISSION_CHANGED: 'bg-purple-100 text-purple-700',
  QIAM_DISCOUNT_APPLIED: 'bg-indigo-100 text-indigo-700',
  SIGNALOPS_STATE_CHANGED: 'bg-pink-100 text-pink-700',
  FINAL_WRITER_MODE_CHANGED: 'bg-teal-100 text-teal-700',
  ERROR_LEDGER_CREATED: 'bg-red-100 text-red-700',
  PATCH_CANDIDATE_CREATED: 'bg-lime-100 text-lime-700',
}

function safeText(value: unknown, fallback = '') {
  return typeof value === 'string' ? value : fallback
}

function shortHash(value: unknown) {
  const text = safeText(value)
  return text ? `${text.slice(0, 16)}...` : '-'
}

function auditEventKey(event: AuditLogEvent) {
  return `${safeText(event.runId)}:${safeText(event.auditId)}:${safeText(event.eventType)}:${safeText(event.node)}:${safeText(event.timestamp)}`
}

function mergeAuditLogEvents(runId: string, ...sources: Array<AuditLogEvent[] | undefined>) {
  const seen = new Set<string>()
  const merged: AuditLogEvent[] = []
  for (const source of sources) {
    for (const event of source ?? []) {
      if (event.runId !== runId) continue
      const key = auditEventKey(event)
      if (seen.has(key)) continue
      seen.add(key)
      merged.push(event)
    }
  }
  return merged
}

export function AuditLogPage() {
  const { currentRun, liveEvents, loadRunHistory } = useAnalysisStore()
  const [auditError, setAuditError] = useState<string | undefined>()
  const [runLoading, setRunLoading] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [filterType, setFilterType] = useState<string>('ALL')

  useEffect(() => {
    if (currentRun) {
      setRunLoading(false)
      return
    }
    let cancelled = false
    setRunLoading(true)
    setAuditError(undefined)
    loadRunHistory()
      .catch((error) => {
        if (!cancelled) {
          setAuditError(`Run history unavailable: ${error instanceof Error ? error.message : 'unknown error'}`)
        }
      })
      .finally(() => {
        if (!cancelled) setRunLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [currentRun, loadRunHistory])

  const auditKey = currentRun ? `audit-log:${currentRun.runId}` : null
  const {
    data: fetchedAudit,
    error: auditFetchError,
    isValidating: auditValidating,
  } = useCachedResource<AuditLogEvent[]>(auditKey, () =>
    currentRun ? getAuditLog(currentRun.runId) : Promise.resolve<AuditLogEvent[]>([]),
  )

  const auditLogs = useMemo(
    () =>
      currentRun
        ? mergeAuditLogEvents(currentRun.runId, fetchedAudit, currentRun.auditLog, liveEvents)
        : [],
    [currentRun, fetchedAudit, liveEvents],
  )
  const auditApiError = auditFetchError
    ? auditFetchError instanceof Error
      ? auditFetchError.message
      : 'unknown error'
    : undefined
  const loading = runLoading || (auditLogs.length === 0 && auditValidating)

  const eventTypes = useMemo(() => {
    const types = new Set(auditLogs.map((event) => safeText(event.eventType, 'UNKNOWN')))
    return ['ALL', ...Array.from(types)]
  }, [auditLogs])

  const filteredLogs = useMemo(() => {
    const normalizedQuery = searchQuery.toLowerCase()
    return auditLogs.filter((event) => {
      const matchesSearch =
        normalizedQuery === '' ||
        safeText(event.message).toLowerCase().includes(normalizedQuery) ||
        safeText(event.node).toLowerCase().includes(normalizedQuery) ||
        safeText(event.auditId).toLowerCase().includes(normalizedQuery)
      const matchesType = filterType === 'ALL' || safeText(event.eventType, 'UNKNOWN') === filterType
      return matchesSearch && matchesType
    })
  }, [auditLogs, searchQuery, filterType])

  const handleExport = () => {
    const data = JSON.stringify(filteredLogs, null, 2)
    const blob = new Blob([data], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `audit-log-${currentRun?.runId || 'export'}.json`
    anchor.click()
    URL.revokeObjectURL(url)
  }

  if (!currentRun) {
    return (
      <div className="space-y-6">
        <SectionTitle title="Audit Log / 审计日志" subtitle="审计链路与事件回放" />
        <Card title={runLoading ? '加载运行记录' : '未选择运行记录'} className="!rounded-lg !shadow-none">
          <div className="text-sm leading-6 text-slate-600">
            {runLoading
              ? '正在加载最新运行记录...'
              : '没有可用的当前运行记录。请先创建或选择一次分析运行。'}
          </div>
          {auditError ? (
            <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">
              {auditError}
            </div>
          ) : null}
        </Card>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <SectionTitle title="Audit Log / 审计日志" subtitle="审计链路与事件回放" />

      <Card title="筛选与导出" className="!rounded-lg !shadow-none">
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative flex-1 min-w-[200px]">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              type="text"
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              placeholder="搜索消息、节点或审计 ID..."
              className="w-full rounded-lg border border-slate-200 bg-white pl-9 pr-4 py-2 text-sm text-slate-900 outline-none transition focus:border-slate-400"
            />
          </div>
          <div className="flex items-center gap-2">
            <Filter size={16} className="text-slate-400" />
            <select
              value={filterType}
              onChange={(event) => setFilterType(event.target.value)}
              className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none transition focus:border-slate-400"
            >
              {eventTypes.map((type) => (
                <option key={type} value={type}>
                  {type === 'ALL' ? '全部类型' : type}
                </option>
              ))}
            </select>
          </div>
          <button
            type="button"
            onClick={handleExport}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-600 transition hover:bg-slate-50"
          >
            <Download size={16} />
            导出 JSON
          </button>
        </div>
        <div className="mt-4 grid gap-3 sm:grid-cols-3">
          <MetricTile className="!rounded-lg !p-3 !shadow-none" label="审计记录" value={auditLogs.length} helper="当前运行快照/API 合并" />
          <MetricTile className="!rounded-lg !p-3 !shadow-none" label="筛选后" value={filteredLogs.length} helper={searchQuery || filterType !== 'ALL' ? '已应用筛选' : '未筛选'} tone="primary" />
          <MetricTile className="!rounded-lg !p-3 !shadow-none" label="事件类型" value={Math.max(0, eventTypes.length - 1)} helper="不含全部类型" tone="info" />
        </div>
        {auditApiError ? (
          <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">
            Audit API unavailable; using current run snapshot. {auditApiError}
          </div>
        ) : null}
      </Card>

      {loading ? (
        <Card title="加载中" className="!rounded-lg !shadow-none">
          <div className="text-sm text-slate-600">正在加载审计日志...</div>
        </Card>
      ) : filteredLogs.length === 0 ? (
        <Card title="无审计记录" className="!rounded-lg !shadow-none">
          <div className="text-sm text-slate-600">
            {auditLogs.length === 0 ? '当前运行未生成审计事件。' : '没有匹配筛选条件的审计事件。'}
          </div>
        </Card>
      ) : (
        <Card title="事件账本" className="!rounded-lg !shadow-none">
          <TableShell className="!rounded-lg !shadow-none">
            <div className="overflow-x-auto">
              <table className="institution-table">
                <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className="px-3 py-2 font-semibold">时间</th>
                    <th className="px-3 py-2 font-semibold">事件</th>
                    <th className="px-3 py-2 font-semibold">节点 / 消息</th>
                    <th className="px-3 py-2 font-semibold">状态变更</th>
                    <th className="px-3 py-2 font-semibold">审计与哈希</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 bg-white">
                  {filteredLogs.map((event, index) => {
                    const eventType = safeText(event.eventType, 'UNKNOWN')
                    const node = safeText(event.node, 'system')
                    const auditId = safeText(event.auditId)
                    return (
                      <tr key={auditId || safeText(event.timestamp) || index} className="align-top transition hover:bg-slate-50">
                        <td className="whitespace-nowrap px-3 py-3 text-xs text-slate-500">
                          <div className="flex items-center gap-2">
                            <Clock size={12} className="text-slate-400" />
                            {formatDateTime(safeText(event.timestamp))}
                          </div>
                        </td>
                        <td className="px-3 py-3">
                          <span className={`inline-flex rounded-md px-2 py-0.5 text-[10px] font-semibold ${EVENT_TYPE_COLORS[eventType] || 'bg-slate-100 text-slate-700'}`}>
                            {eventType}
                          </span>
                        </td>
                        <td className="max-w-xl px-3 py-3">
                          <div className="font-semibold text-slate-900">{node}</div>
                          <div className="mt-1 text-xs leading-5 text-slate-600">{safeText(event.message, eventType)}</div>
                        </td>
                        <td className="px-3 py-3">
                          <div className="flex items-center gap-1.5">
                            <Badge status={event.statusBefore || 'WAIT'} className="rounded-md px-2 py-0.5">{event.statusBefore || 'WAIT'}</Badge>
                            <ArrowRight size={12} className="text-slate-300" />
                            <Badge status={event.statusAfter || 'PASS'} className="rounded-md px-2 py-0.5">{event.statusAfter || 'PASS'}</Badge>
                          </div>
                        </td>
                        <td className="px-3 py-3 text-xs text-slate-500">
                          <div className="flex items-center gap-1.5 font-mono text-slate-600">
                            <Hash size={12} className="text-slate-400" />
                            {auditId || '-'}
                          </div>
                          <div className="mt-1 font-mono">in {shortHash(event.inputHash)}</div>
                          <div className="mt-1 font-mono">out {shortHash(event.outputHash)}</div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </TableShell>
        </Card>
      )}
    </div>
  )
}
