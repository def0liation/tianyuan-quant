import { useEffect, useMemo, useState } from 'react'
import { Activity, ChevronDown, ChevronUp, Database, Radio, ShieldCheck } from 'lucide-react'
import { NavLink, useLocation } from 'react-router-dom'
import { useBackendStore } from '../../store/useBackendStore'
import { useAnalysisStore } from '../../store/useAnalysisStore'
import { HistorySelector } from '../history/HistorySelector'
import { Badge } from '../common/Badge'
import { DataModeBadge } from '../common/DataModeBadge'
import routeManifest from '../../routeManifest.json'

const GUARDRAIL_HUB_PATH = '/guardrail-hub'
const LEGACY_GUARDRAIL_PATHS = ['/dvg-gate', '/risk', '/trade-micro'] as const
const NON_ANALYSIS_RUN_QUERY_ROUTES = new Set(['/research-lab/backtest'])

function linkedAnalysisRunId(pathname: string, search: string) {
  if (NON_ANALYSIS_RUN_QUERY_ROUTES.has(pathname)) return ''
  return new URLSearchParams(search).get('run_id')?.trim() || ''
}

function getActivePath(pathname: string) {
  if (pathname.startsWith('/research-lab')) return '/research-lab'
  if (LEGACY_GUARDRAIL_PATHS.includes(pathname as (typeof LEGACY_GUARDRAIL_PATHS)[number])) return GUARDRAIL_HUB_PATH
  const redirect = routeManifest.redirects.find((item) => item.from === pathname)
  if (redirect?.to.startsWith('/research-lab')) return '/research-lab'
  return redirect?.to ?? pathname
}

function getActiveRoute(pathname: string) {
  const activePath = getActivePath(pathname)
  const group = routeManifest.navGroups.find((entry) => entry.items.some((item) => item.path === activePath))
  const item = group?.items.find((entry) => entry.path === activePath)
  return {
    activePath,
    group,
    item,
    label: item?.label ?? (pathname.startsWith('/research-lab') ? '研究实验室' : '工程控制台'),
  }
}

export function TopBar() {
  const { backendStatus, startupStatus, isBackendConnected, checkBackendHealth } = useBackendStore()
  const { currentRun } = useAnalysisStore()
  const [isCompact, setIsCompact] = useState(false)
  const location = useLocation()
  const routeState = useMemo(() => getActiveRoute(location.pathname), [location.pathname])
  const linkedRunId = useMemo(
    () => linkedAnalysisRunId(location.pathname, location.search),
    [location.pathname, location.search],
  )
  const isLinkedRunPending = Boolean(linkedRunId && currentRun?.runId !== linkedRunId)
  const displayedRun = isLinkedRunPending ? undefined : currentRun

  useEffect(() => {
    checkBackendHealth()
    if (isBackendConnected && startupStatus?.ready) return
    const timer = window.setInterval(() => {
      checkBackendHealth()
    }, 1500)
    return () => window.clearInterval(timer)
  }, [checkBackendHealth, isBackendConnected, startupStatus?.ready])

  const finalAction = displayedRun?.finalWriter?.finalAction ?? displayedRun?.finalAction ?? 'WAIT'
  const safetyStatus = backendStatus?.tradingEnabled || backendStatus?.autoOrderEnabled ? '异常' : '安全锁定'
  const backendLabel = isBackendConnected ? '已连接' : '未连接'
  const runId = isLinkedRunPending ? linkedRunId : displayedRun?.runId ?? 'RUN-未选择'
  const symbol = isLinkedRunPending ? '正在加载关联运行' : displayedRun?.stockCode ?? '组合 / 待选择'
  const groupItems = routeState.group?.items ?? routeManifest.navGroups[0]?.items ?? []

  return (
    <header className="sticky top-0 z-30 bg-[var(--md-sys-color-surface)]">
      <div className="institution-command-bar">
        <div className="mx-auto flex min-h-16 max-w-[1680px] items-center justify-between gap-2 px-3 sm:gap-4 sm:px-6 xl:px-8">
          <div className="flex min-w-0 flex-1 items-center gap-3 sm:gap-4">
            <div className="grid h-10 w-10 shrink-0 place-items-center rounded-[var(--institution-radius-md)] bg-[var(--md-sys-color-primary)] text-sm font-black text-[var(--md-sys-color-on-primary)]">
              TY
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2 text-[11px] font-bold uppercase text-[var(--md-sys-color-on-surface-variant)]">
                <span>天元量化 Agent</span>
                <span className="h-1 w-1 rounded-full bg-[var(--md-sys-color-outline)]" />
                <span>{routeState.group?.title ?? '工作台'}</span>
              </div>
              <div className="mt-1 flex min-w-0 flex-wrap items-center gap-2">
                <h1 className="min-w-0 flex-1 truncate text-lg font-semibold leading-6 text-[var(--md-sys-color-on-surface)] sm:text-xl">
                  {routeState.label}
                </h1>
                <Badge status={finalAction}>{isLinkedRunPending ? 'RUN 加载中' : finalAction}</Badge>
                {isLinkedRunPending ? <Badge status="WAIT">等待 URL 运行</Badge> : <DataModeBadge mode={displayedRun?.dataMode || 'MOCK'} />}
              </div>
            </div>
          </div>

          <div className="flex shrink-0 items-center gap-2">
            {!isCompact ? (
              <>
                <HistorySelector />
                <div className="hidden min-w-0 items-center gap-2 xl:flex">
                  <div className="institution-chip">
                    <Database size={13} />
                    <span data-testid="topbar-current-run-id" className="max-w-[180px] truncate font-mono" title={runId}>{runId}</span>
                  </div>
                  <div className="institution-chip institution-chip-data">
                    <Activity size={13} />
                    <span data-testid={isLinkedRunPending ? 'topbar-current-run-loading' : 'topbar-current-run-symbol'} className="max-w-[140px] truncate" title={symbol}>{symbol}</span>
                  </div>
                  <div className="institution-chip">
                    <Radio size={13} />
                    后端: {backendLabel}
                  </div>
                  <div className={safetyStatus === '异常' ? 'institution-chip border-[var(--md-sys-color-error-container)] bg-[var(--md-sys-color-error-container)] text-[var(--md-sys-color-on-error-container)]' : 'institution-chip'}>
                    <ShieldCheck size={13} />
                    交易安全: {safetyStatus}
                  </div>
                  <div className="institution-chip">simulationOnly=true</div>
                  <div className="institution-chip">isRealTrade=false</div>
                </div>
              </>
            ) : null}
            <button
              type="button"
              className="material-icon-button material-icon-button-outlined shrink-0"
              onClick={() => setIsCompact((value) => !value)}
              title={isCompact ? '展开顶部' : '收起顶部'}
              aria-label={isCompact ? '展开顶部' : '收起顶部'}
            >
              {isCompact ? <ChevronDown size={16} /> : <ChevronUp size={16} />}
            </button>
          </div>
        </div>
      </div>

      <div className="institution-secondary-nav">
        <div className="mx-auto flex min-h-[3.25rem] max-w-[1680px] items-center gap-3 overflow-x-auto px-3 sm:gap-4 sm:px-6 xl:px-8">
          <div className="hidden shrink-0 items-center gap-1 md:flex">
            {routeManifest.navGroups.map((group) => {
              const isActive = group.title === routeState.group?.title
              return (
                <span key={group.title} className={isActive ? 'institution-chip institution-chip-data' : 'institution-chip'}>
                  {group.title}
                </span>
              )
            })}
          </div>
          <nav aria-label="页面导航" className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto py-2">
            {groupItems.map((item) => (
              <NavLink
                key={item.path}
                to={item.path}
                className={({ isActive }) =>
                  isActive || item.path === routeState.activePath
                    ? 'institution-nav-pill institution-nav-pill-active'
                    : 'institution-nav-pill'
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
        </div>
      </div>
    </header>
  )
}
