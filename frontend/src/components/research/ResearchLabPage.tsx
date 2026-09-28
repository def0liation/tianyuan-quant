import { useEffect, useMemo, useState } from 'react'
import { NavLink, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import {
  Archive,
  ArrowRight,
  Beaker,
  BookOpenCheck,
  BrainCircuit,
  CheckCircle2,
  Database,
  FileText,
  GitBranch,
  Layers,
  LineChart,
  Play,
  RefreshCw,
  ShieldCheck,
  Upload,
} from 'lucide-react'
import { MetricTile } from '../common/Material'
import { DataCompressionPage } from '../data/DataCompressionPage'
import { KnowledgeIterationPage } from '../knowledge/KnowledgeIterationPage'
import { CaseLibraryPage } from '../caseLibrary/CaseLibraryPage'
import { EvaluationSandboxPage } from '../evaluation/EvaluationSandboxPage'
import { KnowledgeVersionsPage } from '../evaluation/KnowledgeVersionsPage'
import { ResearchLoopsPage } from './ResearchLoopsPage'
import { ResearchTracesPage } from './ResearchTracesPage'
import BacktestPage from '../backtest/BacktestPage'
import { getResearchSummary } from '../../api/researchClient'
import { ResearchSummary } from '../../types'

const tabs = [
  { label: '总览', description: '状态与入口', path: '/research-lab/overview', icon: BrainCircuit },
  { label: '研究迭代', description: '假设与轮次', path: '/research-lab/research', icon: GitBranch },
  { label: '数据压缩', description: '证据摘要', path: '/research-lab/evidence', icon: Database },
  { label: '回测', description: '复盘验证', path: '/research-lab/backtest', icon: Play },
  { label: '知识迭代', description: '知识反馈', path: '/research-lab/knowledge', icon: BookOpenCheck },
  { label: '案例库', description: '案例沉淀', path: '/research-lab/cases', icon: Archive },
  { label: '沙箱评估', description: '补丁评估', path: '/research-lab/evaluation', icon: Beaker },
  { label: '知识版本', description: '版本门禁', path: '/research-lab/versions', icon: GitBranch },
  { label: '轨迹导入', description: '外部轨迹', path: '/research-lab/traces', icon: Upload },
]

const workflowSteps = [
  {
    label: '01',
    title: '提出假设',
    subtitle: 'Hypothesis',
    detail: '把研究目标、目标模块和预期指标记录成可追踪循环。',
    icon: BrainCircuit,
    tone: 'border-cyan-100 bg-cyan-50 text-cyan-700',
  },
  {
    label: '02',
    title: '运行实验',
    subtitle: 'Run',
    detail: '连接当前分析、回测、Agent 输出和人工反馈。',
    icon: LineChart,
    tone: 'border-slate-200 bg-slate-50 text-slate-700',
  },
  {
    label: '03',
    title: '压缩证据',
    subtitle: 'Evidence',
    detail: '保留质量分、关键摘要、来源链接和可复核指标。',
    icon: Database,
    tone: 'border-emerald-100 bg-emerald-50 text-emerald-700',
  },
  {
    label: '04',
    title: '沉淀知识',
    subtitle: 'Feedback',
    detail: '形成案例、知识条目、补丁和沙箱评估结果。',
    icon: BookOpenCheck,
    tone: 'border-amber-100 bg-amber-50 text-amber-700',
  },
]

const workspaceCards = [
  {
    title: '研究迭代',
    subtitle: '研究循环',
    description: '创建假设、生成轮次、连接当前运行结果并记录反馈 verdict。',
    path: '/research-lab/research',
    icon: GitBranch,
    cta: '进入迭代台',
    bullets: ['工作流向导', '下一步动作', '阻断原因'],
    accent: 'bg-cyan-500',
  },
  {
    title: '数据压缩',
    subtitle: '证据压缩',
    description: '把运行摘要、质量提示、指标对比和保留策略放到同一个证据视图。',
    path: '/research-lab/evidence',
    icon: Database,
    cta: '查看证据',
    bullets: ['运行摘要', '质量分', '保留策略'],
    accent: 'bg-emerald-500',
  },
  {
    title: '知识与案例',
    subtitle: 'Knowledge and cases',
    description: '沉淀可复用案例、错误模式、知识条目和修复线索。',
    path: '/research-lab/cases',
    icon: Archive,
    cta: '打开案例库',
    bullets: ['Case library', 'Error archive', 'Patch trace'],
    accent: 'bg-amber-500',
  },
  {
    title: '评估沙箱',
    subtitle: 'Evaluation sandbox',
    description: '用独立评估结果决定补丁是否进入知识版本或继续回滚。',
    path: '/research-lab/evaluation',
    icon: Beaker,
    cta: '进入评估',
    bullets: ['补丁测试', '晋级门禁', '版本复核'],
    accent: 'bg-sky-500',
  },
  {
    title: 'Trace 导入',
    subtitle: 'RD-Agent trace',
    description: '导入外部研究轨迹，先检查事件与产物，再关联到研究循环或运行记录。',
    path: '/research-lab/traces',
    icon: Upload,
    cta: '导入轨迹',
    bullets: ['轨迹 JSON', '事件索引', '产物复核'],
    accent: 'bg-violet-500',
  },
]

function ResearchLabOverview() {
  const navigate = useNavigate()
  const [summary, setSummary] = useState<ResearchSummary | null>(null)
  const [summaryError, setSummaryError] = useState<string | null>(null)

  useEffect(() => {
    let mounted = true
    getResearchSummary()
      .then((nextSummary) => {
        if (!mounted) return
        setSummary(nextSummary)
        setSummaryError(null)
      })
      .catch((err) => {
        if (!mounted) return
        setSummaryError(err instanceof Error ? err.message : '研究摘要暂不可用')
      })
    return () => {
      mounted = false
    }
  }, [])

  const acceptedRate = summary && summary.total_iterations > 0
    ? `${Math.round((summary.accepted_iterations / summary.total_iterations) * 100)}%`
    : summary
      ? '0%'
      : '--'

  const overviewMetrics = useMemo(() => [
    {
      label: '研究循环',
      value: summary ? summary.total_loops.toLocaleString() : '--',
      helper: 'Total loops / 全部循环',
      icon: GitBranch,
      tone: 'bg-cyan-50 text-cyan-700',
    },
    {
      label: '活跃循环',
      value: summary ? summary.active_loops.toLocaleString() : '--',
      helper: '正在推进的研究循环',
      icon: RefreshCw,
      tone: 'bg-emerald-50 text-emerald-700',
    },
    {
      label: '迭代轮次',
      value: summary ? summary.total_iterations.toLocaleString() : '--',
      helper: 'Iterations / 研究轮次',
      icon: Layers,
      tone: 'bg-slate-100 text-slate-700',
    },
    {
      label: '采纳率',
      value: acceptedRate,
      helper: 'Accepted / 已采纳反馈',
      icon: CheckCircle2,
      tone: 'bg-amber-50 text-amber-700',
    },
  ], [acceptedRate, summary])

  return (
    <div className="space-y-6">
      <section className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(280px,420px)]">
        <div className="min-w-0 rounded-md border border-slate-200 bg-white p-5 shadow-sm shadow-slate-200/60">
          <div className="flex flex-wrap items-center gap-2 text-xs font-semibold">
            <span className="rounded-md bg-cyan-50 px-2.5 py-1 text-cyan-700">研究实验室</span>
            <span className="rounded-md bg-emerald-50 px-2.5 py-1 text-emerald-700">闭环</span>
            <span className="rounded-md bg-amber-50 px-2.5 py-1 text-amber-700">证据优先</span>
          </div>
          <h2 className="mt-4 text-2xl font-semibold tracking-tight text-slate-950 sm:text-3xl">研究实验室工作台</h2>
          <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-600">
            将假设、运行、证据压缩、回测验证和知识反馈放在同一个可审计闭环中。总览只做状态聚合和入口调度，具体结论仍回到各模块复核。
          </p>
          <div className="mt-5 flex flex-wrap gap-3">
            <button
              type="button"
              onClick={() => navigate('/research-lab/research')}
              className="inline-flex items-center gap-2 rounded-md bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-800"
            >
              <GitBranch size={16} />
              新建研究迭代
            </button>
            <button
              type="button"
              onClick={() => navigate('/research-lab/backtest')}
              className="inline-flex items-center gap-2 rounded-md border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-50"
            >
              <Play size={16} />
              打开回测工作台
            </button>
            <button
              type="button"
              onClick={() => navigate('/research-lab/evidence')}
              className="inline-flex items-center gap-2 rounded-md border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-50"
            >
              <FileText size={16} />
              查看证据压缩
            </button>
          </div>
        </div>

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1">
          {overviewMetrics.map((metric) => {
            const Icon = metric.icon
            return (
              <MetricTile key={metric.label} label={metric.label} value={metric.value} helper={summaryError ?? metric.helper} icon={Icon} />
            )
          })}
        </div>
      </section>

      <section className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-base font-semibold text-slate-950">闭环进度</h3>
            <p className="mt-1 text-sm text-slate-500">四个节点固定研究假设、实验运行、证据压缩和知识反馈。</p>
          </div>
          <button
            type="button"
            onClick={() => navigate('/research-lab/versions')}
            className="inline-flex items-center gap-2 rounded-md border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
          >
            <ShieldCheck size={15} />
            知识版本门禁
          </button>
        </div>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          {workflowSteps.map((step, index) => {
            const Icon = step.icon
            return (
              <div key={step.title} className="rounded-md border border-slate-200 bg-white p-4 shadow-sm shadow-slate-200/60">
                <div className="flex items-start justify-between gap-3">
                  <div className={`grid h-10 w-10 shrink-0 place-items-center rounded-md border ${step.tone}`}>
                    <Icon size={18} />
                  </div>
                  <span className="font-mono text-xs font-semibold text-slate-400">{step.label}</span>
                </div>
                <div className="mt-4 text-base font-semibold text-slate-950">{step.title}</div>
                <div className="mt-1 text-xs font-medium uppercase tracking-wider text-slate-400">{step.subtitle}</div>
                <p className="mt-3 min-h-12 text-sm leading-6 text-slate-600">{step.detail}</p>
                <div className="mt-4 flex items-center gap-2 text-xs font-semibold text-slate-500">
                  <span className="h-px flex-1 bg-slate-200" />
                  {index < workflowSteps.length - 1 ? (
                    <span className="inline-flex items-center gap-1">
                      下一步 <ArrowRight size={12} />
                    </span>
                  ) : (
                    <span>沉淀</span>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      </section>

      <section className="space-y-3">
        <div>
          <h3 className="text-base font-semibold text-slate-950">模块入口</h3>
          <p className="mt-1 text-sm text-slate-500">从总览进入具体工作面，避免在多个页面重复承载同一功能。</p>
        </div>
        <div className="grid gap-3 lg:grid-cols-2 2xl:grid-cols-5">
          {workspaceCards.map((card) => {
            const Icon = card.icon
            return (
              <button
                key={card.path}
                type="button"
                onClick={() => navigate(card.path)}
                className="group rounded-md border border-slate-200 bg-white p-4 text-left shadow-sm shadow-slate-200/60 transition hover:border-cyan-300 hover:bg-slate-50"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="text-base font-semibold text-slate-950">{card.title}</div>
                    <div className="mt-1 text-xs font-medium uppercase tracking-wider text-slate-400">{card.subtitle}</div>
                  </div>
                  <div className={`grid h-10 w-10 shrink-0 place-items-center rounded-md text-white ${card.accent}`}>
                    <Icon size={18} />
                  </div>
                </div>
                <p className="mt-3 min-h-16 text-sm leading-6 text-slate-600">{card.description}</p>
                <div className="mt-4 flex flex-wrap gap-2">
                  {card.bullets.map((bullet) => (
                    <span key={bullet} className="rounded-md bg-slate-100 px-2 py-1 text-xs text-slate-600">{bullet}</span>
                  ))}
                </div>
                <div className="mt-4 inline-flex items-center gap-2 text-sm font-semibold text-cyan-700 transition group-hover:text-cyan-900">
                  {card.cta}
                  <ArrowRight size={15} />
                </div>
              </button>
            )
          })}
        </div>
      </section>

      <section className="grid gap-4 lg:grid-cols-[1.1fr_0.9fr]">
        <div className="rounded-md border border-slate-200 bg-white p-5 shadow-sm shadow-slate-200/60">
          <div className="flex items-start gap-3">
            <div className="grid h-10 w-10 shrink-0 place-items-center rounded-md bg-slate-100 text-slate-700">
              <ShieldCheck size={18} />
            </div>
            <div className="min-w-0">
              <h3 className="text-base font-semibold text-slate-950">可验证输出</h3>
              <p className="mt-2 text-sm leading-6 text-slate-600">
                每次研究都保留来源、证据、结论和下一步。弱样本、mock 和 fallback 只作为 supporting evidence，不自动升级成强结论。
              </p>
            </div>
          </div>
          <div className="mt-5 grid gap-3 sm:grid-cols-3">
            {['来源可追溯', '反馈可记录', '补丁可评估'].map((item) => (
              <div key={item} className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-medium text-slate-700">
                {item}
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-md border border-slate-200 bg-white p-5 shadow-sm shadow-slate-200/60">
          <div className="flex items-start gap-3">
            <div className="grid h-10 w-10 shrink-0 place-items-center rounded-md bg-cyan-50 text-cyan-700">
              <BrainCircuit size={18} />
            </div>
            <div className="min-w-0">
              <h3 className="text-base font-semibold text-slate-950">下一步优先级</h3>
              <p className="mt-2 text-sm leading-6 text-slate-600">
                先进入研究迭代查看当前循环的下一步向导，再按阻塞原因补齐运行、回测、资产或反馈。
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => navigate('/research-lab/research')}
            className="mt-5 inline-flex items-center gap-2 rounded-md bg-slate-900 px-3 py-2 text-sm font-semibold text-white transition hover:bg-slate-800"
          >
            <GitBranch size={15} />
            打开研究迭代向导
          </button>
          <div className="mt-5 flex flex-wrap gap-2 text-xs text-slate-600">
            <span className="rounded-md bg-cyan-50 px-2.5 py-1 font-semibold text-cyan-700">活跃循环：{summary?.active_loops ?? '--'}</span>
            <span className="rounded-md bg-amber-50 px-2.5 py-1 font-semibold text-amber-700">需补丁轮次：{summary?.patch_required_iterations ?? '--'}</span>
            <span className="rounded-md bg-slate-100 px-2.5 py-1 font-semibold text-slate-700">跨项目链接：{summary?.linked_project_count ?? '--'}</span>
          </div>
        </div>
      </section>
    </div>
  )
}

export function ResearchLabPage() {
  const location = useLocation()
  const activePath = useMemo(() => {
    return tabs.find((tab) => location.pathname === tab.path)?.path ?? '/research-lab/overview'
  }, [location.pathname])

  return (
    <div className="space-y-5">
      <div className="sticky top-0 z-10 -mx-4 border-b border-slate-200 bg-white/95 px-4 py-3 backdrop-blur sm:-mx-6 sm:px-6 xl:-mx-8 xl:px-8">
        <div className="space-y-3">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div className="min-w-0">
              <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">研究实验室模块</div>
              <div className="mt-1 text-sm font-semibold text-slate-950">统一入口，按研究闭环切换工作面</div>
            </div>
            <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-600">
              {tabs.length} 个模块
            </div>
          </div>
          <nav aria-label="研究实验室模块" className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5 2xl:grid-cols-9">
            {tabs.map((tab) => {
              const Icon = tab.icon
              return (
                <NavLink
                  key={tab.path}
                  to={tab.path}
                  className={({ isActive }) =>
                    `group flex min-h-[52px] min-w-0 items-center gap-2 rounded-md border px-3 py-2 text-sm transition ${
                      isActive || activePath === tab.path
                        ? 'border-cyan-200 bg-cyan-50 text-cyan-900 shadow-sm'
                        : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:bg-slate-50 hover:text-slate-900'
                    }`
                  }
                >
                  <Icon size={16} className="shrink-0" />
                  <span className="min-w-0">
                    <span className="block truncate font-semibold">{tab.label}</span>
                    <span className="block truncate text-[11px] font-medium text-slate-500">{tab.description}</span>
                  </span>
                </NavLink>
              )
            })}
          </nav>
        </div>
      </div>

      <Routes>
        <Route index element={<Navigate to="overview" replace />} />
        <Route path="overview" element={<ResearchLabOverview />} />
        <Route path="research" element={<ResearchLoopsPage />} />
        <Route path="evidence" element={<DataCompressionPage />} />
        <Route path="backtest" element={<BacktestPage />} />
        <Route path="knowledge" element={<KnowledgeIterationPage />} />
        <Route path="cases" element={<CaseLibraryPage />} />
        <Route path="evaluation" element={<EvaluationSandboxPage />} />
        <Route path="versions" element={<KnowledgeVersionsPage />} />
        <Route path="traces" element={<ResearchTracesPage />} />
        <Route path="*" element={<Navigate to="overview" replace />} />
      </Routes>
    </div>
  )
}
