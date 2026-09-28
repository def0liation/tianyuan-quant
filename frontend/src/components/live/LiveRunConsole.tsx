import { type ReactNode, useEffect, useMemo, useRef, useState } from 'react'
import { Activity, AlertTriangle, CheckCircle2, RefreshCw, RotateCcw, StopCircle, XCircle } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'
import { cancelAnalysisRun, retryAnalysisRun } from '../../api/analysisClient'
import { connectRunStream } from '../../api/streamClient'
import type { StreamMessage } from '../../api/streamClient'
import { useAnalysisStore } from '../../store/useAnalysisStore'
import { getOperatorApiToken, roleAllows, useOperatorContext } from '../../store/operatorContext'
import { buildConclusionInsights } from '../../utils/conclusionInsights'
import { buildRunFailureNotice } from '../../utils/runFailure'
import { visibleRunHistory } from '../../utils/runHistory'
import { SectionTitle } from '../common/SectionTitle'
import { Card } from '../common/Card'
import { Badge } from '../common/Badge'
import { ConclusionModules } from '../final/ConclusionModules'
import { MetricTile, TableShell } from '../common/Material'

type MetricTone = 'primary' | 'neutral' | 'success' | 'warning' | 'danger' | 'info'

function streamBoundaryText(payload: unknown) {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return ''
  const record = payload as Record<string, unknown>
  if (record.simulation_only !== true || record.is_real_trade !== false) return ''
  const namespace = typeof record.allowed_order_namespace === 'string' && record.allowed_order_namespace.trim()
    ? record.allowed_order_namespace
    : 'SIM_*'
  const evidenceUsage =
    typeof (record.evidence_usage ?? record.evidenceUsage) === 'string' &&
    String(record.evidence_usage ?? record.evidenceUsage).trim()
      ? String(record.evidence_usage ?? record.evidenceUsage)
      : 'simulation_only'
  const strongConclusionAllowed = (record.strong_conclusion_allowed ?? record.strongConclusionAllowed) === true ? 'true' : 'false'
  return `simulation_only=true / is_real_trade=false / evidence_usage=${evidenceUsage} / strong_conclusion_allowed=${strongConclusionAllowed} / ${namespace}`
}

export function LiveRunConsole() {
  const {
    currentRun,
    currentRunId,
    liveEvents,
    runHistory,
    appendLiveEvent,
    refreshRun,
    loadRunHistory,
    selectRun,
  } = useAnalysisStore()
  const [isStreaming, setIsStreaming] = useState(false)
  const [streamErrors, setStreamErrors] = useState<string | null>(null)
  const [loadingRun, setLoadingRun] = useState(false)
  const [jobAction, setJobAction] = useState<'cancel' | 'retry' | null>(null)
  const [jobActionError, setJobActionError] = useState<string | null>(null)
  const [searchParams, setSearchParams] = useSearchParams()
  const deepLinkLoadingRef = useRef<string | null>(null)
  const operator = useOperatorContext()
  const canControlLiveRun = roleAllows(operator.role, 'operator')
  const liveRunControlDisabledReason = canControlLiveRun
    ? ''
    : `实时运行控制需要 operator 权限。当前角色：${operator.role}。`

  const streamAuthToken = operator.apiTokenSet ? getOperatorApiToken() : ''
  const deepLinkedRunId = searchParams.get('run_id') || ''
  const runId = deepLinkedRunId || currentRunId || currentRun?.runId
  const selectableRunHistory = visibleRunHistory(runHistory, { preserveRunIds: [runId, deepLinkedRunId] })
  const job = currentRun?.job ?? runHistory.find((item) => item.runId === runId)?.job
  const currentRunNodes = currentRun?.nodes
  const currentRunStatus = currentRun?.status
  const retryFromNodeId = currentRun?.retry?.from_node_id
  const jobFailedNodeId = job?.failed_node_id
  const jobStatus = job?.status
  const isStaleRecovery =
    currentRun?.status === 'STALE' ||
    currentRun?.failureCategory === 'STALE_RUN_RECOVERY' ||
    job?.status === 'STALE'
  const failedNodeId = useMemo(() => {
    const failedNode = currentRunNodes?.find((item) => ['FAIL', 'ERROR', 'CANCELLED', 'BLOCK_BUY'].includes(String(item.status)) || item.isBlocked)
    const terminalJobFailedNode = ['FAILED', 'STALE', 'CANCELLED'].includes(String(jobStatus)) ? jobFailedNodeId : ''
    const terminalRetryNode = ['FAILED', 'STALE', 'CANCELLED'].includes(String(currentRunStatus)) ? String(retryFromNodeId ?? '') : ''
    return terminalJobFailedNode || failedNode?.id || terminalRetryNode
  }, [currentRunNodes, currentRunStatus, jobFailedNodeId, jobStatus, retryFromNodeId])
  const failedNodeLabel = isStaleRecovery ? '中断节点' : '失败节点'
  const retryActionLabel = isStaleRecovery ? '从中断节点重试' : '从失败节点重试'
  const recentEvents = useMemo(() => liveEvents.slice(0, 12), [liveEvents])
  const conclusionInsights = currentRun ? buildConclusionInsights(currentRun) : []
  const canCancelRunByStatus = Boolean(runId && ['QUEUED', 'RUNNING'].includes(currentRun?.status ?? '') && job?.status !== 'CANCEL_REQUESTED')
  const canRetryRunByStatus = Boolean(
    runId &&
      currentRun &&
      ['FAILED', 'STALE', 'CANCELLED'].includes(currentRun.status) &&
      failedNodeId &&
      (job?.attempt ?? 0) < (job?.max_attempts ?? 3),
  )
  const canCancelRun = canControlLiveRun && canCancelRunByStatus
  const canRetryRun = canControlLiveRun && canRetryRunByStatus
  const failureNotice =
    currentRun && ['FAILED', 'STALE', 'CANCELLED'].includes(currentRun.status) ? buildRunFailureNotice(currentRun, '分析任务未完整完成') : undefined

  useEffect(() => {
    loadRunHistory().catch(() => undefined)
  }, [loadRunHistory])

  useEffect(() => {
    if (!deepLinkedRunId || deepLinkedRunId === runId || deepLinkLoadingRef.current === deepLinkedRunId) return
    deepLinkLoadingRef.current = deepLinkedRunId
    setLoadingRun(true)
    setStreamErrors(null)
    refreshRun(deepLinkedRunId)
      .catch(() => undefined)
      .finally(() => {
        deepLinkLoadingRef.current = null
        setLoadingRun(false)
      })
  }, [deepLinkedRunId, refreshRun, runId])

  useEffect(() => {
    if (!runId) return

    setStreamErrors(null)
    const cleanup = connectRunStream(runId, {
      onOpen: () => setIsStreaming(true),
      onMessage: (message: StreamMessage) => {
        const boundary = streamBoundaryText(message.payload)
        const eventMessage = message.message || message.event_type
        appendLiveEvent({
          timestamp: message.timestamp || new Date().toISOString(),
          runId: message.run_id || runId,
          node: message.node_id || 'system',
          eventType: message.event_type as any,
          message: boundary ? `${eventMessage} (${boundary})` : eventMessage,
          statusBefore: 'WAIT',
          statusAfter: ['RUN_FAILED', 'RUN_CANCELLED', 'RUN_STALE_RECOVERED', 'RUN_NOT_FOUND', 'RUN_REMOVED', 'STREAM_TIMEOUT'].includes(message.event_type) ? 'FAIL' : 'PASS',
          inputHash: '',
          outputHash: '',
          auditId: message.audit_id || '',
        })

        if (['RUN_FINISHED', 'RUN_FAILED', 'RUN_CANCELLED', 'RUN_STALE_RECOVERED', 'RUN_REMOVED', 'STREAM_TIMEOUT'].includes(message.event_type)) {
          refreshRun(message.run_id || runId).catch(() => undefined)
          loadRunHistory().catch(() => undefined)
        }
      },
      onError: () => {
        setStreamErrors('实时流连接异常，已保留当前结果。可稍后点击刷新。')
      },
      onClose: () => setIsStreaming(false),
    }, {
      authToken: streamAuthToken,
    })

    return cleanup
  }, [runId, streamAuthToken, appendLiveEvent, refreshRun, loadRunHistory])

  useEffect(() => {
    if (!runId || (currentRun?.status !== 'RUNNING' && !['QUEUED', 'RUNNING', 'CANCEL_REQUESTED'].includes(job?.status ?? ''))) return
    const timer = window.setInterval(() => {
      refreshRun(runId).catch(() => undefined)
    }, 3000)
    return () => window.clearInterval(timer)
  }, [runId, currentRun?.status, job?.status, refreshRun])

  async function handleSelectRun(nextRunId: string) {
    if (!nextRunId) return
    setLoadingRun(true)
    setStreamErrors(null)
    try {
      await selectRun(nextRunId)
      setSearchParams({ run_id: nextRunId })
    } finally {
      setLoadingRun(false)
    }
  }

  async function handleRefresh() {
    if (!runId) return
    setLoadingRun(true)
    try {
      await refreshRun(runId)
      await loadRunHistory().catch(() => undefined)
    } finally {
      setLoadingRun(false)
    }
  }

  async function handleCancelRun() {
    if (!canControlLiveRun) {
      setJobActionError(liveRunControlDisabledReason)
      return
    }
    if (!runId || !canCancelRunByStatus) return
    setJobAction('cancel')
    setJobActionError(null)
    try {
      await cancelAnalysisRun(runId, { operator: 'frontend_live_run' })
      await refreshRun(runId).catch(() => undefined)
      await loadRunHistory().catch(() => undefined)
    } catch (error) {
      setJobActionError(error instanceof Error ? error.message : '取消任务失败。')
    } finally {
      setJobAction(null)
    }
  }

  async function handleRetryRun() {
    if (!canControlLiveRun) {
      setJobActionError(liveRunControlDisabledReason)
      return
    }
    if (!runId || !canRetryRunByStatus) return
    setJobAction('retry')
    setJobActionError(null)
    try {
      await retryAnalysisRun(runId, {
        from_node_id: failedNodeId || undefined,
        reason: 'Retry requested from Live Run Console.',
        operator: 'frontend_live_run',
      })
      await refreshRun(runId).catch(() => undefined)
      await loadRunHistory().catch(() => undefined)
    } catch (error) {
      setJobActionError(error instanceof Error ? error.message : '重试任务失败。')
    } finally {
      setJobAction(null)
    }
  }

  return (
    <div data-testid="live-run-console" className="space-y-6">
      <SectionTitle title="实时运行" subtitle="查看当前任务、历史任务、建议模块和后端审计事件流。" dataMode={currentRun?.dataMode} />

      {failureNotice && (
        <div className="rounded-lg border border-rose-200 bg-rose-50 p-4">
          <div className="flex items-start gap-3">
            <XCircle className="mt-0.5 h-5 w-5 flex-shrink-0 text-rose-600" />
            <div className="flex-1 min-w-0">
              <h3 className="text-sm font-semibold text-rose-900">{failureNotice.title}</h3>
              <p className="mt-1 text-xs leading-5 text-rose-700">
                {failureNotice.description}
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                {failureNotice.tags.map((tag) => (
                  <span key={tag} className="rounded-md border border-rose-200 bg-white px-2.5 py-1 text-xs font-medium text-rose-700">
                    {tag}
                  </span>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="grid gap-6 xl:grid-cols-[1.4fr_1fr]">
        <Card title="当前任务" className="!rounded-lg !shadow-none">
          <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="min-w-0">
                <div className="text-xs font-semibold uppercase text-slate-500">运行 ID</div>
                <div data-testid="live-run-current-run-id" className="mt-1 break-all text-sm font-semibold text-slate-950">{runId ?? '尚未创建'}</div>
              </div>
              <div data-testid="live-run-stream-status" className={`inline-flex items-center gap-2 rounded-md border px-3 py-2 text-xs font-semibold ${
                isStreaming ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-slate-200 bg-white text-slate-600'
              }`}>
                <Activity size={15} />
                {isStreaming ? '已连接' : '未连接'}
              </div>
            </div>
          </div>

          <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <MetricTile className="!rounded-lg !p-3 !shadow-none" label="股票代码" value={currentRun?.stockCode ?? 'N/A'} helper={currentRun?.stockName || '当前运行标的'} />
            <MetricTile className="!rounded-lg !p-3 !shadow-none" label="任务类型" value={currentRun?.taskType ?? 'N/A'} helper={currentRun?.runMode ?? 'N/A'} />
            <MetricTile className="!rounded-lg !p-3 !shadow-none" label="当前阶段" value={currentRun?.status ?? 'N/A'} tone={statusTone(currentRun?.status)} helper={job ? jobStatusLabel(job.status, currentRun?.failureCategory) : '尚未入队'} />
            <MetricTile className="!rounded-lg !p-3 !shadow-none" label="尝试次数" value={`${job?.attempt ?? 0}/${job?.max_attempts ?? 3}`} helper={`操作者：${job?.last_operator || job?.operator || 'local_workbench'}`} />
          </div>

          <div data-testid="live-run-job-lifecycle" className="mt-5 border-t border-slate-100 pt-4">
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <span className="text-xs font-semibold uppercase text-slate-400">任务生命周期</span>
              <Badge status={job?.status ?? 'WAIT'}>{job ? jobStatusLabel(job.status, currentRun?.failureCategory) : '尚未入队'}</Badge>
            </div>
            <div className="grid gap-3 text-xs text-slate-600 md:grid-cols-3">
              <div className="rounded-lg border border-slate-200 bg-white px-3 py-2">尝试次数：{job?.attempt ?? 0}/{job?.max_attempts ?? 3}</div>
              <div className="rounded-lg border border-slate-200 bg-white px-3 py-2">{failedNodeLabel}：{failedNodeId || '无'}</div>
              <div className="rounded-lg border border-slate-200 bg-white px-3 py-2">操作者：{job?.last_operator || job?.operator || 'local_workbench'}</div>
              <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 md:col-span-3">最近错误：{job?.last_error || currentRun?.failReason || '无'}</div>
            </div>
            {job?.history?.length ? (
              <div className="mt-3 space-y-2">
                {job.history.slice(-4).reverse().map((event, index) => (
                  <div key={`${event.event}-${event.at}-${index}`} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
                    <span className="font-medium text-slate-800">{jobEventLabel(event.event)} · 第 {event.attempt} 次</span>
                    <span>{event.at}</span>
                  </div>
                ))}
              </div>
            ) : null}
          </div>

          <div className="mt-5 flex flex-wrap gap-2 text-xs text-slate-500">
            <span data-testid="live-run-control-role">角色：{operator.role}；控制：{canControlLiveRun ? 'operator+' : '已阻断'}</span>
            {!canControlLiveRun ? (
              <span data-testid="live-run-control-disabled-reason" className="text-amber-700">{liveRunControlDisabledReason}</span>
            ) : null}
          </div>

          <div className="mt-3 flex flex-wrap gap-3">
            <button
              type="button"
              onClick={handleRefresh}
              disabled={!runId || loadingRun}
              className="inline-flex items-center gap-2 rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <RefreshCw size={16} className={loadingRun ? 'animate-spin' : ''} />
              刷新当前任务
            </button>
            <button
              type="button"
              data-testid="live-run-cancel-run"
              onClick={handleCancelRun}
              disabled={!canCancelRun || jobAction !== null}
              title={!canControlLiveRun ? liveRunControlDisabledReason : undefined}
              className="inline-flex items-center gap-2 rounded-lg border border-red-200 px-4 py-2 text-sm font-medium text-red-700 transition hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <StopCircle size={16} />
              {jobAction === 'cancel' ? '取消中...' : '取消运行'}
            </button>
            <button
              type="button"
              data-testid="live-run-retry-run"
              onClick={handleRetryRun}
              disabled={!canRetryRun || jobAction !== null}
              title={!canControlLiveRun ? liveRunControlDisabledReason : undefined}
              className="inline-flex items-center gap-2 rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <RotateCcw size={16} className={jobAction === 'retry' ? 'animate-spin' : ''} />
              {jobAction === 'retry' ? '重试中...' : retryActionLabel}
            </button>
          </div>

          {streamErrors && (
            <div data-testid="live-run-stream-error" className="mt-4 rounded-lg bg-amber-50 p-4 text-sm text-amber-700">
              {streamErrors}
            </div>
          )}
          {jobActionError && <div className="mt-4 rounded-lg bg-rose-50 p-4 text-sm text-rose-700">{jobActionError}</div>}
        </Card>

        <Card title="任务历史" className="!rounded-lg !shadow-none">
          <div className="space-y-3">
            <select
              value={runId ?? ''}
              onChange={(event) => handleSelectRun(event.target.value)}
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900"
            >
              {selectableRunHistory.map((run) => (
                <option key={run.runId} value={run.runId}>
                  {run.stockCode} · {run.taskType} · {run.status}
                </option>
              ))}
            </select>
            <div className="text-xs leading-5 text-slate-500">
              历史来自本地持久化运行记录。重启后端后，会重新加载已保存的任务。
            </div>
          </div>
        </Card>
      </div>

      <div className="grid gap-6 xl:grid-cols-4">
        <HealthCard title="DVG" status={currentRun?.dvg.status ?? 'WAIT'} />
        <HealthCard
          title="QIAM"
          status={currentRun?.qiam.finalBuySuitability === 'FAVORABLE' ? 'PASS' : currentRun?.qiam.finalBuySuitability === 'NEUTRAL' ? 'WARN' : 'BLOCK_BUY'}
          label={currentRun?.qiam.finalBuySuitability ?? 'UNKNOWN'}
        />
        <HealthCard title="最终动作" status={currentRun?.finalWriter?.finalAction ?? currentRun?.finalAction ?? 'WAIT'} label={<span data-testid="live-run-final-action">{currentRun?.finalWriter?.finalAction ?? currentRun?.finalAction ?? 'WAIT'}</span>} />
        <HealthCard title="熔断开关" status={currentRun?.killSwitch.level ?? 'NONE'} />
      </div>

      {conclusionInsights.length ? (
        <ConclusionModules modules={conclusionInsights} previewItems={2} columns="xl:grid-cols-4" />
      ) : null}

      <Card title="实时事件流" className="!rounded-lg !shadow-none">
        <TableShell className="!rounded-lg !shadow-none">
          {recentEvents.length === 0 ? (
            <div className="px-4 py-8 text-center text-sm text-slate-500">暂无实时事件。</div>
          ) : (
            <div className="divide-y divide-slate-100">
              {recentEvents.map((event, index) => (
                <div
                  key={`${event.auditId}-${index}`}
                  data-testid={`live-run-event-${event.eventType}`}
                  data-status-after={event.statusAfter}
                  className="grid gap-3 bg-white px-4 py-3 text-sm transition hover:bg-slate-50 lg:grid-cols-[180px_220px_1fr]"
                >
                  <div className="flex items-center gap-2 text-xs text-slate-500">
                    <span className={`h-2.5 w-2.5 rounded-full ${eventDotClass(event.statusAfter)}`} />
                    <span>{event.timestamp}</span>
                  </div>
                  <div className="min-w-0">
                    <Badge status={event.statusAfter} className="rounded-md px-2 py-0.5">{event.eventType}</Badge>
                    <div className="mt-1 truncate text-xs text-slate-500">节点：{event.node}</div>
                  </div>
                  <div className="leading-6 text-slate-700">{event.message}</div>
                </div>
              ))}
            </div>
          )}
        </TableShell>
      </Card>
    </div>
  )
}

function HealthCard({ title, status, label }: { title: string; status: string; label?: ReactNode }) {
  const pct = statusHealthPercent(status)
  return (
    <Card title={title} className="!rounded-lg !shadow-none">
      <div className="flex items-center justify-between gap-3">
        <Badge status={status}>{label ?? status}</Badge>
        {pct >= 70 ? <CheckCircle2 size={18} className="text-emerald-600" /> : <AlertTriangle size={18} className="text-amber-600" />}
      </div>
      <div className="mt-4 h-2 rounded-full bg-slate-100">
        <div className={`h-full rounded-full ${pct >= 70 ? 'bg-emerald-500' : pct >= 40 ? 'bg-amber-500' : 'bg-rose-500'}`} style={{ width: `${pct}%` }} />
      </div>
    </Card>
  )
}

function statusTone(status?: string): MetricTone {
  if (!status) return 'neutral'
  if (['COMPLETED', 'PASS', 'READY', 'FAVORABLE', 'NONE'].includes(status)) return 'success'
  if (['RUNNING', 'QUEUED', 'CREATED'].includes(status)) return 'primary'
  if (['WARN', 'NEUTRAL', 'CANCEL_REQUESTED'].includes(status)) return 'warning'
  if (['FAILED', 'FAIL', 'ERROR', 'STALE', 'CANCELLED', 'BLOCK_BUY', 'HARD'].includes(status)) return 'danger'
  return 'neutral'
}

function statusHealthPercent(status: string) {
  if (['PASS', 'FAVORABLE', 'NONE', 'COMPLETED'].includes(status)) return 92
  if (['WARN', 'NEUTRAL', 'SOFT', 'RUNNING', 'QUEUED', 'WAIT'].includes(status)) return 58
  if (['BLOCK_BUY', 'FAIL', 'FAILED', 'ERROR', 'HARD', 'STALE', 'CANCELLED'].includes(status)) return 24
  return 45
}

function eventDotClass(status?: string) {
  if (['PASS', 'COMPLETED'].includes(String(status))) return 'bg-emerald-500'
  if (['WARN', 'WAIT', 'RUNNING'].includes(String(status))) return 'bg-amber-500'
  if (['FAIL', 'ERROR', 'BLOCK_BUY', 'CANCELLED'].includes(String(status))) return 'bg-rose-500'
  return 'bg-slate-400'
}

function jobStatusLabel(status: string, failureCategory?: string) {
  if (status === 'FAILED' && failureCategory === 'MARKET_DATA_PREFLIGHT_BLOCKED') return '已阻断'
  const labels: Record<string, string> = {
    PENDING: '待入队',
    QUEUED: '已入队',
    RUNNING: '运行中',
    CANCEL_REQUESTED: '取消请求中',
    COMPLETED: '已完成',
    FAILED: '失败',
    CANCELLED: '已取消',
    STALE: '已恢复为异常',
  }
  return labels[status] ?? status
}

function jobEventLabel(event: string) {
  const labels: Record<string, string> = {
    JOB_QUEUED: '入队',
    JOB_RUNNING: '开始运行',
    JOB_CANCEL_REQUESTED: '请求取消',
    JOB_COMPLETED: '完成',
    JOB_FAILED: '失败',
    JOB_CANCELLED: '取消',
    JOB_STALE: '异常恢复',
  }
  return labels[event] ?? event
}
