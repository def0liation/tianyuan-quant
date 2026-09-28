import { useCallback, useEffect, useMemo, useState } from 'react'
import { Archive, Database, Filter, RefreshCw, Save, ShieldCheck } from 'lucide-react'
import { Badge } from '../common/Badge'
import { Card } from '../common/Card'
import { ResearchEmptyState, ResearchError, ResearchLoading, ResearchMetricCard, ResearchPageHeader } from '../research/ResearchLabShared'
import {
  compressRun,
  getDataPipelineOverview,
  getKnowledgeDistillationGroups,
  getRunCompressionSummary,
} from '../../api/dataPipelineClient'
import {
  AnalysisRunSummary,
  CompressionOverview,
  KnowledgeDistillationGroup,
  RunCompressionSummary,
} from '../../types'
import { useAnalysisStore } from '../../store/useAnalysisStore'
import { roleAllows, useOperatorContext } from '../../store/operatorContext'
import { useToastStore } from '../../store/useToastStore'
import { visibleRunHistory } from '../../utils/runHistory'

function qualityBadge(level?: string) {
  if (level === 'HIGH') return 'PASS'
  if (level === 'MEDIUM') return 'WARN'
  return 'FAIL'
}

function retentionBadge(action?: string) {
  if (action === 'KEEP_RAW_AND_SUMMARY') return 'PASS'
  if (action === 'KEEP_SUMMARY_REVIEW_RAW') return 'WARN'
  if (action === 'KEEP_RAW_UNTIL_FINAL') return 'RUNNING'
  return 'FAIL'
}

function shortHash(value?: string) {
  if (!value) return 'N/A'
  return `${value.slice(0, 10)}...${value.slice(-8)}`
}

type DataCompressionEvidenceStrength = 'LOW' | 'MEDIUM'

interface DataCompressionGovernance {
  contextId: string
  evidenceStrength: DataCompressionEvidenceStrength
  blocker: string
  nextAction: string
  simulationOnly: boolean
  isRealTrade: boolean
  evidenceUsage: 'simulation_only'
  strongConclusionAllowed: false
}

function dataCompressionEvidenceStrength(
  summary: RunCompressionSummary,
  compressed: boolean,
): DataCompressionEvidenceStrength {
  if (!compressed) return 'LOW'
  if (summary.evidence_summary.length === 0 || summary.guardrail_summary.length === 0) return 'LOW'
  if (summary.quality.missing_critical_fields.length > 0) return 'LOW'
  const level = summary.quality.level.toUpperCase()
  if (level === 'HIGH' || level === 'MEDIUM') return 'MEDIUM'
  return 'LOW'
}

function buildDataCompressionGovernance(
  summary: RunCompressionSummary,
  selectedRun: AnalysisRunSummary | undefined,
  compressed: boolean,
): DataCompressionGovernance {
  const hasMissingCriticalFields = summary.quality.missing_critical_fields.length > 0
  const hasGuardrails = summary.guardrail_summary.length > 0
  const hasEvidence = summary.evidence_summary.length > 0
  const qualityLevel = summary.quality.level.toUpperCase()
  const blocker = hasMissingCriticalFields
    ? 'MISSING_CRITICAL_FIELDS'
    : !hasGuardrails
      ? 'MISSING_GUARDRAIL_SUMMARY'
      : !hasEvidence
        ? 'MISSING_EVIDENCE_SUMMARY'
        : qualityLevel === 'LOW'
          ? 'LOW_QUALITY'
          : !compressed
            ? 'PREVIEW_ONLY'
            : 'NONE'
  const nextAction = blocker === 'NONE'
    ? '可进入 Knowledge / Research Lab 仅模拟复核'
    : blocker === 'PREVIEW_ONLY'
      ? '写回压缩摘要后再进入知识沉淀'
      : '补齐数据质量、护栏和证据摘要后再沉淀'

  return {
    contextId: summary.run_id || selectedRun?.runId || 'NO_RUN',
    evidenceStrength: dataCompressionEvidenceStrength(summary, compressed),
    blocker,
    nextAction,
    simulationOnly: true,
    isRealTrade: false,
    evidenceUsage: 'simulation_only',
    strongConclusionAllowed: false,
  }
}

function chooseAvailableRunId(
  history: Array<{ runId: string }>,
  candidates: Array<string | null | undefined>,
) {
  const availableRunIds = new Set(history.map((run) => run.runId))
  for (const candidate of candidates) {
    if (candidate && availableRunIds.has(candidate)) {
      return candidate
    }
  }
  return history[0]?.runId ?? ''
}

export function DataCompressionPage() {
  const operator = useOperatorContext()
  const canWriteDataCompression = roleAllows(operator.role, 'researcher')
  const dataCompressionWriteDisabledReason = canWriteDataCompression
    ? ''
    : `数据压缩写入需要 researcher 权限。当前角色：${operator.role}。`
  const { runHistory, currentRunId, loadRunHistory } = useAnalysisStore()
  const addToast = useToastStore((state) => state.addToast)
  const [overview, setOverview] = useState<CompressionOverview | null>(null)
  const [selectedRunId, setSelectedRunId] = useState(currentRunId ?? '')
  const [summary, setSummary] = useState<RunCompressionSummary | null>(null)
  const [distillationGroups, setDistillationGroups] = useState<KnowledgeDistillationGroup[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const selectableRunHistory = useMemo(
    () => visibleRunHistory(runHistory, { preserveRunIds: [selectedRunId, currentRunId] }),
    [currentRunId, runHistory, selectedRunId],
  )

  const selectedRun = useMemo(
    () => selectableRunHistory.find((run) => run.runId === selectedRunId),
    [selectableRunHistory, selectedRunId],
  )
  const selectedRunCompressed = Boolean(selectedRun?.compressed || summary?.compression_persisted)
  const artifactPath = summary?.artifact_path ?? selectedRun?.compressedArtifactPath
  const compressedAt = summary?.compressed_at ?? selectedRun?.compressedAt

  const loadPipeline = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      await loadRunHistory().catch(() => undefined)
      const nextOverview = await getDataPipelineOverview()
      setOverview(nextOverview)
      const latestHistory = visibleRunHistory(useAnalysisStore.getState().runHistory, {
        preserveRunIds: [selectedRunId, currentRunId],
      })
      const nextRunId = chooseAvailableRunId(latestHistory, [
        selectedRunId,
        currentRunId,
        nextOverview.latest_run_id,
      ])
      if (nextRunId) {
        setSelectedRunId(nextRunId)
        setSummary(await getRunCompressionSummary(nextRunId))
      } else {
        setSelectedRunId('')
        setSummary(null)
      }
      setDistillationGroups(await getKnowledgeDistillationGroups({ minGroupSize: 2 }))
    } catch (err) {
      setError(err instanceof Error ? err.message : '无法加载数据压缩管线')
    } finally {
      setLoading(false)
    }
  }, [currentRunId, loadRunHistory, selectedRunId])

  useEffect(() => {
    loadPipeline()
  }, [loadPipeline])

  async function handleSelectRun(runId: string) {
    setSelectedRunId(runId)
    setError(null)
    setSummary(null)
    if (!runId) {
      return
    }
    try {
      setSummary(await getRunCompressionSummary(runId))
    } catch (err) {
      setError(err instanceof Error ? err.message : '无法加载运行摘要')
    }
  }

  async function handleCompressRun() {
    if (!canWriteDataCompression) {
      addToast(dataCompressionWriteDisabledReason, 'error')
      return
    }
    if (!selectedRunId) return
    if (selectedRunCompressed) {
      addToast('该运行已压缩，已阻止重复写回。', 'info')
      return
    }
    setSaving(true)
    try {
      const nextSummary = await compressRun(selectedRunId)
      setSummary(nextSummary)
      addToast('压缩摘要已写回运行记录', 'success')
      await loadRunHistory().catch(() => undefined)
      setOverview(await getDataPipelineOverview())
    } catch (err) {
      addToast(err instanceof Error ? err.message : '写回压缩摘要失败', 'error')
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <ResearchLoading label="正在加载数据压缩管线..." />

  return (
    <div className="space-y-6">
      <ResearchPageHeader
        eyebrow="证据压缩"
        title="数据压缩"
        subtitle="把运行数据清洗、指纹去重、摘要提炼和保留策略集中到一张证据工作台，保证后续知识沉淀有可追溯来源。"
        icon={Database}
        tags={['运行摘要', '质量分', '保留策略']}
        actions={
          <button
            type="button"
            onClick={loadPipeline}
            disabled={saving}
            className="inline-flex items-center gap-2 rounded-md border border-slate-600 bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:opacity-60"
          >
            <RefreshCw size={16} />
            刷新管线
          </button>
        }
      />

      {error ? <ResearchError message={error} /> : null}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <ResearchMetricCard label="参与扫描" value={overview?.total_runs ?? 0} helper="已纳入压缩视图" icon={Archive} tone="bg-cyan-50 text-cyan-700" />
        <ResearchMetricCard label="平均质量分" value={overview?.average_quality_score ?? 0} helper="证据质量均值" icon={ShieldCheck} tone="bg-emerald-50 text-emerald-700" />
        <ResearchMetricCard label="高质量样本" value={overview?.high_quality_count ?? 0} helper="可直接沉淀" icon={Save} tone="bg-amber-50 text-amber-700" />
        <ResearchMetricCard label="需复核样本" value={overview?.low_quality_count ?? 0} helper="需要人工核验" icon={Filter} tone="bg-rose-50 text-rose-700" />
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.2fr_1fr]">
        <Card title="运行压缩">
          <div className="space-y-5">
            <div className="flex flex-wrap gap-2 text-xs text-slate-500">
              <span data-testid="data-compression-write-role">角色：{operator.role}；写入：{canWriteDataCompression ? 'researcher+' : '已阻断'}</span>
              {!canWriteDataCompression ? (
                <span data-testid="data-compression-write-disabled-reason" className="text-amber-700">{dataCompressionWriteDisabledReason}</span>
              ) : null}
            </div>
            <div className="grid gap-3 md:grid-cols-[1fr_auto_auto]">
              <select
                value={selectedRunId}
                onChange={(event) => handleSelectRun(event.target.value)}
                className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900"
              >
                <option value="">选择运行</option>
                {selectableRunHistory.map((run) => (
                  <option key={run.runId} value={run.runId}>
                    {run.stockCode} · {run.status} · {run.compressed ? '已压缩' : '未压缩'} · {run.runId}
                  </option>
                ))}
              </select>
              <button
                type="button"
                onClick={loadPipeline}
                disabled={saving}
                className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:opacity-60"
              >
                <RefreshCw size={16} />
                刷新
              </button>
              <button
                type="button"
                data-testid="data-compression-write-summary"
                onClick={handleCompressRun}
                disabled={!selectedRunId || saving || selectedRunCompressed || !canWriteDataCompression}
                title={dataCompressionWriteDisabledReason || undefined}
                className="inline-flex items-center justify-center gap-2 rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
              >
                <Save size={16} />
                {selectedRunCompressed ? '已压缩' : '写回摘要'}
              </button>
            </div>

            {summary ? (
              <div className="space-y-5">
                {(() => {
                  const compressionGovernance = buildDataCompressionGovernance(summary, selectedRun, selectedRunCompressed)
                  return (
                    <div data-testid={`data-compression-run-governance-${summary.run_id}`} className="grid gap-2 rounded-md border border-cyan-200 bg-white/80 p-3 text-xs text-slate-700 sm:grid-cols-2 xl:grid-cols-5">
                      <span data-testid={`data-compression-run-governance-id-${summary.run_id}`} className="min-w-0 break-words font-mono">
                        Run: {compressionGovernance.contextId}
                      </span>
                      <span data-testid={`data-compression-run-evidence-strength-${summary.run_id}`} className="min-w-0 break-words">
                        Evidence: {compressionGovernance.evidenceStrength}
                      </span>
                      <span data-testid={`data-compression-run-blocker-${summary.run_id}`} className="min-w-0 break-words">
                        Blocker: {compressionGovernance.blocker}
                      </span>
                      <span data-testid={`data-compression-run-next-action-${summary.run_id}`} className="min-w-0 break-words">
                        Next: {compressionGovernance.nextAction}
                      </span>
                      <span data-testid={`data-compression-run-simulation-boundary-${summary.run_id}`} className="min-w-0 break-words font-medium text-slate-900">
                        simulation_only={String(compressionGovernance.simulationOnly)} / is_real_trade={String(compressionGovernance.isRealTrade)} / evidence_usage={compressionGovernance.evidenceUsage} / strong_conclusion_allowed={String(compressionGovernance.strongConclusionAllowed)} / SIM_*
                      </span>
                    </div>
                  )
                })()}

                <div className="flex flex-wrap items-center gap-2">
                  <Badge status={qualityBadge(summary.quality.level)}>{summary.quality.level} · {summary.quality.score}</Badge>
                  <Badge status={retentionBadge(summary.retention_action)}>{summary.retention_action}</Badge>
                  <Badge status={selectedRunCompressed ? 'PASS' : 'WARN'}>{selectedRunCompressed ? '已压缩' : '预览摘要'}</Badge>
                  <span className="rounded bg-slate-100 px-2 py-1 text-xs text-slate-600">
                    {summary.token_budget_estimate} tokens
                  </span>
                </div>

                <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
                  <div className="text-sm font-semibold text-slate-950">{summary.decision_summary}</div>
                  <div className="mt-2 text-xs text-slate-500">
                    {selectedRun?.taskType ?? 'task'} · {summary.run_mode} · {summary.status}
                  </div>
                  <div className="mt-2 break-all text-xs text-slate-500">
                    {summary.data_fingerprint.namespace}: {shortHash(summary.data_fingerprint.fingerprint)}
                  </div>
                  <div className="mt-3 rounded border border-slate-200 bg-white px-3 py-2 text-xs leading-5 text-slate-600">
                    <div className="font-semibold text-slate-700">压缩产物</div>
                    {selectedRunCompressed ? (
                      <>
                        <div className="mt-1 break-all">位置：{artifactPath ?? 'backend/app/storage/runs/{runId}.json#compressedSummary'}</div>
                        <div className="mt-1">写回时间：{compressedAt ?? summary.created_at}</div>
                      </>
                    ) : (
                      <div className="mt-1">当前为即时预览；点击“写回摘要”后会写入运行 JSON 的 compressedSummary 字段。</div>
                    )}
                  </div>
                </div>

                <div className="grid gap-4 lg:grid-cols-2">
                  <div>
                    <div className="mb-2 text-xs font-semibold uppercase text-slate-400">关键指标</div>
                    <div className="space-y-2 text-sm text-slate-600">
                      {Object.entries(summary.key_metrics).map(([key, value]) => (
                        <div key={key} className="flex justify-between gap-3 rounded border border-slate-100 px-3 py-2">
                          <span className="text-slate-500">{key}</span>
                          <span className="text-right font-medium text-slate-900">{String(value ?? 'N/A')}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                  <div>
                    <div className="mb-2 text-xs font-semibold uppercase text-slate-400">保留策略</div>
                    <div className="rounded border border-slate-100 px-3 py-2 text-sm leading-6 text-slate-600">
                      {summary.retention_reason}
                    </div>
                    <div className="mt-3 text-xs font-semibold uppercase text-slate-400">缺失项</div>
                    <div className="mt-2 flex flex-wrap gap-2">
                      {summary.quality.missing_critical_fields.length ? summary.quality.missing_critical_fields.map((field) => (
                        <span key={field} className="rounded bg-amber-100 px-2 py-1 text-xs text-amber-800">{field}</span>
                      )) : <span className="text-sm text-slate-500">无</span>}
                    </div>
                  </div>
                </div>

                <div className="grid gap-4 lg:grid-cols-2">
                  <div>
                    <div className="mb-2 text-xs font-semibold uppercase text-slate-400">护栏</div>
                    <ul className="space-y-1 text-sm text-slate-600">
                      {summary.guardrail_summary.map((item, index) => (
                        <li key={index}>· {item}</li>
                      ))}
                    </ul>
                  </div>
                  <div>
                    <div className="mb-2 text-xs font-semibold uppercase text-slate-400">证据</div>
                    <ul className="space-y-1 text-sm text-slate-600">
                      {summary.evidence_summary.map((item, index) => (
                        <li key={index}>· {item}</li>
                      ))}
                    </ul>
                  </div>
                </div>
              </div>
            ) : (
              <ResearchEmptyState title="暂无可压缩运行" description="创建或刷新一次分析任务后，运行摘要会出现在这里供你预览和写回。" icon={Archive} />
            )}
          </div>
        </Card>

        <Card title="知识提炼">
          <div className="space-y-4">
            <div className="flex items-center gap-2 text-sm text-slate-600">
              <Filter size={16} />
              <span>{distillationGroups.length} 个相似分组</span>
            </div>
            {distillationGroups.length === 0 ? (
              <ResearchEmptyState title="暂无可合并分组" description="当相似证据或重复知识达到阈值后，这里会显示建议合并的分组。" icon={Filter} />
            ) : (
              distillationGroups.map((group) => (
                <div key={group.group_id} className="rounded-lg border border-slate-200 bg-white p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge status="WARN">{group.category}</Badge>
                    <span className="rounded bg-slate-100 px-2 py-1 text-xs text-slate-600">
                      duplicates {group.duplicate_count}
                    </span>
                  </div>
                  <div className="mt-3 break-all text-xs text-slate-500">{group.group_id}</div>
                  <div className="mt-2 text-sm leading-6 text-slate-600">{group.reason}</div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {group.shared_tags.map((tag) => (
                      <span key={tag} className="rounded bg-slate-100 px-2 py-1 text-xs text-slate-500">{tag}</span>
                    ))}
                  </div>
                  <div className="mt-3 flex items-center gap-2 text-xs text-slate-500">
                    <Archive size={14} />
                    <span>{group.suggested_action}</span>
                  </div>
                </div>
              ))
            )}
          </div>
        </Card>
      </div>
    </div>
  )
}
