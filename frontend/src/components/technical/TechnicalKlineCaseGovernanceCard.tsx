import { useCallback, useEffect, useState } from 'react'
import { CheckCircle2, RefreshCw } from 'lucide-react'
import type { AnalysisRun } from '../../types'
import {
  getTechnicalKlineGovernance,
  recordTechnicalKlineCase,
  type TechnicalKlineCaseRecord,
  type TechnicalKlineGovernance,
} from '../../api/technicalKlineClient'
import { roleAllows, type OperatorRole, useOperatorContext } from '../../store/operatorContext'
import { Badge } from '../common/Badge'
import { Card } from '../common/Card'

type CaseClassification = 'valid' | 'misjudge' | 'insufficient_data'

const CLASSIFICATION_OPTIONS: Array<{ value: CaseClassification; label: string }> = [
  { value: 'valid', label: '有效' },
  { value: 'misjudge', label: '误判' },
  { value: 'insufficient_data', label: '数据不足' },
]

const CLASSIFICATION_LABELS: Record<CaseClassification, string> = {
  valid: '有效',
  misjudge: '误判',
  insufficient_data: '数据不足',
}

const ROLE_LABELS: Record<OperatorRole, string> = {
  viewer: '查看者',
  researcher: '研究员',
  operator: '操作员',
  admin: '管理员',
}

const GOVERNANCE_LABELS: Record<string, string> = {
  UNAVAILABLE: '不可用',
  READY: '已就绪',
  RUNNING: '运行中',
  WAIT: '等待中',
  NO_CASES: '暂无案例',
  LOW_SAMPLE: '样本偏少',
  LOW_COVERAGE: '覆盖不足',
  READY_FOR_REVIEW: '待复核',
  NO_CURRENT_CONFIG_CASES: '当前配置暂无案例',
  LOW_CURRENT_CONFIG_SAMPLE: '当前配置样本偏少',
  INCOMPLETE_REPRESENTATIVE_CASE_SET: '代表性案例集不完整',
  NO_BASELINE_CONFIG: '暂无基线配置',
  REVIEW_ONLY_PARAMETER_GOVERNANCE: '仅复核参数治理',
  REVIEW_ONLY_NO_TRADE_ACTION: '仅复核，不触发交易动作',
  NO_DIRECT_TRADE_ACTION: '不产生直接交易动作',
  SUPPORTING_ONLY: '仅辅助',
  VALID: '有效',
  MISJUDGE: '误判',
  INSUFFICIENT_DATA: '数据不足',
  REVIEW_READY: '进入复核',
  EXPAND_REPRESENTATIVE_HISTORY: '扩充代表性案例历史',
  RECORD_CURRENT_CONFIG_CASES: '记录当前配置案例',
  EXPAND_CURRENT_CONFIG_CASES: '扩充当前配置案例',
  RECORD_PREVIOUS_OR_BASELINE_CONFIG_CASES: '记录历史或基线配置案例',
  REVIEW_PARAMETER_VERSION_DELTA: '复核参数版本差异',
  RECORD_REVIEWED_LONG_WINDOW_CASES: '记录长窗口已复核案例',
  EXPAND_LONG_WINDOW_REVIEW_HISTORY: '扩充长窗口复核历史',
  RECORD_CURRENT_CONFIG_LONG_WINDOW_CASES: '记录当前配置长窗口案例',
  RETAIN_BASELINE_CONFIG_LONG_WINDOW_CASES: '保留基线配置长窗口案例',
  REVIEW_LONG_WINDOW_PARAMETER_REGRESSION: '复核长窗口参数回归',
  REVIEWED_REAL_TUSHARE_KLINE_CASES_ONLY: '仅使用已复核的真实 Tushare K 线案例',
  RETAINED_REVIEW_HISTORY: '已留存复核历史',
  LAST_200_GOVERNANCE_CASES: '最近 200 条治理案例',
  CURRENT_CONFIG: '当前配置',
  BASELINE_CONFIGS: '基线配置',
  ALL_NON_CURRENT_RETAINED_CONFIGS: '全部非当前留存配置',
}

function normalizeClassification(value?: string | null): CaseClassification {
  if (value === 'misjudge' || value === 'insufficient_data' || value === 'valid') return value
  return 'valid'
}

function formatCaseMessage(record: TechnicalKlineCaseRecord) {
  return `案例已记录：${record.caseId}${record.caseLibraryCaseId ? ` / 案例库：${record.caseLibraryCaseId}` : ''}`
}

function displayClassification(value?: string | null) {
  const raw = String(value ?? '').trim()
  if (raw === 'valid' || raw === 'misjudge' || raw === 'insufficient_data') {
    return CLASSIFICATION_LABELS[raw]
  }
  return GOVERNANCE_LABELS[raw.toUpperCase()] ?? raw
}

function displayClassificationList(values: string[]) {
  return values.length ? values.map(displayClassification).join('、') : '无'
}

function displayRole(role: OperatorRole) {
  return ROLE_LABELS[role] ?? role
}

function displayGovernanceCode(value?: string | null, fallback = '-') {
  const raw = String(value ?? '').trim()
  if (!raw) return fallback
  return GOVERNANCE_LABELS[raw.toUpperCase()] ?? localizeGovernanceText(raw)
}

function localizeGovernanceText(value: string) {
  return value
    .replace(/MISSING_TECHNICAL_KLINE_CLASSIFICATION:([a-z_]+)/gi, (_, classification: string) => (
      `缺少技术K线分类：${displayClassification(classification)}`
    ))
    .replace(/Add (\d+) reviewed Technical Kline case\(s\)\./gi, '补充 $1 条已复核技术K线案例。')
    .replace(/Add reviewed Technical Kline cases from (\d+) additional symbol\(s\)\./gi, '再补充 $1 个标的的已复核技术K线案例。')
    .replace(/Add reviewed Technical Kline cases classified as: ([a-z_,\s]+)\./gi, (_, classifications: string) => (
      `补充分类为 ${displayClassificationList(classifications.split(',').map((item) => item.trim()).filter(Boolean))} 的已复核技术K线案例。`
    ))
    .replace(/Representative case set is ready for review-only parameter governance\./gi, '代表性案例集已满足仅复核参数治理。')
    .replace(/\bNO_DIRECT_TRADE_ACTION\b/g, GOVERNANCE_LABELS.NO_DIRECT_TRADE_ACTION)
    .replace(/\bREVIEW_ONLY_NO_TRADE_ACTION\b/g, GOVERNANCE_LABELS.REVIEW_ONLY_NO_TRADE_ACTION)
    .replace(/\bREVIEW_ONLY_PARAMETER_GOVERNANCE\b/g, GOVERNANCE_LABELS.REVIEW_ONLY_PARAMETER_GOVERNANCE)
    .replace(/\bsupporting_only\b/gi, GOVERNANCE_LABELS.SUPPORTING_ONLY)
}

function formatRate(value?: number | null) {
  if (value === null || value === undefined) return '-'
  return `${Math.round(value * 100)}%`
}

function impactBadgeStatus(status?: string) {
  if (status === 'READY' || status === 'READY_FOR_REVIEW') return 'PASS'
  if (status === 'LOW_SAMPLE' || status === 'LOW_COVERAGE' || status?.startsWith('INCOMPLETE') || status === 'NO_BASELINE_CONFIG') return 'WARN'
  return 'WAIT'
}

function formatDelta(value?: number | null) {
  if (value === null || value === undefined) return '-'
  const pct = Math.round(value * 1000) / 10
  return `${value > 0 ? '+' : ''}${pct}%`
}

export function TechnicalKlineCaseGovernanceCard({ run }: { run: AnalysisRun }) {
  const operator = useOperatorContext()
  const [governance, setGovernance] = useState<TechnicalKlineGovernance | null>(null)
  const [classification, setClassification] = useState<CaseClassification>('valid')
  const [note, setNote] = useState('')
  const [loading, setLoading] = useState(false)
  const [recording, setRecording] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  const canRecordCase = roleAllows(operator.role, 'researcher')
  const disabledReason = canRecordCase
    ? undefined
    : `沉淀技术K线案例需要研究员及以上角色。当前角色：${displayRole(operator.role)}。`
  const technicalKlineCaseBoundaryText = 'simulation_only=true / is_real_trade=false / evidence_usage=technical_kline_review_only / strong_conclusion_allowed=false / SIM_*'

  const loadGovernance = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const data = await getTechnicalKlineGovernance()
      setGovernance(data)
      setClassification(normalizeClassification(data.caseClassification.selected))
    } catch (err) {
      setGovernance(null)
      setError(err instanceof Error ? err.message : '技术K线治理不可用')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadGovernance()
  }, [loadGovernance])

  async function handleRecordCase() {
    if (!canRecordCase) {
      setMessage(disabledReason ?? '技术K线案例沉淀已禁用。')
      return
    }
    if (!governance) {
      setMessage('需要先加载技术K线治理信息，才能记录案例。')
      return
    }
    setRecording(true)
    setMessage('')
    setError('')
    try {
      const saved = await recordTechnicalKlineCase({
        symbol: run.stockCode,
        classification,
        note: note.trim(),
        run_id: run.runId,
        analysis_status: String(run.technicalKline?.status ?? ''),
        technical_bias: String(run.technicalKline?.technicalBias ?? ''),
        config_hash: governance.analysisConfig.configHash,
        prompt_version: governance.promptGovernance.version,
      })
      setMessage(formatCaseMessage(saved))
      setNote('')
      await loadGovernance()
    } catch (err) {
      setMessage(err instanceof Error ? err.message : '技术K线案例记录失败')
    } finally {
      setRecording(false)
    }
  }

  const caseCount = governance?.savedGovernance?.cases.length ?? 0
  const caseImpact = governance?.savedGovernance?.caseImpact
  const latestConfigImpact = caseImpact?.byConfigHash?.[0]
  const representativeCaseSet = caseImpact?.representativeCaseSet
  const parameterVersionReview = caseImpact?.parameterVersionReview
  const longWindowRegression = caseImpact?.longWindowRegression

  return (
    <Card
      title="技术K线案例治理"
      action={
        <button
          type="button"
          data-testid="technical-kline-governance-refresh"
          onClick={loadGovernance}
          disabled={loading}
          className="inline-flex items-center gap-1.5 rounded-md border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 disabled:opacity-50"
        >
          <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
          刷新
        </button>
      }
    >
      <div data-testid="technical-kline-case-governance" className="space-y-4">
        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
          <Badge status={error ? 'WARN' : governance ? 'PASS' : loading ? 'RUNNING' : 'WAIT'}>
            {displayGovernanceCode(error ? 'UNAVAILABLE' : governance ? 'READY' : loading ? 'RUNNING' : 'WAIT')}
          </Badge>
          {governance ? (
            <>
              <span data-testid="technical-kline-governance-config-hash" className="font-mono">
                {governance.analysisConfig.configHash}
              </span>
              <span>{governance.promptGovernance.version}</span>
            </>
          ) : null}
        </div>

        <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-500">
          <span data-testid="technical-kline-card-case-role">
            角色：{displayRole(operator.role)}；案例记录权限：{canRecordCase ? '研究员及以上' : '已阻断'}
          </span>
          <span data-testid="technical-kline-case-governance-simulation-boundary" className="ml-3 inline-flex min-w-0 break-words text-slate-600">
            技术 K 线案例治理仅作为参数复核证据；{technicalKlineCaseBoundaryText}
          </span>
          {!canRecordCase ? (
            <span data-testid="technical-kline-card-case-disabled-reason" className="ml-3 text-amber-700">
              {disabledReason}
            </span>
          ) : null}
        </div>

        {error ? (
          <div
            data-testid="technical-kline-case-governance-error"
            className="rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800"
          >
            {displayGovernanceCode(error, '技术K线治理不可用')}
          </div>
        ) : null}

        <div className="grid gap-3 lg:grid-cols-[180px_minmax(0,1fr)_auto]">
          <label className="space-y-1 text-xs text-slate-600">
            <span>分类</span>
            <select
              data-testid="technical-kline-case-classification"
              value={classification}
              onChange={(event) => setClassification(normalizeClassification(event.target.value))}
              className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm text-slate-900"
            >
              {CLASSIFICATION_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="space-y-1 text-xs text-slate-600">
            <span>复核备注</span>
            <input
              data-testid="technical-kline-case-note"
              value={note}
              onChange={(event) => setNote(event.target.value)}
              placeholder="填写误判、有效或数据不足的原因"
              className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm text-slate-900"
            />
          </label>
          <button
            type="button"
            data-testid="technical-kline-record-case"
            onClick={handleRecordCase}
            disabled={recording || loading || !governance || !canRecordCase}
            title={disabledReason}
            className="inline-flex min-h-[38px] items-center justify-center gap-1.5 self-end rounded-md border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 disabled:opacity-50"
          >
            <CheckCircle2 size={14} />
            记录案例
          </button>
        </div>

        <div className="flex flex-wrap items-center gap-3 text-xs text-slate-500">
          <span>
            运行 <span className="font-mono">{run.runId}</span>
          </span>
          <span>
            标的 <span className="font-mono">{run.stockCode}</span>
          </span>
          <span data-testid="technical-kline-case-count">案例 {caseCount}</span>
        </div>

        {caseImpact ? (
          <div
            data-testid="technical-kline-case-impact"
            className="rounded-md border border-slate-200 bg-white p-3 text-xs text-slate-600"
          >
            <div className="flex flex-wrap items-center gap-2">
              <Badge status={impactBadgeStatus(caseImpact.status)}>{displayGovernanceCode(caseImpact.status)}</Badge>
              <span className="font-semibold text-slate-800">仅复核参数影响</span>
              <span>{displayGovernanceCode(caseImpact.policy.weakSampleAction)}</span>
              <span>{displayGovernanceCode(caseImpact.policy.tradeActionPolicy)}</span>
            </div>
            <div className="mt-3 grid gap-3 md:grid-cols-3">
              <div>
                <div className="text-slate-500">全部已复核案例</div>
                <div className="mt-1 font-semibold text-slate-900">{caseImpact.totalCases}</div>
                <div className="mt-1">误判 {formatRate(caseImpact.misjudgeRate)}</div>
              </div>
              <div data-testid="technical-kline-current-config-impact">
                <div className="text-slate-500">当前配置</div>
                <div className="mt-1 font-mono text-slate-900">{caseImpact.currentConfig.configHash || '-'}</div>
                <div className="mt-1">
                  {caseImpact.currentConfig.caseCount} 条案例 / 误判 {formatRate(caseImpact.currentConfig.misjudgeRate)}
                </div>
              </div>
              <div>
                <div className="text-slate-500">最近复核配置</div>
                <div className="mt-1 font-mono text-slate-900">{latestConfigImpact?.configHash ?? '-'}</div>
                <div className="mt-1">
                  {latestConfigImpact?.totalCases ?? 0} 条案例 / 数据不足{' '}
                  {formatRate(latestConfigImpact?.insufficientDataRate)}
                </div>
              </div>
            </div>
            {caseImpact.warnings.length ? (
              <div data-testid="technical-kline-case-impact-warnings" className="mt-3 flex flex-wrap gap-2">
                {caseImpact.warnings.map((warning) => (
                  <Badge key={warning} status="WARN">
                    {displayGovernanceCode(warning)}
                  </Badge>
                ))}
              </div>
            ) : null}
            {representativeCaseSet ? (
              <div
                data-testid="technical-kline-representative-case-set"
                className="mt-3 rounded-md border border-slate-200 bg-slate-50 p-3"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <Badge status={impactBadgeStatus(representativeCaseSet.status)}>
                    {displayGovernanceCode(representativeCaseSet.status)}
                  </Badge>
                  <span className="font-semibold text-slate-800">代表性案例集</span>
                  <span>{displayGovernanceCode(representativeCaseSet.boundary)}</span>
                </div>
                <div className="mt-3 grid gap-3 md:grid-cols-3">
                  <div>
                    <div className="text-slate-500">已复核案例</div>
                    <div className="mt-1 font-semibold text-slate-900">
                      {representativeCaseSet.reviewedCaseCount} / {representativeCaseSet.minimumReviewedCases}
                    </div>
                  </div>
                  <div>
                    <div className="text-slate-500">标的数</div>
                    <div className="mt-1 font-semibold text-slate-900">
                      {representativeCaseSet.uniqueSymbolCount} / {representativeCaseSet.minimumSymbols}
                    </div>
                  </div>
                  <div data-testid="technical-kline-representative-missing-classes">
                    <div className="text-slate-500">缺少分类</div>
                    <div className="mt-1 text-slate-900">
                      {displayClassificationList(representativeCaseSet.missingClassifications)}
                    </div>
                  </div>
                </div>
                {representativeCaseSet.remediation?.nextActions?.length ? (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {representativeCaseSet.remediation.nextActions.slice(0, 3).map((action) => (
                      <Badge key={action} status={representativeCaseSet.status === 'READY' ? 'PASS' : 'WARN'}>
                        {displayGovernanceCode(action)}
                      </Badge>
                    ))}
                  </div>
                ) : null}
              </div>
            ) : null}
            {parameterVersionReview ? (
              <div
                data-testid="technical-kline-parameter-version-review"
                className="mt-3 rounded-md border border-slate-200 bg-slate-50 p-3"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <Badge status={impactBadgeStatus(parameterVersionReview.status)}>
                    {displayGovernanceCode(parameterVersionReview.status)}
                  </Badge>
                  <span className="font-semibold text-slate-800">参数版本复核</span>
                  <span>{displayGovernanceCode(parameterVersionReview.boundary)}</span>
                </div>
                <div className="mt-3 grid gap-3 md:grid-cols-3">
                  <div>
                    <div className="text-slate-500">当前配置已复核案例</div>
                    <div className="mt-1 font-semibold text-slate-900">
                      {parameterVersionReview.currentConfigCaseCount}
                    </div>
                  </div>
                  <div>
                    <div className="text-slate-500">基线配置数</div>
                    <div className="mt-1 font-semibold text-slate-900">
                      {parameterVersionReview.baselineConfigCount}
                    </div>
                  </div>
                  <div>
                    <div className="text-slate-500">动作</div>
                    <div className="mt-1 text-slate-900">{displayGovernanceCode(parameterVersionReview.action)}</div>
                  </div>
                </div>
                {parameterVersionReview.comparison ? (
                  <div
                    data-testid="technical-kline-parameter-version-delta"
                    className="mt-3 grid gap-3 md:grid-cols-4"
                  >
                    <div>
                      <div className="text-slate-500">基线</div>
                      <div className="mt-1 break-all font-mono text-slate-900">
                        {parameterVersionReview.comparison.baselineConfigHash}
                      </div>
                    </div>
                    <div>
                      <div className="text-slate-500">有效率变化</div>
                      <div className="mt-1 font-semibold text-slate-900">
                        {formatDelta(parameterVersionReview.comparison.validRateDelta)}
                      </div>
                    </div>
                    <div>
                      <div className="text-slate-500">误判率变化</div>
                      <div className="mt-1 font-semibold text-slate-900">
                        {formatDelta(parameterVersionReview.comparison.misjudgeRateDelta)}
                      </div>
                    </div>
                    <div>
                      <div className="text-slate-500">数据不足率变化</div>
                      <div className="mt-1 font-semibold text-slate-900">
                        {formatDelta(parameterVersionReview.comparison.insufficientDataRateDelta)}
                      </div>
                    </div>
                  </div>
                ) : null}
              </div>
            ) : null}
            {longWindowRegression ? (
              <div
                data-testid="technical-kline-long-window-regression"
                className="mt-3 rounded-md border border-slate-200 bg-slate-50 p-3"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <Badge status={impactBadgeStatus(longWindowRegression.status)}>
                    {displayGovernanceCode(longWindowRegression.status)}
                  </Badge>
                  <span className="font-semibold text-slate-800">长窗口回归留存</span>
                  <span>{displayGovernanceCode(longWindowRegression.boundary)}</span>
                  <span>{displayGovernanceCode(longWindowRegression.tradeActionPolicy)}</span>
                </div>
                <div className="mt-3 grid gap-3 md:grid-cols-4">
                  <div>
                    <div className="text-slate-500">留存已复核案例</div>
                    <div className="mt-1 font-semibold text-slate-900">
                      {longWindowRegression.reviewedCaseCount} / {longWindowRegression.minimumReviewedCases}
                    </div>
                    <div className="mt-1 text-slate-500">留存上限 {longWindowRegression.retainedCaseLimit}</div>
                  </div>
                  <div>
                    <div className="text-slate-500">配置版本数</div>
                    <div className="mt-1 font-semibold text-slate-900">
                      {longWindowRegression.configVersionCount} / {longWindowRegression.minimumConfigVersions}
                    </div>
                    <div className="mt-1 text-slate-500">基线 {longWindowRegression.baselineConfigCount}</div>
                  </div>
                  <div>
                    <div className="text-slate-500">标的数</div>
                    <div className="mt-1 font-semibold text-slate-900">
                      {longWindowRegression.uniqueSymbolCount} / {longWindowRegression.minimumSymbols}
                    </div>
                    <div className="mt-1 text-slate-500">
                      缺少分类 {longWindowRegression.missingClassifications.length ? displayClassificationList(longWindowRegression.missingClassifications) : '无'}
                    </div>
                  </div>
                  <div>
                    <div className="text-slate-500">动作</div>
                    <div className="mt-1 text-slate-900">{displayGovernanceCode(longWindowRegression.action)}</div>
                    <div className="mt-1 text-slate-500">{displayGovernanceCode(longWindowRegression.dataPolicy)}</div>
                  </div>
                </div>
                <div className="mt-3 grid gap-2 md:grid-cols-3">
                  {longWindowRegression.windows.slice(0, 3).map((window) => (
                    <div key={window.label} className="rounded-md border border-slate-200 bg-white p-2">
                      <div className="text-[11px] text-slate-500">{displayGovernanceCode(window.label)}</div>
                      <div className="mt-1 font-semibold text-slate-900">{window.caseCount} 条案例</div>
                      <div className="mt-1 break-all text-slate-500">{displayGovernanceCode(window.scope)}</div>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        ) : null}

        {message ? (
          <div
            data-testid="technical-kline-case-message"
            className="rounded-md border border-slate-200 bg-slate-50 p-3 text-xs text-slate-700"
          >
            {message}
          </div>
        ) : null}
      </div>
    </Card>
  )
}
