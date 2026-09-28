import { useCallback, useEffect, useMemo, useState, type ElementType } from 'react'
import {
  AlertTriangle,
  BarChart3,
  ChevronDown,
  ChevronRight,
  CheckCircle,
  Clock,
  FileText,
  Gauge,
  Layers,
  RefreshCw,
  Save,
  Server,
  SlidersHorizontal,
  Target,
  Wifi,
  WifiOff,
  XCircle,
  Zap,
} from 'lucide-react'
import { AgentRuntimeSection } from '../agents/AgentRuntimeSection'
import { Card } from '../common/Card'
import { SectionTitle } from '../common/SectionTitle'
import { MatrixHeatmap, MetricTile } from '../common/Material'
import {
  DataSourceItem,
  DataSourceTestResult,
  getDataSourcesConfig,
  putDataSourcesConfig,
  testDataSourceConnection,
} from '../../api/configClient'
import {
  getMarketDataAdapterConfigs,
  getMarketDataAdapters,
  postAdapterHealth,
  putMarketDataAdapterConfig,
} from '../../api/agentRuntimeClient'
import type { DataSourceHealth, MarketDataAdapterConfig } from '../../types'
import { useToastStore } from '../../store/useToastStore'
import { roleAllows, useOperatorContext } from '../../store/operatorContext'

const SOURCE_ICONS: Record<string, ElementType> = {
  BarChart3,
  FileText,
  Gauge,
  Clock,
  Layers,
  Target,
}

function SourceIcon({ iconName }: { iconName: string }) {
  const Icon = SOURCE_ICONS[iconName] || FileText
  return <Icon size={16} />
}

function iconForSource(key: string) {
  if (key === 'realtime_quote') return 'BarChart3'
  if (key === 'kline_quote') return 'BarChart3'
  if (key === 'fundamentals') return 'FileText'
  if (key === 'announcements') return 'Clock'
  if (key === 'moneyflow') return 'Layers'
  if (key === 'macro') return 'Gauge'
  return 'Target'
}

const ADAPTER_CONFIG_HINTS: Record<string, { auth: string; runtime: string }> = {
  tushare: {
    auth: '使用 Tushare Token',
    runtime: '默认优先行情源',
  },
  akshare: {
    auth: '无需 Token',
    runtime: '本地 Python akshare 包，数据来自东方财富公开接口；安装东方财富客户端不会改变此状态',
  },
  sina: {
    auth: '无需 Token',
    runtime: '公开行情降级源',
  },
  tencent_finance: {
    auth: '按授权网关配置',
    runtime: '默认使用腾讯公开实时行情；历史、公告和资金流需配置 TENCENT_FINANCE_BASE_URL',
  },
  tongdaxin: {
    auth: '需要授权 Token',
    runtime: '配置 TONGDAXIN_BASE_URL 与 API_KEY/TOKEN 后参与行情链',
  },
  ifind: {
    auth: '需要 iFinD 授权',
    runtime: '配置 IFIND_BASE_URL 与 API_KEY/TOKEN 后参与行情链',
  },
}

const ADAPTER_PROVIDER_LABELS: Record<string, string> = {
  tushare: 'Tushare 官方',
  tencent_finance: '腾讯财经',
  tongdaxin: '通达信',
  ifind: '同花顺 iFinD',
  akshare: 'AkShare',
  sina: '新浪财经',
  mock: '模拟源',
}

const ADAPTER_CAPABILITY_LABELS: Record<string, string> = {
  REALTIME_QUOTE: '实时行情',
  HISTORICAL_QUOTE: '历史行情',
  FUNDAMENTALS: '基本面',
  ANNOUNCEMENTS: '公告',
  MONEYFLOW: '资金流',
  CHIP: '筹码',
  MACRO: '宏观',
  INDEX: '指数',
  BOND: '债券',
  FUTURES: '期货',
}

const TUSHARE_TIERS = [
  { id: 'realtime', label: '实时接口', hint: '实时行情能力，按接口形态单独校验。', keys: ['realtime_quote'] },
  { id: 'base', label: '120/2000 积分', hint: '股票日线、低频行情、公告和宏观数据。K线日线通常低门槛，周线/月线按低频行情校验。', keys: ['kline_quote', 'announcements', 'macro'] },
  { id: 'finance', label: '5000 积分', hint: '三大报表等财务数据，权限不足时不参与基本面推断。', keys: ['fundamentals'] },
  { id: 'feature', label: '5000/10000 积分', hint: '资金流向、每日筹码及胜率、每日筹码分布等特色数据，以账号实际权限为准。', keys: ['moneyflow', 'chip'] },
]

function formatSourceTestMessage(result: DataSourceTestResult) {
  if (result.diagnosis === 'TOKEN_OR_PERMISSION') {
    return result.message
  }
  if (result.key === 'macro' && /401|权限|积分|token/i.test(result.message)) {
    return '宏观指标接口需要单独的 Tushare 权限或积分；行情连接正常不代表 cn_cpi、cn_gdp、shibor_lpr 可用。请开通权限，或关闭宏观指标数据源。'
  }
  return result.message
}

function adapterInstallLabel(adapter: DataSourceHealth) {
  if (adapter.installed) return 'Python 包已安装'
  if (adapter.adapterId === 'akshare') return '缺少 akshare Python 包'
  if (adapter.adapterId === 'tushare') return '缺少 tushare Python 包'
  if (['tencent_finance', 'tongdaxin', 'ifind'].includes(adapter.adapterId)) return '授权网关未就绪'
  return '缺少本地依赖'
}

function adapterProviderLabel(value: unknown) {
  const raw = String(value || '').trim()
  if (!raw) return '未知来源'
  return ADAPTER_PROVIDER_LABELS[raw.toLowerCase()] ?? raw
}

function adapterDisplayLabel(adapter: DataSourceHealth) {
  const raw = String(adapter.label || '').trim()
  const map: Record<string, string> = {
    'Tushare (官方)': 'Tushare（官方）',
    'AkShare (东方财富)': 'AkShare（东方财富）',
  }
  return map[raw] ?? (raw || adapterProviderLabel(adapter.provider || adapter.adapterId))
}

function adapterCapabilityLabel(value: string) {
  const raw = String(value || '').trim()
  if (!raw) return '未知能力'
  return ADAPTER_CAPABILITY_LABELS[raw.toUpperCase()] ?? raw
}

function localizeAdapterMessage(value: unknown) {
  const raw = String(value || '').trim()
  if (!raw || raw === 'OK') return ''
  const timeout = raw.match(/^health check timed out after\s+(\d+)s\.?$/i)
  if (timeout) return `健康检查 ${timeout[1]} 秒后超时。`
  const realtimeFallback = raw.match(/^Realtime unavailable fallback to\s+([a-z0-9_-]+)\.?$/i)
  if (realtimeFallback) return `实时行情不可用，已回退到 ${adapterProviderLabel(realtimeFallback[1])}。`
  const map: Record<string, string> = {
    'akshare package is not installed': '当前后端 Python 环境未安装 akshare 包；东方财富是数据来源，不是本地依赖。',
    'Tushare token is missing': '未配置 Tushare Token。',
    'Adapter metadata only; run an explicit health check for upstream status.': '当前仅显示适配器元数据；点击“检测”可确认上游状态。',
    'Partially usable: upstream reachable, realtime quote unavailable': '部分可用：上游可达，但实时行情不可用。',
    'Upstream not healthy': '上游状态不健康。',
    'Live data usable': '实时数据可用。',
    'Adapter disabled': '适配器已禁用。',
    'health check failed': '健康检查失败。',
  }
  return map[raw] ?? raw
}

function adapterMessageLabel(adapter: DataSourceHealth) {
  return localizeAdapterMessage(adapter.message)
}

function adapterIsMetadataOnly(adapter: DataSourceHealth) {
  return adapter.healthCheckMode === 'metadata'
}

function adapterUpstreamHealthy(adapter: DataSourceHealth) {
  return adapter.upstreamHealthy ?? adapter.healthy
}

function adapterLiveUsable(adapter: DataSourceHealth) {
  return adapter.liveDataUsable ?? adapter.healthy
}

function adapterFallbackUsable(adapter: DataSourceHealth) {
  return Boolean(adapter.fallbackUsed && adapterLiveUsable(adapter))
}

function adapterPartialUsable(adapter: DataSourceHealth) {
  return adapterUpstreamHealthy(adapter) && !adapterLiveUsable(adapter)
}

function adapterReadinessLabel(adapter: DataSourceHealth) {
  if (!adapter.enabled) return '适配器已禁用'
  if (!adapter.installed) return adapterInstallLabel(adapter)
  if (adapterIsMetadataOnly(adapter)) {
    return adapterMessageLabel(adapter) || '尚未执行适配器健康检查。'
  }
  if (adapterFallbackUsable(adapter)) return adapterMessageLabel(adapter) || '实时数据降级可用'
  if (adapterLiveUsable(adapter)) return '实时数据可用'
  const message = adapterMessageLabel(adapter)
  const lastError = localizeAdapterMessage(adapter.lastError)
  if (adapterPartialUsable(adapter)) {
    return message || lastError || '部分可用：上游可达，但实时行情不可用。'
  }
  return message || lastError || '上游状态不健康'
}

function adapterCapabilities(adapter: DataSourceHealth) {
  return Array.isArray(adapter.capabilities) ? adapter.capabilities : []
}

function sourceProviderSummary(source: DataSourceItem) {
  const providers = source.providers?.length ? source.providers : Object.keys(source.provider_apis || {})
  return providers.length ? providers.join(' / ') : 'tushare'
}

function sourcePrimaryApi(source: DataSourceItem) {
  return source.provider_apis?.tushare || source.tushare_api
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error || '未知错误')
}

export function SettingsPage() {
  const [token, setToken] = useState('')
  const [tokenMask, setTokenMask] = useState<string | null>(null)
  const [tokenSet, setTokenSet] = useState(false)
  const [sources, setSources] = useState<DataSourceItem[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
  const [testResults, setTestResults] = useState<Record<string, DataSourceTestResult>>({})
  const [testingKey, setTestingKey] = useState<string | null>(null)
  const [expandedSourceGroupIds, setExpandedSourceGroupIds] = useState<Set<string>>(() => new Set(['realtime']))
  const [adapters, setAdapters] = useState<DataSourceHealth[]>([])
  const [adapterConfigs, setAdapterConfigs] = useState<Record<string, MarketDataAdapterConfig>>({})
  const [expandedAdapterId, setExpandedAdapterId] = useState<string | null>(null)
  const [adaptersLoading, setAdaptersLoading] = useState(false)
  const [adapterLoadError, setAdapterLoadError] = useState<string | null>(null)
  const [checkingAdapter, setCheckingAdapter] = useState<string | null>(null)
  const [savingAdapterId, setSavingAdapterId] = useState<string | null>(null)
  const addToast = useToastStore((s) => s.addToast)
  const operator = useOperatorContext()
  const canManageSettingsConfig = roleAllows(operator.role, 'admin')
  const canRunSettingsChecks = roleAllows(operator.role, 'operator')
  const configWriteDisabledReason = canManageSettingsConfig
    ? undefined
    : `设置页数据源和适配器配置写入需要 admin 权限。当前角色：${operator.role}。`
  const activeCheckDisabledReason = canRunSettingsChecks
    ? undefined
    : `设置页实时数据源和适配器检测需要 operator 权限。当前角色：${operator.role}。`
  const dataSourceSaveDisabled = saving || !canManageSettingsConfig
  const adapterRefreshDisabled = adaptersLoading || !canRunSettingsChecks

  const loadConfig = useCallback(async () => {
    setLoading(true)
    try {
      const config = await getDataSourcesConfig()
      setToken('')
      setTokenMask(config.tushare_token_mask || null)
      setTokenSet(Boolean(config.tushare_token_set))
      setSources(config.sources || [])
    } catch {
      setMessage({ type: 'error', text: '加载数据源配置失败，请确认后端服务已启动。' })
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadConfig()
  }, [loadConfig])

  useEffect(() => {
    loadAdapters()
  }, [])

  const loadAdapters = async () => {
    setAdaptersLoading(true)
    setAdapterLoadError(null)
    try {
      const [listResult, configResult] = await Promise.allSettled([
        getMarketDataAdapters(),
        getMarketDataAdapterConfigs(),
      ])
      const errors: string[] = []
      if (listResult.status === 'fulfilled') {
        setAdapters(listResult.value)
      } else {
        errors.push(`适配器状态加载失败：${errorMessage(listResult.reason)}`)
      }
      if (configResult.status === 'fulfilled') {
        setAdapterConfigs(Object.fromEntries(configResult.value.map((config) => [config.adapter_id, config])))
      } else {
        errors.push(`适配器配置加载失败：${errorMessage(configResult.reason)}`)
      }
      setAdapterLoadError(errors.length ? errors.join('；') : null)
    } catch (error) {
      setAdapterLoadError(`适配器加载失败：${errorMessage(error)}`)
    } finally {
      setAdaptersLoading(false)
    }
  }

  function guardSettingsConfigWrite(action: string) {
    if (canManageSettingsConfig) return true
    const reason = `${action}需要 admin 权限。当前角色：${operator.role}。`
    setMessage({ type: 'error', text: reason })
    addToast(reason, 'error')
    return false
  }

  function guardSettingsActiveCheck(action: string) {
    if (canRunSettingsChecks) return true
    const reason = `${action}需要 operator 权限。当前角色：${operator.role}。`
    setAdapterLoadError(reason)
    addToast(reason, 'error')
    return false
  }

  const handleCheckAdapter = async (adapterId: string) => {
    if (!guardSettingsActiveCheck('适配器健康检查')) return
    setCheckingAdapter(adapterId)
    try {
      const health = await postAdapterHealth(adapterId)
      setAdapters((prev) => prev.map((a) => (a.adapterId === adapterId ? health : a)))
      const healthMessage = adapterMessageLabel(health)
      if (health.healthy && adapterFallbackUsable(health)) {
        addToast(`${health.label || adapterId} 降级可用：${healthMessage || '主源不可用，已启用降级源。'}`, 'warning')
      } else if (health.healthy && adapterLiveUsable(health)) {
        addToast(`${health.label || adapterId} 健康 (${health.latencyAvgMs}ms)`, 'success')
      } else if (health.healthy) {
        addToast(`${health.label || adapterId} 部分可用：${healthMessage || '上游可达，但实时行情不可用。'}`, 'warning')
      } else {
        addToast(`${health.label || adapterId} 不健康：${healthMessage || '上游状态不健康。'}`, 'error')
      }
    } catch {
      addToast(`${adapterId} 健康检查失败`, 'error')
    } finally {
      setCheckingAdapter(null)
    }
  }

  const handleCheckAllAdapters = async () => {
    if (!guardSettingsActiveCheck('刷新全部适配器')) return
    setAdaptersLoading(true)
    setAdapterLoadError(null)
    try {
      const [listResult, configResult] = await Promise.allSettled([
        getMarketDataAdapters({ liveCheck: true }),
        getMarketDataAdapterConfigs(),
      ])
      const errors: string[] = []
      if (listResult.status === 'fulfilled') {
        setAdapters(listResult.value)
      } else {
        errors.push(`适配器状态加载失败：${errorMessage(listResult.reason)}`)
      }
      if (configResult.status === 'fulfilled') {
        setAdapterConfigs(Object.fromEntries(configResult.value.map((config) => [config.adapter_id, config])))
      } else {
        errors.push(`适配器配置加载失败：${errorMessage(configResult.reason)}`)
      }
      if (errors.length) {
        const nextError = errors.join('；')
        setAdapterLoadError(nextError)
        addToast(nextError, 'warning')
        return
      }
      addToast('适配器状态已刷新', 'success')
    } catch (error) {
      const nextError = `刷新适配器状态失败: ${errorMessage(error)}`
      setAdapterLoadError(nextError)
      addToast(nextError, 'error')
    } finally {
      setAdaptersLoading(false)
    }
  }

  const handleAdapterConfigChange = (adapterId: string, patch: Partial<MarketDataAdapterConfig>) => {
    if (!canManageSettingsConfig) return
    setAdapterConfigs((prev) => {
      const current = prev[adapterId]
      if (!current) return prev
      return {
        ...prev,
        [adapterId]: { ...current, ...patch },
      }
    })
  }

  const handleSaveAdapterConfig = async (adapterId: string) => {
    if (!guardSettingsConfigWrite('保存适配器配置')) return
    const config = adapterConfigs[adapterId]
    if (!config) return

    setSavingAdapterId(adapterId)
    try {
      const saved = await putMarketDataAdapterConfig(adapterId, {
        enabled: config.enabled,
        priority: config.priority,
        timeout_seconds: config.timeout_seconds,
      })
      setAdapterConfigs((prev) => ({ ...prev, [adapterId]: saved }))
      const nextAdapters = await getMarketDataAdapters()
      setAdapters(nextAdapters)
      addToast(`${saved.label || adapterId} 配置已保存`, 'success')
    } catch (error) {
      addToast(`保存适配器配置失败: ${error instanceof Error ? error.message : '未知错误'}`, 'error')
    } finally {
      setSavingAdapterId(null)
    }
  }

  const handleToggle = (index: number) => {
    if (!canManageSettingsConfig) return
    setSources((prev) => prev.map((source, i) => (i === index ? { ...source, enabled: !source.enabled } : source)))
  }

  const toggleSourceGroup = (groupId: string) => {
    setExpandedSourceGroupIds((prev) => {
      const next = new Set(prev)
      if (next.has(groupId)) {
        next.delete(groupId)
      } else {
        next.add(groupId)
      }
      return next
    })
  }

  const handleSave = async () => {
    if (!guardSettingsConfigWrite('保存数据源配置')) return
    setSaving(true)
    setMessage(null)
    try {
      const nextToken = token.trim()
      await putDataSourcesConfig(nextToken || undefined, sources)
      if (nextToken) {
        setTokenMask(nextToken.length > 8 ? `${nextToken.slice(0, 4)}...${nextToken.slice(-4)}` : '*'.repeat(nextToken.length))
        setTokenSet(true)
        setToken('')
      }
      setMessage({ type: 'success', text: '数据源配置已保存。Token 已同步至行情数据配置，下次运行任务时生效。' })
      addToast('数据源配置保存成功', 'success')
    } catch {
      setMessage({ type: 'error', text: '保存失败，请重试。' })
      addToast('保存失败，请重试', 'error')
    } finally {
      setSaving(false)
    }
  }

  const handleTest = async (key: string) => {
    if (!guardSettingsActiveCheck('数据源连接测试')) return
    setTestingKey(key)
    try {
      const result = await testDataSourceConnection(key)
      setTestResults((prev) => ({ ...prev, [key]: result }))
      if (result.status === 'READY') {
        addToast(`${result.name} 连接成功 (${result.latency_ms}ms)`, 'success')
      } else {
        addToast(`${result.name} 连接失败: ${formatSourceTestMessage(result)}`, 'error')
      }
    } catch (error) {
      addToast(`测试失败: ${error instanceof Error ? error.message : '未知错误'}`, 'error')
    } finally {
      setTestingKey(null)
    }
  }

  const maskedToken = token ? (token.length > 8 ? `${token.slice(0, 4)}...${token.slice(-4)}` : '*'.repeat(token.length)) : tokenMask
  const enabledCount = sources.filter((source) => source.enabled).length
  const sourceGroups = useMemo(() => {
    const indexed = sources.map((source, index) => ({ source, index }))
    const used = new Set<string>()
    const groups = TUSHARE_TIERS.map((tier) => {
      const items = indexed.filter((item) => tier.keys.includes(item.source.key))
      items.forEach((item) => used.add(item.source.key))
      return { ...tier, items }
    }).filter((group) => group.items.length > 0)
    const otherItems = indexed.filter((item) => !used.has(item.source.key))
    if (otherItems.length > 0) {
      groups.push({ id: 'other', label: '其他接口', hint: '未归入当前积分表的扩展接口。', keys: [], items: otherItems })
    }
    return groups
  }, [sources])
  const sourceMatrixRows = sourceGroups.map((group) => {
    const total = group.items.length || 1
    const enabled = group.items.filter((item) => item.source.enabled).length
    const ready = group.items.filter((item) => testResults[item.source.key]?.status === 'READY').length
    const failed = group.items.filter((item) => testResults[item.source.key]?.status === 'FAILED').length
    return {
      label: group.label,
      cells: [
        { label: '启用', value: enabled / total, helper: `${enabled}/${group.items.length}` },
        { label: 'READY', value: ready / total, helper: `${ready} recent` },
        { label: 'FAILED', value: failed / total, helper: `${failed} recent` },
        { label: '覆盖', value: group.items.length > 0 ? 1 : 0, helper: group.id },
      ],
    }
  })
  const adapterMatrixRows = adapters.length ? [{
    label: '适配器',
    cells: [
      { label: '启用', value: adapters.filter((adapter) => adapter.enabled).length / adapters.length, helper: `${adapters.filter((adapter) => adapter.enabled).length}/${adapters.length}` },
      { label: '已安装', value: adapters.filter((adapter) => adapter.installed).length / adapters.length, helper: `${adapters.filter((adapter) => adapter.installed).length}/${adapters.length}` },
      { label: '实时可用', value: adapters.filter(adapterLiveUsable).length / adapters.length, helper: `${adapters.filter(adapterLiveUsable).length}/${adapters.length}` },
      { label: '待检测', value: adapters.filter((adapter) => adapterIsMetadataOnly(adapter) && adapter.enabled && adapter.installed).length / adapters.length, helper: `${adapters.filter((adapter) => adapterIsMetadataOnly(adapter) && adapter.enabled && adapter.installed).length}/${adapters.length}` },
    ],
  }] : []

  return (
    <div className="space-y-6">
      <SectionTitle title="系统设置" subtitle="统一管理 API 配置、数据源连接、运行时路由" />

      <Card title="免责声明">
        <div className="text-sm leading-6 text-slate-600">
          本系统仅用于研究与测试，不提供交易建议，不连接真实交易账户，不触发实际下单。所有输出均需人工确认。
          This system is for research and testing only.
        </div>
      </Card>

      <AgentRuntimeSection />

      <div className="grid gap-3 md:grid-cols-2">
        <div className="rounded-md border border-slate-200 bg-white px-4 py-3 text-xs text-slate-500">
          <span data-testid="settings-data-source-config-role">
            角色：{operator.role}；设置配置写入：{canManageSettingsConfig ? 'admin' : '已阻断'}
          </span>
          {!canManageSettingsConfig ? (
            <span data-testid="settings-data-source-config-disabled-reason" className="ml-3 text-amber-700">
              {configWriteDisabledReason}
            </span>
          ) : null}
        </div>
        <div className="rounded-md border border-slate-200 bg-white px-4 py-3 text-xs text-slate-500">
          <span data-testid="settings-data-source-check-role">
            角色：{operator.role}；设置主动检查：{canRunSettingsChecks ? 'operator+' : '已阻断'}
          </span>
          {!canRunSettingsChecks ? (
            <span data-testid="settings-data-source-check-disabled-reason" className="ml-3 text-amber-700">
              {activeCheckDisabledReason}
            </span>
          ) : null}
        </div>
      </div>

      <Card title="数据源配置">
        {loading ? (
          <div className="flex items-center gap-3 py-4 text-sm text-slate-500">
            <RefreshCw size={16} className="animate-spin" />
            正在读取配置...
          </div>
        ) : (
          <div className="space-y-6">
            <div className="grid gap-3 md:grid-cols-3">
              <MetricTile className="!rounded-lg !p-3 !shadow-none" label="启用数据源" value={`${enabledCount}/${sources.length}`} helper="配置矩阵覆盖所有 Tushare 分层接口" tone="info" />
              <MetricTile className="!rounded-lg !p-3 !shadow-none" label="Token 状态" value={token.trim() ? '待保存' : tokenSet ? '已配置' : '未配置'} helper={maskedToken || '无脱敏标记'} tone={tokenSet || token.trim() ? 'success' : 'warning'} />
              <MetricTile className="!rounded-lg !p-3 !shadow-none" label="主动检查" value={canRunSettingsChecks ? 'operator+' : '已阻断'} helper={`当前角色：${operator.role}`} tone={canRunSettingsChecks ? 'success' : 'warning'} />
            </div>
            <div className="rounded-md border border-slate-200 bg-slate-50 p-4">
              <div className="mb-1 text-xs font-medium text-slate-500">Tushare Token</div>
              <div className="flex items-center gap-3">
                <input
                  data-testid="settings-data-source-token-input"
                  type="password"
                  value={token}
                  onChange={(event) => setToken(event.target.value)}
                  disabled={!canManageSettingsConfig}
                  title={configWriteDisabledReason}
                  placeholder={tokenSet ? '已保存 token；留空保存会沿用旧 token' : '在此粘贴 tushare token（https://tushare.pro 获取）'}
                  className="flex-1 rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm text-slate-900 outline-none transition focus:border-slate-400 disabled:cursor-not-allowed disabled:opacity-60"
                />
                {maskedToken && (
                  <span className="whitespace-nowrap rounded bg-slate-200 px-2 py-1 text-xs text-slate-600">
                    {maskedToken}
                  </span>
                )}
              </div>
              <div className="mt-2 text-xs text-slate-400">
                一个 token 统一用于以下所有 tushare 数据源。可在
                <a href="https://tushare.pro" target="_blank" rel="noreferrer" className="mx-1 text-cyan-600 underline">
                  tushare.pro
                </a>
                注册获取。
              </div>
              <div className="mt-3 grid gap-2 text-xs sm:grid-cols-3">
                <div className="rounded-md border border-slate-200 bg-white px-3 py-2 text-slate-600">
                  Token 状态：{token.trim() ? '本次输入待保存，仅密码框持有' : tokenSet ? `已配置，当前只显示脱敏标记 ${tokenMask ?? 'set'}` : '未配置'}
                </div>
                <div className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-emerald-700">
                  明文处理：输入框不会回填后端明文，保存后会清空本次输入。
                </div>
                <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-amber-800">
                  自定义行情 base_url 请在上方 Agent runtime 中配置；生产 strict 模式会触发白名单/确认校验。
                </div>
              </div>
            </div>

            <div>
              <div className="mb-3 flex items-center justify-between">
                <div>
                  <div className="text-sm font-medium text-slate-700">
                    数据源开关（{enabledCount}/{sources.length} 已启用）
                  </div>
                  <div className="mt-1 text-xs text-slate-400">
                    测试按钮继续验证 Tushare 兼容接口；腾讯财经、通达信、iFinD 通过授权网关健康检查和适配器 fallback 直接参与个股分析。
                  </div>
                </div>
              </div>
              {sourceMatrixRows.length > 0 ? (
                <div className="mb-4 rounded-lg border border-slate-200 bg-white p-3">
                  <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500">数据源配置矩阵</div>
                  <MatrixHeatmap rows={sourceMatrixRows} />
                </div>
              ) : null}
              <div className="space-y-4">
                {sourceGroups.map((group) => {
                  const expanded = expandedSourceGroupIds.has(group.id)
                  const panelId = `source-group-panel-${group.id}`
                  const enabledInGroup = group.items.filter((item) => item.source.enabled).length
                  const readyCount = group.items.filter((item) => testResults[item.source.key]?.status === 'READY').length
                  const failedCount = group.items.filter((item) => testResults[item.source.key]?.status === 'FAILED').length

                  return (
                  <div key={group.id} className="rounded-md border border-slate-200 bg-slate-50/70 p-3">
                    <button
                      type="button"
                      onClick={() => toggleSourceGroup(group.id)}
                      aria-controls={panelId}
                      aria-expanded={expanded}
                      className="mb-3 flex w-full flex-col gap-3 rounded-md px-2 py-2 text-left transition hover:bg-white/70 sm:flex-row sm:items-start sm:justify-between"
                    >
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-xs font-semibold text-slate-800">{group.label}</span>
                          <span
                            className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                              group.id === 'realtime'
                                ? 'bg-emerald-100 text-emerald-700'
                                : expanded
                                  ? 'bg-cyan-50 text-cyan-700'
                                  : 'bg-slate-200 text-slate-600'
                            }`}
                          >
                            {group.id === 'realtime' ? '核心配置' : expanded ? '已展开' : '已折叠'}
                          </span>
                        </div>
                        <div className="mt-0.5 text-[11px] leading-relaxed text-slate-500">{group.hint}</div>
                      </div>
                      <div className="flex shrink-0 flex-wrap items-center gap-2">
                        <span className="rounded bg-white px-2 py-1 text-[10px] font-medium text-slate-500">
                          {enabledInGroup}/{group.items.length} 已启用
                        </span>
                        {(readyCount > 0 || failedCount > 0) && (
                          <span
                            className={`rounded px-2 py-1 text-[10px] font-medium ${
                              failedCount > 0 ? 'bg-red-50 text-red-600' : 'bg-emerald-50 text-emerald-700'
                            }`}
                          >
                            测试 {readyCount} 通过 / {failedCount} 失败
                          </span>
                        )}
                        <span className="inline-flex items-center gap-1 rounded border border-slate-200 bg-white px-2 py-1 text-[10px] font-medium text-slate-600">
                          {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                          {expanded ? '收起' : '展开'}
                        </span>
                      </div>
                    </button>
                    <div id={panelId}>
                    {!expanded && (
                      <div className="flex flex-wrap gap-2 px-2 pb-1">
                        {group.items.slice(0, 4).map(({ source }) => (
                          <span
                            key={source.key}
                            className={`rounded border px-2 py-1 text-[11px] ${
                              source.enabled
                                ? 'border-emerald-100 bg-white text-emerald-700'
                                : 'border-slate-200 bg-white text-slate-500'
                            }`}
                          >
                            {source.name} · {source.enabled ? '已启用' : '已关闭'}
                          </span>
                        ))}
                        {group.items.length > 4 && (
                          <span className="rounded border border-slate-200 bg-white px-2 py-1 text-[11px] text-slate-500">
                            +{group.items.length - 4} 项
                          </span>
                        )}
                      </div>
                    )}
                    {expanded && (
                      <div className="space-y-2">
                        {group.items.map(({ source, index }) => (
                          <div
                            key={source.key}
                            className={`flex items-center gap-4 rounded-md border px-4 py-3 transition ${
                              source.enabled ? 'border-emerald-200 bg-emerald-50/40' : 'border-slate-200 bg-white'
                            }`}
                          >
                            <div
                              className={`grid h-9 w-9 shrink-0 place-items-center rounded-md ${
                                source.enabled ? 'bg-emerald-100 text-emerald-600' : 'bg-slate-100 text-slate-400'
                              }`}
                            >
                              <SourceIcon iconName={iconForSource(source.key)} />
                            </div>
                            <div className="min-w-0 flex-1">
                              <div className="flex items-center gap-2">
                                <span className="text-sm font-semibold text-slate-900">{source.name}</span>
                                <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-500">
                                  {sourcePrimaryApi(source)}
                                </span>
                                <span className="rounded bg-indigo-50 px-1.5 py-0.5 text-[10px] font-medium text-indigo-700">
                                  {sourceProviderSummary(source)}
                                </span>
                                {source.tier_label && (
                                  <span className="rounded bg-cyan-50 px-1.5 py-0.5 text-[10px] font-medium text-cyan-700">
                                    {source.tier_label}
                                  </span>
                                )}
                              </div>
                              <div className="mt-0.5 text-xs leading-relaxed text-slate-500">{source.description}</div>
                              {testResults[source.key] && (
                                <div
                                  className={`mt-1 text-[11px] leading-relaxed ${
                                    testResults[source.key]?.status === 'READY' ? 'text-emerald-700' : 'text-red-600'
                                  }`}
                                >
                                  {testResults[source.key]?.status === 'READY'
                                    ? `最近测试：连接成功，返回 ${testResults[source.key]?.record_count ?? 0} 条记录`
                                    : `最近测试：${formatSourceTestMessage(testResults[source.key]!)}`
                                  }
                                </div>
                              )}
                            </div>
                            <div className="flex items-center gap-2">
                              {source.enabled && testResults[source.key]?.status === 'READY' && (
                                <CheckCircle size={14} className="text-emerald-500" />
                              )}
                              {source.enabled && testResults[source.key]?.status === 'FAILED' && (
                                <XCircle size={14} className="text-red-500" />
                              )}
                              {source.enabled ? (
                                <Wifi size={14} className="text-emerald-500" />
                              ) : (
                                <WifiOff size={14} className="text-slate-300" />
                              )}
                              <button
                                data-testid={`settings-data-source-test-${source.key}`}
                                onClick={() => handleTest(source.key)}
                                disabled={testingKey === source.key || !source.enabled || !canRunSettingsChecks}
                                title={activeCheckDisabledReason}
                                className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-2 py-1 text-[10px] font-medium text-slate-600 transition hover:bg-slate-50 disabled:opacity-40"
                              >
                                {testingKey === source.key ? <RefreshCw size={10} className="animate-spin" /> : <Zap size={10} />}
                                测试
                              </button>
                              <label className="relative inline-flex cursor-pointer items-center">
                                <input
                                  data-testid={`settings-data-source-toggle-${source.key}`}
                                  type="checkbox"
                                  checked={source.enabled}
                                  onChange={() => handleToggle(index)}
                                  disabled={!canManageSettingsConfig}
                                  title={configWriteDisabledReason}
                                  className="peer sr-only"
                                />
                                <div className="h-5 w-9 rounded-full bg-slate-200 after:absolute after:left-[2px] after:top-[2px] after:h-4 after:w-4 after:rounded-full after:bg-white after:transition peer-checked:bg-emerald-500 peer-checked:after:translate-x-4" />
                              </label>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                    </div>
                  </div>
                  )
                })}
              </div>
            </div>

            {message && (
              <div
                className={`flex items-center gap-2 rounded-md px-4 py-2.5 text-sm ${
                  message.type === 'success'
                    ? 'border border-emerald-200 bg-emerald-50 text-emerald-700'
                    : 'border border-red-200 bg-red-50 text-red-700'
                }`}
              >
                {message.type === 'error' ? <AlertTriangle size={14} /> : null}
                {message.text}
              </div>
            )}

            <button
              data-testid="settings-data-source-save"
              onClick={handleSave}
              disabled={dataSourceSaveDisabled}
              title={configWriteDisabledReason}
              className="inline-flex items-center gap-2 rounded-lg bg-slate-900 px-5 py-2.5 text-sm font-medium text-white transition hover:bg-slate-800 disabled:opacity-50"
            >
              <Save size={16} />
              {saving ? '保存中...' : '保存配置'}
            </button>
          </div>
        )}
      </Card>

      <Card title="数据源适配器状态">
        <div className="flex items-center justify-between mb-3">
          <span className="text-xs text-slate-500">
            适配器降级优先级：Tushare 官方 → 腾讯财经 → 通达信 → 同花顺 iFinD → AkShare → 新浪财经 → 模拟源
          </span>
          <button
            data-testid="settings-adapter-refresh-all"
            onClick={handleCheckAllAdapters}
            disabled={adapterRefreshDisabled}
            title={activeCheckDisabledReason}
            className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-2 py-1 text-[10px] font-medium text-slate-600 transition hover:bg-slate-50 disabled:opacity-40"
          >
            <RefreshCw size={10} className={adaptersLoading ? 'animate-spin' : ''} />
            刷新全部
          </button>
        </div>
        {adapterLoadError && !adaptersLoading && (
          <div data-testid="settings-adapter-load-error" className="mb-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
            {adapterLoadError}
          </div>
        )}
        {adapters.length === 0 && !adaptersLoading && !adapterLoadError && (
          <div data-testid="settings-adapter-empty-state" className="py-3 text-sm text-slate-400">尚未检测到任何数据适配器</div>
        )}
        {adaptersLoading && (
          <div data-testid="settings-adapter-loading" className="flex items-center gap-2 py-3 text-sm text-slate-400">
            <RefreshCw size={14} className="animate-spin" />
            加载中...
          </div>
        )}
        {adapterMatrixRows.length > 0 ? (
          <div className="mb-4 rounded-lg border border-slate-200 bg-white p-3">
            <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500">适配器运行健康矩阵</div>
            <MatrixHeatmap rows={adapterMatrixRows} />
          </div>
        ) : null}
        <div data-testid="settings-adapter-list" className="space-y-2">
          {adapters.map((adapter) => {
            const config = adapterConfigs[adapter.adapterId]
            const capabilities = adapterCapabilities(adapter)
            const upstreamHealthy = adapterUpstreamHealthy(adapter)
            const liveUsable = adapterLiveUsable(adapter)
            const fallbackUsable = adapterFallbackUsable(adapter)
            const partialUsable = adapterPartialUsable(adapter)
            const metadataOnly = adapterIsMetadataOnly(adapter)
            const hint = ADAPTER_CONFIG_HINTS[adapter.adapterId] || {
              auth: config?.requires_token ? '需要密钥' : '无需 Token',
              runtime: '自定义适配器',
            }
            const expanded = expandedAdapterId === adapter.adapterId
            return (
              <div
                key={adapter.adapterId}
                className={`rounded-md border ${
                  !adapter.enabled || !adapter.installed
                    ? 'border-slate-200 bg-slate-50'
                    : fallbackUsable
                    ? 'border-amber-200 bg-amber-50/30'
                    : liveUsable
                    ? 'border-emerald-200 bg-emerald-50/30'
                    : metadataOnly
                    ? 'border-slate-200 bg-slate-50/40'
                    : upstreamHealthy
                    ? 'border-amber-200 bg-amber-50/30'
                    : 'border-red-200 bg-red-50/30'
                }`}
              >
                <div className="flex items-center gap-3 px-3 py-2">
                  <div
                    className={`grid h-7 w-7 shrink-0 place-items-center rounded ${
                      !adapter.enabled || !adapter.installed
                        ? 'bg-slate-200 text-slate-400'
                        : fallbackUsable
                        ? 'bg-amber-100 text-amber-600'
                        : liveUsable
                        ? 'bg-emerald-100 text-emerald-600'
                        : metadataOnly
                        ? 'bg-slate-100 text-slate-500'
                        : upstreamHealthy
                        ? 'bg-amber-100 text-amber-600'
                        : 'bg-red-100 text-red-600'
                    }`}
                  >
                    <Server size={13} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className={`text-sm font-semibold ${!adapter.enabled || !adapter.installed ? 'text-slate-400' : 'text-slate-900'}`}>
                        {adapterDisplayLabel(adapter)}
                      </span>
                      <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-500">
                        {adapterProviderLabel(adapter.provider || adapter.adapterId)}
                      </span>
                      {config && (
                        <>
                          <span className="rounded bg-white px-1.5 py-0.5 text-[10px] font-medium text-slate-500">
                            优先级 {config.priority}
                          </span>
                          <span className="rounded bg-white px-1.5 py-0.5 text-[10px] font-medium text-slate-500">
                            {config.timeout_seconds} 秒
                          </span>
                        </>
                      )}
                      {liveUsable && (
                        <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-medium text-emerald-700">
                          {adapter.latencyAvgMs}ms
                        </span>
                      )}
                      {fallbackUsable && (
                        <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-700">
                          降级可用
                        </span>
                      )}
                      {partialUsable && (
                        <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-700">
                          部分可用
                        </span>
                      )}
                      {metadataOnly && adapter.enabled && adapter.installed && (
                        <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-600">
                          待检测
                        </span>
                      )}
                      {!adapter.enabled && (
                        <span className="rounded bg-slate-200 px-1.5 py-0.5 text-[10px] font-medium text-slate-500">
                          已禁用
                        </span>
                      )}
                      {!adapter.installed && (
                        <span className="rounded bg-slate-200 px-1.5 py-0.5 text-[10px] font-medium text-slate-500">
                          {adapterInstallLabel(adapter)}
                        </span>
                      )}
                    </div>
                    <div className="mt-0.5 flex flex-wrap gap-1">
                      {capabilities.slice(0, 5).map((cap) => (
                        <span key={cap} className="rounded border border-slate-100 bg-white px-1 py-0.5 text-[9px] text-slate-500">
                          {adapterCapabilityLabel(cap)}
                        </span>
                      ))}
                      {capabilities.length > 5 && (
                        <span className="text-[9px] text-slate-400">+{capabilities.length - 5} 项</span>
                      )}
                      {capabilities.length === 0 && (
                        <span className="text-[9px] text-slate-400">未声明能力</span>
                      )}
                    </div>
                    <div className="mt-1 text-[10px] text-slate-500">
                      {adapterReadinessLabel(adapter)}
                    </div>
                  </div>
                  <div className="flex items-center gap-1.5">
                    {fallbackUsable && <AlertTriangle size={12} className="text-amber-500" />}
                    {!fallbackUsable && liveUsable && <CheckCircle size={12} className="text-emerald-500" />}
                    {partialUsable && <AlertTriangle size={12} className="text-amber-500" />}
                    {metadataOnly && adapter.installed && adapter.enabled && <Clock size={12} className="text-slate-400" />}
                    {adapter.installed && adapter.enabled && !metadataOnly && !upstreamHealthy && <AlertTriangle size={12} className="text-amber-500" />}
                    <button
                      data-testid={`settings-adapter-config-toggle-${adapter.adapterId}`}
                      onClick={() => setExpandedAdapterId(expanded ? null : adapter.adapterId)}
                      className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-2 py-1 text-[10px] font-medium text-slate-600 transition hover:bg-slate-50"
                    >
                      <SlidersHorizontal size={10} />
                      配置
                    </button>
                    <button
                      data-testid={`settings-adapter-check-${adapter.adapterId}`}
                      onClick={() => handleCheckAdapter(adapter.adapterId)}
                      disabled={checkingAdapter === adapter.adapterId || !adapter.installed || !adapter.enabled || !canRunSettingsChecks}
                      title={activeCheckDisabledReason}
                      className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-2 py-1 text-[10px] font-medium text-slate-600 transition hover:bg-slate-50 disabled:opacity-40"
                    >
                      {checkingAdapter === adapter.adapterId ? <RefreshCw size={10} className="animate-spin" /> : <Zap size={10} />}
                      检测
                    </button>
                  </div>
                </div>

                {expanded && (
                  <div className="border-t border-slate-200/80 px-3 py-3">
                    {config ? (
                      <div className="space-y-3">
                        <div className="grid gap-3 md:grid-cols-[minmax(140px,1fr)_120px_120px_auto] md:items-end">
                          <label className="flex h-10 items-center gap-2 rounded-md border border-slate-200 bg-white px-3 text-sm text-slate-700">
                            <input
                              data-testid={`settings-adapter-enabled-${adapter.adapterId}`}
                              type="checkbox"
                              checked={config.enabled}
                              onChange={(event) => handleAdapterConfigChange(adapter.adapterId, { enabled: event.target.checked })}
                              disabled={!canManageSettingsConfig}
                              title={configWriteDisabledReason}
                              className="h-4 w-4 rounded border-slate-300"
                            />
                            启用适配器
                          </label>
                          <label className="space-y-1 text-xs text-slate-500">
                            <span className="font-medium">优先级</span>
                            <input
                              data-testid={`settings-adapter-priority-${adapter.adapterId}`}
                              type="number"
                              min={1}
                              max={99}
                              value={config.priority}
                              onChange={(event) => handleAdapterConfigChange(adapter.adapterId, { priority: Number(event.target.value) })}
                              disabled={!canManageSettingsConfig}
                              title={configWriteDisabledReason}
                              className="w-full rounded-md border border-slate-200 bg-white px-2 py-2 text-sm text-slate-900"
                            />
                          </label>
                          <label className="space-y-1 text-xs text-slate-500">
                            <span className="font-medium">超时秒</span>
                            <input
                              data-testid={`settings-adapter-timeout-${adapter.adapterId}`}
                              type="number"
                              min={3}
                              max={120}
                              value={config.timeout_seconds}
                              onChange={(event) => handleAdapterConfigChange(adapter.adapterId, { timeout_seconds: Number(event.target.value) })}
                              disabled={!canManageSettingsConfig}
                              title={configWriteDisabledReason}
                              className="w-full rounded-md border border-slate-200 bg-white px-2 py-2 text-sm text-slate-900"
                            />
                          </label>
                          <button
                            data-testid={`settings-adapter-save-config-${adapter.adapterId}`}
                            onClick={() => handleSaveAdapterConfig(adapter.adapterId)}
                            disabled={savingAdapterId === adapter.adapterId || !canManageSettingsConfig}
                            title={configWriteDisabledReason}
                            className="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-slate-900 px-4 text-sm font-medium text-white transition hover:bg-slate-800 disabled:opacity-50"
                          >
                            <Save size={14} />
                            {savingAdapterId === adapter.adapterId ? '保存中' : '保存'}
                          </button>
                        </div>
                        <div className="grid gap-2 text-xs text-slate-500 sm:grid-cols-3">
                          <div className="rounded-md border border-slate-200 bg-white px-3 py-2">
                            认证：{hint.auth}
                          </div>
                          <div className="rounded-md border border-slate-200 bg-white px-3 py-2">
                            运行：{hint.runtime}
                          </div>
                          <div className="rounded-md border border-slate-200 bg-white px-3 py-2">
                            安装：{adapterInstallLabel(adapter)}
                          </div>
                        </div>
                        {config.note && (
                          <div className="rounded-md border border-slate-200 bg-white px-3 py-2 text-xs text-slate-500">
                            {config.note}
                          </div>
                        )}
                      </div>
                    ) : (
                      <div className="text-xs text-slate-400">配置数据暂不可用，请刷新适配器状态。</div>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </Card>

      <Card title="版本信息">
        <div className="grid gap-3 sm:grid-cols-3">
          <MetricTile className="!rounded-lg !p-3 !shadow-none" label="前端版本" value="0.1.0" />
          <MetricTile className="!rounded-lg !p-3 !shadow-none" label="后端版本" value="0.2.0" />
          <MetricTile className="!rounded-lg !p-3 !shadow-none" label="已启用数据源" value={`${enabledCount}/${sources.length}`} tone="info" />
        </div>
      </Card>

      <Card title="开发支持">
        <div className="space-y-2 text-sm text-slate-600">
          <div>技术栈: React 18 / TypeScript / FastAPI / Tailwind / SQLite</div>
          <div>数据层: tushare + 腾讯财经/通达信/同花顺 iFinD 授权网关 + AkShare/Sina 降级</div>
          <div>交易边界: 禁用真实交易与自动下单</div>
        </div>
      </Card>
    </div>
  )
}
