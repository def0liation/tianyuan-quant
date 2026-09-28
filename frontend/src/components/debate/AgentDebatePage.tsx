import { useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { BrainCircuit, Clock, Coins, Gavel, MessageSquare, XCircle } from 'lucide-react'
import { useAnalysisStore } from '../../store/useAnalysisStore'
import type {
  AgentDebateTurn,
  AgentNode,
  AgentOutputSource,
  AgentTokenUsageRow,
  AnalysisRun,
  LLMTraceItem,
  StandardAgentStatus,
  TokenUsageSource,
} from '../../types'
import { SectionTitle } from '../common/SectionTitle'
import { Card } from '../common/Card'
import { Badge } from '../common/Badge'
import { buildRunFailureNotice } from '../../utils/runFailure'
import { MetricTile, TableShell } from '../common/Material'

const stanceLabel: Record<AgentDebateTurn['stance'], string> = {
  support: '支持',
  challenge: '质询',
  block: '阻断',
  observe: '观察',
}

const stanceColor: Record<AgentDebateTurn['stance'], string> = {
  support: '#059669',
  challenge: '#d97706',
  block: '#e11d48',
  observe: '#64748b',
}

function formatNumber(value?: number) {
  return typeof value === 'number' ? value.toLocaleString() : '0'
}

type TokenTableRow = AgentTokenUsageRow & {
  source: AgentOutputSource
  sourceLabel: string
  sourceClass: string
  usageSource: TokenUsageSource
  usageLabel: string
  usageClass: string
  profile: string
  providerModel: string
  llmStatus: string
  finishReason: string
  degradationReason: string
  hasProviderUsage: boolean
  isMock: boolean
}

type DisplayDebateTurn = AgentDebateTurn & {
  sourceLabel: string
  sourceClass: string
  degradationReason: string
}

type AgentDebateEvidenceStrength = 'LOW' | 'MEDIUM'

interface AgentDebateGovernance {
  contextId: string
  evidenceStrength: AgentDebateEvidenceStrength
  blocker: string
  nextAction: string
  simulationOnly: boolean
  isRealTrade: boolean
  evidenceUsage: string
  strongConclusionAllowed: boolean
}

interface AgentDebateUsageStats {
  providerUsage: number
  providerEmpty: number
  noUsage: number
  mock: number
  llm: number
  degraded: number
  rule: number
  plugin: number
}

const sourceMetaMap: Record<string, { label: string; className: string }> = {
  LLM: { label: '真实 LLM 输出', className: 'border-emerald-200 bg-emerald-50 text-emerald-800' },
  LLM_DEGRADED: { label: 'LLM 降级输出', className: 'border-amber-200 bg-amber-50 text-amber-800' },
  LLM_FAILED: { label: 'LLM 失败输出', className: 'border-red-200 bg-red-50 text-red-800' },
  RULE_ENGINE: { label: '规则引擎输出', className: 'border-slate-200 bg-slate-50 text-slate-700' },
  PLUGIN_OBSERVATION: { label: '只读插件观察', className: 'border-sky-200 bg-sky-50 text-sky-800' },
  NODE_SUMMARY: { label: '节点摘要输出', className: 'border-blue-200 bg-blue-50 text-blue-800' },
  MOCK: { label: 'Mock / 示例输出', className: 'border-purple-200 bg-purple-50 text-purple-800' },
}

const usageMetaMap: Record<string, { label: string; className: string }> = {
  PROVIDER_USAGE: { label: 'Provider usage', className: 'border-emerald-200 bg-emerald-50 text-emerald-800' },
  PROVIDER_EMPTY: { label: 'usage 为空', className: 'border-amber-200 bg-amber-50 text-amber-800' },
  NO_PROVIDER_USAGE: { label: '未计量', className: 'border-slate-200 bg-slate-50 text-slate-700' },
  MOCK_ESTIMATE: { label: 'Mock 估算', className: 'border-purple-200 bg-purple-50 text-purple-800' },
}

function sourceMeta(source?: AgentOutputSource) {
  return sourceMetaMap[normalizeSource(source)] ?? sourceMetaMap.NODE_SUMMARY
}

function usageMeta(source?: TokenUsageSource) {
  return usageMetaMap[normalizeUsageSource(source)] ?? usageMetaMap.NO_PROVIDER_USAGE
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

function normalizeUsageSource(source: unknown): TokenUsageSource {
  const value = textValue(source).toUpperCase()
  if (value === 'PROVIDER_USAGE') return 'PROVIDER_USAGE'
  if (value === 'PROVIDER_EMPTY') return 'PROVIDER_EMPTY'
  if (value === 'NO_PROVIDER_USAGE') return 'NO_PROVIDER_USAGE'
  if (value === 'MOCK' || value === 'MOCK_ESTIMATE') return 'MOCK_ESTIMATE'
  return 'NO_PROVIDER_USAGE'
}

function runnerFor(node?: AgentNode) {
  return asRecord(asRecord(node?.rawJson).llmRunner)
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

function isMockOutput(_run: AnalysisRun, node?: AgentNode, row?: AgentTokenUsageRow) {
  return normalizeSource(row?.source) === 'MOCK'
    || textValue(row?.usage_source ?? row?.usageSource).toUpperCase() === 'MOCK_ESTIMATE'
    || textValue(node?.auditId).includes('MOCK')
    || textValue(node?.id).startsWith('mock_')
}

function isNonExecutablePluginObservation(node?: AgentNode) {
  const rawJson = asRecord(node?.rawJson)
  const dagRegistration = asRecord(rawJson.dagRegistration)
  const permissionSandbox = asRecord(rawJson.permissionSandbox)
  const pluginObservation = asRecord(rawJson.pluginObservation)
  const nodeId = textValue(node?.id)
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

function classifyOutput(run: AnalysisRun, node?: AgentNode, row?: AgentTokenUsageRow, trace?: LLMTraceItem): AgentOutputSource {
  if (isMockOutput(run, node, row)) return 'MOCK'
  if (isNonExecutablePluginObservation(node)) return 'PLUGIN_OBSERVATION'
  const runner = runnerFor(node)
  const status = textValue(row?.llm_status ?? row?.llmStatus ?? row?.status ?? trace?.status ?? runner.status).toUpperCase()
  const error = textValue(row?.error ?? trace?.error ?? runner.error)
  const downgradeText = (node?.downgradeReasons ?? []).join(' ')
  const outputText = `${node?.outputSummary ?? ''} ${downgradeText}`.toLowerCase()

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

function resolveUsageSource(
  run: AnalysisRun,
  node?: AgentNode,
  row?: AgentTokenUsageRow,
  trace?: LLMTraceItem,
  runner: Record<string, any> = {},
): TokenUsageSource {
  if (isMockOutput(run, node, row)) return 'MOCK_ESTIMATE'
  const explicit = textValue(row?.usage_source ?? row?.usageSource)
  if (explicit) return normalizeUsageSource(explicit)
  const rowTokens = numberValue(row?.prompt_tokens) + numberValue(row?.completion_tokens) + numberValue(row?.total_tokens)
  if (rowTokens > 0 || usageTokens(trace?.usage) > 0 || usageTokens(runner.usage) > 0) return 'PROVIDER_USAGE'
  const status = textValue(row?.llm_status ?? row?.llmStatus ?? row?.status ?? trace?.status ?? runner.status).toUpperCase()
  return status === 'COMPLETED' ? 'PROVIDER_EMPTY' : 'NO_PROVIDER_USAGE'
}

function degradationReason(
  source: AgentOutputSource,
  usageSource: TokenUsageSource,
  node?: AgentNode,
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
    || (node?.downgradeReasons ?? []).join('；')
  if (explicit) return explicit
  if (usageSource === 'PROVIDER_EMPTY') return 'LLM 调用完成，但 provider 没有返回 usage；token 按 0 展示，不从摘要估算。'
  if (usageSource === 'NO_PROVIDER_USAGE') return '本行没有 provider usage 记录；token 按 0 展示。'
  if (usageSource === 'MOCK_ESTIMATE') return 'Mock/sample token 仅为占位估算，不代表真实 LLM 计量。'
  if (source === 'RULE_ENGINE') return '本轮未记录真实 LLM 调用，当前显示规则引擎或模块产物。'
  return 'provider usage 已返回，可用于本次 token 计量。'
}

function buildTokenRow(run: AnalysisRun, node?: AgentNode, row?: AgentTokenUsageRow, trace?: LLMTraceItem): TokenTableRow {
  const runner = runnerFor(node)
  const source = classifyOutput(run, node, row, trace)
  const usageSource = resolveUsageSource(run, node, row, trace, runner)
  const sourceMetaValue = sourceMeta(source)
  const usageMetaValue = usageMeta(usageSource)
  const rawPromptTokens = numberValue(row?.prompt_tokens) || numberValue(trace?.promptTokens) || numberValue(asRecord(runner.usage).prompt_tokens)
  const rawCompletionTokens = numberValue(row?.completion_tokens) || numberValue(trace?.completionTokens) || numberValue(asRecord(runner.usage).completion_tokens)
  const rawTotalTokens = numberValue(row?.total_tokens) || numberValue(trace?.totalTokens) || usageTokens(runner.usage) || rawPromptTokens + rawCompletionTokens
  const promptTokens = usageSource === 'PROVIDER_USAGE' ? rawPromptTokens : 0
  const completionTokens = usageSource === 'PROVIDER_USAGE' ? rawCompletionTokens : 0
  const totalTokens = usageSource === 'PROVIDER_USAGE' ? rawTotalTokens : 0
  const profile = textValue(row?.profile_id ?? row?.profileId ?? trace?.profileId ?? runner.profileId) || '未记录'
  const provider = textValue(row?.provider ?? trace?.provider ?? runner.provider)
  const model = textValue(row?.model ?? trace?.model ?? runner.model)
  const providerModel = provider && model ? `${provider} / ${model}` : provider || model || '未记录'
  const llmStatus = textValue(row?.llm_status ?? row?.llmStatus ?? row?.status ?? trace?.status ?? runner.status) || (node?.isSkipped ? 'SKIPPED' : 'RULE_ENGINE')
  const latencyMs = numberValue(row?.latency_ms) || numberValue(trace?.latencyMs) || numberValue(runner.latencyMs) || numberValue(node?.duration)
  const finishReason = textValue(row?.finish_reason ?? row?.finishReason ?? trace?.finishReason ?? runner.finishReason) || '未返回'
  const isMock = usageSource === 'MOCK_ESTIMATE'
  return {
    node: row?.node ?? node?.id ?? 'unknown',
    name: row?.name ?? node?.name ?? row?.node ?? 'Unknown Agent',
    status: row?.status ?? llmStatus,
    provider,
    model,
    profile_id: profile,
    profileId: profile,
    prompt_tokens: promptTokens,
    completion_tokens: completionTokens,
    total_tokens: totalTokens,
    latency_ms: latencyMs,
    finish_reason: finishReason,
    finishReason,
    error: textValue(row?.error ?? trace?.error ?? runner.error),
    audit_id: row?.audit_id ?? node?.auditId ?? '',
    source,
    sourceLabel: sourceMetaValue.label,
    sourceClass: sourceMetaValue.className,
    usage_source: usageSource,
    usageSource,
    usageLabel: usageMetaValue.label,
    usageClass: usageMetaValue.className,
    profile,
    providerModel,
    llmStatus,
    degradationReason: degradationReason(source, usageSource, node, row, trace, runner),
    hasProviderUsage: usageSource === 'PROVIDER_USAGE' && !isMock,
    isMock,
  }
}

function buildTokenRows(run?: AnalysisRun): TokenTableRow[] {
  if (!run) return []
  const traces = traceMap(run)
  const tokenRows = tokenRowMap(run)
  const nodes = nodesFor(run)
  const nodeIds = new Set(nodes.map((node) => node.id))
  const rows = nodes.map((node) => buildTokenRow(run, node, tokenRows.get(node.id), traces.get(node.id)))
  const extraRows = Array.isArray(run.tokenUsage?.rows) ? run.tokenUsage.rows : []
  extraRows.forEach((row) => {
    if (!nodeIds.has(row.node)) {
      rows.push(buildTokenRow(run, undefined, row, traces.get(row.node)))
    }
  })
  return rows
}

function normalizeStatus(status: string): StandardAgentStatus {
  if (status === 'BLOCK_BUY') return 'BLOCK'
  if (status === 'FAIL' || status === 'RUNNING') return status === 'FAIL' ? 'ERROR' : 'WARN'
  if (['PASS', 'WARN', 'REVIEW_ONLY', 'BLOCK', 'ERROR', 'SKIPPED'].includes(status)) {
    return status as StandardAgentStatus
  }
  return 'WARN'
}

function stanceFromStatus(status: StandardAgentStatus): AgentDebateTurn['stance'] {
  if (status === 'PASS') return 'support'
  if (status === 'BLOCK' || status === 'ERROR') return 'block'
  if (status === 'WARN' || status === 'REVIEW_ONLY') return 'challenge'
  return 'observe'
}

function turnsFromNodes(nodes: AgentNode[]): AgentDebateTurn[] {
  return nodes.map((node, index) => {
    const status = normalizeStatus(node.status)
    const summary = node.outputSummary || node.inputSummary || ''
    const evidence = [
      node.outputSummary ? `节点输出：${node.outputSummary}` : '',
      node.inputSummary ? `节点输入：${node.inputSummary}` : '',
    ].filter(Boolean)

    if (node.isSkipped) {
      return {
        order: index + 1,
        node: node.id,
        name: node.name,
        stance: 'observe' as const,
        claim: summary
          ? `本轮该 Agent 没有执行，原因是：${summary}。它没有贡献本轮辩论结论。`
          : '本轮该 Agent 因上游门禁触发被跳过，未参与本次辩论。其职责范围内的检查未能执行，下游 Agent 需关注这一缺口可能带来的风险。',
        evidence: ['因上游阻断条件满足，本轮该 Agent 被编排器跳过'],
        counterpoints: ['该 Agent 被跳过意味着其职责范围内的检查未能执行'],
        decision_impact: '该 Agent 没有直接影响本轮决策。',
        status,
        confidence: 'UNKNOWN' as const,
        source: 'NODE_SUMMARY',
        token_total: 0,
        latency_ms: node.duration,
        audit_id: node.auditId,
      }
    }

    if (node.isBlocked) {
      return {
        order: index + 1,
        node: node.id,
        name: node.name,
        stance: 'block' as const,
        claim: summary || `${node.name} 触发阻断状态，对后续买入、加仓或执行计划形成限制。`,
        evidence: evidence.length ? evidence : [`${node.name} 在本轮分析中触发了阻断条件`],
        counterpoints: [...(node.downgradeReasons ?? []),
          ...(node.blockedPaths?.length ? [`以下路径已被阻断：${node.blockedPaths.join('、')}，相关操作不得在后续环节中执行。`] : []),
        ],
        decision_impact: '该 Agent 对后续正向交易路径形成约束或阻断，下游买入相关环节将受到硬性限制。',
        status,
        confidence: 'HIGH' as const,
        source: 'NODE_SUMMARY',
        token_total: 0,
        latency_ms: node.duration,
        audit_id: node.auditId,
      }
    }

    const claim = summary || `${node.name} 已完成运行，但没有返回可展示的主张文本。`
    const evidenceItems = node.missingData?.length
      ? [`缺失数据：${node.missingData.join('、')}，这些关键数据的缺失影响判断的完整性和可靠性，需要在决策中考虑这一不确定性。`]
      : (evidence.length ? evidence : [`${node.name} 本轮没有报告缺失数据。`])
    const counterpoints = [...(node.downgradeReasons ?? []),
      ...(node.blockedPaths?.length ? [`以下路径已被阻断：${node.blockedPaths.join('、')}`] : []),
    ]
    if (counterpoints.length === 0) {
      counterpoints.push('当前环节未产生额外反驳意见，分析结果与上游约束保持一致。')
    }
    const decisionImpact = '该 Agent 允许流程在上游约束内继续推进，下游环节可在当前的权限范围内进行后续操作。'

    return {
      order: index + 1,
      node: node.id,
      name: node.name,
      stance: stanceFromStatus(status),
      claim,
      evidence: evidenceItems,
      counterpoints,
      decision_impact: decisionImpact,
      status,
      confidence: status === 'PASS' ? 'HIGH' as const : status === 'SKIPPED' ? 'UNKNOWN' as const : 'MEDIUM' as const,
      source: 'NODE_SUMMARY',
      token_total: 0,
      latency_ms: node.duration,
      audit_id: node.auditId,
    }
  })
}

function UsageHealthStrip({ stats }: { stats: {
  providerUsage: number
  providerEmpty: number
  noUsage: number
  mock: number
} }) {
  const total = Math.max(1, stats.providerUsage + stats.providerEmpty + stats.noUsage + stats.mock)
  const segments = [
    { label: 'Provider usage', value: stats.providerUsage, className: 'bg-emerald-500' },
    { label: 'usage 为空', value: stats.providerEmpty, className: 'bg-amber-500' },
    { label: '未计量', value: stats.noUsage, className: 'bg-slate-400' },
    { label: 'Mock', value: stats.mock, className: 'bg-cyan-500' },
  ]

  return (
    <div className="mt-4 rounded-lg border border-slate-200 bg-white px-3 py-3">
      <div className="mb-2 text-xs font-semibold uppercase text-slate-500">Token / Call Health</div>
      <div className="flex h-2 overflow-hidden rounded-full bg-slate-100">
        {segments.map((segment) => (
          <div key={segment.label} className={segment.className} style={{ width: `${Math.max(0, (segment.value / total) * 100)}%` }} />
        ))}
      </div>
      <div className="mt-3 grid gap-2 text-xs text-slate-600 sm:grid-cols-4">
        {segments.map((segment) => (
          <div key={segment.label} className="flex items-center gap-2">
            <span className={`h-2 w-2 rounded-full ${segment.className}`} />
            <span>{segment.label} {segment.value}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function buildAgentDebateGovernance(
  run: AnalysisRun,
  debate: AnalysisRun['debateArtifacts'] | undefined,
  turns: DisplayDebateTurn[],
  stats: AgentDebateUsageStats,
): AgentDebateGovernance {
  const paperTrading = run.paperTrading
  const paperTradingEvidence = paperTrading as typeof paperTrading & {
    evidenceUsage?: string
    evidence_usage?: string
    strongConclusionAllowed?: boolean
    strong_conclusion_allowed?: boolean
  }
  const namespace = paperTrading.allowed_order_namespace ?? paperTrading.orderNamespace ?? paperTrading.order_namespace ?? ''
  const latestAction = paperTrading.latest_action ?? paperTrading.action ?? paperTrading.paper_action ?? ''
  const simulationOnly = paperTrading.simulation_only === true
  const isRealTrade = paperTrading.is_real_trade === true
  const evidenceUsage = paperTradingEvidence.evidenceUsage ?? paperTradingEvidence.evidence_usage ?? 'simulation_only'
  const strongConclusionAllowed =
    paperTradingEvidence.strongConclusionAllowed === true || paperTradingEvidence.strong_conclusion_allowed === true
  const evidenceBoundaryBroken = evidenceUsage !== 'simulation_only' || strongConclusionAllowed
  const boundaryBroken =
    !simulationOnly
    || isRealTrade
    || namespace !== 'SIM_*'
    || (latestAction ? !latestAction.startsWith('SIM_') : false)
    || evidenceBoundaryBroken
  const hasCanonicalDebate = Boolean(debate?.audit_id && Array.isArray(debate?.turns) && debate.turns.length > 0)
  const hasTurns = turns.length > 0
  const hasProviderUsage = stats.providerUsage > 0
  const hasMock = stats.mock > 0 || turns.some((turn) => turn.source === 'MOCK')
  const hasOnlyFallbackSources = !hasCanonicalDebate || (stats.llm === 0 && stats.degraded === 0 && stats.rule > 0)
  const blocker = boundaryBroken
    ? 'SIMULATION_BOUNDARY_VIOLATED'
    : !hasTurns
      ? 'MISSING_DEBATE_TURNS'
      : !hasCanonicalDebate
        ? 'NODE_SUMMARY_FALLBACK_ONLY'
        : hasMock
          ? 'MOCK_OUTPUT_PRESENT'
          : !hasProviderUsage
            ? 'NO_PROVIDER_USAGE'
            : 'NONE'
  const evidenceStrength: AgentDebateEvidenceStrength = hasCanonicalDebate && hasProviderUsage && !hasOnlyFallbackSources && !boundaryBroken && hasTurns && !hasMock
    ? 'MEDIUM'
    : 'LOW'
  const nextAction = blocker === 'NONE'
    ? '可进入 Final Writer / Research Lab 仅模拟复核'
    : blocker === 'NODE_SUMMARY_FALLBACK_ONLY'
      ? '等待标准 debateArtifacts 写入后再使用辩论证据'
      : blocker === 'NO_PROVIDER_USAGE'
        ? '补齐 provider usage 或保留为支持性观察'
        : '先修复辩论产物、来源或模拟边界'

  return {
    contextId: debate?.audit_id || debate?.run_id || run.runId,
    evidenceStrength,
    blocker,
    nextAction,
    simulationOnly,
    isRealTrade,
    evidenceUsage,
    strongConclusionAllowed,
  }
}

export function AgentDebatePage() {
  const { currentRun } = useAnalysisStore()
  const [searchParams] = useSearchParams()
  const linkedRunId = (searchParams.get('run_id') || '').trim()
  const isLinkedRunPending = Boolean(linkedRunId && currentRun?.runId !== linkedRunId)

  const debate = currentRun?.debateArtifacts
  const runNodes = currentRun ? nodesFor(currentRun) : []
  const debateTurns = Array.isArray(debate?.turns) ? debate.turns : []
  const turns = debateTurns.length ? debateTurns : turnsFromNodes(runNodes)
  const tokenUsage = currentRun?.tokenUsage
  const tokenRows = useMemo(() => buildTokenRows(currentRun), [currentRun])
  const tokenRowsByNode = useMemo(() => new Map(tokenRows.map((row) => [row.node, row])), [tokenRows])
  const displayTurns = useMemo<DisplayDebateTurn[]>(() => turns.map((turn) => {
    const row = tokenRowsByNode.get(turn.node)
    const source = row?.source ?? turn.source ?? 'NODE_SUMMARY'
    const meta = sourceMeta(source)
    return {
      ...turn,
      source,
      sourceLabel: meta.label,
      sourceClass: meta.className,
      token_total: row?.total_tokens ?? 0,
      latency_ms: row?.latency_ms ?? turn.latency_ms,
      degradationReason: row?.degradationReason ?? '',
    }
  }), [tokenRowsByNode, turns])

  const totals = useMemo(() => {
    const prompt = tokenRows.reduce((sum, row) => sum + row.prompt_tokens, 0)
    const completion = tokenRows.reduce((sum, row) => sum + row.completion_tokens, 0)
    const total = tokenRows.reduce((sum, row) => sum + row.total_tokens, 0)
    const latency = tokenRows.reduce((sum, row) => sum + row.latency_ms, 0)
    return { prompt, completion, total, latency }
  }, [tokenRows])

  const stanceData = useMemo(() => {
    const counts = { support: 0, challenge: 0, block: 0, observe: 0 }
    displayTurns.forEach((turn) => {
      counts[turn.stance] += 1
    })
    return Object.entries(counts).map(([stance, count]) => ({
      stance,
      label: stanceLabel[stance as AgentDebateTurn['stance']],
      count,
    }))
  }, [displayTurns])

  const usageStats = useMemo(() => {
    return tokenRows.reduce(
      (acc, row) => {
        if (row.hasProviderUsage) acc.providerUsage += 1
        if (row.usageSource === 'PROVIDER_EMPTY') acc.providerEmpty += 1
        if (row.usageSource === 'NO_PROVIDER_USAGE') acc.noUsage += 1
        if (row.isMock) acc.mock += 1
        if (row.source === 'LLM') acc.llm += 1
        if (row.source === 'LLM_DEGRADED' || row.source === 'LLM_FAILED') acc.degraded += 1
        if (row.source === 'RULE_ENGINE') acc.rule += 1
        if (row.source === 'PLUGIN_OBSERVATION') acc.plugin += 1
        return acc
      },
      { providerUsage: 0, providerEmpty: 0, noUsage: 0, mock: 0, llm: 0, degraded: 0, rule: 0, plugin: 0 },
    )
  }, [tokenRows])

  const usageNotice = usageStats.providerUsage > 0
    ? `${usageStats.providerUsage} 个 Agent 返回了 provider usage；空 usage 行保持 0，不做估算。`
    : usageStats.mock > 0
      ? '当前包含 Mock/sample token，占位估算不会作为真实 LLM 计量。'
      : '本次没有 provider usage；token 全部按 0 展示，不从辩论文本或节点摘要估算。'

  if (!currentRun || isLinkedRunPending) {
    return (
      <div data-testid="agent-debate-page-loading" className="text-sm text-slate-500">
        正在加载 Agent 辩论与 Token 计量...
        {linkedRunId ? <span className="ml-2 font-mono">{linkedRunId}</span> : null}
      </div>
    )
  }

  const failureNotice =
    ['FAILED', 'STALE'].includes(currentRun.status) ? buildRunFailureNotice(currentRun, '辩论数据需复核') : undefined
  const debateGovernance = buildAgentDebateGovernance(currentRun, debate, displayTurns, usageStats)

  return (
    <div className="space-y-6" data-testid="agent-debate-page">
      <SectionTitle
        title="Agent 辩论与 Token 计量"
        subtitle="观察每个 Agent 的输出来源、LLM 配置档、Token、延迟、完成原因与降级/失败原因；空用量不做估算。"
      />

      {failureNotice && (
        <div className="rounded-lg border border-rose-200 bg-rose-50 p-4">
          <div className="flex items-start gap-3">
            <XCircle className="mt-0.5 h-5 w-5 flex-shrink-0 text-rose-600" />
            <div className="flex-1 min-w-0">
              <h3 className="text-sm font-semibold text-rose-900">{failureNotice.title}</h3>
              <p className="mt-1 text-xs leading-5 text-rose-700">
                {failureNotice.description}
              </p>
            </div>
          </div>
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <div data-testid="agent-debate-source-summary">
          <MetricTile
            className="!h-full !rounded-lg !shadow-none"
            label="最终动作"
            value={debate?.final_action ?? currentRun.finalWriter?.finalAction ?? currentRun.finalAction}
            icon={Gavel}
            tone="info"
          />
        </div>
        <MetricTile
          className="!rounded-lg !shadow-none"
          label="总 Token"
          value={formatNumber(totals.total)}
          helper={`输入 ${formatNumber(totals.prompt)} / 输出 ${formatNumber(totals.completion)}`}
          icon={Coins}
          tone="success"
        />
        <MetricTile
          className="!rounded-lg !shadow-none"
          label="输出来源"
          value={`LLM ${usageStats.llm} / 降级 ${usageStats.degraded} / 规则 ${usageStats.rule}`}
          helper={`空 usage ${usageStats.providerEmpty + usageStats.noUsage} · 插件观察 ${usageStats.plugin} · Mock ${usageStats.mock}`}
          icon={BrainCircuit}
          tone="primary"
        />
        <MetricTile className="!rounded-lg !shadow-none" label="累计延迟" value={`${formatNumber(totals.latency)} ms`} icon={Clock} tone="warning" />
      </div>
      <div data-testid="agent-debate-governance" className="grid gap-2 rounded-md border border-cyan-200 bg-white/80 p-3 text-xs text-slate-700 sm:grid-cols-2 xl:grid-cols-5">
        <span data-testid="agent-debate-governance-id" className="min-w-0 break-words font-mono">
          Debate: {debateGovernance.contextId}
        </span>
        <span data-testid="agent-debate-evidence-strength" className="min-w-0 break-words">
          Evidence: {debateGovernance.evidenceStrength}
        </span>
        <span data-testid="agent-debate-blocker" className="min-w-0 break-words">
          Blocker: {debateGovernance.blocker}
        </span>
        <span data-testid="agent-debate-next-action" className="min-w-0 break-words">
          Next: {debateGovernance.nextAction}
        </span>
        <span data-testid="agent-debate-simulation-boundary" className="min-w-0 break-words font-medium text-slate-900">
          simulation_only={String(debateGovernance.simulationOnly)} / is_real_trade={String(debateGovernance.isRealTrade)} / evidence_usage={debateGovernance.evidenceUsage} / strong_conclusion_allowed={String(debateGovernance.strongConclusionAllowed)} / SIM_*
        </span>
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.15fr_0.85fr]">
        <Card title="Token 使用量排行" className="!rounded-lg !shadow-none">
          <div className="h-96">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={tokenRows} layout="vertical" margin={{ left: 20, right: 20 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis type="number" />
                <YAxis dataKey="name" type="category" width={140} tick={{ fontSize: 12 }} />
                <Tooltip />
                <Legend />
                <Bar dataKey="prompt_tokens" stackId="tokens" name="输入 Token" fill="#0891b2" />
                <Bar dataKey="completion_tokens" stackId="tokens" name="输出 Token" fill="#14b8a6" />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-3 rounded-md bg-slate-50 p-3 text-xs leading-5 text-slate-500">
            <div>{usageNotice}</div>
            {tokenUsage?.note ? <div className="mt-1">{tokenUsage.note}</div> : null}
          </div>
          <UsageHealthStrip stats={usageStats} />
        </Card>

        <Card title="辩论立场分布" className="!rounded-lg !shadow-none">
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={stanceData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="label" />
                <YAxis allowDecimals={false} />
                <Tooltip />
                <Bar dataKey="count" name="Agent 数量" radius={[4, 4, 0, 0]}>
                  {stanceData.map((entry) => (
                    <Cell key={entry.stance} fill={stanceColor[entry.stance as AgentDebateTurn['stance']]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="grid gap-2 text-sm text-slate-600">
            <div>主导约束：{debate?.summary?.dominant_constraint || '暂无'}</div>
            <div>支持 / 质询 / 阻断：{debate?.summary?.support_count ?? 0} / {debate?.summary?.challenge_count ?? 0} / {debate?.summary?.block_count ?? 0}</div>
            <div data-testid="agent-debate-metering-status">计量状态：{tokenUsage?.metering_status ?? (usageStats.providerUsage > 0 ? 'LIVE_USAGE' : 'NO_PROVIDER_USAGE')}</div>
          </div>
        </Card>
      </div>

      <Card title="每个 Agent 的 Token / LLM 状态" className="!rounded-lg !shadow-none">
        <TableShell className="!rounded-lg !shadow-none">
        <div className="overflow-x-auto">
          <table className="institution-table">
            <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-3 py-2 font-semibold">Agent</th>
                <th className="px-3 py-2 font-semibold">来源 / Usage</th>
                <th className="px-3 py-2 font-semibold">配置档</th>
                <th className="px-3 py-2 font-semibold">Token</th>
                <th className="px-3 py-2 font-semibold">延迟</th>
                <th className="px-3 py-2 font-semibold">完成原因</th>
                <th className="px-3 py-2 font-semibold">错误 / 降级原因</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {tokenRows.map((row) => (
                <tr key={row.node} data-testid={`agent-debate-token-row-${row.node}`} className="align-top">
                  <td className="px-3 py-3">
                    <div className="font-medium text-slate-950">{row.name}</div>
                    <div className="mt-1 text-xs text-slate-500">{row.node}</div>
                  </td>
                  <td className="px-3 py-3">
                    <div className="flex flex-wrap gap-1.5">
                      <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-medium ${row.sourceClass}`}>
                        {row.sourceLabel}
                      </span>
                      <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-medium ${row.usageClass}`}>
                        {row.usageLabel}
                      </span>
                    </div>
                    <div className="mt-1 text-xs text-slate-500">LLM status: {row.llmStatus}</div>
                  </td>
                  <td className="px-3 py-3 text-slate-600">
                    <div>{row.profile}</div>
                    <div className="mt-1 text-xs text-slate-500">{row.providerModel}</div>
                  </td>
                  <td className="px-3 py-3 text-slate-600">
                    <div>{formatNumber(row.total_tokens)} total</div>
                    <div className="mt-1 text-xs text-slate-500">
                      {formatNumber(row.prompt_tokens)} in / {formatNumber(row.completion_tokens)} out
                    </div>
                  </td>
                  <td className="px-3 py-3 text-slate-600">{formatNumber(row.latency_ms)} ms</td>
                  <td className="px-3 py-3 text-slate-600">{row.finishReason}</td>
                  <td className="max-w-md px-3 py-3 text-slate-600">{row.degradationReason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        </TableShell>
      </Card>

      <Card title="Agent 辩论过程" className="!rounded-lg !shadow-none">
        <div className="space-y-4">
          <div className="rounded-md border border-slate-200 bg-white p-3 text-xs leading-5 text-slate-600">
            这里仅展示本轮运行实际产生的 Agent 输出。LLM 成功、LLM 降级/失败、规则引擎、只读插件观察和 mock/sample 会分别标注；token 不从主张文本反推。
          </div>
          {displayTurns.length === 0 ? (
            <div className="rounded-md bg-slate-50 p-4 text-sm text-slate-500">
              当前运行还没有标准化辩论摘要。创建或刷新一次分析任务后会自动生成。
            </div>
          ) : (
            displayTurns.map((turn) => (
              <div key={`${turn.order}-${turn.node}`} className="rounded-md border border-slate-200 bg-slate-50 p-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="flex min-w-0 items-center gap-3">
                    <div
                      className="grid h-9 w-9 shrink-0 place-items-center rounded-md text-sm font-bold text-white"
                      style={{ backgroundColor: stanceColor[turn.stance] }}
                    >
                      {turn.order}
                    </div>
                    <div className="min-w-0">
                      <div className="truncate font-semibold text-slate-950">{turn.name}</div>
                      <div className="text-xs text-slate-500">{stanceLabel[turn.stance]} · {turn.sourceLabel}</div>
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge status={turn.status}>{turn.status}</Badge>
                    <Badge status={turn.confidence}>{turn.confidence}</Badge>
                    <span className={`inline-flex rounded-full border px-3 py-1 text-xs font-medium ${turn.sourceClass}`}>
                      {turn.sourceLabel}
                    </span>
                    {turn.source === 'MOCK' && <Badge status="WARN">示例数据</Badge>}
                    <span className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium text-slate-600">
                      {formatNumber(turn.token_total)} tokens
                    </span>
                  </div>
                </div>

                {turn.degradationReason ? (
                  <div className="mt-3 rounded-md border border-slate-200 bg-white px-3 py-2 text-xs leading-5 text-slate-600">
                    降级/计量说明：{turn.degradationReason}
                  </div>
                ) : null}

                <div className="mt-4 grid gap-4 lg:grid-cols-3">
                  <div>
                    <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-slate-900">
                      <BrainCircuit size={16} />
                      主张
                    </div>
                    <p className="text-sm leading-6 text-slate-600">{turn.claim}</p>
                  </div>
                  <div>
                    <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-slate-900">
                      <Gavel size={16} />
                      依据
                    </div>
                    <ul className="space-y-2 text-sm leading-5 text-slate-600">
                      {(turn.evidence.length ? turn.evidence : ['暂无明确依据']).map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                  </div>
                  <div>
                    <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-slate-900">
                      <MessageSquare size={16} />
                      反驳与影响
                    </div>
                    <ul className="space-y-2 text-sm leading-5 text-slate-600">
                      {(turn.counterpoints.length ? turn.counterpoints : ['无额外反驳']).map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                      <li className="font-medium text-slate-800">{turn.decision_impact}</li>
                    </ul>
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      </Card>
    </div>
  )
}
