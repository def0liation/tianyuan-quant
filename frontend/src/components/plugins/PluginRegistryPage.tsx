import { useCallback, useEffect, useState } from 'react'
import { Archive, CheckCircle2, Play, Power, RefreshCw, ShieldCheck, Upload } from 'lucide-react'
import {
  archivePlugin,
  cleanupPluginArtifacts,
  disablePlugin,
  enablePlugin,
  getPluginAudit,
  getPluginRuntimePlan,
  getPluginUsageHistory,
  getPluginUsageStats,
  listPlugins,
  runPluginSandbox,
  upgradePlugin,
  uploadPluginArtifact,
  validatePlugin,
} from '../../api/pluginClient'
import {
  PluginArtifactCleanupResult,
  PluginAuditItem,
  PluginArtifactUploadResult,
  PluginItem,
  PluginRuntimeAgentPlan,
  PluginRuntimePlan,
  PluginSandboxRunResult,
  PluginUsageHistoryBucket,
  PluginUsageHistoryResponse,
  PluginUsageStatsItem,
  PluginValidateResult,
} from '../../types'
import { Badge } from '../common/Badge'
import { Card } from '../common/Card'
import { SectionTitle } from '../common/SectionTitle'
import { EvidenceLedger, MetricTile } from '../common/Material'
import { roleAllows, useOperatorContext } from '../../store/operatorContext'

function messageOf(error: unknown) {
  return error instanceof Error ? error.message : '请求失败'
}

const PLUGIN_LABELS: Record<string, { name: string; description?: string }> = {
  technical_kline_readonly: {
    name: '技术 K 线只读 Agent',
    description: '只读技术分析插件示例，仅允许输出复核观察，不允许发出交易动作。',
  },
}

const AGENT_LABELS: Record<string, string> = {
  quant_core: '量化核心',
  technical_kline_analyst: '技术 K 线分析 Agent',
  'Technical K-line Analyst': '技术 K 线分析 Agent',
}

function pluginLabel(plugin: PluginItem) {
  return PLUGIN_LABELS[plugin.plugin_id]?.name || plugin.name || plugin.plugin_id
}

function pluginDescription(plugin: PluginItem) {
  return PLUGIN_LABELS[plugin.plugin_id]?.description || plugin.description
}

function agentLabel(agentId: unknown, fallback: unknown) {
  const id = String(agentId ?? '')
  const raw = String(fallback ?? (id || 'agent'))
  return AGENT_LABELS[id] || AGENT_LABELS[raw] || raw
}

function sourceLabel(source: string) {
  const labels: Record<string, string> = {
    builtin: '内置',
    filesystem: '文件系统',
    api: 'API',
    registry: '注册表',
  }
  return labels[source] || source
}

function actionLabel(action: string) {
  const labels: Record<string, string> = {
    REGISTER: '注册',
    ENABLE: '启用',
    DISABLE: '停用',
    VALIDATE: '校验',
    MIGRATE: '迁移',
    ARCHIVE: '归档',
    UPGRADE: '升级',
    SANDBOX_RUN: '沙箱运行',
    SANDBOX_BLOCK: '沙箱阻断',
  }
  labels.ARTIFACT_UPLOAD = '产物上传'
  return labels[action] || action
}

function auditIdLabel(entry: PluginAuditItem) {
  const suffix = entry.audit_id.split('_').pop() || entry.audit_id
  return `${actionLabel(entry.action)}-${suffix}`
}

function registryAgentLabel(agent: Record<string, any>) {
  return agentLabel(agent.agent_id, agent.name)
}

function gateLabel(gate: string) {
  const labels: Record<string, string> = {
    Risk: '风险门禁',
    DVG: 'DVG 门禁',
    Execution: '执行门禁',
    'Anti-Conclusion': '反结论门禁',
  }
  return labels[gate] || `${gate} 门禁`
}

function auditMessageLabel(entry: PluginAuditItem) {
  if (entry.message === 'Plugin manifest registered.') return '插件清单已注册。'
  if (entry.message === 'Builtin readonly plugin seeded.') return '内置只读插件已初始化。'
  if (entry.message === 'Builtin readonly plugin runtime contract refreshed.') return '内置只读插件运行时契约已刷新。'
  if (entry.message === 'Filesystem plugin discovered.') return '文件系统插件已发现。'
  if (entry.message === 'Plugin manifest validation completed.') return '插件清单校验已完成。'
  if (entry.message === 'Plugin enabled=true.') return '插件已启用。'
  if (entry.message === 'Plugin enabled=false.') return '插件已停用。'
  if (entry.message === 'Plugin archived and disabled.') return '插件已归档并停用。'
  if (entry.message === 'Plugin upgraded to a new version.') return '插件已升级到新版本。'

  if (entry.message === 'Plugin package artifact uploaded and sha256 verified.') return '插件包产物已上传并通过 sha256 校验。'

  const sandboxMatch = entry.message.match(/^Plugin sandbox run ([A-Z_]+) for agent (.+)\.$/)
  if (sandboxMatch) {
    return `插件沙箱运行 ${sandboxMatch[1]}，Agent：${agentLabel(sandboxMatch[2], sandboxMatch[2])}。`
  }

  return entry.message
}

function statusBadge(status: string) {
  if (status === 'READY' || status === 'PLANNED' || status === 'COMPLETED') return 'PASS'
  if (status === 'BLOCKED' || status === 'FAILED') return 'FAIL'
  if (status === 'EMPTY') return 'SKIPPED'
  return 'WAIT'
}

function boolBadge(value: boolean) {
  return value ? 'PASS' : 'FAIL'
}

function metricToneForBadge(value?: string): 'primary' | 'neutral' | 'success' | 'warning' | 'danger' | 'info' | 'data' {
  if (value === 'PASS') return 'success'
  if (value === 'WARN' || value === 'WAIT') return 'warning'
  if (value === 'FAIL' || value === 'BLOCKED') return 'danger'
  if (value === 'REVIEW_ONLY') return 'info'
  return 'neutral'
}

function resourceQuotaBadge(value: unknown) {
  const status = String(value ?? 'EMPTY').toUpperCase()
  if (status === 'OK') return 'PASS'
  if (status === 'WARN') return 'WARN'
  if (status === 'EMPTY') return 'SKIPPED'
  return 'WAIT'
}

function numberValue(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0
}

function formatBytes(value: unknown) {
  const bytes = numberValue(value)
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${bytes} B`
}

function usageForPlugin(stats: PluginUsageStatsItem[], pluginId?: string) {
  return stats.find((item) => item.plugin_id === pluginId)
}

function usageHistoryForPlugin(history: PluginUsageHistoryResponse | null, pluginId?: string): PluginUsageHistoryBucket[] {
  if (!history || !pluginId) return []
  return history.items.filter((item) => item.plugin_id === pluginId)
}

function nextPatchVersion(version: string) {
  const parts = version.split('.').map((part) => Number.parseInt(part, 10))
  if (parts.length >= 3 && parts.every((part) => Number.isFinite(part))) {
    return `${parts[0]}.${parts[1]}.${parts[2] + 1}`
  }
  if (parts.length === 2 && parts.every((part) => Number.isFinite(part))) {
    return `${parts[0]}.${parts[1]}.1`
  }
  return `${version || '0.1.0'}.1`
}

function verifiedPackageArtifact(plugin: PluginItem) {
  const artifact = plugin.manifest?.package_artifact
  if (
    artifact
    && typeof artifact === 'object'
    && artifact.artifact_type === 'uploaded_package'
    && artifact.verified === true
    && typeof artifact.checksum === 'string'
    && artifact.checksum.length > 0
  ) {
    return artifact as Record<string, any>
  }
  return null
}

function packageScanStatus(plugin: PluginItem) {
  const artifact = plugin.manifest?.package_artifact as Record<string, any> | undefined
  return String(plugin.package_scan_status || artifact?.scan_status || '')
}

function packageHashScanStatus(plugin: PluginItem) {
  const artifact = plugin.manifest?.package_artifact as Record<string, any> | undefined
  return String(plugin.package_hash_scan_status || artifact?.hash_scan_status || '')
}

function packageExternalScanStatus(plugin: PluginItem) {
  const artifact = plugin.manifest?.package_artifact as Record<string, any> | undefined
  return String(plugin.package_external_scan_status || artifact?.external_scan_status || '')
}

function packageExternalScanProvider(plugin: PluginItem) {
  const artifact = plugin.manifest?.package_artifact as Record<string, any> | undefined
  return String(plugin.package_external_scan_provider || artifact?.external_scan_provider || artifact?.external_scan?.scanner || '')
}

function packageExternalScanDetail(plugin: PluginItem) {
  const artifact = plugin.manifest?.package_artifact as Record<string, any> | undefined
  return externalScanDetailLabel(artifact?.external_scan)
}

function externalScanDetailLabel(scan: unknown) {
  const detail = scan && typeof scan === 'object' ? scan as Record<string, any> : {}
  const values = [
    safeSidecarText(detail.provider_status) ? `提供方 ${safeSidecarText(detail.provider_status)}` : '',
    safeSidecarText(detail.threat_intel_status) ? `威胁情报 ${safeSidecarText(detail.threat_intel_status)}` : '',
    safeSidecarText(detail.signature_version) ? `签名 ${safeSidecarText(detail.signature_version)}` : '',
    safeSidecarText(detail.engine_version) ? `引擎 ${safeSidecarText(detail.engine_version)}` : '',
    detail.matches_artifact_checksum === true ? '校验和匹配' : '',
  ].filter(Boolean)
  return values.join(' / ')
}

const SENSITIVE_PLUGIN_TEXT_PATTERN = /(authorization|bearer|token|api[_-]?key|secret|password|credential)/i

function safeSidecarText(value: unknown) {
  const text = String(value ?? '').trim()
  if (!text) return ''
  return SENSITIVE_PLUGIN_TEXT_PATTERN.test(text) ? '[redacted]' : text
}

function redactPluginDisplayValue(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map((item) => redactPluginDisplayValue(item))
  }
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([key, item]) => [
        key,
        SENSITIVE_PLUGIN_TEXT_PATTERN.test(key) ? '[redacted]' : redactPluginDisplayValue(item),
      ]),
    )
  }
  if (typeof value === 'string') {
    return SENSITIVE_PLUGIN_TEXT_PATTERN.test(value) ? '[redacted]' : value
  }
  return value
}

function safePluginJson(value: unknown) {
  return JSON.stringify(redactPluginDisplayValue(value), null, 2)
}

function sandboxDisplayPayload(result: PluginSandboxRunResult) {
  return result.errors.length ? { output: result.output, errors: result.errors } : result.output
}

function packageRetentionLabel(plugin: PluginItem) {
  const artifact = plugin.manifest?.package_artifact as Record<string, any> | undefined
  return String(plugin.package_retention_expires_at || artifact?.retention_expires_at || '')
}

function pluginWithUploadedArtifact(plugin: PluginItem, uploaded: PluginArtifactUploadResult): PluginItem {
  const packageArtifact = {
    artifact_id: uploaded.artifact_id,
    artifact_type: uploaded.artifact_type,
    source: uploaded.source,
    filename: uploaded.filename,
    content_type: uploaded.content_type,
    size_bytes: uploaded.size_bytes,
    checksum: uploaded.checksum,
    checksum_algorithm: uploaded.checksum_algorithm,
    expected_checksum: uploaded.expected_checksum,
    storage_path: uploaded.storage_path,
    stored_at: uploaded.stored_at,
    stored_by: uploaded.stored_by,
    verified: uploaded.verified,
    recorded_only: uploaded.recorded_only,
    hash_scan_status: uploaded.hash_scan_status,
    hash_scan: uploaded.hash_scan,
    scan_status: uploaded.scan_status,
    scan_summary: uploaded.scan_summary,
    scan_warnings: uploaded.scan_warnings,
    scan: uploaded.scan,
    external_scan_status: uploaded.external_scan_status,
    external_scan_provider: uploaded.external_scan_provider,
    external_scan_required: uploaded.external_scan_required,
    external_scan: uploaded.external_scan,
    retention_days: uploaded.retention_days,
    retention_expires_at: uploaded.retention_expires_at,
    retention_policy: uploaded.retention_policy,
    notes: uploaded.notes,
  }
  return {
    ...plugin,
    version: uploaded.version || plugin.version,
    manifest: {
      ...(plugin.manifest || {}),
      package_artifact: packageArtifact,
    },
    package_artifact_id: uploaded.artifact_id,
    package_checksum: uploaded.checksum,
    package_artifact_verified: uploaded.verified === true && uploaded.recorded_only !== true,
    package_artifact_storage_path: uploaded.storage_path,
    package_scan_status: uploaded.scan_status,
    package_hash_scan_status: uploaded.hash_scan_status,
    package_external_scan_status: uploaded.external_scan_status,
    package_external_scan_provider: uploaded.external_scan_provider,
    package_retention_expires_at: uploaded.retention_expires_at,
    package_retention_days: uploaded.retention_days,
  }
}

export function PluginRegistryPage() {
  const operator = useOperatorContext()
  const [plugins, setPlugins] = useState<PluginItem[]>([])
  const [runtimePlan, setRuntimePlan] = useState<PluginRuntimePlan | null>(null)
  const [usageStats, setUsageStats] = useState<PluginUsageStatsItem[]>([])
  const [usageHistory, setUsageHistory] = useState<PluginUsageHistoryResponse | null>(null)
  const [selectedId, setSelectedId] = useState('')
  const [audit, setAudit] = useState<PluginAuditItem[]>([])
  const [validation, setValidation] = useState<PluginValidateResult | null>(null)
  const [sandboxResult, setSandboxResult] = useState<PluginSandboxRunResult | null>(null)
  const [artifactFile, setArtifactFile] = useState<File | null>(null)
  const [artifactExpectedChecksum, setArtifactExpectedChecksum] = useState('')
  const [artifactUploadResult, setArtifactUploadResult] = useState<PluginArtifactUploadResult | null>(null)
  const [artifactCleanupResult, setArtifactCleanupResult] = useState<PluginArtifactCleanupResult | null>(null)
  const [runningSandboxAgentId, setRunningSandboxAgentId] = useState('')
  const [artifactUploading, setArtifactUploading] = useState(false)
  const [artifactCleanupRunning, setArtifactCleanupRunning] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const selected = plugins.find((plugin) => plugin.plugin_id === selectedId) ?? plugins[0]
  const selectedRuntimeAgents = runtimePlan?.agents.filter((agent) => agent.plugin_id === selected?.plugin_id) ?? []
  const selectedUsageStats = usageForPlugin(usageStats, selected?.plugin_id)
  const selectedUsageHistory = usageHistoryForPlugin(usageHistory, selected?.plugin_id)
  const selectedPackageScanStatus = selected ? packageScanStatus(selected) : ''
  const selectedPackageHashScanStatus = selected ? packageHashScanStatus(selected) : ''
  const selectedPackageExternalScanStatus = selected ? packageExternalScanStatus(selected) : ''
  const selectedPackageExternalScanProvider = selected ? packageExternalScanProvider(selected) : ''
  const selectedPackageExternalScanDetail = selected ? packageExternalScanDetail(selected) : ''
  const selectedPackageRetentionLabel = selected ? packageRetentionLabel(selected) : ''
  const canRunPluginChecks = roleAllows(operator.role, 'operator')
  const canTogglePlugins = roleAllows(operator.role, 'admin')
  const pluginRuntimeActionDisabledReason = canRunPluginChecks
    ? undefined
    : `插件运行时检查需要 operator 权限。当前角色：${operator.role}。`
  const pluginLifecycleActionDisabledReason = canTogglePlugins
    ? undefined
    : `插件生命周期和产物操作需要 admin 权限。当前角色：${operator.role}。`
  const selectedArchived = selected?.lifecycle_status === 'ARCHIVED'

  const load = useCallback(async (nextSelected = '') => {
    setLoading(true)
    setError('')
    try {
      const [pluginData, planData, usageData, historyData] = await Promise.all([
        listPlugins(),
        getPluginRuntimePlan(),
        getPluginUsageStats(),
        getPluginUsageHistory(),
      ])
      setPlugins(pluginData)
      setRuntimePlan(planData)
      setUsageStats(usageData)
      setUsageHistory(historyData)
      const id = nextSelected || pluginData[0]?.plugin_id || ''
      setSelectedId(id)
      if (id) {
        setAudit(await getPluginAudit(id))
      } else {
        setAudit([])
      }
    } catch (err) {
      setError(messageOf(err))
    } finally {
      setLoading(false)
    }
  }, [])

  async function handleSelect(pluginId: string) {
    setSelectedId(pluginId)
    setValidation(null)
    setSandboxResult(null)
    setArtifactUploadResult(null)
    setArtifactCleanupResult(null)
    setArtifactFile(null)
    setArtifactExpectedChecksum('')
    setError('')
    try {
      setAudit(await getPluginAudit(pluginId))
    } catch (err) {
      setError(messageOf(err))
    }
  }

  async function handleToggle(plugin: PluginItem) {
    if (!canTogglePlugins) {
      setError(pluginLifecycleActionDisabledReason || '插件生命周期操作需要 admin 权限。')
      return
    }
    if (plugin.lifecycle_status === 'ARCHIVED') return
    setLoading(true)
    setError('')
    try {
      const next = plugin.enabled ? await disablePlugin(plugin.plugin_id) : await enablePlugin(plugin.plugin_id)
      await load(next.plugin_id)
    } catch (err) {
      setError(messageOf(err))
    } finally {
      setLoading(false)
    }
  }

  async function handleArchive(plugin: PluginItem) {
    if (!canTogglePlugins) {
      setError(pluginLifecycleActionDisabledReason || '插件生命周期操作需要 admin 权限。')
      return
    }
    if (plugin.lifecycle_status === 'ARCHIVED') return
    setLoading(true)
    setError('')
    try {
      const archived = await archivePlugin(plugin.plugin_id, { reason: 'Archived from Plugin Registry UI.' })
      await load(archived.plugin_id)
    } catch (err) {
      setError(messageOf(err))
    } finally {
      setLoading(false)
    }
  }

  async function handleArtifactUpload(plugin: PluginItem) {
    if (!canTogglePlugins) {
      setError(pluginLifecycleActionDisabledReason || '插件产物上传需要 admin 权限。')
      return
    }
    if (!artifactFile) {
      setError('上传前请先选择插件包产物。')
      return
    }
    setArtifactUploading(true)
    setError('')
    try {
      const uploaded = await uploadPluginArtifact(plugin.plugin_id, artifactFile, {
        expected_checksum: artifactExpectedChecksum.trim(),
        reason: 'Uploaded from Plugin Registry UI for package review.',
      })
      setArtifactUploadResult(uploaded)
      setArtifactFile(null)
      setArtifactExpectedChecksum('')
      await load(uploaded.plugin_id)
      setPlugins((current) => {
        const merged = current.map((item) => item.plugin_id === uploaded.plugin_id ? pluginWithUploadedArtifact(item, uploaded) : item)
        return merged.some((item) => item.plugin_id === uploaded.plugin_id) ? merged : [pluginWithUploadedArtifact(plugin, uploaded), ...current]
      })
      setSelectedId(uploaded.plugin_id)
    } catch (err) {
      setError(messageOf(err))
    } finally {
      setArtifactUploading(false)
    }
  }

  async function handleArtifactCleanupDryRun(plugin: PluginItem) {
    if (!canTogglePlugins) {
      setError(pluginLifecycleActionDisabledReason || '插件产物清理需要 admin 权限。')
      return
    }
    setArtifactCleanupRunning(true)
    setError('')
    try {
      const result = await cleanupPluginArtifacts({
        dry_run: true,
        reason: `Dry-run retention cleanup from Plugin Registry for ${plugin.plugin_id}.`,
      })
      setArtifactCleanupResult(result)
      await load(plugin.plugin_id)
    } catch (err) {
      setError(messageOf(err))
    } finally {
      setArtifactCleanupRunning(false)
    }
  }

  async function handleUpgrade(plugin: PluginItem) {
    if (!canTogglePlugins) {
      setError(pluginLifecycleActionDisabledReason || '插件升级需要 admin 权限。')
      return
    }
    setLoading(true)
    setError('')
    try {
      const nextVersion = nextPatchVersion(plugin.version)
      const storedArtifact = verifiedPackageArtifact(plugin)
      const upgraded = await upgradePlugin(plugin.plugin_id, {
        ...plugin,
        version: nextVersion,
        enabled: plugin.enabled && plugin.lifecycle_status !== 'ARCHIVED',
        manifest: plugin.manifest ?? {},
        package_artifact: storedArtifact ? {
          ...storedArtifact,
          source: 'plugin_registry_ui_uploaded_artifact',
          notes: 'Stored and sha256-verified package artifact selected from Plugin Registry; no executable artifact was imported.',
        } : {
          artifact_id: `${plugin.plugin_id}@${nextVersion}`,
          artifact_type: 'manifest_only',
          source: 'plugin_registry_ui',
          checksum: `sha256:metadata-only:${plugin.plugin_id}:${nextVersion}`,
          recorded_only: true,
          notes: 'UI-recorded metadata migration; no executable artifact was imported.',
        },
        migration_steps: [
          storedArtifact ? {
            step_id: 'verified_artifact_upgrade',
            kind: 'artifact_storage_verified',
            description: 'Use the stored and sha256-verified package artifact for the governed upgrade.',
          } : {
            step_id: 'manifest_contract_upgrade',
            kind: 'metadata_only',
            description: 'Record upgraded manifest/package metadata from Plugin Registry.',
          },
        ],
        reason: 'Upgraded from Plugin Registry UI.',
      })
      await load(upgraded.plugin_id)
      setPlugins((current) => {
        const merged = current.map((item) => item.plugin_id === upgraded.plugin_id ? { ...item, ...upgraded } : item)
        return merged.some((item) => item.plugin_id === upgraded.plugin_id) ? merged : [upgraded, ...current]
      })
      setSelectedId(upgraded.plugin_id)
    } catch (err) {
      setError(messageOf(err))
    } finally {
      setLoading(false)
    }
  }

  async function handleValidate(pluginId: string) {
    if (!canRunPluginChecks) {
      setError(pluginRuntimeActionDisabledReason || '插件运行时检查需要 operator 权限。')
      return
    }
    setLoading(true)
    setError('')
    try {
      setValidation(await validatePlugin(pluginId))
      setAudit(await getPluginAudit(pluginId))
      setRuntimePlan(await getPluginRuntimePlan())
      setUsageStats(await getPluginUsageStats())
      setUsageHistory(await getPluginUsageHistory())
    } catch (err) {
      setError(messageOf(err))
    } finally {
      setLoading(false)
    }
  }

  async function handleSandboxRun(agent: PluginRuntimeAgentPlan) {
    if (!selected) return
    if (!canRunPluginChecks) {
      setError(pluginRuntimeActionDisabledReason || '插件运行时检查需要 operator 权限。')
      return
    }
    setRunningSandboxAgentId(agent.agent_id)
    setSandboxResult(null)
    setError('')
    try {
      const symbol = 'SANDBOX'
      const result = await runPluginSandbox(selected.plugin_id, agent.agent_id, {
        input_payload: { symbol, analysis_context: { source: 'plugin_registry_dry_run' }, kline: [] },
      })
      setSandboxResult(result)
      setAudit(await getPluginAudit(selected.plugin_id))
      setRuntimePlan(await getPluginRuntimePlan())
      setUsageStats(await getPluginUsageStats())
      setUsageHistory(await getPluginUsageHistory())
    } catch (err) {
      setError(messageOf(err))
    } finally {
      setRunningSandboxAgentId('')
    }
  }

  useEffect(() => {
    load()
  }, [load])

  return (
    <div className="space-y-6">
      <SectionTitle
        eyebrow="模块"
        title="插件运行时"
        subtitle="注册、校验、运行时 DAG 计划、只读沙箱与交易动作门禁。"
      />

      {error && <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}

      <RuntimePlanSummary plan={runtimePlan} loading={loading} onRefresh={() => load(selectedId)} />

      <div className="grid gap-6 xl:grid-cols-[380px_minmax(0,1fr)]">
        <Card
          title="插件注册表"
          action={
            <button
              type="button"
              title="刷新插件"
              onClick={() => load(selectedId)}
              className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-slate-200 text-slate-700 hover:bg-slate-50"
            >
              <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
            </button>
          }
        >
          <div className="space-y-2">
            {plugins.length === 0 ? (
              <div className="rounded-md bg-slate-50 p-3 text-sm text-slate-500">暂无已注册插件</div>
            ) : (
              plugins.map((plugin) => {
                const agentCount = runtimePlan?.agents.filter((agent) => agent.plugin_id === plugin.plugin_id).length ?? 0
                return (
                  <button
                    key={plugin.plugin_id}
                    type="button"
                    onClick={() => handleSelect(plugin.plugin_id)}
                    className={`w-full rounded-md border p-4 text-left transition ${
                      selected?.plugin_id === plugin.plugin_id ? 'border-cyan-300 bg-cyan-50 shadow-sm' : 'border-slate-200 hover:bg-slate-50'
                    }`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="truncate text-base font-semibold text-slate-950">{pluginLabel(plugin)}</div>
                        <div className="mt-1 truncate text-xs text-slate-500">
                          v{plugin.version} / {sourceLabel(plugin.source)}
                        </div>
                      </div>
                      <Badge status={plugin.lifecycle_status === 'ARCHIVED' ? 'SKIPPED' : plugin.enabled ? 'PASS' : 'SKIPPED'} className="shrink-0">
                        {plugin.lifecycle_status === 'ARCHIVED' ? '已归档' : plugin.enabled ? '已启用' : '已停用'}
                      </Badge>
                    </div>
                    <div className="mt-2 flex flex-wrap gap-2">
                      <Badge status={plugin.risk_level}>{plugin.risk_level}</Badge>
                      <Badge status="READ_ONLY">只读</Badge>
                      <Badge status="REVIEW_ONLY">{agentCount || plugin.agents.length} 个 Agent</Badge>
                    </div>
                  </button>
                )
              })
            )}
          </div>
        </Card>

        {selected ? (
          <div className="min-w-0 space-y-6">
            <Card
              title={pluginLabel(selected)}
              action={
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    disabled={loading || !canRunPluginChecks}
                    title={pluginRuntimeActionDisabledReason || undefined}
                    onClick={() => handleValidate(selected.plugin_id)}
                    data-testid="plugin-validate-action"
                    className="inline-flex h-9 items-center gap-2 rounded-md border border-slate-200 px-3 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                  >
                    <ShieldCheck size={16} />
                    校验
                  </button>
                  <button
                    type="button"
                    disabled={loading || !canTogglePlugins || selectedArchived}
                    title={selectedArchived ? '归档插件不能直接启用；请注册新版本恢复。' : canTogglePlugins ? undefined : pluginLifecycleActionDisabledReason}
                    onClick={() => handleToggle(selected)}
                    data-testid="plugin-toggle-action"
                    className="inline-flex h-9 items-center gap-2 rounded-md bg-slate-950 px-3 text-sm font-semibold text-white disabled:opacity-50"
                  >
                    <Power size={16} />
                    {selected.enabled ? '停用' : '启用'}
                  </button>
                  <button
                    type="button"
                    disabled={loading || !canTogglePlugins || selectedArchived}
                    title={selectedArchived ? '插件已归档。' : canTogglePlugins ? undefined : pluginLifecycleActionDisabledReason}
                    onClick={() => handleArchive(selected)}
                    data-testid="plugin-archive-action"
                    className="inline-flex h-9 items-center gap-2 rounded-md border border-slate-200 px-3 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                  >
                    <Archive size={16} />
                    归档
                  </button>
                  <button
                    type="button"
                    disabled={loading || !canTogglePlugins}
                    title={canTogglePlugins ? '升级插件清单版本' : pluginLifecycleActionDisabledReason}
                    onClick={() => handleUpgrade(selected)}
                    data-testid="plugin-upgrade-action"
                    className="inline-flex h-9 items-center gap-2 rounded-md border border-slate-200 px-3 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                  >
                    <Upload size={16} />
                    升级
                  </button>
                </div>
              }
            >
              <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                <span className="rounded bg-slate-100 px-2 py-1">操作员：{operator.id}</span>
                <span data-testid="plugin-runtime-action-role" className="rounded bg-slate-100 px-2 py-1">
                  角色：{operator.role}；运行时检查：{canRunPluginChecks ? 'operator+' : '已阻断'}
                </span>
                <span data-testid="plugin-lifecycle-action-role" className="rounded bg-slate-100 px-2 py-1">
                  生命周期/产物：{canTogglePlugins ? 'admin' : '已阻断'}
                </span>
                <Badge status={canTogglePlugins ? 'PASS' : 'SKIPPED'}>角色 {operator.role}</Badge>
                {!canRunPluginChecks ? (
                  <span data-testid="plugin-runtime-action-disabled-reason" className="text-amber-700">{pluginRuntimeActionDisabledReason}</span>
                ) : null}
                {!canTogglePlugins ? (
                  <span data-testid="plugin-lifecycle-action-disabled-reason" className="text-amber-700">{pluginLifecycleActionDisabledReason}</span>
                ) : null}
              </div>
              <div className="text-sm leading-6 text-slate-600">{pluginDescription(selected)}</div>
              <div className="mt-4 grid gap-4 md:grid-cols-4">
                <Metric label="插件 ID" value={selected.plugin_id} />
                <Metric label="权限数量" value={String(selected.permissions.length)} />
                <Metric label="注册 Agent" value={String(selected.agents.length)} />
                <Metric label="生命周期" value={selected.lifecycle_status ?? 'ACTIVE'} badge={selectedArchived ? 'SKIPPED' : 'PASS'} />
              </div>
              {selected.upgraded_at ? (
                <div data-testid="plugin-upgraded-state" className="mt-4 rounded-md border border-cyan-100 bg-cyan-50 px-3 py-2 text-sm text-cyan-800">
                  已从 {selected.upgrade_from_version || 'unknown'} 升级；操作者 {selected.upgraded_by || 'unknown'}；时间 {selected.upgraded_at}
                  {selected.package_checksum ? ` / ${selected.package_checksum}` : ''}
                </div>
              ) : null}
              {selectedArchived ? (
                <div data-testid="plugin-archived-state" className="mt-4 rounded-md border border-amber-100 bg-amber-50 px-3 py-2 text-sm text-amber-800">
                  已归档：{selected.archived_at || 'N/A'} / {selected.archived_by || 'unknown'}
                </div>
              ) : null}
              {(selected.package_artifact_id || selected.package_checksum) ? (
                <div data-testid="plugin-package-artifact-state" className="mt-4 rounded-md border border-emerald-100 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
                  包产物{selected.package_artifact_verified ? '已验证' : '已记录'}：{selected.package_artifact_id || 'unknown'} / {selected.package_checksum || '无 checksum'}
                  {selectedPackageHashScanStatus ? ` / 哈希扫描 ${selectedPackageHashScanStatus}` : ''}
                  {selectedPackageScanStatus ? ` / 扫描 ${selectedPackageScanStatus}` : ''}
                  {selectedPackageExternalScanStatus ? ` / 外部扫描 ${selectedPackageExternalScanStatus}${selectedPackageExternalScanProvider ? ` (${selectedPackageExternalScanProvider})` : ''}` : ''}
                  {selectedPackageExternalScanDetail ? ` / ${selectedPackageExternalScanDetail}` : ''}
                  {selectedPackageRetentionLabel ? ` / 保留至 ${selectedPackageRetentionLabel}` : ''}
                </div>
              ) : null}
              <div data-testid="plugin-usage-history" className="mt-4 rounded-md border border-slate-200 p-3">
                <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                  <div className="text-sm font-medium text-slate-700">使用历史</div>
                  <span className="text-xs text-slate-500">{usageHistory?.days ?? 0} days / {usageHistory?.bucket ?? 'day'}</span>
                </div>
                <div className="grid gap-2 md:grid-cols-3">
                  {selectedUsageHistory.slice(-6).reverse().map((bucket) => (
                    <div key={`${bucket.plugin_id}-${bucket.bucket_start}`} className="rounded-md bg-slate-50 px-3 py-2">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-xs font-medium text-slate-600">{bucket.bucket_label || bucket.bucket_start}</span>
                        <Badge status={bucket.total_audit_events ? 'PASS' : 'SKIPPED'}>{bucket.total_audit_events} events</Badge>
                      </div>
                      <div className="mt-1 text-xs text-slate-500">
                        sandbox {bucket.sandbox_run_count} / lifecycle {bucket.lifecycle_event_count} / avg {numberValue(bucket.average_elapsed_ms).toFixed(1)} ms
                      </div>
                    </div>
                  ))}
                </div>
              </div>
              <div className="mt-4 rounded-md border border-slate-200 p-3">
                <div className="mb-2 text-sm font-medium text-slate-700">包产物上传</div>
                <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(180px,260px)_auto]">
                  <input
                    type="file"
                    data-testid="plugin-artifact-file"
                    disabled={artifactUploading || loading || !canTogglePlugins}
                    title={!canTogglePlugins ? pluginLifecycleActionDisabledReason : undefined}
                    onChange={(event) => setArtifactFile(event.target.files?.[0] ?? null)}
                    className="min-w-0 rounded-md border border-slate-200 px-3 py-2 text-sm text-slate-700"
                  />
                  <input
                    type="text"
                    data-testid="plugin-artifact-checksum"
                    value={artifactExpectedChecksum}
                    onChange={(event) => setArtifactExpectedChecksum(event.target.value)}
                    placeholder="可选 sha256"
                    disabled={artifactUploading || loading || !canTogglePlugins}
                    title={!canTogglePlugins ? pluginLifecycleActionDisabledReason : undefined}
                    className="rounded-md border border-slate-200 px-3 py-2 text-sm text-slate-700"
                  />
                  <button
                    type="button"
                    data-testid="plugin-artifact-upload-action"
                    disabled={artifactUploading || loading || !canTogglePlugins || !artifactFile}
                    title={!canTogglePlugins ? pluginLifecycleActionDisabledReason : undefined}
                    onClick={() => handleArtifactUpload(selected)}
                    className="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-slate-200 px-3 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                  >
                    <Upload size={16} />
                    {artifactUploading ? '上传中' : '上传产物'}
                  </button>
                </div>
                {artifactUploadResult && artifactUploadResult.plugin_id === selected.plugin_id ? (
                  <div data-testid="plugin-artifact-upload-result" className="mt-3 rounded-md bg-slate-50 px-3 py-2 text-xs text-slate-600">
                    {artifactUploadResult.verified ? '已验证' : '未验证'} / 哈希扫描 {artifactUploadResult.hash_scan_status || 'UNKNOWN'} / 扫描 {artifactUploadResult.scan_status || 'UNKNOWN'} / 外部扫描 {artifactUploadResult.external_scan_status || 'UNKNOWN'}{artifactUploadResult.external_scan_provider ? ` (${artifactUploadResult.external_scan_provider})` : ''} / 保留至 {artifactUploadResult.retention_expires_at || 'N/A'} / {artifactUploadResult.checksum} / {artifactUploadResult.storage_path}
                    {externalScanDetailLabel(artifactUploadResult.external_scan) ? ` / ${externalScanDetailLabel(artifactUploadResult.external_scan)}` : ''}
                  </div>
                ) : null}
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    data-testid="plugin-artifact-cleanup-dry-run-action"
                    disabled={artifactCleanupRunning || loading || !canTogglePlugins}
                    title={!canTogglePlugins ? pluginLifecycleActionDisabledReason : undefined}
                    onClick={() => handleArtifactCleanupDryRun(selected)}
                    className="inline-flex h-9 items-center justify-center gap-2 rounded-md border border-slate-200 px-3 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                  >
                    <RefreshCw size={15} />
                    {artifactCleanupRunning ? '检查清理中' : '清理预演'}
                  </button>
                  {artifactCleanupResult ? (
                    <div data-testid="plugin-artifact-cleanup-result" className="rounded-md bg-slate-50 px-3 py-2 text-xs text-slate-600">
                      {artifactCleanupResult.status}：已过期 {artifactCleanupResult.expired_count} / 将删除 {artifactCleanupResult.would_delete_count} / 已跳过 {artifactCleanupResult.skipped_count}
                    </div>
                  ) : null}
                </div>
              </div>
              <div data-testid="plugin-usage-summary" className="mt-4 grid gap-4 md:grid-cols-4">
                <Metric label="使用事件" value={String(selectedUsageStats?.total_audit_events ?? 0)} />
                <Metric label="沙箱运行" value={String(selectedUsageStats?.sandbox_run_count ?? 0)} />
                <Metric label="阻断/失败" value={String((selectedUsageStats?.sandbox_block_count ?? 0) + (selectedUsageStats?.execute_preview_failed_count ?? 0))} />
                <Metric label="平均耗时" value={`${numberValue(selectedUsageStats?.average_elapsed_ms).toFixed(1)} ms`} />
              </div>
              {selectedUsageStats?.last_audit_id ? (
                <div className="mt-2 flex flex-wrap gap-2 text-xs text-slate-500">
                  <Badge status={statusBadge(selectedUsageStats.last_status)}>{selectedUsageStats.last_action || 'NO_ACTION'}</Badge>
                  <span>{selectedUsageStats.last_audit_id}</span>
                  <span>{selectedUsageStats.last_actor || 'system'}</span>
                </div>
              ) : null}
              <div className="mt-4 rounded-md border border-slate-200 p-3">
                <div className="mb-2 text-sm font-medium text-slate-700">注册契约</div>
                <div className="space-y-2">
                  {selected.agents.map((agent, index) => (
                    <div key={`${selected.plugin_id}-${index}`} className="flex flex-wrap items-center justify-between gap-3 rounded-md bg-slate-50 px-3 py-2 text-sm">
                      <span className="font-medium text-slate-700">{registryAgentLabel(agent)}</span>
                      <div className="flex flex-wrap gap-2">
                        <Badge status={agent.input_schema?.type ? 'PASS' : 'FAIL'}>输入结构</Badge>
                        <Badge status={agent.output_schema?.type ? 'PASS' : 'FAIL'}>输出结构</Badge>
                        <Badge status={Array.isArray(agent.permissions) && agent.permissions.length ? 'PASS' : 'FAIL'}>权限</Badge>
                        <Badge status={agent.can_emit_trade_action ? 'FAIL' : 'PASS'}>不发交易动作</Badge>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
              {validation && validation.plugin_id === selected.plugin_id && (
                <div className="mt-4 rounded-md border border-slate-200 p-3">
                  <div className="mb-2 flex items-center gap-2 text-sm font-medium text-slate-700">
                    <CheckCircle2 size={16} />
                    清单校验
                  </div>
                  <Badge status={validation.valid ? 'PASS' : 'FAIL'}>{validation.valid ? '已通过' : '未通过'}</Badge>
                  {[...validation.failures, ...validation.warnings].length > 0 && (
                    <ul className="mt-3 space-y-1 text-sm text-slate-600">
                      {[...validation.failures, ...validation.warnings].map((item) => <li key={item}>{item}</li>)}
                    </ul>
                  )}
                </div>
              )}
            </Card>

            <RuntimeAgentsPanel
              agents={selectedRuntimeAgents}
              runningAgentId={runningSandboxAgentId}
              sandboxResult={sandboxResult}
              canRunPluginChecks={canRunPluginChecks}
              disabledReason={pluginRuntimeActionDisabledReason}
              onSandboxRun={handleSandboxRun}
            />

            <Card title="插件审计">
              {audit.length === 0 ? (
                <div className="rounded-md bg-slate-50 p-3 text-sm text-slate-500">暂无审计记录</div>
              ) : (
                <EvidenceLedger
                  rows={audit.map((entry) => ({
                    label: auditIdLabel(entry),
                    source: entry.actor || 'system',
                    status: <Badge status="REVIEW_ONLY">{actionLabel(entry.action)}</Badge>,
                    detail: `${auditMessageLabel(entry)} / ${entry.created_at}`,
                    strength: 100,
                  }))}
                  className="!rounded-lg !shadow-none"
                />
              )}
            </Card>
          </div>
        ) : (
          <Card title="插件详情">
            <div className="text-sm text-slate-500">请选择一个插件</div>
          </Card>
        )}
      </div>
    </div>
  )
}

function RuntimePlanSummary({ plan, loading, onRefresh }: { plan: PluginRuntimePlan | null; loading: boolean; onRefresh: () => void }) {
  const resourceSummary = plan?.resource_summary ?? {}
  const resourceWarnings = Array.isArray(resourceSummary.warnings) ? resourceSummary.warnings : []

  return (
    <Card
      title="运行时计划"
      action={
        <button
          type="button"
          title="刷新运行时计划"
          onClick={onRefresh}
          className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-slate-200 text-slate-700 hover:bg-slate-50"
        >
          <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
        </button>
      }
    >
      <div className="grid gap-4 md:grid-cols-6">
        <Metric label="计划状态" value={plan?.status ?? '加载中'} badge={statusBadge(plan?.status ?? 'WAIT')} />
        <Metric label="沙箱状态" value={plan?.sandbox_status ?? '加载中'} badge={statusBadge(plan?.sandbox_status ?? 'WAIT')} />
        <Metric label="启用插件数" value={String(plan?.enabled_plugin_count ?? 0)} />
        <Metric label="运行时 Agent" value={String(plan?.enabled_agent_count ?? 0)} />
        <Metric label="DAG 节点" value={String(plan?.registered_dag_node_count ?? 0)} />
        <Metric label="热加载 Agent" value={String(plan?.hot_reload_agent_count ?? 0)} />
      </div>
      {plan && (
        <div className="mt-4 flex flex-wrap gap-2">
          {plan.required_gates.map((gate) => <Badge key={gate} status="REVIEW_ONLY">{gateLabel(gate)}</Badge>)}
          {plan.forbidden_trade_actions.map((action) => <Badge key={action} status="BLOCKED">{action}</Badge>)}
        </div>
      )}
      {plan && (
        <div data-testid="plugin-resource-summary" className="mt-4 grid gap-4 md:grid-cols-4">
          <Metric
            label="资源配额"
            value={String(resourceSummary.quota_status ?? 'EMPTY')}
            badge={resourceQuotaBadge(resourceSummary.quota_status)}
          />
          <Metric label="自定义限制" value={String(numberValue(resourceSummary.agents_with_custom_limits))} />
          <Metric label="总超时" value={`${numberValue(resourceSummary.total_timeout_ms)} ms`} />
          <Metric label="输出预算" value={formatBytes(resourceSummary.total_max_output_bytes)} />
        </div>
      )}
      {resourceWarnings.length > 0 && (
        <ul data-testid="plugin-resource-warnings" className="mt-3 space-y-1 text-sm text-amber-700">
          {resourceWarnings.slice(0, 4).map((warning) => <li key={warning}>{warning}</li>)}
        </ul>
      )}
    </Card>
  )
}

function RuntimeAgentsPanel({
  agents,
  runningAgentId,
  sandboxResult,
  canRunPluginChecks,
  disabledReason,
  onSandboxRun,
}: {
  agents: PluginRuntimeAgentPlan[]
  runningAgentId: string
  sandboxResult: PluginSandboxRunResult | null
  canRunPluginChecks: boolean
  disabledReason?: string
  onSandboxRun: (agent: PluginRuntimeAgentPlan) => void
}) {
  return (
    <Card title="运行时沙箱计划">
      {agents.length === 0 ? (
        <div className="rounded-md bg-slate-50 p-3 text-sm text-slate-500">当前插件暂无启用的运行时 Agent</div>
      ) : (
        <div className="space-y-3">
          {agents.map((agent) => (
            <div key={agent.dag_node_id} className="rounded-md border border-slate-200 p-3">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="truncate text-sm font-semibold text-slate-950">{agentLabel(agent.agent_id, agent.agent_name)}</div>
                  <div className="mt-1 truncate text-xs text-slate-500">{agent.dag_node_id}</div>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge status={statusBadge(agent.registration_status)}>{agent.registration_status}</Badge>
                  <button
                    type="button"
                    onClick={() => onSandboxRun(agent)}
                    disabled={!agent.execution_sandbox.hot_reload_allowed || runningAgentId !== '' || !canRunPluginChecks}
                    title={disabledReason || (!agent.execution_sandbox.hot_reload_allowed ? '该 Agent 不允许沙箱热加载。' : undefined)}
                    data-testid={`plugin-sandbox-run-${agent.agent_id}`}
                    className="inline-flex h-8 items-center gap-1.5 rounded-md border border-slate-200 px-2 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <Play size={13} />
                    {runningAgentId === agent.agent_id ? '运行中' : '沙箱运行'}
                  </button>
                </div>
              </div>
              <div className="mt-2 text-xs text-slate-500">
                DAG：{agent.dag_registration?.node_type ?? 'plugin_observation'}，插入位置：
                {agent.dag_registration?.insertion_after ?? 'quant_core'}，执行模式：
                {agent.dag_registration?.execution_mode ?? 'READ_ONLY_NO_CODE'}
              </div>
              <div className="mt-3 grid gap-3 sm:grid-cols-2 2xl:grid-cols-4">
                <StatusBlock
                  label="结构校验"
                  status={agent.schema_status.valid}
                  detail={agent.schema_status.valid ? '已声明输入与输出' : agent.schema_status.failures.join('; ')}
                />
                <StatusBlock
                  label="权限沙箱"
                  status={agent.permission_sandbox.allowed}
                  detail={`${agent.permission_sandbox.mode}；代码执行 ${agent.permission_sandbox.code_execution}`}
                />
                <StatusBlock
                  label="风险门禁"
                  status={agent.risk_gate.allowed && !agent.risk_gate.trade_actions_allowed}
                  detail={`${agent.risk_gate.risk_level}；${agent.risk_gate.required_gates.map(gateLabel).join(' / ')}`}
                />
                <StatusBlock
                  label="执行沙箱"
                  status={agent.execution_sandbox.allowed}
                  detail={`${agent.execution_sandbox.mode}；热加载 ${agent.execution_sandbox.hot_reload_allowed ? '允许' : '阻断'}`}
                />
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <Badge status={agent.execution_sandbox.code_execution === 'DISABLED' ? 'PASS' : 'FAIL'}>
                  代码 {agent.execution_sandbox.code_execution}
                </Badge>
                <Badge status={agent.execution_sandbox.network_access === 'DENIED' ? 'PASS' : 'FAIL'}>
                  网络 {agent.execution_sandbox.network_access}
                </Badge>
                <Badge status={agent.execution_sandbox.filesystem_access === 'DENIED' ? 'PASS' : 'WARN'}>
                  文件系统 {agent.execution_sandbox.filesystem_access}
                </Badge>
                <Badge status={agent.execution_sandbox.trade_action_hard_block ? 'PASS' : 'FAIL'}>交易硬阻断</Badge>
                <Badge status={agent.execution_sandbox.resource_limit_warnings?.length ? 'WARN' : 'PASS'}>
                  资源 {numberValue(agent.execution_sandbox.resource_limits?.timeout_ms)} ms / {formatBytes(agent.execution_sandbox.resource_limits?.max_output_bytes)}
                </Badge>
                {agent.execution_sandbox.custom_resource_limits && <Badge status="REVIEW_ONLY">自定义配额</Badge>}
              </div>
              {agent.execution_sandbox.resource_limit_warnings?.length > 0 && (
                <ul data-testid="plugin-resource-limit-warnings" className="mt-3 space-y-1 text-sm text-amber-700">
                  {agent.execution_sandbox.resource_limit_warnings.map((warning) => <li key={warning}>{warning}</li>)}
                </ul>
              )}
              {sandboxResult && sandboxResult.agent_id === agent.agent_id && (
                <div className="mt-3 rounded-md border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700">
                  <div className="mb-2 flex flex-wrap items-center gap-2">
                    <Badge status={statusBadge(sandboxResult.status)}>{sandboxResult.status}</Badge>
                    <span className="text-xs text-slate-500">{sandboxResult.audit_id}</span>
                  </div>
                  <pre className="max-h-40 overflow-auto whitespace-pre-wrap text-xs">{safePluginJson(sandboxDisplayPayload(sandboxResult))}</pre>
                </div>
              )}
              {agent.validation_failures.length > 0 && (
                <ul className="mt-3 space-y-1 text-sm text-red-700">
                  {agent.validation_failures.map((failure) => <li key={failure}>{failure}</li>)}
                </ul>
              )}
              {agent.execution_sandbox.block_reasons.length > 0 && (
                <ul className="mt-3 space-y-1 text-sm text-red-700">
                  {agent.execution_sandbox.block_reasons.map((failure) => <li key={failure}>{failure}</li>)}
                </ul>
              )}
            </div>
          ))}
        </div>
      )}
    </Card>
  )
}

function Metric({ label, value, badge }: { label: string; value: string; badge?: string }) {
  return (
    <MetricTile
      className="!rounded-lg !p-3 !shadow-none"
      label={label}
      value={badge ? <Badge status={badge}>{value}</Badge> : value}
      tone={metricToneForBadge(badge)}
    />
  )
}

function StatusBlock({ label, status, detail }: { label: string; status: boolean; detail: string }) {
  return (
    <div className="min-w-0 rounded-lg border border-slate-200 bg-white p-3">
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
        <span className="text-xs text-slate-500">{label}</span>
        <Badge status={boolBadge(status)}>{status ? 'PASS' : 'FAIL'}</Badge>
      </div>
      <div className="mt-2 break-words text-sm text-slate-700">{detail}</div>
    </div>
  )
}
