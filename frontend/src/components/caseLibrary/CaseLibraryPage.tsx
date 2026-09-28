import { useCallback, useEffect, useState } from 'react'
import {
  BookOpenCheck,
  CheckCircle2,
  GitBranch,
  RefreshCw,
  Save,
  Tag,
  Trash2,
  XCircle,
  AlertTriangle,
  Wrench,
  ChevronDown,
  ChevronUp,
  Zap,
} from 'lucide-react'
import { useSearchParams } from 'react-router-dom'
import { Badge } from '../common/Badge'
import { ResearchEmptyState, ResearchError, ResearchLoading, ResearchMetricCard, ResearchPageHeader, ResearchSegmentedTabs } from '../research/ResearchLabShared'
import {
  getCaseLibrarySummary,
  getCases,
  createCase,
  updateCaseReview,
  getReviewTags,
  createReviewTag,
  getErrorEntries,
  getKnowledgePatches,
  reviewKnowledgePatch,
  approvePatchWithEvaluation,
  runPatchEvaluation,
  deleteCase,
  deleteErrorEntry,
  deleteKnowledgePatch,
} from '../../api/caseLibraryClient'
import { listKnowledgeCases, listPaperOrders, listSignals } from '../../api/signalopsClient'
import {
  AgentSimulationCaseItem,
  CaseLibraryItem,
  CaseLibrarySummary,
  ErrorLedgerItem,
  KnowledgePatchItem,
  PaperOrderItem,
  SignalItem,
} from '../../types'
import { useAnalysisStore } from '../../store/useAnalysisStore'
import { useToastStore } from '../../store/useToastStore'
import { roleAllows, useOperatorContext } from '../../store/operatorContext'
import { formatDateTime } from '../../utils/format'

const optimismBiasOptions = ['NONE', 'SLIGHT', 'MODERATE', 'SEVERE']
const dataSufficiencyOptions = ['ADEQUATE', 'PARTIAL', 'INSUFFICIENT']
type CaseLibraryTab = 'cases' | 'simulation' | 'errors' | 'patches'
type PromotionFeedback = {
  type: 'info' | 'success' | 'error'
  message: string
}
type SimulationCaseGovernance = {
  contextId: string
  evidenceStrength: 'LOW'
  blocker: string
  nextAction: string
  simulationOnly: boolean
  isRealTrade: boolean
  evidenceUsage: 'review_gate_only'
  strongConclusionAllowed: false
}
type ErrorLedgerGovernance = {
  contextId: string
  evidenceStrength: 'LOW' | 'MEDIUM'
  blocker: string
  nextAction: string
  simulationOnly: boolean
  isRealTrade: boolean
}

const caseLibraryTabs: Array<{ value: CaseLibraryTab; label: string }> = [
  { value: 'cases', label: '人工案例' },
  { value: 'simulation', label: 'Agent 模拟操作案例' },
  { value: 'errors', label: '错误账本' },
  { value: 'patches', label: '知识补丁' },
]
const executableSimulationActions = new Set(['SIM_BUY', 'SIM_SELL', 'SIM_CLOSE', 'SIM_REBALANCE', 'SIM_T_BUY', 'SIM_T_SELL', 'SIM_SHORT', 'SIM_COVER'])

function statusBadge(status: string) {
  if (status === 'REVIEWED') return 'PASS'
  if (status === 'PENDING') return 'WARN'
  return 'SKIPPED'
}

function promotionFeedbackClass(type: PromotionFeedback['type']) {
  if (type === 'success') return 'border-emerald-200 bg-emerald-50 text-emerald-800'
  if (type === 'error') return 'border-red-200 bg-red-50 text-red-800'
  return 'border-cyan-200 bg-cyan-50 text-cyan-800'
}

function numberText(value: unknown, fractionDigits = 2) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed.toLocaleString(undefined, { maximumFractionDigits: fractionDigits }) : '-'
}

function reviewGateEvidenceStrength(value?: string | null, fallback = 'LOW') {
  const normalized = String(value || '').trim().toUpperCase()
  if (['HIGH', 'STRONG', 'PRIMARY', 'PRIMARY_EVIDENCE', 'PASS', 'READY'].includes(normalized)) return 'MEDIUM'
  if (['RESEARCH_GRADE', 'PRIMARY_EVIDENCE_READY'].includes(normalized)) return 'MEDIUM'
  if (['UNKNOWN', 'SUPPORTING_ONLY', 'WEAK', 'WARN', 'WARNING', 'REVIEW', 'REVIEW_ONLY'].includes(normalized)) return 'LOW'
  if (['MEDIUM', 'LOW', 'MISSING', 'PENDING'].includes(normalized)) return normalized
  if (['FAIL', 'FAILED', 'BLOCKED'].includes(normalized)) return 'MISSING'
  return fallback
}

function caseEvidenceStrengthLabel(item: CaseLibraryItem) {
  const apiStrength = reviewGateEvidenceStrength(item.evidence_strength)
  if (apiStrength === 'MEDIUM') return 'MEDIUM：已复盘，仍仅作辅助'
  if (apiStrength === 'LOW') return 'LOW：复盘证据不足'
  if (apiStrength === 'PENDING') return 'PENDING：待人工复盘'
  if (apiStrength === 'MISSING') return 'MISSING：缺少案例证据'
  const reviewed = item.review_status === 'REVIEWED'
  const hasJudgement = item.conclusion_correct !== null && item.final_action_correct !== null
  const hasReviewEvidence = item.key_lessons.length > 0 && item.review_note.trim().length > 0
  if (reviewed && item.data_sufficiency === 'ADEQUATE' && hasJudgement && hasReviewEvidence) {
    return 'MEDIUM：已复盘，仍仅作辅助'
  }
  if (reviewed && hasJudgement) return 'LOW：已复盘待补证'
  if (reviewed || hasReviewEvidence) return 'LOW：部分复盘'
  return 'LOW：待人工复盘'
}

function caseBlockingReason(item: CaseLibraryItem) {
  if (item.review_status !== 'REVIEWED') return `复盘状态：${item.review_status}`
  if (item.data_sufficiency !== 'ADEQUATE') return `数据充分性：${item.data_sufficiency}`
  if (item.conclusion_correct === null || item.final_action_correct === null) return '缺少结论或动作正确性判断'
  if (item.key_lessons.length === 0) return '缺少关键教训'
  if (!item.review_note.trim()) return '缺少复盘备注'
  if (item.optimism_bias === 'SEVERE') return '乐观偏差严重，禁止升级强证据'
  return '无阻断，保持人工复核'
}

function caseNextActionLabel(item: CaseLibraryItem) {
  const blocker = caseBlockingReason(item)
  if (item.review_status !== 'REVIEWED') return '补充人工复盘后再进入知识补丁'
  if (blocker !== '无阻断，保持人工复核') return '补齐 case 证据后再进入 Knowledge / Evaluation'
  return '可进入知识补丁 / Knowledge / Evaluation 仅复核'
}

function patchHasEvaluationEvidence(patch: KnowledgePatchItem) {
  return Object.keys(patch.backtest_result ?? {}).length > 0
}

function patchEvidenceStrengthLabel(patch: KnowledgePatchItem) {
  const strength = reviewGateEvidenceStrength(patch.evidence_strength)
  if (strength === 'MEDIUM') return 'MEDIUM：评估/回测通过，仍需人工复核'
  if (strength === 'LOW') return 'LOW：补丁证据不足'
  if (strength === 'MISSING') return 'MISSING：缺少补丁证据'
  if (strength === 'PENDING') return 'PENDING：等待评估/回测'
  if (patchHasEvaluationEvidence(patch)) return '评估证据已记录'
  if (patch.backtest_required) return '弱证据：缺少评估/回测'
  return '人工复核证据'
}

function patchBlockingReason(patch: KnowledgePatchItem) {
  if (patch.approval_status !== 'CANDIDATE') return `状态：${patch.approval_status}`
  if (patch.backtest_required && !patchHasEvaluationEvidence(patch)) return '缺少评估/回测证据'
  if (!patch.risk_note.trim()) return '缺少风险边界说明'
  return '等待 researcher 复核'
}

function patchNextActionLabel(patch: KnowledgePatchItem) {
  if (patch.approval_status === 'CANDIDATE' && patch.backtest_required && !patchHasEvaluationEvidence(patch)) {
    return '先运行评估+批准'
  }
  if (patch.approval_status === 'CANDIDATE') return '复核后批准或拒绝'
  if (patch.approval_status === 'APPROVED') return '监控知识版本与回滚影响'
  if (patch.approval_status === 'REJECTED') return '保留审计记录'
  return '归档或删除前复核'
}

function simulationCaseWarnings(item: AgentSimulationCaseItem) {
  const riskConstraints = (item.outcome?.risk_constraints ?? {}) as Record<string, any>
  return Array.isArray(riskConstraints.paper_gate_warnings)
    ? riskConstraints.paper_gate_warnings.map(String).filter(Boolean)
    : item.failure_tags
}

function buildSimulationCaseGovernance(item: AgentSimulationCaseItem): SimulationCaseGovernance {
  const outcome = item.outcome ?? {}
  const action = String(outcome.paper_action || outcome.action || '')
  const hasExecutableAction = executableSimulationActions.has(action)
  const hasTradeMetrics = outcome.trade_metrics_available === true
  const warnings = simulationCaseWarnings(item)
  const status = String(item.knowledge_candidate_status || '').toUpperCase()
  const simulationOnly = item.simulation_only === true
  const isRealTrade = item.is_real_trade === true
  const hasIds = Boolean(item.source_signal_id && item.source_paper_order_id)
  const boundaryBroken = !simulationOnly || isRealTrade

  let blocker = '无阻断，保持人工复核'
  if (boundaryBroken) {
    blocker = 'Agent simulation case simulation-only boundary violated'
  } else if (!hasIds) {
    blocker = '缺少 SignalOps signal/order ID'
  } else if (warnings.length > 0) {
    blocker = `Paper gate warning: ${warnings[0]}`
  } else if (hasExecutableAction && !hasTradeMetrics) {
    blocker = '缺少模拟成交指标'
  } else if (!['REVIEWED', 'READY', 'ACCEPTED'].includes(status)) {
    blocker = `知识候选状态：${item.knowledge_candidate_status || 'REVIEWING'}`
  }

  const nextAction = boundaryBroken
    ? '停止沉淀，先修复 simulation-only 边界'
    : !hasIds
      ? '补齐 SignalOps signal/order 链接后再进入案例复盘'
      : warnings.length > 0 || (hasExecutableAction && !hasTradeMetrics)
        ? '先复核 paper gate / 模拟成交指标'
        : blocker === '无阻断，保持人工复核'
          ? '可进入 Case / Knowledge / Evaluation 仅模拟复核'
          : '交给人工复盘后再进入 Knowledge / Evaluation'

  return {
    contextId: item.case_id || item.source_paper_order_id || item.source_signal_id || 'pending-simulation-case',
    evidenceStrength: 'LOW',
    blocker,
    nextAction,
    simulationOnly,
    isRealTrade,
    evidenceUsage: 'review_gate_only',
    strongConclusionAllowed: false,
  }
}

function errorLedgerBoundary(entry: ErrorLedgerItem) {
  const attribution = entry.attribution ?? {}
  const simulationOnly = typeof entry.simulation_only === 'boolean'
    ? entry.simulation_only
    : attribution.simulation_only === false ? false : true
  const isRealTrade = typeof entry.is_real_trade === 'boolean'
    ? entry.is_real_trade
    : attribution.is_real_trade === true
  return { simulationOnly, isRealTrade }
}

function buildErrorLedgerGovernance(entry: ErrorLedgerItem): ErrorLedgerGovernance {
  const { simulationOnly, isRealTrade } = errorLedgerBoundary(entry)
  const status = String(entry.status || '').toUpperCase()
  const hasIds = Boolean(entry.entry_id && entry.run_id && entry.audit_id)
  const boundaryBroken = !simulationOnly || isRealTrade
  const apiStrength = reviewGateEvidenceStrength(entry.evidence_strength)
  const evidenceStrength = apiStrength === 'MEDIUM' ? 'MEDIUM' : 'LOW'

  let blocker = '无阻断，保持人工复核'
  if (boundaryBroken) {
    blocker = 'Error ledger simulation-only boundary violated'
  } else if (status === 'OPEN') {
    blocker = `错误仍打开：${entry.error_type}`
  } else if (entry.patch_required && !entry.patch_candidate_id) {
    blocker = '需要补丁但缺少 patch candidate'
  } else if (!hasIds) {
    blocker = '缺少 run/audit/error ID'
  } else if (entry.repeated_count > 1) {
    blocker = `重复错误 ${entry.repeated_count} 次`
  }

  const nextAction = boundaryBroken
    ? '停止沉淀，先修复 simulation-only 边界'
    : status === 'OPEN'
      ? '先归因并创建/关联补丁'
      : entry.patch_required && !entry.patch_candidate_id
        ? '补齐 patch candidate 后再进入 Knowledge / Evaluation'
        : blocker === '无阻断，保持人工复核'
          ? '保留审计记录，必要时进入 Knowledge / Evaluation 复核'
          : '复核错误账本后再进入补丁或知识沉淀'

  return {
    contextId: entry.entry_id || entry.audit_id || entry.run_id || 'pending-error-ledger',
    evidenceStrength,
    blocker,
    nextAction,
    simulationOnly,
    isRealTrade,
  }
}

function formatOutcomeSummary(item: AgentSimulationCaseItem) {
  const outcome = item.outcome ?? {}
  const symbol = String(outcome.symbol || item.source_signal_id || '-')
  const action = String(outcome.paper_action || outcome.action || 'SIM_ACTION')
  const status = String(outcome.fill_status || item.knowledge_candidate_status || 'REVIEWING')
  return `${symbol} · ${action} · ${status}`
}

function normalizePaperOrderMetrics(order: PaperOrderItem) {
  const hasTradeMetrics = executableSimulationActions.has(order.action)
  if (!hasTradeMetrics) {
    return {
      tradeMetricsAvailable: false,
      fillStatus: 'OBSERVED',
      simulatedPrice: null,
      simulatedQuantity: null,
      simulatedValue: null,
      metricNote: 'SIM_HOLD 是观察动作，无模拟成交价、数量或金额',
    }
  }
  const fill = order.simulated_fill ?? {}
  const simulatedPrice = Number(fill.filled_price ?? order.simulated_price)
  const simulatedQuantity = Number(fill.filled_quantity ?? order.simulated_quantity)
  const validPrice = Number.isFinite(simulatedPrice) && simulatedPrice > 0
  const validQuantity = Number.isFinite(simulatedQuantity) && simulatedQuantity > 0
  return {
    tradeMetricsAvailable: validPrice && validQuantity,
    fillStatus: order.fill_status,
    simulatedPrice: validPrice ? simulatedPrice : null,
    simulatedQuantity: validQuantity ? simulatedQuantity : null,
    simulatedValue: validPrice && validQuantity ? simulatedPrice * simulatedQuantity : null,
    metricNote: validPrice && validQuantity ? '模拟成交数据来自 paper_order/simulated_fill' : '模拟委托缺少有效成交价或数量',
  }
}

function sanitizeSimulationCase(item: AgentSimulationCaseItem): AgentSimulationCaseItem {
  const outcome = item.outcome ?? {}
  const action = String(outcome.paper_action || outcome.action || '')
  const hasTradeMetrics = executableSimulationActions.has(action)
  if (!hasTradeMetrics) {
    return {
      ...item,
      outcome: {
        ...outcome,
        fill_status: action === 'SIM_HOLD' ? 'OBSERVED' : outcome.fill_status,
        trade_metrics_available: false,
        metric_note: 'SIM_HOLD 是观察动作，无模拟成交价、数量或金额',
        simulated_price: null,
        simulated_quantity: null,
        simulated_value: null,
      },
    }
  }
  const price = Number(outcome.simulated_fill?.filled_price ?? outcome.simulated_price)
  const quantity = Number(outcome.simulated_fill?.filled_quantity ?? outcome.simulated_quantity)
  const validPrice = Number.isFinite(price) && price > 0
  const validQuantity = Number.isFinite(quantity) && quantity > 0
  return {
    ...item,
    outcome: {
      ...outcome,
      trade_metrics_available: validPrice && validQuantity,
      metric_note: validPrice && validQuantity ? '模拟成交数据来自 paper_order/simulated_fill' : '模拟委托缺少有效成交价或数量',
      simulated_price: validPrice ? price : null,
      simulated_quantity: validQuantity ? quantity : null,
      simulated_value: validPrice && validQuantity ? price * quantity : null,
    },
  }
}

function mergeSimulationCases(
  persisted: AgentSimulationCaseItem[],
  signals: SignalItem[],
  ordersBySignal: Map<string, PaperOrderItem[]>,
) {
  const byOrderId = new Map<string, AgentSimulationCaseItem>()
  for (const item of persisted) {
    byOrderId.set(item.source_paper_order_id, sanitizeSimulationCase(item))
  }
  for (const signal of signals) {
    const orders = ordersBySignal.get(signal.signal_id) ?? []
    for (const order of orders) {
      if (byOrderId.has(order.order_id)) continue
      const metrics = normalizePaperOrderMetrics(order)
      byOrderId.set(order.order_id, {
        case_id: `SIMCASE_DERIVED_${order.order_id}`,
        case_source: 'AGENT_SIMULATION',
        operator_type: 'AGENT',
        source_signal_id: signal.signal_id,
        source_paper_order_id: order.order_id,
        run_id: order.run_id,
        agent_id: order.agent_id,
        audit_id: order.audit_id,
        simulation_only: true,
        is_real_trade: false,
        outcome: {
          source: 'paper_order',
          review_required: true,
          symbol: signal.symbol,
          stock_name: signal.stock_name,
          signal_status: signal.status,
          paper_action: order.action,
          action_reason: order.action_reason,
          fill_status: metrics.fillStatus,
          trade_metrics_available: metrics.tradeMetricsAvailable,
          metric_note: metrics.metricNote,
          simulated_price: metrics.simulatedPrice,
          simulated_quantity: metrics.simulatedQuantity,
          simulated_value: metrics.simulatedValue,
          risk_constraints: order.risk_constraints,
          invalidation_conditions: order.invalidation_conditions,
          data_snapshot_hash: order.data_snapshot_hash,
          simulated_fill: order.simulated_fill,
          knowledge_use: '非真实交易，仅用于知识迭代',
        },
        failure_tags: order.risk_constraints?.paper_gate_warnings?.length ? ['PAPER_GATE_WARNING'] : [],
        knowledge_candidate_status: 'REVIEWING',
        created_at: order.created_at,
        updated_at: order.updated_at,
      })
    }
  }
  return Array.from(byOrderId.values()).sort((left, right) => (
    String(right.created_at || '').localeCompare(String(left.created_at || ''))
  ))
}

export function CaseLibraryPage() {
  const { currentRunId, currentRun } = useAnalysisStore()
  const [searchParams] = useSearchParams()
  const addToast = useToastStore((state) => state.addToast)
  const operator = useOperatorContext()

  const [summary, setSummary] = useState<CaseLibrarySummary | null>(null)
  const [cases, setCases] = useState<CaseLibraryItem[]>([])
  const [simulationCases, setSimulationCases] = useState<AgentSimulationCaseItem[]>([])
  const [, setTags] = useState<any[]>([])
  const [errors, setErrors] = useState<ErrorLedgerItem[]>([])
  const [patches, setPatches] = useState<KnowledgePatchItem[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<CaseLibraryTab>('cases')
  const [expandedCase, setExpandedCase] = useState<string | null>(null)
  const [reviewForm, setReviewForm] = useState<Record<string, any>>({})
  const [promotionFeedback, setPromotionFeedback] = useState<Record<string, PromotionFeedback>>({})

  const linkedRunId = (searchParams.get('run_id') || '').trim()
  const isLinkedRunPending = Boolean(linkedRunId && currentRun?.runId !== linkedRunId)
  const runId = isLinkedRunPending ? '' : linkedRunId || currentRunId || currentRun?.runId
  const runContextId = isLinkedRunPending ? linkedRunId : runId
  const canWriteCaseLibraryItems = roleAllows(operator.role, 'researcher')
  const canDeleteCaseLibraryItems = roleAllows(operator.role, 'admin')
  const runHydrationDisabledReason = isLinkedRunPending ? `正在加载 URL 指定的运行：${linkedRunId}` : undefined
  const caseLibraryWriteDisabledReason = canWriteCaseLibraryItems
    ? undefined
    : `案例库写入需要 researcher 权限。当前角色：${operator.role}。`
  const deleteDisabledReason = canDeleteCaseLibraryItems
    ? undefined
    : `案例库删除需要 admin 权限。当前角色：${operator.role}。`

  const loadData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [s, c, t, e, p, persistedSimulationCases, signals] = await Promise.all([
        getCaseLibrarySummary(),
        getCases({ limit: 50 }),
        getReviewTags({ limit: 100 }),
        getErrorEntries({ limit: 50 }),
        getKnowledgePatches({ limit: 50 }),
        listKnowledgeCases('AGENT_SIMULATION'),
        listSignals({ limit: 50 }),
      ])
      const ordersBySignal = new Map<string, PaperOrderItem[]>()
      await Promise.all(
        signals.map(async (signal) => {
          try {
            ordersBySignal.set(signal.signal_id, await listPaperOrders(signal.signal_id))
          } catch {
            ordersBySignal.set(signal.signal_id, [])
          }
        }),
      )
      setSummary(s)
      setCases(c)
      setSimulationCases(mergeSimulationCases(persistedSimulationCases, signals, ordersBySignal))
      setTags(t)
      setErrors(e)
      setPatches(p)
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadData()
  }, [loadData])

  async function handleCreateCase() {
    if (!canWriteCaseLibraryItems) {
      addToast(caseLibraryWriteDisabledReason || '案例库写入需要 researcher 权限。', 'error')
      return
    }
    if (isLinkedRunPending) {
      addToast(runHydrationDisabledReason || '正在加载 URL 指定的运行。', 'error')
      return
    }
    if (!runId) {
      addToast('请先选择一个运行', 'error')
      return
    }
    setSaving(true)
    try {
      await createCase(runId)
      addToast('案例已创建', 'success')
      await loadData()
    } catch (err) {
      addToast(err instanceof Error ? err.message : '创建失败', 'error')
    } finally {
      setSaving(false)
    }
  }

  async function handleSaveReview(caseId: string) {
    if (!canWriteCaseLibraryItems) {
      addToast(caseLibraryWriteDisabledReason || '案例库写入需要 researcher 权限。', 'error')
      return
    }
    const form = reviewForm[caseId]
    if (!form) return
    setSaving(true)
    try {
      await updateCaseReview(caseId, form)
      addToast('复盘已保存', 'success')
      setReviewForm((prev) => ({ ...prev, [caseId]: undefined }))
      await loadData()
    } catch (err) {
      addToast(err instanceof Error ? err.message : '保存失败', 'error')
    } finally {
      setSaving(false)
    }
  }

  async function handleAddTag(caseId: string, _runId: string) {
    if (!canWriteCaseLibraryItems) {
      addToast(caseLibraryWriteDisabledReason || '案例库写入需要 researcher 权限。', 'error')
      return
    }
    const type = prompt('标签类型:', 'CONCLUSION_CORRECT')
    if (!type) return
    const value = prompt('标签值:', '')
    if (!value) return
    setSaving(true)
    try {
      await createReviewTag(caseId, {
        tag_type: type,
        tag_value: value,
        severity: 'MEDIUM',
      })
      addToast('标签已添加', 'success')
      const updatedTags = await getReviewTags({ case_id: caseId })
      setTags((prev) => [
        ...prev.filter((t) => t.case_id !== caseId),
        ...updatedTags,
      ])
    } catch (err) {
      addToast(err instanceof Error ? err.message : '添加失败', 'error')
    } finally {
      setSaving(false)
    }
  }

  async function handleReviewPatch(patchId: string, action: 'APPROVE' | 'REJECT' | 'ARCHIVE') {
    if (!canWriteCaseLibraryItems) {
      addToast(caseLibraryWriteDisabledReason || '案例库写入需要 researcher 权限。', 'error')
      return
    }
    setSaving(true)
    setPromotionFeedback((prev) => {
      const next = { ...prev }
      delete next[patchId]
      return next
    })
    try {
      await reviewKnowledgePatch(patchId, { action, reviewer: 'human' })
      addToast(action === 'APPROVE' ? '补丁已批准' : '补丁已更新', 'success')
      await loadData()
    } catch (err) {
      addToast(err instanceof Error ? err.message : '操作失败', 'error')
    } finally {
      setSaving(false)
    }
  }

  async function handleApproveWithEval(patch: KnowledgePatchItem) {
    if (!canWriteCaseLibraryItems) {
      addToast(caseLibraryWriteDisabledReason || '案例库写入需要 researcher 权限。', 'error')
      return
    }
    setSaving(true)
    setPromotionFeedback((prev) => ({
      ...prev,
      [patch.patch_id]: {
        type: 'info',
        message: 'Running forced evaluation before promotion...',
      },
    }))
    try {
      const evalResult = await runPatchEvaluation(patch.patch_id, true)
      await approvePatchWithEvaluation(patch.patch_id, 'human', {
        evaluation_id: evalResult.eval_id,
        source_case_id: patch.source_case_id,
        risk_boundary: patch.risk_note || 'Promotion is limited to the patch affected modules.',
        approval_record: {
          reviewer: 'human',
          decision: 'PROMOTE_AFTER_EVALUATION',
        },
        rollback_impact: {
          rollback_plan: patch.rollback_plan,
          affected_modules: patch.affected_modules,
        },
      })
      addToast('评估+批准完成，已生成新知识版本', 'success')
      setPromotionFeedback((prev) => ({
        ...prev,
        [patch.patch_id]: {
          type: 'success',
          message: `Evaluation promotion completed. Knowledge version was generated from ${evalResult.eval_id}.`,
        },
      }))
      await loadData()
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Evaluation promotion failed.'
      setPromotionFeedback((prev) => ({
        ...prev,
        [patch.patch_id]: {
          type: 'error',
          message: `评估晋级被阻断：${message}`,
        },
      }))
      addToast(message, 'error')
    } finally {
      setSaving(false)
    }
  }

  async function handleDeleteCase(caseId: string, symbol: string) {
    if (!canDeleteCaseLibraryItems) {
      addToast(`删除需要 admin 权限。当前角色：${operator.role}。`, 'error')
      return
    }
    if (!window.confirm(`确定删除案例 ${symbol}？`)) return
    setSaving(true)
    try {
      await deleteCase(caseId)
      addToast('案例已删除', 'success')
      await loadData()
    } catch (err) {
      addToast(err instanceof Error ? err.message : '删除失败', 'error')
    } finally {
      setSaving(false)
    }
  }

  async function handleDeleteError(entryId: string) {
    if (!canDeleteCaseLibraryItems) {
      addToast(`删除需要 admin 权限。当前角色：${operator.role}。`, 'error')
      return
    }
    if (!window.confirm('确定删除此错误记录？')) return
    setSaving(true)
    try {
      await deleteErrorEntry(entryId)
      addToast('错误记录已删除', 'success')
      await loadData()
    } catch (err) {
      addToast(err instanceof Error ? err.message : '删除失败', 'error')
    } finally {
      setSaving(false)
    }
  }

  async function handleDeletePatch(patchId: string) {
    if (!canDeleteCaseLibraryItems) {
      addToast(`删除需要 admin 权限。当前角色：${operator.role}。`, 'error')
      return
    }
    if (!window.confirm('确定删除此知识补丁？')) return
    setSaving(true)
    try {
      await deleteKnowledgePatch(patchId)
      addToast('补丁已删除', 'success')
      await loadData()
    } catch (err) {
      addToast(err instanceof Error ? err.message : '删除失败', 'error')
    } finally {
      setSaving(false)
    }
  }

  function updateForm(caseId: string, key: string, value: any) {
    setReviewForm((prev) => ({
      ...prev,
      [caseId]: { ...prev[caseId], [key]: value },
    }))
  }

  if (loading) return <ResearchLoading label="正在加载案例库..." />

  return (
    <div className="space-y-6">
      <ResearchPageHeader
        eyebrow="案例库"
        title="案例库"
        subtitle="集中管理人工案例、Agent 模拟操作案例、错误账本和知识补丁，让复盘、标签、补丁批准和删除操作都在同一条审计链路里完成。"
        icon={BookOpenCheck}
        tags={['Review cases', 'Error ledger', 'Knowledge patch']}
        actions={
          <button
            type="button"
            data-testid="case-library-create-case"
            onClick={handleCreateCase}
            disabled={!runId || saving || !canWriteCaseLibraryItems || isLinkedRunPending}
            title={runHydrationDisabledReason || caseLibraryWriteDisabledReason || undefined}
            className="inline-flex items-center gap-2 rounded-md bg-cyan-400 px-4 py-2 text-sm font-semibold text-slate-950 transition hover:bg-cyan-300 disabled:cursor-not-allowed disabled:opacity-60"
          >
            <GitBranch size={16} />
            从当前运行创建案例
          </button>
        }
      />

      <div className="rounded-md border border-slate-200 bg-white px-4 py-3 text-xs text-slate-500">
        <span data-testid="case-library-write-role">
          角色：{operator.role}；写入：{canWriteCaseLibraryItems ? 'researcher+' : '已阻断'}；删除：{canDeleteCaseLibraryItems ? 'admin' : '已阻断'}
        </span>
        <span data-testid="case-library-current-run-id" className="ml-3 break-all font-mono text-slate-600">
          运行：{runContextId || '尚未选择'}
        </span>
        {isLinkedRunPending ? (
          <span data-testid="case-library-current-run-loading" className="ml-3 text-amber-700">{runHydrationDisabledReason}</span>
        ) : null}
        {!canWriteCaseLibraryItems ? (
          <span data-testid="case-library-write-disabled-reason" className="ml-3 text-amber-700">{caseLibraryWriteDisabledReason}</span>
        ) : null}
      </div>

      {!canDeleteCaseLibraryItems ? (
        <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          案例库删除操作仅限 admin。当前角色：{operator.role}。
        </div>
      ) : null}

      {error ? <ResearchError message={error} /> : null}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
        <ResearchMetricCard label="案例总数" value={summary?.total ?? 0} helper="Cases / 人工复盘样本" icon={BookOpenCheck} tone="bg-cyan-50 text-cyan-700" />
        <ResearchMetricCard label="模拟仓案例" value={simulationCases.length} helper="SignalOps / 虚拟仓样本" icon={Zap} tone="bg-sky-50 text-sky-700" />
        <ResearchMetricCard label="待复盘" value={summary?.pending ?? 0} helper="Pending / 待人工判断" icon={RefreshCw} tone="bg-amber-50 text-amber-700" />
        <ResearchMetricCard label="准确率" value={`${(summary?.accuracy_rate ?? 0) * 100}%`} helper="Accuracy / 已复盘表现" icon={CheckCircle2} tone="bg-emerald-50 text-emerald-700" />
        <ResearchMetricCard label="错误记录" value={errors.length} helper="Errors / 需修正模式" icon={AlertTriangle} tone="bg-rose-50 text-rose-700" />
        <ResearchMetricCard label="候选补丁" value={patches.filter((p) => p.approval_status === 'CANDIDATE').length} helper="Patches / 等待批准" icon={Wrench} tone="bg-slate-100 text-slate-700" />
      </div>

      <div className="flex flex-col gap-3 rounded-md border border-slate-200 bg-white p-4 shadow-sm shadow-slate-200/60 xl:flex-row xl:items-center">
        <ResearchSegmentedTabs
          active={activeTab}
          onChange={(value) => setActiveTab(value as CaseLibraryTab)}
          tabs={caseLibraryTabs.map((tab) => ({
            ...tab,
            icon: tab.value === 'cases' ? BookOpenCheck : tab.value === 'simulation' ? Zap : tab.value === 'errors' ? AlertTriangle : Wrench,
            count: tab.value === 'cases' ? cases.length : tab.value === 'simulation' ? simulationCases.length : tab.value === 'errors' ? errors.length : patches.length,
          }))}
        />
        <button
          type="button"
          onClick={loadData}
          disabled={saving}
          className="inline-flex items-center justify-center gap-2 rounded-md border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:opacity-60 xl:ml-auto"
        >
          <RefreshCw size={16} />
          刷新
        </button>
      </div>

      {activeTab === 'cases' && (
        <div className="space-y-4">
          {cases.length === 0 ? (
            <ResearchEmptyState title="暂无人工案例" description="从当前运行创建案例后，可以在这里补充复盘结论、标签、市场背景和关键教训。" icon={BookOpenCheck} />
          ) : (
            cases.map((item) => (
              <div key={item.case_id} className="rounded-lg border border-slate-200 bg-white p-4">
                <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                  <div className="flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge status={statusBadge(item.review_status)}>{item.review_status}</Badge>
                      <span className="rounded bg-slate-100 px-2 py-1 text-xs text-slate-600">{item.symbol}</span>
                      <span className="text-xs text-slate-500">{item.task_type}</span>
                      <span className="text-xs text-slate-400">{item.run_mode}</span>
                    </div>
                    <div className="mt-2 text-sm font-medium text-slate-900">
                      最终动作: {item.final_action}
                    </div>
                    <div className="mt-1 text-xs text-slate-400">
                      Run: {item.run_id} · {formatDateTime(item.created_at)}
                    </div>
                    <div data-testid={`case-library-case-governance-${item.case_id}`} className="mt-3 grid gap-2 rounded-md border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600 sm:grid-cols-2 xl:grid-cols-5">
                      <span data-testid={`case-library-case-id-${item.case_id}`} className="min-w-0 break-all">
                        Case: {item.case_id}
                      </span>
                      <span data-testid={`case-library-case-evidence-strength-${item.case_id}`} className="min-w-0 break-words">
                        Evidence: {caseEvidenceStrengthLabel(item)}
                      </span>
                      <span data-testid={`case-library-case-blocker-${item.case_id}`} className="min-w-0 break-words">
                        Blocker: {caseBlockingReason(item)}
                      </span>
                      <span data-testid={`case-library-case-next-action-${item.case_id}`} className="min-w-0 break-words">
                        Next: {caseNextActionLabel(item)}
                      </span>
                      <span data-testid={`case-library-case-simulation-boundary-${item.case_id}`} className="min-w-0 break-words font-medium text-slate-900">
                        simulation_only={String(item.simulation_only)} / is_real_trade={String(item.is_real_trade)} / evidence_usage={item.evidence_usage} / strong_conclusion_allowed={String(item.strong_conclusion_allowed)} / SIM_*
                      </span>
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => setExpandedCase(expandedCase === item.case_id ? null : item.case_id)}
                      className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-3 py-2 text-xs font-medium text-slate-700 transition hover:bg-slate-50"
                    >
                      {expandedCase === item.case_id ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                      复盘
                    </button>
                    <button
                      type="button"
                      data-testid={`case-library-add-tag-${item.case_id}`}
                      onClick={() => handleAddTag(item.case_id, item.run_id)}
                      disabled={saving || !canWriteCaseLibraryItems}
                      title={caseLibraryWriteDisabledReason || undefined}
                      className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-3 py-2 text-xs font-medium text-slate-700 transition hover:bg-slate-50 disabled:opacity-60"
                    >
                      <Tag size={14} />
                      标签
                    </button>
                    <button
                      type="button"
                      onClick={() => handleDeleteCase(item.case_id, item.symbol)}
                      disabled={saving || !canDeleteCaseLibraryItems}
                      title={deleteDisabledReason ?? '删除此案例'}
                      className="inline-flex items-center gap-1 rounded-lg border border-red-200 px-3 py-2 text-xs font-medium text-red-600 transition hover:bg-red-50 disabled:opacity-60"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>

                {item.tags.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {item.tags.map((tag) => (
                      <span key={tag} className="rounded bg-slate-100 px-2 py-1 text-xs text-slate-500">{tag}</span>
                    ))}
                  </div>
                )}

                {expandedCase === item.case_id && (
                  <div className="mt-4 space-y-3 border-t border-slate-100 pt-4">
                    <div className="grid gap-3 sm:grid-cols-2">
                      <label className="space-y-1 text-sm">
                        <span className="font-medium text-slate-700">结论是否正确</span>
                        <select
                          value={reviewForm[item.case_id]?.conclusion_correct ?? (item.conclusion_correct === true ? 'true' : item.conclusion_correct === false ? 'false' : '')}
                          onChange={(e) => updateForm(item.case_id, 'conclusion_correct', e.target.value === 'true' ? true : e.target.value === 'false' ? false : null)}
                          className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-slate-900"
                        >
                          <option value="">未评估</option>
                          <option value="true">正确</option>
                          <option value="false">错误</option>
                        </select>
                      </label>
                      <label className="space-y-1 text-sm">
                        <span className="font-medium text-slate-700">数据充分性</span>
                        <select
                          value={reviewForm[item.case_id]?.data_sufficiency ?? item.data_sufficiency}
                          onChange={(e) => updateForm(item.case_id, 'data_sufficiency', e.target.value)}
                          className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-slate-900"
                        >
                          {dataSufficiencyOptions.map((o) => (
                            <option key={o} value={o}>{o}</option>
                          ))}
                        </select>
                      </label>
                      <label className="space-y-1 text-sm">
                        <span className="font-medium text-slate-700">乐观偏差</span>
                        <select
                          value={reviewForm[item.case_id]?.optimism_bias ?? item.optimism_bias}
                          onChange={(e) => updateForm(item.case_id, 'optimism_bias', e.target.value)}
                          className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-slate-900"
                        >
                          {optimismBiasOptions.map((o) => (
                            <option key={o} value={o}>{o}</option>
                          ))}
                        </select>
                      </label>
                      <label className="space-y-1 text-sm">
                        <span className="font-medium text-slate-700">复盘状态</span>
                        <select
                          value={reviewForm[item.case_id]?.review_status ?? item.review_status}
                          onChange={(e) => updateForm(item.case_id, 'review_status', e.target.value)}
                          className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-slate-900"
                        >
                          <option value="PENDING">PENDING</option>
                          <option value="REVIEWED">REVIEWED</option>
                        </select>
                      </label>
                    </div>
                    <label className="space-y-1 text-sm">
                      <span className="font-medium text-slate-700">关键教训 (逗号分隔)</span>
                      <input
                        value={reviewForm[item.case_id]?.key_lessons?.join(',') ?? item.key_lessons.join(',')}
                        onChange={(e) => updateForm(item.case_id, 'key_lessons', e.target.value.split(',').map((s) => s.trim()).filter(Boolean))}
                        className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-slate-900"
                      />
                    </label>
                    <label className="space-y-1 text-sm">
                      <span className="font-medium text-slate-700">市场背景</span>
                      <textarea
                        rows={2}
                        value={reviewForm[item.case_id]?.market_context ?? item.market_context}
                        onChange={(e) => updateForm(item.case_id, 'market_context', e.target.value)}
                        className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-slate-900"
                      />
                    </label>
                    <label className="space-y-1 text-sm">
                      <span className="font-medium text-slate-700">复盘备注</span>
                      <textarea
                        rows={2}
                        value={reviewForm[item.case_id]?.review_note ?? item.review_note}
                        onChange={(e) => updateForm(item.case_id, 'review_note', e.target.value)}
                        className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-slate-900"
                      />
                    </label>
                    <button
                      type="button"
                      data-testid={`case-library-save-review-${item.case_id}`}
                      onClick={() => handleSaveReview(item.case_id)}
                      disabled={saving || !canWriteCaseLibraryItems}
                      title={caseLibraryWriteDisabledReason || undefined}
                      className="inline-flex items-center gap-2 rounded-lg bg-emerald-700 px-4 py-2 text-sm font-semibold text-white transition hover:bg-emerald-800 disabled:opacity-60"
                    >
                      <Save size={16} />
                      保存复盘
                    </button>
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      )}

      {activeTab === 'simulation' && (
        <div className="space-y-4">
          <div className="rounded-md border border-cyan-200 bg-cyan-50 px-4 py-3 text-sm text-cyan-900">
            这些案例来自 SignalOps 虚拟仓和模拟委托，均标记为非真实交易，仅用于知识迭代、复盘和候选补丁验证。
          </div>
          {simulationCases.length === 0 ? (
            <ResearchEmptyState title="暂无模拟仓案例" description="SignalOps 自动模拟仓产生委托后，会在这里汇总为非真实交易案例。" icon={Zap} />
          ) : (
            simulationCases.map((item) => {
              const outcome = item.outcome ?? {}
              const warnings = simulationCaseWarnings(item)
              const hasTradeMetrics = outcome.trade_metrics_available === true
              const governance = buildSimulationCaseGovernance(item)
              return (
                <div key={item.case_id} className="rounded-lg border border-slate-200 bg-white p-4">
                  <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge status="WARN">{item.knowledge_candidate_status}</Badge>
                        <span className="rounded bg-cyan-100 px-2 py-1 text-xs font-medium text-cyan-800">Agent 模拟操作案例</span>
                        <span className="rounded bg-rose-50 px-2 py-1 text-xs font-medium text-rose-700">非真实交易</span>
                        <span className="rounded bg-slate-100 px-2 py-1 text-xs text-slate-600">{String(outcome.symbol || '-')}</span>
                      </div>
                      <div className="mt-2 text-sm font-semibold text-slate-950">{formatOutcomeSummary(item)}</div>
                      <div className="mt-1 text-sm text-slate-600">
                        {String(outcome.action_reason || '虚拟仓委托已纳入知识迭代复盘，等待人工审核和沙箱验证。')}
                      </div>
                      <div className="mt-3 grid gap-3 text-xs text-slate-600 sm:grid-cols-2 xl:grid-cols-4">
                        <div>
                          <span className="text-slate-400">模拟成交价</span>
                          <div className="font-medium text-slate-900">{hasTradeMetrics ? numberText(outcome.simulated_price) : '观察动作'}</div>
                        </div>
                        <div>
                          <span className="text-slate-400">模拟数量</span>
                          <div className="font-medium text-slate-900">{hasTradeMetrics ? numberText(outcome.simulated_quantity) : '无成交'}</div>
                        </div>
                        <div>
                          <span className="text-slate-400">模拟金额</span>
                          <div className="font-medium text-slate-900">{hasTradeMetrics ? numberText(outcome.simulated_value) : '不计算'}</div>
                        </div>
                        <div>
                          <span className="text-slate-400">信号状态</span>
                          <div className="font-medium text-slate-900">{String(outcome.signal_status || '-')}</div>
                        </div>
                      </div>
                      <div className="mt-2 text-xs text-slate-500">{String(outcome.metric_note || '模拟数据来自 SignalOps paper order')}</div>
                      <div data-testid={`case-library-simulation-case-governance-${item.case_id}`} className="mt-3 grid gap-2 rounded-md border border-sky-200 bg-sky-50 p-3 text-xs text-slate-700 sm:grid-cols-2 xl:grid-cols-5">
                        <span data-testid={`case-library-simulation-case-id-${item.case_id}`} className="min-w-0 break-all">
                          Case: {governance.contextId}
                        </span>
                        <span data-testid={`case-library-simulation-case-evidence-strength-${item.case_id}`} className="min-w-0 break-words">
                          Evidence: {governance.evidenceStrength}
                        </span>
                        <span data-testid={`case-library-simulation-case-blocker-${item.case_id}`} className="min-w-0 break-words">
                          Blocker: {governance.blocker}
                        </span>
                        <span data-testid={`case-library-simulation-case-next-action-${item.case_id}`} className="min-w-0 break-words">
                          Next: {governance.nextAction}
                        </span>
                        <span data-testid={`case-library-simulation-case-simulation-boundary-${item.case_id}`} className="min-w-0 break-words font-medium text-slate-900">
                          simulation_only={String(governance.simulationOnly)} / is_real_trade={String(governance.isRealTrade)} / evidence_usage={governance.evidenceUsage} / strong_conclusion_allowed={String(governance.strongConclusionAllowed)} / SIM_*
                        </span>
                      </div>
                      {warnings.length > 0 && (
                        <div className="mt-3 flex flex-wrap gap-2">
                          {warnings.map((warning) => (
                            <span key={String(warning)} className="rounded bg-amber-100 px-2 py-1 text-xs text-amber-700">
                              {String(warning)}
                            </span>
                          ))}
                        </div>
                      )}
                      <div className="mt-3 text-xs text-slate-400">
                        Signal: {item.source_signal_id} · Paper order: {item.source_paper_order_id} · {formatDateTime(item.created_at)}
                      </div>
                    </div>
                    <div className="shrink-0 text-right text-xs text-slate-500">
                      <div>{item.case_source}</div>
                      <div>{item.agent_id}</div>
                      {item.run_id ? <div>Run: {item.run_id}</div> : null}
                    </div>
                  </div>
                </div>
              )
            })
          )}
        </div>
      )}

      {activeTab === 'errors' && (
        <div className="space-y-4">
          {errors.length === 0 ? (
            <ResearchEmptyState title="暂无错误记录" description="当研究闭环产生失败、偏差或需补丁事项时，错误账本会在这里显示。" icon={AlertTriangle} />
          ) : (
            errors.map((entry) => {
              const governance = buildErrorLedgerGovernance(entry)
              return (
                <div key={entry.entry_id} className="rounded-lg border border-slate-200 bg-white p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge status={entry.status === 'OPEN' ? 'FAIL' : 'PASS'}>{entry.status}</Badge>
                        <span className="rounded bg-slate-100 px-2 py-1 text-xs text-slate-600">{entry.error_type}</span>
                        {entry.node && <span className="text-xs text-slate-500">{entry.node}</span>}
                        {entry.patch_required && (
                          <span className="inline-flex items-center gap-1 rounded bg-amber-100 px-2 py-1 text-xs text-amber-700">
                            <Wrench size={12} />
                            需补丁
                          </span>
                        )}
                      </div>
                      <div className="mt-2 text-sm text-slate-700">{entry.error_reason}</div>
                      <div className="mt-1 text-xs text-slate-400">
                        Run: {entry.run_id} · 重复: {entry.repeated_count}次 · {formatDateTime(entry.created_at)}
                      </div>
                      <div data-testid={`case-library-error-governance-${entry.entry_id}`} className="mt-3 grid gap-2 rounded-md border border-rose-200 bg-rose-50 p-3 text-xs text-slate-700 sm:grid-cols-2 xl:grid-cols-5">
                        <span data-testid={`case-library-error-id-${entry.entry_id}`} className="min-w-0 break-all">
                          Error: {governance.contextId}
                        </span>
                        <span data-testid={`case-library-error-evidence-strength-${entry.entry_id}`} className="min-w-0 break-words">
                          Evidence: {governance.evidenceStrength}
                        </span>
                        <span data-testid={`case-library-error-blocker-${entry.entry_id}`} className="min-w-0 break-words">
                          Blocker: {governance.blocker}
                        </span>
                        <span data-testid={`case-library-error-next-action-${entry.entry_id}`} className="min-w-0 break-words">
                          Next: {governance.nextAction}
                        </span>
                        <span data-testid={`case-library-error-simulation-boundary-${entry.entry_id}`} className="min-w-0 break-words font-medium text-slate-900">
                          simulation_only={String(governance.simulationOnly)} / is_real_trade={String(governance.isRealTrade)} / evidence_usage={entry.evidence_usage} / strong_conclusion_allowed={String(entry.strong_conclusion_allowed)} / SIM_*
                        </span>
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => handleDeleteError(entry.entry_id)}
                      disabled={saving || !canDeleteCaseLibraryItems}
                      title="删除此错误记录"
                      className="shrink-0 inline-flex items-center justify-center rounded p-1.5 text-slate-400 transition hover:bg-red-50 hover:text-red-600 disabled:opacity-40"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>
              )
            })
          )}
        </div>
      )}

      {activeTab === 'patches' && (
        <div className="space-y-4">
          {patches.length === 0 ? (
            <ResearchEmptyState title="暂无知识补丁" description="案例复盘或研究轮次生成补丁后，可以在这里评估、批准、拒绝或归档。" icon={Wrench} />
          ) : (
            patches.map((patch) => (
              <div key={patch.patch_id} className="rounded-lg border border-slate-200 bg-white p-4">
                <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                  <div className="flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge status={patch.approval_status === 'APPROVED' ? 'PASS' : patch.approval_status === 'CANDIDATE' ? 'WARN' : 'SKIPPED'}>
                        {patch.approval_status}
                      </Badge>
                      {patch.backtest_required && (
                        <span className="inline-flex items-center gap-1 rounded bg-blue-100 px-2 py-1 text-xs text-blue-700">
                          <AlertTriangle size={12} />
                          需回测
                        </span>
                      )}
                    </div>
                    <div className="mt-2 text-base font-semibold text-slate-950">{patch.title}</div>
                    <div className="mt-1 text-sm text-slate-600">{patch.reason}</div>
                    <div data-testid={`case-library-patch-governance-${patch.patch_id}`} className="mt-3 grid gap-2 rounded-md border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600 sm:grid-cols-2 xl:grid-cols-5">
                      <span data-testid={`case-library-patch-id-${patch.patch_id}`} className="min-w-0 break-all">
                        Patch: {patch.patch_id}
                      </span>
                      <span data-testid={`case-library-patch-evidence-strength-${patch.patch_id}`} className="min-w-0 break-words">
                        Evidence: {patchEvidenceStrengthLabel(patch)}
                      </span>
                      <span data-testid={`case-library-patch-blocker-${patch.patch_id}`} className="min-w-0 break-words">
                        Blocker: {patchBlockingReason(patch)}
                      </span>
                      <span data-testid={`case-library-patch-next-action-${patch.patch_id}`} className="min-w-0 break-words">
                        Next: {patchNextActionLabel(patch)}
                      </span>
                      <span data-testid={`case-library-patch-simulation-boundary-${patch.patch_id}`} className="min-w-0 break-words font-medium text-slate-900">
                        simulation_only={String(patch.simulation_only)} / is_real_trade={String(patch.is_real_trade)} / evidence_usage={patch.evidence_usage} / strong_conclusion_allowed={String(patch.strong_conclusion_allowed)} / SIM_*
                      </span>
                    </div>
                    <div className="mt-2 text-xs text-slate-400">
                      影响模块: {patch.affected_modules.join(', ') || 'N/A'}
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {patch.approval_status === 'CANDIDATE' && (
                      <>
                        <button
                          type="button"
                          data-testid={`case-library-approve-with-evaluation-${patch.patch_id}`}
                          onClick={() => handleApproveWithEval(patch)}
                          disabled={saving || !canWriteCaseLibraryItems}
                          title={caseLibraryWriteDisabledReason || undefined}
                          className="inline-flex items-center gap-1 rounded-lg bg-cyan-700 px-3 py-2 text-xs font-semibold text-white transition hover:bg-cyan-800 disabled:opacity-60"
                        >
                          <Zap size={14} />
                          评估+批准
                        </button>
                        <button
                          type="button"
                          data-testid={`case-library-review-approve-${patch.patch_id}`}
                          onClick={() => handleReviewPatch(patch.patch_id, 'APPROVE')}
                          disabled={saving || !canWriteCaseLibraryItems}
                          title={caseLibraryWriteDisabledReason || undefined}
                          className="inline-flex items-center gap-1 rounded-lg bg-emerald-700 px-3 py-2 text-xs font-semibold text-white transition hover:bg-emerald-800 disabled:opacity-60"
                        >
                          <CheckCircle2 size={14} />
                          批准
                        </button>
                        <button
                          type="button"
                          data-testid={`case-library-review-reject-${patch.patch_id}`}
                          onClick={() => handleReviewPatch(patch.patch_id, 'REJECT')}
                          disabled={saving || !canWriteCaseLibraryItems}
                          title={caseLibraryWriteDisabledReason || undefined}
                          className="inline-flex items-center gap-1 rounded-lg border border-rose-200 px-3 py-2 text-xs font-semibold text-rose-700 transition hover:bg-rose-50 disabled:opacity-60"
                        >
                          <XCircle size={14} />
                          拒绝
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDeletePatch(patch.patch_id)}
                          disabled={saving || !canDeleteCaseLibraryItems}
                          title={deleteDisabledReason ?? 'Delete knowledge patch'}
                          className="inline-flex items-center justify-center rounded p-1.5 text-slate-400 transition hover:bg-red-50 hover:text-red-600 disabled:opacity-40"
                        >
                          <Trash2 size={14} />
                        </button>
                      </>
                    )}
                    {patch.approval_status === 'APPROVED' && (
                      <>
                        <button
                          type="button"
                          data-testid={`case-library-review-archive-${patch.patch_id}`}
                          onClick={() => handleReviewPatch(patch.patch_id, 'ARCHIVE')}
                          disabled={saving || !canWriteCaseLibraryItems}
                          title={caseLibraryWriteDisabledReason || undefined}
                          className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-700 transition hover:bg-slate-50 disabled:opacity-60"
                        >
                          <BookOpenCheck size={14} />
                          归档
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDeletePatch(patch.patch_id)}
                          disabled={saving || !canDeleteCaseLibraryItems}
                          title={deleteDisabledReason ?? 'Delete knowledge patch'}
                          className="inline-flex items-center justify-center rounded p-1.5 text-slate-400 transition hover:bg-red-50 hover:text-red-600 disabled:opacity-40"
                        >
                          <Trash2 size={14} />
                        </button>
                      </>
                    )}
                    {(patch.approval_status === 'REJECTED' || patch.approval_status === 'ARCHIVED') && (
                      <button
                        type="button"
                        onClick={() => handleDeletePatch(patch.patch_id)}
                        disabled={saving || !canDeleteCaseLibraryItems}
                        title={deleteDisabledReason ?? 'Delete knowledge patch'}
                        className="inline-flex items-center justify-center rounded p-1.5 text-slate-400 transition hover:bg-red-50 hover:text-red-600 disabled:opacity-40"
                      >
                        <Trash2 size={14} />
                      </button>
                    )}
                  </div>
                </div>
                {patch.risk_note && (
                  <div className="mt-3 rounded bg-amber-50 p-3 text-xs text-amber-800">
                    <span className="font-semibold">风险说明:</span> {patch.risk_note}
                  </div>
                )}
                {patch.rollback_plan && (
                  <div className="mt-2 text-xs text-slate-500">
                    <span className="font-semibold">回滚方案:</span> {patch.rollback_plan}
                  </div>
                )}
                {promotionFeedback[patch.patch_id] ? (
                  <div
                    data-testid={`case-library-promotion-feedback-${patch.patch_id}`}
                    className={`mt-3 rounded-md border px-3 py-2 text-xs leading-5 ${promotionFeedbackClass(promotionFeedback[patch.patch_id].type)}`}
                  >
                    {promotionFeedback[patch.patch_id].message}
                  </div>
                ) : null}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  )
}
