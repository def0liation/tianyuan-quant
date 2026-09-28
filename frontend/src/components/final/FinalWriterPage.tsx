import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { FileText, XCircle } from 'lucide-react'
import { getAnalysisRunReport } from '../../api/analysisClient'
import { useAnalysisStore } from '../../store/useAnalysisStore'
import type { AnalysisRun, FinalReportAsset } from '../../types'
import { buildConclusionInsights, displayFinalWriterContent } from '../../utils/conclusionInsights'
import { buildDashboardProvenanceSummary } from '../../utils/dataProvenance'
import type { DashboardProvenanceSummary } from '../../utils/dataProvenance'
import { buildRunFailureNotice } from '../../utils/runFailure'
import { SectionTitle } from '../common/SectionTitle'
import { Card } from '../common/Card'
import { Badge } from '../common/Badge'
import { MetricTile, SourceFreshnessPanel, TableShell } from '../common/Material'
import { ConclusionModules } from './ConclusionModules'
import { formatDateTime } from '../../utils/format'

type FinalWriterEvidenceStrength = 'LOW' | 'MEDIUM'

interface FinalWriterGovernance {
  contextId: string
  evidenceStrength: FinalWriterEvidenceStrength
  blocker: string
  nextAction: string
  simulationOnly: boolean
  isRealTrade: boolean
  evidenceUsage: string
  strongConclusionAllowed: boolean
}

function finalWriterActionNeedsReview(action?: string) {
  return action === 'BUY_CANDIDATE' || action === 'ADD_CANDIDATE'
}

function buildFinalWriterGovernance(
  run: AnalysisRun,
  provenanceSummary: DashboardProvenanceSummary,
  hasReportAsset: boolean,
): FinalWriterGovernance {
  const finalWriter = run.finalWriter
  const finalAction = finalWriter?.finalAction ?? run.finalAction
  const sectionCount = finalWriter?.sections?.length ?? 0
  const paperTrading = run.paperTrading
  const finalWriterEvidence = finalWriter as typeof finalWriter & {
    evidenceUsage?: string
    evidence_usage?: string
    strongConclusionAllowed?: boolean
    strong_conclusion_allowed?: boolean
  }
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
  const evidenceUsage =
    finalWriterEvidence?.evidenceUsage
    ?? finalWriterEvidence?.evidence_usage
    ?? paperTradingEvidence.evidenceUsage
    ?? paperTradingEvidence.evidence_usage
    ?? 'simulation_only'
  const strongConclusionAllowed =
    finalWriterEvidence?.strongConclusionAllowed === true
    || finalWriterEvidence?.strong_conclusion_allowed === true
    || paperTradingEvidence.strongConclusionAllowed === true
    || paperTradingEvidence.strong_conclusion_allowed === true
  const evidenceBoundaryBroken = evidenceUsage !== 'simulation_only' || strongConclusionAllowed
  const boundaryBroken =
    !simulationOnly
    || isRealTrade
    || namespace !== 'SIM_*'
    || (latestAction ? !latestAction.startsWith('SIM_') : false)
    || evidenceBoundaryBroken
  const weakProvenance = provenanceSummary.level === 'LOW' || provenanceSummary.level === 'UNKNOWN'
  const actionReviewMissing = finalWriterActionNeedsReview(finalAction) && finalWriter?.humanConfirmationRequired !== true
  const blocker = boundaryBroken
    ? 'SIMULATION_BOUNDARY_VIOLATED'
    : !finalWriter
      ? 'MISSING_FINAL_WRITER'
      : sectionCount === 0
        ? 'MISSING_REPORT_SECTIONS'
        : run.status !== 'COMPLETED'
          ? 'RUN_NOT_COMPLETED'
          : weakProvenance
            ? 'WEAK_SOURCE_PROVENANCE'
            : actionReviewMissing
              ? 'ACTION_REVIEW_REQUIRED'
              : !hasReportAsset
                ? 'REPORT_ASSET_NOT_PERSISTED'
                : 'NONE'
  const evidenceStrength: FinalWriterEvidenceStrength = boundaryBroken || !finalWriter || sectionCount === 0 || run.status !== 'COMPLETED' || weakProvenance || !hasReportAsset || actionReviewMissing
    ? 'LOW'
    : 'MEDIUM'
  const nextAction = blocker === 'NONE'
    ? '可进入 Case / Knowledge / Evaluation 仅模拟复核'
    : blocker === 'REPORT_ASSET_NOT_PERSISTED'
      ? '等待最终报告资产落库后再作为复核输入'
      : blocker === 'ACTION_REVIEW_REQUIRED'
        ? '补充人工确认；最终输出不能生成真实交易动作'
        : '先修复来源、章节、运行状态或模拟边界'

  return {
    contextId: finalWriter?.auditId || run.finalReportAsset?.auditId || run.runId,
    evidenceStrength,
    blocker,
    nextAction,
    simulationOnly,
    isRealTrade,
    evidenceUsage,
    strongConclusionAllowed,
  }
}

export function FinalWriterPage() {
  const { currentRun, currentRunId: storeRunId, refreshRun } = useAnalysisStore()
  const [searchParams] = useSearchParams()
  const [reportAsset, setReportAsset] = useState<FinalReportAsset | null>(null)
  const [deepLinkError, setDeepLinkError] = useState('')
  const hydrationAttemptRef = useRef('')
  const currentRunId = currentRun?.runId
  const linkedRunId = searchParams.get('run_id')?.trim() || ''
  const hasFinalWriter = Boolean(currentRun?.finalWriter)
  const reportDependency = currentRun?.finalReportAsset?.reportId ?? currentRun?.finalWriter?.auditId ?? ''

  useEffect(() => {
    if (!linkedRunId || storeRunId === linkedRunId) return
    if (hydrationAttemptRef.current === linkedRunId) return
    hydrationAttemptRef.current = linkedRunId
    setDeepLinkError('')
    refreshRun(linkedRunId).catch((error) => {
      setDeepLinkError(error instanceof Error ? error.message : '加载运行失败')
    })
  }, [linkedRunId, refreshRun, storeRunId])

  useEffect(() => {
    let cancelled = false
    if (!currentRunId || !hasFinalWriter) {
      setReportAsset(null)
      return
    }
    getAnalysisRunReport(currentRunId)
      .then((report) => {
        if (!cancelled) setReportAsset(report)
      })
      .catch(() => {
        if (!cancelled) setReportAsset(null)
      })
    return () => {
      cancelled = true
    }
  }, [currentRunId, hasFinalWriter, reportDependency])

  if (!currentRun || (linkedRunId && currentRun.runId !== linkedRunId)) {
    return (
      <div data-testid="final-writer-page-loading" className="text-sm text-slate-500">
        正在加载最终报告...
        {linkedRunId ? <span className="ml-2 font-mono">{linkedRunId}</span> : null}
        {deepLinkError ? <div className="mt-2 text-red-600">{deepLinkError}</div> : null}
      </div>
    )
  }

  const finalWriter = currentRun.finalWriter
  const insights = buildConclusionInsights(currentRun)
  const finalAction = finalWriter?.finalAction ?? currentRun.finalAction
  const provenanceSummary = buildDashboardProvenanceSummary(currentRun)
  const finalWriterGovernance = buildFinalWriterGovernance(currentRun, provenanceSummary, Boolean(reportAsset || currentRun.finalReportAsset))
  const failureNotice =
    ['FAILED', 'STALE'].includes(currentRun.status) ? buildRunFailureNotice(currentRun, '最终结论需复核') : undefined

  return (
    <div className="space-y-5" data-testid="final-writer-page">
      <SectionTitle title="最终输出" subtitle="按模块查看结论、推导依据、基本面、技术面和数据核验清单。" dataMode={currentRun?.dataMode} />
      <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-500">
        Run ID: <span data-testid="final-writer-current-run-id" className="break-all font-mono text-slate-700">{currentRun.runId}</span>
      </div>
      <div data-testid="final-writer-governance" className="grid gap-2 rounded-md border border-cyan-200 bg-white/80 p-3 text-xs text-slate-700 sm:grid-cols-2 xl:grid-cols-5">
        <span data-testid="final-writer-governance-id" className="min-w-0 break-words font-mono">
          Context: {finalWriterGovernance.contextId}
        </span>
        <span data-testid="final-writer-evidence-strength" className="min-w-0 break-words">
          Evidence: {finalWriterGovernance.evidenceStrength}
        </span>
        <span data-testid="final-writer-blocker" className="min-w-0 break-words">
          Blocker: {finalWriterGovernance.blocker}
        </span>
        <span data-testid="final-writer-next-action" className="min-w-0 break-words">
          Next: {finalWriterGovernance.nextAction}
        </span>
        <span data-testid="final-writer-simulation-boundary" className="min-w-0 break-words font-medium text-slate-900">
          simulation_only={String(finalWriterGovernance.simulationOnly)} / is_real_trade={String(finalWriterGovernance.isRealTrade)} / evidence_usage={finalWriterGovernance.evidenceUsage} / strong_conclusion_allowed={String(finalWriterGovernance.strongConclusionAllowed)} / SIM_*
        </span>
      </div>

      {failureNotice && (
        <div className="rounded-md border border-red-200 bg-red-50 p-4">
          <div className="flex items-start gap-3">
            <XCircle className="mt-0.5 h-5 w-5 flex-shrink-0 text-red-600" />
            <div className="flex-1 min-w-0">
              <h3 className="text-sm font-semibold text-red-700">{failureNotice.title}</h3>
              <p className="mt-1 text-xs leading-5 text-red-700">
                {failureNotice.description}
              </p>
            </div>
          </div>
        </div>
      )}

      <Card title="报告数据可信前置说明" className="!rounded-lg !shadow-none">
        <div data-testid="final-writer-data-provenance" className="grid gap-4 lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)]">
          <div className="rounded-md border border-[#d2e3fc] bg-[#e8f0fe] p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-[#1967d2]">数据可信等级</div>
                <div className="mt-2 text-2xl font-semibold text-slate-950">{provenanceSummary.label}</div>
              </div>
              <Badge status={provenanceSummary.status} className="!rounded-md px-2 py-0.5">{provenanceSummary.level}</Badge>
            </div>
            <div className="mt-3 text-sm leading-6 text-slate-600">{provenanceSummary.headline}</div>
            <div className="mt-3 flex flex-wrap gap-1.5">
              {(['LIVE', 'FALLBACK', 'MOCK', 'MISSING', 'USER_INPUT'] as const).map((kind) => (
                provenanceSummary.sourceCounts[kind] > 0 ? (
                  <span key={kind} className="rounded-md border border-slate-200 bg-white px-2 py-0.5 text-[11px] font-semibold text-slate-600">
                    {kind === 'USER_INPUT' ? 'USER_INPUT_ONLY' : kind}: {provenanceSummary.sourceCounts[kind]}
                  </span>
                ) : null
              ))}
            </div>
          </div>

          <div>
            <SourceFreshnessPanel
              className="mb-3"
              sources={(provenanceSummary.freshnessItems.length ? provenanceSummary.freshnessItems : [{
                key: 'final-writer:freshness:none',
                label: 'No source freshness recorded',
                freshness: 'unknown',
                status: 'WAIT',
              }]).slice(0, 4).map((item) => ({
                label: item.label,
                freshness: item.freshness,
                mode: String(('provider' in item ? item.provider || item.status : item.status) ?? ''),
              }))}
            />
            <TableShell className="!rounded-lg !shadow-none">
            <table className="institution-table">
              <thead className="bg-slate-50">
                <tr className="text-left font-semibold uppercase tracking-wide text-slate-500">
                  <th className="px-3 py-2">检查项</th>
                  <th className="px-3 py-2">证据</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 bg-white">
                <tr data-testid="final-writer-source-freshness">
                  <td className="px-3 py-2 font-medium text-slate-900">数据源新鲜度</td>
                  <td className="px-3 py-2 leading-5 text-slate-600">
                    {(provenanceSummary.freshnessItems.length ? provenanceSummary.freshnessItems : [{
                      key: 'freshness:none',
                      label: 'No source freshness recorded',
                      status: 'WAIT',
                      freshness: 'unknown',
                      detail: 'No source freshness recorded',
                    }]).slice(0, 4).map((item) => (
                      <div key={item.key}>
                        <span className="font-semibold text-slate-700">{item.label}</span>: {item.freshness}
                      </div>
                    ))}
                  </td>
                </tr>
                <tr>
                  <td className="px-3 py-2 font-medium text-slate-900">Fallback 链</td>
                  <td className="px-3 py-2 leading-5 text-slate-600">
                    {(provenanceSummary.fallbackChain.length ? provenanceSummary.fallbackChain : ['无 fallback / 降级链']).slice(0, 4).map((item) => <div key={item}>{item}</div>)}
                  </td>
                </tr>
                <tr>
                  <td className="px-3 py-2 font-medium text-slate-900">缺失字段</td>
                  <td className="px-3 py-2 leading-5 text-slate-600">
                    {(provenanceSummary.missingFields.length ? provenanceSummary.missingFields : ['无核心缺失字段']).slice(0, 6).map((item) => <div key={item}>{item}</div>)}
                  </td>
                </tr>
                <tr>
                  <td className="px-3 py-2 font-medium text-slate-900">人工复核点</td>
                  <td className="px-3 py-2 leading-5 text-slate-600">
                    {(provenanceSummary.reviewPoints.length ? provenanceSummary.reviewPoints : ['当前无额外人工复核点']).slice(0, 5).map((item) => <div key={item}>{item}</div>)}
                  </td>
                </tr>
              </tbody>
            </table>
            </TableShell>
          </div>
        </div>
      </Card>

      <div className="grid gap-6 md:grid-cols-2 xl:grid-cols-4">
        <MetricTile label="最终动作" value={<span data-testid="final-writer-final-action">{finalAction}</span>} helper="只表达上游允许的动作" tone={finalAction === 'WAIT' ? 'warning' : 'success'} />
        <MetricTile label="人工确认" value={finalWriter?.humanConfirmationRequired === false ? '不需要' : '需要'} tone={finalWriter?.humanConfirmationRequired === false ? 'success' : 'warning'} />
        <MetricTile label="输出模式" value={finalWriter?.mode ?? currentRun.killSwitch.finalWriterMode} tone="info" />
        <MetricTile label="审计 ID" value={<span className="break-all text-sm">{finalWriter?.auditId ?? 'N/A'}</span>} />
      </div>

      {(reportAsset || currentRun.finalReportAsset) && (
        <Card title="报告资产" className="!rounded-lg !shadow-none">
          <TableShell className="!rounded-lg !shadow-none">
            <table className="institution-table">
              <thead className="bg-slate-50">
                <tr className="text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                  <th className="px-3 py-2">资产</th>
                  <th className="px-3 py-2">值</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 bg-white">
                <tr>
                  <td className="px-3 py-2 font-medium text-slate-900">
                    <span className="inline-flex items-center gap-2"><FileText size={14} />Report ID</span>
                  </td>
                  <td className="break-all px-3 py-2 font-mono text-xs text-slate-700">{reportAsset?.report_id ?? currentRun.finalReportAsset?.reportId}</td>
                </tr>
                <tr>
                  <td className="px-3 py-2 font-medium text-slate-900">模式</td>
                  <td className="px-3 py-2 text-slate-700">{reportAsset?.final_writer_mode ?? finalWriter?.mode ?? currentRun.killSwitch.finalWriterMode}</td>
                </tr>
                <tr>
                  <td className="px-3 py-2 font-medium text-slate-900">更新时间</td>
                  <td className="px-3 py-2 text-slate-700">{formatDateTime(reportAsset?.updated_at ?? currentRun.finalReportAsset?.updatedAt)}</td>
                </tr>
              </tbody>
            </table>
          </TableShell>
        </Card>
      )}

      <ConclusionModules modules={insights} />

      {finalWriter?.sections?.length ? (
        <Card title="模型原始章节" className="!rounded-lg !shadow-none">
          <div data-testid="final-writer-sections" className="grid gap-4 lg:grid-cols-2">
            {finalWriter.sections.map((section, index) => (
              <div key={`${section.title}-${index}`} className="rounded-md border border-slate-200 bg-white p-4">
                <div className="flex items-center justify-between gap-3">
                  <div className="font-medium text-slate-900">{section.title}</div>
                  <Badge status={section.riskLevel === 'LOW' ? 'PASS' : section.riskLevel === 'MEDIUM' ? 'WARN' : 'FAIL'} className="!rounded-md px-2 py-0.5">
                    {section.riskLevel}
                  </Badge>
                </div>
                <div className="mt-3 text-sm leading-6 text-slate-600">
                  {displayFinalWriterContent(section.content)}
                </div>
              </div>
            ))}
          </div>
        </Card>
      ) : null}
    </div>
  )
}
