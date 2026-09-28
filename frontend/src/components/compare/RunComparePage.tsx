import { useEffect, useMemo, useState } from 'react'
import { Activity, AlertTriangle, Clock, GitBranch, ShieldCheck } from 'lucide-react'
import { compareAnalysisRuns, getAnalysisRuns, RunCompareResult } from '../../api/analysisClient'
import { AnalysisRunSummary } from '../../types'
import { Badge } from '../common/Badge'
import { Card } from '../common/Card'
import { MetricTile, TableShell } from '../common/Material'
import { SectionTitle } from '../common/SectionTitle'
import { formatDateTime } from '../../utils/format'

const DIFF_LABEL_TEXT: Record<string, string> = {
  final: '最终动作',
  final_mode: '最终输出模式',
  final_audit: '最终输出审计 ID',
  final_sections: '最终输出章节',
  dvg: 'DVG 数据可靠性',
  dvg_cap: 'DVG 决策上限',
  dvg_missing: 'DVG 缺失数据',
  qiam_up: 'QIAM 上行概率',
  qiam_final: 'QIAM 最终适宜性',
  portfolio: '组合覆盖',
  portfolio_add: '组合加仓许可',
  execution: '执行可达性',
  execution_actions: '执行允许动作',
  signal_status: 'SignalOps 状态',
  signal_blocked: 'SignalOps 阻断原因',
  signal_triggers: 'SignalOps 触发条件',
  signal_invalidations: 'SignalOps 失效条件',
  data_mode: '数据模式',
  source_summary: '数据源摘要',
  source_fallback: '数据源降级错误',
  agent_statuses: 'Agent 状态',
}

const IMPACT_TEXT: Record<string, string> = {
  'No change.': '无变化。',
  'Field value changed.': '字段值发生变化。',
  'Final Writer output changed; review section text and audit attribution before reusing the conclusion.': '最终输出发生变化；复用结论前请检查章节文本和审计归因。',
  'DVG gate result changed; conclusion confidence or output permission may differ.': '数据验证结果发生变化；结论可信度或输出权限可能不同。',
  'QIAM suitability changed; probability band or discount factors may affect the final action.': '量化适宜性发生变化；概率分布或折扣因子可能影响最终动作。',
  'Portfolio source or constraints changed; real holdings may alter position caps and execution limits.': '组合来源或约束发生变化；真实持仓可能改变仓位上限和执行限制。',
  'Execution reachability changed; this is not buy permission, but it changes the allowed execution path.': '执行可达性发生变化；这不是买入许可，但会影响允许的执行路径。',
  'SignalOps lifecycle changed; watch/paper-test/qualified status should be reviewed.': 'SignalOps 生命周期发生变化；观察、模拟验证或合格状态需要复核。',
  'Data source coverage changed; inspect adapter-level reasons in the data source health page.': '数据源覆盖发生变化；请到数据源健康页面查看适配器层原因。',
  'One or more agent statuses changed; inspect DAG and audit details before comparing conclusions.': '一个或多个 Agent 状态发生变化；比较结论前请复核 DAG 和审计详情。',
  'No key differences detected between the two runs.': '两次运行未检测到关键差异。',
}

const VALUE_TEXT: Record<string, string> = {
  WAIT: '等待',
  PAPER_TEST_ONLY: '仅模拟验证',
  BUY: '买入',
  SELL: '卖出',
  HOLD: '持有',
  NORMAL: '正常',
  REVIEW_ONLY: '仅复核',
  LIVE: '实时数据',
  FALLBACK: '降级数据',
  PASS: '通过',
  WARN: '警告',
  FAIL: '失败',
  WATCH: '观察',
  PAPER_TEST: '模拟验证',
  QUALIFIED: '合格',
  REACHABLE: '可达',
  BLOCKED: '已阻断',
}

function translateText(value: string) {
  return IMPACT_TEXT[value] ?? VALUE_TEXT[value] ?? value
}

function diffTone(changed: boolean) {
  return changed ? 'border-l-[#fbbc04] bg-[#fff8e1]' : 'border-l-[#34a853] bg-white'
}

function impactStatus(changed: boolean) {
  return changed ? 'WARN' : 'PASS'
}

function renderValue(value: unknown) {
  if (Array.isArray(value)) return value.length ? value.map((item) => translateText(String(item))).join(', ') : '-'
  if (typeof value === 'number') return Math.abs(value) <= 1 ? `${(value * 100).toFixed(1)}%` : value.toLocaleString()
  if (value === null || value === undefined || value === '') return '-'
  if (typeof value === 'object') return JSON.stringify(value)
  return translateText(String(value))
}

function buildRunCompareGovernance(result: RunCompareResult) {
  const changedDiffs = result.diffs.filter((item) => item.changed)
  const incompleteStatus = [result.leftRun, result.rightRun].find((run) => !['COMPLETED', 'FAILED', 'STALE', 'CANCELLED'].includes(run.status))
  const firstChange = changedDiffs[0]
  const blocker = incompleteStatus
    ? `运行 ${incompleteStatus.runId} 仍处于 ${incompleteStatus.status}，比较结果不能作为闭环结论`
    : firstChange
      ? `${DIFF_LABEL_TEXT[firstChange.key] ?? firstChange.label}：${translateText(firstChange.impact)}`
      : '无关键差异；仍需按审计链路复核原始 run'
  const nextAction = firstChange
    ? '打开差异模块和 Audit Log，核对原始事件后再更新 Case / Knowledge'
    : '保留对比记录，继续验证回测与研究闭环一致性'
  return {
    contextId: `${result.leftRun.runId} -> ${result.rightRun.runId}`,
    evidenceStrength: 'LOW',
    blocker,
    nextAction,
    simulationOnly: true,
    isRealTrade: false,
    evidenceUsage: 'simulation_only',
    strongConclusionAllowed: false,
  }
}

export function RunComparePage() {
  const [runs, setRuns] = useState<AnalysisRunSummary[]>([])
  const [left, setLeft] = useState('')
  const [right, setRight] = useState('')
  const [result, setResult] = useState<RunCompareResult | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    getAnalysisRuns()
      .then((items) => {
        setRuns(items)
        setLeft(items[1]?.runId || items[0]?.runId || '')
        setRight(items[0]?.runId || '')
      })
      .catch((err) => setError(err instanceof Error ? err.message : '加载运行历史失败'))
  }, [])

  const options = useMemo(() => runs.map((run) => ({
    value: run.runId,
    label: `${run.stockCode} · ${run.finalAction} · ${formatDateTime(run.updatedAt || run.createdAt)}`,
  })), [runs])
  const changedDiffs = result?.diffs.filter((item) => item.changed) ?? []
  const unchangedCount = result ? Math.max(0, result.diffs.length - result.changedCount) : 0
  const runCompareGovernance = result ? buildRunCompareGovernance(result) : null

  async function handleCompare() {
    if (!left || !right || left === right) {
      setError('请选择两个不同的运行记录')
      return
    }
    setLoading(true)
    setError('')
    try {
      setResult(await compareAnalysisRuns(left, right))
    } catch (err) {
      setError(err instanceof Error ? err.message : '运行对比失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-5 text-slate-900">
      <SectionTitle title="运行对比" subtitle="对比两次运行的结论、数据源、DVG、QIAM、组合和执行差异，定位结论变化原因。" />

      <Card title="选择运行">
        <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
          <SelectRun label="左侧运行" value={left} onChange={setLeft} options={options} />
          <SelectRun label="右侧运行" value={right} onChange={setRight} options={options} />
          <button
            type="button"
            onClick={handleCompare}
            disabled={loading}
            className="mt-7 inline-flex h-10 items-center justify-center gap-2 rounded-md bg-[#0b57d0] px-4 text-sm font-semibold text-white transition hover:bg-[#0842a0] disabled:opacity-60"
          >
            <GitBranch size={16} />
            对比
          </button>
        </div>
        {error && <div className="mt-4 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</div>}
      </Card>

      {result && (
        <>
          <div className="grid gap-3 md:grid-cols-4">
            <MetricTile
              label="变化项"
              value={`${result.changedCount}/${result.diffs.length}`}
              helper={`未变 ${unchangedCount} 项 · ${formatDateTime(result.generatedAt)}`}
              icon={Activity}
              tone={result.changedCount > 0 ? 'warning' : 'success'}
            />
            <MetricTile
              label="最终动作"
              value={`${result.leftRun.finalAction} → ${result.rightRun.finalAction}`}
              helper="对比最终输出前先看审计归因和数据源差异。"
              icon={GitBranch}
              tone={result.leftRun.finalAction === result.rightRun.finalAction ? 'success' : 'warning'}
            />
            <MetricTile
              label="运行模式"
              value={`${result.leftRun.runMode} / ${result.rightRun.runMode}`}
              helper={`${result.leftRun.status} → ${result.rightRun.status}`}
              icon={ShieldCheck}
              tone="info"
            />
            <MetricTile
              label="重点复核"
              value={changedDiffs[0] ? (DIFF_LABEL_TEXT[changedDiffs[0].key] ?? changedDiffs[0].label) : '无关键差异'}
              helper={changedDiffs[0] ? translateText(changedDiffs[0].impact) : 'No key differences detected between the two runs.'}
              icon={AlertTriangle}
              tone={changedDiffs.length ? 'warning' : 'success'}
            />
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <RunCard title="左侧" run={result.leftRun} />
            <RunCard title="右侧" run={result.rightRun} />
          </div>

          {runCompareGovernance && (
            <Card title="对比治理">
              <div data-testid="run-compare-governance" className="grid gap-3 text-sm md:grid-cols-2 xl:grid-cols-5">
                <div className="rounded-md border border-slate-200 bg-[#f8fafd] px-3 py-2">
                  <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Context ID</div>
                  <div data-testid="run-compare-governance-id" className="mt-1 break-all font-mono text-xs text-slate-700">{runCompareGovernance.contextId}</div>
                </div>
                <div className="rounded-md border border-slate-200 bg-[#f8fafd] px-3 py-2">
                  <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">证据强度</div>
                  <div data-testid="run-compare-evidence-strength" className="mt-1 font-semibold text-amber-700">{runCompareGovernance.evidenceStrength}</div>
                </div>
                <div className="rounded-md border border-slate-200 bg-[#f8fafd] px-3 py-2">
                  <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">阻塞原因</div>
                  <div data-testid="run-compare-blocker" className="mt-1 leading-5 text-slate-700">{runCompareGovernance.blocker}</div>
                </div>
                <div className="rounded-md border border-slate-200 bg-[#f8fafd] px-3 py-2">
                  <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">下一步</div>
                  <div data-testid="run-compare-next-action" className="mt-1 leading-5 text-slate-700">{runCompareGovernance.nextAction}</div>
                </div>
                <div className="rounded-md border border-slate-200 bg-[#f8fafd] px-3 py-2">
                  <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">边界</div>
                  <div data-testid="run-compare-simulation-boundary" className="mt-1 font-mono text-xs text-slate-700">
                    simulation_only={String(runCompareGovernance.simulationOnly)} / is_real_trade={String(runCompareGovernance.isRealTrade)} / evidence_usage={runCompareGovernance.evidenceUsage} / strong_conclusion_allowed={String(runCompareGovernance.strongConclusionAllowed)} / SIM_*
                  </div>
                </div>
              </div>
            </Card>
          )}

          <Card title="变化摘要">
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <Badge status={result.changedCount > 0 ? 'WARN' : 'PASS'}>{result.changedCount} 项变化</Badge>
              <span className="text-xs text-slate-500">生成时间 {formatDateTime(result.generatedAt)}</span>
            </div>
            <div className="grid gap-2 text-sm text-slate-700 lg:grid-cols-2">
              {result.summary.map((item, index) => (
                <div key={index} className="rounded-md border border-slate-200 bg-[#f8fafd] px-3 py-2 leading-6">
                  {translateText(item)}
                </div>
              ))}
            </div>
          </Card>

          <Card title="模块级差异">
            <TableShell>
              <table className="institution-table">
                <thead className="border-b border-slate-200 bg-[#f8fafd] text-[11px] uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className="px-3 py-2">模块</th>
                    <th className="px-3 py-2">左侧</th>
                    <th className="px-3 py-2">右侧</th>
                    <th className="px-3 py-2">影响</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {result.diffs.map((item) => (
                    <tr key={item.key} className={`border-l-4 align-top ${diffTone(item.changed)}`}>
                      <td className="px-3 py-2.5 font-semibold text-slate-950">
                        <div>{DIFF_LABEL_TEXT[item.key] ?? item.label}</div>
                        <Badge status={impactStatus(item.changed)} className="mt-1 !px-2 !py-0.5 !text-[10px]">{item.changed ? 'CHANGED' : 'UNCHANGED'}</Badge>
                      </td>
                      <td className="max-w-[280px] px-3 py-2.5 text-slate-700">{renderValue(item.left)}</td>
                      <td className="max-w-[280px] px-3 py-2.5 text-slate-700">{renderValue(item.right)}</td>
                      <td className="px-3 py-2.5 leading-5 text-slate-600">{translateText(item.impact)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableShell>
          </Card>
        </>
      )}
    </div>
  )
}

function SelectRun({ label, value, onChange, options }: { label: string; value: string; onChange: (value: string) => void; options: Array<{ value: string; label: string }> }) {
  return (
    <label className="space-y-2 text-sm">
      <span className="font-medium text-slate-700">{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)} className="w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-slate-900 outline-none transition focus:border-[#1a73e8] focus:ring-2 focus:ring-[#1a73e8]/15">
        <option value="">请选择运行</option>
        {options.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
      </select>
    </label>
  )
}

function RunCard({ title, run }: { title: string; run: AnalysisRunSummary }) {
  return (
    <Card title={title}>
      <div className="space-y-3 text-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="font-semibold text-slate-950">{run.stockCode} {run.stockName}</div>
            <div className="mt-1 flex items-center gap-1.5 text-xs text-slate-500">
              <Clock size={13} />
              {formatDateTime(run.updatedAt || run.createdAt)}
            </div>
          </div>
          <Badge status={run.finalAction}>{run.finalAction}</Badge>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge status={run.runMode}>{run.runMode}</Badge>
          <Badge status={run.status}>{run.status}</Badge>
        </div>
        <div className="break-all rounded-md border border-slate-200 bg-[#f8fafd] px-3 py-2 font-mono text-xs text-slate-500">{run.runId}</div>
      </div>
    </Card>
  )
}
