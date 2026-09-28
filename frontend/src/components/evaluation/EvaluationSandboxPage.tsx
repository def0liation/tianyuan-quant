import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, Beaker, CheckCircle2, ChevronDown, ChevronUp, RefreshCw, Split, Wrench } from 'lucide-react'
import { Badge } from '../common/Badge'
import { ResearchEmptyState, ResearchLoading, ResearchMetricCard, ResearchPageHeader } from '../research/ResearchLabShared'
import {
  getEvaluations,
  getKnowledgePatches,
  runPatchEvaluation,
  runPatchStrategyExperiment,
} from '../../api/caseLibraryClient'
import { EvaluationRunItem, KnowledgePatchItem, StrategyExperimentReport } from '../../types'
import { roleAllows, useOperatorContext } from '../../store/operatorContext'
import { useToastStore } from '../../store/useToastStore'
import { formatDateTime } from '../../utils/format'

function formatPct(value: number | undefined | null) {
  return `${(((value ?? 0) as number) * 100).toFixed(0)}%`
}

function getExperimentReport(patch: KnowledgePatchItem): StrategyExperimentReport | null {
  const report = patch.backtest_result?.strategy_experiment_report
  return report && typeof report === 'object' ? report as StrategyExperimentReport : null
}

function evaluationRunBoundaryViolation(latestEval?: EvaluationRunItem) {
  if (!latestEval) return ''
  if (latestEval.simulation_only !== true) return 'Evaluation run simulation-only boundary missing'
  if (latestEval.is_real_trade === true) return 'Evaluation run real-trade boundary violated'
  if (latestEval.strong_conclusion_allowed === true) return 'Evaluation run strong conclusion boundary violated'
  if (latestEval.evidence_usage !== 'review_gate_only') return 'Evaluation run evidence usage must remain review_gate_only'
  return ''
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

function evaluationEvidenceStrengthLabel(latestEval?: EvaluationRunItem, experimentReport?: StrategyExperimentReport | null) {
  if (evaluationRunBoundaryViolation(latestEval)) return 'MISSING：评估审计边界违规'
  const apiStrength = reviewGateEvidenceStrength(latestEval?.evidence_strength)
  if (apiStrength === 'MEDIUM') return 'MEDIUM：评估通过，仍需复核'
  if (apiStrength === 'LOW') return 'LOW：存在退化或需复核'
  if (apiStrength === 'MISSING') return 'MISSING：评估失败'
  if (apiStrength === 'PENDING') return 'PENDING：评估未完成'
  if (latestEval?.status === 'COMPLETED' && latestEval.regressed_cases === 0 && latestEval.total_cases > 0) {
    return 'MEDIUM：评估通过，仍需复核'
  }
  if (latestEval?.status === 'COMPLETED') return 'LOW：存在退化或需复核'
  if (latestEval?.status === 'FAILED') return 'MISSING：评估失败'
  if (experimentReport) return 'LOW：策略实验辅助'
  return 'MISSING：未运行评估'
}

function evaluationPatchBlocker(patch: KnowledgePatchItem, latestEval: EvaluationRunItem | undefined, canRun: boolean) {
  if (patch.approval_status !== 'CANDIDATE') return `状态：${patch.approval_status}`
  if (!canRun) return '当前角色无法运行评估'
  if (!latestEval) return '缺少评估结果'
  const boundaryViolation = evaluationRunBoundaryViolation(latestEval)
  if (boundaryViolation) return boundaryViolation
  if (latestEval.status === 'FAILED') return latestEval.error || '评估失败'
  if (latestEval.regressed_cases > 0) return `存在 ${latestEval.regressed_cases} 个退化案例`
  if (patch.backtest_required && latestEval.status !== 'COMPLETED') return '回测要求未满足'
  return '无阻断，等待复核'
}

function evaluationPatchNextAction(
  patch: KnowledgePatchItem,
  latestEval: EvaluationRunItem | undefined,
  experimentReport: StrategyExperimentReport | null,
  canRun: boolean,
) {
  if (!canRun) return '切换 researcher 角色'
  if (evaluationRunBoundaryViolation(latestEval)) return '停止晋级，先修复评估审计边界'
  if (!latestEval || latestEval.status === 'FAILED') return '运行评估'
  if (latestEval.regressed_cases > 0) return '查看退化案例并调整补丁'
  if (!experimentReport) return '运行策略 A/B'
  if (patch.approval_status === 'CANDIDATE') return '回到案例库晋级复核'
  if (patch.approval_status === 'APPROVED') return '观察知识版本回归'
  return '保留审计记录'
}

function buildEvaluationRunGovernance(latestEval: EvaluationRunItem) {
  const boundaryViolation = evaluationRunBoundaryViolation(latestEval)
  let blocker = '无阻断，等待人工复核'
  if (boundaryViolation) {
    blocker = boundaryViolation
  } else if (latestEval.status === 'FAILED') {
    blocker = latestEval.error || '评估失败'
  } else if (latestEval.regressed_cases > 0) {
    blocker = `存在 ${latestEval.regressed_cases} 个退化案例`
  } else if (latestEval.total_cases <= 0) {
    blocker = '缺少评估案例'
  } else if (latestEval.status !== 'COMPLETED') {
    blocker = `评估状态 ${latestEval.status || 'UNKNOWN'}`
  }

  const nextAction = boundaryViolation
    ? '停止晋级，先修复评估审计边界'
    : latestEval.status === 'FAILED'
      ? '修复失败原因后重新运行评估'
      : latestEval.regressed_cases > 0
        ? '查看退化案例并调整补丁'
        : blocker === '无阻断，等待人工复核'
          ? '仅作为 review_gate_only 证据，等待人工复核'
          : '补齐评估证据后再进入知识版本复核'

  return {
    contextId: latestEval.eval_id,
    evidenceStrength: evaluationEvidenceStrengthLabel(latestEval, null),
    blocker,
    nextAction,
    simulationOnly: latestEval.simulation_only === true,
    isRealTrade: latestEval.is_real_trade === true,
    evidenceUsage: latestEval.evidence_usage,
    strongConclusionAllowed: latestEval.strong_conclusion_allowed === true,
  }
}

function strategyExperimentEvidenceStrength(report: StrategyExperimentReport) {
  const normalized = String(report.evidence_strength || '').toUpperCase()
  if (['MISSING', 'PENDING'].includes(normalized)) return normalized
  return 'LOW'
}

function buildStrategyExperimentGovernance(patch: KnowledgePatchItem, report: StrategyExperimentReport) {
  const candidate = patch.approval_status === 'CANDIDATE'
  const simulationOnly = report.simulation_only === true
  const isRealTrade = report.is_real_trade === true
  const hasBoundaryViolation = !simulationOnly || isRealTrade || report.strong_conclusion_allowed === true
  let blocker = `补丁状态 ${patch.approval_status}；实验结果只能作为事后观察`
  let nextAction = '保留实验报告，纳入 Knowledge Version 回归观察'
  if (hasBoundaryViolation) {
    blocker = 'Strategy experiment simulation-only boundary missing or violated'
    nextAction = '停止晋级，先修复策略实验审计边界'
  } else if (candidate) {
    blocker = '策略 A/B 只能辅助补丁评估，不能单独晋级知识补丁'
    nextAction = '回到 Case Library，结合评估 run 和人工复核后再申请晋级'
  }

  return {
    contextId: report.experiment_id,
    evidenceStrength: strategyExperimentEvidenceStrength(report),
    blocker,
    nextAction,
    simulationOnly,
    isRealTrade,
    evidenceUsage: report.evidence_usage,
    strongConclusionAllowed: report.strong_conclusion_allowed === true,
  }
}

function buildStrategyConfigs(patch: KnowledgePatchItem, latestEval?: EvaluationRunItem) {
  const rawConfigs = patch.patch_content?.strategy_configs
  if (Array.isArray(rawConfigs) && rawConfigs.length >= 2) return rawConfigs

  const backtest = patch.backtest_result || {}
  const totalCases = Math.max(latestEval?.total_cases ?? backtest.cases_tested ?? 1, 1)
  return [
    {
      config_id: 'control',
      label: '当前基线',
      metrics: {
        win_rate: backtest.win_rate ?? backtest.hit_rate ?? 0.5,
        max_drawdown: backtest.max_drawdown ?? backtest.max_drawdown_pct ?? 0.12,
        misjudge_rate: backtest.misjudge_rate ?? backtest.false_positive_rate ?? 0.16,
        manual_review_pass_rate: backtest.manual_review_pass_rate ?? 0.68,
        risk_trigger_rate: backtest.risk_trigger_rate ?? 0.18,
      },
    },
    {
      config_id: 'candidate',
      label: 'Patch candidate',
      parameters: patch.patch_content || {},
      metrics: {
        win_rate: latestEval?.pass_rate ?? backtest.pass_rate ?? 0.58,
        max_drawdown: backtest.max_drawdown_after ?? backtest.max_drawdown ?? 0.1,
        misjudge_rate: latestEval ? latestEval.regressed_cases / totalCases : backtest.misjudge_rate ?? 0.12,
        manual_review_pass_rate: latestEval?.pass_rate ?? backtest.manual_review_pass_rate ?? 0.72,
        risk_trigger_rate: backtest.risk_trigger_rate_after ?? backtest.risk_trigger_rate ?? 0.14,
      },
    },
  ]
}

export function EvaluationSandboxPage() {
  const addToast = useToastStore((s) => s.addToast)
  const operator = useOperatorContext()
  const [patches, setPatches] = useState<KnowledgePatchItem[]>([])
  const [evaluations, setEvaluations] = useState<EvaluationRunItem[]>([])
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState<string | null>(null)
  const [experimenting, setExperimenting] = useState<string | null>(null)
  const [expandedEval, setExpandedEval] = useState<string | null>(null)
  const canRunEvaluationSandbox = roleAllows(operator.role, 'researcher')
  const evaluationSandboxDisabledReason = canRunEvaluationSandbox
    ? undefined
    : `评估沙箱运行需要 researcher 权限。当前角色：${operator.role}。`

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [p, e] = await Promise.all([
        getKnowledgePatches({ limit: 30 }),
        getEvaluations(undefined, 30),
      ])
      setPatches(p)
      setEvaluations(e)
    } catch {
      // Keep the page usable if one request is temporarily unavailable.
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  async function handleEvaluate(patchId: string) {
    if (!canRunEvaluationSandbox) {
      addToast(evaluationSandboxDisabledReason || '评估沙箱运行需要 researcher 权限。', 'error')
      return
    }
    setRunning(patchId)
    try {
      const result = await runPatchEvaluation(patchId, true)
      setEvaluations((prev) => [result, ...prev.filter((e) => e.eval_id !== result.eval_id)])
      addToast(`评估完成：${result.summary.slice(0, 80)}`, 'success')
    } catch (err) {
      addToast(err instanceof Error ? err.message : '评估失败', 'error')
    } finally {
      setRunning(null)
    }
  }

  async function handleExperiment(patch: KnowledgePatchItem, latestEval?: EvaluationRunItem) {
    if (!canRunEvaluationSandbox) {
      addToast(evaluationSandboxDisabledReason || '评估沙箱运行需要 researcher 权限。', 'error')
      return
    }
    setExperimenting(patch.patch_id)
    try {
      const report = await runPatchStrategyExperiment(patch.patch_id, {
        hypothesis: patch.patch_content?.hypothesis || patch.title,
        strategy_configs: buildStrategyConfigs(patch, latestEval),
        sample_window: { source: 'evaluation_sandbox', generated_at: new Date().toISOString() },
      })
      setPatches((prev) => prev.map((item) => (
        item.patch_id === patch.patch_id
          ? {
              ...item,
              backtest_result: {
                ...(item.backtest_result || {}),
                strategy_experiment_report: report,
              },
            }
          : item
      )))
      addToast(`A/B 实验完成：胜出配置 ${report.winner_config_id}`, 'success')
    } catch (err) {
      addToast(err instanceof Error ? err.message : '策略实验失败', 'error')
    } finally {
      setExperimenting(null)
    }
  }

  function getEvalForPatch(patchId: string) {
    return evaluations.filter((e) => e.patch_id === patchId)
  }

  if (loading) return <ResearchLoading label="正在加载评估沙箱..." />

  const completedCount = evaluations.filter((item) => item.status === 'COMPLETED').length
  const backtestRequiredCount = patches.filter((item) => item.backtest_required).length
  const experimentCount = patches.filter((item) => getExperimentReport(item)).length

  return (
    <div data-testid="evaluation-sandbox-page" className="space-y-6">
      <ResearchPageHeader
        eyebrow="评估沙箱"
        title="沙箱评估"
        subtitle="在历史复盘案例上验证知识补丁，查看评估结果、策略 A/B 实验摘要和发布晋级前置证据。"
        icon={Beaker}
        tags={['补丁评估', '策略 A/B', '晋级证据']}
        actions={
          <button
            type="button"
            onClick={load}
            disabled={Boolean(running || experimenting)}
            className="inline-flex items-center gap-2 rounded-md border border-slate-600 bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:opacity-60"
          >
            <RefreshCw size={16} />
            刷新
          </button>
        }
      />

      <div className="rounded-md border border-slate-200 bg-white px-4 py-3 text-xs text-slate-500">
        <span data-testid="evaluation-sandbox-write-role">
          角色：{operator.role}；运行沙箱：{canRunEvaluationSandbox ? 'researcher+' : '已阻断'}
        </span>
        {!canRunEvaluationSandbox ? (
          <span data-testid="evaluation-sandbox-write-disabled-reason" className="ml-3 text-amber-700">{evaluationSandboxDisabledReason}</span>
        ) : null}
      </div>

      <div data-testid="evaluation-sandbox-summary" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <ResearchMetricCard label="知识补丁" value={patches.length} helper="Patches / 待验证对象" icon={Wrench} tone="bg-cyan-50 text-cyan-700" />
        <ResearchMetricCard label="已完成评估" value={completedCount} helper="历史评估次数" icon={CheckCircle2} tone="bg-emerald-50 text-emerald-700" />
        <ResearchMetricCard label="策略实验" value={experimentCount} helper="A/B 实验报告" icon={Split} tone="bg-sky-50 text-sky-700" />
        <ResearchMetricCard label="需回测" value={backtestRequiredCount} helper="Backtest required / 风险提示" icon={AlertTriangle} tone="bg-amber-50 text-amber-700" />
      </div>

      <div className="space-y-4">
        {patches.length === 0 ? (
          <ResearchEmptyState title="暂无知识补丁" description="案例库或研究迭代生成知识补丁后，可在这里运行评估和策略 A/B 实验。" icon={Beaker} />
        ) : (
          patches.map((patch) => {
            const patchEvals = getEvalForPatch(patch.patch_id)
            const latestEval = patchEvals[0]
            const experimentReport = getExperimentReport(patch)
            const winnerMetrics = experimentReport?.metrics_by_strategy?.[experimentReport.winner_config_id]

            return (
              <div
                key={patch.patch_id}
                data-testid={`evaluation-sandbox-patch-${patch.patch_id}`}
                className="rounded-md border border-slate-200 bg-white p-4 shadow-sm"
              >
                <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge status={patch.approval_status === 'APPROVED' ? 'PASS' : 'WARN'}>{patch.approval_status}</Badge>
                      {patch.backtest_required && (
                        <span className="inline-flex items-center gap-1 rounded-md bg-blue-100 px-2 py-1 text-xs text-blue-700">
                          <AlertTriangle size={12} /> 需回测
                        </span>
                      )}
                    </div>
                    <div className="mt-2 text-base font-semibold text-slate-950">{patch.title}</div>
                    <div className="mt-1 text-sm text-slate-500">模块：{patch.affected_modules.join(', ') || 'N/A'}</div>
                    <div data-testid={`evaluation-sandbox-patch-governance-${patch.patch_id}`} className="mt-3 grid gap-2 rounded-md border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600 sm:grid-cols-2 xl:grid-cols-5">
                      <span data-testid={`evaluation-sandbox-patch-id-${patch.patch_id}`} className="min-w-0 break-all">
                        Patch: {patch.patch_id}
                      </span>
                      <span data-testid={`evaluation-sandbox-patch-evidence-strength-${patch.patch_id}`} className="min-w-0 break-words">
                        Evidence: {evaluationEvidenceStrengthLabel(latestEval, experimentReport)}
                      </span>
                      <span data-testid={`evaluation-sandbox-patch-blocker-${patch.patch_id}`} className="min-w-0 break-words">
                        Blocker: {evaluationPatchBlocker(patch, latestEval, canRunEvaluationSandbox)}
                      </span>
                      <span data-testid={`evaluation-sandbox-patch-next-action-${patch.patch_id}`} className="min-w-0 break-words">
                        Next: {evaluationPatchNextAction(patch, latestEval, experimentReport, canRunEvaluationSandbox)}
                      </span>
                      <span data-testid={`evaluation-sandbox-patch-simulation-boundary-${patch.patch_id}`} className="min-w-0 break-words font-medium text-slate-900">
                        simulation_only={String(latestEval?.simulation_only ?? true)} / is_real_trade={String(latestEval?.is_real_trade ?? false)} / evidence_usage={latestEval?.evidence_usage ?? 'review_gate_only'} / strong_conclusion_allowed={String(latestEval?.strong_conclusion_allowed ?? false)} / SIM_*
                      </span>
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      data-testid={`evaluation-sandbox-experiment-${patch.patch_id}`}
                      onClick={() => handleExperiment(patch, latestEval)}
                      disabled={experimenting === patch.patch_id || !canRunEvaluationSandbox}
                      title={evaluationSandboxDisabledReason || undefined}
                      className="inline-flex items-center gap-2 rounded-md border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 disabled:opacity-60"
                    >
                      {experimenting === patch.patch_id ? <RefreshCw size={14} className="animate-spin" /> : <Split size={14} />}
                      策略 A/B
                    </button>
                    <button
                      type="button"
                      data-testid={`evaluation-sandbox-run-${patch.patch_id}`}
                      onClick={() => handleEvaluate(patch.patch_id)}
                      disabled={running === patch.patch_id || !canRunEvaluationSandbox}
                      title={evaluationSandboxDisabledReason || undefined}
                      className="inline-flex items-center gap-2 rounded-md bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:opacity-60"
                    >
                      {running === patch.patch_id ? <RefreshCw size={14} className="animate-spin" /> : <Beaker size={14} />}
                      运行评估
                    </button>
                  </div>
                </div>

                {experimentReport && winnerMetrics && (
                  <div data-testid={`evaluation-sandbox-experiment-report-${patch.patch_id}`} className="mt-4 rounded-md border border-sky-100 bg-sky-50 p-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge status="REVIEW_ONLY">策略 A/B</Badge>
                      <span className="text-xs font-medium text-sky-700">Winner: {experimentReport.winner_config_id}</span>
                      <span className="text-xs text-sky-600">Samples: {experimentReport.sample_window?.case_count ?? '-'}</span>
                    </div>
                    <StrategyExperimentGovernancePanel patch={patch} report={experimentReport} />
                    <div className="mt-3 grid gap-2 sm:grid-cols-5">
                      <div className="rounded-md bg-white p-2 text-xs text-slate-600">胜率 <b className="text-slate-950">{formatPct(winnerMetrics.win_rate)}</b></div>
                      <div className="rounded-md bg-white p-2 text-xs text-slate-600">回撤 <b className="text-slate-950">{formatPct(winnerMetrics.max_drawdown)}</b></div>
                      <div className="rounded-md bg-white p-2 text-xs text-slate-600">误判 <b className="text-slate-950">{formatPct(winnerMetrics.misjudge_rate)}</b></div>
                      <div className="rounded-md bg-white p-2 text-xs text-slate-600">复核通过 <b className="text-slate-950">{formatPct(winnerMetrics.manual_review_pass_rate)}</b></div>
                      <div className="rounded-md bg-white p-2 text-xs text-slate-600">风险触发 <b className="text-slate-950">{formatPct(winnerMetrics.risk_trigger_rate)}</b></div>
                    </div>
                    <div className="mt-2 text-xs leading-5 text-sky-700">{experimentReport.summary}</div>
                  </div>
                )}

                {latestEval && (
                  <div data-testid={`evaluation-sandbox-evaluation-${latestEval.eval_id}`} className="mt-4 space-y-3 border-t border-slate-100 pt-4">
                    {(() => {
                      const evalGovernance = buildEvaluationRunGovernance(latestEval)
                      return (
                        <>
                          <div className="flex flex-wrap items-center gap-2">
                            <Badge status={latestEval.status === 'COMPLETED' ? 'PASS' : latestEval.status === 'FAILED' ? 'FAIL' : 'WARN'}>
                              {latestEval.status}
                            </Badge>
                            <span className="text-xs text-slate-500">{latestEval.elapsed_ms}ms</span>
                          </div>

                          <div data-testid={`evaluation-sandbox-evaluation-governance-${latestEval.eval_id}`} className="grid gap-2 rounded-md border border-emerald-200 bg-emerald-50 p-3 text-xs text-slate-700 sm:grid-cols-2 xl:grid-cols-5">
                            <span data-testid={`evaluation-sandbox-evaluation-id-${latestEval.eval_id}`} className="min-w-0 break-all">
                              Eval: {evalGovernance.contextId}
                            </span>
                            <span data-testid={`evaluation-sandbox-evaluation-evidence-strength-${latestEval.eval_id}`} className="min-w-0 break-words">
                              Evidence: {evalGovernance.evidenceStrength}
                            </span>
                            <span data-testid={`evaluation-sandbox-evaluation-blocker-${latestEval.eval_id}`} className="min-w-0 break-words">
                              Blocker: {evalGovernance.blocker}
                            </span>
                            <span data-testid={`evaluation-sandbox-evaluation-next-action-${latestEval.eval_id}`} className="min-w-0 break-words">
                              Next: {evalGovernance.nextAction}
                            </span>
                            <span data-testid={`evaluation-sandbox-evaluation-simulation-boundary-${latestEval.eval_id}`} className="min-w-0 break-words font-medium text-slate-900">
                              simulation_only={String(evalGovernance.simulationOnly)} / is_real_trade={String(evalGovernance.isRealTrade)} / evidence_usage={evalGovernance.evidenceUsage} / strong_conclusion_allowed={String(evalGovernance.strongConclusionAllowed)} / SIM_*
                            </span>
                          </div>
                        </>
                      )
                    })()}

                    <div className="grid gap-3 sm:grid-cols-5">
                      <div className="rounded-md bg-slate-50 p-3">
                        <div className="text-xs text-slate-400">总案例</div>
                        <div className="text-lg font-bold text-slate-900">{latestEval.total_cases}</div>
                      </div>
                      <div className="rounded-md bg-emerald-50 p-3">
                        <div className="text-xs text-emerald-600">通过</div>
                        <div className="text-lg font-bold text-emerald-700">{latestEval.passed_cases}</div>
                      </div>
                      <div className={`rounded-md p-3 ${latestEval.improved_cases > 0 ? 'bg-green-50' : 'bg-slate-50'}`}>
                        <div className="text-xs text-green-600">改进</div>
                        <div className="text-lg font-bold text-green-700">{latestEval.improved_cases}</div>
                      </div>
                      <div className={`rounded-md p-3 ${latestEval.regressed_cases > 0 ? 'bg-red-50' : 'bg-slate-50'}`}>
                        <div className="text-xs text-red-600">退化</div>
                        <div className="text-lg font-bold text-red-700">{latestEval.regressed_cases}</div>
                      </div>
                      <div className="rounded-md bg-slate-50 p-3">
                        <div className="text-xs text-slate-400">改进率</div>
                        <div className="text-lg font-bold text-slate-900">{formatPct(latestEval.improvement_rate)}</div>
                      </div>
                    </div>

                    <div data-testid={`evaluation-sandbox-evaluation-summary-${latestEval.eval_id}`} className="text-xs text-slate-500">{latestEval.summary}</div>

                    {patchEvals.length > 1 && (
                      <button
                        type="button"
                        onClick={() => setExpandedEval(expandedEval === patch.patch_id ? null : patch.patch_id)}
                        className="inline-flex items-center gap-1 text-xs text-slate-500 hover:text-slate-700"
                      >
                        {expandedEval === patch.patch_id ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                        历史评估 ({patchEvals.length})
                      </button>
                    )}

                    {expandedEval === patch.patch_id && patchEvals.map((ev) => (
                      <div key={ev.eval_id} className="rounded-md border border-slate-100 p-3">
                        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                          <span>{ev.status}</span>
                          <span>|</span>
                          <span>{formatDateTime(ev.created_at)}</span>
                          <span>|</span>
                          <span>改进: {formatPct(ev.improvement_rate)}</span>
                        </div>
                        {ev.per_case_results?.length > 0 && (
                          <div className="mt-2 space-y-1">
                            {ev.per_case_results.map((cr: any, i: number) => (
                              <div key={i} className="flex items-center gap-2 text-xs">
                                {cr.verdict === 'PASS' ? (
                                  <CheckCircle2 size={12} className="text-emerald-500" />
                                ) : (
                                  <AlertTriangle size={12} className="text-amber-500" />
                                )}
                                <span className="text-slate-600">{cr.symbol}</span>
                                <Badge status={cr.improvement === 'IMPROVED' ? 'PASS' : cr.improvement === 'REGRESSED' ? 'FAIL' : 'SKIPPED'}>
                                  {cr.improvement}
                                </Badge>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}

function StrategyExperimentGovernancePanel({
  patch,
  report,
}: {
  patch: KnowledgePatchItem
  report: StrategyExperimentReport
}) {
  const governance = buildStrategyExperimentGovernance(patch, report)
  return (
    <div data-testid={`evaluation-sandbox-experiment-governance-${patch.patch_id}`} className="mt-3 grid gap-2 rounded-md border border-sky-200 bg-white/80 p-3 text-xs text-slate-600 sm:grid-cols-2 xl:grid-cols-5">
      <span className="min-w-0 break-words">
        Experiment:
        <span data-testid={`evaluation-sandbox-experiment-id-${patch.patch_id}`} className="ml-1 break-all font-mono text-slate-500">{governance.contextId}</span>
      </span>
      <span data-testid={`evaluation-sandbox-experiment-evidence-strength-${patch.patch_id}`} className="min-w-0 break-words">
        Evidence: {governance.evidenceStrength}
      </span>
      <span data-testid={`evaluation-sandbox-experiment-blocker-${patch.patch_id}`} className="min-w-0 break-words">
        Blocker: {governance.blocker}
      </span>
      <span data-testid={`evaluation-sandbox-experiment-next-action-${patch.patch_id}`} className="min-w-0 break-words">
        Next: {governance.nextAction}
      </span>
      <span data-testid={`evaluation-sandbox-experiment-simulation-boundary-${patch.patch_id}`} className="min-w-0 break-words font-medium text-slate-900">
        simulation_only={String(governance.simulationOnly)} / is_real_trade={String(governance.isRealTrade)} / evidence_usage={governance.evidenceUsage} / strong_conclusion_allowed={String(governance.strongConclusionAllowed)} / SIM_*
      </span>
    </div>
  )
}
