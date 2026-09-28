import { type ElementType, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertTriangle, Archive, BookOpen, CheckCircle2, ExternalLink, FlaskConical, GitBranch, Paperclip, Plus, RefreshCw, Save, Send, Sparkles, Wrench, XCircle } from 'lucide-react'
import { Badge } from '../common/Badge'
import { Card } from '../common/Card'
import { AgentTimeline, EvidenceLedger, FactorBarStack, MatrixHeatmap, TableShell } from '../common/Material'
import { ResearchError, ResearchLoading, ResearchMetricCard, ResearchPageHeader } from './ResearchLabShared'
import {
  confirmResearchHypothesisDraft,
  archiveResearchLoop,
  attachResearchIterationBacktest,
  attachResearchIterationRun,
  createP2ClosedLoopSample,
  createResearchIteration,
  createResearchLoop,
  createNextResearchIteration,
  createResearchSampleLoopFromLatestRun,
  draftResearchHypotheses,
  getResearchLoop,
  getResearchLoops,
  getResearchSummary,
  getResearchVerdictInputs,
  materializeResearchIterationArtifacts,
  patchResearchIteration,
  recordResearchIterationFeedback,
  refreshResearchVerdictInputs,
  retryBottomResearchBacktest,
  updateResearchLoop,
} from '../../api/researchClient'
import { getAnalysisRun } from '../../api/analysisClient'
import type { P2ClosedLoopSampleResponse, P2ClosedLoopStepStatus, ResearchSampleLoopResponse } from '../../api/researchClient'
import { AnalysisRun, BottomResearchResult, ResearchActionSelection, ResearchHypothesisDraft, ResearchHypothesisDraftResponse, ResearchIteration, ResearchLoop, ResearchLoopDetail, ResearchMetricComparisonRow, ResearchSummary, ResearchVerdictInputs, ResearchWorkflowState } from '../../types'
import { useAnalysisStore } from '../../store/useAnalysisStore'
import { useToastStore } from '../../store/useToastStore'
import { roleAllows, useOperatorContext } from '../../store/operatorContext'
import { formatDateTime } from '../../utils/format'

const actionTargets = ['factor', 'model', 'signal', 'risk_rule', 'portfolio_rule', 'execution_rule', 'data_quality_rule', 'prompt_rule']
const targetModules = ['factor_engine', 'qiam', 'dvg_gate', 'risk_firewall', 'signalops', 'case_library', 'knowledge', 'evaluation', 'market_data', 'data_pipeline']

const statusLabels: Record<string, string> = {
  ACTIVE: '进行中',
  PAUSED: '已暂停',
  COMPLETED: '已完成',
  ARCHIVED: '已归档',
  PENDING: '待处理',
  REVIEWED: '已复核',
  NEEDS_MORE_DATA: '需要更多数据',
  ACCEPTED: '已接受',
  REJECTED: '已拒绝',
  PATCH_REQUIRED: '需要补丁',
  RUNNING: '运行中',
  DAILY_REVIEWED: '每日复盘',
  REGRESSED: '已退化',
  GUARDRAIL_BLOCKED: '被护栏阻断',
  DRAFT: '草稿',
  PASS: '通过',
  READY: '就绪',
  WAIT: '等待',
  WARN: '需关注',
  BLOCKED: '已阻塞',
}

const qualityLabels: Record<string, string> = {
  HIGH: '高',
  MEDIUM: '中',
  LOW: '低',
  PASS: '通过',
  WARN: '需关注',
  FAIL: '失败',
  MISSING: '缺失',
}

const actionTargetLabels: Record<string, string> = {
  factor: '因子',
  model: '模型',
  signal: '信号',
  risk_rule: '风险规则',
  portfolio_rule: '组合规则',
  execution_rule: '执行规则',
  data_quality_rule: '数据质量规则',
  prompt_rule: '提示规则',
}

const evidenceSourceLabels: Record<string, string> = {
  MFE_MAE_RESEARCH_RUN: 'MFE/MAE 路径研究',
  BOTTOM_RESEARCH_RUN: 'MFE/MAE 路径研究',
  RUN: '运行',
  BACKTEST: '回测',
  CASE: '案例',
  SIM_CASE: '模拟案例',
  KNOWLEDGE: '知识',
  PATCH: '补丁',
  EVALUATION: '评估',
  SIGNALOPS: 'SignalOps',
  KNOWLEDGE_VERSION: '知识版本',
}

const metricLabels: Record<string, string> = {
  quality_score: '质量分',
  final_action: '最终动作',
  qiam_confidence: 'QIAM 置信度',
  dvg_status: 'DVG 状态',
  backtest_return_pct: '回测收益',
  evaluation_pass_rate: '评估通过率',
}

const workflowStageLabels: Record<string, string> = {
  no_iteration: '无研究轮次',
  missing_run: '缺少运行',
  missing_portfolio_snapshot: '缺少持仓快照',
  missing_backtest: '缺少回测',
  needs_evidence_review: '待审核证据',
  evidence_review: '证据审核',
  missing_artifacts: '缺少研究资产',
  missing_evaluation: '缺少评估',
  missing_knowledge_version: '缺少知识版本',
  review_knowledge_version: '知识版本待审核',
  accepted: '已接受',
  feedback_ready: '反馈就绪',
  needs_feedback_decision: '待反馈决策',
  workflow_state_missing: '后端状态缺失',
  WAITING: '等待中',
}

const workflowActionLabels: Record<string, string> = {
  create_iteration: '创建第一轮研究',
  attach_or_create_run: '关联或创建运行',
  attach_portfolio_snapshot: '关联持仓快照',
  attach_or_create_backtest: '关联或创建回测',
  review_evidence: '审核证据',
  materialize_artifacts: '补齐研究资产',
  evaluate_patch: '评估补丁',
  promote_knowledge_version: '发布知识版本',
  review_knowledge_version: '审核知识版本',
  create_next_iteration: '创建下一轮研究',
  accept_feedback: '采纳反馈',
  send_to_feedback: '发送到反馈',
}

const workflowStepLabels: Record<string, string> = {
  portfolio: '持仓',
  run: '运行',
  signalops: 'SignalOps',
  backtest: '回测',
  backtest_quality: '回测质量',
  research: '研究',
  iteration: '轮次',
  evidence: '证据审核',
  artifacts: '资产',
  knowledge: '知识',
  case: '案例',
  patch: '补丁',
  evaluation: '评估',
  feedback: '反馈',
  knowledge_version: '知识版本',
}

const knownTextLabels: Record<string, string> = {
  'SignalOps daily paper-trading research loop': 'SignalOps 每日模拟交易研究循环',
  'Connect AI paper-trading outcomes with Research Lab so cleaned cases can tune buy triggers, invalidation rules, and position sizing.': '把 AI 模拟交易结果接入研究实验室，用清洗后的案例调优买入触发、失效规则和仓位规模。',
  'Create first iteration': '创建第一轮研究',
  'Attach or create run': '关联或创建运行',
  'Attach portfolio snapshot': '关联持仓快照',
  'Attach or create backtest': '关联或创建回测',
  'Review evidence': '审核证据',
  'No action required': '无需操作',
  'Materialize artifacts': '补齐研究资产',
  'Evaluate patch': '评估补丁',
  'Promote knowledge version': '发布知识版本',
  'Review knowledge version': '审核知识版本',
  'Create next iteration': '创建下一轮研究',
  'Accept feedback': '采纳反馈',
  'Send to feedback': '发送到反馈',
  'No research iteration exists for this loop.': '这个研究循环还没有研究轮次。',
  'Create an iteration before attaching research evidence.': '先创建研究轮次，再关联研究证据。',
  'Analysis run linked.': '已关联分析运行。',
  'Imported holdings snapshot linked.': '已关联导入持仓快照。',
  'No imported holdings snapshot is linked.': '没有关联导入持仓快照。',
  'No imported holdings snapshot is linked to the current iteration.': '当前轮次还没有关联导入持仓快照。',
  'No imported holdings snapshot is linked; portfolio evidence remains user-input or template context.': '没有关联导入持仓快照；组合证据仍是用户输入或模板上下文。',
  'No linked analysis run.': '没有关联分析运行。',
  'No linked analysis run for this iteration.': '当前轮次还没有关联分析运行。',
  'No linked analysis run for the current iteration.': '当前轮次还没有关联分析运行。',
  'Linked analysis run is missing or legacy; attach a canonical analysis run.': '关联分析运行不存在或来自 legacy；请关联 canonical 分析运行。',
  'Backtest linked.': '已关联回测。',
  'No linked backtest.': '没有关联回测。',
  'No linked backtest for the current iteration.': '当前轮次还没有关联回测。',
  'Linked backtest is missing; attach a persisted backtest run.': '关联回测不存在；请关联已持久化的回测运行。',
  'Backtest evidence can support research review.': '回测证据可进入研究复核。',
  'Link a backtest before quality review.': '先关联回测，再审核质量。',
  'Backtest evidence is supporting-only and cannot be promoted to a strong research conclusion.': '回测证据仅能作为支持材料，不能升级为强研究结论。',
  'Backtest evidence does not meet canSupportResearchVerdict.': '回测证据未达到可支撑研究结论的标准。',
  'Backtest uses mock or fallback market data.': '回测使用了 mock 或 fallback 行情数据。',
  'Backtest has no explicit out-of-sample or walk-forward evidence.': '回测缺少明确样本外或 walk-forward 证据。',
  'Backtest benchmark evidence is missing or unavailable.': '回测 benchmark 证据缺失或不可用。',
  'Evidence links available.': '已有证据链接。',
  'Verdict evidence has not been reviewed.': '尚未审核反馈证据。',
  'Case, knowledge candidate, and patch are linked.': '已关联案例、知识候选和补丁。',
  'No linked research case.': '没有关联研究案例。',
  'No linked knowledge item.': '没有关联知识条目。',
  'No linked patch candidate.': '没有关联补丁候选。',
  'No linked patch evaluation for the current iteration.': '当前轮次还没有关联补丁评估。',
  'No promoted knowledge version for the current iteration.': '当前轮次还没有发布知识版本。',
  'Patch evaluation linked.': '已关联补丁评估。',
  'Evaluate the linked patch.': '评估已关联补丁。',
  'Create a patch before evaluation.': '评估前需要先创建补丁。',
  'Knowledge version promoted.': '已发布知识版本。',
  'Knowledge version ready': '知识版本已就绪',
  'Knowledge version staged for review': '知识版本已进入审核队列',
  'Knowledge version is review and cannot activate feedback acceptance.': '知识版本仍处于审核状态，不能激活反馈采纳。',
  'Promote a knowledge version after evaluation.': '评估后发布知识版本。',
  'Evaluate a patch before knowledge promotion.': '发布知识版本前需要先完成补丁评估。',
  'Accepted by feedback.': '反馈已采纳。',
  'Ready for acceptance feedback.': '可以提交采纳反馈。',
  'Feedback acceptance is not ready.': '反馈采纳条件尚未满足。',
  'Quality score': '质量分',
  'Final action': '最终动作',
  'QIAM confidence': 'QIAM 置信度',
  'DVG status': 'DVG 状态',
  'Backtest return': '回测收益',
  'Eval pass rate': '评估通过率',
}

function splitCsv(value: string) {
  return value.split(',').map((item) => item.trim()).filter(Boolean)
}

function statusBadge(status: string) {
  if (status === 'ACTIVE' || status === 'ACCEPTED') return 'PASS'
  if (status === 'PATCH_REQUIRED' || status === 'REJECTED') return 'FAIL'
  if (status === 'PAUSED' || status === 'REVIEWED') return 'WARN'
  return 'WAIT'
}

function statusLabel(status: string) {
  return statusLabels[status.toUpperCase()] ?? status
}

function actionTargetLabel(target: string) {
  return actionTargetLabels[target] ?? target
}

function qualityLabel(quality: string) {
  return qualityLabels[quality.toUpperCase()] ?? statusLabel(quality)
}

function workflowReviewStrength(value?: string | null, fallbackStatus?: string): string {
  const normalized = String(value || '').trim().toUpperCase()
  if ([
    'HIGH',
    'STRONG',
    'PRIMARY',
    'PRIMARY_EVIDENCE',
    'PRIMARY_EVIDENCE_READY',
    'PASS',
    'READY',
    'RESEARCH_GRADE',
  ].includes(normalized)) return 'MEDIUM'
  if (['UNKNOWN', 'SUPPORTING_ONLY', 'WEAK', 'WARN', 'REVIEW', 'REVIEW_ONLY'].includes(normalized)) return 'LOW'
  if (['MEDIUM', 'LOW', 'MISSING', 'PENDING'].includes(normalized)) return normalized
  if (['FAIL', 'FAILED', 'BLOCKED'].includes(normalized)) return 'MISSING'
  return fallbackStatus ? workflowReviewStrength(fallbackStatus) : 'LOW'
}

function closedLoopStepReviewStrength(step: P2ClosedLoopStepStatus) {
  const normalized = workflowReviewStrength(step.evidence_strength)
  if (['PENDING', 'UNKNOWN'].includes(normalized)) return workflowReviewStrength(step.status)
  return normalized
}

function evidenceSourceLabel(sourceType: string) {
  return evidenceSourceLabels[sourceType.toUpperCase()] ?? sourceType
}

function metricLabel(row: ResearchMetricComparisonRow) {
  return metricLabels[row.key] ?? (row.label ? localizedText(row.label) : row.key)
}

function workflowStageLabel(stage: string) {
  return workflowStageLabels[stage] ?? statusLabel(stage)
}

function workflowStepLabel(key: string, fallback: string) {
  return workflowStepLabels[key] ?? knownTextLabels[fallback] ?? fallback
}

function localizedText(value: string): string {
  const trimmed = value.trim()
  if (knownTextLabels[trimmed]) return knownTextLabels[trimmed]
  if (trimmed.includes('; ')) return trimmed.split('; ').map(localizedText).join('；')
  const backtestStrengthMatch = trimmed.match(/^Backtest evidence strength is ([A-Z_]+); keep it as supporting evidence/i)
  if (backtestStrengthMatch) {
    return `回测证据强度为 ${backtestStrengthMatch[1].toUpperCase()}；仅作为支持材料，需先审核样本、数据源和样本外检查。`
  }
  if (trimmed.includes('mock or fallback market data')) return '回测使用 mock 或 fallback 行情数据，需先审核证据。'
  const iterationMatch = trimmed.match(/^Current iteration #(\d+):\s*(.+)$/)
  if (iterationMatch) return `当前轮次 #${iterationMatch[1]}：${statusLabel(iterationMatch[2])}`
  const linkedCaseMissingMatch = trimmed.match(/^Linked case not found:\s*(.+)$/)
  if (linkedCaseMissingMatch) return `关联案例不存在：${linkedCaseMissingMatch[1]}`
  const evidenceQualityMatch = trimmed.match(/^([A-Z_]+):(.+?)\s+quality=([A-Z_]+)$/)
  if (evidenceQualityMatch) {
    return `${evidenceSourceLabel(evidenceQualityMatch[1])}：${evidenceQualityMatch[2]} 质量=${qualityLabel(evidenceQualityMatch[3])}`
  }
  return value
}

function workflowNextActionLabel(workflowState: ResearchWorkflowState | null, iteration: ResearchIteration | null): string {
  if (workflowState?.next_action) {
    return workflowActionLabels[workflowState.next_action] ?? localizedText(workflowState.next_action_label)
  }
  return fallbackNextActionLabel(iteration)
}

function workflowCurrentStepLabel(workflowState: ResearchWorkflowState | null): string {
  if (!workflowState) return 'UNKNOWN：后端 workflow_state 缺失'
  const currentStep = workflowState.steps.find((step) => (
    step.missing_items.length > 0 || step.status.toUpperCase() !== 'PASS'
  ))
    ?? workflowState.steps.find((step) => step.key === workflowState.stage)
    ?? workflowState.steps[workflowState.steps.length - 1]
  if (!currentStep) return `阶段：${workflowStageLabel(workflowState.stage)}`
  const stepLabel = workflowStepLabel(currentStep.key, currentStep.label)
  const stepStatus = statusLabel(currentStep.status)
  const stepRef = currentStep.ref_id ? ` · ${currentStep.ref_id}` : ''
  return `${stepLabel} · ${stepStatus}${stepRef}`
}

export function ResearchLoopsPage() {
  const addToast = useToastStore((state) => state.addToast)
  const { currentRun, currentRunId } = useAnalysisStore()
  const operator = useOperatorContext()
  const canWriteResearchLab = roleAllows(operator.role, 'researcher')
  const researchWriteDisabledReason = canWriteResearchLab
    ? ''
    : `研究实验室工作流写入需要研究员权限。当前角色：${operator.role}。`
  const [summary, setSummary] = useState<ResearchSummary | null>(null)
  const [loops, setLoops] = useState<ResearchLoop[]>([])
  const [detail, setDetail] = useState<ResearchLoopDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [title, setTitle] = useState('')
  const [objective, setObjective] = useState('')
  const [hypothesis, setHypothesis] = useState('')
  const [plan, setPlan] = useState('')
  const [actionTarget, setActionTarget] = useState('factor')
  const [tagsText, setTagsText] = useState('')
  const [modulesText, setModulesText] = useState('factor_engine,signalops')
  const [linkedProject, setLinkedProject] = useState('')
  const [linkedModule, setLinkedModule] = useState('')
  const [linkedPath, setLinkedPath] = useState('')
  const [iterationHypothesis, setIterationHypothesis] = useState('')
  const [iterationPlan, setIterationPlan] = useState('')
  const [iterationModules, setIterationModules] = useState('qiam,dvg_gate,signalops')
  const [feedbackNote, setFeedbackNote] = useState('')
  const [loopEditTitle, setLoopEditTitle] = useState('')
  const [loopEditObjective, setLoopEditObjective] = useState('')
  const [loopEditStatus, setLoopEditStatus] = useState('ACTIVE')
  const [loopEditTags, setLoopEditTags] = useState('')
  const [iterationEditHypothesis, setIterationEditHypothesis] = useState('')
  const [iterationEditPlan, setIterationEditPlan] = useState('')
  const [iterationEditModules, setIterationEditModules] = useState('')
  const [iterationEditStatus, setIterationEditStatus] = useState('PENDING')
  const [iterationEditVerdict, setIterationEditVerdict] = useState('PENDING')
  const [attachRunId, setAttachRunId] = useState(currentRunId ?? '')
  const [attachBacktestId, setAttachBacktestId] = useState('')
  const [verdictInputs, setVerdictInputs] = useState<ResearchVerdictInputs | null>(null)
  const [verdictLoading, setVerdictLoading] = useState(false)
  const [artifactLoading, setArtifactLoading] = useState(false)
  const [linkedRun, setLinkedRun] = useState<AnalysisRun | null>(null)
  const [linkedRunLoading, setLinkedRunLoading] = useState(false)
  const [linkedRunError, setLinkedRunError] = useState<string | null>(null)
  const [bottomRetrying, setBottomRetrying] = useState(false)
  const [draftUseLlm, setDraftUseLlm] = useState(false)
  const [draftMaxDrafts, setDraftMaxDrafts] = useState(3)
  const [draftLoading, setDraftLoading] = useState(false)
  const [draftError, setDraftError] = useState<string | null>(null)
  const [draftResult, setDraftResult] = useState<ResearchHypothesisDraftResponse | null>(null)
  const [confirmingDraftIndex, setConfirmingDraftIndex] = useState<number | null>(null)
  const [sampleLoopCreating, setSampleLoopCreating] = useState(false)
  const [closedLoopCreating, setClosedLoopCreating] = useState(false)
  const [closedLoopForceBacktest, setClosedLoopForceBacktest] = useState(false)
  const [closedLoopRunEvaluation, setClosedLoopRunEvaluation] = useState(true)
  const [closedLoopPromoteKnowledgeVersion, setClosedLoopPromoteKnowledgeVersion] = useState(true)
  const [sampleLoopResult, setSampleLoopResult] = useState<ResearchSampleLoopResponse | null>(null)
  const [closedLoopResult, setClosedLoopResult] = useState<P2ClosedLoopSampleResponse | null>(null)
  const selectedLoopIdRef = useRef<string | undefined>()
  const loadRequestRef = useRef(0)
  const verdictRequestRef = useRef(0)

  const selectedLoopId = detail?.loop.loop_id
  const currentIteration = useMemo(() => {
    if (!detail) return null
    return detail.iterations.find((item) => item.iteration_id === detail.loop.current_iteration_id)
      ?? detail.iterations[detail.iterations.length - 1]
      ?? null
  }, [detail])
  const linkedRunId = currentIteration?.linked_run_id
  const currentLinkedRun = currentRun?.runId === linkedRunId ? currentRun : null

  const load = useCallback(async (preferredLoopId?: string) => {
    const requestId = loadRequestRef.current + 1
    loadRequestRef.current = requestId
    const isLatestRequest = () => requestId === loadRequestRef.current
    setLoading(true)
    setError(null)
    try {
      const [nextSummary, nextLoops] = await Promise.all([getResearchSummary(), getResearchLoops()])
      if (!isLatestRequest()) return
      setSummary(nextSummary)
      setLoops(nextLoops)
      const nextLoopId = preferredLoopId || selectedLoopIdRef.current || nextLoops[0]?.loop_id
      const nextDetail = nextLoopId ? await getResearchLoop(nextLoopId) : null
      if (!isLatestRequest()) return
      selectedLoopIdRef.current = nextLoopId
      setDetail(nextDetail)
    } catch (err) {
      if (isLatestRequest()) setError(err instanceof Error ? err.message : '无法加载研究循环')
    } finally {
      if (isLatestRequest()) setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const loadVerdictInputs = useCallback(async (iterationId: string, persist = false) => {
    const requestId = verdictRequestRef.current + 1
    verdictRequestRef.current = requestId
    setVerdictLoading(true)
    try {
      const nextInputs = persist
        ? await refreshResearchVerdictInputs(iterationId)
        : await getResearchVerdictInputs(iterationId)
      if (verdictRequestRef.current !== requestId || nextInputs.iteration_id !== iterationId) return
      setVerdictInputs(nextInputs)
      if (persist) addToast('结论输入已刷新', 'success')
    } catch (err) {
      if (verdictRequestRef.current === requestId) setVerdictInputs(null)
      if (persist) addToast(err instanceof Error ? err.message : 'Unable to refresh verdict inputs', 'error')
    } finally {
      if (verdictRequestRef.current === requestId) setVerdictLoading(false)
    }
  }, [addToast])

  useEffect(() => {
    if (!currentIteration) {
      verdictRequestRef.current += 1
      setVerdictInputs(null)
      return
    }
    loadVerdictInputs(currentIteration.iteration_id)
  }, [currentIteration, loadVerdictInputs])

  useEffect(() => {
    let cancelled = false
    if (!linkedRunId) {
      setLinkedRun(null)
      setLinkedRunLoading(false)
      setLinkedRunError(null)
      return
    }
    if (currentLinkedRun) {
      setLinkedRun(currentLinkedRun)
      setLinkedRunLoading(false)
      setLinkedRunError(null)
      return
    }
    setLinkedRunLoading(true)
    setLinkedRunError(null)
    getAnalysisRun(linkedRunId)
      .then((run) => {
        if (!cancelled) {
          setLinkedRun(run)
          setLinkedRunError(null)
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setLinkedRun(null)
          setLinkedRunError(error instanceof Error ? error.message : 'Unknown linked run load error')
        }
      })
      .finally(() => {
        if (!cancelled) setLinkedRunLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [linkedRunId, currentLinkedRun])

  useEffect(() => {
    setDraftResult(null)
    setDraftError(null)
  }, [selectedLoopId])

  useEffect(() => {
    if (!detail) return
    setLoopEditTitle(localizedText(detail.loop.title))
    setLoopEditObjective(localizedText(detail.loop.objective))
    setLoopEditStatus(detail.loop.status)
    setLoopEditTags(detail.loop.tags.join(','))
  }, [detail])

  function ensureResearchLabWrite(action: string) {
    if (canWriteResearchLab) return true
    addToast(`${action}需要研究员权限。当前角色：${operator.role}。`, 'error')
    return false
  }

  useEffect(() => {
    if (!selectedLoopId || !closedLoopResult?.loop_id) return
    if (closedLoopResult.loop_id !== selectedLoopId) {
      setClosedLoopResult(null)
    }
  }, [selectedLoopId, closedLoopResult?.loop_id])

  useEffect(() => {
    if (!currentIteration) return
    setIterationEditHypothesis(currentIteration.hypothesis)
    setIterationEditPlan(currentIteration.plan)
    setIterationEditModules(currentIteration.target_modules.join(','))
    setIterationEditStatus(currentIteration.status)
    setIterationEditVerdict(currentIteration.verdict)
    setAttachRunId(currentIteration.linked_run_id ?? currentRunId ?? '')
    setAttachBacktestId(currentIteration.linked_backtest_id ?? '')
  }, [currentIteration, currentRunId])

  async function handleCreateLoop() {
    if (!ensureResearchLabWrite('创建研究循环')) return
    setSaving(true)
    try {
      const linkedProjects = linkedProject.trim() && linkedModule.trim()
        ? [{
          project: linkedProject.trim(),
          module: linkedModule.trim(),
          path: linkedPath.trim(),
          expected_version: 'latest-compatible',
          sync_status: 'PENDING',
          note: '由研究实验室创建',
        }]
        : []
      const created = await createResearchLoop({
        title,
        objective,
        hypothesis,
        plan,
        action_target: actionTarget,
        tags: splitCsv(tagsText),
        target_modules: splitCsv(modulesText),
        linked_projects: linkedProjects,
      })
      addToast('研究循环已创建', 'success')
      setTitle('')
      setObjective('')
      setHypothesis('')
      setPlan('')
      setTagsText('')
      setLinkedProject('')
      setLinkedModule('')
      setLinkedPath('')
      await load(created.loop.loop_id)
    } catch (err) {
      addToast(err instanceof Error ? err.message : '创建研究循环失败', 'error')
    } finally {
      setSaving(false)
    }
  }

  async function handleCreateSampleLoop() {
    if (!ensureResearchLabWrite('从最新运行创建研究循环')) return
    setSampleLoopCreating(true)
    try {
      const result = await createResearchSampleLoopFromLatestRun({ reviewer: 'human' })
      setSampleLoopResult(result)
      if (result.created && result.detail) {
        addToast('Sample research loop created from the latest run', 'success')
        await load(result.detail.loop.loop_id)
      } else {
        addToast(result.missing_reasons[0] || 'No completed or stale run is available', 'warning')
      }
    } catch (err) {
      addToast(err instanceof Error ? err.message : 'Unable to create sample research loop', 'error')
    } finally {
      setSampleLoopCreating(false)
    }
  }

  async function handleCreateClosedLoopSample() {
    if (!ensureResearchLabWrite('创建 P2 闭环样本')) return
    setClosedLoopCreating(true)
    try {
      const result = await createP2ClosedLoopSample({
        reviewer: 'human',
        force_backtest: closedLoopForceBacktest,
        materialize_artifacts: true,
        run_evaluation: closedLoopRunEvaluation,
        promote_knowledge_version: closedLoopRunEvaluation && closedLoopPromoteKnowledgeVersion,
      })
      setClosedLoopResult(result)
      setSampleLoopResult(result.sample_loop ?? null)
      if (result.created && result.sample_loop?.detail) {
        const knowledgeId = stringValue(result.knowledge_item_id)
        addToast(knowledgeId ? `P2 闭环样例已生成: ${knowledgeId}` : 'P2 闭环样例已生成', 'success')
        if (result.warnings.length > 0) {
          addToast(`闭环提示: ${result.warnings.slice(0, 2).join(' / ')}`, 'warning')
        }
        await load(result.sample_loop.detail.loop.loop_id)
      } else {
        addToast(result.warnings[0] || '无法创建 P2 闭环样本', 'warning')
      }
    } catch (err) {
      addToast(err instanceof Error ? err.message : '无法创建 P2 闭环样本', 'error')
    } finally {
      setClosedLoopCreating(false)
    }
  }

  async function handleCreateIteration() {
    if (!selectedLoopId) return
    if (!ensureResearchLabWrite('创建研究轮次')) return
    setSaving(true)
    try {
      const iteration = await createResearchIteration(selectedLoopId, {
        hypothesis: iterationHypothesis,
        plan: iterationPlan,
        target_modules: splitCsv(iterationModules),
        linked_run_id: currentRunId ?? undefined,
      })
      addToast(`第 ${iteration.order} 轮研究已创建`, 'success')
      setIterationHypothesis('')
      setIterationPlan('')
      await load(selectedLoopId)
    } catch (err) {
      addToast(err instanceof Error ? err.message : '创建研究轮次失败', 'error')
    } finally {
      setSaving(false)
    }
  }

  async function handleUpdateLoop() {
    if (!selectedLoopId) return
    if (!ensureResearchLabWrite('更新研究循环')) return
    setSaving(true)
    try {
      const updated = await updateResearchLoop(selectedLoopId, {
        title: loopEditTitle,
        objective: loopEditObjective,
        status: loopEditStatus,
        tags: splitCsv(loopEditTags),
      })
      addToast('研究循环已更新', 'success')
      await load(updated.loop.loop_id)
    } catch (err) {
      addToast(err instanceof Error ? err.message : 'Unable to update research loop', 'error')
    } finally {
      setSaving(false)
    }
  }

  async function handleArchiveLoop() {
    if (!selectedLoopId) return
    if (!ensureResearchLabWrite('归档研究循环')) return
    setSaving(true)
    try {
      const archived = await archiveResearchLoop(selectedLoopId, {
        reviewer: 'human',
        note: feedbackNote || '由研究实验室归档。',
      })
      addToast('研究循环已归档', 'success')
      await load(archived.loop.loop_id)
    } catch (err) {
      addToast(err instanceof Error ? err.message : 'Unable to archive research loop', 'error')
    } finally {
      setSaving(false)
    }
  }

  async function handlePatchIteration(iteration: ResearchIteration) {
    if (!ensureResearchLabWrite('补丁更新研究轮次')) return
    setSaving(true)
    try {
      await patchResearchIteration(iteration.iteration_id, {
        hypothesis: iterationEditHypothesis,
        plan: iterationEditPlan,
        target_modules: splitCsv(iterationEditModules),
        status: iterationEditStatus,
        verdict: iterationEditVerdict,
      })
      addToast('研究轮次已更新', 'success')
      await load(iteration.loop_id)
      await loadVerdictInputs(iteration.iteration_id)
    } catch (err) {
      addToast(err instanceof Error ? err.message : 'Unable to patch research iteration', 'error')
    } finally {
      setSaving(false)
    }
  }

  async function handleAttachRun(iteration: ResearchIteration) {
    if (!attachRunId.trim()) return
    if (!ensureResearchLabWrite('关联分析运行')) return
    setSaving(true)
    try {
      await attachResearchIterationRun(iteration.iteration_id, {
        run_id: attachRunId.trim(),
        reviewer: 'human',
        note: feedbackNote || '由研究实验室关联。',
      })
      addToast('Run attached to research iteration', 'success')
      await load(iteration.loop_id)
      await loadVerdictInputs(iteration.iteration_id, true)
    } catch (err) {
      addToast(err instanceof Error ? err.message : 'Unable to attach run', 'error')
    } finally {
      setSaving(false)
    }
  }

  async function handleAttachBacktest(iteration: ResearchIteration) {
    if (!attachBacktestId.trim()) return
    if (!ensureResearchLabWrite('关联回测')) return
    setSaving(true)
    try {
      await attachResearchIterationBacktest(iteration.iteration_id, {
        backtest_id: attachBacktestId.trim(),
        reviewer: 'human',
        note: feedbackNote || '由研究实验室关联。',
      })
      addToast('回测已关联到研究轮次', 'success')
      await load(iteration.loop_id)
      await loadVerdictInputs(iteration.iteration_id, true)
    } catch (err) {
      addToast(err instanceof Error ? err.message : 'Unable to attach backtest', 'error')
    } finally {
      setSaving(false)
    }
  }

  async function handleRetryBottomResearchBacktest(iteration: ResearchIteration) {
    const runId = linkedRun?.runId ?? iteration.linked_run_id ?? ''
    if (!runId) return
    if (!ensureResearchLabWrite('刷新 MFE/MAE 研究证据')) return
    setBottomRetrying(true)
    try {
      const updated = await retryBottomResearchBacktest(iteration.iteration_id, {
        run_id: runId,
        force_new: false,
        reviewer: 'human',
      })
      addToast('MFE/MAE 路径研究回测证据已刷新', 'success')
      await load(updated.loop_id)
      await loadVerdictInputs(updated.iteration_id)
    } catch (err) {
      addToast(err instanceof Error ? err.message : '无法重试 MFE/MAE 路径研究回测', 'error')
    } finally {
      setBottomRetrying(false)
    }
  }

  async function handleCreateNextFromIteration(iteration: ResearchIteration) {
    if (!ensureResearchLabWrite('创建下一轮研究')) return
    setSaving(true)
    try {
      const next = await createNextResearchIteration(iteration.iteration_id, {
        hypothesis: iterationHypothesis || iterationEditHypothesis,
        plan: iterationPlan || iterationEditPlan,
        target_modules: splitCsv(iterationModules || iterationEditModules),
        reviewer: 'human',
        note: feedbackNote || '由研究实验室创建下一轮。',
      })
      addToast(`Next research iteration #${next.order} created`, 'success')
      setIterationHypothesis('')
      setIterationPlan('')
      await load(iteration.loop_id)
    } catch (err) {
      addToast(err instanceof Error ? err.message : 'Unable to create next iteration', 'error')
    } finally {
      setSaving(false)
    }
  }

  async function handleDraftHypotheses() {
    if (!selectedLoopId || !detail) return
    if (!ensureResearchLabWrite('起草研究假设')) return
    setDraftLoading(true)
    setDraftError(null)
    try {
      const result = await draftResearchHypotheses(selectedLoopId, {
        iteration_id: currentIteration?.iteration_id,
        context_metrics: buildDraftContextMetrics(detail.loop, currentIteration, verdictInputs),
        use_llm: draftUseLlm,
        max_drafts: draftMaxDrafts,
        reviewer: 'human',
      })
      setDraftResult(result)
      addToast(result.llm_error ? 'LLM failed; rule drafts are still available' : 'Hypothesis drafts generated', result.llm_error ? 'warning' : 'success')
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unable to generate hypothesis drafts'
      setDraftError(message)
      addToast(message, 'error')
    } finally {
      setDraftLoading(false)
    }
  }

  function handleApplyDraft(draft: ResearchHypothesisDraft) {
    const fields = normalizeDraftFields(draft, draftResult?.action_selection)
    setIterationHypothesis(fields.hypothesis)
    setIterationPlan(fields.plan)
    setIterationModules(fields.modules.join(','))
    addToast('Draft applied to the next-iteration form', 'success')
  }

  async function handleConfirmDraft(index: number) {
    if (!draftResult || !selectedLoopId) return
    if (!ensureResearchLabWrite('确认研究假设草稿')) return
    setConfirmingDraftIndex(index)
    try {
      const iteration = await confirmResearchHypothesisDraft(draftResult.draft_id, {
        selected_index: index,
        reviewer: 'human',
        note: feedbackNote || 'Confirmed from guided hypothesis draft.',
      })
      setDraftResult((current) => current
        ? {
          ...current,
          status: 'CONFIRMED',
          confirmation_required: false,
          confirmed_iteration_id: iteration.iteration_id,
        }
        : current)
      addToast(`Draft confirmed as research iteration #${iteration.order}`, 'success')
      await load(selectedLoopId)
      await loadVerdictInputs(iteration.iteration_id)
    } catch (err) {
      addToast(err instanceof Error ? err.message : 'Unable to confirm hypothesis draft', 'error')
    } finally {
      setConfirmingDraftIndex(null)
    }
  }

  async function handleFeedback(iteration: ResearchIteration, verdict: string) {
    if (!ensureResearchLabWrite('记录研究反馈')) return
    const iterationVerdictInputs = verdictInputs?.iteration_id === iteration.iteration_id ? verdictInputs : null
    if (verdict === 'ACCEPTED' && (!iterationVerdictInputs || !iterationVerdictInputs.can_accept_feedback)) {
      addToast('证据质量还不足以直接接受反馈。请先刷新反馈证据，或发送到反馈复核。', 'error')
      return
    }
    setSaving(true)
    try {
      await recordResearchIterationFeedback(iteration.iteration_id, {
        action: verdict === 'ACCEPTED' ? 'ACCEPT' : verdict === 'REJECTED' ? 'REJECT' : 'PATCH',
        verdict,
        note: feedbackNote,
        linked_run_id: iteration.linked_run_id ?? currentRunId ?? undefined,
        metrics: verdict === 'ACCEPTED' ? iterationVerdictInputs?.metrics : undefined,
        evidence_links: verdict === 'ACCEPTED' ? iterationVerdictInputs?.evidence.map((item) => ({
          source_type: item.source_type,
          source_id: item.source_id,
          label: item.label,
          quality: item.quality,
          reportedQuality: item.reportedQuality ?? item.reported_quality ?? undefined,
          created_at: item.created_at,
        })) : undefined,
      })
      addToast('研究反馈已记录', 'success')
      setFeedbackNote('')
      await load(iteration.loop_id)
    } catch (err) {
      addToast(err instanceof Error ? err.message : '记录研究反馈失败', 'error')
    } finally {
      setSaving(false)
    }
  }

  async function handleSendVerdictToFeedback(iteration: ResearchIteration) {
    if (!ensureResearchLabWrite('发送结论证据到反馈')) return
    if (!verdictInputs || verdictInputs.iteration_id !== iteration.iteration_id) {
      addToast('结论输入尚未加载完成', 'error')
      return
    }
    setSaving(true)
    try {
      const feedbackVerdict = verdictInputs.suggested_feedback_verdict === 'ACCEPTED' && !verdictInputs.can_accept_feedback
        ? 'PENDING'
        : verdictInputs.suggested_feedback_verdict || iteration.verdict || 'PENDING'
      await recordResearchIterationFeedback(iteration.iteration_id, {
        action: 'SEND_TO_FEEDBACK',
        verdict: feedbackVerdict,
        note: feedbackNote || `Engine verdict: ${verdictInputs.engine_verdict}`,
        linked_run_id: iteration.linked_run_id ?? undefined,
        linked_backtest_id: iteration.linked_backtest_id ?? undefined,
        linked_case_id: iteration.linked_case_id ?? undefined,
        linked_knowledge_item_id: iteration.linked_knowledge_item_id ?? undefined,
        linked_patch_id: iteration.linked_patch_id ?? undefined,
        metrics: verdictInputs.metrics,
        evidence_links: verdictInputs.evidence.map((item) => ({
          source_type: item.source_type,
          source_id: item.source_id,
          label: item.label,
          quality: item.quality,
          reportedQuality: item.reportedQuality ?? item.reported_quality ?? undefined,
          created_at: item.created_at,
        })),
      })
      addToast('Verdict evidence sent to feedback', 'success')
      setFeedbackNote('')
      await load(iteration.loop_id)
    } catch (err) {
      addToast(err instanceof Error ? err.message : 'Unable to send verdict evidence', 'error')
    } finally {
      setSaving(false)
    }
  }

  async function handleMaterializeArtifacts(iteration: ResearchIteration, runEvaluation = false) {
    if (!ensureResearchLabWrite('生成研究产物')) return
    setArtifactLoading(true)
    try {
      const result = await materializeResearchIterationArtifacts(iteration.iteration_id, {
        create_case: true,
        create_knowledge_item: true,
        create_error_entry: true,
        create_patch: true,
        run_evaluation: runEvaluation,
        reviewer: 'human',
        note: feedbackNote || `为 ${iteration.iteration_id} 生成研究实验室 P5 产物`,
        patch_content: {
          frontend_action: runEvaluation ? 'materialize_and_evaluate' : 'materialize',
        },
      })
      const created = [
        result.case ? 'case' : '',
        result.knowledge_item ? 'knowledge' : '',
        result.error_entry ? 'error' : '',
        result.patch ? 'patch' : '',
        result.evaluation ? 'evaluation' : '',
      ].filter(Boolean).join(', ')
      addToast(`闭环资产已生成${created ? `: ${created}` : ''}`, 'success')
      if (result.warnings.length > 0) {
        addToast(`闭环提示: ${result.warnings.join(', ')}`, 'warning')
      }
      await load(iteration.loop_id)
      await loadVerdictInputs(iteration.iteration_id)
    } catch (err) {
      addToast(err instanceof Error ? err.message : '生成闭环资产失败', 'error')
    } finally {
      setArtifactLoading(false)
    }
  }

  if (loading) return <ResearchLoading label="正在加载研究实验室..." />

  return (
    <div className="space-y-6">
      <ResearchPageHeader
        eyebrow="研究循环"
        title="研究迭代"
        subtitle="把假设、实验、证据、反馈和下一轮研究放在同一条闭环链路里，方便直接从当前运行生成可复核的研究轮次。"
        icon={GitBranch}
        tags={['Hypothesis', 'Run evidence', 'Feedback verdict']}
        actions={
          <div className="flex flex-wrap gap-2">
          <div className="flex flex-col justify-center rounded-md border border-slate-200 bg-white px-3 py-1 text-xs text-slate-600">
            <span data-testid="research-lab-workflow-role">角色：{operator.role}；写入：{canWriteResearchLab ? 'researcher+' : '已阻断 / blocked'}</span>
            {researchWriteDisabledReason ? (
              <span data-testid="research-lab-workflow-disabled-reason" className="text-amber-700">{researchWriteDisabledReason}</span>
            ) : null}
          </div>
          <button
            type="button"
            data-testid="research-create-closed-loop-sample"
            onClick={handleCreateClosedLoopSample}
            disabled={saving || closedLoopCreating || !canWriteResearchLab}
            title={researchWriteDisabledReason || undefined}
            className="inline-flex items-center gap-2 rounded-md border border-emerald-200 bg-emerald-50 px-4 py-2 text-sm font-semibold text-emerald-800 transition hover:bg-emerald-100 disabled:opacity-60"
          >
            <Sparkles size={16} />
            {closedLoopCreating ? '生成中...' : '生成闭环样例'}
          </button>
          <button
            type="button"
            data-testid="research-create-sample-loop-from-latest-run"
            onClick={handleCreateSampleLoop}
            disabled={saving || sampleLoopCreating || !canWriteResearchLab}
            title={researchWriteDisabledReason || undefined}
            className="inline-flex items-center gap-2 rounded-md border border-cyan-200 bg-cyan-50 px-4 py-2 text-sm font-semibold text-cyan-800 transition hover:bg-cyan-100 disabled:opacity-60"
          >
            <Sparkles size={16} />
            {sampleLoopCreating ? '创建中...' : '从最近运行创建'}
          </button>
          <button
            type="button"
            onClick={() => load()}
            disabled={saving}
            className="inline-flex items-center gap-2 rounded-md border border-slate-600 bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:opacity-60"
          >
            <RefreshCw size={16} />
            刷新循环
          </button>
          </div>
        }
      />

      {error ? <ResearchError message={error} /> : null}
      {sampleLoopResult?.missing_reasons?.length ? (
        <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
          <div className="font-semibold">样例循环证据提示</div>
          <div className="mt-1">{sampleLoopResult.missing_reasons.slice(0, 3).join(' / ')}</div>
        </div>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <ResearchMetricCard label="研究循环" value={summary?.total_loops ?? 0} helper="Loops / 全部研究对象" icon={GitBranch} tone="bg-cyan-50 text-cyan-700" />
        <ResearchMetricCard label="进行中" value={summary?.active_loops ?? 0} helper="Active / 当前推进" icon={RefreshCw} tone="bg-emerald-50 text-emerald-700" />
        <ResearchMetricCard label="研究轮次" value={summary?.total_iterations ?? 0} helper="Iterations / 假设验证次数" icon={FlaskConical} tone="bg-slate-100 text-slate-700" />
        <ResearchMetricCard label="已接受" value={summary?.accepted_iterations ?? 0} helper="Accepted / 反馈采纳" icon={CheckCircle2} tone="bg-amber-50 text-amber-700" />
        <ResearchMetricCard label="跨项目链接" value={summary?.linked_project_count ?? 0} helper="外部依赖" icon={ExternalLink} tone="bg-sky-50 text-sky-700" />
      </div>

      <ClosedLoopWizardPanel
        iteration={currentIteration}
        workflowState={detail?.workflow_state ?? null}
        sampleResult={sampleLoopResult}
        closedLoopResult={closedLoopResult}
        saving={saving || !canWriteResearchLab}
        artifactLoading={artifactLoading}
        closedLoopCreating={closedLoopCreating}
        writeDisabledReason={researchWriteDisabledReason}
        forceBacktest={closedLoopForceBacktest}
        runEvaluation={closedLoopRunEvaluation}
        promoteKnowledgeVersion={closedLoopPromoteKnowledgeVersion}
        onForceBacktestChange={setClosedLoopForceBacktest}
        onRunEvaluationChange={setClosedLoopRunEvaluation}
        onPromoteKnowledgeVersionChange={setClosedLoopPromoteKnowledgeVersion}
        onCreateClosedLoop={handleCreateClosedLoopSample}
        onMaterializeCurrent={() => currentIteration && handleMaterializeArtifacts(currentIteration, closedLoopRunEvaluation)}
      />

      <div className="grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
        <div className="space-y-6">
          <Card title="新建研究循环">
            <div className="space-y-3">
              <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="标题" className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm" />
              <textarea value={objective} onChange={(event) => setObjective(event.target.value)} placeholder="目标" rows={2} className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm" />
              <textarea value={hypothesis} onChange={(event) => setHypothesis(event.target.value)} placeholder="初始假设" rows={2} className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm" />
              <textarea value={plan} onChange={(event) => setPlan(event.target.value)} placeholder="实验计划" rows={2} className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm" />
              <div className="grid gap-3 md:grid-cols-2">
                <select value={actionTarget} onChange={(event) => setActionTarget(event.target.value)} className="rounded-md border border-slate-200 px-3 py-2 text-sm">
                  {actionTargets.map((item) => <option key={item} value={item}>{actionTargetLabel(item)}</option>)}
                </select>
                <input value={tagsText} onChange={(event) => setTagsText(event.target.value)} placeholder="标签，以逗号分隔" className="rounded-md border border-slate-200 px-3 py-2 text-sm" />
              </div>
              <input value={modulesText} onChange={(event) => setModulesText(event.target.value)} placeholder="影响模块，以逗号分隔" className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm" list="research-target-modules" />
              <datalist id="research-target-modules">
                {targetModules.map((item) => <option key={item} value={item} />)}
              </datalist>
              <div className="grid gap-3 md:grid-cols-3">
                <input value={linkedProject} onChange={(event) => setLinkedProject(event.target.value)} placeholder="关联项目" className="rounded-md border border-slate-200 px-3 py-2 text-sm" />
                <input value={linkedModule} onChange={(event) => setLinkedModule(event.target.value)} placeholder="关联模块" className="rounded-md border border-slate-200 px-3 py-2 text-sm" />
                <input value={linkedPath} onChange={(event) => setLinkedPath(event.target.value)} placeholder="路径" className="rounded-md border border-slate-200 px-3 py-2 text-sm" />
              </div>
              <button type="button" onClick={handleCreateLoop} disabled={saving || !canWriteResearchLab || !title.trim() || !objective.trim()} title={researchWriteDisabledReason || undefined} className="inline-flex items-center gap-2 rounded-md bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:opacity-60">
                <Plus size={16} />
                创建循环
              </button>
            </div>
          </Card>

          <Card title="研究循环">
            <div className="space-y-3">
              <button type="button" onClick={() => load()} disabled={saving} className="inline-flex items-center gap-2 rounded-md border border-slate-200 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50">
                <RefreshCw size={14} />
                刷新
              </button>
              {loops.length === 0 ? (
                <div className="rounded-md border border-dashed border-slate-200 p-5 text-sm text-slate-500">暂无研究循环</div>
              ) : loops.map((loop) => (
                <button
                  key={loop.loop_id}
                  type="button"
                  data-testid="research-loop-select"
                  data-loop-id={loop.loop_id}
                  onClick={() => load(loop.loop_id)}
                  className={`w-full rounded-md border p-4 text-left transition ${loop.loop_id === selectedLoopId ? 'border-cyan-400 bg-cyan-50' : 'border-slate-200 hover:bg-slate-50'}`}
                >
                  <div className="flex items-center justify-between gap-3">
                    <div className="min-w-0 font-semibold text-slate-950">{localizedText(loop.title)}</div>
                    <Badge status={statusBadge(loop.status)}>{statusLabel(loop.status)}</Badge>
                  </div>
                  <div className="mt-2 line-clamp-2 text-sm text-slate-500">{localizedText(loop.objective)}</div>
                  <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-500">
                    <span>{actionTargetLabel(loop.action_target)}</span>
                    <span>{loop.iteration_count} 轮次</span>
                    <span>{formatDateTime(loop.updated_at)}</span>
                  </div>
                </button>
              ))}
              {loops.length === 0 ? (
                <button
                  type="button"
                  onClick={handleCreateSampleLoop}
                  disabled={saving || sampleLoopCreating || !canWriteResearchLab}
                  title={researchWriteDisabledReason || undefined}
                  className="inline-flex items-center gap-2 rounded-md bg-slate-900 px-3 py-2 text-xs font-semibold text-white hover:bg-slate-800 disabled:opacity-60"
                >
                  <Sparkles size={13} />
                  {sampleLoopCreating ? '创建中...' : '从最近运行创建'}
                </button>
              ) : null}
            </div>
          </Card>
        </div>

        <div className="space-y-6">
          <Card title="当前研究">
            {detail ? (
              <div className="space-y-4">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge status={statusBadge(detail.loop.status)}>{statusLabel(detail.loop.status)}</Badge>
                  <Badge status="READ_ONLY">{actionTargetLabel(detail.loop.action_target)}</Badge>
                  {detail.loop.linked_projects.length > 0 ? <Badge status="WARN">已链接</Badge> : null}
                </div>
                <div>
                  <div className="text-lg font-semibold text-slate-950">{localizedText(detail.loop.title)}</div>
                  <div className="mt-1 text-sm text-slate-600">{localizedText(detail.loop.objective)}</div>
                </div>
                <WorkflowNextActionPanel
                  workflowState={detail.workflow_state ?? null}
                  fallbackIteration={currentIteration}
                  fallbackBlockingReasons={verdictInputs?.blocking_reasons ?? currentIteration?.metrics?.blocking_reasons}
                />
                <div className="rounded-md border border-slate-200 bg-slate-50 p-4">
                  <div className="mb-3 text-sm font-semibold text-slate-950">循环更新 / 归档</div>
                  <div className="grid gap-3 md:grid-cols-2">
                    <input value={loopEditTitle} onChange={(event) => setLoopEditTitle(event.target.value)} placeholder="循环标题" className="rounded-md border border-slate-200 px-3 py-2 text-sm" />
                    <select value={loopEditStatus} onChange={(event) => setLoopEditStatus(event.target.value)} className="rounded-md border border-slate-200 px-3 py-2 text-sm">
                      {['ACTIVE', 'PAUSED', 'COMPLETED', 'ARCHIVED'].map((status) => <option key={status} value={status}>{statusLabel(status)}</option>)}
                    </select>
                    <textarea value={loopEditObjective} onChange={(event) => setLoopEditObjective(event.target.value)} rows={2} placeholder="目标" className="rounded-md border border-slate-200 px-3 py-2 text-sm md:col-span-2" />
                    <input value={loopEditTags} onChange={(event) => setLoopEditTags(event.target.value)} placeholder="标签，以逗号分隔" className="rounded-md border border-slate-200 px-3 py-2 text-sm md:col-span-2" />
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button type="button" onClick={handleUpdateLoop} disabled={saving || !canWriteResearchLab || !loopEditTitle.trim() || !loopEditObjective.trim()} title={researchWriteDisabledReason || undefined} className="inline-flex items-center gap-2 rounded-md bg-slate-900 px-3 py-2 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-60">
                      <Save size={15} />
                      保存循环
                    </button>
                    <button type="button" onClick={handleArchiveLoop} disabled={saving || !canWriteResearchLab || detail.loop.status === 'ARCHIVED'} title={researchWriteDisabledReason || undefined} className="inline-flex items-center gap-2 rounded-md border border-amber-300 bg-white px-3 py-2 text-sm font-semibold text-amber-800 hover:bg-amber-50 disabled:opacity-60">
                      <Archive size={15} />
                      归档
                    </button>
                  </div>
                </div>
                <div className="grid gap-3 md:grid-cols-3">
                  <input value={iterationHypothesis} onChange={(event) => setIterationHypothesis(event.target.value)} placeholder="下一轮假设" className="rounded-md border border-slate-200 px-3 py-2 text-sm" />
                  <input value={iterationPlan} onChange={(event) => setIterationPlan(event.target.value)} placeholder="实验计划" className="rounded-md border border-slate-200 px-3 py-2 text-sm" />
                  <input value={iterationModules} onChange={(event) => setIterationModules(event.target.value)} placeholder="影响模块" className="rounded-md border border-slate-200 px-3 py-2 text-sm" />
                </div>
                <button type="button" onClick={handleCreateIteration} disabled={saving || !canWriteResearchLab || !iterationHypothesis.trim()} title={researchWriteDisabledReason || undefined} className="inline-flex items-center gap-2 rounded-md bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:opacity-60">
                  <GitBranch size={16} />
                  创建下一轮
                </button>
              </div>
            ) : (
              <div className="rounded-md border border-dashed border-slate-200 p-5 text-sm text-slate-500">请选择或创建研究循环</div>
            )}
          </Card>

          {detail ? (
            <GuidedHypothesisPanel
              result={draftResult}
              error={draftError}
              loading={draftLoading}
              saving={saving || !canWriteResearchLab}
              useLlm={draftUseLlm}
              maxDrafts={draftMaxDrafts}
              hasIteration={Boolean(currentIteration)}
              onUseLlmChange={setDraftUseLlm}
              onMaxDraftsChange={setDraftMaxDrafts}
              onGenerate={handleDraftHypotheses}
              onApply={handleApplyDraft}
              onConfirm={handleConfirmDraft}
              confirmingIndex={confirmingDraftIndex}
            />
          ) : null}

          {currentIteration ? (
            <Card title="当前轮次">
              <div className="space-y-4">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge status={statusBadge(currentIteration.status)}>{statusLabel(currentIteration.status)}</Badge>
                  <Badge status={statusBadge(currentIteration.verdict)}>{statusLabel(currentIteration.verdict)}</Badge>
                  <span className="text-xs text-slate-500">#{currentIteration.order}</span>
                  <span data-testid="current-loop-id" className="rounded bg-slate-100 px-2 py-1 text-xs text-slate-500">loop: {currentIteration.loop_id}</span>
                  <span data-testid="current-iteration-id" className="rounded bg-slate-100 px-2 py-1 text-xs text-slate-500">iteration: {currentIteration.iteration_id}</span>
                </div>
                <div>
                  <div className="text-base font-semibold text-slate-950">{currentIteration.hypothesis}</div>
                  {currentIteration.plan ? <div className="mt-1 text-sm text-slate-600">{currentIteration.plan}</div> : null}
                </div>
                <div className="flex flex-wrap gap-2">
                  {currentIteration.target_modules.map((module) => (
                    <span key={module} className="rounded bg-slate-100 px-2 py-1 text-xs text-slate-600">{module}</span>
                  ))}
                </div>
                <div className="flex flex-wrap gap-2 text-xs text-slate-500">
                  {currentIteration.linked_run_id ? <span className="rounded bg-slate-100 px-2 py-1">运行：{currentIteration.linked_run_id}</span> : null}
                  {currentIteration.linked_backtest_id ? (
                    <Link
                      to={researchBacktestPath(currentIteration, currentIteration.linked_backtest_id)}
                      data-testid="research-open-linked-backtest"
                      className="inline-flex items-center gap-1 rounded bg-slate-100 px-2 py-1 text-cyan-700 hover:bg-cyan-50"
                    >
                      回测：{currentIteration.linked_backtest_id}
                      <ExternalLink size={12} />
                    </Link>
                  ) : null}
                  {stringValue(currentIteration.metrics?.source_draft_id) ? <span className="rounded bg-slate-100 px-2 py-1">草稿：{stringValue(currentIteration.metrics?.source_draft_id)}</span> : null}
                </div>
                <div className="rounded-md border border-slate-200 bg-slate-50 p-4">
                  <div className="mb-3 text-sm font-semibold text-slate-950">轮次补丁 / 关联证据</div>
                  <div className="grid gap-3 md:grid-cols-2">
                    <input value={iterationEditHypothesis} onChange={(event) => setIterationEditHypothesis(event.target.value)} placeholder="假设" className="rounded-md border border-slate-200 px-3 py-2 text-sm md:col-span-2" />
                    <textarea value={iterationEditPlan} onChange={(event) => setIterationEditPlan(event.target.value)} rows={2} placeholder="计划" className="rounded-md border border-slate-200 px-3 py-2 text-sm md:col-span-2" />
                    <input value={iterationEditModules} onChange={(event) => setIterationEditModules(event.target.value)} placeholder="目标模块，以逗号分隔" className="rounded-md border border-slate-200 px-3 py-2 text-sm md:col-span-2" />
                    <select value={iterationEditStatus} onChange={(event) => setIterationEditStatus(event.target.value)} className="rounded-md border border-slate-200 px-3 py-2 text-sm">
                      {['PENDING', 'RUNNING', 'REVIEWED', 'PATCH_REQUIRED', 'ACCEPTED', 'REJECTED', 'ARCHIVED'].map((status) => <option key={status} value={status}>{statusLabel(status)}</option>)}
                    </select>
                    <select value={iterationEditVerdict} onChange={(event) => setIterationEditVerdict(event.target.value)} className="rounded-md border border-slate-200 px-3 py-2 text-sm">
                      {['PENDING', 'ACCEPTED', 'PATCH_REQUIRED', 'REJECTED', 'NEEDS_MORE_DATA'].map((verdict) => <option key={verdict} value={verdict}>{statusLabel(verdict)}</option>)}
                    </select>
                    <input data-testid="research-attach-run-id" value={attachRunId} onChange={(event) => setAttachRunId(event.target.value)} placeholder="运行 ID" className="rounded-md border border-slate-200 px-3 py-2 text-sm" />
                    <input value={attachBacktestId} onChange={(event) => setAttachBacktestId(event.target.value)} placeholder="回测 ID" className="rounded-md border border-slate-200 px-3 py-2 text-sm" />
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button type="button" onClick={() => handlePatchIteration(currentIteration)} disabled={saving || !canWriteResearchLab || !iterationEditHypothesis.trim()} title={researchWriteDisabledReason || undefined} className="inline-flex items-center gap-2 rounded-md bg-slate-900 px-3 py-2 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-60">
                      <Save size={15} />
                      更新轮次
                    </button>
                    <button type="button" onClick={() => handleAttachRun(currentIteration)} disabled={saving || !canWriteResearchLab || !attachRunId.trim()} title={researchWriteDisabledReason || undefined} className="inline-flex items-center gap-2 rounded-md border border-cyan-300 bg-white px-3 py-2 text-sm font-semibold text-cyan-800 hover:bg-cyan-50 disabled:opacity-60">
                      <Paperclip size={15} />
                      关联运行
                    </button>
                    <button type="button" onClick={() => handleAttachBacktest(currentIteration)} disabled={saving || !canWriteResearchLab || !attachBacktestId.trim()} title={researchWriteDisabledReason || undefined} className="inline-flex items-center gap-2 rounded-md border border-cyan-300 bg-white px-3 py-2 text-sm font-semibold text-cyan-800 hover:bg-cyan-50 disabled:opacity-60">
                      <FlaskConical size={15} />
                      关联回测
                    </button>
                    <button type="button" onClick={() => handleCreateNextFromIteration(currentIteration)} disabled={saving || !canWriteResearchLab || !(iterationHypothesis || iterationEditHypothesis).trim()} title={researchWriteDisabledReason || undefined} className="inline-flex items-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-100 disabled:opacity-60">
                      <GitBranch size={15} />
                      从当前创建下一轮
                    </button>
                  </div>
                </div>
                <BottomResearchEvidencePanel
                  iteration={currentIteration}
                  linkedRun={linkedRun}
                  linkedRunLoading={linkedRunLoading}
                  linkedRunError={linkedRunError}
                  retrying={bottomRetrying}
                  saving={saving || !canWriteResearchLab}
                  onRetry={() => handleRetryBottomResearchBacktest(currentIteration)}
                />
                <ClosureHealthSummaryPanel
                  iteration={currentIteration}
                  linkedRun={linkedRun}
                  linkedRunLoading={linkedRunLoading}
                  linkedRunError={linkedRunError}
                  inputs={verdictInputs}
                  workflowState={detail?.workflow_state ?? null}
                />
                <VerdictInputsPanel
                  iteration={currentIteration}
                  inputs={verdictInputs}
                  loading={verdictLoading}
                  saving={saving || !canWriteResearchLab}
                  onRefresh={() => loadVerdictInputs(currentIteration.iteration_id, true)}
                  onSend={() => handleSendVerdictToFeedback(currentIteration)}
                />
                <ArtifactActionsPanel
                  iteration={currentIteration}
                  loading={artifactLoading}
                  saving={saving || !canWriteResearchLab}
                  onMaterialize={() => handleMaterializeArtifacts(currentIteration, false)}
                  onMaterializeAndEvaluate={() => handleMaterializeArtifacts(currentIteration, true)}
                />
                <textarea value={feedbackNote} onChange={(event) => setFeedbackNote(event.target.value)} rows={2} placeholder="反馈记录" className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm" />
                <div className="flex flex-wrap gap-2">
                  <Link
                    to={`/new-task?research_loop_id=${encodeURIComponent(currentIteration.loop_id)}&research_iteration_id=${encodeURIComponent(currentIteration.iteration_id)}`}
                    className="inline-flex items-center gap-2 rounded-md border border-cyan-300 bg-white px-3 py-2 text-sm font-semibold text-cyan-800 hover:bg-cyan-50"
                  >
                    <GitBranch size={15} />
                    创建关联运行
                  </Link>
                  <Link
                    to={signalOpsEvidencePath(currentIteration)}
                    data-testid="research-open-signalops-evidence"
                    className="inline-flex items-center gap-2 rounded-md border border-cyan-300 bg-white px-3 py-2 text-sm font-semibold text-cyan-800 hover:bg-cyan-50"
                  >
                    <FlaskConical size={15} />
                    SignalOps evidence
                  </Link>
                  <button type="button" onClick={() => handleFeedback(currentIteration, 'ACCEPTED')} disabled={saving || !canWriteResearchLab} title={researchWriteDisabledReason || undefined} className="inline-flex items-center gap-2 rounded-md bg-emerald-600 px-3 py-2 text-sm font-semibold text-white disabled:opacity-60">
                    <CheckCircle2 size={15} />
                    接受
                  </button>
                  <button type="button" onClick={() => handleFeedback(currentIteration, 'PATCH_REQUIRED')} disabled={saving || !canWriteResearchLab} title={researchWriteDisabledReason || undefined} className="inline-flex items-center gap-2 rounded-md bg-amber-600 px-3 py-2 text-sm font-semibold text-white disabled:opacity-60">
                    <Save size={15} />
                    需要补丁
                  </button>
                  <button type="button" onClick={() => handleFeedback(currentIteration, 'REJECTED')} disabled={saving || !canWriteResearchLab} title={researchWriteDisabledReason || undefined} className="inline-flex items-center gap-2 rounded-md bg-rose-600 px-3 py-2 text-sm font-semibold text-white disabled:opacity-60">
                    <XCircle size={15} />
                    拒绝
                  </button>
                </div>
              </div>
            </Card>
          ) : null}

          <Card title="轮次时间线">
            {detail?.iterations.length ? (
              <AgentTimeline
                items={detail.iterations.map((iteration) => ({
                  label: `#${iteration.order} ${iteration.hypothesis}`,
                  status: `${statusLabel(iteration.status)} / ${statusLabel(iteration.verdict)}`,
                  detail: (
                    <span className="inline-flex flex-wrap items-center gap-x-3 gap-y-1">
                      <span>{formatDateTime(iteration.updated_at)}</span>
                      <span>{iteration.target_modules.slice(0, 3).join(' / ') || '无模块'}</span>
                      {iteration.linked_backtest_id ? <span>BT {iteration.linked_backtest_id}</span> : null}
                    </span>
                  ),
                  tone: materialToneForStatus(iteration.verdict || iteration.status),
                }))}
              />
            ) : (
                <div className="rounded-md border border-dashed border-slate-200 p-5 text-sm text-slate-500">暂无轮次</div>
            )}
          </Card>
        </div>
      </div>
    </div>
  )
}

function ClosedLoopWizardPanel({
  iteration,
  workflowState,
  sampleResult,
  closedLoopResult,
  saving,
  artifactLoading,
  closedLoopCreating,
  writeDisabledReason,
  forceBacktest,
  runEvaluation,
  promoteKnowledgeVersion,
  onForceBacktestChange,
  onRunEvaluationChange,
  onPromoteKnowledgeVersionChange,
  onCreateClosedLoop,
  onMaterializeCurrent,
}: {
  iteration: ResearchIteration | null
  workflowState: ResearchWorkflowState | null
  sampleResult: ResearchSampleLoopResponse | null
  closedLoopResult: P2ClosedLoopSampleResponse | null
  saving: boolean
  artifactLoading: boolean
  closedLoopCreating: boolean
  writeDisabledReason: string
  forceBacktest: boolean
  runEvaluation: boolean
  promoteKnowledgeVersion: boolean
  onForceBacktestChange: (value: boolean) => void
  onRunEvaluationChange: (value: boolean) => void
  onPromoteKnowledgeVersionChange: (value: boolean) => void
  onCreateClosedLoop: () => void
  onMaterializeCurrent: () => void
}) {
  const steps = closedLoopResult?.steps?.length
    ? closedLoopResult.steps.map((step) => ({
      key: step.key,
      label: workflowStepLabel(step.key, step.label),
      status: step.status,
      detail: stringValue(step.ref_id) || statusLabel(step.status),
      note: step.note ? localizedText(step.note) : step.note,
      source: step.ref_id ? 'p2_closed_loop_sample' : '',
      source_timestamp: '',
      evidence_strength: closedLoopStepReviewStrength(step),
      missing_items: step.missing_items.length
        ? step.missing_items.map(localizedText)
        : (step.status === 'PASS' ? [] : [step.note ? localizedText(step.note) : statusLabel(step.status)]),
      next_action_label: step.next_action_label
        ? localizedText(step.next_action_label)
        : (step.status === 'PASS' ? 'No action required' : 'Review evidence'),
    }))
    : workflowState?.steps?.length
    ? workflowState.steps.map((step) => ({
      ...step,
      label: workflowStepLabel(step.key, step.label),
      detail: localizedText(step.detail),
      note: '',
      source: step.source ?? '',
      source_timestamp: step.source_timestamp ?? '',
      evidence_strength: workflowReviewStrength(step.evidence_strength),
      missing_items: (step.missing_items ?? []).map(localizedText),
      next_action_label: step.next_action_label ? localizedText(step.next_action_label) : '',
    }))
    : []
  const guideLabel = workflowState ? workflowNextActionLabel(workflowState, iteration) : '等待后端 workflow_state'
  const blockingReasons = (workflowState?.blocking_reasons ?? []).map(localizedText)
  const maturityLabel = workflowState?.maturity_label ? localizedText(workflowState.maturity_label) : 'Workflow state missing'
  const maturityLevel = workflowState?.maturity_level ?? 'workflow_state_missing'
  const maturityReasons = (workflowState?.maturity_reasons ?? []).map(localizedText)
  const workflowMissing = !closedLoopResult?.steps?.length && !workflowState?.steps?.length

  return (
    <Card
      title="P2 闭环向导"
      action={<Badge status={workflowState ? statusBadge(workflowState.stage) : 'WARN'}>{workflowState ? `${Math.round(workflowState.maturity_score)}%` : 'workflow_state 缺失'}</Badge>}
    >
      <div className="mb-4 rounded-md border border-cyan-200 bg-cyan-50 px-4 py-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-xs font-semibold uppercase tracking-wider text-cyan-700">下一步</div>
            <div className="mt-1 text-sm font-semibold text-slate-950">{guideLabel}</div>
            <div data-testid="workflow-maturity-level" className="mt-1 text-xs text-cyan-800">
              Maturity: {maturityLabel} / {maturityLevel}
            </div>
            {writeDisabledReason ? (
              <div data-testid="research-closed-loop-secondary-disabled-reason" className="mt-2 text-xs text-amber-700">
                {writeDisabledReason}
              </div>
            ) : null}
          </div>
          <Badge status={blockingReasons.length || workflowMissing ? 'WARN' : 'PASS'}>{workflowStageLabel(workflowState?.stage ?? 'workflow_state_missing')}</Badge>
        </div>
        {maturityReasons.length ? (
          <div className="mt-2 flex flex-wrap gap-2 text-xs text-cyan-800">
            {maturityReasons.slice(0, 3).map((reason) => (
              <span key={reason} data-testid="workflow-maturity-reason" className="rounded-md border border-cyan-200 bg-white/70 px-2 py-1">{reason}</span>
            ))}
          </div>
        ) : null}
        {blockingReasons.length ? (
          <div className="mt-2 flex flex-wrap gap-2 text-xs text-amber-800">
            {blockingReasons.slice(0, 3).map((reason) => (
              <span key={reason} data-testid="workflow-blocking-reason" className="rounded-md border border-amber-200 bg-amber-50 px-2 py-1">{reason}</span>
            ))}
          </div>
        ) : (
          <div className="mt-2 text-xs text-cyan-800">{workflowMissing ? '后端 workflow_state 暂不可用；不会使用前端本地规则推断成熟度。' : '当前没有后端标记的阻塞原因。'}</div>
        )}
      </div>
      <div className="grid gap-4 xl:grid-cols-[1fr_auto]">
        <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
          {steps.length ? steps.map((step) => {
            const missingItems = step.missing_items ?? []
            const sourceTimestamp = step.source_timestamp ? formatDateTime(step.source_timestamp) : ''
            const nextLabel = step.next_action_label ? localizedText(step.next_action_label) : ''
            return (
              <div key={step.key} data-testid={`workflow-step-${step.key}`} className={`rounded-md border p-3 ${closedLoopStepClass(step.status)}`}>
                <div className="flex items-center justify-between gap-2">
                  <div className="text-sm font-semibold text-slate-950">{step.label}</div>
                  {step.status === 'PASS' ? <CheckCircle2 size={15} className="text-emerald-600" /> : <AlertTriangle size={15} className="text-amber-600" />}
                </div>
                {step.key === 'backtest' && step.detail.startsWith('BT_') ? (
                  <Link
                    to={iteration ? researchBacktestPath(iteration, step.detail) : `/research-lab/backtest?run_id=${encodeURIComponent(step.detail)}`}
                    data-testid="workflow-backtest-link"
                    className="mt-2 block truncate text-xs font-medium text-cyan-700 hover:text-cyan-900"
                    title={step.detail}
                  >
                    {step.detail}
                  </Link>
                ) : (
                  <div data-testid={`workflow-step-${step.key}-detail`} className="mt-2 truncate text-xs text-slate-500" title={step.detail}>{step.detail}</div>
                )}
                {(step.source || sourceTimestamp || step.evidence_strength) ? (
                  <div data-testid={`workflow-step-${step.key}-meta`} className="mt-2 flex flex-wrap gap-1 text-[11px] leading-4 text-slate-600">
                    {step.source ? <span data-testid={`workflow-step-${step.key}-source`} className="rounded bg-white/70 px-1.5 py-0.5">source: {step.source}</span> : null}
                    {sourceTimestamp ? <span data-testid={`workflow-step-${step.key}-timestamp`} className="rounded bg-white/70 px-1.5 py-0.5">{sourceTimestamp}</span> : null}
                    {step.evidence_strength ? <span data-testid={`workflow-step-${step.key}-strength`} className="rounded bg-white/70 px-1.5 py-0.5">strength: {qualityLabel(step.evidence_strength)}</span> : null}
                  </div>
                ) : null}
                {missingItems.length ? (
                  <div data-testid={`workflow-step-${step.key}-missing`} className="mt-2 line-clamp-2 text-[11px] leading-4 text-amber-700">
                    missing: {missingItems.slice(0, 2).join(' / ')}
                  </div>
                ) : null}
                {nextLabel ? (
                  <div data-testid={`workflow-step-${step.key}-next`} className="mt-1 truncate text-[11px] leading-4 text-slate-500" title={nextLabel}>
                    next: {nextLabel}
                  </div>
                ) : null}
                {step.note ? <div className="mt-1 line-clamp-2 text-[11px] leading-4 text-slate-500">{step.note}</div> : null}
              </div>
            )
          }) : (
            <div data-testid="workflow-empty-state" className="rounded-md border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-800 md:col-span-3 xl:col-span-6">
              后端 workflow_state 暂不可用，闭环步骤和成熟度等待后端返回。
            </div>
          )}
        </div>
        <div className="flex min-w-[220px] flex-col gap-3">
          <label className="inline-flex items-center gap-2 text-xs font-medium text-slate-600">
            <input
              type="checkbox"
              checked={forceBacktest}
              onChange={(event) => onForceBacktestChange(event.target.checked)}
              disabled={saving}
              title={writeDisabledReason || undefined}
              className="h-4 w-4 rounded border-slate-300 text-cyan-600 disabled:opacity-50"
            />
            重建回测
          </label>
          <label className="inline-flex items-center gap-2 text-xs font-medium text-slate-600">
            <input
              type="checkbox"
              checked={runEvaluation}
              onChange={(event) => onRunEvaluationChange(event.target.checked)}
              disabled={saving}
              title={writeDisabledReason || undefined}
              className="h-4 w-4 rounded border-slate-300 text-cyan-600 disabled:opacity-50"
            />
            生成评估
          </label>
          <label className="inline-flex items-center gap-2 text-xs font-medium text-slate-600">
            <input
              type="checkbox"
              checked={promoteKnowledgeVersion}
              onChange={(event) => onPromoteKnowledgeVersionChange(event.target.checked)}
              disabled={!runEvaluation || saving}
              title={writeDisabledReason || undefined}
              className="h-4 w-4 rounded border-slate-300 text-cyan-600 disabled:opacity-50"
            />
            发布知识版本
          </label>
          <button
            type="button"
            data-testid="research-create-closed-loop-sample-secondary"
            onClick={onCreateClosedLoop}
            disabled={saving || closedLoopCreating}
            title={writeDisabledReason || undefined}
            className="inline-flex items-center justify-center gap-2 rounded-md bg-slate-900 px-3 py-2 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-60"
          >
            <Sparkles size={15} />
            {closedLoopCreating ? '生成中...' : '生成闭环样例'}
          </button>
          <button
            type="button"
            data-testid="research-materialize-current-artifacts"
            onClick={onMaterializeCurrent}
            disabled={saving || artifactLoading || !iteration}
            title={writeDisabledReason || undefined}
            className="inline-flex items-center justify-center gap-2 rounded-md border border-cyan-300 bg-white px-3 py-2 text-sm font-semibold text-cyan-800 hover:bg-cyan-50 disabled:opacity-60"
          >
            <BookOpen size={15} />
            {artifactLoading ? '补齐中...' : '补齐当前资产'}
          </button>
        </div>
      </div>
      {(closedLoopResult?.warnings?.length || sampleResult?.missing_reasons?.length) ? (
        <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">
          {(closedLoopResult?.warnings?.length ? closedLoopResult.warnings : sampleResult?.missing_reasons ?? []).slice(0, 3).join(' / ')}
        </div>
      ) : null}
    </Card>
  )
}

function WorkflowNextActionPanel({
  workflowState,
  fallbackBlockingReasons,
}: {
  workflowState: ResearchWorkflowState | null
  fallbackIteration: ResearchIteration | null
  fallbackBlockingReasons?: string[]
}) {
  const blockingReasons = dedupeStrings(workflowState?.blocking_reasons ?? fallbackBlockingReasons ?? [])
  const nextActionLabel = workflowState ? workflowNextActionLabel(workflowState, null) : '等待后端 workflow_state'
  const stage = workflowState?.stage || 'workflow_state_missing'
  const helper = workflowState
    ? '由后端工作流状态驱动'
    : blockingReasons.length
      ? '后端 workflow_state 暂不可用；以下阻塞原因来自后端 verdict inputs'
      : '后端 workflow_state 暂不可用；不会使用前端本地规则推断成熟度'

  return (
    <div className="rounded-md border border-cyan-200 bg-cyan-50 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-xs font-semibold text-cyan-700">工作流向导</div>
          <div className="mt-1 text-sm font-semibold text-slate-950">下一步：{nextActionLabel}</div>
          <div className="mt-1 text-xs text-slate-600">{helper}</div>
        </div>
        <Badge status={blockingReasons.length ? 'WARN' : statusBadge(stage)}>{workflowStageLabel(stage)}</Badge>
      </div>
      {blockingReasons.length ? (
        <div className="mt-3 space-y-2">
          <div className="text-xs font-semibold text-amber-800">阻塞原因</div>
          <div className="flex flex-wrap gap-2">
            {blockingReasons.slice(0, 4).map((reason) => (
              <span key={reason} className="rounded-md border border-amber-200 bg-white px-2 py-1 text-xs text-amber-800">{localizedText(reason)}</span>
            ))}
          </div>
        </div>
      ) : (
        <div className="mt-3 text-xs text-cyan-800">
          {workflowState ? '没有阻塞原因，按上面的下一步按钮继续推进。' : '后端 workflow_state 暂不可用；暂无 verdict inputs 阻塞原因。'}
        </div>
      )}
    </div>
  )
}

function fallbackNextActionLabel(iteration: ResearchIteration | null) {
  if (!iteration) return '点击“创建下一轮”或“生成闭环样例”建立第一条研究轮次'
  const metrics = iteration.metrics ?? {}
  const artifactLinks = metrics.artifact_links && typeof metrics.artifact_links === 'object'
    ? metrics.artifact_links as Record<string, unknown>
    : {}
  if (!iteration.linked_run_id) return '点击“创建关联运行”生成实验证据'
  if (!iteration.linked_backtest_id) return '点击“关联回测”或“生成闭环样例”补齐回测'
  if (!iteration.linked_knowledge_item_id && !artifactLinks.knowledge_item_id) return '点击“补齐当前资产”生成 case、knowledge、patch 和 evaluation'
  if (['PENDING', 'REVIEWED', 'NEEDS_MORE_DATA'].includes(iteration.verdict)) return '点击“发送到反馈”或选择接受/需要补丁/拒绝'
  return '点击“Next from current”进入下一轮研究'
}

function closedLoopStepClass(status: string) {
  if (status === 'PASS') return 'border-emerald-200 bg-emerald-50/70'
  if (status === 'WARN') return 'border-amber-200 bg-amber-50/70'
  if (status === 'FAIL') return 'border-red-200 bg-red-50/70'
  return 'border-slate-200 bg-slate-50'
}

type MaterialTone = 'primary' | 'neutral' | 'success' | 'warning' | 'danger' | 'info' | 'data'

function materialToneForStatus(status: string): MaterialTone {
  const normalized = status.toUpperCase()
  if (['PASS', 'ACTIVE', 'ACCEPTED', 'READY', 'COMPLETED'].includes(normalized)) return 'success'
  if (['FAIL', 'REJECTED', 'REGRESSED', 'GUARDRAIL_BLOCKED'].includes(normalized)) return 'danger'
  if (['WARN', 'PATCH_REQUIRED', 'NEEDS_MORE_DATA', 'PAUSED'].includes(normalized)) return 'warning'
  if (['RUNNING', 'REVIEWED'].includes(normalized)) return 'info'
  return 'neutral'
}

function evidenceStrengthForStatus(status: string): number {
  const normalized = status.toUpperCase()
  if (['PASS', 'ACTIVE', 'ACCEPTED', 'READY', 'COMPLETED'].includes(normalized)) return 100
  if (['WARN', 'PATCH_REQUIRED', 'NEEDS_MORE_DATA', 'PAUSED'].includes(normalized)) return 62
  if (['FAIL', 'REJECTED', 'REGRESSED', 'GUARDRAIL_BLOCKED'].includes(normalized)) return 35
  return 25
}

function evidenceStrengthForQuality(quality: string): number {
  const normalized = workflowReviewStrength(quality)
  if (normalized === 'MEDIUM') return 68
  if (normalized === 'LOW') return 35
  if (normalized === 'MISSING') return 18
  if (normalized === 'PENDING' || normalized === 'UNKNOWN') return 45
  return 35
}

function qualityBadgeStatus(quality: string): string {
  const normalized = workflowReviewStrength(quality)
  if (normalized === 'MEDIUM') return 'WARN'
  if (['LOW', 'MISSING'].includes(normalized)) return 'FAIL'
  return 'WAIT'
}

function reportedEvidenceQuality(item: { reportedQuality?: string | null; reported_quality?: string | null }) {
  return stringValue(item.reportedQuality) ?? stringValue(item.reported_quality)
}

function evidenceAuditDetail(item: {
  source_id: string
  summary?: string
  quality: string
  reportedQuality?: string | null
  reported_quality?: string | null
}) {
  const detail = item.summary || item.source_id
  const reported = reportedEvidenceQuality(item)
  if (!reported || reported.toUpperCase() === item.quality.toUpperCase()) return detail
  return `${detail} · reportedQuality=${qualityLabel(reported)} -> review_gate=${qualityLabel(workflowReviewStrength(item.quality))}`
}

function GuidedHypothesisPanel({
  result,
  error,
  loading,
  saving,
  useLlm,
  maxDrafts,
  hasIteration,
  onUseLlmChange,
  onMaxDraftsChange,
  onGenerate,
  onApply,
  onConfirm,
  confirmingIndex,
}: {
  result: ResearchHypothesisDraftResponse | null
  error: string | null
  loading: boolean
  saving: boolean
  useLlm: boolean
  maxDrafts: number
  hasIteration: boolean
  onUseLlmChange: (value: boolean) => void
  onMaxDraftsChange: (value: number) => void
  onGenerate: () => void
  onApply: (draft: ResearchHypothesisDraft) => void
  onConfirm: (index: number) => void
  confirmingIndex: number | null
}) {
  const selection = result?.action_selection
  const actionTarget = selectionString(selection, 'action_target') || selectionString(selection, 'target') || selectionString(selection, 'actionTarget') || '-'
  const ruleId = selectionString(selection, 'rule_id') || selectionString(selection, 'ruleId') || '-'
  const reason = selectionString(selection, 'reason') || '-'
  const selectionEvidence = normalizeStringList(selection?.evidence)
  const promptProvenance = result?.prompt_provenance ? compactRecordText(result.prompt_provenance) : '-'
  const tokenUsageHref = result?.token_usage_link || '/debate'

  return (
    <Card title="引导式假设生成">
      <div className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-3">
            <label className="inline-flex items-center gap-2 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={useLlm}
                onChange={(event) => onUseLlmChange(event.target.checked)}
                className="h-4 w-4 rounded border-slate-300 text-slate-900"
              />
              use_llm
            </label>
            <label className="inline-flex items-center gap-2 text-sm text-slate-700">
              max_drafts
              <input
                type="number"
                min={1}
                max={5}
                value={maxDrafts}
                onChange={(event) => onMaxDraftsChange(clampDraftCount(event.target.value))}
                className="w-16 rounded-md border border-slate-200 px-2 py-1 text-sm"
              />
            </label>
            <Badge status={hasIteration ? 'PASS' : 'WAIT'}>{hasIteration ? 'iteration context' : 'loop context'}</Badge>
          </div>
          <button type="button" onClick={onGenerate} disabled={loading || saving} className="inline-flex items-center gap-2 rounded-md bg-cyan-700 px-3 py-2 text-sm font-semibold text-white hover:bg-cyan-800 disabled:opacity-60">
            <Sparkles size={15} />
            {loading ? 'Generating...' : 'Generate hypothesis'}
          </button>
        </div>

        {error ? (
          <div className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</div>
        ) : null}

        {result ? (
          <div className="space-y-4">
            <div className="grid gap-3 md:grid-cols-3">
              <div className="min-w-0 rounded-md border border-slate-200 bg-slate-50 p-3">
                <div className="text-xs font-semibold uppercase text-slate-500">动作目标</div>
                <div className="mt-1 break-words text-sm font-semibold text-slate-950">{actionTarget}</div>
              </div>
              <div className="min-w-0 rounded-md border border-slate-200 bg-slate-50 p-3">
                <div className="text-xs font-semibold uppercase text-slate-500">规则 ID</div>
                <div className="mt-1 break-words text-sm font-semibold text-slate-950">{ruleId}</div>
              </div>
              <div className="min-w-0 rounded-md border border-slate-200 bg-slate-50 p-3">
                <div className="text-xs font-semibold uppercase text-slate-500">LLM 状态</div>
                <div className="mt-1 flex flex-wrap items-center gap-2">
                  <Badge status={result.llm_error ? 'FAIL' : useLlm ? 'PASS' : 'READ_ONLY'}>{result.llm_status || (useLlm ? 'UNKNOWN' : 'OFF')}</Badge>
                  <TokenUsageLink href={tokenUsageHref} />
                </div>
              </div>
            </div>

            <div className="grid gap-3 md:grid-cols-2">
              <div className="min-w-0 rounded-md border border-slate-200 p-3">
                <div className="text-xs font-semibold uppercase text-slate-500">原因</div>
                <div className="mt-1 max-h-20 overflow-y-auto break-words text-sm text-slate-700">{reason}</div>
              </div>
              <div className="min-w-0 rounded-md border border-slate-200 p-3">
                <div className="text-xs font-semibold uppercase text-slate-500">证据</div>
                {selectionEvidence.length ? (
                  <div className="mt-2 flex max-h-20 flex-wrap gap-2 overflow-y-auto">
                    {selectionEvidence.slice(0, 6).map((item) => (
                      <span key={item} className="max-w-full break-words rounded bg-slate-100 px-2 py-1 text-xs text-slate-600">{item}</span>
                    ))}
                  </div>
                ) : (
                  <div className="mt-1 text-sm text-slate-500">-</div>
                )}
              </div>
            </div>

            {result.llm_error ? (
              <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
                LLM error: {result.llm_error}
              </div>
            ) : null}

            <div className="flex flex-wrap gap-2 text-xs text-slate-500">
              <span className="rounded bg-slate-100 px-2 py-1">token: {formatTokenUsage(result.token_usage)}</span>
              <span className="rounded bg-slate-100 px-2 py-1">prompt: {promptProvenance}</span>
              <span className="rounded bg-slate-100 px-2 py-1">draft: {result.draft_id}</span>
              <span className="rounded bg-slate-100 px-2 py-1">confirmation_required: {String(result.confirmation_required)}</span>
              {result.confirmed_iteration_id ? <span className="rounded bg-emerald-100 px-2 py-1 text-emerald-700">confirmed: {result.confirmed_iteration_id}</span> : null}
              <span className={`rounded px-2 py-1 ${result.auto_run_started ? 'bg-rose-100 text-rose-700' : 'bg-slate-100'}`}>auto_run_started: {String(result.auto_run_started)}</span>
              <span className="rounded bg-slate-100 px-2 py-1">{formatDateTime(result.created_at)}</span>
            </div>

            <div className="space-y-3">
              <div className="text-sm font-semibold text-slate-950">Drafts / 草稿</div>
              {result.drafts.length ? (
                <div className="max-h-96 space-y-3 overflow-y-auto pr-1">
                  {result.drafts.map((draft, index) => {
                    const fields = normalizeDraftFields(draft, selection)
                    const draftEvidence = normalizeStringList(draft.evidence)
                    return (
                      <div key={draft.draft_id || `${index}-${fields.hypothesis}`} className="rounded-md border border-slate-200 p-4">
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <div className="min-w-0 flex-1">
                            <div className="break-words text-sm font-semibold text-slate-950">{fields.hypothesis || `Draft ${index + 1}`}</div>
                            {fields.plan ? <div className="mt-2 max-h-24 overflow-y-auto break-words text-sm text-slate-600">{fields.plan}</div> : null}
                          </div>
                          <div className="flex shrink-0 flex-wrap gap-2">
                            <button type="button" onClick={() => onApply(draft)} className="inline-flex items-center gap-2 rounded-md border border-cyan-300 bg-white px-3 py-2 text-xs font-semibold text-cyan-800 hover:bg-cyan-50">
                              <CheckCircle2 size={13} />
                              应用到表单
                            </button>
                            <button
                              type="button"
                              onClick={() => onConfirm(index)}
                              disabled={saving || loading || confirmingIndex !== null || !result.confirmation_required}
                              className="inline-flex items-center gap-2 rounded-md bg-slate-900 px-3 py-2 text-xs font-semibold text-white hover:bg-slate-800 disabled:opacity-60"
                            >
                              <GitBranch size={13} />
                              {confirmingIndex === index ? '确认中...' : '确认生成轮次'}
                            </button>
                          </div>
                        </div>
                        <div className="mt-3 flex flex-wrap gap-2">
                          {fields.modules.map((module) => (
                            <span key={module} className="max-w-full break-words rounded bg-slate-100 px-2 py-1 text-xs text-slate-600">{module}</span>
                          ))}
                        </div>
                        {draftEvidence.length ? (
                          <div className="mt-3 flex max-h-16 flex-wrap gap-2 overflow-y-auto">
                            {draftEvidence.slice(0, 5).map((item) => (
                              <span key={item} className="max-w-full break-words rounded border border-slate-200 px-2 py-1 text-xs text-slate-500">{item}</span>
                            ))}
                          </div>
                        ) : null}
                      </div>
                    )
                  })}
                </div>
              ) : (
                <div className="rounded-md border border-dashed border-slate-200 p-4 text-sm text-slate-500">暂无草稿返回。</div>
              )}
            </div>
          </div>
        ) : (
          <div className="rounded-md border border-dashed border-slate-200 p-4 text-sm text-slate-500">
            Draft-only generation does not start a run. Confirm a draft to create a linked research iteration with provenance, or apply it to the form for manual editing.
          </div>
        )}
      </div>
    </Card>
  )
}

function TokenUsageLink({ href }: { href: string }) {
  const content = (
    <>
      <ExternalLink size={13} />
      Token usage
    </>
  )
  if (/^https?:\/\//i.test(href)) {
    return <a href={href} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs font-semibold text-cyan-700 hover:text-cyan-900">{content}</a>
  }
  return <Link to={href} className="inline-flex items-center gap-1 text-xs font-semibold text-cyan-700 hover:text-cyan-900">{content}</Link>
}

function buildArtifactChainGovernance(
  iteration: ResearchIteration,
  artifactIds: {
    caseId?: string
    knowledgeId?: string
    errorId?: string
    patchId?: string
    evaluationId?: string
    requiresError: boolean
    requiresPatch: boolean
    assetsComplete: boolean
  },
) {
  const metrics = iteration.metrics ?? {}
  const simulationOnly = metrics.simulation_only === false ? false : true
  const isRealTrade = metrics.is_real_trade === true
  const evidenceUsage = stringValue(metrics.artifact_chain_evidence_usage) ?? 'review_gate_only'
  const strongConclusionAllowed = metrics.artifact_chain_strong_conclusion_allowed === true
  const boundaryBroken = !simulationOnly || isRealTrade || evidenceUsage !== 'review_gate_only' || strongConclusionAllowed
  const hasIds = Boolean(iteration.loop_id && iteration.iteration_id)

  let blocker = '无阻断，保持人工复核'
  if (boundaryBroken) {
    blocker = 'Research artifact chain simulation-only boundary violated'
  } else if (!hasIds) {
    blocker = '缺少 loop/iteration ID'
  } else if (!artifactIds.caseId) {
    blocker = '缺少 case artifact'
  } else if (!artifactIds.knowledgeId) {
    blocker = '缺少 knowledge artifact'
  } else if (artifactIds.requiresError && !artifactIds.errorId) {
    blocker = '需要 error ledger 但缺少 error artifact'
  } else if (artifactIds.requiresPatch && !artifactIds.patchId) {
    blocker = '需要 patch 但缺少 patch artifact'
  } else if (artifactIds.patchId && !artifactIds.evaluationId) {
    blocker = '补丁未评估'
  } else if (!artifactIds.assetsComplete) {
    blocker = '资产链尚未补齐'
  }

  const nextAction = boundaryBroken
    ? '停止沉淀，先修复 Research Lab simulation-only 边界'
    : !hasIds
      ? '补齐 loop/iteration 链接后再生成资产'
      : !artifactIds.caseId || !artifactIds.knowledgeId || (artifactIds.requiresError && !artifactIds.errorId) || (artifactIds.requiresPatch && !artifactIds.patchId)
        ? '补齐 case / knowledge / patch / error 链接'
        : artifactIds.patchId && !artifactIds.evaluationId
          ? '运行补丁评估后再进入 Knowledge Version'
          : '保留资产链，进入反馈或知识版本复核'

  return {
    contextId: iteration.iteration_id || iteration.loop_id || 'pending-research-artifact-chain',
    evidenceStrength: 'LOW',
    blocker,
    nextAction,
    simulationOnly,
    isRealTrade,
    evidenceUsage,
    strongConclusionAllowed,
  }
}

function ArtifactActionsPanel({
  iteration,
  loading,
  saving,
  onMaterialize,
  onMaterializeAndEvaluate,
}: {
  iteration: ResearchIteration
  loading: boolean
  saving: boolean
  onMaterialize: () => void
  onMaterializeAndEvaluate: () => void
}) {
  const artifactLinks = (
    iteration.metrics?.artifact_links && typeof iteration.metrics.artifact_links === 'object'
      ? iteration.metrics.artifact_links
      : {}
  ) as Record<string, unknown>
  const caseId = iteration.linked_case_id || stringValue(artifactLinks.case_id)
  const knowledgeId = iteration.linked_knowledge_item_id || stringValue(artifactLinks.knowledge_item_id)
  const errorId = stringValue(artifactLinks.error_entry_id)
  const patchId = iteration.linked_patch_id || stringValue(artifactLinks.patch_id)
  const evaluationId = stringValue(artifactLinks.evaluation_id)
  const hasArtifacts = Boolean(caseId || knowledgeId || errorId || patchId || evaluationId)
  const verdicts = [
    iteration.verdict,
    iteration.status,
    stringValue(iteration.metrics?.engine_verdict),
    stringValue(iteration.metrics?.suggested_feedback_verdict),
  ].map((item) => (item || '').toUpperCase()).filter(Boolean)
  const requiresPatch = verdicts.some((item) => ['ACCEPTED', 'ACCEPT', 'PATCH_REQUIRED', 'REGRESSED', 'GUARDRAIL_BLOCKED'].includes(item))
  const requiresError = verdicts.some((item) => ['REJECTED', 'REJECT', 'PATCH_REQUIRED', 'REGRESSED', 'GUARDRAIL_BLOCKED'].includes(item))
  const assetsComplete = Boolean(caseId && knowledgeId && (!requiresError || errorId) && (!requiresPatch || patchId))
  const canEvaluate = Boolean(patchId && !evaluationId)
  const materializeLabel = assetsComplete ? '资产已生成' : hasArtifacts ? '补齐资产' : '生成资产'
  const evaluateLabel = evaluationId ? '已评估' : patchId ? '生成并评估' : '先生成补丁'
  const artifactGovernance = buildArtifactChainGovernance(iteration, {
    caseId,
    knowledgeId,
    errorId,
    patchId,
    evaluationId,
    requiresError,
    requiresPatch,
    assetsComplete,
  })

  return (
    <div className="rounded-md border border-cyan-200 bg-cyan-50 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-slate-950">闭环资产</div>
          <div className="mt-1 text-xs text-slate-600">{'loop -> iteration -> run -> evidence -> case/knowledge -> patch -> evaluation -> feedback'}</div>
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={onMaterialize} disabled={loading || saving || assetsComplete} className="inline-flex items-center gap-2 rounded-md bg-cyan-700 px-3 py-2 text-xs font-semibold text-white hover:bg-cyan-800 disabled:opacity-60">
            <Archive size={13} />
            {materializeLabel}
          </button>
          <button type="button" onClick={onMaterializeAndEvaluate} disabled={loading || saving || !canEvaluate} className="inline-flex items-center gap-2 rounded-md border border-cyan-300 bg-white px-3 py-2 text-xs font-semibold text-cyan-800 hover:bg-cyan-100 disabled:opacity-60">
            <FlaskConical size={13} />
            {evaluateLabel}
          </button>
        </div>
      </div>

      <div data-testid={`research-artifact-chain-governance-${iteration.iteration_id}`} className="mt-3 grid gap-2 rounded-md border border-cyan-200 bg-white/80 p-3 text-xs text-slate-700 sm:grid-cols-2 xl:grid-cols-5">
        <span data-testid={`research-artifact-chain-id-${iteration.iteration_id}`} className="min-w-0 break-all">
          Iteration: {artifactGovernance.contextId}
        </span>
        <span data-testid={`research-artifact-chain-evidence-strength-${iteration.iteration_id}`} className="min-w-0 break-words">
          Evidence: {artifactGovernance.evidenceStrength}
        </span>
        <span data-testid={`research-artifact-chain-blocker-${iteration.iteration_id}`} className="min-w-0 break-words">
          Blocker: {artifactGovernance.blocker}
        </span>
        <span data-testid={`research-artifact-chain-next-action-${iteration.iteration_id}`} className="min-w-0 break-words">
          Next: {artifactGovernance.nextAction}
        </span>
        <span data-testid={`research-artifact-chain-simulation-boundary-${iteration.iteration_id}`} className="min-w-0 break-words font-medium text-slate-900">
          simulation_only={String(artifactGovernance.simulationOnly)} / is_real_trade={String(artifactGovernance.isRealTrade)} / evidence_usage={artifactGovernance.evidenceUsage} / strong_conclusion_allowed={String(artifactGovernance.strongConclusionAllowed)} / SIM_*
        </span>
      </div>

      {hasArtifacts ? (
        <div className="mt-3 grid gap-2 md:grid-cols-2">
          <ArtifactLink icon={Archive} label="案例" value={caseId} to="/research-lab/cases" />
          <ArtifactLink icon={BookOpen} label="知识" value={knowledgeId} to="/research-lab/knowledge" />
          <ArtifactLink icon={AlertTriangle} label="错误" value={errorId} to="/research-lab/cases" />
          <ArtifactLink icon={Wrench} label="补丁" value={patchId} to="/research-lab/cases" />
          <ArtifactLink icon={FlaskConical} label="评估" value={evaluationId} to="/research-lab/evaluation" />
        </div>
      ) : (
        <div className="mt-3 rounded-md border border-dashed border-cyan-300 bg-white/70 p-3 text-xs text-slate-600">
          当前轮次还没有派生资产。生成后会回写 case、knowledge、patch 和 evaluation 链接。
        </div>
      )}
    </div>
  )
}

function ArtifactLink({
  icon: Icon,
  label,
  value,
  to,
}: {
  icon: ElementType
  label: string
  value?: string
  to: string
}) {
  if (!value) {
    return (
      <div className="flex items-center gap-2 rounded-md border border-cyan-100 bg-white/70 px-3 py-2 text-xs text-slate-400">
        <Icon size={13} />
        <span>{label}: -</span>
      </div>
    )
  }
  return (
    <Link to={to} data-testid={`artifact-link-${label.toLowerCase()}`} className="flex min-w-0 items-center gap-2 rounded-md border border-cyan-100 bg-white px-3 py-2 text-xs text-slate-700 hover:bg-cyan-100">
      <Icon size={13} className="shrink-0" />
      <span className="font-semibold">{label}</span>
      <span className="truncate">{value}</span>
    </Link>
  )
}

function mfeMaeResearchFromRun(run: AnalysisRun | null): BottomResearchResult | null {
  if (!run) return null
  return run.mfeMaeResearch
    ?? run.bottomResearch
    ?? run.quantCore?.mfeMaeResearch
    ?? run.quantCore?.bottomResearch
    ?? null
}

function BottomResearchEvidencePanel({
  iteration,
  linkedRun,
  linkedRunLoading,
  linkedRunError,
  retrying,
  saving,
  onRetry,
}: {
  iteration: ResearchIteration
  linkedRun: AnalysisRun | null
  linkedRunLoading: boolean
  linkedRunError: string | null
  retrying: boolean
  saving: boolean
  onRetry: () => void
}) {
  const metrics = iteration.metrics ?? {}
  const bottom = mfeMaeResearchFromRun(linkedRun)
  const diagnostics = bottom?.modelDiagnostics ?? {}
  const walkForward = bottomWalkForward(bottom, metrics)
  const quantileCoverage = objectValue(walkForward.quantileCoverage)
  const conditionalEvaluation = objectValue(diagnostics.conditionalQuantileEvaluation)
  const conditionalTargetCoverage = objectValue(conditionalEvaluation.targetCoverage)
  const conditionalMfeCoverage = objectValue(conditionalTargetCoverage.mfe)
  const conditionalRankIc = objectValue(conditionalEvaluation.rankIc)
  const bottomStatus = stringValue(bottom?.status) ?? stringValue(metrics.mfe_mae_research_status ?? metrics.bottom_research_status)
  const repairProbability = metricNumberValue(bottom?.mfeFavorableProbability ?? bottom?.bottomRepairProbability ?? metrics.mfe_favorable_probability ?? metrics.bottom_repair_probability)
  const breakdownRisk = metricNumberValue(bottom?.maeBreachProbability ?? bottom?.breakdownRiskProbability ?? metrics.mae_breach_probability ?? metrics.breakdown_risk_probability)
  const evidenceGrade = stringValue(diagnostics.evidenceGrade) ?? stringValue(metrics.mfe_mae_research_evidence_grade ?? metrics.bottom_research_evidence_grade)
  const sampleCount = metricNumberValue(diagnostics.sampleCount ?? metrics.mfe_mae_research_sample_count ?? metrics.bottom_research_sample_count)
  const foldCount = metricNumberValue(walkForward.foldCount ?? metrics.bottom_research_fold_count)
  const rankIc = metricNumberValue(walkForward.rankIc ?? metrics.mfe_mae_rank_ic)
  const q80Coverage = metricNumberValue(quantileCoverage.q80Coverage ?? objectValue(quantileCoverage.q80).coverage)
  const q90Coverage = metricNumberValue(quantileCoverage.q90Coverage ?? objectValue(quantileCoverage.q90).coverage)
  const conditionalMfeQ80Coverage = metricNumberValue(conditionalMfeCoverage.q80Coverage ?? objectValue(conditionalMfeCoverage.q80).coverage)
  const conditionalMfeRankIc = metricNumberValue(conditionalRankIc.mfe)
  const sampleQualitySummary = compactResearchSampleQuality(conditionalEvaluation.sampleQuality ?? bottom?.sampleQuality ?? {})
  const leakagePolicy = stringValue(conditionalEvaluation.leakagePolicy ?? bottom?.leakagePolicy)
  const backtestId = stringValue(metrics.mfe_mae_research_backtest_id ?? metrics.bottom_research_backtest_id) ?? stringValue(iteration.linked_backtest_id)
  const warning = stringValue(metrics.mfe_mae_research_backtest_error ?? metrics.bottom_research_backtest_error) ?? stringValue(metrics.mfe_mae_research_backtest_warning ?? metrics.bottom_research_backtest_warning)
  const retryState = bottomResearchRetryState(linkedRun, linkedRunLoading, linkedRunError)
  const hasEvidence = Boolean(bottomStatus || repairProbability !== undefined || backtestId || warning)
  const probabilityRows = [
    { label: 'MFE 有利概率', value: normalizedProbabilityValue(repairProbability), helper: formatProbability(repairProbability), tone: 'positive' as const },
    { label: 'MAE 跌破风险', value: normalizedProbabilityValue(breakdownRisk), helper: formatProbability(breakdownRisk), tone: 'negative' as const },
    { label: 'Rank IC', value: normalizedSignedValue(rankIc), helper: formatDisplayMetricValue(rankIc ?? '-'), tone: 'data' as const },
    { label: 'CQ MFE Rank IC', value: normalizedSignedValue(conditionalMfeRankIc), helper: formatDisplayMetricValue(conditionalMfeRankIc ?? '-'), tone: 'data' as const },
  ]
  const calibrationRows = [
    {
      label: 'MAE coverage',
      cells: [
        { label: 'Q80', value: normalizedProbabilityValue(q80Coverage), helper: formatProbability(q80Coverage) },
        { label: 'Q90', value: normalizedProbabilityValue(q90Coverage), helper: formatProbability(q90Coverage) },
        { label: 'Fold', value: normalizedCountValue(foldCount, 10), helper: formatDisplayMetricValue(foldCount ?? '-') },
      ],
    },
    {
      label: 'CQ / sample',
      cells: [
        { label: 'MFE Q80', value: normalizedProbabilityValue(conditionalMfeQ80Coverage), helper: formatProbability(conditionalMfeQ80Coverage) },
        { label: 'Sample', value: normalizedCountValue(sampleCount, 100), helper: formatDisplayMetricValue(sampleCount ?? '-') },
        { label: 'Leakage', value: leakagePolicy ? 1 : 0, helper: leakagePolicy ? 'declared' : '-' },
      ],
    },
  ]

  return (
    <div className="border-t border-slate-200 pt-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-slate-950">MFE/MAE 路径研究证据</div>
          <div className="mt-1 text-xs text-slate-500">
            Supporting-only evidence; QIAM calibration is capped at one controlled step and cannot create executable trade action.
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {bottomStatus ? <Badge status={bottomStatus.toUpperCase() === 'PASS' ? 'PASS' : 'WARN'}>{bottomStatus}</Badge> : null}
          {backtestId ? (
            <Link
              to={researchBacktestPath(iteration, backtestId)}
              className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-2 py-1 text-xs font-semibold text-cyan-700 hover:bg-cyan-50"
            >
              回测 {backtestId}
              <ExternalLink size={12} />
            </Link>
          ) : null}
          <button
            type="button"
            onClick={onRetry}
            disabled={!retryState.canRetry || retrying || saving}
            className="inline-flex items-center gap-2 rounded-md border border-cyan-300 bg-white px-3 py-2 text-xs font-semibold text-cyan-800 hover:bg-cyan-50 disabled:opacity-60"
          >
            <RefreshCw size={13} className={retrying ? 'animate-spin' : ''} />
            重试 MFE/MAE 回测
          </button>
          {!retryState.canRetry ? (
            <div className="basis-full text-xs text-slate-500" data-testid="mfe-mae-retry-disabled-reason">
              重试已禁用：{retryState.reason}
            </div>
          ) : null}
        </div>
      </div>

      {hasEvidence ? (
        <div className="mt-3 space-y-3">
          <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(260px,0.9fr)]">
            <div className="rounded-md border border-slate-200 bg-white p-3">
              <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500">MFE/MAE direct labels</div>
              <FactorBarStack rows={probabilityRows} maxAbs={1} />
            </div>
            <div className="rounded-md border border-slate-200 bg-white p-3">
              <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500">Calibration matrix</div>
              <MatrixHeatmap rows={calibrationRows} />
            </div>
          </div>
          <div className="grid gap-3 md:grid-cols-4">
            <MetricPill label="证据等级" value={formatDisplayMetricValue(evidenceGrade ?? '-')} />
            <MetricPill label="样本数" value={formatDisplayMetricValue(sampleCount ?? '-')} />
            <MetricPill label="滚动前推折数" value={formatDisplayMetricValue(foldCount ?? '-')} />
            <MetricPill label="样本质量" value={sampleQualitySummary.summary} title={sampleQualitySummary.detail} />
            <MetricPill label="泄漏策略" value={leakagePolicy ? '已声明' : '-'} title={leakagePolicy || '-'} />
            <MetricPill label="信号数量" value={formatDisplayMetricValue(metrics.mfe_mae_research_signal_count ?? metrics.bottom_research_signal_count ?? '-')} />
          </div>
        </div>
      ) : (
        <div className="mt-3 text-xs text-slate-500">
          {linkedRunLoading ? '正在加载关联运行...' : '该轮次暂无可用的 MFE/MAE 路径研究输出。'}
        </div>
      )}

      {warning ? (
        <div className="mt-3 flex gap-2 rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
          <AlertTriangle size={13} className="mt-0.5 shrink-0" />
          <span>{localizedText(warning)}</span>
        </div>
      ) : null}
    </div>
  )
}

function MetricPill({ label, value, title }: { label: string; value: string; title?: string }) {
  return (
    <div className="min-w-0 border-l border-slate-200 pl-3">
      <div className="text-[11px] font-medium uppercase text-slate-400">{label}</div>
      <div className="mt-1 truncate text-sm font-semibold text-slate-900" title={title ?? value}>{value}</div>
    </div>
  )
}

function ClosureHealthSummaryPanel({
  iteration,
  linkedRun,
  linkedRunLoading,
  linkedRunError,
  inputs,
  workflowState,
}: {
  iteration: ResearchIteration
  linkedRun: AnalysisRun | null
  linkedRunLoading: boolean
  linkedRunError: string | null
  inputs: ResearchVerdictInputs | null
  workflowState: ResearchWorkflowState | null
}) {
  const metrics = inputs?.metrics ?? iteration.metrics ?? {}
  const artifactLinks = metrics.artifact_links && typeof metrics.artifact_links === 'object'
    ? metrics.artifact_links as Record<string, unknown>
    : {}
  const retryState = bottomResearchRetryState(linkedRun, linkedRunLoading, linkedRunError)
  const rawBacktestId = stringValue(metrics.mfe_mae_research_backtest_id ?? metrics.bottom_research_backtest_id)
    ?? stringValue(iteration.linked_backtest_id)
    ?? stringValue(artifactLinks.backtest_id)
    ?? stringValue(artifactLinks.backtest_run_id)
  const workflowBacktestStep = workflowState?.steps.find((step) => step.key === 'backtest')
  const workflowBacktestStatus = workflowBacktestStep?.status?.toUpperCase() ?? ''
  const workflowBacktestId = workflowBacktestStatus === 'PASS'
    ? stringValue(workflowBacktestStep?.ref_id)
    : undefined
  const backtestId = workflowState ? workflowBacktestId : rawBacktestId
  const backtestStatus = workflowBacktestStep?.status
    ?? (backtestId ? 'PASS' : 'WAIT')
  const backtestDetail = backtestId
    ?? (workflowBacktestStep?.missing_items?.[0] ? localizedText(workflowBacktestStep.missing_items[0]) : undefined)
    ?? (workflowBacktestStep?.detail ? localizedText(workflowBacktestStep.detail) : undefined)
    ?? (rawBacktestId ? `unverified: ${rawBacktestId}` : 'missing')
  const caseId = stringValue(iteration.linked_case_id) ?? stringValue(artifactLinks.case_id)
  const knowledgeId = stringValue(iteration.linked_knowledge_item_id)
    ?? stringValue(artifactLinks.knowledge_item_id)
    ?? stringValue(artifactLinks.knowledge_id)
  const workflowKnowledgeVersionId = stringValue(
    workflowState?.steps.find((step) => step.key === 'knowledge_version')?.ref_id
  )
  const knowledgeVersionId = stringValue(artifactLinks.knowledge_version_id)
    ?? stringValue(iteration.metrics?.knowledge_version_id)
    ?? workflowKnowledgeVersionId
    ?? stringValue(iteration.evidence_links.find((item) => item.source_type.toUpperCase() === 'KNOWLEDGE_VERSION')?.source_id)
  const evaluationId = stringValue(artifactLinks.evaluation_id)
    ?? stringValue(iteration.evidence_links.find((item) => item.source_type.toUpperCase() === 'EVALUATION')?.source_id)
  const warnings = dedupeStrings([
    ...(inputs?.blocking_reasons ?? []),
    ...(inputs?.quality_warnings ?? []),
    ...(workflowState?.blocking_reasons ?? []),
    ...normalizeStringList(metrics.blocking_reasons),
    ...normalizeStringList(metrics.quality_warnings),
    ...normalizeStringList(metrics.warnings),
  ].filter(Boolean))
  const nextAction = workflowNextActionLabel(workflowState, iteration)
  const currentStep = workflowCurrentStepLabel(workflowState)
  const evidenceStrength = researchLoopEvidenceStrengthLabel(workflowState, iteration, inputs)
  const blocker = researchLoopBlockerLabel(workflowState, warnings)
  const rows = [
    {
      key: 'run',
      label: 'Run',
      value: iteration.linked_run_id || 'missing',
      status: iteration.linked_run_id ? 'PASS' : 'WAIT',
    },
    {
      key: 'bottom',
      label: 'Usable MFE/MAE',
      value: retryState.canRetry ? 'ready' : retryState.reason,
      status: retryState.canRetry ? 'PASS' : (linkedRunLoading ? 'WAIT' : 'WARN'),
    },
    {
      key: 'backtest',
      label: '回测',
      value: backtestDetail,
      status: backtestStatus,
      href: backtestId ? researchBacktestPath(iteration, backtestId) : '',
    },
    {
      key: 'evidence',
      label: 'Evidence',
      value: `${iteration.evidence_links.length} links`,
      status: iteration.evidence_links.length ? 'PASS' : 'WAIT',
    },
    {
      key: 'case',
      label: 'Case',
      value: caseId || 'missing',
      status: caseId ? 'PASS' : 'WAIT',
    },
    {
      key: 'knowledge',
      label: 'Knowledge',
      value: knowledgeId || 'missing',
      status: knowledgeId ? 'PASS' : 'WAIT',
    },
    {
      key: 'knowledge_version',
      label: '知识版本',
      value: knowledgeVersionId || 'missing',
      status: knowledgeVersionId ? 'PASS' : 'WAIT',
    },
    {
      key: 'evaluation',
      label: 'Evaluation',
      value: evaluationId || 'missing',
      status: evaluationId ? 'PASS' : 'WAIT',
    },
    {
      key: 'next',
      label: 'Next action',
      value: nextAction,
      status: warnings.length ? 'WARN' : 'PASS',
    },
  ]

  return (
    <div className="rounded-md border border-slate-200 bg-white p-4" data-testid="closure-health-summary">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-slate-950">闭环健康摘要</div>
          <div className="mt-1 text-xs text-slate-500">
            当前轮次 ID、证据就绪状态、阻断原因、警告和下一步动作。
          </div>
        </div>
        <Badge status={warnings.length ? 'WARN' : 'PASS'}>
          {warnings.length ? `${warnings.length} warnings` : 'ready'}
        </Badge>
      </div>
      <div data-testid={`research-loop-governance-${iteration.iteration_id}`} className="mt-3 grid gap-2 rounded-md border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600 sm:grid-cols-2 xl:grid-cols-6">
        <span className="min-w-0 break-words">
          轮次 ID：
          <span data-testid={`research-loop-iteration-id-${iteration.iteration_id}`} className="break-all font-mono text-slate-500">{iteration.iteration_id}</span>
        </span>
        <span data-testid={`research-loop-current-step-${iteration.iteration_id}`} className="min-w-0 break-words">
          当前环节：{currentStep}
        </span>
        <span data-testid={`research-loop-evidence-strength-${iteration.iteration_id}`} className="min-w-0 break-words">
          证据强度：{evidenceStrength}
        </span>
        <span data-testid={`research-loop-blocker-${iteration.iteration_id}`} className="min-w-0 break-words">
          阻塞：{blocker}
        </span>
        <span data-testid={`research-loop-next-action-${iteration.iteration_id}`} className="min-w-0 break-words">
          下一步：{nextAction}
        </span>
        <span data-testid={`research-loop-simulation-boundary-${iteration.iteration_id}`} className="min-w-0 break-words font-medium text-slate-900">
          simulation_only={String(workflowState?.simulation_only ?? true)} / is_real_trade={String(workflowState?.is_real_trade ?? false)} / evidence_usage={workflowState?.evidence_usage ?? 'review_gate_only'} / strong_conclusion_allowed={String(workflowState?.strong_conclusion_allowed ?? false)} / SIM_*
        </span>
      </div>
      <EvidenceLedger
        className="mt-3"
        rows={rows.map((row) => ({
          label: row.href ? (
            <Link to={row.href} className="inline-flex items-center gap-1 text-cyan-700 hover:text-cyan-900">
              {row.label}
              <ExternalLink size={12} />
            </Link>
          ) : row.label,
          source: row.key,
          status: <Badge status={statusBadge(row.status)}>{statusLabel(row.status)}</Badge>,
          detail: row.value,
          strength: evidenceStrengthForStatus(row.status),
        }))}
      />
      {warnings.length > 0 ? (
        <div className="mt-3 flex flex-wrap gap-2 text-xs text-amber-800">
          {warnings.slice(0, 4).map((warning) => (
            <span key={warning} className="rounded-md border border-amber-200 bg-amber-50 px-2 py-1">
              {localizedText(warning)}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  )
}

function researchLoopEvidenceStrengthLabel(
  workflowState: ResearchWorkflowState | null,
  iteration: ResearchIteration,
  inputs: ResearchVerdictInputs | null,
) {
  if (!workflowState) return 'LOW：后端 workflow_state 缺失'
  const workflowStrength = workflowReviewStrength(workflowState.evidence_strength)
  if (workflowState.blocking_reasons.length > 0) return 'LOW：后端阻塞待处理'
  if (iteration.evidence_links.length === 0 && !(inputs?.evidence.length)) return 'LOW：无证据链接'
  const strengths = [
    workflowStrength,
    ...workflowState.steps.map((step) => step.evidence_strength),
    ...iteration.evidence_links.map((item) => item.quality),
    ...(inputs?.evidence.map((item) => item.quality) ?? []),
  ].map((item) => workflowReviewStrength(item))
  if (workflowState.steps.some((step) => step.missing_items.length > 0) || strengths.includes('MISSING')) return 'LOW：缺少闭环证据'
  if (strengths.length === 0) return 'LOW：无证据链接'
  if (strengths.some((item) => item !== 'MEDIUM')) return 'LOW：证据需复核'
  if (strengths.every((item) => item === 'MEDIUM')) return 'MEDIUM：后端证据可复核'
  return 'LOW：证据需复核'
}

function researchLoopBlockerLabel(workflowState: ResearchWorkflowState | null, warnings: string[]) {
  if (!workflowState) return '后端 workflow_state 缺失'
  const blocker = workflowState.blocking_reasons[0] ?? warnings[0]
  return blocker ? localizedText(blocker) : '无阻塞，按后端下一步推进'
}

function buildVerdictOverrideAudit(iteration: ResearchIteration, metrics: Record<string, unknown>) {
  if (metrics.verdict_gate_override !== true) return null
  const blockingReasons = normalizeStringList(metrics.verdict_gate_override_blocking_reasons)
  const qualityWarnings = normalizeStringList(metrics.verdict_gate_override_quality_warnings)
  const evidenceUsage = stringValue(metrics.verdict_gate_override_evidence_usage) ?? 'review_gate_only'
  const simulationOnly = metrics.verdict_gate_override_simulation_only === false ? false : true
  const isRealTrade = metrics.verdict_gate_override_is_real_trade === true
  const strongConclusionAllowed = metrics.verdict_gate_override_strong_conclusion_allowed === true
  const canAcceptFeedback = metrics.verdict_gate_override_can_accept_feedback === true
  const boundaryBroken = !simulationOnly || isRealTrade || strongConclusionAllowed || evidenceUsage !== 'review_gate_only'
  const blocker = blockingReasons[0]
    ?? qualityWarnings[0]
    ?? (canAcceptFeedback ? '人工覆盖已保留审计上下文' : '人工覆盖发生在 verdict gate 未允许接受时')
  const nextAction = boundaryBroken
    ? '停止沉淀，先修复人工覆盖的 simulation/review-gate 边界'
    : '复核 override reason、阻塞项和 evidence links 后再进入知识沉淀'
  const evidenceStrength = 'LOW'

  return {
    contextId: iteration.iteration_id,
    generatedAt: stringValue(metrics.verdict_gate_override_inputs_generated_at)
      ?? stringValue(metrics.verdict_inputs_generated_at)
      ?? '-',
    evidenceStrength,
    blocker,
    nextAction,
    simulationOnly,
    isRealTrade,
    evidenceUsage,
    strongConclusionAllowed,
    canAcceptFeedback,
  }
}

function VerdictInputsPanel({
  iteration,
  inputs,
  loading,
  saving,
  onRefresh,
  onSend,
}: {
  iteration: ResearchIteration
  inputs: ResearchVerdictInputs | null
  loading: boolean
  saving: boolean
  onRefresh: () => void
  onSend: () => void
}) {
  const metrics = inputs?.metrics ?? iteration.metrics ?? {}
  const overrideAudit = buildVerdictOverrideAudit(iteration, { ...(iteration.metrics ?? {}), ...metrics })
  const warnings = dedupeStrings([
    ...(inputs?.blocking_reasons ?? []),
    ...(inputs?.quality_warnings ?? []),
    ...((metrics.quality_warnings as string[] | undefined) ?? []),
    ...((metrics.warnings as string[] | undefined) ?? []),
    ...iteration.evidence_links
      .filter((item) => item.quality && !['HIGH', 'PASS'].includes(item.quality.toUpperCase()))
      .map((item) => `${item.source_type}:${item.source_id} quality=${item.quality}`),
  ].filter(Boolean))
  const rows = buildMetricRows(inputs, metrics)
  const evidence = inputs?.evidence ?? iteration.evidence_links.map((item) => ({
    ...item,
    summary: '',
    metrics: {},
  }))

  return (
    <div className="rounded-md border border-slate-200 bg-slate-50 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <Badge status={verdictStatus(inputs?.engine_verdict ?? iteration.verdict)}>
            {statusLabel(inputs?.engine_verdict ?? iteration.verdict)}
          </Badge>
          {inputs ? (
            <span className="text-xs text-slate-500">
              反馈：{statusLabel(inputs.suggested_feedback_verdict)} · 置信度 {Math.round(inputs.confidence * 100)}%
            </span>
          ) : (
            <span className="text-xs text-slate-500">{loading ? '正在加载反馈证据...' : '未加载反馈证据'}</span>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={onRefresh} disabled={loading || saving} className="inline-flex items-center gap-2 rounded-md border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-100 disabled:opacity-60">
            <RefreshCw size={13} />
            刷新
          </button>
          <button type="button" onClick={onSend} disabled={!inputs || loading || saving} className="inline-flex items-center gap-2 rounded-md bg-slate-900 px-3 py-2 text-xs font-semibold text-white hover:bg-slate-800 disabled:opacity-60">
            <Send size={13} />
            发送到反馈
          </button>
        </div>
      </div>

      {warnings.length > 0 ? (
        <div className="mt-3 space-y-1 rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
          {warnings.slice(0, 4).map((warning) => (
            <div key={warning} className="flex gap-2">
              <AlertTriangle size={13} className="mt-0.5 shrink-0" />
              <span>{localizedText(warning)}</span>
            </div>
          ))}
        </div>
      ) : null}

      {overrideAudit ? (
        <div data-testid={`research-verdict-override-governance-${iteration.iteration_id}`} className="mt-3 border-l-4 border-amber-400 bg-amber-50 px-3 py-3 text-xs text-amber-900">
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-6">
            <span data-testid={`research-verdict-override-id-${iteration.iteration_id}`} className="min-w-0 break-all">
              Iteration: {overrideAudit.contextId}
            </span>
            <span data-testid={`research-verdict-override-evidence-strength-${iteration.iteration_id}`} className="min-w-0 break-words">
              Evidence: {overrideAudit.evidenceStrength}
            </span>
            <span data-testid={`research-verdict-override-blocker-${iteration.iteration_id}`} className="min-w-0 break-words">
              Blocker: {localizedText(overrideAudit.blocker)}
            </span>
            <span data-testid={`research-verdict-override-next-action-${iteration.iteration_id}`} className="min-w-0 break-words">
              Next: {overrideAudit.nextAction}
            </span>
            <span className="min-w-0 break-words">
              can_accept_feedback={String(overrideAudit.canAcceptFeedback)} / evidence_usage={overrideAudit.evidenceUsage}
            </span>
            <span data-testid={`research-verdict-override-simulation-boundary-${iteration.iteration_id}`} className="min-w-0 break-words font-medium">
              simulation_only={String(overrideAudit.simulationOnly)} / is_real_trade={String(overrideAudit.isRealTrade)} / evidence_usage={overrideAudit.evidenceUsage} / strong_conclusion_allowed={String(overrideAudit.strongConclusionAllowed)} / SIM_* / generated_at={overrideAudit.generatedAt}
            </span>
          </div>
        </div>
      ) : null}

      <TableShell className="mt-3">
        <table className="institution-table">
          <thead>
            <tr>
              <th>指标</th>
              <th>基线</th>
              <th>当前</th>
              <th>质量</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.key}>
                <td className="font-medium text-slate-700">{metricLabel(row)}</td>
                <td>{formatDisplayMetricValue(row.baseline)}</td>
                <td className="font-semibold text-slate-900">{formatDisplayMetricValue(row.current)}</td>
                <td>{formatDisplayMetricValue(row.quality || row.warning || '-')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableShell>

      {evidence.length > 0 ? (
        <EvidenceLedger
          className="mt-3"
          rows={evidence.slice(0, 6).map((item) => ({
            label: item.label || item.source_id,
            source: evidenceSourceLabel(item.source_type),
            status: <Badge status={qualityBadgeStatus(item.quality)}>{qualityLabel(workflowReviewStrength(item.quality))}</Badge>,
            detail: evidenceAuditDetail(item),
            strength: evidenceStrengthForQuality(item.quality),
          }))}
        />
      ) : null}
    </div>
  )
}

function buildMetricRows(inputs: ResearchVerdictInputs | null, metrics: Record<string, unknown>): ResearchMetricComparisonRow[] {
  const comparison = inputs?.comparison?.slice(0, 6) ?? []
  if (comparison.length > 0) return comparison
  return [
    { key: 'quality_score', label: '质量分', baseline: '-', current: metrics.quality_score ?? '-', quality: String(metrics.quality_level ?? '') },
    { key: 'final_action', label: 'Final action', baseline: inputs?.baseline?.final_action ?? '-', current: metrics.final_action ?? inputs?.current?.final_action ?? '-' },
    { key: 'qiam_confidence', label: 'QIAM confidence', baseline: '-', current: metrics.qiam_confidence ?? '-' },
    { key: 'dvg_status', label: 'DVG status', baseline: '-', current: metrics.dvg_status ?? '-' },
    { key: 'backtest_return_pct', label: '回测收益', baseline: '-', current: metrics.backtest_return_pct ?? '-' },
    { key: 'evaluation_pass_rate', label: 'Eval pass rate', baseline: '-', current: metrics.evaluation_pass_rate ?? '-' },
  ]
}

function buildDraftContextMetrics(loop: ResearchLoop, iteration: ResearchIteration | null, inputs: ResearchVerdictInputs | null): Record<string, unknown> {
  return {
    loop_id: loop.loop_id,
    loop_status: loop.status,
    loop_action_target: loop.action_target,
    iteration_id: iteration?.iteration_id,
    iteration_status: iteration?.status,
    iteration_verdict: iteration?.verdict,
    current_metrics: inputs?.metrics ?? iteration?.metrics ?? {},
    baseline: inputs?.baseline ?? iteration?.metrics?.baseline ?? {},
    current: inputs?.current ?? iteration?.metrics?.current ?? {},
    comparison: inputs?.comparison ?? iteration?.metrics?.comparison ?? [],
    blocking_reasons: inputs?.blocking_reasons ?? iteration?.metrics?.blocking_reasons ?? [],
    quality_warnings: inputs?.quality_warnings ?? iteration?.metrics?.quality_warnings ?? [],
    evidence_links: inputs?.evidence ?? iteration?.evidence_links ?? [],
  }
}

function normalizeDraftFields(draft: ResearchHypothesisDraft, selection?: ResearchActionSelection) {
  const hypothesis = stringValue(draft.hypothesis)
    || stringValue(draft.title)
    || stringValue(draft.rationale)
    || stringValue(draft.reason)
    || ''
  const plan = draftPlanText(draft.plan ?? draft.experiment_plan ?? draft.experimentPlan)
  const actionTarget = stringValue(draft.action_target)
    || stringValue(draft.actionTarget)
    || selectionString(selection, 'action_target')
    || selectionString(selection, 'target')
  const modules = dedupeStrings([
    ...normalizeStringList(draft.target_modules),
    ...normalizeStringList(draft.targetModules),
    ...normalizeStringList(draft.modules),
  ])
  return {
    hypothesis,
    plan,
    modules: modules.length ? modules : modulesForActionTarget(actionTarget),
  }
}

function modulesForActionTarget(target?: string) {
  switch (target) {
    case 'factor':
      return ['factor_engine', 'qiam']
    case 'model':
      return ['qiam', 'evaluation']
    case 'signal':
      return ['signalops', 'qiam']
    case 'risk_rule':
      return ['risk_firewall', 'portfolio']
    case 'portfolio_rule':
      return ['portfolio', 'risk_firewall']
    case 'execution_rule':
      return ['execution', 'signalops']
    case 'data_quality_rule':
      return ['dvg_gate', 'market_data', 'data_pipeline']
    case 'prompt_rule':
      return ['final_writer', 'knowledge']
    default:
      return ['qiam', 'dvg_gate', 'signalops']
  }
}

function draftPlanText(value: unknown) {
  if (typeof value === 'string') return value
  if (value && typeof value === 'object') return JSON.stringify(value)
  return ''
}

function selectionString(selection: ResearchActionSelection | undefined, key: string) {
  if (!selection) return undefined
  return stringValue(selection[key])
}

function normalizeStringList(value: unknown): string[] {
  if (!value) return []
  if (Array.isArray(value)) return value.map(formatEvidenceValue).filter(Boolean)
  if (typeof value === 'string') return splitCsv(value)
  return [formatEvidenceValue(value)].filter(Boolean)
}

function formatEvidenceValue(value: unknown) {
  if (value === undefined || value === null || value === '') return ''
  if (typeof value === 'string') return value.trim()
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return JSON.stringify(value)
}

function compactRecordText(record: Record<string, unknown>) {
  const preferredKeys = ['profile_id', 'prompt_id', 'prompt_hash', 'source', 'mode', 'version', 'audit_id']
  const preferred = preferredKeys
    .map((key) => [key, record[key]] as const)
    .filter(([, value]) => value !== undefined && value !== null && value !== '')
  const entries = preferred.length ? preferred : Object.entries(record).slice(0, 3)
  if (!entries.length) return '-'
  return entries.map(([key, value]) => `${key}=${formatMetricValue(value)}`).join(', ')
}

function formatTokenUsage(value: unknown) {
  if (!value || typeof value !== 'object') return 'none'
  const record = value as Record<string, unknown>
  const totals = typeof record.totals === 'object' && record.totals !== null ? record.totals as Record<string, unknown> : {}
  const total = numberValue(record.total_tokens) ?? numberValue(totals.total_tokens)
  const prompt = numberValue(record.prompt_tokens) ?? numberValue(totals.prompt_tokens)
  const completion = numberValue(record.completion_tokens) ?? numberValue(totals.completion_tokens)
  if (total === undefined && prompt === undefined && completion === undefined) return compactRecordText(record)
  return `total=${total ?? '-'}, prompt=${prompt ?? '-'}, completion=${completion ?? '-'}`
}

function numberValue(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

function clampDraftCount(value: string) {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return 1
  return Math.max(1, Math.min(5, Math.floor(parsed)))
}

function verdictStatus(verdict: string) {
  if (['ACCEPT', 'ACCEPTED'].includes(verdict)) return 'PASS'
  if (['REJECT', 'REJECTED', 'REGRESSED', 'GUARDRAIL_BLOCKED'].includes(verdict)) return 'FAIL'
  if (['PATCH_REQUIRED', 'NEEDS_MORE_DATA'].includes(verdict)) return 'WARN'
  return 'WAIT'
}

function bottomResearchRetryState(run: AnalysisRun | null, linkedRunLoading: boolean, linkedRunError: string | null): { canRetry: boolean; reason: string } {
  if (linkedRunLoading) {
    return { canRetry: false, reason: 'Linked run is still loading.' }
  }
  if (linkedRunError) {
    return { canRetry: false, reason: `Linked run failed to load: ${linkedRunError}` }
  }
  if (!run) {
    return { canRetry: false, reason: 'No linked run is loaded for this iteration.' }
  }
  const bottom = mfeMaeResearchFromRun(run)
  if (!bottom) {
    return { canRetry: false, reason: '关联运行没有 MFE/MAE 路径研究输出。' }
  }
  const status = stringValue(bottom.status)?.toUpperCase()
  if (status !== 'PASS' && status !== 'WARN') {
    return { canRetry: false, reason: `MFE/MAE 路径研究状态为 ${status || 'missing'}，不是 PASS 或 WARN。` }
  }
  const provenance = bottom.provenance ?? {}
  const firstTradeDate = stringValue(provenance.firstTradeDate)
  const lastTradeDate = stringValue(provenance.lastTradeDate)
  if (!firstTradeDate && !lastTradeDate) {
    return { canRetry: false, reason: 'MFE/MAE 路径研究溯源缺少 firstTradeDate 和 lastTradeDate。' }
  }
  if (!firstTradeDate) {
    return { canRetry: false, reason: 'MFE/MAE 路径研究溯源缺少 firstTradeDate。' }
  }
  if (!lastTradeDate) {
    return { canRetry: false, reason: 'MFE/MAE 路径研究溯源缺少 lastTradeDate。' }
  }
  if (!stringValue(run.stockCode)) {
    return { canRetry: false, reason: 'Linked run is missing a stock code.' }
  }
  return { canRetry: true, reason: '' }
}

function bottomWalkForward(bottom: BottomResearchResult | null, metrics: Record<string, unknown>): Record<string, unknown> {
  const diagnostics = bottom?.modelDiagnostics ?? {}
  const mfeEval = diagnostics.mfeMaePathRiskEvaluation
  if (mfeEval && typeof mfeEval === 'object' && !Array.isArray(mfeEval)) {
    return {
      ...(mfeEval as Record<string, unknown>),
      foldCount: Array.isArray((mfeEval as Record<string, unknown>).folds) ? ((mfeEval as Record<string, unknown>).folds as unknown[]).length : undefined,
    }
  }
  const walkForward = diagnostics.walkForward as Record<string, unknown> | undefined
  const bottomRepair = walkForward?.bottomRepair
  if (bottomRepair && typeof bottomRepair === 'object' && !Array.isArray(bottomRepair)) {
    return bottomRepair as Record<string, unknown>
  }
  const metricWalk = metrics.mfe_mae_research_walk_forward ?? metrics.bottom_research_walk_forward
  if (metricWalk && typeof metricWalk === 'object' && !Array.isArray(metricWalk)) {
    return metricWalk as Record<string, unknown>
  }
  return {}
}

function metricNumberValue(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : undefined
  }
  return undefined
}

function normalizedProbabilityValue(value: unknown): number {
  const number = metricNumberValue(value)
  if (number === undefined) return 0
  const normalized = Math.abs(number) > 1 ? number / 100 : number
  return Math.max(0, Math.min(1, normalized))
}

function normalizedSignedValue(value: unknown): number {
  const number = metricNumberValue(value)
  if (number === undefined) return 0
  const normalized = Math.abs(number) > 1 ? number / 100 : number
  return Math.max(-1, Math.min(1, normalized))
}

function normalizedCountValue(value: unknown, denominator: number): number {
  const number = metricNumberValue(value)
  if (number === undefined || denominator <= 0) return 0
  return Math.max(0, Math.min(1, number / denominator))
}

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function compactResearchSampleQuality(value: unknown) {
  const sample = objectValue(value)
  if (!Object.keys(sample).length) return { summary: '-', detail: '-' }
  const status = stringValue(sample.status)
  const labeledCount = metricNumberValue(sample.labeledCount)
  const evaluatedCount = metricNumberValue(sample.evaluatedTestCount)
  const foldCount = metricNumberValue(sample.foldCount)
  const reasons = Array.isArray(sample.reasons) ? sample.reasons.map(String).filter(Boolean) : []
  const parts = [
    status ? statusLabel(status) : '',
    labeledCount !== undefined ? `labels ${formatDisplayMetricValue(labeledCount)}` : '',
    evaluatedCount !== undefined ? `eval ${formatDisplayMetricValue(evaluatedCount)}` : '',
    foldCount !== undefined ? `folds ${formatDisplayMetricValue(foldCount)}` : '',
    reasons.length ? `reasons ${reasons.length}` : '',
  ].filter(Boolean)
  return {
    summary: parts.join(' / ') || 'declared',
    detail: JSON.stringify(sample),
  }
}

function formatProbability(value: number | undefined) {
  if (value === undefined) return '-'
  const normalized = Math.abs(value) <= 1 ? value * 100 : value
  return `${normalized.toFixed(1)}%`
}

function formatMetricValue(value: unknown) {
  if (value === undefined || value === null || value === '') return '-'
  if (typeof value === 'number') {
    if (Math.abs(value) <= 1) return value.toFixed(2)
    return Number.isInteger(value) ? String(value) : value.toFixed(2)
  }
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  if (Array.isArray(value)) return value.join(', ')
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function formatDisplayMetricValue(value: unknown) {
  const formatted = formatMetricValue(value)
  if (formatted === '-') return formatted
  const upper = formatted.toUpperCase()
  if (qualityLabels[upper]) return qualityLabel(formatted)
  if (statusLabels[upper]) return statusLabel(formatted)
  return localizedText(formatted)
}

function dedupeStrings(values: string[]) {
  return Array.from(new Set(values.map((item) => item.trim()).filter(Boolean)))
}

function stringValue(value: unknown) {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined
}

function firstStringValue(value: unknown) {
  if (typeof value === 'string') return stringValue(value)
  if (Array.isArray(value)) {
    for (const item of value) {
      const next = stringValue(item)
      if (next) return next
    }
  }
  return undefined
}

function researchSignalOpsSignalId(iteration: ResearchIteration) {
  return stringValue(iteration.metrics?.signalops_signal_id)
    ?? firstStringValue(iteration.metrics?.signalops_signal_ids)
    ?? stringValue(iteration.evidence_links.find((item) => String(item.source_type || '').toUpperCase() === 'SIGNALOPS')?.source_id)
}

function signalOpsEvidencePath(iteration: ResearchIteration) {
  const params = new URLSearchParams({ iteration_id: iteration.iteration_id })
  const signalId = researchSignalOpsSignalId(iteration)
  if (signalId) params.set('signal_id', signalId)
  return `/signalops?${params.toString()}`
}

function researchBacktestPath(iteration: ResearchIteration, backtestId: string) {
  const params = new URLSearchParams({
    run_id: backtestId,
    iteration_id: iteration.iteration_id,
  })
  return `/research-lab/backtest?${params.toString()}`
}
