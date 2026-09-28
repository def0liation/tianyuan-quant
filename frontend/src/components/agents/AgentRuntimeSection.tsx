import { Fragment, useEffect, useMemo, useState } from 'react'
import { CheckCircle2, ChevronDown, ChevronRight, Plug, Plus, RefreshCw, Router, Save, Search, ShieldAlert, ShieldCheck, ZoomIn, ZoomOut } from 'lucide-react'
import { SectionTitle } from '../common/SectionTitle'
import { Card } from '../common/Card'
import { Badge } from '../common/Badge'
import {
  getAgentRuntime,
  testLLMProfile,
  updateAgentLLM,
  updateAgentRuntime,
  upsertLLMProfile,
  validateLLMProfileConfig,
} from '../../api/agentRuntimeClient'
import {
  AgentLLMProfile,
  AgentRuntimeConfig,
  RuntimeBaseUrlSecurity,
  RuntimeProfileHealthStatus,
  UpsertLLMProfilePayload,
} from '../../types'
import { roleAllows, useOperatorContext } from '../../store/operatorContext'
import { formatDateTime } from '../../utils/format'

type ProfileDraft = {
  id: string
  label: string
  provider: string
  base_url: string
  model: string
  egress_confirmed: boolean
  api_key: string
  clear_api_key: boolean
  temperature: number
  max_tokens: number
  timeout_seconds: number
  enabled: boolean
}

type ModelPreset = {
  value: string
  label: string
  note?: string
}

type BaseUrlRisk = {
  status: 'trusted' | 'local' | 'custom' | 'missing' | 'invalid'
  label: string
  detail: string
  requiresConfirmation: boolean
}

const AGENT_STAGE_LABELS: Record<string, string> = {
  control: '控制与路由',
  data: '数据接入',
  guardrail: '风控门禁',
  analysis: '市场与量化',
  risk: '组合风险',
  execution: '执行复核',
  output: '输出与审计',
}

function agentStageLabel(stage: string) {
  return AGENT_STAGE_LABELS[stage] ?? (stage || '其他')
}

const emptyDraft: ProfileDraft = {
  id: '',
  label: '',
  provider: 'openai_compatible',
  base_url: 'https://api.openai.com/v1',
  model: '',
  egress_confirmed: false,
  api_key: '',
  clear_api_key: false,
  temperature: 0.2,
  max_tokens: 4096,
  timeout_seconds: 60,
  enabled: true,
}

const providerPresets: Record<string, Pick<ProfileDraft, 'provider' | 'base_url'>> = {
  openai: { provider: 'openai', base_url: 'https://api.openai.com/v1' },
  openai_compatible: { provider: 'openai_compatible', base_url: 'https://api.openai.com/v1' },
  deepseek: { provider: 'deepseek', base_url: 'https://api.deepseek.com' },
  qwen: { provider: 'qwen', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1' },
  moonshot: { provider: 'moonshot', base_url: 'https://api.moonshot.ai/v1' },
  mistral: { provider: 'mistral', base_url: 'https://api.mistral.ai/v1' },
  xai: { provider: 'xai', base_url: 'https://api.x.ai/v1' },
  openrouter: { provider: 'openrouter', base_url: 'https://openrouter.ai/api/v1' },
  local: { provider: 'local', base_url: 'http://localhost:11434/v1' },
  anthropic: { provider: 'anthropic', base_url: 'https://api.anthropic.com/v1' },
  gemini: { provider: 'gemini', base_url: 'https://generativelanguage.googleapis.com/v1beta/openai' },
}

const LLM_ALLOWED_BASE_URLS = Array.from(new Set(Object.values(providerPresets).map((preset) => preset.base_url)))
const RUNTIME_LOAD_RETRY_DELAYS_MS = [1000, 3000, 6000]

const modelPresets: Record<string, ModelPreset[]> = {
  openai: [
    { value: 'gpt-5.5', label: 'GPT-5.5', note: 'frontier' },
    { value: 'gpt-5.4', label: 'GPT-5.4' },
    { value: 'gpt-5.4-mini', label: 'GPT-5.4 mini' },
    { value: 'gpt-5.4-nano', label: 'GPT-5.4 nano' },
    { value: 'gpt-5.2', label: 'GPT-5.2' },
    { value: 'gpt-5.2-pro', label: 'GPT-5.2 pro' },
    { value: 'gpt-5', label: 'GPT-5' },
    { value: 'gpt-5-mini', label: 'GPT-5 mini' },
    { value: 'gpt-5-nano', label: 'GPT-5 nano' },
    { value: 'gpt-4.1', label: 'GPT-4.1' },
    { value: 'gpt-4.1-mini', label: 'GPT-4.1 mini' },
    { value: 'gpt-4.1-nano', label: 'GPT-4.1 nano' },
    { value: 'gpt-4o', label: 'GPT-4o' },
    { value: 'gpt-4o-mini', label: 'GPT-4o mini' },
  ],
  anthropic: [
    { value: 'claude-opus-4-20250514', label: 'Claude Opus 4' },
    { value: 'claude-sonnet-4-20250514', label: 'Claude Sonnet 4' },
    { value: 'claude-3-7-sonnet-20250219', label: 'Claude 3.7 Sonnet' },
    { value: 'claude-3-5-sonnet-20241022', label: 'Claude 3.5 Sonnet' },
    { value: 'claude-3-5-haiku-20241022', label: 'Claude 3.5 Haiku' },
  ],
  gemini: [
    { value: 'gemini-2.5-pro', label: 'Gemini 2.5 Pro' },
    { value: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash' },
    { value: 'gemini-2.5-flash-lite', label: 'Gemini 2.5 Flash-Lite' },
    { value: 'gemini-2.0-flash', label: 'Gemini 2.0 Flash' },
    { value: 'gemini-2.0-flash-lite', label: 'Gemini 2.0 Flash-Lite' },
  ],
  deepseek: [
    { value: 'deepseek-v4-pro', label: 'DeepSeek V4 Pro' },
    { value: 'deepseek-v4-flash', label: 'DeepSeek V4 Flash' },
    { value: 'deepseek-chat', label: 'DeepSeek Chat' },
    { value: 'deepseek-reasoner', label: 'DeepSeek Reasoner' },
  ],
  qwen: [
    { value: 'qwen3-max', label: 'Qwen3 Max' },
    { value: 'qwen3-max-preview', label: 'Qwen3 Max Preview' },
    { value: 'qwen-plus', label: 'Qwen Plus' },
    { value: 'qwen-plus-latest', label: 'Qwen Plus Latest' },
    { value: 'qwen-flash', label: 'Qwen Flash' },
    { value: 'qwen3-coder-plus', label: 'Qwen3 Coder Plus' },
    { value: 'qwen3-coder-flash', label: 'Qwen3 Coder Flash' },
  ],
  moonshot: [
    { value: 'kimi-k2.5', label: 'Kimi K2.5' },
    { value: 'kimi-k2-turbo-preview', label: 'Kimi K2 Turbo Preview' },
    { value: 'kimi-k2-thinking', label: 'Kimi K2 Thinking' },
    { value: 'kimi-k2-thinking-turbo', label: 'Kimi K2 Thinking Turbo' },
    { value: 'moonshot-v1-8k', label: 'Moonshot V1 8K' },
    { value: 'moonshot-v1-32k', label: 'Moonshot V1 32K' },
    { value: 'moonshot-v1-128k', label: 'Moonshot V1 128K' },
  ],
  mistral: [
    { value: 'mistral-large-latest', label: 'Mistral Large Latest' },
    { value: 'mistral-small-latest', label: 'Mistral Small Latest' },
    { value: 'codestral-latest', label: 'Codestral Latest' },
    { value: 'ministral-8b-latest', label: 'Ministral 8B Latest' },
  ],
  xai: [
    { value: 'grok-4', label: 'Grok 4' },
    { value: 'grok-3', label: 'Grok 3' },
    { value: 'grok-3-mini', label: 'Grok 3 Mini' },
  ],
  openrouter: [
    { value: 'openai/gpt-5.5', label: 'OpenAI GPT-5.5' },
    { value: 'anthropic/claude-sonnet-4', label: 'Claude Sonnet 4' },
    { value: 'google/gemini-2.5-pro', label: 'Gemini 2.5 Pro' },
    { value: 'deepseek/deepseek-v4-pro', label: 'DeepSeek V4 Pro' },
    { value: 'qwen/qwen3-max', label: 'Qwen3 Max' },
    { value: 'moonshotai/kimi-k2.5', label: 'Kimi K2.5' },
  ],
  local: [
    { value: 'qwen3:8b', label: 'Ollama Qwen3 8B' },
    { value: 'qwen3:14b', label: 'Ollama Qwen3 14B' },
    { value: 'llama3.1:8b', label: 'Ollama Llama 3.1 8B' },
    { value: 'deepseek-r1:8b', label: 'Ollama DeepSeek R1 8B' },
    { value: 'local-model-name', label: '本地自定义模型' },
  ],
}

modelPresets.openai_compatible = [
  ...modelPresets.openai,
  ...modelPresets.deepseek,
  ...modelPresets.qwen,
  ...modelPresets.moonshot,
  ...modelPresets.gemini,
]

function modelOptionsForProvider(provider: string) {
  return modelPresets[provider] ?? modelPresets.openai_compatible
}

function profileToDraft(profile: AgentLLMProfile): ProfileDraft {
  return {
    id: profile.id,
    label: profile.label,
    provider: profile.provider,
    base_url: profile.base_url,
    model: profile.model,
    egress_confirmed: Boolean(profile.egress_confirmed),
    api_key: '',
    clear_api_key: false,
    temperature: profile.temperature,
    max_tokens: profile.max_tokens,
    timeout_seconds: profile.timeout_seconds,
    enabled: profile.enabled,
  }
}

function legacyProfileReady(profile?: AgentLLMProfile) {
  if (!profile) return false
  const localProfile = profile.provider === 'local' || profile.base_url.startsWith('http://localhost') || profile.base_url.startsWith('http://127.0.0.1')
  return Boolean(profile.enabled && profile.base_url && profile.model && (profile.api_key_set || localProfile))
}

function llmHealthStatus(profile?: AgentLLMProfile): RuntimeProfileHealthStatus {
  if (!profile) return 'INCOMPLETE'
  return profile.health_status ?? (legacyProfileReady(profile) ? 'READY' : profile.enabled ? 'INCOMPLETE' : 'DISABLED')
}

function healthBadgeStatus(status: RuntimeProfileHealthStatus) {
  if (status === 'READY') return 'PASS'
  if (status === 'FAILED') return 'FAIL'
  if (status === 'DISABLED') return 'SKIPPED'
  return 'WARN'
}

function llmHealthLabel(profile?: AgentLLMProfile) {
  const status = llmHealthStatus(profile)
  if (status === 'READY') return '最近调用成功'
  if (status === 'CONFIGURED') return profile?.last_checked_at ? '配置完整，未真实调用' : '配置完整'
  if (status === 'FAILED') return '最近调用失败'
  if (status === 'DISABLED') return '已禁用'
  return '配置不完整'
}

function llmHealthDetail(profile?: AgentLLMProfile) {
  if (!profile) return ''
  if (profile.last_error) return `失败原因: ${profile.last_error}`
  if (profile.last_call_success === true) {
    const latency = typeof profile.last_latency_ms === 'number' ? `，${profile.last_latency_ms}ms` : ''
    return `最近调用成功${latency}${profile.last_checked_at ? `，${formatDateTime(profile.last_checked_at)}` : ''}`
  }
  if (profile.configured && profile.last_call_success == null) return '配置字段完整，但尚未记录真实 LLM 调用成功。'
  return ''
}

function canonicalBaseUrl(value: string) {
  const trimmed = value.trim().replace(/\/+$/, '')
  if (!trimmed) return ''

  try {
    const url = new URL(trimmed)
    const pathname = url.pathname.replace(/\/+$/, '')
    return `${url.protocol}//${url.host}${pathname}`.toLowerCase()
  } catch {
    return trimmed.toLowerCase()
  }
}

function isLoopbackHost(hostname: string) {
  return ['localhost', '127.0.0.1', '::1', '[::1]'].includes(hostname.toLowerCase())
}

function assessBaseUrlRisk(value: string, allowedBaseUrls: string[], surface: 'LLM' | '行情'): BaseUrlRisk {
  const trimmed = value.trim()
  if (!trimmed) {
    return {
      status: 'missing',
      label: '缺少基础 URL',
      detail: `${surface} 配置档尚未配置调用地址。`,
      requiresConfirmation: false,
    }
  }

  let parsed: URL
  try {
    parsed = new URL(trimmed)
  } catch {
    return {
      status: 'invalid',
      label: 'URL 格式异常',
      detail: '请输入完整的 http(s) 地址；生产 strict 模式应拒绝无法解析的地址。',
      requiresConfirmation: true,
    }
  }

  if (!['http:', 'https:'].includes(parsed.protocol)) {
    return {
      status: 'invalid',
      label: '协议不受控',
      detail: '仅允许 http(s) endpoint；其他协议不应携带后端密钥发起请求。',
      requiresConfirmation: true,
    }
  }

  const canonical = canonicalBaseUrl(trimmed)
  const allowed = new Set(allowedBaseUrls.map(canonicalBaseUrl))
  if (allowed.has(canonical)) {
    const local = isLoopbackHost(parsed.hostname)
    return {
      status: local ? 'local' : 'trusted',
      label: local ? '本地预设端点' : '预设可信端点',
      detail: local
        ? '该地址匹配本地模型预设，适合本机开发；生产部署前仍需确认不会把后端密钥发往非预期服务。'
        : '该地址匹配前端内置 provider 预设；生产仍由后端 strict 校验和写入认证兜底。',
      requiresConfirmation: false,
    }
  }

  return {
    status: isLoopbackHost(parsed.hostname) ? 'local' : 'custom',
    label: isLoopbackHost(parsed.hostname) ? '自定义本地端点' : '自定义基础 URL',
    detail: `${parsed.host} 不在前端预设白名单中。保存或真实连通测试前需要人工确认；生产 strict 模式必须由后端白名单或审批机制放行。`,
    requiresConfirmation: true,
  }
}

function baseUrlRiskClass(status: BaseUrlRisk['status']) {
  if (status === 'trusted') return 'border-emerald-200 bg-emerald-50 text-emerald-800'
  if (status === 'local') return 'border-sky-200 bg-sky-50 text-sky-800'
  if (status === 'missing') return 'border-slate-200 bg-slate-50 text-slate-600'
  return 'border-amber-200 bg-amber-50 text-amber-800'
}

function confirmBaseUrlRisk(label: string, risk: BaseUrlRisk) {
  if (!risk.requiresConfirmation) return true
  return window.confirm(
      `${label} 使用 ${risk.label}。\n\n${risk.detail}\n\n继续保存或测试会把当前配置档的密钥随请求交给后端运行时。请确认该地址已完成白名单/审批检查，且 audit 记录不会保存明文 Key。`,
  )
}

function BaseUrlRiskNotice({ title, risk, auditText }: { title: string; risk: BaseUrlRisk; auditText?: string }) {
  return (
    <div className={`rounded-lg border px-3 py-2 text-xs ${baseUrlRiskClass(risk.status)}`}>
      <div className="flex items-center gap-2 font-semibold">
        <ShieldAlert size={14} />
        <span>{title}: {risk.label}</span>
      </div>
      <div className="mt-1 leading-relaxed">{risk.detail}</div>
      <div className="mt-1 text-[11px] opacity-80">
        生产 strict：自定义地址必须通过后端白名单或审批确认；配置 audit 只记录 profile、host、操作者和时间，不记录明文 Key。
      </div>
      {auditText && <div className="mt-1 text-[11px] opacity-80">Audit: {auditText}</div>}
    </div>
  )
}

function ServerBaseUrlSecurity({
  testId,
  security,
}: {
  testId: string
  security?: RuntimeBaseUrlSecurity | null
}) {
  if (!security) return null
  const allowedHosts = Array.isArray(security.allowed_hosts) ? security.allowed_hosts : []
  return (
    <div data-testid={testId} className="mt-2 rounded-md border border-slate-200 bg-white px-3 py-2 text-[11px] leading-5 text-slate-600">
      <div className="font-semibold text-slate-800">
        服务端出站安全：{security.status ?? 'NOT_EVALUATED'} / {security.allowed ? '允许' : '已阻断'}
      </div>
      <div>
        strict {security.strict_mode_required ? '是' : '否'}
        {security.host ? ` / 主机 ${security.host}` : ''}
        {security.reason ? ` / 原因 ${security.reason}` : ''}
        {security.code ? ` / 代码 ${security.code}` : ''}
      </div>
      {security.message ? <div className="break-words">{security.message}</div> : null}
      <div>允许域名：{allowedHosts.length ? allowedHosts.join(', ') : '未配置'}</div>
    </div>
  )
}

export function AgentRuntimeSection() {
  const operator = useOperatorContext()
  const [runtime, setRuntime] = useState<AgentRuntimeConfig | null>(null)
  const [selectedProfileId, setSelectedProfileId] = useState('')
  const [profileDraft, setProfileDraft] = useState<ProfileDraft>(emptyDraft)
  const [newProfileId, setNewProfileId] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [runtimeLoadRetry, setRuntimeLoadRetry] = useState(0)
  const [validationStatus, setValidationStatus] = useState<{
    isValid: boolean | null
    message: string
  }>({ isValid: null, message: '' })
  const [agentZoom, setAgentZoom] = useState<1 | 2 | 3>(2)
  const [agentFilter, setAgentFilter] = useState('')
  const [expandedAgentGroups, setExpandedAgentGroups] = useState<Record<string, boolean>>({})
  const canManageRuntime = roleAllows(operator.role, 'admin')
  const runtimeWriteDisabledReason = canManageRuntime
    ? undefined
    : `当前角色 ${operator.role} 不能修改 Agent Runtime 配置。请切换到 admin 或使用管理员 token。`
  const runtimeActionDisabled = saving || testing || !canManageRuntime

  const selectedProfile = useMemo(
    () => runtime?.llm_profiles.find((profile) => profile.id === selectedProfileId),
    [runtime, selectedProfileId],
  )

  const defaultMarketProfile = useMemo(
    () => runtime?.market_data_profiles.find((profile) => profile.id === runtime.default_market_data_profile_id),
    [runtime],
  )

  const llmBaseUrlRisk = useMemo(
    () => assessBaseUrlRisk(profileDraft.base_url, LLM_ALLOWED_BASE_URLS, 'LLM'),
    [profileDraft.base_url],
  )

  const llmAuditText =
    selectedProfile?.config_audit?.audit_id
    || selectedProfile?.last_config_audit_id
    || (selectedProfile ? '后端未返回配置 audit id' : '草稿未保存')

  const assignedCount = useMemo(() => {
    if (!runtime || !selectedProfileId) return 0
    return runtime.agents.filter((agent) => agent.llm_profile_id === selectedProfileId).length
  }, [runtime, selectedProfileId])

  const filteredAgents = useMemo(() => {
    if (!runtime) return []
    if (!agentFilter.trim()) return runtime.agents
    const query = agentFilter.toLowerCase().trim()
    return runtime.agents.filter(
      (agent) =>
        agent.name.toLowerCase().includes(query) ||
        agent.role.toLowerCase().includes(query) ||
        (agent.node_type ?? agent.stage ?? '').toLowerCase().includes(query) ||
        (agent.id ?? '').toLowerCase().includes(query),
    )
  }, [runtime, agentFilter])

  const groupedAgents = useMemo(() => {
    const groups = new Map<string, NonNullable<AgentRuntimeConfig['agents']>>()
    for (const agent of filteredAgents) {
      const key = agent.stage || agent.node_type || 'other'
      groups.set(key, [...(groups.get(key) ?? []), agent])
    }
    return Array.from(groups.entries()).map(([key, agents]) => ({
      key,
      label: agentStageLabel(key),
      agents,
      readyCount: agents.filter((agent) => {
        const profile = runtime?.llm_profiles.find((item) => item.id === agent.llm_profile_id)
        return agent.enabled && llmHealthStatus(profile) === 'READY'
      }).length,
    }))
  }, [filteredAgents, runtime])

  const selectedModelOptions = useMemo(
    () => modelOptionsForProvider(profileDraft.provider),
    [profileDraft.provider],
  )

  const selectedModelPresetValue = useMemo(
    () => selectedModelOptions.some((model) => model.value === profileDraft.model) ? profileDraft.model : 'custom',
    [profileDraft.model, selectedModelOptions],
  )

  async function loadRuntime(options: { isRetry?: boolean } = {}) {
    if (!options.isRetry) {
      setRuntimeLoadRetry(0)
    }
    setLoading(true)
    setError(null)
    try {
      const response = await getAgentRuntime()
      setRuntime(response)
      setRuntimeLoadRetry(0)
      const firstProfileId = response.default_llm_profile_id || response.llm_profiles[0]?.id || ''
      setSelectedProfileId((current) => current || firstProfileId)
    } catch (err) {
      setError(err instanceof Error ? err.message : '无法加载 API 配置。')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadRuntime()
  }, [])

  useEffect(() => {
    if (runtime || loading || !error || runtimeLoadRetry >= RUNTIME_LOAD_RETRY_DELAYS_MS.length) return
    const retryTimer = window.setTimeout(() => {
      setRuntimeLoadRetry((attempt) => attempt + 1)
      loadRuntime({ isRetry: true })
    }, RUNTIME_LOAD_RETRY_DELAYS_MS[runtimeLoadRetry])
    return () => window.clearTimeout(retryTimer)
  }, [runtime, loading, error, runtimeLoadRetry])

  useEffect(() => {
    if (selectedProfile) {
      setProfileDraft(profileToDraft(selectedProfile))
    }
  }, [selectedProfile])

  function toggleAgentGroup(groupKey: string) {
    setExpandedAgentGroups((current) => ({ ...current, [groupKey]: !current[groupKey] }))
  }

  function setAllAgentGroups(expanded: boolean) {
    setExpandedAgentGroups(Object.fromEntries(groupedAgents.map((group) => [group.key, expanded])))
  }

  function profilePayload(): { profileId: string; payload: UpsertLLMProfilePayload } {
    const profileId = profileDraft.id.trim()
    if (!profileId) {
      throw new Error('配置档 ID 必填。')
    }

    const payload: UpsertLLMProfilePayload = {
      label: profileDraft.label.trim() || profileId,
      provider: profileDraft.provider,
      base_url: profileDraft.base_url.trim(),
      model: profileDraft.model.trim(),
      egress_confirmed: profileDraft.egress_confirmed,
      clear_api_key: profileDraft.clear_api_key,
      temperature: Number(profileDraft.temperature),
      max_tokens: Number(profileDraft.max_tokens),
      timeout_seconds: Number(profileDraft.timeout_seconds),
      enabled: profileDraft.enabled,
    }

    if (profileDraft.api_key.trim()) {
      payload.api_key = profileDraft.api_key.trim()
    }

    return { profileId, payload }
  }

  async function persistProfile() {
    const { profileId, payload } = profilePayload()
    const response = await upsertLLMProfile(profileId, payload)
    setRuntime(response)
    setSelectedProfileId(profileId)
    setProfileDraft((draft) => ({ ...draft, api_key: '', clear_api_key: false }))
    return { profileId, response }
  }

  function guardRuntimeWrite(action: string) {
    if (canManageRuntime) return true
    setError(`${action} 需要 admin 角色。当前角色：${operator.role}。`)
    return false
  }

  async function handleSaveProfile() {
    if (!guardRuntimeWrite('保存 API 配置档')) return
    if (!confirmBaseUrlRisk('LLM API 配置档', llmBaseUrlRisk)) return
    if (llmBaseUrlRisk.requiresConfirmation && !profileDraft.egress_confirmed) {
      setError('自定义 LLM 基础 URL 需要先勾选白名单/审批确认，后端才会在 strict 模式下允许携带密钥出站。')
      return
    }
    setSaving(true)
    setError(null)
    try {
      await persistProfile()
      setMessage('API 配置档已保存。')
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存 API 配置档失败。')
    } finally {
      setSaving(false)
    }
  }

  async function handleSaveApplyAll() {
    if (!guardRuntimeWrite('保存并应用 API 配置档')) return
    if (!confirmBaseUrlRisk('LLM API 配置档', llmBaseUrlRisk)) return
    if (llmBaseUrlRisk.requiresConfirmation && !profileDraft.egress_confirmed) {
      setError('自定义 LLM 基础 URL 需要先勾选白名单/审批确认，才能应用到全部 Agent。')
      return
    }
    setSaving(true)
    setError(null)
    try {
      const { profileId, response } = await persistProfile()
      const updated = await updateAgentRuntime({
        default_llm_profile_id: profileId,
        default_market_data_profile_id: response.default_market_data_profile_id,
        max_parallel_agents: response.max_parallel_agents,
        apply_default_to_all_agents: true,
      })
      setRuntime(updated)
      setMessage('API 配置档已保存，并应用到全部 Agent。')
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存并应用 API 配置档失败。')
    } finally {
      setSaving(false)
    }
  }

  async function handleLiveTestProfile() {
    if (!guardRuntimeWrite('执行 LLM 连通测试')) return
    if (!confirmBaseUrlRisk('LLM API 连通测试', llmBaseUrlRisk)) return
    if (llmBaseUrlRisk.requiresConfirmation && !profileDraft.egress_confirmed) {
      setError('自定义 LLM 基础 URL 需要先勾选白名单/审批确认，才能执行真实连通测试。')
      return
    }
    setTesting(true)
    setError(null)
    setMessage('正在执行真实 LLM 连通测试，最长等待约 15 秒。')
    try {
      const { profileId } = await persistProfile()
      const result = await testLLMProfile(profileId, true)
      setMessage(`${result.status}: ${result.message}`)
      await loadRuntime()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'API 连通测试失败。')
    } finally {
      setTesting(false)
    }
  }

  async function handleQuickValidateProfile() {
    if (!guardRuntimeWrite('验证 LLM 配置档配置')) return
    setTesting(true)
    setError(null)
    try {
      const config = {
        provider: profileDraft.provider,
        base_url: profileDraft.base_url,
        model: profileDraft.model,
        api_key: profileDraft.api_key,
        enabled: profileDraft.enabled,
      }
      const result = await validateLLMProfileConfig(config)
      if (result.status === 'READY' || result.status === 'CONFIGURED') {
        setMessage('✅ 配置验证通过，可以保存并测试连通性。')
        setValidationStatus({ isValid: true, message: '配置完整' })
      } else {
        setMessage(`⚠️ ${result.status}: ${result.message}`)
        setValidationStatus({ isValid: false, message: result.message })
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '配置验证失败。')
      setValidationStatus({ isValid: false, message: '验证失败' })
    } finally {
      setTesting(false)
    }
  }

  // 实时验证配置
  useEffect(() => {
    const validateConfigRealtime = async () => {
      if (!profileDraft.api_key.trim()) {
        setValidationStatus({ isValid: null, message: '' })
        return
      }
      if (!canManageRuntime) {
        setValidationStatus({ isValid: null, message: '需要 admin 角色' })
        return
      }

      try {
        const config = {
          provider: profileDraft.provider,
          base_url: profileDraft.base_url,
          model: profileDraft.model,
          api_key: profileDraft.api_key,
          enabled: profileDraft.enabled,
        }
        const result = await validateLLMProfileConfig(config)
        if (result.status === 'READY' || result.status === 'CONFIGURED') {
          setValidationStatus({ isValid: true, message: '配置完整' })
        } else {
          setValidationStatus({ isValid: false, message: result.message })
        }
      } catch {
        setValidationStatus({ isValid: false, message: '验证失败' })
      }
    }

    // 防抖处理，避免频繁请求
    const timeoutId = setTimeout(validateConfigRealtime, 500)
    return () => clearTimeout(timeoutId)
  }, [canManageRuntime, profileDraft.provider, profileDraft.base_url, profileDraft.model, profileDraft.api_key, profileDraft.enabled])

  async function handleRuntimeSave(applyAll = false) {
    if (!guardRuntimeWrite(applyAll ? '应用默认配置档到全部 Agent' : '保存运行时路由')) return
    if (!runtime) return
    setSaving(true)
    setError(null)
    try {
      const response = await updateAgentRuntime({
        default_llm_profile_id: runtime.default_llm_profile_id,
        default_market_data_profile_id: runtime.default_market_data_profile_id,
        max_parallel_agents: runtime.max_parallel_agents,
        apply_default_to_all_agents: applyAll,
      })
      setRuntime(response)
      setMessage(applyAll ? '默认配置档已应用到全部 Agent。' : '运行时路由已保存。')
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存运行时路由失败。')
    } finally {
      setSaving(false)
    }
  }

  async function handleAgentChange(agentId: string, llmProfileId: string, enabled: boolean) {
    if (!guardRuntimeWrite('更新 Agent API 路由')) return
    setSaving(true)
    setError(null)
    try {
      const response = await updateAgentLLM(agentId, {
        llm_profile_id: llmProfileId,
        enabled,
      })
      setRuntime(response)
      setMessage('Agent API 路由已更新。')
    } catch (err) {
      setError(err instanceof Error ? err.message : '更新 Agent API 路由失败。')
    } finally {
      setSaving(false)
    }
  }

  function startNewProfile() {
    const profileId = newProfileId.trim() || `llm_${Date.now()}`
    setSelectedProfileId(profileId)
    setProfileDraft({
      ...emptyDraft,
      id: profileId,
      label: profileId,
    })
    setNewProfileId('')
    setError(null)
    setMessage(`已创建 API 配置档草稿：${profileId}。填写完成后请点击保存或保存并应用。`)
  }

  function applyProviderPreset(provider: string) {
    const preset = providerPresets[provider]
    setProfileDraft((draft) => ({
      ...draft,
      provider,
      base_url: preset?.base_url ?? draft.base_url,
      egress_confirmed: false,
    }))
  }

  if (loading) {
    return <div>正在加载 API 配置...</div>
  }

  if (!runtime) {
    const retrying = runtimeLoadRetry < RUNTIME_LOAD_RETRY_DELAYS_MS.length
    return (
      <Card title="API 配置不可用">
        <div data-testid="agent-runtime-load-error" className="space-y-3">
          <div className="text-sm text-rose-600">{error ?? '后端运行时配置不可用。'}</div>
          {retrying ? (
            <div data-testid="agent-runtime-load-retry" className="text-xs text-slate-500">
              后端配置接口恢复后将自动重新加载。
            </div>
          ) : null}
          <button
            type="button"
            onClick={() => loadRuntime()}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
          >
            <RefreshCw size={16} />
            重新加载
          </button>
        </div>
      </Card>
    )
  }

  return (
    <div className="space-y-6">
      <SectionTitle
        title="统一 API 配置"
        subtitle="配置一次模型接口，全部 Agent 按路由直接调用。"
      />

      <div className="rounded-md border border-slate-200 bg-white px-4 py-3 text-xs text-slate-500">
        <span data-testid="agent-runtime-write-role">
          角色：{operator.role}；运行时写入：{canManageRuntime ? 'admin' : '已阻断'}
        </span>
        {!canManageRuntime ? (
          <span data-testid="agent-runtime-write-disabled-reason" className="ml-3 text-amber-700">
            {runtimeWriteDisabledReason}
          </span>
        ) : null}
      </div>

      {!canManageRuntime ? (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          {runtimeWriteDisabledReason}
        </div>
      ) : null}

      {(message || error) && (
        <div className={`rounded-lg border px-4 py-3 text-sm ${error ? 'border-rose-200 bg-rose-50 text-rose-700' : 'border-emerald-200 bg-emerald-50 text-emerald-700'}`}>
          {error ?? message}
        </div>
      )}

      <div className="grid gap-3 md:grid-cols-2">
        <BaseUrlRiskNotice title="LLM 基础 URL" risk={llmBaseUrlRisk} auditText={llmAuditText} />
        <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-700">
          <div className="flex items-center gap-2 font-semibold text-slate-800">
            <ShieldCheck size={14} />
            <span>密钥与配置审计</span>
          </div>
          <div className="mt-1 leading-relaxed">
            API Key 只保留在当前密码输入框和本次请求中；保存或测试后立即清空，前端不写入本机历史，也不展示明文。
          </div>
          <div className="mt-1 text-[11px] text-slate-500">
            生产写入依赖 `API_WRITE_TOKEN`；审计应记录配置档、基础 URL host、操作者和时间，不记录密钥内容。
          </div>
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-[1fr_1.35fr]">
        <Card title="API 配置档">
          <div className="space-y-5">
            <div className="grid gap-3 sm:grid-cols-[1fr_auto_auto]">
              <select
                value={selectedProfileId}
                onChange={(event) => setSelectedProfileId(event.target.value)}
                className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900"
              >
                {runtime.llm_profiles.map((profile) => (
                  <option key={profile.id} value={profile.id}>
                    {profile.label} ({profile.id})
                  </option>
                ))}
                {!selectedProfile && selectedProfileId ? <option value={selectedProfileId}>{selectedProfileId}</option> : null}
              </select>
              <Badge status={healthBadgeStatus(llmHealthStatus(selectedProfile))}>
                {llmHealthLabel(selectedProfile)}
              </Badge>
              <button
                type="button"
                title="重新加载"
                onClick={() => loadRuntime()}
                className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
              >
                <RefreshCw size={16} />
                重新加载
              </button>
            </div>
            {selectedProfile?.health_warnings?.length ? (
              <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                健康警告：{selectedProfile.health_warnings.join(', ')}
              </div>
            ) : null}
            {llmHealthDetail(selectedProfile) ? (
              <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
                {llmHealthDetail(selectedProfile)}
              </div>
            ) : null}

            <div className="grid gap-3 sm:grid-cols-[1fr_auto]">
              <input
                value={newProfileId}
                onChange={(event) => setNewProfileId(event.target.value)}
                placeholder="新配置档 ID"
                className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900"
              />
              <button
                type="button"
                title="新建配置档"
                onClick={startNewProfile}
                className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
              >
                <Plus size={16} />
                新建
              </button>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <label className="space-y-1 text-sm">
                <span className="font-medium text-slate-700">配置档 ID</span>
                <input
                  value={profileDraft.id}
                  onChange={(event) => setProfileDraft((draft) => ({ ...draft, id: event.target.value }))}
                  className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-slate-900"
                />
              </label>
              <label className="space-y-1 text-sm">
                <span className="font-medium text-slate-700">名称</span>
                <input
                  value={profileDraft.label}
                  onChange={(event) => setProfileDraft((draft) => ({ ...draft, label: event.target.value }))}
                  className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-slate-900"
                />
              </label>
              <label className="space-y-1 text-sm">
                <span className="font-medium text-slate-700">提供方</span>
                <select
                  value={profileDraft.provider}
                  onChange={(event) => applyProviderPreset(event.target.value)}
                  className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-slate-900"
                >
                  <option value="openai_compatible">OpenAI 兼容</option>
                  <option value="openai">OpenAI</option>
                  <option value="deepseek">DeepSeek</option>
                  <option value="qwen">Qwen / DashScope</option>
                  <option value="moonshot">Kimi / Moonshot</option>
                  <option value="mistral">Mistral</option>
                  <option value="xai">xAI Grok</option>
                  <option value="openrouter">OpenRouter</option>
                  <option value="anthropic">Anthropic</option>
                  <option value="gemini">Gemini</option>
                  <option value="local">本地</option>
                </select>
              </label>
              <div className="space-y-1 text-sm">
                <span className="font-medium text-slate-700">模型</span>
                <select
                  value={selectedModelPresetValue}
                  onChange={(event) => {
                    const value = event.target.value
                    if (value !== 'custom') {
                      setProfileDraft((draft) => ({ ...draft, model: value }))
                    }
                  }}
                  className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-slate-900"
                >
                  <option value="custom">自定义模型名</option>
                  {selectedModelOptions.map((model) => (
                    <option key={model.value} value={model.value}>
                      {model.label} ({model.value}){model.note ? ` - ${model.note}` : ''}
                    </option>
                  ))}
                </select>
              </div>
              <label className="space-y-1 text-sm md:col-span-2">
                <span className="font-medium text-slate-700">当前模型 ID / 自定义模型</span>
                <input
                  value={profileDraft.model}
                  onChange={(event) => setProfileDraft((draft) => ({ ...draft, model: event.target.value }))}
                  placeholder="选择预设或手动输入提供方支持的模型 ID"
                  list="model-preset-list"
                  className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-slate-900"
                />
                <datalist id="model-preset-list">
                  {selectedModelOptions.map((model) => (
                    <option key={model.value} value={model.value} />
                  ))}
                </datalist>
              </label>
              <label className="space-y-1 text-sm md:col-span-2">
                <span className="font-medium text-slate-700">基础 URL</span>
                <input
                  value={profileDraft.base_url}
                  onChange={(event) => setProfileDraft((draft) => ({ ...draft, base_url: event.target.value, egress_confirmed: false }))}
                  placeholder="https://api.example.com/v1"
                  className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-slate-900"
                />
                <div className={`rounded-md border px-3 py-2 text-xs leading-relaxed ${baseUrlRiskClass(llmBaseUrlRisk.status)}`}>
                  <span className="font-semibold">{llmBaseUrlRisk.label}：</span>
                  {llmBaseUrlRisk.detail}
                  {selectedProfile?.egress_policy_status ? (
                    <div className="mt-1">
                      后端出站策略：{selectedProfile.egress_policy_status}
                      {selectedProfile.egress_policy_message ? ` - ${selectedProfile.egress_policy_message}` : ''}
                    </div>
                  ) : null}
                  <ServerBaseUrlSecurity
                    testId="agent-runtime-llm-base-url-security"
                    security={selectedProfile?.base_url_security}
                  />
                </div>
              </label>
              {llmBaseUrlRisk.requiresConfirmation ? (
                <label className="md:col-span-2 inline-flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-relaxed text-amber-800">
                  <input
                    type="checkbox"
                    checked={profileDraft.egress_confirmed}
                    onChange={(event) => setProfileDraft((draft) => ({ ...draft, egress_confirmed: event.target.checked }))}
                    className="mt-0.5 h-4 w-4 rounded border-amber-300"
                  />
                  <span>
                    我确认该自定义 LLM 基础 URL 已完成白名单/审批核验，并允许后端在 strict 模式下向该 host 发起真实 LLM 请求。
                  </span>
                </label>
              ) : null}
              <div className="space-y-2 text-sm md:col-span-2">
                <label className="block space-y-1">
                  <span className="font-medium text-slate-700">API 密钥</span>
                  <input
                    type="password"
                    value={profileDraft.api_key}
                    onChange={(event) => setProfileDraft((draft) => ({ ...draft, api_key: event.target.value }))}
                    placeholder={selectedProfile?.api_key_set ? `已保存: ${selectedProfile.api_key_mask ?? 'set'}` : 'sk-...'}
                    className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-slate-900"
                    />
                    {validationStatus.isValid !== null && (
                      <div className={`text-xs mt-1 ${validationStatus.isValid ? 'text-green-600' : 'text-red-600'}`}>
                        {validationStatus.isValid ? '✓' : '⚠'} {validationStatus.message}
                      </div>
                    )}
                  </label>
                <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs leading-relaxed text-slate-600">
                  已保存状态由后端以 `api_key_set` 和脱敏 mask 返回：{selectedProfile?.api_key_set ? selectedProfile.api_key_mask ?? 'set' : '未保存'}。
                  新输入的 Key 不会写入浏览器 localStorage，保存或测试后会从表单中清空。
                </div>
              </div>
            </div>

            <div className="grid gap-4 md:grid-cols-3">
              <label className="space-y-1 text-sm">
                <span className="font-medium text-slate-700">温度</span>
                <input
                  type="number"
                  step="0.1"
                  min={0}
                  max={2}
                  value={profileDraft.temperature}
                  onChange={(event) => setProfileDraft((draft) => ({ ...draft, temperature: Number(event.target.value) }))}
                  className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-slate-900"
                />
              </label>
              <label className="space-y-1 text-sm">
                <span className="font-medium text-slate-700">最大 Token</span>
                <input
                  type="number"
                  min={1}
                  value={profileDraft.max_tokens}
                  onChange={(event) => setProfileDraft((draft) => ({ ...draft, max_tokens: Number(event.target.value) }))}
                  className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-slate-900"
                />
              </label>
              <label className="space-y-1 text-sm">
                <span className="font-medium text-slate-700">Timeout 秒</span>
                <input
                  type="number"
                  min={5}
                  value={profileDraft.timeout_seconds}
                  onChange={(event) => setProfileDraft((draft) => ({ ...draft, timeout_seconds: Number(event.target.value) }))}
                  className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-slate-900"
                />
              </label>
            </div>

            <div className="flex flex-col gap-3 text-sm text-slate-700 sm:flex-row sm:items-center sm:justify-between">
              <label className="inline-flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={profileDraft.enabled}
                  onChange={(event) => setProfileDraft((draft) => ({ ...draft, enabled: event.target.checked }))}
                  className="h-4 w-4 rounded border-slate-300"
                />
                启用配置档
              </label>
              <label className="inline-flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={profileDraft.clear_api_key}
                  onChange={(event) => setProfileDraft((draft) => ({ ...draft, clear_api_key: event.target.checked }))}
                  className="h-4 w-4 rounded border-slate-300"
                />
                清除已保存 Key
              </label>
            </div>

            <div className="grid gap-3 sm:grid-cols-4">
              <button
                type="button"
                title="保存 API 配置档"
                data-testid="agent-runtime-save-llm-profile"
                onClick={handleSaveProfile}
                disabled={runtimeActionDisabled}
                className="inline-flex items-center justify-center gap-2 rounded-lg bg-slate-900 px-4 py-3 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
              >
                <Save size={16} />
                保存
              </button>
              <button
                type="button"
                title="保存并应用到全部 Agent"
                data-testid="agent-runtime-save-apply-all"
                onClick={handleSaveApplyAll}
                disabled={runtimeActionDisabled}
                className="inline-flex items-center justify-center gap-2 rounded-lg bg-emerald-700 px-4 py-3 text-sm font-semibold text-white transition hover:bg-emerald-800 disabled:cursor-not-allowed disabled:opacity-60"
              >
                <Router size={16} />
                保存并应用
              </button>
              <button
                type="button"
                title="快速验证配置"
                data-testid="agent-runtime-validate-llm-profile"
                onClick={handleQuickValidateProfile}
                disabled={runtimeActionDisabled}
                className="inline-flex items-center justify-center gap-2 rounded-lg border border-blue-200 px-4 py-3 text-sm font-semibold text-blue-700 transition hover:bg-blue-50 disabled:cursor-not-allowed disabled:opacity-60"
              >
                <CheckCircle2 size={16} />
                {testing ? '验证中' : '快速验证'}
              </button>
              <button
                type="button"
                title="真实连通测试"
                data-testid="agent-runtime-test-llm-profile"
                onClick={handleLiveTestProfile}
                disabled={runtimeActionDisabled}
                className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-200 px-4 py-3 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
              >
                <Plug size={16} />
                {testing ? '测试中' : '连通测试'}
              </button>
            </div>
          </div>
        </Card>

        <div className="space-y-6">
          <Card title="运行时路由">
            <div className="grid gap-4 md:grid-cols-[1fr_160px_auto_auto] md:items-end">
              <label className="space-y-1 text-sm">
                <span className="font-medium text-slate-700">默认配置档</span>
                <select
                  value={runtime.default_llm_profile_id}
                  onChange={(event) => setRuntime((current) => current ? { ...current, default_llm_profile_id: event.target.value } : current)}
                  className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-slate-900"
                >
                  {runtime.llm_profiles.map((profile) => (
                    <option key={profile.id} value={profile.id}>{profile.label}</option>
                  ))}
                </select>
              </label>
              <label className="space-y-1 text-sm">
                <span className="font-medium text-slate-700">并行 Agent</span>
                <input
                  type="number"
                  min={1}
                  max={32}
                  value={runtime.max_parallel_agents}
                  onChange={(event) => setRuntime((current) => current ? { ...current, max_parallel_agents: Number(event.target.value) } : current)}
                  className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-slate-900"
                />
              </label>
              <button
                type="button"
                title="保存运行时路由"
                data-testid="agent-runtime-save-routing"
                onClick={() => handleRuntimeSave(false)}
                disabled={runtimeActionDisabled}
                className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-200 px-4 py-3 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
              >
                <CheckCircle2 size={16} />
                保存路由
              </button>
              <button
                type="button"
                title="应用默认配置档到全部 Agent"
                data-testid="agent-runtime-apply-default-all"
                onClick={() => handleRuntimeSave(true)}
                disabled={runtimeActionDisabled}
                className="inline-flex items-center justify-center gap-2 rounded-lg bg-slate-900 px-4 py-3 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
              >
                <ShieldCheck size={16} />
                应用全部
              </button>
            </div>

            <div className="grid gap-3 pt-2 text-sm text-slate-600 md:grid-cols-4">
              <div>当前配置档: {selectedProfile?.label ?? selectedProfileId}</div>
              <div data-testid="agent-runtime-market-route-summary">
                行情路由: {defaultMarketProfile?.label ?? (runtime.default_market_data_profile_id || '未配置')}
              </div>
              <div>已分配 Agent: {assignedCount} / {runtime.agents.length}</div>
              <div>更新时间: {formatDateTime(runtime.updated_at)}</div>
            </div>
            <div data-testid="agent-runtime-market-source-summary" className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs leading-5 text-slate-600">
              行情数据源由下方“数据源配置”和“数据源适配器状态”统一管理。
              {defaultMarketProfile
                ? ` 当前运行时保留 ${defaultMarketProfile.label} (${defaultMarketProfile.id}) 作为兼容路由。`
                : ' 当前运行时未返回默认行情路由。'}
            </div>
          </Card>

          <Card title="Agent API 分配">
            <div className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="relative flex-1 max-w-md">
                <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                <input
                  type="text"
                  value={agentFilter}
                  onChange={(event) => setAgentFilter(event.target.value)}
                  placeholder="搜索 Agent 名称、角色或节点类型..."
                  className="w-full rounded-lg border border-slate-200 bg-white pl-8 pr-3 py-2 text-sm text-slate-900 outline-none transition focus:border-slate-400"
                />
                {agentFilter && (
                  <button
                    onClick={() => setAgentFilter('')}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-slate-400 hover:text-slate-600"
                  >
                    清除
                  </button>
                )}
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-slate-500">
                  {filteredAgents.length}/{runtime.agents.length} Agent
                </span>
                <button
                  type="button"
                  onClick={() => setAllAgentGroups(true)}
                  className="rounded-md border border-slate-200 px-2 py-1 text-xs font-medium text-slate-600 transition hover:bg-slate-50"
                >
                  全部展开
                </button>
                <button
                  type="button"
                  onClick={() => setAllAgentGroups(false)}
                  className="rounded-md border border-slate-200 px-2 py-1 text-xs font-medium text-slate-600 transition hover:bg-slate-50"
                >
                  全部收起
                </button>
                <div className="flex items-center rounded-lg border border-slate-200 bg-white">
                  <button
                    onClick={() => setAgentZoom((z) => (z > 1 ? ((z - 1) as 1 | 2 | 3) : z))}
                    title="缩小"
                    className={`inline-flex items-center justify-center p-2 transition hover:bg-slate-50 ${agentZoom === 1 ? 'text-slate-300' : 'text-slate-600'}`}
                    disabled={agentZoom === 1}
                  >
                    <ZoomOut size={14} />
                  </button>
                  <span className="px-2 text-xs text-slate-500 border-x border-slate-100">
                    {agentZoom === 1 ? '紧凑' : agentZoom === 2 ? '正常' : '宽松'}
                  </span>
                  <button
                    onClick={() => setAgentZoom((z) => (z < 3 ? ((z + 1) as 1 | 2 | 3) : z))}
                    title="放大"
                    className={`inline-flex items-center justify-center p-2 transition hover:bg-slate-50 ${agentZoom === 3 ? 'text-slate-300' : 'text-slate-600'}`}
                    disabled={agentZoom === 3}
                  >
                    <ZoomIn size={14} />
                  </button>
                </div>
              </div>
            </div>
            <div className="overflow-x-auto">
              <table className="institution-table">
                <thead>
                  <tr className="text-left text-xs uppercase tracking-wide text-slate-500">
                    <th className="px-3 py-2 font-semibold">Agent</th>
                    <th className="px-3 py-2 font-semibold">节点类型</th>
                    <th className="px-3 py-2 font-semibold">API 配置档</th>
                    <th className="px-3 py-2 font-semibold">状态</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {groupedAgents.map((group) => {
                    const expanded = Boolean(agentFilter.trim() || expandedAgentGroups[group.key])
                    return (
                      <Fragment key={group.key}>
                        <tr className="bg-slate-50/80">
                          <td colSpan={4} className="px-3 py-2">
                            <button
                              type="button"
                              onClick={() => toggleAgentGroup(group.key)}
                              className="flex w-full items-center justify-between gap-3 text-left"
                            >
                              <span className="inline-flex items-center gap-2 text-sm font-semibold text-slate-800">
                                {expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
                                {group.label}
                              </span>
                              <span className="text-xs text-slate-500">
                                {group.readyCount}/{group.agents.length} READY
                              </span>
                            </button>
                          </td>
                        </tr>
                        {expanded && group.agents.map((agent) => {
                          const profile = runtime.llm_profiles.find((item) => item.id === agent.llm_profile_id)
                          const zoomClasses = agentZoom === 1
                            ? 'px-2 py-1'
                            : agentZoom === 2
                              ? 'px-3 py-3'
                              : 'px-3 py-4'
                          const nameSize = agentZoom === 1 ? 'text-xs' : 'text-sm'
                          const detailSize = agentZoom === 1 ? 'text-[10px]' : 'text-xs'
                          const selectSize = agentZoom === 1 ? 'px-2 py-1 text-xs' : 'px-3 py-2 text-sm'
                          return (
                            <tr key={agent.id}>
                        <td className={`${zoomClasses} align-top`}>
                          <div className={`font-medium text-slate-900 ${nameSize}`}>{agent.name}</div>
                          {agentZoom > 1 && (
                            <div className={`mt-1 max-w-sm text-slate-500 ${detailSize}`}>{agent.role}</div>
                          )}
                          {agentZoom === 3 && (
                            <div className={`mt-1 text-slate-400 ${detailSize}`}>{agent.system_prompt_ref}</div>
                          )}
                        </td>
                        <td className={`${zoomClasses} align-top text-slate-600`}>
                          <div className={nameSize}>{agent.node_type ?? agent.stage}</div>
                          {agentZoom > 1 && (
                            <div className={`mt-1 text-slate-400 ${detailSize}`}>{agent.prompt_file ?? ''}</div>
                          )}
                        </td>
                        <td className={`${zoomClasses} align-top`}>
                          <select
                            value={agent.llm_profile_id}
                            onChange={(event) => handleAgentChange(agent.id, event.target.value, agent.enabled)}
                            disabled={!canManageRuntime}
                            className={`w-52 rounded-lg border border-slate-200 bg-white text-slate-900 ${selectSize}`}
                          >
                            {runtime.llm_profiles.map((profileOption) => (
                              <option key={profileOption.id} value={profileOption.id}>{profileOption.label}</option>
                            ))}
                            </select>
                        </td>
                        <td className={`${zoomClasses} align-top`}>
                          <div className={`flex flex-col ${agentZoom === 1 ? 'gap-1' : 'gap-2'}`}>
                            <Badge status={agent.enabled ? healthBadgeStatus(llmHealthStatus(profile)) : 'SKIPPED'}>
                              {agent.enabled ? llmHealthLabel(profile) : 'DISABLED'}
                            </Badge>
                            <label className={`inline-flex items-center gap-2 text-slate-600 ${agentZoom === 1 ? 'text-[10px]' : 'text-xs'}`}>
                              <input
                                type="checkbox"
                                checked={agent.enabled}
                                onChange={(event) => handleAgentChange(agent.id, agent.llm_profile_id, event.target.checked)}
                                disabled={!canManageRuntime}
                                className="h-4 w-4 rounded border-slate-300"
                              />
                              启用
                            </label>
                          </div>
                        </td>
                            </tr>
                          )
                        })}
                      </Fragment>
                    )
                  })}
                </tbody>
              </table>
              {filteredAgents.length === 0 && (
                <div className="py-8 text-center text-sm text-slate-400">
                  未找到匹配的 Agent
                </div>
              )}
            </div>
          </Card>
        </div>
      </div>
    </div>
  )
}
