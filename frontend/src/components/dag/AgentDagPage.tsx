import { useCallback, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import ReactFlow, { Background, Controls, MiniMap, type Edge, type Node, type NodeMouseHandler } from 'reactflow'
import 'reactflow/dist/style.css'
import { useAnalysisStore } from '../../store/useAnalysisStore'
import type { AgentNode, AgentOutputSource, AgentTokenUsageRow, AnalysisRun, LLMTraceItem } from '../../types'
import { SectionTitle } from '../common/SectionTitle'
import { Card } from '../common/Card'
import { getStatusColor } from '../../utils/statusColor'
import { canonicalAgentFor } from '../../utils/agentCanonical'
import { MetricTile, TableShell } from '../common/Material'

type AgentObservation = {
  node: AgentNode
  source: AgentOutputSource
  sourceLabel: string
  sourceClass: string
  sourceStroke: string
  profile: string
  providerModel: string
  llmStatus: string
  tokens: number
  latency: number
  finishReason: string
  reason: string
  legacyCompatibilityOnly: boolean
  canonicalNode: string
  activeNode: boolean
}

type AgentDagSourceCounts = {
  llm: number
  degraded: number
  rule: number
  plugin: number
  mock: number
  compatibility: number
}

type AgentDagEvidenceStrength = 'LOW' | 'MEDIUM'

type AgentDagGovernance = {
  contextId: string
  evidenceStrength: AgentDagEvidenceStrength
  blocker: string
  nextAction: string
  simulationOnly: boolean
  isRealTrade: boolean
  evidenceUsage: string
  strongConclusionAllowed: boolean
}

function normalizedEvidenceStrength(value: unknown): AgentDagEvidenceStrength {
  const normalized = String(value || '').trim().toUpperCase()
  if (['UNKNOWN', 'SUPPORTING_ONLY', 'LOW', 'WEAK', 'WARN', 'WARNING', 'REVIEW', 'REVIEW_ONLY'].includes(normalized)) return 'LOW'
  if (normalized === 'MEDIUM') return 'MEDIUM'
  if (['RESEARCH_GRADE', 'PRIMARY_EVIDENCE_READY'].includes(normalized)) return 'MEDIUM'
  if (['STRONG', 'HIGH', 'PRIMARY', 'PRIMARY_EVIDENCE', 'PASS', 'READY'].includes(normalized)) return 'MEDIUM'
  return 'LOW'
}

const SOURCE_META: Record<string, { label: string; className: string; stroke: string }> = {
  LLM: {
    label: '真实 LLM 输出',
    className: 'border-emerald-200 bg-emerald-50 text-emerald-800',
    stroke: '#059669',
  },
  LLM_DEGRADED: {
    label: 'LLM 降级输出',
    className: 'border-amber-200 bg-amber-50 text-amber-800',
    stroke: '#d97706',
  },
  LLM_FAILED: {
    label: 'LLM 失败输出',
    className: 'border-red-200 bg-red-50 text-red-800',
    stroke: '#dc2626',
  },
  RULE_ENGINE: {
    label: '规则引擎输出',
    className: 'border-slate-200 bg-slate-50 text-slate-700',
    stroke: '#64748b',
  },
  PLUGIN_OBSERVATION: {
    label: '只读插件观察',
    className: 'border-sky-200 bg-sky-50 text-sky-800',
    stroke: '#0284c7',
  },
  NODE_SUMMARY: {
    label: '节点摘要输出',
    className: 'border-blue-200 bg-blue-50 text-blue-800',
    stroke: '#2563eb',
  },
  MOCK: {
    label: 'Mock / 示例输出',
    className: 'border-purple-200 bg-purple-50 text-purple-800',
    stroke: '#7c3aed',
  },
}

function sourceMeta(source: AgentOutputSource) {
  return SOURCE_META[normalizeSource(source)] ?? SOURCE_META.NODE_SUMMARY
}

function numberValue(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0
}

function textValue(value: unknown) {
  return typeof value === 'string' && value.trim() ? value.trim() : ''
}

function asRecord(value: unknown): Record<string, any> {
  return value && typeof value === 'object' ? value as Record<string, any> : {}
}

function nodesFor(run: AnalysisRun) {
  return Array.isArray(run.nodes) ? run.nodes : []
}

function normalizeSource(source: unknown): AgentOutputSource {
  const value = textValue(source).toUpperCase()
  if (value === 'LLM') return 'LLM'
  if (value === 'LLM_DEGRADED') return 'LLM_DEGRADED'
  if (value === 'LLM_FAILED') return 'LLM_FAILED'
  if (value === 'RULE_ENGINE') return 'RULE_ENGINE'
  if (value === 'PLUGIN_OBSERVATION') return 'PLUGIN_OBSERVATION'
  if (value === 'NODE_SUMMARY') return 'NODE_SUMMARY'
  if (value === 'MOCK' || value === 'MOCK_ESTIMATE') return 'MOCK'
  return 'NODE_SUMMARY'
}

function runnerFor(node: AgentNode) {
  return asRecord(asRecord(node.rawJson).llmRunner)
}

function usageTokens(usage: unknown) {
  const record = asRecord(usage)
  return numberValue(record.total_tokens)
    || numberValue(record.totalTokens)
    || numberValue(record.prompt_tokens) + numberValue(record.completion_tokens)
    || numberValue(record.input_tokens) + numberValue(record.output_tokens)
    || numberValue(record.promptTokens) + numberValue(record.completionTokens)
    || numberValue(record.inputTokens) + numberValue(record.outputTokens)
}

function traceMap(run: AnalysisRun) {
  const traces = Array.isArray(run.llmTrace) ? run.llmTrace : []
  return new Map(traces.filter((trace) => textValue(trace.nodeId)).map((trace) => [trace.nodeId, trace]))
}

function tokenRowMap(run: AnalysisRun) {
  const rows = Array.isArray(run.tokenUsage?.rows) ? run.tokenUsage.rows : []
  return new Map(rows.filter((row) => textValue(row.node)).map((row) => [row.node, row]))
}

function isMockOutput(_run: AnalysisRun, node: AgentNode, row?: AgentTokenUsageRow) {
  return normalizeSource(row?.source) === 'MOCK'
    || textValue(row?.usage_source ?? row?.usageSource).toUpperCase() === 'MOCK_ESTIMATE'
    || textValue(node.auditId).includes('MOCK')
    || textValue(node.id).startsWith('mock_')
}

function isNonExecutablePluginObservation(node: AgentNode) {
  const rawJson = asRecord(node.rawJson)
  const dagRegistration = asRecord(rawJson.dagRegistration)
  const permissionSandbox = asRecord(rawJson.permissionSandbox)
  const pluginObservation = asRecord(rawJson.pluginObservation)
  const nodeId = textValue(node.id)
  const nodeType = textValue(rawJson.nodeType).toLowerCase()
  const executionMode = textValue(dagRegistration.execution_mode).toUpperCase()
  const permissionMode = textValue(permissionSandbox.mode).toUpperCase()
  const observationStatus = textValue(pluginObservation.status).toUpperCase()
  const canExecuteCode = rawJson.canExecuteCode === true || asRecord(node).canExecuteCode === true

  const isPluginObservation = nodeId.startsWith('plugin:') || nodeType === 'plugin_observation'
  const isReviewOnly = executionMode === 'PLAN_ONLY_NO_EXECUTION'
    || permissionMode === 'READ_ONLY_NO_CODE'
    || observationStatus === 'RECORDED_NO_EXECUTION'

  return isPluginObservation && isReviewOnly && rawJson.directExecution !== true && !canExecuteCode
}

function classifyOutput(run: AnalysisRun, node: AgentNode, row?: AgentTokenUsageRow, trace?: LLMTraceItem): AgentOutputSource {
  if (isMockOutput(run, node, row)) return 'MOCK'
  if (isNonExecutablePluginObservation(node)) return 'PLUGIN_OBSERVATION'
  const runner = runnerFor(node)
  const status = textValue(row?.llm_status ?? row?.llmStatus ?? row?.status ?? trace?.status ?? runner.status).toUpperCase()
  const error = textValue(row?.error ?? trace?.error ?? runner.error)
  const downgradeText = (node.downgradeReasons ?? []).join(' ')
  const outputText = `${node.outputSummary ?? ''} ${downgradeText}`.toLowerCase()

  if (status === 'COMPLETED') return 'LLM'
  if (['FAILED', 'FAIL', 'ERROR'].includes(status)) return 'LLM_FAILED'
  if (status === 'SKIPPED' || error || outputText.includes('llm failed') || outputText.includes('llm skipped')) {
    return 'LLM_DEGRADED'
  }
  const rowSource = row?.source ? normalizeSource(row.source) : ''
  if (rowSource === 'LLM_DEGRADED' || rowSource === 'LLM_FAILED' || rowSource === 'PLUGIN_OBSERVATION' || rowSource === 'NODE_SUMMARY') return rowSource
  if (rowSource === 'LLM' || numberValue(row?.total_tokens) > 0 || numberValue(trace?.totalTokens) > 0) return 'LLM'
  if (rowSource === 'MOCK') return 'MOCK'
  if (rowSource === 'RULE_ENGINE') return 'RULE_ENGINE'
  return 'RULE_ENGINE'
}

function profileFor(row?: AgentTokenUsageRow, trace?: LLMTraceItem, runner: Record<string, any> = {}) {
  return textValue(row?.profile_id ?? row?.profileId ?? trace?.profileId ?? runner.profileId) || '未记录'
}

function providerModelFor(row?: AgentTokenUsageRow, trace?: LLMTraceItem, runner: Record<string, any> = {}) {
  const provider = textValue(row?.provider ?? trace?.provider ?? runner.provider)
  const model = textValue(row?.model ?? trace?.model ?? runner.model)
  if (provider && model) return `${provider} / ${model}`
  return provider || model || '未记录'
}

function degradationReason(
  source: AgentOutputSource,
  node: AgentNode,
  row?: AgentTokenUsageRow,
  trace?: LLMTraceItem,
  runner: Record<string, any> = {},
) {
  if (isNonExecutablePluginObservation(node)) {
    return '只读插件观察节点已记录；执行模式为 PLAN_ONLY_NO_EXECUTION / READ_ONLY_NO_CODE，不需要调用 Agent 或 LLM。'
  }
  const explicit = textValue(row?.degradation_reason ?? row?.degradationReason)
    || textValue(row?.error)
    || textValue(trace?.error)
    || textValue(runner.error)
    || (node.downgradeReasons ?? []).join('；')
  if (explicit) return explicit
  if (source === 'LLM') {
    const total = numberValue(row?.total_tokens) || numberValue(trace?.totalTokens) || usageTokens(runner.usage)
    return total > 0 ? 'provider 返回了 usage，可用于本次 token 计量。' : 'LLM 调用成功，但 provider 未返回 usage；token 显示为 0。'
  }
  if (source === 'RULE_ENGINE') return '本轮未记录真实 LLM 调用，展示规则引擎或模块产物。'
  if (source === 'MOCK') return '当前为 mock/sample 产物，不能作为真实 LLM 调用成功证据。'
  return '本轮没有可用的 LLM 完成记录。'
}

function buildObservations(run: AnalysisRun): AgentObservation[] {
  const traces = traceMap(run)
  const tokenRows = tokenRowMap(run)
  const agentResults = new Map((run.agentResults ?? []).map((item) => [item.node, item]))
  const moduleResults = asRecord(run.agentModuleResults)
  return nodesFor(run).map((node) => {
    const row = tokenRows.get(node.id)
    const trace = traces.get(node.id)
    const runner = runnerFor(node)
    const source = classifyOutput(run, node, row, trace)
    const meta = sourceMeta(source)
    const agentResult = agentResults.get(node.id)
    const moduleResult = asRecord(moduleResults[node.id])
    const inferredCanonicalNode = canonicalAgentFor(node.id)
    const resultActiveNode = typeof agentResult?.activeNode === 'boolean' ? agentResult.activeNode : undefined
    const moduleActiveNode = typeof moduleResult.activeNode === 'boolean' ? moduleResult.activeNode : undefined
    const activeNode = resultActiveNode ?? moduleActiveNode ?? true
    const legacyCompatibilityOnly = agentResult?.legacyCompatibilityOnly === true
      || moduleResult.legacyCompatibilityOnly === true
      || Boolean(inferredCanonicalNode)
      || activeNode === false
    const canonicalNode = textValue(agentResult?.canonicalNode) || textValue(moduleResult.canonicalNode) || inferredCanonicalNode || ''
    const rawTokens = numberValue(row?.total_tokens) || numberValue(trace?.totalTokens) || usageTokens(runner.usage)
    const tokens = source === 'MOCK' ? 0 : rawTokens
    const latency = numberValue(row?.latency_ms) || numberValue(trace?.latencyMs) || numberValue(runner.latencyMs) || numberValue(node.duration)
    return {
      node,
      source,
      sourceLabel: meta.label,
      sourceClass: meta.className,
      sourceStroke: meta.stroke,
      profile: profileFor(row, trace, runner),
      providerModel: providerModelFor(row, trace, runner),
      llmStatus: textValue(row?.llm_status ?? row?.llmStatus ?? row?.status ?? trace?.status ?? runner.status) || 'RULE_ENGINE',
      tokens,
      latency,
      finishReason: textValue(row?.finish_reason ?? row?.finishReason ?? trace?.finishReason ?? runner.finishReason) || '未返回',
      reason: degradationReason(source, node, row, trace, runner),
      legacyCompatibilityOnly,
      canonicalNode,
      activeNode: legacyCompatibilityOnly ? false : activeNode,
    }
  })
}

function formatNumber(value: number) {
  return value.toLocaleString()
}

function isCompatibilityOnly(item: AgentObservation) {
  return item.legacyCompatibilityOnly || item.activeNode === false
}

function compatibilityLabel(item: AgentObservation) {
  return item.canonicalNode ? `兼容 -> ${item.canonicalNode}` : '兼容别名'
}

function buildAgentDagNodeGovernance(item: AgentObservation, runGovernance?: AgentDagGovernance | null): AgentDagGovernance {
  const compatibilityOnly = isCompatibilityOnly(item)
  const status = String(item.node.status || '').toUpperCase()
  const missingData = (item.node.missingData ?? []).length > 0
  const blocked = item.node.isBlocked || ['BLOCK', 'BLOCK_BUY', 'FAIL', 'ERROR'].includes(status)
  const evidenceUsage = String(item.node.evidenceUsage || 'simulation_only')
  const strongConclusionAllowed = item.node.strongConclusionAllowed === true
  const evidenceBoundaryBroken = evidenceUsage !== 'simulation_only' || strongConclusionAllowed

  let evidenceStrength: AgentDagEvidenceStrength = normalizedEvidenceStrength(item.node.evidenceStrength)
  if (evidenceBoundaryBroken || compatibilityOnly || item.source === 'MOCK' || item.source === 'PLUGIN_OBSERVATION') {
    evidenceStrength = 'LOW'
  } else if (item.source === 'LLM_DEGRADED' || item.source === 'LLM_FAILED' || blocked || missingData) {
    evidenceStrength = 'LOW'
  }

  const canonical = item.canonicalNode || 'canonical active node'
  let blocker = '无节点级阻断，继续人工复核'
  if (evidenceBoundaryBroken) {
    blocker = 'Agent node evidence boundary violated'
  } else if (compatibilityOnly) {
    blocker = `Compatibility-only alias; use ${canonical} as canonical state`
  } else if (item.source === 'MOCK') {
    blocker = 'Mock/sample output cannot prove active Agent execution'
  } else if (item.source === 'PLUGIN_OBSERVATION') {
    blocker = 'Plugin observation is read-only and cannot act as executable DAG evidence'
  } else if (item.source === 'LLM_FAILED' || item.source === 'LLM_DEGRADED') {
    blocker = 'LLM output degraded or failed for this node'
  } else if (blocked) {
    blocker = 'Node status blocks downstream evidence promotion'
  } else if (missingData) {
    blocker = 'Node is missing required data fields'
  }

  let nextAction = '继续进入 guardrail_hub / quant_core 仅模拟复核'
  if (compatibilityOnly) {
    nextAction = `Inspect canonical node ${canonical}`
  } else if (item.source === 'MOCK' || item.source === 'PLUGIN_OBSERVATION') {
    nextAction = 'Replace with active run evidence before downstream conclusions'
  } else if (item.source === 'LLM_FAILED' || item.source === 'LLM_DEGRADED') {
    nextAction = 'Review retry diagnostics or keep rule output as weak evidence'
  } else if (blocked || missingData) {
    nextAction = 'Resolve node blocker before promoting evidence'
  }

  return {
    contextId: item.node.id,
    evidenceStrength,
    blocker,
    nextAction,
    simulationOnly: item.node.simulationOnly !== false && (runGovernance?.simulationOnly ?? true),
    isRealTrade: item.node.isRealTrade === true || runGovernance?.isRealTrade === true,
    evidenceUsage,
    strongConclusionAllowed,
  }
}

function buildAgentDagRunGovernance(run: AnalysisRun, observations: AgentObservation[], sourceCounts: AgentDagSourceCounts): AgentDagGovernance {
  const summary = run.dashboardSummary
  const metrics = summary?.metrics
  const evidenceScore = numberValue(metrics?.evidenceScore)
  const sourceReady = numberValue(metrics?.sourceReadyCount)
  const sourceTotal = numberValue(metrics?.sourceTotalCount)
  const blockedAgentCount = numberValue(metrics?.blockedAgentCount)
  const blockedNodes = observations.filter((item) => {
    const status = String(item.node.status || '').toUpperCase()
    return item.node.isBlocked || status === 'BLOCK_BUY' || status === 'FAIL' || status === 'ERROR'
  })
  const hasMissingData = observations.some((item) => (item.node.missingData ?? []).length > 0)
  const hasExecutableDagEvidence = sourceCounts.llm > 0 || sourceCounts.rule > 0
  const simulationOnly = summary?.tradeBoundary?.simulationOnly !== false
  const isRealTrade = summary?.tradeBoundary?.isRealTrade === true
  const evidenceBoundaryViolations = observations.filter((item) => (
    String(item.node.evidenceUsage || 'simulation_only') !== 'simulation_only'
    || item.node.strongConclusionAllowed === true
  ))
  const evidenceUsage = evidenceBoundaryViolations.length
    ? String(evidenceBoundaryViolations[0].node.evidenceUsage || 'UNKNOWN')
    : 'simulation_only'
  const strongConclusionAllowed = evidenceBoundaryViolations.some((item) => item.node.strongConclusionAllowed === true)

  let evidenceStrength: AgentDagEvidenceStrength = 'LOW'
  if (evidenceBoundaryViolations.length > 0 || sourceCounts.compatibility > 0 || sourceCounts.mock > 0 || sourceCounts.plugin > 0) {
    evidenceStrength = 'LOW'
  } else if (sourceCounts.degraded > 0 || blockedAgentCount > 0 || blockedNodes.length > 0 || hasMissingData) {
    evidenceStrength = 'LOW'
  } else if (hasExecutableDagEvidence && evidenceScore >= 80 && sourceTotal > 0 && sourceReady >= sourceTotal) {
    evidenceStrength = 'MEDIUM'
  } else if (hasExecutableDagEvidence && (evidenceScore >= 50 || sourceReady > 0)) {
    evidenceStrength = 'MEDIUM'
  }

  let blocker = summary?.blockers?.[0] || ''
  if (!blocker && evidenceBoundaryViolations.length > 0) {
    blocker = '存在 Agent 节点证据边界异常'
  } else if (!blocker && sourceCounts.compatibility > 0) {
    blocker = '存在 legacy compatibility-only 节点，不能作为活跃 DAG 证据'
  } else if (!blocker && sourceCounts.mock > 0) {
    blocker = '存在 mock/sample 输出，不能作为真实 Agent 证据'
  } else if (!blocker && sourceCounts.plugin > 0) {
    blocker = '存在只读插件观察，不能作为可执行 DAG 证据'
  } else if (!blocker && sourceCounts.degraded > 0) {
    blocker = '存在 LLM 降级或失败节点'
  } else if (!blocker && (blockedAgentCount > 0 || blockedNodes.length > 0)) {
    blocker = `存在 ${Math.max(blockedAgentCount, blockedNodes.length)} 个阻断 Agent`
  } else if (!blocker && hasMissingData) {
    blocker = '存在缺失数据字段'
  } else if (!blocker) {
    blocker = '无阻断，继续保持人工复核'
  }

  let nextAction = summary?.nextReview?.[0] || ''
  if (!nextAction && (sourceCounts.compatibility > 0 || sourceCounts.mock > 0 || sourceCounts.plugin > 0 || sourceCounts.degraded > 0 || blockedAgentCount > 0 || blockedNodes.length > 0 || hasMissingData)) {
    nextAction = '补齐 DAG 证据后再进入后续结论链路'
  } else if (!nextAction) {
    nextAction = '进入 guardrail_hub / quant_core 仅模拟复核'
  }

  return {
    contextId: run.runId,
    evidenceStrength,
    blocker,
    nextAction,
    simulationOnly,
    isRealTrade,
    evidenceUsage,
    strongConclusionAllowed,
  }
}

function AgentHealthBars({ observations }: { observations: AgentObservation[] }) {
  const maxTokens = Math.max(1, ...observations.map((item) => item.tokens))
  const maxLatency = Math.max(1, ...observations.map((item) => item.latency))

  if (observations.length === 0) {
    return <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 px-4 py-6 text-center text-sm text-slate-500">暂无 Agent 调用健康数据。</div>
  }

  return (
    <div className="space-y-3">
      {observations.map((item) => {
        const tokenPct = Math.max(2, Math.round((item.tokens / maxTokens) * 100))
        const latencyPct = Math.max(2, Math.round((item.latency / maxLatency) * 100))
        const compatibilityOnly = isCompatibilityOnly(item)
        return (
          <div key={item.node.id} className={`grid gap-3 rounded-lg border px-4 py-3 text-sm lg:grid-cols-[220px_1fr_130px] ${compatibilityOnly ? 'border-slate-300 bg-slate-50' : 'border-slate-200 bg-white'}`}>
            <div className="min-w-0">
              <div className="truncate font-semibold text-slate-950">{item.node.name}</div>
              <div className="mt-1 truncate text-xs text-slate-500">{item.profile} · {item.providerModel}</div>
            </div>
            <div className="grid gap-2">
              <div className="grid grid-cols-[72px_1fr] items-center gap-3">
                <span className="text-xs font-medium text-slate-500">Token</span>
                <div className="h-2 rounded-full bg-slate-100">
                  <div className="h-full rounded-full bg-cyan-500" style={{ width: `${tokenPct}%` }} />
                </div>
              </div>
              <div className="grid grid-cols-[72px_1fr] items-center gap-3">
                <span className="text-xs font-medium text-slate-500">Latency</span>
                <div className="h-2 rounded-full bg-slate-100">
                  <div className="h-full rounded-full bg-teal-500" style={{ width: `${latencyPct}%` }} />
                </div>
              </div>
            </div>
            <div className="flex flex-wrap items-center justify-start gap-2 lg:justify-end">
              <span className={`inline-flex rounded-md border px-2 py-0.5 text-[11px] font-medium ${getStatusColor(item.node.status)}`}>{item.node.status}</span>
              <span className={`inline-flex rounded-md border px-2 py-0.5 text-[11px] font-medium ${item.sourceClass}`}>{item.sourceLabel}</span>
              {compatibilityOnly ? (
                <span data-testid={`agent-dag-health-compatibility-${item.node.id}`} className="inline-flex rounded-md border border-slate-300 bg-white px-2 py-0.5 text-[11px] font-medium text-slate-600">
                  {compatibilityLabel(item)}
                </span>
              ) : null}
              <span className="w-full text-right text-xs text-slate-500 lg:w-auto">{formatNumber(item.tokens)} / {formatNumber(item.latency)}ms</span>
            </div>
          </div>
        )
      })}
    </div>
  )
}

export function AgentDagPage() {
  const { currentRun } = useAnalysisStore()
  const [searchParams] = useSearchParams()
  const [selectedNodeId, setSelectedNodeId] = useState('')
  const linkedRunId = (searchParams.get('run_id') || '').trim()
  const isLinkedRunPending = Boolean(linkedRunId && currentRun?.runId !== linkedRunId)

  const observations = useMemo(() => currentRun ? buildObservations(currentRun) : [], [currentRun])
  const selectedObservation = useMemo(
    () => observations.find((item) => item.node.id === selectedNodeId) ?? observations[0] ?? null,
    [observations, selectedNodeId],
  )
  const selectedFlowNodeId = selectedObservation?.node.id ?? ''
  const handleNodeClick = useCallback<NodeMouseHandler>((_event, node) => {
    setSelectedNodeId(node.id)
  }, [])

  const { nodes, edges } = useMemo(() => {
    if (!currentRun) {
      return { nodes: [] as Node[], edges: [] as Edge[] }
    }

    const flowNodes: Node[] = observations.map((item, index) => {
      const compatibilityOnly = isCompatibilityOnly(item)
      return {
        id: item.node.id,
        position: { x: 280 * (index % 3), y: 150 * Math.floor(index / 3) },
        data: {
          label: (
            <div
              className={`space-y-2 rounded-lg p-3 ${compatibilityOnly ? 'bg-slate-50' : 'bg-white'}`}
              data-testid={`agent-dag-flow-node-${item.node.id}`}
              data-source={item.source}
              role="button"
              tabIndex={0}
              aria-label={`Select agent ${item.node.id}`}
              aria-pressed={item.node.id === selectedFlowNodeId}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault()
                  setSelectedNodeId(item.node.id)
                }
              }}
            >
              <div className="font-semibold text-slate-950">{item.node.name}</div>
              <div className="flex flex-wrap gap-1.5">
                <span className={`inline-flex rounded-full border px-2 py-0.5 text-[11px] font-medium ${getStatusColor(item.node.status)}`}>
                  {item.node.status}
                </span>
                <span className={`inline-flex rounded-full border px-2 py-0.5 text-[11px] font-medium ${item.sourceClass}`}>
                  {item.sourceLabel}
                </span>
                {compatibilityOnly ? (
                  <span data-testid={`agent-dag-compatibility-${item.node.id}`} className="inline-flex rounded-full border border-slate-300 bg-white px-2 py-0.5 text-[11px] font-medium text-slate-600">
                    {compatibilityLabel(item)}
                  </span>
                ) : null}
              </div>
              <div className="text-[11px] leading-4 text-slate-500">
                <div>Profile: {item.profile}</div>
                <div>{formatNumber(item.tokens)} tokens · {formatNumber(item.latency)}ms</div>
              </div>
              {item.reason ? <div className="line-clamp-2 rounded-md border border-slate-100 bg-slate-50 px-2 py-1 text-[11px] leading-4 text-slate-500">{item.reason}</div> : null}
            </div>
          ),
        },
        style: {
          width: 260,
          borderRadius: 8,
          border: item.node.id === selectedFlowNodeId ? `2px solid ${item.sourceStroke}` : `1px solid ${item.sourceStroke}`,
          background: compatibilityOnly ? '#f8fafc' : '#ffffff',
          boxShadow: item.node.id === selectedFlowNodeId ? '0 12px 26px rgba(15, 23, 42, 0.12)' : '0 1px 2px rgba(15, 23, 42, 0.06)',
        },
      }
    })

    const nodeIds = new Set(flowNodes.map((node) => node.id))
    const observationByNode = new Map(observations.map((item) => [item.node.id, item]))
    const edges: Edge[] = nodesFor(currentRun)
      .flatMap((node) =>
        (node.allowedNextActions ?? []).map((next) => ({
          id: `${node.id}-${next}`,
          source: node.id,
          target: next,
          animated: node.isRunning,
          style: { stroke: observationByNode.get(next)?.sourceStroke ?? '#2563eb' },
        })),
      )
      .filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target))

    return { nodes: flowNodes, edges }
  }, [currentRun, observations, selectedFlowNodeId])

  const sourceCounts = useMemo(() => {
    const counts: AgentDagSourceCounts = {
      llm: 0,
      degraded: 0,
      rule: 0,
      plugin: 0,
      mock: 0,
      compatibility: 0,
    }
    observations.forEach((item) => {
      if (isCompatibilityOnly(item)) counts.compatibility += 1
      else if (item.source === 'LLM') counts.llm += 1
      else if (item.source === 'LLM_DEGRADED' || item.source === 'LLM_FAILED') counts.degraded += 1
      else if (item.source === 'MOCK') counts.mock += 1
      else if (item.source === 'PLUGIN_OBSERVATION') counts.plugin += 1
      else counts.rule += 1
    })
    return counts
  }, [observations])
  const runGovernance = useMemo(
    () => currentRun ? buildAgentDagRunGovernance(currentRun, observations, sourceCounts) : null,
    [currentRun, observations, sourceCounts],
  )
  const selectedNodeGovernance = useMemo(
    () => selectedObservation ? buildAgentDagNodeGovernance(selectedObservation, runGovernance) : null,
    [selectedObservation, runGovernance],
  )

  if (!currentRun || isLinkedRunPending) {
    return (
      <div data-testid="agent-dag-page-loading" className="text-sm text-slate-500">
        正在加载 Agent 流程图...
        {linkedRunId ? <span className="ml-2 font-mono">{linkedRunId}</span> : null}
      </div>
    )
  }

  return (
    <div className="space-y-6" data-testid="agent-dag-page">
      <SectionTitle
        title="Agent 结果与 DAG"
        subtitle="区分真实 LLM 输出、规则引擎输出、LLM 降级/失败输出，并保留每个 Agent 的配置档、Token、延迟和失败原因。"
      />

      {runGovernance ? (
        <div data-testid="agent-dag-run-governance" className="grid gap-2 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600 sm:grid-cols-2 xl:grid-cols-5">
          <span className="min-w-0 break-words">
            <span className="text-slate-500">ID：</span>
            <span data-testid="agent-dag-run-context-id" className="font-mono">{runGovernance.contextId}</span>
          </span>
          <span className="min-w-0 break-words">
            <span className="text-slate-500">证据强度：</span>
            <span data-testid="agent-dag-run-evidence-strength">{runGovernance.evidenceStrength}</span>
          </span>
          <span className="min-w-0 break-words">
            <span className="text-slate-500">阻断：</span>
            <span data-testid="agent-dag-run-blocker">{runGovernance.blocker}</span>
          </span>
          <span className="min-w-0 break-words">
            <span className="text-slate-500">下一步：</span>
            <span data-testid="agent-dag-run-next-action">{runGovernance.nextAction}</span>
          </span>
          <span className="min-w-0 break-words font-medium text-slate-900" data-testid="agent-dag-run-simulation-boundary">
            simulation_only={String(runGovernance.simulationOnly)} / is_real_trade={String(runGovernance.isRealTrade)} / evidence_usage={runGovernance.evidenceUsage} / strong_conclusion_allowed={String(runGovernance.strongConclusionAllowed)} / SIM_*
          </span>
        </div>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4" data-testid="agent-dag-source-summary">
        <MetricTile className="!rounded-lg !shadow-none" label="真实 LLM 输出" value={<span data-testid="agent-dag-llm-count">{sourceCounts.llm}</span>} tone="success" />
        <MetricTile className="!rounded-lg !shadow-none" label="LLM 降级/失败" value={<span data-testid="agent-dag-degraded-count">{sourceCounts.degraded}</span>} tone="warning" />
        <MetricTile
          className="!rounded-lg !shadow-none"
          label="规则引擎输出"
          value={<span data-testid="agent-dag-rule-count">{sourceCounts.rule}</span>}
          helper={<>只读插件观察 <span data-testid="agent-dag-plugin-count">{sourceCounts.plugin}</span> / 兼容别名 <span data-testid="agent-dag-compatibility-count">{sourceCounts.compatibility}</span></>}
        />
        <MetricTile className="!rounded-lg !shadow-none" label="计量状态" value={<span data-testid="agent-dag-metering-status">{currentRun.tokenUsage?.metering_status ?? 'NO_PROVIDER_USAGE'}</span>} tone="info" />
      </div>

      <Card title="Token / Call Health" className="!rounded-lg !shadow-none">
        <AgentHealthBars observations={observations} />
      </Card>

      <Card title="DAG 概览" className="!rounded-lg !shadow-none">
        <div className="h-[640px] rounded-lg border border-slate-200 bg-white" data-testid="agent-dag-flow-canvas">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            fitView
            nodesDraggable={false}
            nodesConnectable={false}
            panOnDrag
            onNodeClick={handleNodeClick}
            proOptions={{ hideAttribution: true }}
          >
            <MiniMap zoomable={false} nodeStrokeColor={() => '#0891b2'} nodeColor={() => '#f8fafc'} maskColor="rgba(241, 245, 249, 0.72)" />
            <Controls />
            <Background gap={20} color="#e2e8f0" />
          </ReactFlow>
        </div>
      </Card>

      {selectedObservation ? (
      <Card title="所选 Agent 证据" className="!rounded-lg !shadow-none">
          <div className="grid gap-4 md:grid-cols-3" data-testid="agent-dag-selected-node-detail">
            <div>
              <div className="text-xs font-medium text-slate-500">Agent</div>
              <div className="mt-1 font-semibold text-slate-950">{selectedObservation.node.name}</div>
              <div className="mt-1 text-xs text-slate-500" data-testid="agent-dag-selected-node-id">{selectedObservation.node.id}</div>
            </div>
            <div>
              <div className="text-xs font-medium text-slate-500">输出来源</div>
              <div className="mt-1">
                <span
                  data-testid="agent-dag-selected-node-source"
                  data-source={selectedObservation.source}
                  className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-medium ${selectedObservation.sourceClass}`}
                >
                  {selectedObservation.sourceLabel}
                </span>
              </div>
              <div className="mt-2 text-xs text-slate-500" data-testid="agent-dag-selected-node-status">LLM status: {selectedObservation.llmStatus}</div>
              {isCompatibilityOnly(selectedObservation) ? (
                <div data-testid="agent-dag-selected-node-compatibility" className="mt-2 rounded-md border border-slate-200 bg-slate-50 px-2 py-1 text-xs text-slate-600">
                  {compatibilityLabel(selectedObservation)}
                </div>
              ) : null}
            </div>
            <div>
              <div className="text-xs font-medium text-slate-500">运行证据</div>
              <div className="mt-1 text-sm text-slate-700">Profile: {selectedObservation.profile}</div>
              <div className="mt-1 text-xs text-slate-500">{selectedObservation.providerModel}</div>
              <div className="mt-1 text-xs text-slate-500">{formatNumber(selectedObservation.tokens)} tokens / {formatNumber(selectedObservation.latency)} ms</div>
            </div>
            <div className="md:col-span-3">
              <div className="text-xs font-medium text-slate-500">原因</div>
              <div className="mt-1 text-sm text-slate-600" data-testid="agent-dag-selected-node-reason">{selectedObservation.reason}</div>
            </div>
            {selectedNodeGovernance ? (
              <div data-testid="agent-dag-selected-node-governance" className="grid gap-2 rounded-md border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600 md:col-span-3 sm:grid-cols-2 xl:grid-cols-5">
                <span className="min-w-0 break-words">
                  ID: <span data-testid="agent-dag-selected-node-context-id" className="font-mono">{selectedNodeGovernance.contextId}</span>
                </span>
                <span data-testid="agent-dag-selected-node-evidence-strength" className="min-w-0 break-words">
                  Evidence: {selectedNodeGovernance.evidenceStrength}
                </span>
                <span data-testid="agent-dag-selected-node-blocker" className="min-w-0 break-words">
                  Blocker: {selectedNodeGovernance.blocker}
                </span>
                <span data-testid="agent-dag-selected-node-next-action" className="min-w-0 break-words">
                  Next: {selectedNodeGovernance.nextAction}
                </span>
                <span data-testid="agent-dag-selected-node-simulation-boundary" className="min-w-0 break-words font-medium text-slate-900">
                  simulation_only={String(selectedNodeGovernance.simulationOnly)} / is_real_trade={String(selectedNodeGovernance.isRealTrade)} / evidence_usage={selectedNodeGovernance.evidenceUsage} / strong_conclusion_allowed={String(selectedNodeGovernance.strongConclusionAllowed)} / SIM_*
                </span>
              </div>
            ) : null}
          </div>
        </Card>
      ) : null}

      <Card title="Agent 结果来源核验" className="!rounded-lg !shadow-none">
        <TableShell className="!rounded-lg !shadow-none">
        <div className="overflow-x-auto">
          <table className="institution-table">
            <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-3 py-2 font-semibold">Agent</th>
                <th className="px-3 py-2 font-semibold">输出来源</th>
                <th className="px-3 py-2 font-semibold">配置档 / 模型</th>
                <th className="px-3 py-2 font-semibold">Token / 延迟</th>
                <th className="px-3 py-2 font-semibold">完成原因</th>
                <th className="px-3 py-2 font-semibold">Error / 降级原因</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {observations.map((item) => {
                const compatibilityOnly = isCompatibilityOnly(item)
                return (
                  <tr key={item.node.id} data-testid={`agent-dag-result-row-${item.node.id}`} className={`align-top ${compatibilityOnly ? 'bg-slate-50' : ''}`}>
                    <td className="px-3 py-3">
                      <div className="font-medium text-slate-950">{item.node.name}</div>
                      <div className="mt-1 text-xs text-slate-500">{item.node.id}</div>
                      {compatibilityOnly ? (
                        <div data-testid={`agent-dag-row-compatibility-${item.node.id}`} className="mt-2 text-xs font-medium text-slate-600">
                          {compatibilityLabel(item)}
                        </div>
                      ) : null}
                    </td>
                    <td className="px-3 py-3">
                      <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-medium ${item.sourceClass}`}>
                        {item.sourceLabel}
                      </span>
                      <div className="mt-1 text-xs text-slate-500">LLM status: {item.llmStatus}</div>
                    </td>
                    <td className="px-3 py-3 text-slate-600">
                      <div>{item.profile}</div>
                      <div className="mt-1 text-xs text-slate-500">{item.providerModel}</div>
                    </td>
                    <td className="px-3 py-3 text-slate-600">
                      <div>{formatNumber(item.tokens)} tokens</div>
                      <div className="mt-1 text-xs text-slate-500">{formatNumber(item.latency)} ms</div>
                    </td>
                    <td className="px-3 py-3 text-slate-600">{item.finishReason}</td>
                    <td className="max-w-md px-3 py-3 text-slate-600">{item.reason}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        </TableShell>
      </Card>
    </div>
  )
}
