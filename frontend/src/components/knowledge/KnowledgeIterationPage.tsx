import { useCallback, useEffect, useMemo, useState } from 'react'
import { BookOpenCheck, CheckCircle2, ChevronDown, ChevronUp, Clock, GitBranch, Layers, RefreshCw, Save, Trash2, XCircle } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'
import { Badge } from '../common/Badge'
import { Card } from '../common/Card'
import { ResearchEmptyState, ResearchError, ResearchLoading, ResearchMetricCard, ResearchPageHeader } from '../research/ResearchLabShared'
import {
  createKnowledgeItem,
  generateKnowledgeFromRun,
  getKnowledgeItems,
  getKnowledgeSummary,
  knowledgeSubmissionConfidence,
  reviewKnowledgeItem,
} from '../../api/knowledgeClient'
import { KnowledgeItem, KnowledgeSummary } from '../../types'
import { useAnalysisStore } from '../../store/useAnalysisStore'
import { roleAllows, useOperatorContext } from '../../store/operatorContext'
import { useToastStore } from '../../store/useToastStore'
import { formatDateTime } from '../../utils/format'

const categoryOptions = [
  'RUN_REVIEW',
  'POSITIVE_SIGNAL',
  'DEFENSIVE_REVIEW',
  'DVG_DATA_GATE',
  'RISK_GUARDRAIL',
  'SIGNALOPS_BLOCK',
]

function splitLines(value: string) {
  return value
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
}

function splitTags(value: string) {
  return value
    .split(',')
    .map((tag) => tag.trim())
    .filter(Boolean)
}

function statusBadge(status: string) {
  if (status === 'ACTIVE') return 'PASS'
  if (status === 'PENDING_REVIEW') return 'WARN'
  if (status === 'REJECTED') return 'FAIL'
  return 'SKIPPED'
}

function confidenceBadge(confidence: string) {
  if (confidence === 'HIGH') return 'HIGH'
  if (confidence === 'MEDIUM') return 'MEDIUM'
  return 'LOW'
}

function getKnowledgeStockCode(item: KnowledgeItem) {
  const taggedCode = item.tags.find((tag) => /^\d{6}(?:\.(?:SH|SZ|BJ))?$/i.test(tag))
  if (taggedCode) return taggedCode.toUpperCase()

  const textMatch = [item.title, item.thesis].join(' ').match(/\b\d{6}(?:\.(?:SH|SZ|BJ))?\b/i)
  return textMatch ? textMatch[0].toUpperCase() : 'UNKNOWN'
}

function canDeleteKnowledgeItem(item: KnowledgeItem) {
  return item.status !== 'PENDING_REVIEW' && item.status !== 'ARCHIVED'
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

function knowledgeEvidenceStrengthLabel(item: KnowledgeItem) {
  const apiStrength = reviewGateEvidenceStrength(item.evidence_strength)
  if (apiStrength === 'MEDIUM') return 'MEDIUM：已审核，仍仅作辅助'
  if (apiStrength === 'LOW') return 'LOW：弱证据或已拒绝'
  if (apiStrength === 'MISSING') return 'MISSING：无证据'
  if (apiStrength === 'PENDING') return 'PENDING：等待审核'
  if (item.evidence.length === 0) return 'MISSING：无证据'
  if (item.confidence === 'HIGH' && item.guardrail_notes.length > 0 && item.source_run_id && item.source_run_verified) {
    return 'MEDIUM：已验证运行证据+护栏'
  }
  if (item.confidence === 'HIGH') return 'MEDIUM：高置信需护栏复核'
  if (item.confidence === 'MEDIUM') return 'MEDIUM：需人工复核'
  return 'LOW：弱证据'
}

function knowledgeItemBlocker(item: KnowledgeItem, canWrite: boolean) {
  if (item.status === 'PENDING_REVIEW' && !canWrite) return '当前角色无法审核'
  if (item.evidence.length === 0) return '缺少证据'
  if (item.guardrail_notes.length === 0) return '缺少护栏备注'
  if (item.source_run_id && !item.source_run_verified) return '来源运行未验证'
  if (item.status === 'PENDING_REVIEW') return '等待 researcher 审核'
  return `状态：${item.status}`
}

function knowledgeItemNextAction(item: KnowledgeItem, canWrite: boolean, canArchive: boolean) {
  if (item.status === 'PENDING_REVIEW' && !canWrite) return '切换 researcher 角色'
  if (item.evidence.length === 0) return '补充证据'
  if (item.guardrail_notes.length === 0) return '补充护栏备注'
  if (item.source_run_id && !item.source_run_verified) return '重新从已验证运行生成，或移除未验证来源'
  if (item.status === 'PENDING_REVIEW') return '批准或拒绝'
  if (item.status === 'ACTIVE') return canArchive ? '定期复核或归档' : '用于后续研究'
  if (item.status === 'REJECTED') return '保留审计记录'
  return '查看详细'
}

type KnowledgeDraftEvidenceStrength = 'LOW'

interface KnowledgeDraftGovernance {
  contextId: string
  evidenceStrength: KnowledgeDraftEvidenceStrength
  blocker: string
  nextAction: string
  confidenceForSubmission: 'MEDIUM' | 'LOW'
}

function buildManualKnowledgeGovernance(input: {
  category: string
  title: string
  thesis: string
  evidenceText: string
  guardrailText: string
  confidence: string
  canWrite: boolean
  runId?: string | null
}): KnowledgeDraftGovernance {
  const evidenceCount = splitLines(input.evidenceText).length
  const guardrailCount = splitLines(input.guardrailText).length
  const requestedHighConfidence = input.confidence.toUpperCase() === 'HIGH'
  const blocker = !input.canWrite
    ? 'ROLE_BLOCKED'
    : !input.title.trim()
      ? 'TITLE_MISSING'
      : !input.thesis.trim()
        ? 'THESIS_MISSING'
        : evidenceCount === 0
          ? 'EVIDENCE_MISSING'
          : guardrailCount === 0
            ? 'GUARDRAIL_MISSING'
            : requestedHighConfidence
              ? 'HIGH_CONFIDENCE_CAPPED'
              : 'NONE'
  const evidenceStrength: KnowledgeDraftEvidenceStrength = 'LOW'
  const nextAction = blocker === 'NONE'
    ? '创建待审核条目；证据只能进入 supporting_only'
    : blocker === 'HIGH_CONFIDENCE_CAPPED'
      ? '手工置信度已封顶为 MEDIUM，等待 researcher 审核'
      : '补齐角色、标题、假设、证据或护栏备注'

  return {
    contextId: `${input.runId ?? 'manual'}:${input.category}:draft`,
    evidenceStrength,
    blocker,
    nextAction,
    confidenceForSubmission: knowledgeSubmissionConfidence(input.confidence),
  }
}

export function KnowledgeIterationPage() {
  const operator = useOperatorContext()
  const canWriteKnowledgeItems = roleAllows(operator.role, 'researcher')
  const canArchiveKnowledgeItems = roleAllows(operator.role, 'admin')
  const knowledgeWriteDisabledReason = canWriteKnowledgeItems
    ? ''
    : `知识写入需要 researcher 权限。当前角色：${operator.role}。`
  const knowledgeArchiveDisabledReason = canArchiveKnowledgeItems
    ? ''
    : `知识归档需要 admin 权限。当前角色：${operator.role}。`
  const { currentRunId, currentRun } = useAnalysisStore()
  const [searchParams] = useSearchParams()
  const addToast = useToastStore((state) => state.addToast)
  const [summary, setSummary] = useState<KnowledgeSummary | null>(null)
  const [items, setItems] = useState<KnowledgeItem[]>([])
  const [statusFilter, setStatusFilter] = useState('')
  const [categoryFilter, setCategoryFilter] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [category, setCategory] = useState('RUN_REVIEW')
  const [title, setTitle] = useState('')
  const [thesis, setThesis] = useState('')
  const [evidenceText, setEvidenceText] = useState('')
  const [guardrailText, setGuardrailText] = useState('')
  const [decisionImpact, setDecisionImpact] = useState('')
  const [tagsText, setTagsText] = useState('')
  const [confidence, setConfidence] = useState('MEDIUM')
  const [expandedItemIds, setExpandedItemIds] = useState<Set<string>>(() => new Set())

  const pendingItems = useMemo(
    () => items.filter((item) => item.status === 'PENDING_REVIEW').length,
    [items],
  )
  const linkedRunId = (searchParams.get('run_id') || '').trim()
  const isLinkedRunPending = Boolean(linkedRunId && currentRun?.runId !== linkedRunId)
  const runId = isLinkedRunPending ? '' : linkedRunId || currentRunId || currentRun?.runId
  const runContextId = isLinkedRunPending ? linkedRunId : runId
  const runHydrationDisabledReason = isLinkedRunPending ? `正在加载 URL 指定的运行：${linkedRunId}` : ''
  const manualKnowledgeGovernance = buildManualKnowledgeGovernance({
    category,
    title,
    thesis,
    evidenceText,
    guardrailText,
    confidence,
    canWrite: canWriteKnowledgeItems,
    runId,
  })

  const loadKnowledge = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [nextSummary, nextItems] = await Promise.all([
        getKnowledgeSummary(),
        getKnowledgeItems({
          status: statusFilter || undefined,
          category: categoryFilter || undefined,
        }),
      ])
      setSummary(nextSummary)
      setItems(statusFilter ? nextItems : nextItems.filter((item) => item.status !== 'ARCHIVED'))
    } catch (err) {
      setError(err instanceof Error ? err.message : '无法加载知识迭代数据')
    } finally {
      setLoading(false)
    }
  }, [categoryFilter, statusFilter])

  useEffect(() => {
    loadKnowledge()
  }, [loadKnowledge])

  async function handleGenerateFromRun() {
    if (!canWriteKnowledgeItems) {
      addToast(knowledgeWriteDisabledReason, 'error')
      return
    }
    if (isLinkedRunPending) {
      addToast(runHydrationDisabledReason || '正在加载 URL 指定的运行。', 'error')
      return
    }
    if (!runId) return
    setSaving(true)
    try {
      await generateKnowledgeFromRun(runId)
      addToast('已从当前运行生成学习候选', 'success')
      await loadKnowledge()
    } catch (err) {
      addToast(err instanceof Error ? err.message : '生成学习候选失败', 'error')
    } finally {
      setSaving(false)
    }
  }

  async function handleCreateManual() {
    if (!canWriteKnowledgeItems) {
      addToast(knowledgeWriteDisabledReason, 'error')
      return
    }
    if (isLinkedRunPending) {
      addToast(runHydrationDisabledReason || '正在加载 URL 指定的运行。', 'error')
      return
    }
    setSaving(true)
    try {
      await createKnowledgeItem({
        category,
        title,
        thesis,
        evidence: splitLines(evidenceText),
        guardrail_notes: splitLines(guardrailText),
        decision_impact: decisionImpact,
        tags: splitTags(tagsText),
        confidence: knowledgeSubmissionConfidence(confidence),
        source_run_id: runId || undefined,
      })
      setTitle('')
      setThesis('')
      setEvidenceText('')
      setGuardrailText('')
      setDecisionImpact('')
      setTagsText('')
      addToast('学习条目已进入待审核', 'success')
      await loadKnowledge()
    } catch (err) {
      addToast(err instanceof Error ? err.message : '创建学习条目失败', 'error')
    } finally {
      setSaving(false)
    }
  }

  async function handleReview(item: KnowledgeItem, action: 'APPROVE' | 'REJECT' | 'ARCHIVE') {
    if (action === 'ARCHIVE' && !canArchiveKnowledgeItems) {
      addToast(knowledgeArchiveDisabledReason, 'error')
      return
    }
    if (action !== 'ARCHIVE' && !canWriteKnowledgeItems) {
      addToast(knowledgeWriteDisabledReason, 'error')
      return
    }
    if (action === 'ARCHIVE' && !window.confirm('确定删除此知识条目？删除后会进入 ARCHIVED，可通过筛选查看。')) {
      return
    }
    setSaving(true)
    try {
      await reviewKnowledgeItem(item.item_id, {
        action,
        reviewer: 'human',
        note: action === 'APPROVE' ? 'approved from console' : action === 'ARCHIVE' ? 'deleted from active knowledge list' : 'reviewed from console',
      })
      addToast(action === 'APPROVE' ? '学习条目已激活' : action === 'ARCHIVE' ? '知识条目已删除' : '学习条目已更新', 'success')
      await loadKnowledge()
    } catch (err) {
      addToast(err instanceof Error ? err.message : '审核操作失败', 'error')
    } finally {
      setSaving(false)
    }
  }

  function toggleItemDetails(itemId: string) {
    setExpandedItemIds((current) => {
      const next = new Set(current)
      if (next.has(itemId)) {
        next.delete(itemId)
      } else {
        next.add(itemId)
      }
      return next
    })
  }

  if (loading) return <ResearchLoading label="正在加载知识迭代..." />

  return (
    <div className="space-y-6">
      <ResearchPageHeader
        eyebrow="知识迭代"
        title="知识迭代"
        subtitle="从运行结果沉淀可审核经验，审核通过后进入主动知识上下文，让研究结论、证据和护栏备注可以被后续任务复用。"
        icon={BookOpenCheck}
        tags={['Run learning', 'Human review', 'Active context']}
        actions={
          <button
            type="button"
            onClick={loadKnowledge}
            disabled={saving}
            className="inline-flex items-center gap-2 rounded-md border border-slate-600 bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:opacity-60"
          >
            <RefreshCw size={16} />
            刷新知识
          </button>
        }
      />

      {error ? <ResearchError message={error} /> : null}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <ResearchMetricCard label="已激活" value={summary?.active_count ?? 0} helper="Active / 已进入知识上下文" icon={CheckCircle2} tone="bg-emerald-50 text-emerald-700" />
        <ResearchMetricCard label="待审核" value={summary?.pending_count ?? pendingItems} helper="Pending / 等待人工确认" icon={Clock} tone="bg-amber-50 text-amber-700" />
        <ResearchMetricCard label="最新版本" value={`v${summary?.latest_version ?? 0}`} helper="Version / 当前激活快照" icon={GitBranch} tone="bg-cyan-50 text-cyan-700" />
        <ResearchMetricCard label="累计条目" value={summary?.total ?? 0} helper="Total / 历史知识条目" icon={Layers} tone="bg-slate-100 text-slate-700" />
      </div>

      <Card title="学习入口">
        <div className="grid gap-4 lg:grid-cols-[1fr_1.2fr]">
          <div className="space-y-4">
            <div className="flex flex-wrap gap-2 text-xs text-slate-500">
              <span data-testid="knowledge-write-role">角色：{operator.role}；写入：{canWriteKnowledgeItems ? 'researcher+' : '已阻断'}；归档：{canArchiveKnowledgeItems ? 'admin' : '已阻断'}</span>
              {!canWriteKnowledgeItems ? (
                <span data-testid="knowledge-write-disabled-reason" className="text-amber-700">{knowledgeWriteDisabledReason}</span>
              ) : null}
              {!canArchiveKnowledgeItems ? (
                <span data-testid="knowledge-archive-disabled-reason" className="text-amber-700">{knowledgeArchiveDisabledReason}</span>
              ) : null}
            </div>
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
              <div className="text-sm font-medium text-slate-900">当前运行沉淀</div>
              <div data-testid="knowledge-current-run-id" className="mt-1 break-all font-mono text-xs text-slate-500">{runContextId || '尚未选择运行'}</div>
              {isLinkedRunPending ? (
                <div data-testid="knowledge-current-run-loading" className="mt-2 text-xs text-amber-700">{runHydrationDisabledReason}</div>
              ) : null}
              <button
                type="button"
                data-testid="knowledge-generate-from-run"
                onClick={handleGenerateFromRun}
                disabled={!runId || saving || !canWriteKnowledgeItems || isLinkedRunPending}
                title={runHydrationDisabledReason || knowledgeWriteDisabledReason || undefined}
                className="mt-4 inline-flex items-center gap-2 rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
              >
                <GitBranch size={16} />
                从当前运行生成
              </button>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <select
                value={statusFilter}
                onChange={(event) => setStatusFilter(event.target.value)}
                className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900"
              >
                <option value="">全部状态</option>
                <option value="PENDING_REVIEW">PENDING_REVIEW</option>
                <option value="ACTIVE">ACTIVE</option>
                <option value="REJECTED">REJECTED</option>
                <option value="ARCHIVED">ARCHIVED</option>
              </select>
              <select
                value={categoryFilter}
                onChange={(event) => setCategoryFilter(event.target.value)}
                className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900"
              >
                <option value="">全部类别</option>
                {categoryOptions.map((option) => (
                  <option key={option} value={option}>{option}</option>
                ))}
              </select>
            </div>
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            <label className="space-y-1 text-sm">
              <span className="font-medium text-slate-700">类别</span>
              <select
                value={category}
                onChange={(event) => setCategory(event.target.value)}
                className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-slate-900"
              >
                {categoryOptions.map((option) => (
                  <option key={option} value={option}>{option}</option>
                ))}
              </select>
            </label>
            <label className="space-y-1 text-sm">
              <span className="font-medium text-slate-700">置信度</span>
              <select
                value={confidence}
                onChange={(event) => setConfidence(event.target.value)}
                className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-slate-900"
              >
                <option value="MEDIUM">MEDIUM</option>
                <option value="LOW">LOW</option>
              </select>
            </label>
            <div data-testid="knowledge-draft-governance" className="grid gap-2 rounded-md border border-cyan-200 bg-cyan-50 p-3 text-xs text-slate-700 sm:grid-cols-2 md:col-span-2 xl:grid-cols-5">
              <span data-testid="knowledge-draft-governance-id" className="min-w-0 break-all font-mono">
                Draft: {manualKnowledgeGovernance.contextId}
              </span>
              <span data-testid="knowledge-draft-evidence-strength" className="min-w-0 break-words">
                Evidence: {manualKnowledgeGovernance.evidenceStrength}
              </span>
              <span data-testid="knowledge-draft-blocker" className="min-w-0 break-words">
                Blocker: {manualKnowledgeGovernance.blocker}
              </span>
              <span data-testid="knowledge-draft-next-action" className="min-w-0 break-words">
                Next: {manualKnowledgeGovernance.nextAction}
              </span>
              <span data-testid="knowledge-draft-simulation-boundary" className="min-w-0 break-words font-medium text-slate-900">
                simulation_only=true / is_real_trade=false / SIM_* / evidence_usage=supporting_only / strong_conclusion_allowed=false / confidence_cap={manualKnowledgeGovernance.confidenceForSubmission}
              </span>
            </div>
            <label className="space-y-1 text-sm md:col-span-2">
              <span className="font-medium text-slate-700">标题</span>
              <input
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-slate-900"
              />
            </label>
            <label className="space-y-1 text-sm md:col-span-2">
              <span className="font-medium text-slate-700">结论假设</span>
              <textarea
                rows={3}
                value={thesis}
                onChange={(event) => setThesis(event.target.value)}
                className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-slate-900"
              />
            </label>
            <label className="space-y-1 text-sm">
              <span className="font-medium text-slate-700">证据，每行一条</span>
              <textarea
                rows={5}
                value={evidenceText}
                onChange={(event) => setEvidenceText(event.target.value)}
                className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-slate-900"
              />
            </label>
            <label className="space-y-1 text-sm">
              <span className="font-medium text-slate-700">护栏备注，每行一条</span>
              <textarea
                rows={5}
                value={guardrailText}
                onChange={(event) => setGuardrailText(event.target.value)}
                className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-slate-900"
              />
            </label>
            <label className="space-y-1 text-sm md:col-span-2">
              <span className="font-medium text-slate-700">决策影响</span>
              <input
                value={decisionImpact}
                onChange={(event) => setDecisionImpact(event.target.value)}
                className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-slate-900"
              />
            </label>
            <label className="space-y-1 text-sm md:col-span-2">
              <span className="font-medium text-slate-700">标签，逗号分隔</span>
              <input
                value={tagsText}
                onChange={(event) => setTagsText(event.target.value)}
                className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-slate-900"
              />
            </label>
            <button
              type="button"
              data-testid="knowledge-create-manual"
              onClick={handleCreateManual}
              disabled={saving || !title.trim() || !thesis.trim() || !canWriteKnowledgeItems || isLinkedRunPending}
              title={runHydrationDisabledReason || knowledgeWriteDisabledReason || undefined}
              className="inline-flex items-center justify-center gap-2 rounded-lg bg-emerald-700 px-4 py-3 text-sm font-semibold text-white transition hover:bg-emerald-800 disabled:cursor-not-allowed disabled:opacity-60 md:col-span-2"
            >
              <Save size={16} />
              创建待审核条目
            </button>
          </div>
        </div>
      </Card>

      <Card title="知识条目">
        <div className="mb-4 flex justify-end">
          <button
            type="button"
            onClick={loadKnowledge}
            disabled={saving}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:opacity-60"
          >
            <RefreshCw size={16} />
            刷新
          </button>
        </div>
        <div className="space-y-4">
          {items.length === 0 ? (
            <ResearchEmptyState title="暂无知识条目" description="从当前运行生成候选，或手动创建一条待审核知识，审核通过后会进入主动上下文。" icon={BookOpenCheck} />
          ) : (
            items.map((item) => {
              const stockCode = getKnowledgeStockCode(item)
              const isPendingReview = item.status === 'PENDING_REVIEW'
              const isExpanded = expandedItemIds.has(item.item_id)
              const shouldShowDetails = isPendingReview || isExpanded

              return (
                <div key={item.item_id} className="rounded-lg border border-slate-200 bg-white p-4">
                  <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-lg font-semibold tracking-normal text-slate-950">{stockCode}</span>
                      </div>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {!isPendingReview ? (
                        <button
                          type="button"
                          onClick={() => toggleItemDetails(item.item_id)}
                          aria-expanded={isExpanded}
                          className="inline-flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-700 transition hover:bg-slate-50"
                        >
                          {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                          {isExpanded ? '收起详细' : '查看详细'}
                        </button>
                      ) : null}
                      {item.status === 'PENDING_REVIEW' ? (
                        <>
                          <button
                            type="button"
                            data-testid={`knowledge-review-approve-${item.item_id}`}
                            onClick={() => handleReview(item, 'APPROVE')}
                            disabled={saving || !canWriteKnowledgeItems}
                            title={knowledgeWriteDisabledReason || undefined}
                            className="inline-flex items-center gap-2 rounded-lg bg-emerald-700 px-3 py-2 text-xs font-semibold text-white transition hover:bg-emerald-800 disabled:opacity-60"
                          >
                            <CheckCircle2 size={14} />
                            批准
                          </button>
                          <button
                            type="button"
                            data-testid={`knowledge-review-reject-${item.item_id}`}
                            onClick={() => handleReview(item, 'REJECT')}
                            disabled={saving || !canWriteKnowledgeItems}
                            title={knowledgeWriteDisabledReason || undefined}
                            className="inline-flex items-center gap-2 rounded-lg border border-rose-200 px-3 py-2 text-xs font-semibold text-rose-700 transition hover:bg-rose-50 disabled:opacity-60"
                          >
                            <XCircle size={14} />
                            拒绝
                          </button>
                        </>
                      ) : null}
                      {canDeleteKnowledgeItem(item) ? (
                        <button
                          type="button"
                          data-testid={`knowledge-archive-item-${item.item_id}`}
                          onClick={() => handleReview(item, 'ARCHIVE')}
                          disabled={saving || !canArchiveKnowledgeItems}
                          title={knowledgeArchiveDisabledReason || undefined}
                          className="inline-flex items-center gap-2 rounded-lg border border-rose-200 px-3 py-2 text-xs font-semibold text-rose-700 transition hover:bg-rose-50 disabled:opacity-60"
                        >
                          <Trash2 size={14} />
                          删除
                        </button>
                      ) : null}
                    </div>
                  </div>
                  <div data-testid={`knowledge-item-governance-${item.item_id}`} className="mt-3 grid gap-2 rounded-md border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600 sm:grid-cols-2 xl:grid-cols-5">
                    <span data-testid={`knowledge-item-id-${item.item_id}`} className="min-w-0 break-all">
                      Item: {item.item_id}
                    </span>
                    <span data-testid={`knowledge-item-evidence-strength-${item.item_id}`} className="min-w-0 break-words">
                      Evidence: {knowledgeEvidenceStrengthLabel(item)}
                    </span>
                    <span data-testid={`knowledge-item-blocker-${item.item_id}`} className="min-w-0 break-words">
                      Blocker: {knowledgeItemBlocker(item, canWriteKnowledgeItems)}
                    </span>
                    <span data-testid={`knowledge-item-next-action-${item.item_id}`} className="min-w-0 break-words">
                      Next: {knowledgeItemNextAction(item, canWriteKnowledgeItems, canArchiveKnowledgeItems)}
                    </span>
                    <span data-testid={`knowledge-item-simulation-boundary-${item.item_id}`} className="min-w-0 break-words font-medium text-slate-900">
                      simulation_only={String(item.simulation_only)} / is_real_trade={String(item.is_real_trade)} / evidence_usage={item.evidence_usage} / strong_conclusion_allowed={String(item.strong_conclusion_allowed)} / SIM_* / source_run_verified={String(item.source_run_verified)}
                    </span>
                  </div>

                  {shouldShowDetails ? (
                    <div className="mt-4 border-t border-slate-100 pt-4">
                      <div className="mb-3 flex flex-wrap items-center gap-2">
                        <Badge status={statusBadge(item.status)}>{item.status}</Badge>
                        <Badge status={confidenceBadge(item.confidence)}>{item.confidence}</Badge>
                        <span className="rounded bg-slate-100 px-2 py-1 text-xs text-slate-600">{item.category}</span>
                        {item.version > 0 ? <span className="text-xs text-slate-500">v{item.version}</span> : null}
                      </div>
                      <div className="text-base font-semibold text-slate-950">{item.title}</div>
                      <div className="mt-1 text-sm leading-6 text-slate-600">{item.thesis}</div>
                      <div className="mt-2 text-xs text-slate-400">
                        {item.source_run_id ? `Run: ${item.source_run_id} (${item.source_run_verified ? 'verified' : 'unverified'})` : 'Manual item'} · Updated: {formatDateTime(item.updated_at)}
                      </div>
                      {item.decision_impact ? (
                        <div className="mt-3 rounded-md bg-emerald-50 p-3 text-sm leading-6 text-emerald-900">
                          {item.decision_impact}
                        </div>
                      ) : null}

                      <div className="mt-4 grid gap-4 lg:grid-cols-2">
                        <div>
                          <div className="mb-2 text-xs font-semibold uppercase text-slate-400">证据</div>
                          {item.evidence.length ? (
                            <ul className="space-y-1 text-sm text-slate-600">
                              {item.evidence.map((entry, index) => (
                                <li key={index}>- {entry}</li>
                              ))}
                            </ul>
                          ) : (
                            <div className="text-sm text-slate-400">暂无证据。</div>
                          )}
                        </div>
                        <div>
                          <div className="mb-2 text-xs font-semibold uppercase text-slate-400">护栏</div>
                          {item.guardrail_notes.length ? (
                            <ul className="space-y-1 text-sm text-slate-600">
                              {item.guardrail_notes.map((entry, index) => (
                                <li key={index}>- {entry}</li>
                              ))}
                            </ul>
                          ) : (
                            <div className="text-sm text-slate-400">暂无门禁说明。</div>
                          )}
                        </div>
                      </div>
                      {item.review_note ? (
                        <div className="mt-4 text-xs text-slate-500">Review: {item.review_note}</div>
                      ) : null}
                      {item.tags.length ? (
                        <div className="mt-4 flex flex-wrap gap-2">
                          {item.tags.map((tag) => (
                            <span key={tag} className="rounded bg-slate-100 px-2 py-1 text-xs text-slate-500">{tag}</span>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              )
            })
          )}
        </div>
      </Card>
    </div>
  )
}
