import { useState, useEffect, useCallback, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  createBacktestRun,
  createBacktestParameterScan,
  createBacktestParameterScanJob,
  getBacktestParameterScanJob,
  cancelBacktestParameterScanJob,
  handoffBacktestParameterScanJob,
  createSignalOpsBacktestSample,
  createSignalOpsRandomValidationJob,
  listBacktestRuns,
  listBacktestParameterScans,
  getBacktestRun,
  getBacktestTrades,
  getBacktestSignals,
  getBacktestExperimentPackage,
  getSignalOpsRandomValidationJob,
  cancelSignalOpsRandomValidationJob,
  deleteBacktestRun,
  getBacktestSummary,
} from '../../api/backtestClient'
import { createResearchBacktestVerdictInputs } from '../../api/researchClient'
import { reportError } from '../../utils/errorReport'
import type {
  BacktestParameterScanResponse,
  BacktestParameterScanHistoryItem,
  BacktestParameterScanJob,
  BacktestParameterScanJobHandoff,
  BacktestParameterScanRequest,
  BacktestParameterScanWindow,
  BacktestRunItem,
  BacktestTradeItem,
  BacktestSignalItem,
  BacktestReport,
  BacktestComparison,
  BacktestSummary,
  SignalOpsRandomValidationJob,
  SignalOpsRandomValidationMode,
} from '../../types'
import { Card } from '../common/Card'
import { SectionTitle } from '../common/SectionTitle'
import { MetricTile, TableShell } from '../common/Material'
import { roleAllows, useOperatorContext } from '../../store/operatorContext'
import {
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  AreaChart,
  Area,
} from 'recharts'
import {
  Play,
  Trash2,
  TrendingUp,
  TrendingDown,
  Activity,
  CheckCircle2,
  XCircle,
  BarChart3,
  Signal,
  ArrowLeftRight,
  Loader2,
  Download,
  AlertTriangle,
  Target,
  DollarSign,
  Shield,
  Clock,
  SlidersHorizontal,
  Shuffle,
  RefreshCw,
  Square,
  UploadCloud,
} from 'lucide-react'

/* ───────── helpers ───────── */
const fmtPct = (v: number) => `${(v * 100).toFixed(1)}%`
const fmtNum = (v: number) => v.toLocaleString('en-US', { maximumFractionDigits: 2 })
const cls = (...a: (string | false | undefined)[]) => a.filter(Boolean).join(' ')
const STATUS_LABELS: Record<string, string> = {
  COMPLETED: '已完成',
  PENDING: '等待中',
  RUNNING: '运行中',
  FAILED: '失败',
  IDEA: '想法',
  WATCH: '观察',
  PAPER_TEST: '模拟测试',
  QUALIFIED: '已合格',
  TRADE_PLAN: '交易计划',
  MANUAL_CONFIRMED: '人工确认',
  EXECUTION_REVIEW: '执行复核',
  CLOSED: '已关闭',
  PATCH_REQUIRED: '需补丁',
  REVIEW_ONLY: '仅复核',
}
const DIRECTION_LABELS: Record<string, string> = {
  BUY: '买入',
  SELL: '卖出',
  HOLD: '持有',
  WAIT: '等待',
  WATCH: '观察',
  LONG: '做多',
  SHORT: '做空',
}
const VERDICT_LABELS: Record<string, string> = {
  IMPROVED: '已改善',
  REGRESSED: '已退化',
  NO_REGRESSION: '无明显退化',
}
const SIGNAL_SOURCE_LABELS: Record<string, string> = {
  MOCK: '模拟信号',
  SIGNALOPS: 'SignalOps',
  BOTTOM_RESEARCH: 'MFE/MAE路径研究',
  MFE_MAE_PATH_RESEARCH: 'MFE/MAE路径研究',
  NONE: '无信号',
}
const SIGNALOPS_ACTION_LABELS: Record<string, string> = {
  SIM_BUY: '模拟买入',
  SIM_SELL: '模拟卖出',
  SIM_CLOSE: '模拟平仓',
  SIM_HOLD: '模拟持有',
  SIM_T_BUY: '模拟做 T 买回',
  SIM_T_SELL: '模拟做 T 卖出',
  SIM_SHORT: '模拟做空',
  SIM_COVER: '模拟回补',
}
const SOURCE_NODE_LABELS: Record<string, string> = {
  signalops_auto_paper_cleaned_history: '自动模拟清洗记录',
  signalops_lifecycle: '生命周期信号',
  signalops_random_strategy_replay: '随机验证策略回放',
  bottom_research: 'MFE/MAE路径研究',
  mfe_mae_path_research: 'MFE/MAE路径研究',
}
const RANDOM_JOB_STATUS_LABELS: Record<string, string> = {
  QUEUED: '排队中',
  RUNNING: '运行中',
  COMPLETED: '已完成',
  FAILED: '失败',
  CANCELLED: '已取消',
}
const RANDOM_PROGRESS_LABELS: Record<string, string> = {
  QUEUED: '等待调度',
  UNIVERSE: '加载全 A 股票池',
  SAMPLE_1: '抽取第一段样本',
  REPLAY_1: '回放当前策略',
  SAMPLE_2: '抽取第二段样本',
  BASELINE_2: '验证原策略',
  CANDIDATE_2: '验证微调候选',
  SYNC_SIGNALOPS: '同步 SignalOps 依据',
  COMPLETED: '已完成',
  FAILED: '失败',
  CANCELLED: '已取消',
}
const EVIDENCE_LEVEL_LABELS: Record<string, string> = {
  MEDIUM: '中证据',
  LOW: '低证据',
  WEAK: '弱证据',
  PENDING: '待生成',
}
const RANDOM_REJECTION_REASON_LABELS: Record<string, string> = {
  untrusted_market_data: '行情数据不可信',
  insufficient_trading_days: '有效交易日不足',
  missing_complete_trade_loop: '缺少完整买卖闭环',
  candidate_worse_than_baseline: '候选策略弱于原策略',
  weak_evidence: '证据等级偏弱',
  validate_only_mode: '仅验证模式',
  review_queue_sync_failed: 'SignalOps 同步失败',
}
const displayStatus = (status?: string) => STATUS_LABELS[status ?? ''] ?? status ?? '-'
const displayDirection = (direction?: string) => DIRECTION_LABELS[direction ?? ''] ?? direction ?? '-'
const displayVerdict = (verdict?: string) => VERDICT_LABELS[verdict ?? ''] ?? verdict ?? '-'
const displaySignalSource = (source?: string | null) => SIGNAL_SOURCE_LABELS[source ?? ''] ?? source ?? '模拟信号'
const displayRandomStatus = (status?: string) => RANDOM_JOB_STATUS_LABELS[status ?? ''] ?? status ?? '-'
const displayRandomProgress = (progress?: string) => RANDOM_PROGRESS_LABELS[progress ?? ''] ?? progress ?? '-'
function normalizeEvidenceLevel(level?: string) {
  const normalized = String(level || '').trim().toUpperCase()
  if (['RESEARCH_GRADE', 'PRIMARY_EVIDENCE_READY'].includes(normalized)) return 'MEDIUM'
  if (['STRONG', 'HIGH', 'PRIMARY', 'PRIMARY_EVIDENCE', 'PASS', 'READY'].includes(normalized)) return 'MEDIUM'
  if (['UNKNOWN', 'SUPPORTING_ONLY', 'WEAK', 'WARN', 'WARNING', 'REVIEW', 'REVIEW_ONLY'].includes(normalized)) return 'LOW'
  return normalized
}
const displayEvidenceLevel = (level?: string) => {
  const normalized = normalizeEvidenceLevel(level)
  return normalized ? EVIDENCE_LEVEL_LABELS[normalized] ?? normalized : '-'
}
const displayBoolFlag = (value: unknown) => value === true ? '是' : value === false ? '否' : '-'
const displaySourceNode = (sourceNode?: string) => SOURCE_NODE_LABELS[sourceNode ?? ''] ?? sourceNode ?? '-'
const displayRandomRejectionReason = (reason?: string) =>
  RANDOM_REJECTION_REASON_LABELS[reason ?? ''] ?? reason ?? '-'
const asRecord = (value: unknown): Record<string, any> =>
  value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, any> : {}
const isRandomJobActive = (job?: SignalOpsRandomValidationJob | null) =>
  Boolean(job && ['QUEUED', 'RUNNING'].includes(String(job.status)))
const isParameterScanJobActive = (job?: BacktestParameterScanJob | null) =>
  Boolean(job && ['QUEUED', 'RUNNING', 'RECOVERING'].includes(String(job.status)))
const displaySignalType = (signalType?: string) => {
  const normalized = String(signalType || '').trim().toUpperCase()
  if (!normalized) return '-'
  if (normalized.startsWith('SIGNALOPS_AUTO_')) {
    const action = normalized.replace('SIGNALOPS_AUTO_', '')
    return `SignalOps 自动-${SIGNALOPS_ACTION_LABELS[action] ?? displayDirection(action)}`
  }
  if (normalized.startsWith('SIGNALOPS_REPLAY_')) {
    return `SignalOps 回放-${displayDirection(normalized.replace('SIGNALOPS_REPLAY_', ''))}`
  }
  if (normalized.startsWith('SIGNALOPS_')) {
    return `SignalOps-${displayStatus(normalized.replace('SIGNALOPS_', ''))}`
  }
  return DIRECTION_LABELS[normalized] ? `${DIRECTION_LABELS[normalized]}信号` : signalType || '-'
}
const hasReport = (report?: Partial<BacktestReport> | null): report is BacktestReport =>
  !!report && typeof report.total_trades === 'number' && typeof report.final_capital === 'number'
const getReportMeta = (report: BacktestReport) => report as BacktestReport & {
  sampleWindow?: Record<string, any>
  evidenceStrength?: Record<string, any>
  evidence_strength?: Record<string, any>
  researchGradeScore?: Record<string, any>
  research_grade_score?: Record<string, any>
  limitations?: string[]
  provenance?: Record<string, any>
  validationProtocol?: Record<string, any>
}
const displayText = (value: unknown, fallback = '-') => {
  const normalized = String(value ?? '').trim()
  return normalized || fallback
}
const firstNonEmptyRecord = (...values: unknown[]) => {
  for (const value of values) {
    const record = asRecord(value)
    if (Object.keys(record).length) return record
  }
  return {}
}
const displayDateRange = (value: unknown) => {
  const record = asRecord(value)
  const start = displayText(record.startDate ?? record.start ?? record.from, '')
  const end = displayText(record.endDate ?? record.end ?? record.to, '')
  if (start && end) return `${start} -> ${end}`
  return start || end || '-'
}
const displayProtocolNumber = (value: unknown) => {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? fmtNum(parsed) : '-'
}
const displayProtocolPercent = (value: unknown) => {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? `${fmtNum(parsed)}%` : '-'
}
const displayProtocolList = (value: unknown) => (
  Array.isArray(value) && value.length ? value.map((item) => displayText(item)).join(' / ') : '-'
)
const compactHash = (value: unknown) => {
  const normalized = displayText(value, '')
  if (!normalized) return '-'
  return normalized.length > 18 ? `${normalized.slice(0, 10)}...${normalized.slice(-6)}` : normalized
}
const signalMetadata = (signal: BacktestSignalItem) =>
  (signal.metadata_json && typeof signal.metadata_json === 'object' ? signal.metadata_json : {}) as Record<string, any>
const signalOpsVersionFor = (signal: BacktestSignalItem, report?: BacktestReport | null) =>
  signalMetadata(signal).signalops_version || (report ? getReportMeta(report).provenance?.signalOpsVersion : undefined) || '-'
const signalOpsSimulationOnlyFor = (signal: BacktestSignalItem, report?: BacktestReport | null) =>
  displayBoolFlag(signalMetadata(signal).simulation_only ?? (report ? getReportMeta(report).provenance?.simulationOnly : undefined))

/* ───────── StatBadge ───────── */
function StatBadge({
  icon: Icon,
  label,
  value,
  suffix = '',
  variant = 'neutral',
}: {
  icon: React.ElementType
  label: string
  value: string | number
  suffix?: string
  variant?: 'good' | 'bad' | 'neutral' | 'accent'
}) {
  const tone = variant === 'good' ? 'success' : variant === 'bad' ? 'danger' : variant === 'accent' ? 'primary' : 'neutral'
  return (
    <MetricTile
      icon={Icon}
      label={label}
      value={suffix ? <>{value}<span className="ml-0.5 text-sm font-semibold">{suffix}</span></> : value}
      tone={tone}
      className="!rounded-lg !p-3 !shadow-none"
    />
  )
}

/* ───────── MiniSparkline ───────── */
function MiniSparkline({ data, color = '#10b981' }: { data: number[]; color?: string }) {
  if (!data.length) return null
  const min = Math.min(...data)
  const max = Math.max(...data)
  const range = max - min || 1
  const points = data.map((v, i) => `${(i / (data.length - 1 || 1)) * 60},${40 - ((v - min) / range) * 30}`).join(' ')
  return (
    <svg width="60" height="40" className="opacity-60">
      <polyline fill="none" stroke={color} strokeWidth="1.5" points={points} />
    </svg>
  )
}

/* ───────── Loading ───────── */
function Loading({ label }: { label: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-12 text-slate-400">
      <Loader2 size={18} className="animate-spin" />
      <span className="text-sm">{label}</span>
    </div>
  )
}

/* ───────── EmptyState ───────── */
function EmptyState({ icon: Icon, text }: { icon: React.ElementType; text: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-slate-300">
      <Icon size={40} strokeWidth={1.2} />
      <p className="mt-2 text-sm">{text}</p>
    </div>
  )
}

/* ───────── ReportPanel ───────── */
function ReportPanel({ report }: { report: BacktestReport }) {
  if (!hasReport(report)) return <EmptyState icon={BarChart3} text="暂无报告数据" />

  const meta = getReportMeta(report)
  const isProfit = report.total_pnl >= 0
  const equityData = report.equity_curve?.map((p) => ({
    date: p.date.slice(5),
    capital: p.capital,
    pnl: p.position_pnl,
  }))
  const validationProtocol = asRecord(meta.validationProtocol)
  const validationOutOfSample = firstNonEmptyRecord(validationProtocol.outOfSample, meta.outOfSampleWindow)
  const validationWalkForward = asRecord(validationProtocol.walkForward)
  const validationParameterScan = asRecord(validationProtocol.parameterScan)
  const validationBenchmark = firstNonEmptyRecord(validationProtocol.benchmark, meta.benchmark)
  const reportBenchmark = asRecord(meta.benchmark)
  const validationHashes = firstNonEmptyRecord(validationProtocol.packageHashes, meta.provenance)
  const walkForwardWindows = Array.isArray(validationWalkForward.windows) ? validationWalkForward.windows : []
  const requiredComponents = Array.isArray(validationProtocol.requiredForResearchGrade)
    ? validationProtocol.requiredForResearchGrade
    : validationProtocol.researchGradeComponents

  return (
      <div data-testid="backtest-report-panel" className="space-y-5">
      {meta.evidenceStrength?.weakSample && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          <div className="font-semibold">弱样本证据</div>
          <div className="mt-1">
            本次回测可用于复核，但仅作为辅助证据，不能支撑强研究结论。
          </div>
          {meta.limitations && meta.limitations.length > 0 && (
            <ul className="mt-2 list-disc pl-5 text-xs">
              {meta.limitations.slice(0, 3).map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {meta.researchGradeScore && (
        <div data-testid="backtest-research-grade-score" className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">研究等级评分</div>
              <div className="mt-1 text-2xl font-bold text-slate-900">{meta.researchGradeScore.score ?? '-'} / 100</div>
            </div>
            <div className="rounded-md bg-white px-3 py-2 text-xs font-semibold text-slate-700">
              {meta.researchGradeScore.band || 'UNKNOWN'} · {meta.researchGradeScore.researchUsage || meta.evidenceStrength?.researchUsage || '-'}
            </div>
          </div>
          {Array.isArray(meta.researchGradeScore.components) && (
            <div className="mt-3 grid gap-2 md:grid-cols-3">
              {meta.researchGradeScore.components.map((component: Record<string, any>) => (
                <div key={String(component.key)} className="rounded-md bg-white px-3 py-2">
                  <div className="text-xs text-slate-500">{component.label || component.key}</div>
                  <div className="mt-1 text-sm font-semibold text-slate-900">{component.score ?? '-'} / 100</div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {meta.validationProtocol && (
        <div data-testid="backtest-validation-protocol" className="rounded-lg border border-cyan-100 bg-cyan-50 px-4 py-3 text-xs text-cyan-900">
          <div className="font-semibold">Validation protocol: {meta.validationProtocol.version || '-'}</div>
          <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
            <span>Parameter scan: {displayBoolFlag(meta.validationProtocol.parameterScan?.enabled)}</span>
            <span>Walk-forward: {displayBoolFlag(meta.validationProtocol.walkForward?.enabled)}</span>
            <span>Benchmark: {displayBoolFlag(meta.validationProtocol.benchmark?.available)}</span>
            <span>Data package: {meta.validationProtocol.packageHashes?.dataPackageHash || '-'}</span>
          </div>
        </div>
      )}

      {meta.validationProtocol && (
        <div data-testid="backtest-validation-detail" className="rounded-lg border border-indigo-100 bg-indigo-50 px-4 py-3 text-xs text-indigo-950">
          <div className="font-semibold">Research validation detail / 研究验证详情</div>
          <div className="mt-2 grid gap-2 md:grid-cols-2">
            <div data-testid="backtest-validation-out-of-sample" className="rounded-md border border-indigo-100 bg-white px-3 py-2">
              <div className="font-medium text-indigo-950">Out-of-sample / 样本外</div>
              <div className="mt-1 grid gap-1 text-indigo-800">
                <span>Window: {displayDateRange(validationOutOfSample)}</span>
                <span>Configured: {displayBoolFlag(validationOutOfSample.configured)}</span>
                <span>Overlaps sample: {displayBoolFlag(validationOutOfSample.overlapsSample)}</span>
                <span>Reason: {displayText(validationOutOfSample.reason)}</span>
              </div>
            </div>
            <div data-testid="backtest-validation-walk-forward" className="rounded-md border border-indigo-100 bg-white px-3 py-2">
              <div className="font-medium text-indigo-950">Walk-forward / 滚动前推</div>
              <div className="mt-1 grid gap-1 text-indigo-800">
                <span>Enabled: {displayBoolFlag(validationWalkForward.enabled)}</span>
                <span>Mode: {displayText(validationWalkForward.mode)}</span>
                <span>Folds/windows: {displayText(validationWalkForward.folds ?? validationWalkForward.foldCount ?? walkForwardWindows.length)}</span>
                <span>Train: {displayDateRange(validationWalkForward.train_window)}</span>
                <span>Validation: {displayDateRange(validationWalkForward.validation_window ?? validationWalkForward.current_window)}</span>
              </div>
            </div>
            <div data-testid="backtest-validation-benchmark" className="rounded-md border border-indigo-100 bg-white px-3 py-2">
              <div className="font-medium text-indigo-950">Benchmark / 基准</div>
              <div className="mt-1 grid gap-1 text-indigo-800">
                <span>Symbol: {displayText(validationBenchmark.symbol ?? reportBenchmark.symbol)}</span>
                <span>Available: {displayBoolFlag(validationBenchmark.available ?? reportBenchmark.available)}</span>
                <span>Type/source: {displayText(validationBenchmark.type ?? reportBenchmark.type)} / {displayText(reportBenchmark.dataSource)}</span>
                <span>Return: {displayProtocolPercent(reportBenchmark.returnPct ?? reportBenchmark.benchmark_return_pct)}</span>
                <span>Reason: {displayText(validationBenchmark.reason ?? reportBenchmark.reason ?? reportBenchmark.note)}</span>
              </div>
            </div>
            <div data-testid="backtest-validation-parameter-scan" className="rounded-md border border-indigo-100 bg-white px-3 py-2">
              <div className="font-medium text-indigo-950">Parameter scan / 参数扫描</div>
              <div className="mt-1 grid gap-1 text-indigo-800">
                <span>Enabled: {displayBoolFlag(validationParameterScan.enabled)}</span>
                <span>Scan: {displayText(validationParameterScan.scanId ?? validationParameterScan.scan_id)}</span>
                <span>Trial count: {displayProtocolNumber(validationParameterScan.trialCount ?? validationParameterScan.maxCombinations)}</span>
                <span>Window count: {displayProtocolNumber(validationParameterScan.windowCount)}</span>
                <span>当前窗口：{displayDateRange(validationParameterScan.window)}</span>
                <span>Combination: {displayProtocolNumber(validationParameterScan.combinationIndex)}</span>
              </div>
            </div>
          </div>
          <div data-testid="backtest-validation-package-hashes" className="mt-2 rounded-md border border-indigo-100 bg-white px-3 py-2 text-indigo-800">
            <div className="font-medium text-indigo-950">Package hashes / 包哈希</div>
            <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
              <span>Data: {compactHash(validationHashes.dataPackageHash)}</span>
              <span>Parameters: {compactHash(validationHashes.parameterHash)}</span>
              <span>Market: {compactHash(validationHashes.marketDataHash)}</span>
              <span>Signals: {compactHash(validationHashes.signalPackageHash)}</span>
              <span>Benchmark: {compactHash(validationHashes.benchmarkDataHash)}</span>
            </div>
          </div>
          <div data-testid="backtest-validation-required-components" className="mt-2 rounded-md border border-indigo-100 bg-white px-3 py-2 text-indigo-800">
            Required for research grade: {displayProtocolList(requiredComponents)}
          </div>
        </div>
      )}

      {/* KPI row */}
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3">
        <StatBadge icon={Target} label="命中率" value={fmtPct(report.hit_rate)} variant={report.hit_rate > 0.5 ? 'good' : 'neutral'} />
        <StatBadge icon={isProfit ? TrendingUp : TrendingDown} label="总盈亏" value={fmtNum(report.total_pnl)} variant={isProfit ? 'good' : 'bad'} />
        <StatBadge icon={DollarSign} label="收益率" value={fmtNum(report.total_return_pct)} suffix="%" variant={report.total_return_pct >= 0 ? 'good' : 'bad'} />
        <StatBadge icon={Activity} label="最大回撤" value={fmtPct(report.max_drawdown_pct)} variant="bad" />
        <StatBadge icon={BarChart3} label="夏普比率" value={fmtNum(report.sharpe_ratio)} variant={report.sharpe_ratio > 1 ? 'good' : 'neutral'} />
        <StatBadge icon={Shield} label="误判率" value={fmtPct(report.false_positive_rate)} variant={report.false_positive_rate < 0.3 ? 'good' : 'bad'} />
        <StatBadge icon={Signal} label="信号来源" value={displaySignalSource(report.signal_source)} variant={report.signal_source === 'SIGNALOPS' ? 'accent' : 'neutral'} />
      </div>

      {meta.provenance?.signalOpsVersion && (
        <div className="rounded-lg border border-indigo-100 bg-indigo-50 px-4 py-3 text-xs text-indigo-800">
          <div className="font-semibold">SignalOps 同步版本：{meta.provenance.signalOpsVersion}</div>
          <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-indigo-700">
            <span>来源：{meta.provenance.signalOpsSourceMode || 'AUTO'}</span>
            <span>仅模拟：{displayBoolFlag(meta.provenance.simulationOnly)}</span>
            <span>真实交易：{displayBoolFlag(meta.provenance.isRealTrade)}</span>
            <span>清洗记录：{meta.provenance.cleanedRecordCount ?? 0}</span>
            <span>队列同步：{meta.provenance.reviewQueueSyncStatus || '-'}</span>
            <span>T+1：{displayBoolFlag(meta.provenance.executionRules?.t_plus_one_long_sell)}</span>
          </div>
        </div>
      )}

      {/* Secondary stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 md:grid-cols-8 gap-2">
        {[
          { label: '交易数', value: report.total_trades },
          { label: '盈利', value: report.winning_trades, color: 'text-emerald-600' },
          { label: '亏损', value: report.losing_trades, color: 'text-red-600' },
          { label: '信号数', value: report.total_signals },
          { label: '买入信号', value: report.buy_signals },
          { label: '卖出信号', value: report.sell_signals },
          { label: 'T+1 拦截', value: report.t_plus_one_blocked },
          { label: '涨跌停拦截', value: report.price_limit_blocked },
        ].map((s) => (
          <div key={s.label} className="rounded-lg bg-slate-50 px-3 py-2 text-center">
            <div className={cls('text-lg font-bold', s.color)}>{s.value}</div>
            <div className="text-[10px] text-slate-400 uppercase tracking-wide">{s.label}</div>
          </div>
        ))}
      </div>

      {/* Slippage & Manual Pass */}
      <div className="flex gap-3">
        <div className="flex-1 rounded-lg bg-slate-50 px-4 py-3 flex items-center justify-between">
          <div>
            <div className="text-xs text-slate-400 uppercase tracking-wide">总滑点</div>
            <div className="text-lg font-bold text-slate-700">{fmtNum(report.slippage_total)}</div>
          </div>
          <AlertTriangle size={20} className="text-amber-400" />
        </div>
        <div className="flex-1 rounded-lg bg-slate-50 px-4 py-3 flex items-center justify-between">
          <div>
            <div className="text-xs text-slate-400 uppercase tracking-wide">人工复核通过率</div>
            <div className="text-lg font-bold text-slate-700">{fmtPct(report.manual_review_pass_rate)}</div>
          </div>
          <CheckCircle2 size={20} className="text-emerald-400" />
        </div>
        <div className="flex-1 rounded-lg bg-slate-50 px-4 py-3 flex items-center justify-between">
          <div>
            <div className="text-xs text-slate-400 uppercase tracking-wide">期末资金</div>
            <div className="text-lg font-bold text-slate-700">{fmtNum(report.final_capital)}</div>
          </div>
          <DollarSign size={20} className="text-indigo-400" />
        </div>
      </div>

      {/* Equity Curve Chart */}
      {equityData && equityData.length > 0 && (
        <div>
          <div className="text-sm font-semibold text-slate-700 mb-2 flex items-center gap-2">
            <TrendingUp size={16} />
            资金曲线
          </div>
          <div className="h-56 bg-white rounded-xl border border-slate-100 p-3">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={equityData}>
                <defs>
                  <linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#6366f1" stopOpacity={0.15} />
                    <stop offset="95%" stopColor="#6366f1" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis dataKey="date" tick={{ fontSize: 11, fill: '#94a3b8' }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 11, fill: '#94a3b8' }} axisLine={false} tickLine={false} width={60} tickFormatter={(v: number) => fmtNum(v)} />
                <Tooltip
                  contentStyle={{ borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 12 }}
                  formatter={(value: number) => [fmtNum(value), '资金']}
                />
                <Area type="monotone" dataKey="capital" stroke="#6366f1" strokeWidth={2} fill="url(#eqGrad)" dot={false} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* Trade Log */}
      {report.trade_log && report.trade_log.length > 0 && (
        <div>
          <div className="text-sm font-semibold text-slate-700 mb-2 flex items-center gap-2">
            <ArrowLeftRight size={16} />
            交易日志 <span className="text-slate-400 font-normal">({report.trade_log.length})</span>
          </div>
          <TableShell>
            <table className="institution-table">
              <thead className="bg-slate-50">
                <tr className="text-xs text-slate-500 uppercase tracking-wide">
                  <th className="text-left py-2.5 px-3 font-medium">时间</th>
                  <th className="text-left py-2.5 px-3 font-medium">方向</th>
                  <th className="text-right py-2.5 px-3 font-medium">价格</th>
                  <th className="text-right py-2.5 px-3 font-medium">数量</th>
                  <th className="text-right py-2.5 px-3 font-medium">金额</th>
                  <th className="text-right py-2.5 px-3 font-medium">滑点</th>
                  <th className="text-right py-2.5 px-3 font-medium">盈亏</th>
                </tr>
              </thead>
              <tbody>
                {report.trade_log.map((t) => (
                  <tr key={t.trade_id} className="border-t border-slate-50 hover:bg-slate-50/50 transition-colors">
                    <td className="py-2 px-3 text-slate-600 text-xs">{t.timestamp}</td>
                    <td className="py-2 px-3">
                      <span className={cls(
                        'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold',
                        t.direction === 'BUY' ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-700'
                      )}>
                        {t.direction === 'BUY' ? <TrendingUp size={10} /> : <TrendingDown size={10} />}
                        {displayDirection(t.direction)}
                      </span>
                    </td>
                    <td className="py-2 px-3 text-right font-mono text-xs">{t.price.toFixed(2)}</td>
                    <td className="py-2 px-3 text-right font-mono text-xs">{t.quantity}</td>
                    <td className="py-2 px-3 text-right font-mono text-xs">{t.amount.toFixed(2)}</td>
                    <td className="py-2 px-3 text-right text-slate-400 font-mono text-xs">{t.slippage.toFixed(2)}</td>
                    <td className={cls(
                      'py-2 px-3 text-right font-mono text-xs font-semibold',
                      (t.realized_pnl ?? 0) >= 0 ? 'text-emerald-600' : 'text-red-600'
                    )}>
                      {t.realized_pnl != null ? t.realized_pnl.toFixed(2) : '-'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableShell>
        </div>
      )}
    </div>
  )
}

/* ───────── ComparisonPanel ───────── */
function ComparisonPanel({ comparison }: { comparison: BacktestComparison }) {
  if (!comparison || !comparison.before || !comparison.after) {
    return <EmptyState icon={ArrowLeftRight} text="同一补丁运行多次回测后，可在这里查看对比" />
  }

  const verdictConfig: Record<string, { icon: React.ElementType; text: string; cls: string }> = {
    IMPROVED: { icon: CheckCircle2, text: '已改善', cls: 'bg-emerald-50 border-emerald-200 text-emerald-700' },
    REGRESSED: { icon: XCircle, text: '已退化', cls: 'bg-red-50 border-red-200 text-red-700' },
    NO_REGRESSION: { icon: AlertTriangle, text: '无明显退化', cls: 'bg-amber-50 border-amber-200 text-amber-700' },
  }
  const v = verdictConfig[comparison.verdict] || verdictConfig.NO_REGRESSION
  const VIcon = v.icon

  const deltaRow = [
    { label: '命中率变化', value: comparison.hit_rate_delta, pct: true },
    { label: '回撤变化', value: comparison.drawdown_delta, pct: true, invert: true },
    { label: '误判率变化', value: comparison.false_positive_delta, pct: true, invert: true },
    { label: '盈亏变化', value: comparison.pnl_delta, pct: false },
    { label: '收益变化', value: comparison.return_delta, pct: false },
  ]

  return (
    <div className="space-y-5">
      {/* Verdict */}
      <div className={cls('inline-flex items-center gap-2 px-4 py-2 rounded-full border text-sm font-bold', v.cls)}>
        <VIcon size={16} />
        {v.text}
      </div>

      {/* Delta cards */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        {deltaRow.map((d) => {
          const isGood = d.invert ? d.value < 0 : d.value > 0
          const display = d.value >= 0 ? `+${d.pct ? fmtPct(d.value) : fmtNum(d.value)}` : `${d.pct ? fmtPct(d.value) : fmtNum(d.value)}`
          return (
            <div key={d.label} className={cls(
              'rounded-xl border p-3',
              isGood ? 'bg-emerald-50 border-emerald-200' : 'bg-red-50 border-red-200'
            )}>
              <div className="text-[11px] font-medium uppercase tracking-wide opacity-70 mb-1">{d.label}</div>
              <div className={cls('text-xl font-bold', isGood ? 'text-emerald-700' : 'text-red-700')}>
                {display}{d.pct && <span className="text-sm">%</span>}
              </div>
            </div>
          )
        })}
      </div>

      {/* Before / After */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {[
          { label: '补丁前', data: comparison.before, border: 'border-slate-200' },
          { label: '补丁后', data: comparison.after, border: 'border-indigo-200 bg-indigo-50/30' },
        ].map((side) => (
          <div key={side.label} className={cls('rounded-xl border p-4', side.border)}>
            <div className="text-xs font-bold uppercase tracking-wide text-slate-400 mb-3">{side.label}</div>
            <div className="grid grid-cols-2 gap-2">
              <StatBadge icon={Target} label="命中率" value={fmtPct(side.data.hit_rate)} />
              <StatBadge icon={Activity} label="回撤" value={fmtPct(side.data.max_drawdown_pct)} />
              <StatBadge icon={DollarSign} label="盈亏" value={fmtNum(side.data.total_pnl)} />
              <StatBadge icon={BarChart3} label="收益率" value={`${fmtNum(side.data.total_return_pct)}%`} />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

/* ───────── RunHistoryItem ───────── */
function RunHistoryItem({
  run,
  selected,
  deleting,
  deleteDisabledReason,
  onSelect,
  onDelete,
}: {
  run: BacktestRunItem
  selected: boolean
  deleting: boolean
  deleteDisabledReason?: string
  onSelect: () => void
  onDelete: () => void
}) {
  const profit = run.report?.total_pnl ?? 0
  const isProfit = profit >= 0

  return (
    <div
      onClick={onSelect}
      className={cls(
        'group relative rounded-xl border p-3 cursor-pointer transition-all',
        selected
          ? 'border-indigo-400 bg-indigo-50 shadow-sm'
          : 'border-slate-200 bg-white hover:border-slate-300 hover:shadow-sm'
      )}
    >
      <div className="flex items-start justify-between gap-3 mb-1.5">
        <div className="min-w-0 flex items-center gap-2">
          <span className="text-sm font-bold text-slate-800">{run.symbol}</span>
          {run.stock_name && <span className="text-xs text-slate-400">{run.stock_name}</span>}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <span className={cls(
            'text-[10px] px-2 py-0.5 rounded-full font-semibold uppercase tracking-wide',
            run.status === 'COMPLETED' ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'
          )}>
            {displayStatus(run.status)}
          </span>
          <button
            onClick={(e) => { e.stopPropagation(); onDelete() }}
            disabled={deleting || Boolean(deleteDisabledReason)}
            className="inline-flex items-center gap-1 rounded-md border border-red-100 bg-white px-2 py-1 text-[11px] font-medium text-red-600 shadow-sm hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50"
            title={deleteDisabledReason ?? deleteRunLabel(run)}
          >
            {deleting ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />}
            {deleteRunLabel(run)}
          </button>
        </div>
      </div>

      <div className="flex items-center gap-1 text-xs text-slate-400 mb-2">
        <Clock size={11} />
        {run.start_date} → {run.end_date}
      </div>

      {run.report && run.report.total_trades > 0 && (
        <div className="flex items-center gap-3 mb-2">
          <div className="flex items-center gap-1 text-xs">
            <Target size={11} className="text-indigo-400" />
            <span className="font-semibold text-slate-600">{(run.report.hit_rate * 100).toFixed(0)}%</span>
          </div>
          <div className={cls('flex items-center gap-1 text-xs font-semibold', isProfit ? 'text-emerald-600' : 'text-red-600')}>
            {isProfit ? <TrendingUp size={11} /> : <TrendingDown size={11} />}
            {fmtNum(profit)}
          </div>
          <MiniSparkline
            data={run.report.equity_curve?.map((p) => p.capital) ?? []}
            color={isProfit ? '#10b981' : '#ef4444'}
          />
        </div>
      )}

      {selected && <div className="absolute left-0 top-3 bottom-3 w-0.5 bg-indigo-500 rounded-r-full" />}
    </div>
  )
}

function SignalOpsRandomValidationPanel({
  job,
  mode,
  submitting,
  canStart,
  canCancel,
  startDisabledReason,
  cancelDisabledReason,
  onModeChange,
  onStart,
  onCancel,
}: {
  job: SignalOpsRandomValidationJob | null
  mode: SignalOpsRandomValidationMode
  submitting: boolean
  canStart: boolean
  canCancel: boolean
  startDisabledReason?: string
  cancelDisabledReason?: string
  onModeChange: (mode: SignalOpsRandomValidationMode) => void
  onStart: () => void
  onCancel: () => void
}) {
  const active = isRandomJobActive(job)
  const dataQuality = asRecord(job?.dataQuality)
  const baseline = asRecord(asRecord(job?.baselineResults).sample2)
  const candidate = asRecord(asRecord(job?.candidateResults).sample2)
  const adjustment = asRecord(job?.appliedAdjustment)
  const deltas = asRecord(adjustment.deltas)
  const sampleWindows = Array.isArray(job?.sampleWindows) ? job?.sampleWindows || [] : []
  const returnDelta = Number(candidate.totalReturnPct || 0) - Number(baseline.totalReturnPct || 0)
  const jobEvidenceLevel = normalizeEvidenceLevel(job?.evidenceLevel)
  const evidenceTone = jobEvidenceLevel === 'MEDIUM'
    ? 'border-sky-200 bg-sky-50 text-sky-700'
    : 'border-amber-200 bg-amber-50 text-amber-700'
  const randomGovernance = buildSignalOpsRandomValidationGovernance(job, mode)

  return (
    <Card title="SignalOps 随机验证">
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(280px,0.55fr)]">
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <div className="inline-flex rounded-lg border border-slate-200 bg-white p-1">
              <button
                type="button"
                onClick={() => onModeChange('VALIDATE_AND_FEEDBACK')}
                disabled={active || submitting}
                className={cls(
                  'rounded-md px-3 py-1.5 text-xs font-semibold transition',
                  mode === 'VALIDATE_AND_FEEDBACK' ? 'bg-indigo-600 text-white' : 'text-slate-500 hover:bg-slate-50',
                )}
              >
                验证并反馈
              </button>
              <button
                type="button"
                onClick={() => onModeChange('VALIDATE_ONLY')}
                disabled={active || submitting}
                className={cls(
                  'rounded-md px-3 py-1.5 text-xs font-semibold transition',
                  mode === 'VALIDATE_ONLY' ? 'bg-indigo-600 text-white' : 'text-slate-500 hover:bg-slate-50',
                )}
              >
                仅验证
              </button>
            </div>
            <button
              type="button"
              onClick={onStart}
              disabled={active || submitting || !canStart}
              title={!canStart ? startDisabledReason : undefined}
              className="inline-flex items-center gap-2 rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-200 disabled:text-slate-400"
            >
              {submitting ? <Loader2 size={16} className="animate-spin" /> : <Shuffle size={16} />}
              {submitting ? '启动中...' : '一键随机验证'}
            </button>
            {active && (
              <button
                type="button"
                onClick={onCancel}
                disabled={!canCancel}
                title={!canCancel ? cancelDisabledReason : undefined}
                className="inline-flex items-center gap-2 rounded-lg border border-red-100 bg-white px-4 py-2 text-sm font-semibold text-red-600 shadow-sm hover:bg-red-50 disabled:cursor-not-allowed disabled:border-slate-200 disabled:text-slate-400"
              >
                <Square size={14} />
                取消任务
              </button>
            )}
            {job && (
              <span className={cls('rounded-full border px-2.5 py-1 text-xs font-semibold', evidenceTone)}>
                {displayEvidenceLevel(job.evidenceLevel)}
              </span>
            )}
          </div>

          <div data-testid="backtest-signalops-random-governance" className="grid gap-2 rounded-lg border border-indigo-200 bg-indigo-50 p-3 text-xs text-slate-700 sm:grid-cols-2 xl:grid-cols-5">
            <span data-testid="backtest-signalops-random-governance-id" className="min-w-0 break-all">
              Job: {randomGovernance.contextId}
            </span>
            <span data-testid="backtest-signalops-random-evidence-strength" className="min-w-0 break-words">
              Evidence: {randomGovernance.evidenceStrength}
            </span>
            <span data-testid="backtest-signalops-random-blocker" className="min-w-0 break-words">
              Blocker: {randomGovernance.blocker}
            </span>
            <span data-testid="backtest-signalops-random-next-action" className="min-w-0 break-words">
              Next: {randomGovernance.nextAction}
            </span>
            <span data-testid="backtest-signalops-random-simulation-boundary" className="min-w-0 break-words font-medium text-slate-900">
              simulation_only={String(randomGovernance.simulationOnly)} / is_real_trade={String(randomGovernance.isRealTrade)} / evidence_usage={randomGovernance.evidenceUsage} / strong_conclusion_allowed={String(randomGovernance.strongConclusionAllowed)} / SIM_*
            </span>
          </div>

          <div className="grid gap-3 md:grid-cols-5">
            <StatBadge icon={RefreshCw} label="任务状态" value={job ? displayRandomStatus(job.status) : '未启动'} variant={job?.status === 'FAILED' ? 'bad' : job?.status === 'COMPLETED' ? 'good' : 'neutral'} />
            <StatBadge icon={Activity} label="当前步骤" value={job ? displayRandomProgress(job.progressStep) : '-'} variant="neutral" />
            <StatBadge icon={Shield} label="数据可信" value={job ? displayBoolFlag(dataQuality.trusted) : '-'} variant={dataQuality.trusted ? 'good' : 'neutral'} />
            <StatBadge icon={ArrowLeftRight} label="买卖闭环" value={job ? displayBoolFlag(dataQuality.completeTradeLoop) : '-'} variant={dataQuality.completeTradeLoop ? 'good' : 'bad'} />
            <StatBadge icon={Target} label="收益差" value={job?.status === 'COMPLETED' ? fmtNum(returnDelta) : '-'} suffix={job?.status === 'COMPLETED' ? '%' : ''} variant={returnDelta >= 0 ? 'good' : 'bad'} />
          </div>

          {job?.error && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {job.error}
            </div>
          )}

          {sampleWindows.length > 0 && (
            <div className="grid gap-3 md:grid-cols-2">
              {sampleWindows.map((sample, index) => (
                <div key={`${sample.symbol}-${sample.start}-${index}`} className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="text-sm font-semibold text-slate-800">
                      样本 {index + 1}：{sample.symbol} {sample.stockName || ''}
                    </div>
                    <span className="rounded-full bg-white px-2 py-0.5 text-[11px] font-medium text-slate-500">{sample.dataSource || '-'}</span>
                  </div>
                  <div className="mt-2 text-xs text-slate-500">
                    {sample.start} → {sample.end} · 交易日 {sample.tradingDays ?? '-'} · {sample.stratum || '未分层'}
                  </div>
                </div>
              ))}
            </div>
          )}

          {job?.status === 'COMPLETED' && (
            <div className="grid gap-3 md:grid-cols-3">
              <div className="rounded-lg border border-slate-200 bg-white p-3">
                <div className="text-xs font-semibold text-slate-400">原策略</div>
                <div className="mt-1 text-lg font-bold text-slate-800">{fmtNum(Number(baseline.totalReturnPct || 0))}%</div>
                <div className="mt-1 text-xs text-slate-500">交易 {baseline.totalTrades ?? 0} · 回撤 {fmtNum(Number(baseline.maxDrawdownPct || 0) * 100)}%</div>
              </div>
              <div className="rounded-lg border border-indigo-200 bg-indigo-50 p-3">
                <div className="text-xs font-semibold text-indigo-500">微调候选</div>
                <div className="mt-1 text-lg font-bold text-indigo-800">{fmtNum(Number(candidate.totalReturnPct || 0))}%</div>
                <div className="mt-1 text-xs text-indigo-600">交易 {candidate.totalTrades ?? 0} · 回撤 {fmtNum(Number(candidate.maxDrawdownPct || 0) * 100)}%</div>
              </div>
              <div className="rounded-lg border border-slate-200 bg-white p-3">
                <div className="text-xs font-semibold text-slate-400">买入持有</div>
                <div className="mt-1 text-lg font-bold text-slate-800">{fmtNum(Number(baseline.buyHoldReturnPct || 0))}%</div>
                <div className="mt-1 text-xs text-slate-500">空仓基准 0%</div>
              </div>
            </div>
          )}
        </div>

        <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
          <div className="text-sm font-semibold text-slate-800">反馈状态</div>
          <div className="mt-3 space-y-2 text-sm text-slate-600">
            <div className="flex justify-between gap-3">
              <span>仅模拟</span>
              <span className="font-semibold">{displayBoolFlag(job?.simulationOnly ?? true)}</span>
            </div>
            <div className="flex justify-between gap-3">
              <span>真实交易</span>
              <span className="font-semibold">{displayBoolFlag(job?.isRealTrade ?? false)}</span>
            </div>
            <div className="flex justify-between gap-3">
              <span>同步 SignalOps</span>
              <span className="font-semibold">{job?.reviewQueueSyncStatus || '-'}</span>
            </div>
            <div className="flex justify-between gap-3">
              <span>微调应用</span>
              <span className="font-semibold">{displayBoolFlag(adjustment.applied)}</span>
            </div>
          </div>
          {Object.keys(deltas).length > 0 && (
            <div className="mt-3 rounded-md border border-white bg-white p-3">
              <div className="text-xs font-semibold text-slate-500">参数变化</div>
              <div className="mt-2 space-y-1 text-xs text-slate-600">
                {Object.entries(deltas).slice(0, 6).map(([key, value]) => (
                  <div key={key} className="flex justify-between gap-2">
                    <span className="truncate">{key}</span>
                    <span className="font-mono">{Number(value).toFixed(4)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {job?.rejectionReasons?.length ? (
            <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
              {job.rejectionReasons.slice(0, 4).map(displayRandomRejectionReason).join(' / ')}
            </div>
          ) : (
            <div className="mt-3 text-xs text-slate-500">
              随机验证会保存 seed、样本窗口、数据质量和可回滚的微调依据；MOCK 数据不会触发策略调整。
            </div>
          )}
        </div>
      </div>
    </Card>
  )
}

/* ───────── BacktestPage ───────── */
type BacktestFormState = {
  symbol: string
  stock_name: string
  start_date: string
  end_date: string
  initial_capital: number
  signal_source: string
  signal_date: string
  patch_id: string
  case_id: string
  scenario_label: string
  force_new: boolean
}

type BacktestGovernance = {
  contextId: string
  evidenceStrength: 'MEDIUM' | 'LOW'
  blocker: string
  nextAction: string
  simulationOnly: boolean
  isRealTrade: boolean
  evidenceUsage: 'supporting_only'
  strongConclusionAllowed: false
}

type BacktestVerdictNotice = {
  iterationId: string
  engineVerdict: string
  canAccept: boolean
  blockers: string[]
  evidenceUsage: 'supporting_only'
  supportingOnly: true
  simulationOnly: true
  isRealTrade: false
  strongConclusionAllowed: false
}

type BacktestParameterScanGovernance = Omit<BacktestGovernance, 'evidenceStrength' | 'evidenceUsage'> & {
  evidenceStrength: 'LOW'
  evidenceUsage: 'review_gate_only'
  strongConclusionAllowed: false
}

const DEFAULT_BACKTEST_FORM: BacktestFormState = {
  symbol: '000001.SZ',
  stock_name: '',
  start_date: '2024-06-01',
  end_date: '2024-09-30',
  initial_capital: 100000,
  signal_source: 'SIGNALOPS',
  signal_date: '',
  patch_id: '',
  case_id: '',
  scenario_label: '',
  force_new: false,
}

function buildSignalOpsRandomValidationGovernance(
  job: SignalOpsRandomValidationJob | null,
  mode: SignalOpsRandomValidationMode,
) {
  const dataQuality = asRecord(job?.dataQuality)
  const status = String(job?.status || '').toUpperCase()
  const simulationOnly = job?.simulationOnly !== false
  const isRealTrade = job?.isRealTrade === true
  const boundaryBroken = !simulationOnly || isRealTrade
  const hasSamples = Array.isArray(job?.sampleWindows) && job.sampleWindows.length > 0
  const trusted = dataQuality.trusted === true
  const completeTradeLoop = dataQuality.completeTradeLoop === true
  const rejected = Array.isArray(job?.rejectionReasons) && job.rejectionReasons.length > 0

  let blocker = '无阻断，保持人工复核'
  if (boundaryBroken) {
    blocker = 'SignalOps random validation simulation-only boundary violated'
  } else if (!job) {
    blocker = '未启动随机验证任务'
  } else if (status === 'FAILED') {
    blocker = job.error || '随机验证失败'
  } else if (status === 'CANCELLED') {
    blocker = '随机验证已取消'
  } else if (isRandomJobActive(job)) {
    blocker = `随机验证仍在运行：${displayRandomProgress(job.progressStep)}`
  } else if (!hasSamples) {
    blocker = '缺少随机样本窗口'
  } else if (!trusted) {
    blocker = '随机验证数据可信度不足'
  } else if (!completeTradeLoop) {
    blocker = '缺少完整买卖闭环'
  } else if (rejected) {
    blocker = displayRandomRejectionReason(job.rejectionReasons[0])
  }

  const nextAction = boundaryBroken
    ? '停止反馈，先修复 SignalOps random validation 边界'
    : !job
      ? `启动 ${mode} 随机验证`
      : status === 'FAILED' || status === 'CANCELLED'
        ? '修复失败原因后重新运行随机验证'
        : isRandomJobActive(job)
          ? '等待随机验证完成或由 operator 取消'
          : !hasSamples || !trusted || !completeTradeLoop || rejected
            ? '补齐样本与数据质量后再同步 SignalOps'
            : '仅作为 supporting review evidence，进入人工复核'

  return {
    contextId: job?.jobId || `pending-random-validation-${mode.toLowerCase()}`,
    evidenceStrength: 'LOW',
    blocker,
    nextAction,
    simulationOnly,
    isRealTrade,
    evidenceUsage: 'supporting_only',
    strongConclusionAllowed: false,
  }
}

const isSampleRun = (run: Pick<BacktestRunItem, 'symbol' | 'scenario_label'>) => {
  const label = (run.scenario_label || '').toLowerCase()
  return label.includes('sample') || label.includes('样本') || label.includes('样例') || run.symbol.toUpperCase().includes('P2LOCAL')
}

const deleteRunLabel = (run: Pick<BacktestRunItem, 'symbol' | 'scenario_label'>) => (
  isSampleRun(run) ? '删除样本' : '删除记录'
)

const buildBacktestParameters = (form: BacktestFormState): Record<string, any> => ({
  signal_source: form.signal_source,
  ...(form.signal_source === 'SIGNALOPS'
    ? {
        signalops_version: 'AUTO_PAPER_V2',
        signalops_source_mode: 'AUTO',
        data_source: 'AUTO',
      }
    : {}),
  ...(form.signal_source === 'MOCK' || form.signal_source === 'NONE'
    ? {
        data_source: 'MOCK',
      }
    : {}),
  ...(form.signal_source === 'MFE_MAE_PATH_RESEARCH' || form.signal_source === 'BOTTOM_RESEARCH'
    ? {
        data_source: 'AUTO',
        bottom_research_config: {
          lookback_range: '2y',
          horizon_days: 20,
          cov_window: 20,
          min_drawdown_pct: 0.12,
          downside_tolerance_pct: 0.05,
          recovery_return_pct: 0.08,
          repair_probability_threshold: 0.60,
          max_research_position_pct: 0.30,
        },
      }
    : {}),
  ...(form.signal_date ? { signal_date: form.signal_date } : {}),
})

const DATE_ONLY_RE = /^(\d{4})-(\d{2})-(\d{2})$/
const DAY_MS = 24 * 60 * 60 * 1000

const parseDateOnly = (value: string) => {
  const match = DATE_ONLY_RE.exec(value.trim())
  if (!match) return null
  return Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]))
}

const formatDateOnly = (value: number) => new Date(value).toISOString().slice(0, 10)

const buildParameterScanWindows = (startDate: string, endDate: string): BacktestParameterScanWindow[] => {
  const fullWindow = { start: startDate, end: endDate, label: 'full' }
  const start = parseDateOnly(startDate)
  const end = parseDateOnly(endDate)
  if (start === null || end === null || end <= start) return [fullWindow]
  const spanDays = Math.floor((end - start) / DAY_MS)
  if (spanDays < 4) return [fullWindow]
  const validationStart = start + (Math.floor(spanDays / 2) + 1) * DAY_MS
  if (validationStart >= end) return [fullWindow]
  return [
    fullWindow,
    { start: formatDateOnly(validationStart), end: endDate, label: 'validation' },
  ]
}

const parameterScanTrialCount = (
  scan: BacktestParameterScanResponse | BacktestParameterScanHistoryItem,
) => Number(scan.summary?.totalTrials ?? scan.trial_count ?? scan.run_ids.length)

const parameterScanCombinationCount = (
  scan: BacktestParameterScanResponse | BacktestParameterScanHistoryItem,
) => Number(scan.summary?.totalCombinations ?? scan.combinations.length)

const parameterScanWindowCount = (
  scan: BacktestParameterScanResponse | BacktestParameterScanHistoryItem,
) => Number(scan.summary?.windowCount ?? scan.window_count ?? scan.windows?.length ?? 1)

const buildBacktestParameterScanGovernance = (
  scan: BacktestParameterScanResponse | BacktestParameterScanHistoryItem,
): BacktestParameterScanGovernance => {
  const status = String(scan.status || '').toUpperCase()
  const simulationOnly = scan.simulation_only === true
  const isRealTrade = scan.is_real_trade === true
  const hasBestRun = Boolean(scan.best_run_id)
  const boundaryBroken = !simulationOnly || isRealTrade
  const completed = status === 'COMPLETED'
  const blocker = boundaryBroken
    ? 'Backtest parameter scan simulation-only boundary violated'
    : !completed
      ? `Parameter scan status ${status || 'UNKNOWN'}`
      : !hasBestRun
        ? 'No best run retained for parameter scan'
        : 'Parameter scan retained as review-gated evidence'
  const nextAction = boundaryBroken
    ? 'Stop handoff until simulation-only boundary is restored'
    : !completed
      ? 'Wait for bounded scan completion before Research Lab handoff'
      : !hasBestRun
        ? 'Review scan failure or rerun bounded parameter scan'
        : 'Open best run and hand off supporting evidence to Research Lab'

  return {
    contextId: scan.scan_id || 'pending-parameter-scan',
    evidenceStrength: 'LOW',
    blocker,
    nextAction,
    simulationOnly,
    isRealTrade,
    evidenceUsage: 'review_gate_only',
    strongConclusionAllowed: false,
  }
}

const buildBacktestParameterScanJobGovernance = (
  job: BacktestParameterScanJob,
): BacktestParameterScanGovernance => {
  const status = String(job.status || '').toUpperCase()
  const simulationOnly = job.simulationOnly === true
  const isRealTrade = job.isRealTrade === true
  const hasBestRun = Boolean(job.bestRunId)
  const boundaryBroken = !simulationOnly || isRealTrade
  const completed = status === 'COMPLETED'
  const active = isParameterScanJobActive(job)
  const blocker = boundaryBroken
    ? 'Backtest parameter scan simulation-only boundary violated'
    : active
      ? `Parameter scan job ${status}`
      : !completed
        ? `Parameter scan job ${status || 'UNKNOWN'}`
        : !hasBestRun
          ? 'No best run retained for parameter scan'
          : 'Parameter scan retained as review-gated evidence'
  const nextAction = boundaryBroken
    ? 'Stop handoff until simulation-only boundary is restored'
    : active
      ? 'Wait for async scan completion before Research Lab handoff'
      : !completed || !hasBestRun
        ? 'Review scan job output or rerun bounded parameter scan'
        : 'Handoff retained supporting evidence after admin custody review'

  return {
    contextId: job.jobId || job.scanId || 'pending-parameter-scan-job',
    evidenceStrength: 'LOW',
    blocker,
    nextAction,
    simulationOnly,
    isRealTrade,
    evidenceUsage: 'review_gate_only',
    strongConclusionAllowed: false,
  }
}

const buildParameterScanRequest = (
  form: BacktestFormState,
  overrides: Partial<BacktestParameterScanRequest> = {},
): BacktestParameterScanRequest => {
  const scanWindows = buildParameterScanWindows(form.start_date, form.end_date)
  return {
    symbol: form.symbol,
    stock_name: form.stock_name.trim() || undefined,
    start_date: form.start_date,
    end_date: form.end_date,
    initial_capital: form.initial_capital,
    patch_id: form.patch_id || undefined,
    case_id: form.case_id || undefined,
    scenario_label: form.scenario_label || 'Parameter scan',
    reuse_existing: !form.force_new,
    force_new: form.force_new,
    ranking_metric: 'research_grade_score',
    max_combinations: 3,
    windows: scanWindows,
    base_parameters: {
      ...buildBacktestParameters(form),
      out_of_sample_start: form.start_date,
      out_of_sample_end: form.end_date,
      walk_forward: {
        enabled: true,
        mode: 'bounded_parameter_scan',
        folds: 2,
        windows: scanWindows,
      },
    },
    parameter_grid: {
      signal_min_strength: [0.3, 0.5, 0.7],
      trade_quantity_pct: [0.1, 0.2],
    },
    ...overrides,
  }
}

function buildBacktestRunGovernance({
  selectedRun,
  scanNotice,
  parameterScanJob,
  sampleNotice,
  randomJob,
  verdictNotice,
}: {
  selectedRun: BacktestRunItem | null
  scanNotice: BacktestParameterScanResponse | null
  parameterScanJob: BacktestParameterScanJob | null
  sampleNotice: { runId: string; marketDataSource: string; evidenceGrade?: string; limitations: string[] } | null
  randomJob: SignalOpsRandomValidationJob | null
  verdictNotice: BacktestVerdictNotice | null
}): BacktestGovernance {
  const report = selectedRun?.report
  const hasSelectedReport = hasReport(report)
  const reportMeta = hasSelectedReport ? getReportMeta(report) : null
  const evidence = firstNonEmptyRecord(reportMeta?.evidenceStrength, reportMeta?.evidence_strength)
  const researchGrade = firstNonEmptyRecord(reportMeta?.researchGradeScore, reportMeta?.research_grade_score)
  const provenance = asRecord(reportMeta?.provenance)
  const parameters = asRecord(selectedRun?.parameters)
  const reportGrade = normalizeEvidenceLevel(String(evidence.grade || evidence.reportedGrade || evidence.reported_grade || sampleNotice?.evidenceGrade || randomJob?.evidenceLevel || ''))
  const researchUsage = String(evidence.researchUsage || evidence.research_usage || researchGrade.researchUsage || researchGrade.research_usage || '').toLowerCase()
  const researchBand = String(researchGrade.band || evidence.researchGradeBand || evidence.research_grade_band || '').toUpperCase()
  const researchScore = Number(researchGrade.score ?? evidence.researchGradeScore ?? evidence.research_grade_score)
  const canSupportResearchVerdict = evidence.canSupportResearchVerdict === true
    || evidence.can_support_research_verdict === true
    || researchGrade.canSupportResearchVerdict === true
    || researchGrade.can_support_research_verdict === true
  const supportingOnly = Boolean(
    evidence.weakSample
    || evidence.weak_sample
    || researchGrade.supportingOnly
    || researchGrade.supporting_only
    || canSupportResearchVerdict
    || researchUsage === 'supporting_only'
    || researchUsage === 'primary_evidence'
    || researchBand === 'SUPPORTING_ONLY',
  )
  const simulationOnly = ![
    provenance.simulationOnly,
    parameters.simulation_only,
    scanNotice?.simulation_only,
    parameterScanJob?.simulationOnly,
    randomJob?.simulationOnly,
  ].some((value) => value === false)
  const isRealTrade = [
    provenance.isRealTrade,
    parameters.is_real_trade,
    scanNotice?.is_real_trade,
    parameterScanJob?.isRealTrade,
    randomJob?.isRealTrade,
  ].some((value) => value === true)

  let evidenceStrength: BacktestGovernance['evidenceStrength'] = 'LOW'
  if (
    hasSelectedReport
    && (reportGrade === 'MEDIUM' || researchBand === 'REVIEWABLE' || (Number.isFinite(researchScore) && researchScore >= 60))
    && !supportingOnly
  ) {
    evidenceStrength = 'MEDIUM'
  } else if (supportingOnly) {
    evidenceStrength = 'LOW'
  } else if (parameterScanJob || scanNotice || sampleNotice || randomJob) {
    evidenceStrength = 'LOW'
  }

  let blocker = ''
  if (!simulationOnly || isRealTrade) {
    blocker = 'Backtest simulation-only boundary violated'
  } else if (!selectedRun) {
    blocker = '未选择 Backtest run'
  } else if (String(selectedRun.status || '').toUpperCase() !== 'COMPLETED') {
    blocker = `回测状态 ${selectedRun.status || 'UNKNOWN'}`
  } else if (!hasSelectedReport) {
    blocker = '缺少 Backtest report'
  } else if (displayText(report.data_error, '')) {
    blocker = `数据问题：${displayText(report.data_error)}`
  } else if (report.total_trades <= 0) {
    blocker = '缺少完整交易闭环'
  } else if (supportingOnly) {
    blocker = `仅 supporting_only evidence：${displayText(evidence.researchGradeBand || evidence.research_grade_band || researchBand || reportGrade || 'LOW')}`
  } else if (parameterScanJob && isParameterScanJobActive(parameterScanJob)) {
    blocker = `参数扫描任务 ${parameterScanJob.status}`
  } else if (randomJob && isRandomJobActive(randomJob)) {
    blocker = `SignalOps 随机验证 ${randomJob.status}`
  } else if (verdictNotice && !verdictNotice.canAccept) {
    blocker = verdictNotice.blockers[0] || `Research verdict ${verdictNotice.engineVerdict}`
  } else if (sampleNotice?.limitations.length) {
    blocker = sampleNotice.limitations[0]
  } else {
    blocker = '无阻断，保持人工复核'
  }

  const nextAction = !simulationOnly || isRealTrade
    ? '停止移交，先修复 simulation-only boundary'
    : blocker === '无阻断，保持人工复核'
      ? '移交 Research Lab / case / knowledge / evaluation 仅模拟复核'
      : '补齐 Backtest 证据后再移交 Research Lab / case / knowledge'

  return {
    contextId: selectedRun?.run_id || parameterScanJob?.jobId || scanNotice?.scan_id || sampleNotice?.runId || randomJob?.jobId || 'pending-backtest-form',
    evidenceStrength,
    blocker,
    nextAction,
    simulationOnly,
    isRealTrade,
    evidenceUsage: 'supporting_only',
    strongConclusionAllowed: false,
  }
}

export default function BacktestPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const operator = useOperatorContext()
  const [runs, setRuns] = useState<BacktestRunItem[]>([])
  const [parameterScans, setParameterScans] = useState<BacktestParameterScanHistoryItem[]>([])
  const [summary, setSummary] = useState<BacktestSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [scanSubmitting, setScanSubmitting] = useState(false)
  const [scanNotice, setScanNotice] = useState<BacktestParameterScanResponse | null>(null)
  const [parameterScanJob, setParameterScanJob] = useState<BacktestParameterScanJob | null>(null)
  const [parameterScanJobSubmitting, setParameterScanJobSubmitting] = useState(false)
  const [parameterScanJobHandoff, setParameterScanJobHandoff] = useState<BacktestParameterScanJobHandoff | null>(null)
  const [parameterScanJobHandoffSubmitting, setParameterScanJobHandoffSubmitting] = useState(false)
  const [parameterScanJobHandoffRefreshing, setParameterScanJobHandoffRefreshing] = useState(false)
  const [sampleSubmitting, setSampleSubmitting] = useState(false)
  const [sampleNotice, setSampleNotice] = useState<{
    runId: string
    marketDataSource: string
    evidenceGrade?: string
    limitations: string[]
  } | null>(null)
  const [error, setError] = useState('')
  const [selectedRun, setSelectedRun] = useState<BacktestRunItem | null>(null)
  const [trades, setTrades] = useState<BacktestTradeItem[]>([])
  const [signals, setSignals] = useState<BacktestSignalItem[]>([])
  const [detailLoading, setDetailLoading] = useState(false)
  const [packageDownloading, setPackageDownloading] = useState(false)
  const [verdictLinking, setVerdictLinking] = useState(false)
  const [verdictNotice, setVerdictNotice] = useState<BacktestVerdictNotice | null>(null)
  const [activeTab, setActiveTab] = useState<'report' | 'trades' | 'signals' | 'comparison'>('report')
  const [showAdvancedForm, setShowAdvancedForm] = useState(false)
  const [deletingRunId, setDeletingRunId] = useState<string | null>(null)
  const [randomMode, setRandomMode] = useState<SignalOpsRandomValidationMode>('VALIDATE_AND_FEEDBACK')
  const [randomJob, setRandomJob] = useState<SignalOpsRandomValidationJob | null>(null)
  const [randomSubmitting, setRandomSubmitting] = useState(false)
  const detailRequestRef = useRef(0)
  const loadingRunIdRef = useRef<string | null>(null)
  const mountedRef = useRef(true)
  const refreshAbortRef = useRef<AbortController | null>(null)
  const detailAbortRef = useRef<AbortController | null>(null)
  const canWriteBacktestResearch = roleAllows(operator.role, 'researcher')
  const backtestWriteDisabledReason = canWriteBacktestResearch
    ? ''
    : `回测研究写入需要 researcher 权限。当前角色：${operator.role}。`
  const canControlBacktestJobs = roleAllows(operator.role, 'operator')
  const backtestJobControlDisabledReason = canControlBacktestJobs
    ? ''
    : `回测任务控制需要 operator 权限。当前角色：${operator.role}。`
  const canHandoffBacktestArtifacts = roleAllows(operator.role, 'admin')
  const backtestHandoffDisabledReason = canHandoffBacktestArtifacts
    ? ''
    : `回测产物交接需要 admin 权限。当前角色：${operator.role}。`
  const canDeleteBacktestRuns = roleAllows(operator.role, 'admin')
  const deleteDisabledReason = canDeleteBacktestRuns
    ? undefined
    : `回测记录删除需要 admin 权限。当前角色：${operator.role}。`

  const [form, setForm] = useState<BacktestFormState>(DEFAULT_BACKTEST_FORM)
  const updateForm = <K extends keyof BacktestFormState>(key: K, value: BacktestFormState[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }))
  }
  const deepLinkedRunId = searchParams.get('run_id') || ''
  const researchIterationId = searchParams.get('iteration_id') || ''
  const setRunIdParam = useCallback((runId: string) => {
    setSearchParams((current) => {
      const next = new URLSearchParams(current)
      next.set('run_id', runId)
      return next
    })
  }, [setSearchParams])

  useEffect(() => {
    return () => {
      mountedRef.current = false
      detailRequestRef.current += 1
      loadingRunIdRef.current = null
      refreshAbortRef.current?.abort()
      detailAbortRef.current?.abort()
    }
  }, [])

  const refresh = useCallback(async () => {
    refreshAbortRef.current?.abort()
    const abortController = new AbortController()
    refreshAbortRef.current = abortController
    setLoading(true)
    setError('')
    try {
      const [runsData, summaryData, parameterScanData] = await Promise.all([
        listBacktestRuns({ limit: 50 }, { signal: abortController.signal }),
        getBacktestSummary({ signal: abortController.signal }),
        listBacktestParameterScans({ limit: 10 }, { signal: abortController.signal }),
      ])
      if (!mountedRef.current || abortController.signal.aborted || refreshAbortRef.current !== abortController) return
      setRuns(runsData)
      setSummary(summaryData)
      setParameterScans(parameterScanData)
    } catch (e) {
      if (!mountedRef.current || abortController.signal.aborted || refreshAbortRef.current !== abortController) return
      setError(e instanceof Error ? e.message : '回测数据加载失败')
    } finally {
      if (refreshAbortRef.current === abortController) {
        refreshAbortRef.current = null
        if (mountedRef.current) setLoading(false)
      }
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  // Poll SignalOps random validation job — only recreate interval when jobId changes,
  // not on every poll result update (the previous dependency on `randomJob` caused
  // the interval to be torn down and recreated every 1.8s during active polling).
  const randomJobId = randomJob?.jobId
  useEffect(() => {
    if (!randomJobId || !randomJob || !isRandomJobActive(randomJob)) return undefined
    const timer = window.setInterval(async () => {
      try {
        const latest = await getSignalOpsRandomValidationJob(randomJobId)
        if (!mountedRef.current) return
        setRandomJob(latest)
        if (!isRandomJobActive(latest)) {
          window.clearInterval(timer)
          await refresh()
          return
        }
        if (latest.status === 'COMPLETED') {
          await refresh()
        }
      } catch (e) {
        if (!mountedRef.current) return
        reportError('轮询 SignalOps 随机验证任务失败', e)
      }
    }, 1800)
    return () => window.clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [randomJobId, refresh])

  const loadDetails = useCallback(async (runId: string) => {
    const requestId = detailRequestRef.current + 1
    detailRequestRef.current = requestId
    detailAbortRef.current?.abort()
    const abortController = new AbortController()
    detailAbortRef.current = abortController
    loadingRunIdRef.current = runId
    setDetailLoading(true)
    setError('')
    try {
      const [run, tradesData, signalsData] = await Promise.all([
        getBacktestRun(runId, { signal: abortController.signal }),
        getBacktestTrades(runId, { signal: abortController.signal }),
        getBacktestSignals(runId, { signal: abortController.signal }),
      ])
      if (mountedRef.current && !abortController.signal.aborted && detailRequestRef.current === requestId) {
        setSelectedRun(run)
        setTrades(tradesData)
        setSignals(signalsData)
        setActiveTab('report')
      }
    } catch (e) {
      if (!mountedRef.current || abortController.signal.aborted || detailRequestRef.current !== requestId) return
      if (detailRequestRef.current === requestId) {
        setError(e instanceof Error ? e.message : '回测详情加载失败')
        setSelectedRun(null)
        setTrades([])
        setSignals([])
      }
    } finally {
      if (mountedRef.current && detailRequestRef.current === requestId) {
        if (detailAbortRef.current === abortController) detailAbortRef.current = null
        loadingRunIdRef.current = null
        setDetailLoading(false)
      }
    }
  }, [])

  const selectRun = useCallback((runId: string) => {
    setRunIdParam(runId)
    void loadDetails(runId)
  }, [loadDetails, setRunIdParam])

  // Poll Backtest parameter scan job — only recreate interval on jobId change
  useEffect(() => {
    const jobId = parameterScanJob?.jobId
    if (!jobId) return undefined
    const timer = window.setInterval(async () => {
      try {
        const latest = await getBacktestParameterScanJob(jobId)
        if (!mountedRef.current) return
        setParameterScanJob(latest)
        if (!isParameterScanJobActive(latest)) {
          window.clearInterval(timer)
          if (latest.scan) setScanNotice(latest.scan)
          await refresh()
          return
        }
        if (latest.status === 'COMPLETED') {
          if (latest.scan) setScanNotice(latest.scan)
          await refresh()
          if (latest.bestRunId) {
            setRunIdParam(latest.bestRunId)
            await loadDetails(latest.bestRunId)
          }
        }
      } catch (e) {
        if (!mountedRef.current) return
        reportError('轮询回测参数扫描任务失败', e)
      }
    }, 1200)
    return () => window.clearInterval(timer)
  }, [loadDetails, parameterScanJob?.jobId, refresh, setRunIdParam])

  useEffect(() => {
    if (!deepLinkedRunId) return
    if (selectedRun?.run_id === deepLinkedRunId) return
    if (loadingRunIdRef.current === deepLinkedRunId) return
    void loadDetails(deepLinkedRunId)
  }, [deepLinkedRunId, loadDetails, selectedRun?.run_id])

  const handleSubmit = async () => {
    if (!canWriteBacktestResearch) {
      setError(backtestWriteDisabledReason)
      return
    }
    if (!form.symbol || !form.start_date || !form.end_date) return
    setSubmitting(true)
    setError('')
    try {
      const result = await createBacktestRun({
        symbol: form.symbol,
        stock_name: form.stock_name.trim() || undefined,
        start_date: form.start_date,
        end_date: form.end_date,
        initial_capital: form.initial_capital,
        patch_id: form.patch_id || undefined,
        case_id: form.case_id || undefined,
        scenario_label: form.scenario_label,
        reuse_existing: !form.force_new,
        force_new: form.force_new,
        parameters: buildBacktestParameters(form),
      })
      await refresh()
      setRunIdParam(result.run_id)
      await loadDetails(result.run_id)
    } catch (e) {
      reportError('创建回测运行失败', e)
      setError(e instanceof Error ? e.message : '创建回测失败')
    } finally {
      setSubmitting(false)
    }
  }

  const handleParameterScan = async () => {
    if (!canWriteBacktestResearch) {
      setError(backtestWriteDisabledReason)
      return
    }
    if (!form.symbol || !form.start_date || !form.end_date) return
    setScanSubmitting(true)
    setError('')
    setScanNotice(null)
    try {
      const result = await createBacktestParameterScan(buildParameterScanRequest(form))
      setScanNotice(result)
      await refresh()
      if (result.best_run_id) {
        setRunIdParam(result.best_run_id)
        await loadDetails(result.best_run_id)
      }
    } catch (e) {
      reportError('创建回测参数扫描失败', e)
      setError(e instanceof Error ? e.message : 'Create backtest parameter scan failed')
    } finally {
      setScanSubmitting(false)
    }
  }

  const handleParameterScanJob = async () => {
    if (!canWriteBacktestResearch) {
      setError(backtestWriteDisabledReason)
      return
    }
    if (!form.symbol || !form.start_date || !form.end_date) return
    setParameterScanJobSubmitting(true)
    setError('')
    setParameterScanJobHandoff(null)
    try {
      const result = await createBacktestParameterScanJob(buildParameterScanRequest(form))
      setParameterScanJob(result)
    } catch (e) {
      reportError('创建回测参数扫描任务失败', e)
      setError(e instanceof Error ? e.message : 'Create backtest parameter scan job failed')
    } finally {
      setParameterScanJobSubmitting(false)
    }
  }

  const handleCancelParameterScanJob = async () => {
    if (!canControlBacktestJobs) {
      setError(backtestJobControlDisabledReason)
      return
    }
    if (!parameterScanJob) return
    setError('')
    try {
      const result = await cancelBacktestParameterScanJob(parameterScanJob.jobId)
      setParameterScanJob(result)
    } catch (e) {
      reportError('取消回测参数扫描任务失败', e)
      setError(e instanceof Error ? e.message : 'Cancel backtest parameter scan job failed')
    }
  }

  const handleHandoffParameterScanJob = async () => {
    if (!canHandoffBacktestArtifacts) {
      setError(backtestHandoffDisabledReason)
      return
    }
    if (!parameterScanJob?.jobId) return
    setParameterScanJobHandoffSubmitting(true)
    setError('')
    try {
      const result = await handoffBacktestParameterScanJob(parameterScanJob.jobId)
      setParameterScanJobHandoff(result)
    } catch (e) {
      reportError('移交回测参数扫描任务失败', e)
      setError(e instanceof Error ? e.message : 'Handoff backtest parameter scan job failed')
    } finally {
      setParameterScanJobHandoffSubmitting(false)
    }
  }

  const handleRefreshParameterScanJobHandoffStatus = async () => {
    if (!parameterScanJob?.jobId) return
    setParameterScanJobHandoffRefreshing(true)
    setError('')
    try {
      const latest = await getBacktestParameterScanJob(parameterScanJob.jobId)
      setParameterScanJob(latest)
    } catch (e) {
      reportError('刷新回测参数扫描移交状态失败', e)
      setError(e instanceof Error ? e.message : '刷新回测参数扫描交接状态失败')
    } finally {
      setParameterScanJobHandoffRefreshing(false)
    }
  }

  const handleSignalOpsSample = async () => {
    if (!canWriteBacktestResearch) {
      setError(backtestWriteDisabledReason)
      return
    }
    setSampleSubmitting(true)
    setError('')
    setSampleNotice(null)
    try {
      const result = await createSignalOpsBacktestSample({
        symbol: form.symbol || undefined,
        start_date: form.start_date || undefined,
        end_date: form.end_date || undefined,
        signal_date: form.signal_date || undefined,
        initial_capital: form.initial_capital,
        data_source: 'AUTO',
        reuse_existing: !form.force_new,
        force_new: form.force_new,
      })
      setSampleNotice({
        runId: result.run_id,
        marketDataSource: result.market_data_source,
        evidenceGrade: String(result.evidence_strength?.grade || ''),
        limitations: result.limitations || [],
      })
      await refresh()
      setRunIdParam(result.run_id)
      await loadDetails(result.run_id)
    } catch (e) {
      reportError('创建 SignalOps 回测样本失败', e)
      setError(e instanceof Error ? e.message : '生成 SignalOps 回测样例失败')
    } finally {
      setSampleSubmitting(false)
    }
  }

  const handleSignalOpsRandomValidation = async () => {
    if (!canWriteBacktestResearch) {
      setError(backtestWriteDisabledReason)
      return
    }
    setRandomSubmitting(true)
    setError('')
    try {
      const result = await createSignalOpsRandomValidationJob({
        mode: randomMode,
        history_years: 10,
        min_window_days: 365,
        max_window_days: 540,
        min_trading_days: 200,
        initial_capital: form.initial_capital,
      })
      setRandomJob(result)
    } catch (e) {
      reportError('创建 SignalOps 随机验证任务失败', e)
      setError(e instanceof Error ? e.message : '启动 SignalOps 随机验证失败')
    } finally {
      setRandomSubmitting(false)
    }
  }

  const handleCancelRandomValidation = async () => {
    if (!canControlBacktestJobs) {
      setError(backtestJobControlDisabledReason)
      return
    }
    if (!randomJob) return
    setError('')
    try {
      const result = await cancelSignalOpsRandomValidationJob(randomJob.jobId)
      setRandomJob(result)
    } catch (e) {
      reportError('取消 SignalOps 随机验证任务失败', e)
      setError(e instanceof Error ? e.message : '取消 SignalOps 随机验证失败')
    }
  }

  const handleDelete = async (run: BacktestRunItem) => {
    if (!canDeleteBacktestRuns) {
      setError(`回测记录删除需要 admin 权限。当前角色：${operator.role}。`)
      return
    }
    const label = deleteRunLabel(run)
    if (!window.confirm(`确定${label} ${run.symbol}（${run.run_id}）？此操作会删除该回测记录、交易和信号明细。`)) return
    setError('')
    setDeletingRunId(run.run_id)
    try {
      await deleteBacktestRun(run.run_id)
      if (selectedRun?.run_id === run.run_id) {
        detailRequestRef.current += 1
        setSelectedRun(null)
        setTrades([])
        setSignals([])
      }
      await refresh()
    } catch (e) {
      reportError('删除回测运行失败', e)
      setError(e instanceof Error ? e.message : '删除回测失败')
    } finally {
      setDeletingRunId(null)
    }
  }

  const handleDownloadExperimentPackage = async () => {
    if (!selectedRun) return
    setPackageDownloading(true)
    setError('')
    try {
      const pkg = await getBacktestExperimentPackage(selectedRun.run_id)
      const blob = new Blob([JSON.stringify(pkg, null, 2)], { type: 'application/json' })
      const url = window.URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `${pkg.package_id || selectedRun.run_id}-experiment-package.json`
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
    } catch (e) {
      reportError('下载回测实验包失败', e)
      setError(e instanceof Error ? e.message : 'Download backtest experiment package failed')
    } finally {
      setPackageDownloading(false)
    }
  }

  const handleCreateResearchVerdictInputs = async () => {
    if (!canWriteBacktestResearch) {
      setError(backtestWriteDisabledReason)
      return
    }
    if (!selectedRun || !researchIterationId) return
    setVerdictLinking(true)
    setError('')
    setVerdictNotice(null)
    try {
      const result = await createResearchBacktestVerdictInputs(selectedRun.run_id, {
        iteration_id: researchIterationId,
        reviewer: 'human',
        role: 'candidate',
        note: 'Create verdict inputs from Backtest page.',
        refresh: true,
      })
      setVerdictNotice({
        iterationId: result.iteration.iteration_id,
        engineVerdict: result.verdict_inputs.engine_verdict,
        canAccept: result.verdict_inputs.can_accept_feedback,
        blockers: result.verdict_inputs.blocking_reasons || [],
        evidenceUsage: result.evidence_usage,
        supportingOnly: result.supporting_only,
        simulationOnly: result.simulation_only,
        isRealTrade: result.is_real_trade,
        strongConclusionAllowed: result.strong_conclusion_allowed,
      })
    } catch (e) {
      reportError('从回测创建研究裁决输入失败', e)
      setError(e instanceof Error ? e.message : '创建研究结论输入失败')
    } finally {
      setVerdictLinking(false)
    }
  }

  const latestParameterScanJobAttempt = parameterScanJob?.attempts?.length
    ? parameterScanJob.attempts[parameterScanJob.attempts.length - 1]
    : null
  const parameterScanHandoffStatus = parameterScanJob?.handoffStatus || null
  const parameterScanHandoffIssues = Array.isArray(parameterScanHandoffStatus?.issues)
    ? parameterScanHandoffStatus.issues
    : []
  const backtestGovernance = buildBacktestRunGovernance({
    selectedRun,
    scanNotice,
    parameterScanJob,
    sampleNotice,
    randomJob,
    verdictNotice,
  })
  const scanNoticeGovernance = scanNotice ? buildBacktestParameterScanGovernance(scanNotice) : null
  const parameterScanJobGovernance = parameterScanJob ? buildBacktestParameterScanJobGovernance(parameterScanJob) : null

  const tabs = [
    { key: 'report' as const, label: '报告', icon: BarChart3, count: hasReport(selectedRun?.report) ? `${selectedRun.report.winning_trades}胜/${selectedRun.report.losing_trades}负` : '' },
    { key: 'trades' as const, label: '交易', icon: ArrowLeftRight, count: trades.length },
    { key: 'signals' as const, label: '信号', icon: Signal, count: signals.length },
    { key: 'comparison' as const, label: '对比', icon: ArrowLeftRight, count: selectedRun?.comparison?.verdict ? displayVerdict(selectedRun.comparison.verdict) : '' },
  ]

  return (
    <div data-testid="backtest-page" className="space-y-5 p-5 max-w-[1600px] mx-auto">
      <SectionTitle
        title="回测"
        subtitle="回测与复盘闭环 — 历史行情回放、T+1/涨跌停/滑点规则验证、信号触发记录、补丁前后对比"
      />

      <div data-testid="backtest-run-governance" className="grid gap-2 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600 sm:grid-cols-2 xl:grid-cols-5">
        <span className="min-w-0 break-words">
          <span className="text-slate-500">ID：</span>
          <span data-testid="backtest-run-governance-id" className="font-mono">{backtestGovernance.contextId}</span>
        </span>
        <span className="min-w-0 break-words">
          <span className="text-slate-500">证据强度：</span>
          <span data-testid="backtest-run-evidence-strength">{backtestGovernance.evidenceStrength}</span>
        </span>
        <span className="min-w-0 break-words">
          <span className="text-slate-500">阻断：</span>
          <span data-testid="backtest-run-blocker">{backtestGovernance.blocker}</span>
        </span>
        <span className="min-w-0 break-words">
          <span className="text-slate-500">下一步：</span>
          <span data-testid="backtest-run-next-action">{backtestGovernance.nextAction}</span>
        </span>
        <span className="min-w-0 break-words font-medium text-slate-900" data-testid="backtest-run-simulation-boundary">
          simulation_only={String(backtestGovernance.simulationOnly)} / is_real_trade={String(backtestGovernance.isRealTrade)} / evidence_usage={backtestGovernance.evidenceUsage} / strong_conclusion_allowed={String(backtestGovernance.strongConclusionAllowed)} / SIM_*
        </span>
      </div>

      {!canDeleteBacktestRuns ? (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          回测删除仅限 admin。当前角色：{operator.role}。
        </div>
      ) : null}

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Summary Cards */}
      {summary && (
        <div data-testid="backtest-summary" className="grid grid-cols-3 gap-4">
          <Card className="!p-4 flex items-center gap-4">
            <div className="h-10 w-10 rounded-lg bg-indigo-50 flex items-center justify-center">
              <Activity size={20} className="text-indigo-600" />
            </div>
            <div>
              <div className="text-2xl font-bold text-slate-800">{summary.total_runs}</div>
              <div className="text-xs text-slate-400 uppercase tracking-wide">回测总数</div>
            </div>
          </Card>
          <Card className="!p-4 flex items-center gap-4">
            <div className="h-10 w-10 rounded-lg bg-emerald-50 flex items-center justify-center">
              <CheckCircle2 size={20} className="text-emerald-600" />
            </div>
            <div>
              <div className="text-2xl font-bold text-slate-800">{summary.completed_runs}</div>
              <div className="text-xs text-slate-400 uppercase tracking-wide">已完成</div>
            </div>
          </Card>
          <Card className="!p-4 flex items-center gap-4">
            <div className="h-10 w-10 rounded-lg bg-amber-50 flex items-center justify-center">
              <Clock size={20} className="text-amber-600" />
            </div>
            <div>
              <div className="text-2xl font-bold text-slate-800">{summary.pending_runs}</div>
              <div className="text-xs text-slate-400 uppercase tracking-wide">等待中</div>
            </div>
          </Card>
        </div>
      )}

      {/* Form */}
      <Card title="新建回测">
        <div className="grid grid-cols-1 lg:grid-cols-[minmax(150px,1fr)_minmax(260px,1.5fr)_minmax(150px,1fr)] gap-3 mb-3">
          <div>
            <label className="block text-[11px] font-medium text-slate-500 uppercase tracking-wide mb-1">证券代码</label>
            <input
              data-testid="backtest-symbol"
              type="text"
              value={form.symbol}
              onChange={(e) => updateForm('symbol', e.target.value)}
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 placeholder:text-slate-300 focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100 focus:outline-none transition-all"
            />
          </div>
          <div>
            <label className="block text-[11px] font-medium text-slate-500 uppercase tracking-wide mb-1">回测区间</label>
            <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-2">
              <input
                data-testid="backtest-start-date"
                aria-label="开始日期"
                type="date"
                value={form.start_date}
                onChange={(e) => updateForm('start_date', e.target.value)}
                className="min-w-0 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100 focus:outline-none transition-all"
              />
              <span className="text-slate-400">→</span>
              <input
                data-testid="backtest-end-date"
                aria-label="结束日期"
                type="date"
                value={form.end_date}
                onChange={(e) => updateForm('end_date', e.target.value)}
                className="min-w-0 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100 focus:outline-none transition-all"
              />
            </div>
          </div>
          <div>
            <label className="block text-[11px] font-medium text-slate-500 uppercase tracking-wide mb-1">信号来源</label>
            <select
              data-testid="backtest-signal-source"
              value={form.signal_source}
              onChange={(e) => updateForm('signal_source', e.target.value)}
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100 focus:outline-none transition-all"
            >
              <option value="SIGNALOPS">SignalOps</option>
              <option value="MFE_MAE_PATH_RESEARCH">MFE/MAE路径研究</option>
              <option value="MOCK">模拟信号</option>
              <option value="NONE">无信号</option>
            </select>
          </div>
        </div>
        {showAdvancedForm && (
          <div className="mb-4 grid grid-cols-1 md:grid-cols-3 gap-3 border-t border-slate-100 pt-3">
            <div>
              <label className="block text-[11px] font-medium text-slate-500 uppercase tracking-wide mb-1">证券名称（记录）</label>
              <input
                type="text"
                value={form.stock_name}
                onChange={(e) => updateForm('stock_name', e.target.value)}
                className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 placeholder:text-slate-300 focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100 focus:outline-none transition-all"
              />
            </div>
            <div>
              <label className="block text-[11px] font-medium text-slate-500 uppercase tracking-wide mb-1">初始资金</label>
              <input
                type="number"
                value={form.initial_capital}
                onChange={(e) => updateForm('initial_capital', Number(e.target.value))}
                className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100 focus:outline-none transition-all"
              />
            </div>
            <div>
              <label className="block text-[11px] font-medium text-slate-500 uppercase tracking-wide mb-1">信号日期（可选）</label>
              <input
                type="date"
                value={form.signal_date}
                onChange={(e) => updateForm('signal_date', e.target.value)}
                className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100 focus:outline-none transition-all"
              />
            </div>
            <div>
              <label className="block text-[11px] font-medium text-slate-500 uppercase tracking-wide mb-1">补丁 ID（记录）</label>
              <input
                type="text"
                value={form.patch_id}
                onChange={(e) => updateForm('patch_id', e.target.value)}
                className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 placeholder:text-slate-300 focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100 focus:outline-none transition-all"
              />
            </div>
            <div>
              <label className="block text-[11px] font-medium text-slate-500 uppercase tracking-wide mb-1">案例 ID（记录）</label>
              <input
                type="text"
                value={form.case_id}
                onChange={(e) => updateForm('case_id', e.target.value)}
                className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 placeholder:text-slate-300 focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100 focus:outline-none transition-all"
              />
            </div>
            <div>
              <label className="block text-[11px] font-medium text-slate-500 uppercase tracking-wide mb-1">场景标签（记录）</label>
              <input
                type="text"
                value={form.scenario_label}
                onChange={(e) => updateForm('scenario_label', e.target.value)}
                className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 placeholder:text-slate-300 focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100 focus:outline-none transition-all"
              />
            </div>
            <label className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={form.force_new}
                onChange={(e) => updateForm('force_new', e.target.checked)}
                className="h-4 w-4 rounded border-slate-300 text-indigo-600"
              />
              强制重建，不复用已有回测
            </label>
          </div>
        )}
        <div className="flex flex-wrap items-center gap-3">
          <div className="basis-full flex flex-wrap gap-2 text-xs text-slate-500">
            <span data-testid="backtest-research-write-role">角色：{operator.role}；写入：{canWriteBacktestResearch ? 'researcher+' : '已阻断'}</span>
            {!canWriteBacktestResearch ? (
              <span data-testid="backtest-research-write-disabled-reason" className="text-amber-700">{backtestWriteDisabledReason}</span>
            ) : null}
            <span data-testid="backtest-job-control-role">任务控制：{canControlBacktestJobs ? 'operator+' : '已阻断'}</span>
            {!canControlBacktestJobs ? (
              <span data-testid="backtest-job-control-disabled-reason" className="text-amber-700">{backtestJobControlDisabledReason}</span>
            ) : null}
            <span data-testid="backtest-artifact-handoff-role">产物交接：{canHandoffBacktestArtifacts ? 'admin' : '已阻断'}</span>
            {!canHandoffBacktestArtifacts ? (
              <span data-testid="backtest-artifact-handoff-disabled-reason" className="text-amber-700">{backtestHandoffDisabledReason}</span>
            ) : null}
          </div>
          <button
            data-testid="backtest-run-submit"
            onClick={handleSubmit}
            disabled={submitting || !canWriteBacktestResearch || !form.symbol || !form.start_date || !form.end_date}
            title={!canWriteBacktestResearch ? backtestWriteDisabledReason : undefined}
            className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-indigo-700 disabled:bg-slate-200 disabled:text-slate-400 disabled:cursor-not-allowed transition-all active:scale-[0.98]"
          >
            {submitting ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />}
            {submitting ? '运行中...' : '运行回测'}
          </button>
          <button
            data-testid="backtest-parameter-scan-submit"
            onClick={handleParameterScan}
            disabled={scanSubmitting || !canWriteBacktestResearch || !form.symbol || !form.start_date || !form.end_date}
            title={!canWriteBacktestResearch ? backtestWriteDisabledReason : undefined}
            className="inline-flex items-center gap-2 rounded-lg border border-violet-300 bg-violet-50 px-5 py-2.5 text-sm font-semibold text-violet-800 shadow-sm hover:bg-violet-100 disabled:bg-slate-100 disabled:text-slate-400 disabled:border-slate-200 disabled:cursor-not-allowed transition-all active:scale-[0.98]"
          >
            {scanSubmitting ? <Loader2 size={16} className="animate-spin" /> : <SlidersHorizontal size={16} />}
            {scanSubmitting ? 'Scanning...' : 'Parameter scan'}
          </button>
          <button
            data-testid="backtest-parameter-scan-job-submit"
            onClick={handleParameterScanJob}
            disabled={parameterScanJobSubmitting || isParameterScanJobActive(parameterScanJob) || !canWriteBacktestResearch || !form.symbol || !form.start_date || !form.end_date}
            title={!canWriteBacktestResearch ? backtestWriteDisabledReason : undefined}
            className="inline-flex items-center gap-2 rounded-lg border border-cyan-300 bg-cyan-50 px-5 py-2.5 text-sm font-semibold text-cyan-800 shadow-sm hover:bg-cyan-100 disabled:bg-slate-100 disabled:text-slate-400 disabled:border-slate-200 disabled:cursor-not-allowed transition-all active:scale-[0.98]"
          >
            {parameterScanJobSubmitting || isParameterScanJobActive(parameterScanJob) ? <Loader2 size={16} className="animate-spin" /> : <Clock size={16} />}
            {parameterScanJobSubmitting || isParameterScanJobActive(parameterScanJob) ? 'Queued...' : 'Queue scan'}
          </button>
          <button
            data-testid="backtest-signalops-sample-submit"
            onClick={handleSignalOpsSample}
            disabled={sampleSubmitting || !canWriteBacktestResearch || !form.start_date || !form.end_date}
            title={!canWriteBacktestResearch ? backtestWriteDisabledReason : undefined}
            className="inline-flex items-center gap-2 rounded-lg border border-amber-300 bg-amber-50 px-5 py-2.5 text-sm font-semibold text-amber-800 shadow-sm hover:bg-amber-100 disabled:bg-slate-100 disabled:text-slate-400 disabled:border-slate-200 disabled:cursor-not-allowed transition-all active:scale-[0.98]"
          >
            {sampleSubmitting ? <Loader2 size={16} className="animate-spin" /> : <Signal size={16} />}
            {sampleSubmitting ? '生成中...' : '生成 SignalOps 样例'}
          </button>
          <button
            type="button"
            onClick={() => setShowAdvancedForm((value) => !value)}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold text-slate-600 hover:bg-slate-50 transition-all active:scale-[0.98]"
          >
            <SlidersHorizontal size={16} />
            {showAdvancedForm ? '收起高级' : '高级设置'}
          </button>
          <span className="text-xs text-slate-500">
            使用当前 SignalOps 自动模拟/清洗记录，生命周期信号作为兜底；所有结果仍仅作为模拟弱证据。
          </span>
        </div>
        {scanNotice && (
          <div data-testid="backtest-parameter-scan-notice" className="mt-3 rounded-lg border border-violet-200 bg-violet-50 px-4 py-3 text-sm text-violet-900">
            <div className="font-semibold">
              Parameter scan completed: {scanNotice.scan_id}
            </div>
            <div className="mt-1 text-xs">
              Combinations: {parameterScanCombinationCount(scanNotice)}; windows: {parameterScanWindowCount(scanNotice)}; trials: {parameterScanTrialCount(scanNotice)}; best run: {scanNotice.best_run_id || '-'}; best score: {fmtNum(scanNotice.best_score)}.
              Boundary: simulation_only={String(scanNotice.simulation_only)}; is_real_trade={String(scanNotice.is_real_trade)}.
            </div>
            {scanNoticeGovernance && (
              <div data-testid="backtest-parameter-scan-governance" className="mt-3 grid gap-2 rounded-md border border-violet-200 bg-white/70 p-2 text-xs sm:grid-cols-2 xl:grid-cols-5">
                <span className="min-w-0 break-words">
                  <span className="text-violet-600">ID: </span>
                  <span data-testid="backtest-parameter-scan-governance-id" className="font-mono">{scanNoticeGovernance.contextId}</span>
                </span>
                <span className="min-w-0 break-words">
                  <span className="text-violet-600">Evidence: </span>
                  <span data-testid="backtest-parameter-scan-governance-evidence-strength">{scanNoticeGovernance.evidenceStrength}</span>
                </span>
                <span className="min-w-0 break-words">
                  <span className="text-violet-600">Blocker: </span>
                  <span data-testid="backtest-parameter-scan-governance-blocker">{scanNoticeGovernance.blocker}</span>
                </span>
                <span className="min-w-0 break-words">
                  <span className="text-violet-600">Next: </span>
                  <span data-testid="backtest-parameter-scan-governance-next-action">{scanNoticeGovernance.nextAction}</span>
                </span>
                <span className="min-w-0 break-words font-semibold text-violet-950" data-testid="backtest-parameter-scan-governance-simulation-boundary">
                  simulation_only={String(scanNoticeGovernance.simulationOnly)} / is_real_trade={String(scanNoticeGovernance.isRealTrade)} / evidence_usage={scanNoticeGovernance.evidenceUsage} / strong_conclusion_allowed={String(scanNoticeGovernance.strongConclusionAllowed)} / SIM_*
                </span>
              </div>
            )}
          </div>
        )}
        {parameterScanJob && (
          <div data-testid="backtest-parameter-scan-job-status" className="mt-3 rounded-lg border border-cyan-200 bg-cyan-50 px-4 py-3 text-sm text-cyan-950">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="font-semibold">
                Async parameter scan job: {parameterScanJob.jobId}
              </div>
              <span className="rounded-full bg-white px-2 py-0.5 text-xs font-semibold text-cyan-800">
                {parameterScanJob.status} / {parameterScanJob.progressStep || '-'}
              </span>
            </div>
            <div className="mt-1 text-xs">
              Scan: {parameterScanJob.scanId || '-'}; combinations: {Number(parameterScanJob.totalCombinations || 0)}; windows: {Number(parameterScanJob.windowCount || 0)}; trials: {Number(parameterScanJob.totalTrials || 0)}; best run: {parameterScanJob.bestRunId || '-'}.
              Boundary: simulationOnly={String(parameterScanJob.simulationOnly)}; isRealTrade={String(parameterScanJob.isRealTrade)}.
              Queue: {parameterScanJob.queueMode || '-'}; durable={String(parameterScanJob.durable === true)}; recovered={String(parameterScanJob.recovered === true)}.
              Idempotency: {parameterScanJob.idempotencyKey || '-'}; attempts: {Number(parameterScanJob.attemptCount || 0)}; current attempt: {parameterScanJob.currentAttemptId || '-'}; last attempt: {parameterScanJob.lastAttemptStatus || latestParameterScanJobAttempt?.status || '-'}.
              Lease: {parameterScanJob.leaseStatus || '-'}; owner: {parameterScanJob.leaseOwner || '-'}; lease id: {parameterScanJob.leaseId || '-'}; expires: {parameterScanJob.leaseExpiresAt || '-'}.
              Latest attempt: {latestParameterScanJobAttempt?.attemptId || '-'} / {latestParameterScanJobAttempt?.status || '-'}; recovered attempt={String(latestParameterScanJobAttempt?.recovered === true)}.
            </div>
            {parameterScanJobGovernance && (
              <div data-testid="backtest-parameter-scan-job-governance" className="mt-3 grid gap-2 rounded-md border border-cyan-200 bg-white/70 p-2 text-xs sm:grid-cols-2 xl:grid-cols-5">
                <span className="min-w-0 break-words">
                  <span className="text-cyan-700">ID: </span>
                  <span data-testid="backtest-parameter-scan-job-governance-id" className="font-mono">{parameterScanJobGovernance.contextId}</span>
                </span>
                <span className="min-w-0 break-words">
                  <span className="text-cyan-700">Evidence: </span>
                  <span data-testid="backtest-parameter-scan-job-governance-evidence-strength">{parameterScanJobGovernance.evidenceStrength}</span>
                </span>
                <span className="min-w-0 break-words">
                  <span className="text-cyan-700">Blocker: </span>
                  <span data-testid="backtest-parameter-scan-job-governance-blocker">{parameterScanJobGovernance.blocker}</span>
                </span>
                <span className="min-w-0 break-words">
                  <span className="text-cyan-700">Next: </span>
                  <span data-testid="backtest-parameter-scan-job-governance-next-action">{parameterScanJobGovernance.nextAction}</span>
                </span>
                <span className="min-w-0 break-words font-semibold text-cyan-950" data-testid="backtest-parameter-scan-job-governance-simulation-boundary">
                  simulation_only={String(parameterScanJobGovernance.simulationOnly)} / is_real_trade={String(parameterScanJobGovernance.isRealTrade)} / evidence_usage={parameterScanJobGovernance.evidenceUsage} / strong_conclusion_allowed={String(parameterScanJobGovernance.strongConclusionAllowed)} / SIM_*
                </span>
              </div>
            )}
            {parameterScanJob.error && (
              <div className="mt-1 text-xs text-red-700">
                Error: {parameterScanJob.error}
              </div>
            )}
            {isParameterScanJobActive(parameterScanJob) && (
              <button
                type="button"
                data-testid="backtest-parameter-scan-job-cancel"
                onClick={handleCancelParameterScanJob}
                disabled={!canControlBacktestJobs}
                title={!canControlBacktestJobs ? backtestJobControlDisabledReason : undefined}
                className="mt-2 inline-flex items-center gap-1 rounded-md border border-cyan-200 bg-white px-2.5 py-1 text-xs font-semibold text-cyan-700 hover:bg-cyan-50 disabled:cursor-not-allowed disabled:border-slate-200 disabled:text-slate-400"
              >
                <Square size={13} />
                Cancel job
              </button>
            )}
            {!isParameterScanJobActive(parameterScanJob) && (
              <button
                type="button"
                data-testid="backtest-parameter-scan-job-handoff"
                onClick={handleHandoffParameterScanJob}
                disabled={parameterScanJobHandoffSubmitting || !canHandoffBacktestArtifacts || parameterScanJob.status !== 'COMPLETED'}
                title={!canHandoffBacktestArtifacts ? backtestHandoffDisabledReason : undefined}
                className="mt-2 inline-flex items-center gap-1 rounded-md border border-cyan-200 bg-white px-2.5 py-1 text-xs font-semibold text-cyan-700 hover:bg-cyan-50 disabled:cursor-not-allowed disabled:border-slate-200 disabled:text-slate-400"
              >
                {parameterScanJobHandoffSubmitting ? <Loader2 size={13} className="animate-spin" /> : <UploadCloud size={13} />}
                {parameterScanJobHandoffSubmitting ? 'Handing off...' : 'Handoff artifacts'}
              </button>
            )}
            {parameterScanJobHandoff && (
              <div data-testid="backtest-parameter-scan-job-handoff-status" className="mt-2 rounded-md border border-cyan-100 bg-white/80 px-3 py-2 text-xs text-cyan-900">
                Handoff: {parameterScanJobHandoff.status || '-'}; destination: {parameterScanJobHandoff.handoffDestination || '-'}; checksum: {parameterScanJobHandoff.bundleChecksum || '-'}; manifest: {parameterScanJobHandoff.manifestFile || '-'}.
                Boundary: simulationOnly={String(parameterScanJobHandoff.simulationOnly)}; isRealTrade={String(parameterScanJobHandoff.isRealTrade)}.
              </div>
            )}
            <div data-testid="backtest-parameter-scan-job-handoff-custody" className="mt-2 rounded-md border border-cyan-100 bg-white/80 px-3 py-2 text-xs text-cyan-900">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span>
                  Custody: {parameterScanHandoffStatus?.status || '-'}; provider: {parameterScanHandoffStatus?.provider || '-'}; reported={String(parameterScanHandoffStatus?.reported === true)}; latest match {parameterScanHandoffStatus?.matchesLatestHandoff ? 'yes' : 'no'}; job match {parameterScanHandoffStatus?.matchesJob ? 'yes' : 'no'}; search ready {parameterScanHandoffStatus?.searchIndexReady ? 'yes' : 'no'}.
                </span>
                <button
                  type="button"
                  data-testid="backtest-parameter-scan-job-handoff-refresh"
                  onClick={handleRefreshParameterScanJobHandoffStatus}
                  disabled={parameterScanJobHandoffRefreshing}
                  className="inline-flex items-center gap-1 rounded-md border border-cyan-200 bg-white px-2 py-1 font-semibold text-cyan-700 hover:bg-cyan-50 disabled:cursor-not-allowed disabled:border-slate-200 disabled:text-slate-400"
                >
                  {parameterScanJobHandoffRefreshing ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
                  刷新托管
                </button>
              </div>
              <div className="mt-1">
                destination: {parameterScanHandoffStatus?.handoffDestination || '-'}; remote: {parameterScanHandoffStatus?.remoteDestination || '-'}; object: {parameterScanHandoffStatus?.objectKey || '-'}; retention: {parameterScanHandoffStatus?.retentionPolicyId || parameterScanHandoffStatus?.retentionStatus || '-'}; manifest: {parameterScanHandoffStatus?.latestManifestFile || '-'}.
              </div>
              {parameterScanHandoffIssues.length > 0 && (
                <div className="mt-1 text-amber-700">
                  issues: {parameterScanHandoffIssues.slice(0, 4).join(', ')}
                </div>
              )}
            </div>
          </div>
        )}
        {sampleNotice && (
          <div data-testid="backtest-signalops-sample-notice" className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
            <div className="font-semibold">
              SignalOps 样例已生成：{sampleNotice.runId}
            </div>
            <div className="mt-1 text-xs">
              行情来源：{sampleNotice.marketDataSource}；证据等级：{sampleNotice.evidenceGrade || '未知'}。
              除非报告明确说明，否则该样例仅供复核，不能视为强研究结论。
            </div>
            {sampleNotice.limitations.length > 0 && (
              <ul className="mt-2 list-disc pl-5 text-xs">
                {sampleNotice.limitations.slice(0, 3).map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            )}
          </div>
        )}
      </Card>

      <SignalOpsRandomValidationPanel
        job={randomJob}
        mode={randomMode}
        submitting={randomSubmitting}
        canStart={canWriteBacktestResearch}
        canCancel={canControlBacktestJobs}
        startDisabledReason={backtestWriteDisabledReason}
        cancelDisabledReason={backtestJobControlDisabledReason}
        onModeChange={setRandomMode}
        onStart={handleSignalOpsRandomValidation}
        onCancel={handleCancelRandomValidation}
      />

      {/* Main Content */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
        {/* History Sidebar */}
        <div className="lg:col-span-4 space-y-4">
          <Card title="参数扫描历史">
            <div data-testid="backtest-parameter-scan-history" className="space-y-2">
              {loading ? (
                <Loading label="正在加载参数扫描..." />
              ) : parameterScans.length === 0 ? (
                <EmptyState icon={SlidersHorizontal} text="No parameter scans" />
              ) : (
                parameterScans.map((scan) => {
                  const scanGovernance = buildBacktestParameterScanGovernance(scan)
                  return (
                    <div
                      key={scan.scan_id}
                      data-testid="backtest-parameter-scan-history-item"
                      className={cls(
                        'rounded-lg border px-3 py-2 text-xs',
                        scan.best_run_id === selectedRun?.run_id
                          ? 'border-violet-300 bg-violet-50'
                          : 'border-slate-200 bg-white',
                      )}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <div className="truncate font-mono font-semibold text-violet-800">{scan.scan_id}</div>
                          <div className="mt-1 text-slate-500">
                            {scan.symbol} {scan.start_date || '-'} {'->'} {scan.end_date || '-'}
                          </div>
                        </div>
                        <span className="rounded-full bg-slate-100 px-2 py-0.5 font-medium text-slate-600">
                          {scan.status}
                        </span>
                      </div>
                      <div className="mt-2 grid grid-cols-2 gap-x-2 gap-y-1 text-slate-600">
                        <span>Trials: {parameterScanTrialCount(scan)}</span>
                        <span>Windows: {parameterScanWindowCount(scan)}</span>
                        <span>Combos: {parameterScanCombinationCount(scan)}</span>
                        <span>Best: {fmtNum(Number(scan.best_score || 0))}</span>
                        <span>sim: {String(scan.simulation_only)}</span>
                        <span>real: {String(scan.is_real_trade)}</span>
                      </div>
                      <div className="mt-1 truncate font-mono text-[11px] text-slate-500">
                        Best run: {scan.best_run_id || '-'}
                      </div>
                      <div data-testid="backtest-parameter-scan-history-governance" className="mt-2 space-y-1 rounded-md border border-slate-200 bg-slate-50 p-2 text-[11px] text-slate-600">
                        <div className="min-w-0 break-words">
                          <span className="text-slate-500">ID: </span>
                          <span data-testid="backtest-parameter-scan-history-governance-id" className="font-mono">{scanGovernance.contextId}</span>
                        </div>
                        <div className="min-w-0 break-words">
                          <span className="text-slate-500">Evidence: </span>
                          <span data-testid="backtest-parameter-scan-history-evidence-strength">{scanGovernance.evidenceStrength}</span>
                        </div>
                        <div className="min-w-0 break-words">
                          <span className="text-slate-500">Blocker: </span>
                          <span data-testid="backtest-parameter-scan-history-blocker">{scanGovernance.blocker}</span>
                        </div>
                        <div className="min-w-0 break-words">
                          <span className="text-slate-500">Next: </span>
                          <span data-testid="backtest-parameter-scan-history-next-action">{scanGovernance.nextAction}</span>
                        </div>
                        <div className="min-w-0 break-words font-semibold text-slate-800" data-testid="backtest-parameter-scan-history-simulation-boundary">
                          simulation_only={String(scanGovernance.simulationOnly)} / is_real_trade={String(scanGovernance.isRealTrade)} / evidence_usage={scanGovernance.evidenceUsage} / strong_conclusion_allowed={String(scanGovernance.strongConclusionAllowed)} / SIM_*
                        </div>
                      </div>
                      <button
                        type="button"
                        data-testid="backtest-parameter-scan-history-open-best"
                        onClick={() => scan.best_run_id && selectRun(scan.best_run_id)}
                        disabled={!scan.best_run_id}
                        className="mt-2 inline-flex items-center gap-1 rounded-md border border-violet-200 bg-white px-2.5 py-1 text-xs font-semibold text-violet-700 hover:bg-violet-50 disabled:border-slate-200 disabled:text-slate-400 disabled:cursor-not-allowed"
                      >
                        <Target size={13} />
                        Open best run
                      </button>
                    </div>
                  )
                })
              )}
            </div>
          </Card>
          <Card title={`历史记录（${runs.length}）`}>
            {loading ? (
              <Loading label="正在加载回测记录..." />
            ) : runs.length === 0 ? (
              <EmptyState icon={Clock} text="暂无回测记录" />
            ) : (
              <div className="space-y-2 max-h-[600px] overflow-y-auto pr-1">
                {runs.map((run) => (
                  <RunHistoryItem
                    key={run.run_id}
                    run={run}
                    selected={selectedRun?.run_id === run.run_id}
                    deleting={deletingRunId === run.run_id}
                    deleteDisabledReason={deleteDisabledReason}
                    onSelect={() => selectRun(run.run_id)}
                    onDelete={() => handleDelete(run)}
                  />
                ))}
              </div>
            )}
          </Card>
        </div>

        {/* Detail Panel */}
        <div className="lg:col-span-8">
          {detailLoading ? (
            <Card><Loading label="正在加载详情..." /></Card>
          ) : selectedRun ? (
            <Card>
              {/* Header */}
              <div data-testid="backtest-selected-run" className="mb-5 flex flex-wrap items-start justify-between gap-3">
                <div className="flex flex-wrap items-center gap-3">
                  <div className="flex items-center gap-2">
                    <div className="h-8 w-8 rounded-lg bg-indigo-50 flex items-center justify-center">
                      <BarChart3 size={16} className="text-indigo-600" />
                    </div>
                    <h3 className="text-lg font-bold text-slate-800">{selectedRun.symbol}</h3>
                  </div>
                  <span data-testid="backtest-selected-run-id" className="text-xs font-mono text-slate-500">
                    {selectedRun.run_id}
                  </span>
                  {selectedRun.stock_name && (
                    <span className="text-sm text-slate-400">{selectedRun.stock_name}</span>
                  )}
                  <span className="text-sm text-slate-400 flex items-center gap-1">
                    <Clock size={13} />
                    {selectedRun.start_date} → {selectedRun.end_date}
                  </span>
                  {selectedRun.patch_id && (
                    <span className="text-[11px] bg-purple-50 text-purple-700 px-2.5 py-1 rounded-full font-medium border border-purple-100">
                      补丁：{selectedRun.patch_id}
                    </span>
                  )}
                  {selectedRun.scenario_label && (
                    <span className="text-[11px] bg-slate-100 text-slate-600 px-2.5 py-1 rounded-full font-medium">
                      {selectedRun.scenario_label}
                    </span>
                  )}
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  {researchIterationId && (
                    <button
                      type="button"
                      data-testid="backtest-create-verdict-inputs"
                      onClick={handleCreateResearchVerdictInputs}
                      disabled={verdictLinking || !canWriteBacktestResearch}
                      title={!canWriteBacktestResearch ? backtestWriteDisabledReason : undefined}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-100 bg-white px-3 py-2 text-xs font-semibold text-emerald-700 shadow-sm hover:bg-emerald-50 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {verdictLinking ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
                      结论输入
                    </button>
                  )}
                  <button
                    type="button"
                    data-testid="backtest-experiment-package-download"
                    onClick={handleDownloadExperimentPackage}
                    disabled={packageDownloading}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-indigo-100 bg-white px-3 py-2 text-xs font-semibold text-indigo-600 shadow-sm hover:bg-indigo-50 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {packageDownloading ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
                    Experiment package
                  </button>
                  <button
                    type="button"
                    onClick={() => handleDelete(selectedRun)}
                    disabled={deletingRunId === selectedRun.run_id || !canDeleteBacktestRuns}
                    title={deleteDisabledReason}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-red-100 bg-white px-3 py-2 text-xs font-semibold text-red-600 shadow-sm hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {deletingRunId === selectedRun.run_id ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
                    {deleteRunLabel(selectedRun)}
                  </button>
                </div>
              </div>
              {verdictNotice && (
                <div data-testid="backtest-verdict-inputs-notice" className="mb-4 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900">
                  <div className="font-semibold">Research verdict inputs refreshed for {verdictNotice.iterationId}</div>
                  <div className="mt-1 text-xs">
                    Engine verdict: {verdictNotice.engineVerdict}; can accept: {String(verdictNotice.canAccept)}; blockers: {verdictNotice.blockers.length}.
                  </div>
                  <div data-testid="backtest-verdict-inputs-boundary" className="mt-1 text-xs">
                    evidence_usage={verdictNotice.evidenceUsage} / supporting_only={String(verdictNotice.supportingOnly)} / simulation_only={String(verdictNotice.simulationOnly)} / is_real_trade={String(verdictNotice.isRealTrade)} / strong_conclusion_allowed={String(verdictNotice.strongConclusionAllowed)} / SIM_*
                  </div>
                </div>
              )}

              {/* Tabs */}
              <div className="flex border-b border-slate-100 mb-5">
                {tabs.map((tab) => {
                  const TabIcon = tab.icon
                  const active = activeTab === tab.key
                  return (
                    <button
                      key={tab.key}
                      onClick={() => setActiveTab(tab.key)}
                      className={cls(
                        'flex items-center gap-1.5 px-4 py-2.5 text-sm font-semibold border-b-2 transition-colors',
                        active
                          ? 'border-indigo-500 text-indigo-600'
                          : 'border-transparent text-slate-400 hover:text-slate-600'
                      )}
                    >
                      <TabIcon size={14} />
                      {tab.label}
                      {tab.count !== '' && (
                        <span className={cls(
                          'text-[10px] px-1.5 py-0.5 rounded-full font-medium',
                          active ? 'bg-indigo-100 text-indigo-700' : 'bg-slate-100 text-slate-500'
                        )}>
                          {tab.count}
                        </span>
                      )}
                    </button>
                  )
                })}
              </div>

              {/* Tab Content */}
              {activeTab === 'report' && hasReport(selectedRun.report) && <ReportPanel report={selectedRun.report} />}
              {activeTab === 'report' && !hasReport(selectedRun.report) && <EmptyState icon={BarChart3} text="暂无报告数据" />}

              {activeTab === 'trades' && (
                trades.length === 0 ? (
                  <EmptyState icon={ArrowLeftRight} text="暂无交易记录" />
                ) : (
                  <TableShell>
                    <table className="institution-table">
                      <thead className="bg-slate-50">
                        <tr className="text-xs text-slate-500 uppercase tracking-wide">
                          <th className="text-left py-2.5 px-3 font-medium">时间</th>
                          <th className="text-left py-2.5 px-3 font-medium">方向</th>
                          <th className="text-right py-2.5 px-3 font-medium">价格</th>
                          <th className="text-right py-2.5 px-3 font-medium">数量</th>
                          <th className="text-right py-2.5 px-3 font-medium">金额</th>
                          <th className="text-right py-2.5 px-3 font-medium">滑点</th>
                          <th className="text-right py-2.5 px-3 font-medium">盈亏</th>
                        </tr>
                      </thead>
                      <tbody>
                        {trades.map((t) => (
                          <tr key={t.trade_id} className="border-t border-slate-50 hover:bg-slate-50/50 transition-colors">
                            <td className="py-2 px-3 text-slate-600 text-xs">{t.timestamp}</td>
                            <td className="py-2 px-3">
                              <span className={cls(
                                'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold',
                                t.direction === 'BUY' ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-700'
                              )}>
                                {t.direction === 'BUY' ? <TrendingUp size={10} /> : <TrendingDown size={10} />}
                                {displayDirection(t.direction)}
                              </span>
                            </td>
                            <td className="py-2 px-3 text-right font-mono text-xs">{t.price.toFixed(2)}</td>
                            <td className="py-2 px-3 text-right font-mono text-xs">{t.quantity}</td>
                            <td className="py-2 px-3 text-right font-mono text-xs">{t.amount.toFixed(2)}</td>
                            <td className="py-2 px-3 text-right text-slate-400 font-mono text-xs">{t.slippage.toFixed(2)}</td>
                            <td className={cls(
                              'py-2 px-3 text-right font-mono text-xs font-semibold',
                              (t.realized_pnl ?? 0) >= 0 ? 'text-emerald-600' : 'text-red-600'
                            )}>
                              {t.realized_pnl != null ? t.realized_pnl.toFixed(2) : '-'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </TableShell>
                )
              )}

              {activeTab === 'signals' && (
                signals.length === 0 ? (
                  <EmptyState icon={Signal} text="暂无信号记录" />
                ) : (
                  <TableShell>
                    <table className="institution-table">
                      <thead className="bg-slate-50">
                        <tr className="text-xs text-slate-500 uppercase tracking-wide">
                          <th className="text-left py-2.5 px-3 font-medium">时间</th>
                          <th className="text-left py-2.5 px-3 font-medium">类型</th>
                          <th className="text-left py-2.5 px-3 font-medium">方向</th>
                          <th className="text-left py-2.5 px-3 font-medium">版本</th>
                          <th className="text-left py-2.5 px-3 font-medium">仅模拟</th>
                          <th className="text-right py-2.5 px-3 font-medium">强度</th>
                          <th className="text-right py-2.5 px-3 font-medium">价格</th>
                          <th className="text-left py-2.5 px-3 font-medium">来源节点</th>
                        </tr>
                      </thead>
                      <tbody>
                        {signals.map((s) => (
                          <tr key={s.signal_id} className="border-t border-slate-50 hover:bg-slate-50/50 transition-colors">
                            <td className="py-2 px-3 text-slate-600 text-xs">{s.timestamp}</td>
                            <td className="py-2 px-3 text-xs">
                              <span className="px-2 py-0.5 rounded-full bg-slate-100 text-slate-600 font-medium">{displaySignalType(s.signal_type)}</span>
                            </td>
                            <td className="py-2 px-3">
                              <span className={cls(
                                'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold',
                                s.direction === 'BUY'
                                  ? 'bg-emerald-50 text-emerald-700'
                                  : s.direction === 'SELL'
                                    ? 'bg-red-50 text-red-700'
                                    : 'bg-slate-100 text-slate-600'
                              )}>
                                {s.direction === 'BUY' ? <TrendingUp size={10} /> : s.direction === 'SELL' ? <TrendingDown size={10} /> : <Signal size={10} />}
                                {displayDirection(s.direction)}
                              </span>
                            </td>
                            <td className="py-2 px-3 text-xs font-mono text-slate-500">{signalOpsVersionFor(s, selectedRun.report)}</td>
                            <td className="py-2 px-3 text-xs text-slate-500">{signalOpsSimulationOnlyFor(s, selectedRun.report)}</td>
                            <td className="py-2 px-3 text-right">
                              <div className="flex items-center justify-end gap-2">
                                <div className="w-16 h-1.5 bg-slate-100 rounded-full overflow-hidden">
                                  <div
                                    className={cls(
                                      'h-full rounded-full transition-all',
                                      s.strength > 0.6 ? 'bg-emerald-500' : s.strength > 0.3 ? 'bg-amber-500' : 'bg-slate-400'
                                    )}
                                    style={{ width: `${s.strength * 100}%` }}
                                  />
                                </div>
                                <span className="text-xs font-mono w-8 text-right">{s.strength.toFixed(2)}</span>
                              </div>
                            </td>
                            <td className="py-2 px-3 text-right font-mono text-xs">{s.price.toFixed(2)}</td>
                            <td className="py-2 px-3 text-xs text-slate-500">{displaySourceNode(s.source_node)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </TableShell>
                )
              )}

              {activeTab === 'comparison' && <ComparisonPanel comparison={selectedRun.comparison} />}
            </Card>
          ) : (
            <Card>
              <EmptyState icon={BarChart3} text="从历史记录中选择一次回测查看详情" />
            </Card>
          )}
        </div>
      </div>
    </div>
  )
}
