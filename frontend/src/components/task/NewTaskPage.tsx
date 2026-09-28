import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  Activity,
  AlertTriangle,
  Check,
  CheckCircle2,
  ClipboardCheck,
  GitBranch,
  Hash,
  Info,
  Loader2,
  Percent,
  Play,
  RefreshCw,
  Rocket,
  ShieldAlert,
  Target,
  X,
  type LucideIcon,
} from 'lucide-react'
import { getAgentRuntime } from '../../api/agentRuntimeClient'
import { Badge } from '../common/Badge'
import { StatusPill } from '../common/Material'
import { createAnalysisRun, getAnalysisRun, startAnalysisRun } from '../../api/analysisClient'
import { getPortfolioSnapshot, listPortfolioSnapshots, PortfolioSnapshot, PortfolioSnapshotSummary } from '../../api/portfolioClient'
import { useAnalysisStore } from '../../store/useAnalysisStore'
import { roleAllows, useOperatorContext } from '../../store/operatorContext'
import { AgentLLMProfile, QuantEngineMode, RuntimeProfileHealthStatus, RunMode } from '../../types'
import { formatDateTime } from '../../utils/format'
import { scenarioTemplates } from '../../utils/scenarioTemplates'

type ToneKey = 'PASS' | 'WARN' | 'FAIL' | 'INFO'

const toneStyles: Record<ToneKey, { text: string; bg: string; border: string; Icon: LucideIcon }> = {
  PASS: { text: 'text-[#086247]', bg: 'bg-[#e4f6ef]', border: 'border-[#bfe0cf]', Icon: Check },
  WARN: { text: 'text-[#7a5206]', bg: 'bg-[#fff4dc]', border: 'border-[#f0dcab]', Icon: AlertTriangle },
  FAIL: { text: 'text-[#b42318]', bg: 'bg-[#fdecec]', border: 'border-[#f6cccc]', Icon: X },
  INFO: { text: 'text-[#153f9f]', bg: 'bg-[#eaf1ff]', border: 'border-[#c7d7fe]', Icon: Info },
}

const FIELD =
  'h-[42px] w-full rounded-lg border border-[#d7dee8] bg-white px-3 text-sm text-[#102033] outline-none transition focus:border-[#1d5eff] focus:ring-2 focus:ring-[#1d5eff]/15'
const SELECT_FIELD = `${FIELD} appearance-none bg-[url('data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%2216%22 height=%2216%22 viewBox=%220 0 24 24%22 fill=%22none%22 stroke=%22%23607086%22 stroke-width=%222%22><path d=%22M6 9l6 6 6-6%22/></svg>')] bg-[length:16px] bg-[right_11px_center] bg-no-repeat pr-9`

const taskTypes = ['持仓复核', '交易机会发现', '风险排查', 'MFE/MAE路径研究']

const taskTypeMeta: Record<string, { desc: string; Icon: LucideIcon }> = {
  '持仓复核': { desc: '复核已有仓位风险', Icon: ClipboardCheck },
  '交易机会发现': { desc: '筛选研究候选', Icon: Target },
  '风险排查': { desc: '排查个股风险', Icon: ShieldAlert },
  'MFE/MAE路径研究': { desc: '回撤 / 修复路径研究', Icon: Activity },
}

const runModes: { value: RunMode; short: string; desc: string }[] = [
  { value: 'FAST_MODE', short: 'FAST', desc: '精简 · 5 节点' },
  { value: 'STANDARD_MODE', short: 'STANDARD', desc: '标准 · 8 节点' },
  { value: 'DEEP_MODE', short: 'DEEP', desc: '深度 · 12 节点' },
]

// Representative agent chain that runs for each mode, surfaced as a preflight preview.
const dagSets: Record<RunMode, string[]> = {
  FAST_MODE: ['Orchestrator', '数据可靠性', 'Guardrail', '量化核心', 'Final Writer'],
  STANDARD_MODE: ['Orchestrator', '数据可靠性', 'Guardrail', '量化核心', 'Execution', 'Anti-Concl', 'SignalOps', 'Final Writer'],
  DEEP_MODE: ['Orchestrator', '数据可靠性', 'Guardrail', '市场技术', '市场态势', '量化核心', 'MFE/MAE', '情景引擎', 'Execution', 'Anti-Concl', 'SignalOps', 'Final Writer'],
}

type PortfolioPreflightLevel = 'LOW' | 'MEDIUM' | 'HIGH'

const portfolioRiskLevelLabels: Record<PortfolioPreflightLevel, string> = {
  LOW: '低',
  MEDIUM: '中',
  HIGH: '高',
}

const portfolioDisplayLabels: Record<string, string> = {
  'Manual entry': '手动录入',
  'SignalOps simulation snapshot': 'SignalOps 模拟快照',
  'Eastmoney broker export': '东方财富券商导出',
  'Huatai Securities export': '华泰证券导出',
  'Futu/Moomoo broker export': '富途 / Moomoo 券商导出',
  'Tiger broker export': '老虎证券导出',
  'Generic broker holdings export': '通用券商持仓导出',
  'Generic holdings table': '通用持仓表',
  'SIGNALOPS_SIMULATION': 'SignalOps 模拟持仓',
  'P2 closed-loop sample holdings': 'P2 闭环样例持仓',
}

interface PortfolioPreflight {
  level: PortfolioPreflightLevel
  status: 'PASS' | 'WARN' | 'FAIL'
  notes: string[]
  matchedSymbol: string
  matchedWeight: number | null
  topIndustry: PortfolioExposure | null
  topTheme: PortfolioExposure | null
  topRiskFactor: PortfolioExposure | null
}

interface PortfolioExposure {
  label: string
  weight: number
}

interface AnalysisRunPreflightGovernance {
  contextId: string
  evidenceStrength: string
  blocker: string
  nextAction: string
  evidenceUsage: 'simulation_only'
  strongConclusionAllowed: false
}

function defaultQuantEngineMode(taskType: string): QuantEngineMode {
  if (taskType.includes('MFE/MAE')) return 'LOW_FREQ_MID_LONG'
  return taskType.includes('交易机会') ? 'HIGH_FREQ_SHORT' : 'LOW_FREQ_MID_LONG'
}

export function NewTaskPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const operator = useOperatorContext()
  const canCreateAnalysisTask = roleAllows(operator.role, 'researcher')
  const newTaskRunDisabledReason = canCreateAnalysisTask
    ? ''
    : `新建任务运行创建需要 researcher 权限。当前角色：${operator.role}。`
  const portfolioPreflightBoundaryText = 'preflight_only=true / simulation_only=true / is_real_trade=false / evidence_usage=portfolio_context_only / strong_conclusion_allowed=false / SIM_*'
  const { selectedScenarioId, setScenario, setRun, loadRunHistory } = useAnalysisStore()
  const researchLoopId = searchParams.get('research_loop_id') || ''
  const researchIterationId = searchParams.get('research_iteration_id') || ''
  const initialSnapshotId = searchParams.get('portfolio_snapshot_id') || ''
  const [symbol, setSymbol] = useState('')
  const [taskType, setTaskType] = useState(taskTypes[0])
  const [runMode, setRunMode] = useState<RunMode>('STANDARD_MODE')
  const [quantEngineMode, setQuantEngineMode] = useState<QuantEngineMode>(() => defaultQuantEngineMode(taskTypes[0]))
  const [positionMode, setPositionMode] = useState<'ratio' | 'shares'>('ratio')
  const [positionRatio, setPositionRatio] = useState(12)
  const [shares, setShares] = useState(1000)
  const [costPrice, setCostPrice] = useState(18.5)
  const [maxDrawdown, setMaxDrawdown] = useState(8)
  const [allowAdd, setAllowAdd] = useState(true)
  const [allowT0, setAllowT0] = useState(false)
  const [snapshots, setSnapshots] = useState<PortfolioSnapshotSummary[]>([])
  const [selectedSnapshotId, setSelectedSnapshotId] = useState(initialSnapshotId)
  const [selectedSnapshotDetail, setSelectedSnapshotDetail] = useState<PortfolioSnapshot | null>(null)
  const [snapshotLoadError, setSnapshotLoadError] = useState('')
  const [defaultLlmProfileId, setDefaultLlmProfileId] = useState('')
  const [defaultLlmProfile, setDefaultLlmProfile] = useState<AgentLLMProfile | null>(null)
  const [llmStatusLoading, setLlmStatusLoading] = useState(false)
  const [llmStatusError, setLlmStatusError] = useState('')
  const [loading, setLoading] = useState(false)
  const [progress, setProgress] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const loadDefaultLlmProfile = useCallback(async () => {
    setLlmStatusLoading(true)
    try {
      const runtime = await getAgentRuntime()
      const profileId = runtime.default_llm_profile_id || runtime.llm_profiles[0]?.id || ''
      const profile = runtime.llm_profiles.find((item) => item.id === profileId) ?? null
      setDefaultLlmProfileId(profileId)
      setDefaultLlmProfile(profile)
      setLlmStatusError(profileId && !profile ? `未找到默认 LLM 配置档：${profileId}` : '')
    } catch (err) {
      setDefaultLlmProfileId('')
      setDefaultLlmProfile(null)
      setLlmStatusError(err instanceof Error ? err.message : '加载默认 LLM 配置档失败')
    } finally {
      setLlmStatusLoading(false)
    }
  }, [])

  useEffect(() => {
    listPortfolioSnapshots()
      .then((items) => {
        setSnapshots(items)
        setSnapshotLoadError('')
        setSelectedSnapshotId((current) => {
          if (current && items.some((item) => item.snapshotId === current)) return current
          return current || items[0]?.snapshotId || ''
        })
      })
      .catch((err) => {
        setSnapshotLoadError(err instanceof Error ? err.message : '加载组合快照失败')
      })
  }, [])

  useEffect(() => {
    if (!selectedSnapshotId) {
      setSelectedSnapshotDetail(null)
      return
    }

    let cancelled = false
    getPortfolioSnapshot(selectedSnapshotId)
      .then((snapshot) => {
        if (cancelled) return
        setSelectedSnapshotDetail(snapshot)
        setSnapshotLoadError('')
        const firstSymbol = snapshot.positions[0]?.symbol?.trim() || ''
        if (firstSymbol) {
          setSymbol((current) => current.trim() ? current : firstSymbol)
        }
      })
      .catch((err) => {
        if (cancelled) return
        setSelectedSnapshotDetail(null)
        setSnapshotLoadError(err instanceof Error ? err.message : '加载组合快照详情失败')
      })

    return () => {
      cancelled = true
    }
  }, [selectedSnapshotId])

  useEffect(() => {
    void loadDefaultLlmProfile()
  }, [loadDefaultLlmProfile])

  useEffect(() => {
    setQuantEngineMode(defaultQuantEngineMode(taskType))
    if (taskType.includes('MFE/MAE')) {
      setRunMode('STANDARD_MODE')
    }
  }, [taskType])

  const selectedSnapshot = useMemo(
    () => snapshots.find((item) => item.snapshotId === selectedSnapshotId),
    [selectedSnapshotId, snapshots],
  )
  const usesPortfolioContext = Boolean(selectedSnapshotId && selectedSnapshot)
  const portfolioPreflight = useMemo(
    () => buildPortfolioPreflight(selectedSnapshotDetail, selectedSnapshot, symbol),
    [selectedSnapshotDetail, selectedSnapshot, symbol],
  )
  const llmHealthStatus = useMemo(() => getLlmHealthStatus(defaultLlmProfile), [defaultLlmProfile])
  const llmReady = llmHealthStatus === 'READY'
  const cleanSymbol = symbol.trim() || selectedSnapshotDetail?.positions[0]?.symbol?.trim() || ''
  const runPreflightGovernance = useMemo(
    () => buildAnalysisRunPreflightGovernance({
      canCreate: canCreateAnalysisTask,
      disabledReason: newTaskRunDisabledReason,
      cleanSymbol,
      scenarioId: selectedScenarioId,
      runMode,
      usesPortfolioContext,
      selectedSnapshotId,
      selectedSnapshot,
      selectedSnapshotDetail,
      snapshotLoadError,
      portfolioPreflight,
      llmHealthStatus,
      researchIterationId,
    }),
    [
      canCreateAnalysisTask,
      cleanSymbol,
      llmHealthStatus,
      newTaskRunDisabledReason,
      portfolioPreflight,
      researchIterationId,
      runMode,
      selectedScenarioId,
      selectedSnapshot,
      selectedSnapshotDetail,
      selectedSnapshotId,
      snapshotLoadError,
      usesPortfolioContext,
    ],
  )

  async function handleSubmit() {
    if (!canCreateAnalysisTask) {
      setError(newTaskRunDisabledReason)
      setProgress(null)
      return
    }
    const portfolioDefaultSymbol = selectedSnapshotDetail?.positions[0]?.symbol?.trim() || ''
    const submitSymbol = symbol.trim() || portfolioDefaultSymbol
    if (!submitSymbol) {
      setError('请先填写股票代码。')
      return
    }

    if (!symbol.trim() && portfolioDefaultSymbol) {
      setSymbol(portfolioDefaultSymbol)
    }

    setLoading(true)
    setError(null)
    setProgress('正在创建后端任务...')
    let phase = '创建任务'
    let createdRunId = ''

    try {
      const userConstraints: Parameters<typeof createAnalysisRun>[0]['user_constraints'] = {
        position_ratio: positionMode === 'ratio' ? positionRatio / 100 : undefined,
        shares: positionMode === 'shares' ? shares : undefined,
        cost_price: costPrice,
        max_drawdown: maxDrawdown / 100,
        allow_add: allowAdd,
        allow_t0: allowT0,
      }
      const response = await createAnalysisRun({
        symbol: submitSymbol,
        task_type: taskType,
        run_mode: runMode,
        quant_engine_mode: quantEngineMode,
        bottom_research_config: taskType.includes('MFE/MAE') ? {
          lookback_range: '2y',
          horizon_days: 20,
          cov_window: 20,
          min_drawdown_pct: 0.12,
          downside_tolerance_pct: 0.05,
          recovery_return_pct: 0.08,
          repair_probability_threshold: 0.60,
          max_research_position_pct: 0.30,
        } : undefined,
        scenario_id: selectedScenarioId,
        user_constraints: userConstraints,
        config_profile_id: 'default',
        portfolio_snapshot_id: usesPortfolioContext ? selectedSnapshotId : undefined,
        research_loop_id: researchLoopId || undefined,
        research_iteration_id: researchIterationId || undefined,
      })
      createdRunId = response.run_id

      phase = '启动任务'
      setProgress('任务已创建，正在启动实时运行...')
      const startResponse = await retryTransientTaskStep(() => startAnalysisRun(response.run_id), () => {
        setProgress('后端连接短暂中断，正在重试启动任务...')
      })
      navigate(`/live-run?run_id=${encodeURIComponent(response.run_id)}`)

      phase = '读取初始结果'
      setProgress(startResponse.status === 'FAILED' ? '任务已被启动前门禁阻断，正在读取失败节点...' : '任务已启动，正在读取初始结果...')
      void retryTransientTaskStep(() => getAnalysisRun(response.run_id), () => undefined)
        .then(async (run) => {
          setRun(run)
          await loadRunHistory().catch(() => undefined)
        })
        .catch(() => {
          loadRunHistory().catch(() => undefined)
        })
    } catch (err) {
      const message = err instanceof Error ? err.message : '请检查后端服务。'
      const prefix = createdRunId && phase !== '创建任务' ? `任务已创建（${createdRunId}），但${phase}失败` : `${phase}失败`
      setError(`${prefix}：${message}`)
      setProgress(null)
    } finally {
      setLoading(false)
    }
  }

  // ---- Preflight (起飞前检查) derived from real form state ----
  const dagNodes = dagSets[runMode] ?? dagSets.STANDARD_MODE
  const quantModeLabel = quantEngineMode === 'HIGH_FREQ_SHORT' ? '高频短线' : '低频中长线'

  const checklist: { label: string; value: string; tone: ToneKey }[] = [
    {
      label: '股票代码',
      value: cleanSymbol || '未填写',
      tone: cleanSymbol ? 'PASS' : 'WARN',
    },
    {
      label: '任务 / 模式',
      value: `${taskType} · ${runMode.replace('_MODE', '')} · ${quantModeLabel}`,
      tone: 'INFO',
    },
    {
      label: 'LLM 配置档',
      value: `${defaultLlmProfile?.label || defaultLlmProfileId || '默认 LLM 配置档'} · ${llmHealthStatus}`,
      tone: llmChecklistTone(llmHealthStatus),
    },
    {
      label: '组合上下文',
      value: usesPortfolioContext
        ? `${formatPortfolioSourceName(selectedSnapshot?.sourceName || selectedSnapshot?.snapshotId)} · ${selectedSnapshot?.positionCount ?? 0} 只`
        : 'USER_INPUT_ONLY',
      tone: usesPortfolioContext ? 'PASS' : 'WARN',
    },
    {
      label: '组合风险',
      value: `组合风险 ${portfolioRiskLevelLabels[portfolioPreflight.level]}${portfolioPreflight.level === 'HIGH' ? ' · 需复核' : ''}`,
      tone: portfolioPreflight.status,
    },
    {
      label: '角色权限',
      value: `${operator.role}${canCreateAnalysisTask ? ' · 可创建' : ' · 已阻断'}`,
      tone: canCreateAnalysisTask ? 'PASS' : 'FAIL',
    },
  ]
  if (researchLoopId || researchIterationId) {
    checklist.push({
      label: '研究关联',
      value: [researchLoopId && `loop=${researchLoopId}`, researchIterationId && `iter=${researchIterationId}`]
        .filter(Boolean)
        .join(' · '),
      tone: 'INFO',
    })
  }

  const verdict: { tone: ToneKey; label: string; sub: string; bar: string; Icon: LucideIcon } = !canCreateAnalysisTask
    ? { tone: 'FAIL', label: '需要 researcher 权限', sub: newTaskRunDisabledReason, bar: '#dc2626', Icon: X }
    : !cleanSymbol
      ? { tone: 'WARN', label: '缺少股票代码', sub: '填写代码后可创建', bar: '#e0a912', Icon: AlertTriangle }
      : portfolioPreflight.level === 'HIGH'
        ? { tone: 'WARN', label: '可创建 · 风险待复核', sub: '组合风险高，建议先复核', bar: '#e0a912', Icon: AlertTriangle }
        : { tone: 'PASS', label: '可创建并启动', sub: '通过全部起飞前检查', bar: '#16a34a', Icon: Rocket }

  const evColor = runPreflightGovernance.evidenceStrength.startsWith('MEDIUM')
    ? 'text-[#086247]'
    : runPreflightGovernance.evidenceStrength.startsWith('LOW')
      ? 'text-[#7a5206]'
      : 'text-[#b42318]'
  const verdictTone = toneStyles[verdict.tone]

  return (
    <div className="flex flex-col gap-4">
      <section>
        <div className="text-xs font-bold tracking-[0.4px] text-[#1d5eff]">新建任务 · NEW ANALYSIS RUN</div>
        <h2 className="mt-1 text-[26px] font-bold leading-tight tracking-[-0.3px] text-[#102033]">装配一次分析运行</h2>
        <p className="mt-1.5 max-w-[680px] text-[13px] leading-relaxed text-[#607086]">
          创建一条后端编排的个股分析任务并进入实时运行台。右侧起飞前检查会随表单实时评估可创建性——不承诺收益，不触发真实下单。
        </p>
      </section>

      {researchLoopId || researchIterationId ? (
        <div className="flex items-start gap-2 rounded-lg border border-[#c7d7fe] bg-[#eaf1ff] px-4 py-3 text-xs leading-5 text-[#153f9f]">
          <Info size={15} className="mt-0.5 shrink-0" />
          <span>
            本次任务将关联研究实验室。
            {researchLoopId ? <span className="ml-2 font-semibold">loop={researchLoopId}</span> : null}
            {researchIterationId ? <span className="ml-2 font-semibold">iteration={researchIterationId}</span> : null}
            运行创建、完成或失败后会回写到对应研究轮次。
          </span>
        </div>
      ) : null}

      <div className="grid grid-cols-1 gap-4 min-[1140px]:grid-cols-[minmax(0,1fr)_384px] min-[1140px]:items-start">
        {/* ----- Left column: configuration card ----- */}
        <div className="min-w-0">
          <div className="overflow-hidden rounded-[10px] border border-[#d7dee8] bg-white shadow-[0_1px_2px_rgba(16,32,51,0.06),0_1px_3px_rgba(16,32,51,0.04)]">
            {/* 01 标的与任务 */}
            <div className="border-b border-[#eef2f6] px-[18px] py-4">
              <SectionHead step="01" title="标的与任务" />
              <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2">
                <label className="block">
                  <FieldLabel>股票代码</FieldLabel>
                  <input
                    data-testid="new-task-symbol"
                    value={symbol}
                    onChange={(event) => setSymbol(event.target.value)}
                    placeholder="例如 603663"
                    className={`${FIELD} font-mono font-semibold tracking-[0.5px]`}
                  />
                </label>
                <div>
                  <FieldLabel>提交标的预览</FieldLabel>
                  <div className="flex h-[42px] items-center rounded-lg border border-dashed border-[#d7dee8] bg-[#f8fafd] px-3 font-mono text-[13px] text-[#607086]">
                    {cleanSymbol || '输入代码或选择快照后预览'}
                  </div>
                </div>
              </div>
              <div className="mt-3.5">
                <FieldLabel>任务类型</FieldLabel>
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  {taskTypes.map((item) => {
                    const meta = taskTypeMeta[item]
                    const ItemIcon = meta?.Icon ?? ClipboardCheck
                    const active = taskType === item
                    return (
                      <button
                        key={item}
                        type="button"
                        onClick={() => setTaskType(item)}
                        className={`flex items-center gap-2.5 rounded-lg border px-3 py-2.5 text-left transition ${
                          active
                            ? 'border-[#1d5eff] bg-[#eaf1ff] text-[#153f9f] shadow-[0_1px_2px_rgba(29,94,255,0.14)]'
                            : 'border-[#e4e8f0] bg-white text-[#3c4759] hover:border-[#c7d2e0]'
                        }`}
                      >
                        <span
                          className={`grid h-[26px] w-[26px] shrink-0 place-items-center rounded-md ${
                            active ? 'bg-[#dbe7ff] text-[#153f9f]' : 'bg-[#eef2f6] text-[#607086]'
                          }`}
                        >
                          <ItemIcon size={14} />
                        </span>
                        <span className="min-w-0">
                          <span className="block text-[13px] font-semibold">{item}</span>
                          <span className="block truncate text-[10px] text-[#9aa6b4]">{meta?.desc}</span>
                        </span>
                      </button>
                    )
                  })}
                </div>
              </div>
            </div>

            {/* 02 运行编排 */}
            <div className="border-b border-[#eef2f6] px-[18px] py-4">
              <SectionHead step="02" title="运行编排" />
              <FieldLabel>运行模式</FieldLabel>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                {runModes.map((mode) => {
                  const active = runMode === mode.value
                  return (
                    <button
                      key={mode.value}
                      type="button"
                      onClick={() => setRunMode(mode.value)}
                      className={`flex flex-col items-start rounded-lg border px-3 py-2.5 transition ${
                        active
                          ? 'border-[#1d5eff] bg-[#eaf1ff] text-[#153f9f] shadow-[0_1px_2px_rgba(29,94,255,0.14)]'
                          : 'border-[#e4e8f0] bg-white text-[#3c4759] hover:border-[#c7d2e0]'
                      }`}
                    >
                      <span className="font-mono text-[13px] font-bold">{mode.short}</span>
                      <span className="mt-0.5 text-[10px] text-[#9aa6b4]">{mode.desc}</span>
                    </button>
                  )
                })}
              </div>
              <div className="mt-3.5 grid grid-cols-1 gap-3.5 sm:grid-cols-2">
                <div>
                  <FieldLabel>Quant Engine 模式</FieldLabel>
                  <div className="grid grid-cols-2 gap-2">
                    {([
                      { value: 'HIGH_FREQ_SHORT', label: '高频短线' },
                      { value: 'LOW_FREQ_MID_LONG', label: '低频中长线' },
                    ] as const).map((q) => {
                      const active = quantEngineMode === q.value
                      return (
                        <button
                          key={q.value}
                          type="button"
                          onClick={() => setQuantEngineMode(q.value)}
                          className={`h-[38px] rounded-lg border text-[12px] font-semibold transition ${
                            active
                              ? 'border-[#1d5eff] bg-[#eaf1ff] text-[#153f9f]'
                              : 'border-[#e4e8f0] bg-white text-[#3c4759] hover:border-[#c7d2e0]'
                          }`}
                        >
                          {q.label}
                        </button>
                      )
                    })}
                  </div>
                </div>
                <label className="block">
                  <FieldLabel>场景模板</FieldLabel>
                  <select
                    value={selectedScenarioId}
                    onChange={(event) => setScenario(event.target.value)}
                    className={SELECT_FIELD}
                  >
                    {scenarioTemplates.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.label}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <div className="mt-3 rounded-lg border border-[#e4e8f0] bg-[#f8fafd] px-3 py-2.5 text-[11px] leading-[1.55] text-[#607086]">
                {quantEngineMode === 'HIGH_FREQ_SHORT'
                  ? '短线模式会让 Level-2、盘口深度、分时/逐笔等高频缺失参与 QIAM 折扣。'
                  : '中长线模式把高频缺失标记为不适用，不压低 QIAM 分数。'}
              </div>
            </div>

            {/* 03 组合上下文 */}
            <div className="border-b border-[#eef2f6] px-[18px] py-4">
              <SectionHead step="03" title="组合上下文" />
              <label className="block">
                <FieldLabel>选择组合快照</FieldLabel>
                <select
                  value={selectedSnapshotId}
                  onChange={(event) => setSelectedSnapshotId(event.target.value)}
                  className={SELECT_FIELD}
                >
                  <option value="">不使用快照，仅使用手动仓位（USER_INPUT_ONLY）</option>
                  {snapshots.map((item) => (
                    <option key={item.snapshotId} value={item.snapshotId}>
                      {formatPortfolioSourceName(item.sourceName || item.snapshotId)} · {item.positionCount}只 · {formatPercent(item.totalPositionRatio)}
                    </option>
                  ))}
                </select>
                {snapshotLoadError ? <div className="mt-1 text-xs text-[#b42318]">{snapshotLoadError}</div> : null}
              </label>

              <div
                data-testid="new-task-portfolio-context"
                className={`mt-3 rounded-lg border px-3 py-2.5 ${
                  usesPortfolioContext ? 'border-[#bfe0cf] bg-[#e8f7f0] text-[#086247]' : 'border-[#f0dcab] bg-[#fdf6e3] text-[#7a5206]'
                }`}
              >
                <div className="flex items-center gap-1.5 text-xs font-bold">
                  {usesPortfolioContext ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}
                  {usesPortfolioContext ? '本次任务将使用组合上下文' : '本次任务不使用组合上下文'}
                </div>
                <div className="mt-1 text-[11px] leading-[1.55]">
                  {usesPortfolioContext
                    ? `${formatPortfolioSourceName(selectedSnapshot?.sourceName || selectedSnapshot?.snapshotId)} · ${selectedSnapshot?.positionCount ?? 0} 只 · 总资产 ${formatMoney(selectedSnapshot?.totalAssets ?? 0)} · 仓位 ${formatPercent(selectedSnapshot?.totalPositionRatio ?? 0)}`
                    : '提交时不会发送组合快照 ID（portfolio_snapshot_id），后端将按 USER_INPUT_ONLY 处理。'}
                </div>
              </div>

              {selectedSnapshot ? (
                <>
                  <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
                    <MiniMetric k="快照 ID" v={selectedSnapshot.snapshotId} />
                    <MiniMetric k="来源" v={formatPortfolioSourceName(selectedSnapshot.sourceName)} />
                    <MiniMetric k="现金" v={formatMoney(selectedSnapshot.cash)} />
                    <MiniMetric k="默认股票" v={selectedSnapshotDetail?.positions[0]?.symbol || '-'} />
                    <MiniMetric k="当前股票持仓" v={portfolioPreflight.matchedWeight == null ? '-' : formatPercent(portfolioPreflight.matchedWeight)} />
                    <MiniMetric k="导入模板" v={`${formatPortfolioTemplateName(selectedSnapshot.brokerTemplateLabel, selectedSnapshot.brokerTemplateId)} ${formatPercent(selectedSnapshot.templateConfidence)}`} />
                  </div>
                  <div
                    data-testid="new-task-portfolio-risk-preflight"
                    className={`mt-3 rounded-lg border px-3 py-2.5 ${portfolioRiskRailTone(portfolioPreflight.level)}`}
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge status={portfolioPreflight.status}>组合风险 {portfolioRiskLevelLabels[portfolioPreflight.level]}</Badge>
                      <span className="text-[13px] font-semibold text-[#102033]">任务前持仓风险提示</span>
                    </div>
                    <ul className="mt-2 list-disc space-y-1 pl-5 text-[11px] leading-5">
                      {portfolioPreflight.notes.map((note) => (
                        <li key={note}>{note}</li>
                      ))}
                    </ul>
                    <div className="mt-2.5 grid grid-cols-1 gap-2 sm:grid-cols-3">
                      <MiniMetric k="最大行业暴露" v={formatExposure(portfolioPreflight.topIndustry)} />
                      <MiniMetric k="最大主题暴露" v={formatExposure(portfolioPreflight.topTheme)} />
                      <MiniMetric k="最大风险因子" v={formatExposure(portfolioPreflight.topRiskFactor)} />
                    </div>
                    <div
                      data-testid="new-task-portfolio-risk-boundary"
                      className="mt-2.5 rounded-md border border-[#e4e8f0] bg-white/70 px-3 py-2 text-[11px] leading-5 text-[#607086]"
                    >
                      组合上下文仅作为任务前风险证据；{portfolioPreflightBoundaryText}
                    </div>
                  </div>
                </>
              ) : snapshots.length === 0 && !snapshotLoadError ? (
                <div className="mt-3 rounded-lg border border-dashed border-[#d7dee8] bg-[#f8fafd] px-3 py-2.5 text-[12px] text-[#607086]">
                  暂无快照。可先到“真实持仓”页面创建样例、手动快照或导入持仓文件。
                </div>
              ) : null}
            </div>

            {/* 04 持仓约束 */}
            <div className="border-b border-[#eef2f6] px-[18px] py-4">
              <div className="mb-3.5 flex items-center justify-between gap-2.5">
                <SectionHead step="04" title="持仓约束" inline />
                <div className="inline-flex items-center overflow-hidden rounded-lg border border-[#d7dee8] bg-[#f3f6fa]" role="tablist" aria-label="持仓表达方式">
                  {([
                    { value: 'ratio', label: '百分比', Icon: Percent },
                    { value: 'shares', label: '股数', Icon: Hash },
                  ] as const).map((mode) => {
                    const active = positionMode === mode.value
                    return (
                      <button
                        key={mode.value}
                        type="button"
                        role="tab"
                        aria-selected={active}
                        onClick={() => setPositionMode(mode.value)}
                        className={`inline-flex h-[30px] items-center gap-1.5 px-3 text-xs font-semibold transition ${
                          active ? 'bg-[#0b57d0] text-white' : 'bg-transparent text-[#607086] hover:bg-[#e9eef4]'
                        }`}
                      >
                        <mode.Icon size={13} />
                        {mode.label}
                      </button>
                    )
                  })}
                </div>
              </div>
              <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-3">
                <label className="block">
                  <FieldLabel>{positionMode === 'ratio' ? '当前仓位 %' : '持有股数'}</FieldLabel>
                  {positionMode === 'ratio' ? (
                    <input
                      type="number"
                      min={0}
                      max={100}
                      value={positionRatio}
                      onChange={(event) => setPositionRatio(Number(event.target.value))}
                      className={`${FIELD} font-mono`}
                    />
                  ) : (
                    <input
                      type="number"
                      min={0}
                      step={100}
                      value={shares}
                      onChange={(event) => setShares(Number(event.target.value))}
                      className={`${FIELD} font-mono`}
                    />
                  )}
                </label>
                <label className="block">
                  <FieldLabel>持仓成本</FieldLabel>
                  <input
                    type="number"
                    min={0}
                    step="0.01"
                    value={costPrice}
                    onChange={(event) => setCostPrice(Number(event.target.value))}
                    className={`${FIELD} font-mono`}
                  />
                </label>
                <label className="block">
                  <FieldLabel>最大可接受回撤 %</FieldLabel>
                  <input
                    type="number"
                    min={0}
                    max={100}
                    value={maxDrawdown}
                    onChange={(event) => setMaxDrawdown(Number(event.target.value))}
                    className={`${FIELD} font-mono`}
                  />
                </label>
              </div>
              <div className="mt-3.5 flex flex-wrap gap-2.5">
                <ToggleSwitch on={allowAdd} onClick={() => setAllowAdd((value) => !value)} label="允许加仓候选" />
                <ToggleSwitch on={allowT0} onClick={() => setAllowT0((value) => !value)} label="允许 T+0 观察" />
              </div>
            </div>

            {/* 05 默认 LLM 配置档 */}
            <div className="px-[18px] py-4">
              <div className="mb-3.5 flex items-center justify-between gap-2.5">
                <SectionHead step="05" title="默认 LLM 配置档" inline />
                <button
                  type="button"
                  title="刷新 LLM 状态"
                  onClick={loadDefaultLlmProfile}
                  disabled={llmStatusLoading}
                  className="inline-flex h-[30px] items-center gap-1.5 rounded-lg border border-[#d7dee8] px-3 text-xs font-medium text-[#3c4759] transition hover:bg-[#f3f6fa] disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <RefreshCw size={13} className={llmStatusLoading ? 'animate-spin' : undefined} />
                  刷新
                </button>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {llmReady ? <CheckCircle2 size={16} className="text-emerald-600" /> : <AlertTriangle size={16} className="text-amber-600" />}
                <StatusPill tone={llmStatusPillTone(llmHealthStatus)}>{llmHealthStatus}</StatusPill>
                <span className="break-all text-sm font-semibold text-[#102033]">
                  {defaultLlmProfile?.label || defaultLlmProfileId || '默认 LLM 配置档'}
                </span>
              </div>
              <div
                className={`mt-3 rounded-lg border px-3 py-2.5 text-[11px] leading-[1.55] ${
                  llmReady ? 'border-[#bfe0cf] bg-[#e8f7f0] text-[#086247]' : 'border-[#f0dcab] bg-[#fdf6e3] text-[#7a5206]'
                }`}
              >
                {llmStatusLoading && !defaultLlmProfile
                  ? '正在读取默认 LLM 配置档状态。'
                  : llmReadinessMessage(defaultLlmProfile, llmHealthStatus, llmStatusError)}
              </div>
              <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-4">
                <MiniMetric k="配置档 ID" v={defaultLlmProfile?.id || defaultLlmProfileId || '-'} />
                <MiniMetric k="服务商" v={defaultLlmProfile?.provider || '-'} />
                <MiniMetric k="模型" v={defaultLlmProfile?.model || '-'} />
                <MiniMetric k="最近实时调用" v={formatLlmLiveCallStatus(defaultLlmProfile)} />
                <MiniMetric k="上次调用时间" v={formatDateTime(defaultLlmProfile?.last_live_call_at)} />
                <MiniMetric k="上次检查时间" v={formatDateTime(defaultLlmProfile?.last_checked_at)} />
                <MiniMetric k="最近错误" v={defaultLlmProfile?.last_error || llmStatusError || '无'} />
                <MiniMetric k="语义" v={llmHealthMeaning(llmHealthStatus)} />
              </div>
            </div>
          </div>
        </div>

        {/* ----- Right column: PREFLIGHT rail ----- */}
        <aside className="flex min-w-0 flex-col gap-3.5 min-[1140px]:sticky min-[1140px]:top-6 min-[1140px]:self-start">
          <div className="overflow-hidden rounded-[10px] border border-[#d7dee8] bg-white shadow-[0_6px_22px_rgba(16,32,51,0.08),0_1px_3px_rgba(16,32,51,0.05)]">
            <div className="h-1" style={{ background: verdict.bar }} />

            {/* verdict */}
            <div className="border-b border-[#eef2f6] px-4 py-3.5">
              <div className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-[0.3px] text-[#7c8794]">
                <Rocket size={13} />
                起飞前检查 · PREFLIGHT
              </div>
              <div className="mt-2.5 flex items-center gap-2.5">
                <span className={`grid h-[34px] w-[34px] shrink-0 place-items-center rounded-[9px] ${verdictTone.bg} ${verdictTone.text}`}>
                  <verdict.Icon size={19} />
                </span>
                <div className="min-w-0">
                  <div className={`text-base font-bold leading-tight ${verdictTone.text}`}>{verdict.label}</div>
                  <div className="text-[11px] text-[#7c8794]">{verdict.sub}</div>
                </div>
              </div>
              <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-[#7c8794]">
                <span data-testid="new-task-run-role">角色：{operator.role}；创建运行：{canCreateAnalysisTask ? 'researcher+' : '已阻断'}</span>
                {!canCreateAnalysisTask ? (
                  <span data-testid="new-task-run-disabled-reason" className="text-[#7a5206]">{newTaskRunDisabledReason}</span>
                ) : null}
              </div>
            </div>

            {/* checklist */}
            <div className="border-b border-[#eef2f6] px-4 py-2.5">
              {checklist.map((item) => {
                const tone = toneStyles[item.tone]
                return (
                  <div key={item.label} className="flex items-start gap-2.5 py-1.5">
                    <span className={`mt-0.5 grid h-[18px] w-[18px] shrink-0 place-items-center rounded-[5px] ${tone.bg} ${tone.text}`}>
                      <tone.Icon size={11} />
                    </span>
                    <div className="flex min-w-0 flex-1 items-baseline justify-between gap-2">
                      <span className="shrink-0 text-xs font-medium text-[#3c4759]">{item.label}</span>
                      <span className={`truncate text-right text-[11px] font-semibold ${tone.text}`}>{item.value}</span>
                    </div>
                  </div>
                )
              })}
            </div>

            {/* mini DAG */}
            <div className="border-b border-[#eef2f6] px-4 py-3">
              <div className="mb-2.5 flex items-center justify-between gap-2">
                <span className="flex items-center gap-1.5 text-xs font-semibold text-[#102033]">
                  <GitBranch size={13} />
                  将运行的 Agent 链
                </span>
                <span className="font-mono text-[11px] text-[#7c8794]">
                  {dagNodes.length} 节点 · {runMode.replace('_MODE', '')}
                </span>
              </div>
              <div className="flex flex-wrap items-center gap-x-[3px] gap-y-1">
                {dagNodes.map((node, index) => (
                  <span key={node} className="flex items-center gap-x-[3px]">
                    <span className="inline-flex h-[22px] items-center gap-1 rounded-md border border-[#c9ece8] bg-[#e7f6f4] px-2 text-[11px] font-semibold text-[#0f766e]">
                      <span className="font-mono text-[#5aa39c]">{index + 1}</span>
                      {node}
                    </span>
                    {index < dagNodes.length - 1 ? <span className="text-[10px] text-[#b8c3d1]">›</span> : null}
                  </span>
                ))}
              </div>
            </div>

            {/* governance: evidence / blocker / next action / context id */}
            <div data-testid="new-task-run-governance" className="border-b border-[#eef2f6] px-4 py-3">
              <div className="grid grid-cols-2 gap-2.5">
                <div>
                  <div className="text-[10px] font-semibold text-[#7c8794]">证据强度</div>
                  <div data-testid="new-task-run-evidence-strength" className={`mt-0.5 text-xs font-semibold ${evColor}`}>
                    {runPreflightGovernance.evidenceStrength}
                  </div>
                </div>
                <div>
                  <div className="text-[10px] font-semibold text-[#7c8794]">阻塞</div>
                  <div data-testid="new-task-run-blocker" className="mt-0.5 text-xs font-semibold text-[#102033]">
                    {runPreflightGovernance.blocker}
                  </div>
                </div>
              </div>
              <div className="mt-2.5">
                <div className="text-[10px] font-semibold text-[#7c8794]">下一步</div>
                <div data-testid="new-task-run-next-action" className="mt-0.5 text-xs font-semibold text-[#0b57d0]">
                  {runPreflightGovernance.nextAction}
                </div>
              </div>
              <div className="mt-2.5 break-words rounded-md border border-[#e4e8f0] bg-[#f8fafd] px-2.5 py-2 font-mono text-[9px] leading-[1.65] text-[#9aa6b4]">
                上下文 ID：<span data-testid="new-task-run-context-id" className="break-all">{runPreflightGovernance.contextId}</span>
                <br />
                <span data-testid="new-task-run-simulation-boundary">
                  边界：simulation_only=true / is_real_trade=false / evidence_usage={runPreflightGovernance.evidenceUsage} / strong_conclusion_allowed={String(runPreflightGovernance.strongConclusionAllowed)} / SIM_*
                </span>
              </div>
            </div>

            {/* CTA */}
            <div className="px-4 py-3.5">
              {progress || error ? (
                <div
                  className={`mb-2.5 rounded-lg border px-3 py-2.5 text-xs leading-5 ${
                    error ? 'border-[#f6cccc] bg-[#fdecec] text-[#b42318]' : 'border-[#bfe0cf] bg-[#e4f6ef] text-[#086247]'
                  }`}
                >
                  {error ?? progress}
                </div>
              ) : null}
              <button
                type="button"
                data-testid="new-task-submit"
                onClick={handleSubmit}
                disabled={loading || !canCreateAnalysisTask}
                title={newTaskRunDisabledReason || undefined}
                className={`flex h-[46px] w-full items-center justify-center gap-2 rounded-[10px] text-sm font-bold transition ${
                  loading || !canCreateAnalysisTask
                    ? 'cursor-not-allowed bg-[#e4e8f0] text-[#9aa6b4]'
                    : 'bg-[#0b57d0] text-white shadow-[0_4px_14px_rgba(11,87,208,0.28)] hover:bg-[#0a4cb8]'
                }`}
              >
                {loading ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />}
                {loading ? '创建中…' : '创建并启动任务'}
              </button>
            </div>
          </div>
        </aside>
      </div>
    </div>
  )
}

function SectionHead({ step, title, inline = false }: { step: string; title: string; inline?: boolean }) {
  return (
    <div className={`flex items-center gap-2 ${inline ? '' : 'mb-3.5'}`}>
      <span className="grid h-[22px] w-[22px] place-items-center rounded-md bg-[#eaf1ff] font-mono text-[11px] font-bold text-[#153f9f]">
        {step}
      </span>
      <span className="text-sm font-semibold text-[#102033]">{title}</span>
    </div>
  )
}

function FieldLabel({ children }: { children: ReactNode }) {
  return <span className="mb-1.5 block text-xs font-semibold text-[#3c4759]">{children}</span>
}

function ToggleSwitch({ on, onClick, label }: { on: boolean; onClick: () => void; label: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      onClick={onClick}
      className={`inline-flex h-[38px] items-center gap-2.5 whitespace-nowrap rounded-[9px] border py-0 pl-2 pr-3 text-xs font-semibold transition ${
        on ? 'border-[#bfe0cf] bg-[#eafaf2] text-[#086247]' : 'border-[#e4e8f0] bg-white text-[#607086] hover:border-[#c7d2e0]'
      }`}
    >
      <span
        className={`flex h-5 w-[34px] shrink-0 items-center rounded-full p-0.5 transition ${
          on ? 'justify-end bg-[#16a34a]' : 'justify-start bg-[#cdd6e2]'
        }`}
      >
        <span className="h-4 w-4 rounded-full bg-white shadow-[0_1px_2px_rgba(0,0,0,0.25)]" />
      </span>
      {label}
    </button>
  )
}

function MiniMetric({ k, v }: { k: string; v: string }) {
  return (
    <div className="rounded-md border border-[#eef2f6] bg-[#f8fafd] px-2.5 py-2">
      <div className="text-[10px] text-[#7c8794]">{k}</div>
      <div className="mt-0.5 break-all text-xs font-semibold text-[#102033]">{v}</div>
    </div>
  )
}

async function retryTransientTaskStep<T>(
  operation: () => Promise<T>,
  onRetry: () => void,
  attempts = 3,
) {
  let lastError: unknown
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      return await operation()
    } catch (error) {
      lastError = error
      if (attempt >= attempts || !isTransientTaskError(error)) {
        throw error
      }
      onRetry()
      await wait(600 * attempt)
    }
  }
  throw lastError
}

function isTransientTaskError(error: unknown) {
  const message = error instanceof Error ? error.message : String(error)
  return /后端服务连接中断|正在重启|Internal Server Error|Failed to fetch|NetworkError|ECONNRESET|请求超时|无法连接后端服务/i.test(message)
}

function wait(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

function getLlmHealthStatus(profile: AgentLLMProfile | null): RuntimeProfileHealthStatus {
  if (!profile) return 'INCOMPLETE'
  if (profile.health_status) return profile.health_status
  if (profile.last_call_success === true) return 'READY'
  if (profile.last_call_success === false) return 'FAILED'
  if (profile.configured || isLlmProfileConfigured(profile)) return 'CONFIGURED'
  return profile.enabled ? 'INCOMPLETE' : 'DISABLED'
}

function isLlmProfileConfigured(profile: AgentLLMProfile) {
  const authReady = profile.auth_available ?? (profile.api_key_set || profile.provider === 'local')
  return Boolean(profile.enabled && profile.base_url && profile.model && authReady)
}

function llmStatusPillTone(status: RuntimeProfileHealthStatus) {
  if (status === 'READY') return 'success' as const
  if (status === 'FAILED' || status === 'BLOCKED') return 'danger' as const
  if (status === 'DISABLED') return 'neutral' as const
  return 'warning' as const
}

function llmChecklistTone(status: RuntimeProfileHealthStatus): ToneKey {
  if (status === 'READY') return 'PASS'
  if (status === 'FAILED' || status === 'BLOCKED') return 'FAIL'
  return 'WARN'
}

function llmReadinessMessage(
  profile: AgentLLMProfile | null,
  status: RuntimeProfileHealthStatus,
  loadError: string,
) {
  if (loadError) return `无法确认默认 LLM 状态：${loadError}。创建任务不受阻断，但本次运行的 LLM 可用性未知。`
  if (!profile) return '未发现默认 LLM 配置档。创建任务不受阻断，但 LLM 节点可能降级。'
  if (status === 'READY') return '最近一次实时调用成功，默认 LLM 配置档可用于本次任务。'
  if (status === 'CONFIGURED') return '配置字段完整，但尚未记录成功实时调用。创建任务不受阻断，建议先在统一 API 配置页执行实时测试。'
  if (status === 'FAILED') return '最近一次实时调用失败。创建任务不受阻断，但 LLM 节点可能降级或记录失败原因。'
  if (status === 'DISABLED') return '默认 LLM 配置档已禁用。创建任务不受阻断，但 LLM 节点不会按该配置档正常调用。'
  if (status === 'BLOCKED') return '默认 LLM 配置档的出站地址被策略阻断。创建任务不受阻断，但 LLM 节点可能无法真实调用。'
  return '默认 LLM 配置档配置不完整。创建任务不受阻断，但 LLM 节点可能降级。'
}

function formatLlmLiveCallStatus(profile: AgentLLMProfile | null) {
  if (!profile) return 'UNKNOWN'
  const latency = typeof profile.last_latency_ms === 'number' ? ` · ${profile.last_latency_ms}ms` : ''
  if (profile.last_call_success === true) return `READY${latency}`
  if (profile.last_call_success === false) return `FAILED${latency}`
  const status = getLlmHealthStatus(profile)
  if (status === 'CONFIGURED') return 'CONFIGURED · 未记录成功实时调用'
  if (status === 'INCOMPLETE') return 'INCOMPLETE'
  return `${profile.last_test_status || status}${latency}`
}

function llmHealthMeaning(status: RuntimeProfileHealthStatus) {
  if (status === 'READY') return '最近实时调用成功'
  if (status === 'CONFIGURED') return '配置完整，未确认实时调用成功'
  if (status === 'FAILED') return '最近实时调用失败'
  if (status === 'DISABLED') return '已禁用'
  if (status === 'BLOCKED') return '出站策略阻断'
  return '配置不完整或不可确认'
}

function buildAnalysisRunPreflightGovernance({
  canCreate,
  disabledReason,
  cleanSymbol,
  scenarioId,
  runMode,
  usesPortfolioContext,
  selectedSnapshotId,
  selectedSnapshot,
  selectedSnapshotDetail,
  snapshotLoadError,
  portfolioPreflight,
  llmHealthStatus,
  researchIterationId,
}: {
  canCreate: boolean
  disabledReason: string
  cleanSymbol: string
  scenarioId: string
  runMode: RunMode
  usesPortfolioContext: boolean
  selectedSnapshotId: string
  selectedSnapshot?: PortfolioSnapshotSummary
  selectedSnapshotDetail: PortfolioSnapshot | null
  snapshotLoadError: string
  portfolioPreflight: PortfolioPreflight
  llmHealthStatus: RuntimeProfileHealthStatus
  researchIterationId: string
}): AnalysisRunPreflightGovernance {
  const snapshotId = usesPortfolioContext ? selectedSnapshotId : 'USER_INPUT_ONLY'
  const researchId = researchIterationId || 'research:none'
  const contextId = `${scenarioId}:${runMode}:${snapshotId}:${researchId}`
  const qualityStatus = String(selectedSnapshot?.qualityStatus || '').toUpperCase()
  const qualityUsable = !selectedSnapshot || ['READY', 'PASS', 'OK', 'HEALTHY', 'VALID'].includes(qualityStatus)
  const templateConfidence = selectedSnapshot?.templateConfidence ?? 0
  const hasMissingEvidence = !cleanSymbol || (usesPortfolioContext && !selectedSnapshot)

  let evidenceStrength = 'MEDIUM：提交上下文已复核'
  if (hasMissingEvidence) {
    evidenceStrength = 'MISSING：缺少运行输入'
  } else if (!usesPortfolioContext) {
    evidenceStrength = 'LOW：USER_INPUT_ONLY 持仓'
  } else if (snapshotLoadError || !qualityUsable || portfolioPreflight.level === 'HIGH') {
    evidenceStrength = 'LOW：组合证据需复核'
  } else if (!selectedSnapshotDetail) {
    evidenceStrength = 'MEDIUM：快照详情加载中'
  } else if (templateConfidence > 0 && templateConfidence < 0.7) {
    evidenceStrength = 'LOW：券商模板需复核'
  }

  let blocker = '无阻塞，等待创建'
  if (!canCreate) {
    blocker = disabledReason || '当前角色无权创建运行'
  } else if (!cleanSymbol) {
    blocker = '缺少股票代码'
  } else if (snapshotLoadError) {
    blocker = `快照详情加载失败：${snapshotLoadError}`
  } else if (usesPortfolioContext && !selectedSnapshot) {
    blocker = '所选组合快照不可用'
  } else if (portfolioPreflight.level === 'HIGH') {
    blocker = '组合风险高，提交前需复核'
  } else if (llmHealthStatus === 'BLOCKED') {
    blocker = '默认 LLM 出站策略阻断，LLM 节点可能降级'
  }

  let nextAction = '创建并启动任务'
  if (!canCreate) {
    nextAction = '切换到 researcher+ 角色'
  } else if (!cleanSymbol) {
    nextAction = '填写股票代码'
  } else if (snapshotLoadError || (usesPortfolioContext && !selectedSnapshot)) {
    nextAction = '重新选择或刷新组合快照'
  } else if (!usesPortfolioContext) {
    nextAction = '确认 USER_INPUT_ONLY 或选择组合快照'
  } else if (portfolioPreflight.level === 'HIGH') {
    nextAction = '复核组合风险后再提交'
  } else if (!['READY', 'CONFIGURED'].includes(llmHealthStatus)) {
    nextAction = '可提交；建议先刷新 LLM 实时状态'
  }

  return {
    contextId,
    evidenceStrength,
    blocker,
    nextAction,
    evidenceUsage: 'simulation_only',
    strongConclusionAllowed: false,
  }
}

function buildPortfolioPreflight(
  snapshot: PortfolioSnapshot | null,
  summary: PortfolioSnapshotSummary | undefined,
  symbol: string,
): PortfolioPreflight {
  const notes: string[] = []
  const positions = snapshot?.positions ?? []
  const cleanSymbol = normalizePortfolioSymbol(symbol)
  const matched = cleanSymbol
    ? positions.find((position) => normalizePortfolioSymbol(position.symbol) === cleanSymbol) ?? null
    : null
  const totalPositionRatio = summary?.totalPositionRatio ?? snapshot?.totalPositionRatio ?? 0
  const maxSinglePositionRatio = summary?.maxSinglePositionRatio ?? snapshot?.maxSinglePositionRatio ?? 0
  const issueCount = summary?.issueCount ?? snapshot?.issues.length ?? 0
  const positionCount = summary?.positionCount ?? positions.length
  const brokerTemplateLabel = summary?.brokerTemplateLabel || snapshot?.brokerTemplateLabel || ''
  const brokerTemplateId = summary?.brokerTemplateId || snapshot?.brokerTemplateId || ''
  const templateConfidence = summary?.templateConfidence ?? snapshot?.templateConfidence ?? 0
  const templateWarnings = summary?.templateWarnings ?? snapshot?.templateWarnings ?? []
  const topIndustry = topExposure(positions, 'industry')
  const topTheme = topExposure(positions, 'theme')
  const topRiskFactor = topExposure(positions, 'riskFactor')
  let level: PortfolioPreflightLevel = 'LOW'

  if (!summary) {
    return {
      level: 'MEDIUM',
      status: 'WARN',
      notes: ['未选择组合快照；本次运行将仅使用 USER_INPUT_ONLY 持仓约束。'],
      matchedSymbol: '',
      matchedWeight: null,
      topIndustry: null,
      topTheme: null,
      topRiskFactor: null,
    }
  }

  if (!snapshot) {
    notes.push('已选择快照概要，但详细持仓仍在加载；创建任务时后端会解析该快照。')
    level = 'MEDIUM'
  }

  if (issueCount > 0) {
    notes.push(`导入质量存在 ${issueCount} 个问题；依赖该快照前请复核券商模板映射。`)
    level = 'HIGH'
  }
  if (brokerTemplateLabel || brokerTemplateId) {
    notes.push(`券商导入模板：${formatPortfolioTemplateName(brokerTemplateLabel, brokerTemplateId)}，置信度 ${formatPercent(templateConfidence)}。`)
  }
  if (templateConfidence > 0 && templateConfidence < 0.7) {
    notes.push('券商模板置信度低于 70%；将该快照作为持仓证据前请复核映射列。')
    level = level === 'LOW' ? 'MEDIUM' : level
  }
  for (const warning of templateWarnings.slice(0, 2)) {
    notes.push(`券商模板警告：${formatPortfolioTemplateWarning(warning)}`)
    level = level === 'LOW' ? 'MEDIUM' : level
  }
  if (positionCount === 0) {
    notes.push('快照没有导入持仓；组合证据偏弱。')
    level = 'HIGH'
  }
  if (totalPositionRatio >= 0.9) {
    notes.push(`股票总仓位为 ${formatPercent(totalPositionRatio)}，新增风险的现金缓冲偏少。`)
    level = 'HIGH'
  } else if (totalPositionRatio >= 0.7) {
    notes.push(`股票总仓位为 ${formatPercent(totalPositionRatio)}；提交前请复核现金缓冲和回撤容忍度。`)
    level = level === 'LOW' ? 'MEDIUM' : level
  }
  if (maxSinglePositionRatio >= 0.3) {
    notes.push(`最大单一持仓为 ${formatPercent(maxSinglePositionRatio)}，超过 30% 集中度复核阈值。`)
    level = 'HIGH'
  } else if (maxSinglePositionRatio >= 0.2) {
    notes.push(`最大单一持仓为 ${formatPercent(maxSinglePositionRatio)}；需要复核个股集中度。`)
    level = level === 'LOW' ? 'MEDIUM' : level
  }
  if (cleanSymbol && snapshot && !matched) {
    notes.push('当前股票不在所选快照中；后端会将该股票标记为无持仓行。')
    level = level === 'LOW' ? 'MEDIUM' : level
  }
  if (matched) {
    notes.push(`当前股票持仓：${matched.symbol}，权重 ${formatPercent(matched.weight)}，持股 ${numberText(matched.shares)}，可用 ${numberText(matched.availableShares)}。`)
  }
  for (const exposure of [topIndustry, topTheme, topRiskFactor]) {
    if (!exposure) continue
    if (exposure.weight >= 0.5) {
      notes.push(`${formatPortfolioDisplayText(exposure.label)} 暴露达到 ${formatPercent(exposure.weight)}；加仓决策前应复核集中度。`)
      level = level === 'HIGH' ? 'HIGH' : 'MEDIUM'
    }
  }
  if (notes.length === 0) {
    notes.push('未发现导入质量问题或明显集中度阈值触发；仍需以 DVG、风险防火墙和执行检查作为最终关口。')
  }

  return {
    level,
    status: level === 'HIGH' ? 'FAIL' : level === 'MEDIUM' ? 'WARN' : 'PASS',
    notes,
    matchedSymbol: matched?.symbol ?? '',
    matchedWeight: matched?.weight ?? null,
    topIndustry,
    topTheme,
    topRiskFactor,
  }
}

function normalizePortfolioSymbol(value: string) {
  return value.trim().toUpperCase().replace(/\.(SH|SZ|BJ|HK|US|JP)$/i, '')
}

function topExposure(
  positions: PortfolioSnapshot['positions'],
  key: 'industry' | 'theme' | 'riskFactor',
): PortfolioExposure | null {
  const exposure = new Map<string, number>()
  for (const position of positions) {
    const label = String(position[key] || '').trim()
    if (!label) continue
    const weight = Number.isFinite(position.weight) ? position.weight : 0
    exposure.set(label, (exposure.get(label) ?? 0) + weight)
  }
  return Array.from(exposure.entries())
    .sort((left, right) => right[1] - left[1])
    .map(([label, weight]) => ({ label, weight }))[0] ?? null
}

function formatExposure(exposure: PortfolioExposure | null) {
  return exposure ? `${formatPortfolioDisplayText(exposure.label)} ${formatPercent(exposure.weight)}` : '-'
}

function formatPortfolioSourceName(value?: string | null) {
  const trimmed = String(value || '').trim()
  if (!trimmed) return '-'
  const signalOpsMatch = trimmed.match(/^SignalOps paper portfolio (.+)$/)
  if (signalOpsMatch) return `SignalOps 模拟组合 ${signalOpsMatch[1]}`
  return formatPortfolioDisplayText(trimmed)
}

function formatPortfolioTemplateName(label?: string | null, templateId?: string | null) {
  return formatPortfolioDisplayText(label || templateId || '-')
}

function formatPortfolioDisplayText(value: string) {
  const trimmed = String(value || '').trim()
  return portfolioDisplayLabels[trimmed] ?? trimmed
}

function formatPortfolioTemplateWarning(value: string) {
  const trimmed = String(value || '').trim()
  if (!trimmed) return '-'
  if (trimmed.startsWith('Required holding columns were not fully mapped:')) {
    return `必填持仓列未完全映射：${localizePortfolioFieldList(trimmed.replace(/^Required holding columns were not fully mapped:\s*/i, '').replace(/\.$/, ''))}。`
  }
  if (trimmed.startsWith('Review broker template mapping for optional columns:')) {
    return `请复核券商模板的可选列映射：${localizePortfolioFieldList(trimmed.replace(/^Review broker template mapping for optional columns:\s*/i, '').replace(/\.$/, ''))}。`
  }
  if (trimmed === 'No broker-specific source hint matched; generic column aliases were used.') {
    return '未匹配到特定券商来源提示，已使用通用列别名。'
  }
  return trimmed
}

function localizePortfolioFieldList(value: string) {
  const fieldLabels: Record<string, string> = {
    symbol: '股票代码',
    shares: '持股数量',
    name: '股票名称',
    availableShares: '可用股数',
    costPrice: '成本价',
    marketValue: '持仓市值',
  }
  return value.split(',').map((item) => {
    const field = item.trim()
    return fieldLabels[field] ?? field
  }).join('、')
}

function portfolioRiskRailTone(level: PortfolioPreflightLevel) {
  if (level === 'HIGH') return 'border-[#f6cccc] bg-[#fdecec]'
  if (level === 'MEDIUM') return 'border-[#f0dcab] bg-[#fdf6e3]'
  return 'border-[#bfe0cf] bg-[#e8f7f0]'
}

function numberText(value: number) {
  return Number(value || 0).toLocaleString('zh-CN', { maximumFractionDigits: 2 })
}

function formatMoney(value: number) {
  return `¥${Number(value || 0).toLocaleString('zh-CN', { maximumFractionDigits: 0 })}`
}

function formatPercent(value: number) {
  return `${(Number(value || 0) * 100).toFixed(1)}%`
}
