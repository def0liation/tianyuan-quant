import create from 'zustand'
import { AnalysisRun, AnalysisRunStatus, AnalysisRunSummary, OrchestratorStep, AuditLogEvent, PermissionItem, RunStreamEvent } from '../types'
import { mockScenarios } from '../mock/scenarios'
import { getAnalysisRun, getAnalysisRuns } from '../api/analysisClient'
import { dedupeInFlight } from '../api/requestCache'
import { BackendHealth } from '../types'
import { useToastStore } from './useToastStore'

interface AnalysisState {
  currentRun?: AnalysisRun
  currentRunId?: string
  runStatus: 'IDLE' | AnalysisRunStatus
  selectedNodeId?: string
  selectedScenarioId: string
  permissionMatrix: PermissionItem[]
  orchestratorSteps: OrchestratorStep[]
  liveEvents: AuditLogEvent[]
  runHistory: AnalysisRunSummary[]
  backendHealth?: BackendHealth
  autoRefreshEnabled: boolean
  autoRefreshInterval: number
  setScenario: (scenarioId: string) => void
  setSelectedNode: (nodeId: string | undefined) => void
  setRun: (run: AnalysisRun) => void
  appendLiveEvent: (event: AuditLogEvent) => void
  refreshRun: (runId: string) => Promise<void>
  loadRunHistory: () => Promise<void>
  selectRun: (runId: string) => Promise<void>
  fallbackToMock: () => void
  setAutoRefresh: (enabled: boolean) => void
}

function toSummary(run: AnalysisRun): AnalysisRunSummary {
  return {
    runId: run.runId,
    stockCode: run.stockCode,
    stockName: run.stockName,
    taskType: run.taskType,
    runMode: run.runMode,
    status: run.status,
    failReason: run.failReason,
    failureCategory: run.failureCategory,
    recovery: run.recovery,
    job: run.job,
    finalAction: run.finalWriter?.finalAction ?? run.finalAction,
    createdAt: run.createdAt,
    updatedAt: run.updatedAt,
    compressed: Boolean(run.compressedSummary),
    compressedAt: run.compressedSummary?.compressed_at ?? run.compressedSummary?.created_at ?? undefined,
    compressedArtifactPath: run.compressedSummary?.artifact_path ?? (run.compressedSummary ? `backend/app/storage/runs/${run.runId}.json#compressedSummary` : undefined),
  }
}

function mergeRunHistory(history: AnalysisRunSummary[], run: AnalysisRun) {
  const summary = toSummary(run)
  const next = [summary, ...history.filter((item) => item.runId !== run.runId)]
  return next.sort((a, b) => (b.updatedAt || b.createdAt).localeCompare(a.updatedAt || a.createdAt))
}

function isMockRun(run?: AnalysisRun) {
  return Boolean(run?.runId?.startsWith('RUN_MOCK_'))
}

function mockScenarioFor(scenarioId: string) {
  return mockScenarios[scenarioId] ?? mockScenarios.qiam_discounted
}

function auditEventKey(event: AuditLogEvent) {
  return `${event.runId}:${event.auditId}:${event.eventType}:${event.node}:${event.timestamp}`
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value))
}

function streamBoundaryText(payload: unknown) {
  if (!isRecord(payload)) return ''
  if (payload.simulation_only !== true || payload.is_real_trade !== false) return ''
  const namespace = typeof payload.allowed_order_namespace === 'string' && payload.allowed_order_namespace.trim()
    ? payload.allowed_order_namespace
    : 'SIM_*'
  const evidenceUsage =
    typeof (payload.evidence_usage ?? payload.evidenceUsage) === 'string' &&
    String(payload.evidence_usage ?? payload.evidenceUsage).trim()
      ? String(payload.evidence_usage ?? payload.evidenceUsage)
      : 'simulation_only'
  const strongConclusionAllowed = (payload.strong_conclusion_allowed ?? payload.strongConclusionAllowed) === true ? 'true' : 'false'
  return `simulation_only=true / is_real_trade=false / evidence_usage=${evidenceUsage} / strong_conclusion_allowed=${strongConclusionAllowed} / ${namespace}`
}

function streamEventToAuditEvent(event: RunStreamEvent, runId: string): AuditLogEvent {
  const boundary = streamBoundaryText(event.payload)
  const message = event.message || event.event_type
  return {
    timestamp: event.timestamp || '',
    runId: event.run_id || runId,
    node: event.node_id || 'system',
    eventType: event.event_type as AuditLogEvent['eventType'],
    message: boundary ? `${message} (${boundary})` : message,
    statusBefore: 'WAIT',
    statusAfter: ['RUN_FAILED', 'RUN_CANCELLED', 'RUN_STALE_RECOVERED', 'RUN_NOT_FOUND', 'RUN_REMOVED', 'STREAM_TIMEOUT'].includes(event.event_type) ? 'FAIL' : 'PASS',
    inputHash: '',
    outputHash: '',
    auditId: event.audit_id || `AUD_STREAM_${runId}_${event.event_type}`,
  }
}

function streamEventsToAuditEvents(events: RunStreamEvent[] | undefined, runId: string) {
  return Array.isArray(events) ? events.map((event) => streamEventToAuditEvent(event, runId)) : []
}

function runLiveEvents(run: AnalysisRun) {
  return [
    ...(run.auditLog || []),
    ...streamEventsToAuditEvents(run.streamEvents, run.runId),
  ]
}

function mergeLiveEvents(existing: AuditLogEvent[], incoming: AuditLogEvent[] | undefined, runId: string) {
  const seen = new Set<string>()
  const merged: AuditLogEvent[] = []
  const relevantExisting = existing.filter((event) => event.runId === runId)
  const auditLog = Array.isArray(incoming) ? incoming : []

  for (const event of [...relevantExisting, ...auditLog]) {
    const key = auditEventKey(event)
    if (seen.has(key)) continue
    seen.add(key)
    merged.push(event)
  }

  return merged
}

export const useAnalysisStore = create<AnalysisState>((set, get) => ({
  currentRun: undefined,
  currentRunId: undefined,
  runStatus: 'IDLE',
  selectedScenarioId: 'qiam_discounted',
  permissionMatrix: [],
  orchestratorSteps: [],
  liveEvents: [],
  runHistory: [],
  autoRefreshEnabled: true,
  autoRefreshInterval: 5000,
  setScenario: (scenarioId) => {
    set((state) => {
      if (!isMockRun(state.currentRun)) {
        return { selectedScenarioId: scenarioId }
      }
      const run = mockScenarioFor(scenarioId)
      return {
        selectedScenarioId: scenarioId,
        currentRun: run,
        currentRunId: run.runId,
        runStatus: run.status,
        liveEvents: runLiveEvents(run),
        runHistory: mergeRunHistory(state.runHistory, run),
      }
    })
  },
  setSelectedNode: (nodeId) => set({ selectedNodeId: nodeId }),
  setRun: (run) => set((state) => ({
    currentRun: run,
    currentRunId: run.runId,
    runStatus: run.status,
    liveEvents: mergeLiveEvents(state.liveEvents, runLiveEvents(run), run.runId),
    runHistory: mergeRunHistory(state.runHistory, run),
  })),
  appendLiveEvent: (event) => set((state) => {
    const key = auditEventKey(event)
    if (state.liveEvents.some((item) => auditEventKey(item) === key)) {
      return state
    }
    return { liveEvents: [event, ...state.liveEvents] }
  }),
  refreshRun: async (runId) => {
    try {
      const run = await getAnalysisRun(runId)
      set((state) => ({
        currentRun: run,
        currentRunId: runId,
        runStatus: run.status,
        liveEvents: mergeLiveEvents(state.liveEvents, runLiveEvents(run), run.runId),
        runHistory: mergeRunHistory(state.runHistory, run),
      }))
    } catch (error) {
      useToastStore.getState().addToast(
        `刷新分析任务失败: ${error instanceof Error ? error.message : '未知错误'}`,
        'error',
        3000
      )
      throw error
    }
  },
  loadRunHistory: async () => {
    await dedupeInFlight('analysis:run-history', async () => {
      try {
        const runs = await getAnalysisRuns()
        const state = get()
        const currentRunId = state.currentRunId
        set({ runHistory: runs })
        if (!state.currentRun && runs.length > 0) {
          const targetRunSummary = currentRunId
            ? runs.find((run) => run.runId === currentRunId) ?? runs[0]
            : runs[0]
          const latestRun = await getAnalysisRun(targetRunSummary.runId)
          set((state) => ({
            currentRun: latestRun,
            currentRunId: latestRun.runId,
            runStatus: latestRun.status,
            liveEvents: mergeLiveEvents(state.liveEvents, runLiveEvents(latestRun), latestRun.runId),
            runHistory: mergeRunHistory(state.runHistory, latestRun),
          }))
        }
      } catch (error) {
        useToastStore.getState().addToast(
          `加载历史记录失败: ${error instanceof Error ? error.message : '未知错误'}`,
          'error',
          3000
        )
        throw error
      }
    })
  },
  selectRun: async (runId) => {
    try {
      const run = await getAnalysisRun(runId)
      set((state) => ({
        currentRun: run,
        currentRunId: run.runId,
        runStatus: run.status,
        liveEvents: runLiveEvents(run),
        runHistory: mergeRunHistory(state.runHistory, run),
      }))
    } catch (error) {
      useToastStore.getState().addToast(
        `选择任务失败: ${error instanceof Error ? error.message : '未知错误'}`,
        'error',
        3000
      )
      throw error
    }
  },
  fallbackToMock: () => {
    const scenarioId = get().selectedScenarioId
    const run = mockScenarioFor(scenarioId)
    set((state) => ({ currentRun: run, currentRunId: run.runId, runStatus: run.status, selectedScenarioId: scenarioId, liveEvents: runLiveEvents(run), runHistory: mergeRunHistory(state.runHistory, run) }))
  },
  setAutoRefresh: (enabled) => set({ autoRefreshEnabled: enabled }),
}))
