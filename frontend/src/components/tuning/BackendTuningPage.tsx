import { useEffect, useState } from 'react'
import { SectionTitle } from '../common/SectionTitle'
import { Card } from '../common/Card'
import { Badge } from '../common/Badge'
import { MetricTile, TableShell } from '../common/Material'
import { getConfigSchema, getCurrentConfig, validateConfigChange, patchRuntimeConfig, createConfigDraft } from '../../api/configClient'
import { ConfigDraft, ConfigProfile, ConfigSchemaItem, PolicyCheckResult } from '../../types'
import { roleAllows, useOperatorContext } from '../../store/operatorContext'

export function BackendTuningPage() {
  const operator = useOperatorContext()
  const canManageBackendTuning = roleAllows(operator.role, 'admin')
  const tuningWriteDisabledReason = canManageBackendTuning
    ? ''
    : `后端调参写入需要 admin 权限。当前角色：${operator.role}。`
  const [profile, setProfile] = useState<ConfigProfile | null>(null)
  const [schema, setSchema] = useState<ConfigSchemaItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [draftChanges, setDraftChanges] = useState<Record<string, any>>({})
  const [draftReason, setDraftReason] = useState('安全审查调整')
  const [validationResult, setValidationResult] = useState<PolicyCheckResult | null>(null)
  const [draftResult, setDraftResult] = useState<ConfigDraft | null>(null)

  useEffect(() => {
    async function fetchConfig() {
      setLoading(true)
      try {
        const current = await getCurrentConfig()
        const schemaItems = await getConfigSchema()
        setProfile(current)
        setSchema(schemaItems)
      } catch {
        setError('无法获取配置数据，请检查后端服务。')
      } finally {
        setLoading(false)
      }
    }

    fetchConfig()
  }, [])

  async function handleChangeItem(key: string, value: any) {
    const nextChanges = { ...draftChanges, [key]: value }
    setDraftChanges(nextChanges)
    const result = await validateConfigChange({ changes: nextChanges })
    setValidationResult(result)
  }

  async function handleApplyRuntimeChange() {
    if (!canManageBackendTuning) return
    try {
      await patchRuntimeConfig({ changes: draftChanges })
      const current = await getCurrentConfig()
      setProfile(current)
      setDraftResult(null)
      setError(null)
      setValidationResult({ passed: true, warnings: [], blocked_reasons: [], level: 'SAFE' })
    } catch {
      setError('应用运行时配置失败。')
    }
  }

  async function handleCreateDraft() {
    if (!canManageBackendTuning) return
    try {
      const result = await createConfigDraft({ changes: draftChanges, reason: draftReason })
      setDraftResult(result)
      setValidationResult(result.policy_check ?? null)
      setError(null)
    } catch {
      setError('提交配置草稿失败。')
    }
  }

  if (loading) {
    return <div>加载中...</div>
  }

  if (error) {
    return (
      <Card title="后端调参异常" className="!rounded-lg !shadow-none">
        <div className="text-sm text-rose-600">{error}</div>
      </Card>
    )
  }

  return (
    <div className="space-y-6">
      <SectionTitle title="后端调参" subtitle="配置调优与策略校验。" />

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="当前配置摘要" className="!rounded-lg !shadow-none">
          <div className="grid gap-3 sm:grid-cols-2">
            <MetricTile className="!rounded-lg !p-3 !shadow-none" label="配置版本" value={profile?.version ?? '-'} tone="primary" />
            <MetricTile className="!rounded-lg !p-3 !shadow-none" label="默认运行模式" value={renderConfigValue(profile?.safe_runtime_config.run_mode_default)} />
            <MetricTile className="!rounded-lg !p-3 !shadow-none" label="工具预算" value={renderConfigValue(profile?.safe_runtime_config.tool_budget)} tone="info" />
            <MetricTile className="!rounded-lg !p-3 !shadow-none" label="最大并行节点" value={renderConfigValue(profile?.safe_runtime_config.max_parallel_nodes)} tone="success" />
          </div>
        </Card>

        <Card title="锁定护栏" className="!rounded-lg !shadow-none">
          <TableShell className="!rounded-lg !shadow-none">
          <div className="divide-y divide-slate-100 text-sm text-slate-600">
            {Object.entries(profile?.locked_guardrails ?? {}).map(([key, value]) => (
              <div key={key} className="grid gap-3 px-3 py-2 md:grid-cols-[1fr_180px]">
                <div className="break-all font-medium text-slate-800">{key}</div>
                <div className="font-mono text-xs text-slate-500">{renderConfigValue(value)}</div>
              </div>
            ))}
          </div>
          </TableShell>
        </Card>
      </div>

      <Card title="配置项调优" className="!rounded-lg !shadow-none">
        <div className="space-y-4">
          <div className="flex flex-wrap gap-2 text-xs text-slate-500">
            <span data-testid="backend-tuning-role">角色：{operator.role}；写入：{canManageBackendTuning ? 'admin' : '已阻断'}</span>
            {!canManageBackendTuning ? (
              <span data-testid="backend-tuning-disabled-reason" className="text-amber-700">{tuningWriteDisabledReason}</span>
            ) : null}
          </div>
          <TableShell className="!rounded-lg !shadow-none">
            <div className="overflow-x-auto">
              <table className="institution-table">
                <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className="px-3 py-2 font-semibold">配置项</th>
                    <th className="px-3 py-2 font-semibold">层级</th>
                    <th className="px-3 py-2 font-semibold">当前值</th>
                    <th className="px-3 py-2 font-semibold">草稿值</th>
                    <th className="px-3 py-2 font-semibold">调优输入</th>
                    <th className="px-3 py-2 font-semibold">影响</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 bg-white">
                  {schema.map((item) => {
                    const draftValue = draftChanges[item.key] ?? item.current
                    const changed = draftChanges[item.key] !== undefined && draftValue !== item.current
                    return (
                      <tr key={item.key} className="align-top transition hover:bg-slate-50">
                        <td className="max-w-sm px-3 py-3">
                          <div className="font-semibold text-slate-950">{item.label}</div>
                          <div className="mt-1 break-all text-xs text-slate-500">{item.key}</div>
                          <div className="mt-2 text-xs leading-5 text-slate-600">{item.description}</div>
                        </td>
                        <td className="px-3 py-3">
                          <Badge status={item.layer === 'LOCKED' ? 'BLOCKED' : item.layer === 'SAFE_RUNTIME' ? 'PASS' : item.layer === 'REVIEW_REQUIRED' ? 'WARN' : 'WAIT'} className="rounded-md px-2 py-0.5">{item.layer}</Badge>
                        </td>
                        <td className="px-3 py-3 font-mono text-xs text-slate-600">{renderConfigValue(item.current)}</td>
                        <td className="px-3 py-3 font-mono text-xs text-slate-900">
                          <span className={changed ? 'rounded-md bg-cyan-50 px-2 py-1 text-cyan-800' : ''}>{renderConfigValue(draftValue)}</span>
                        </td>
                        <td className="px-3 py-3">
                          {item.type === 'select' ? (
                            <select
                              value={draftChanges[item.key] ?? item.current}
                              onChange={(event) => handleChangeItem(item.key, event.target.value)}
                              className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900"
                            >
                              {item.options?.map((option) => (
                                <option key={option} value={option}>{option}</option>
                              ))}
                            </select>
                          ) : (
                            <input
                              type="number"
                              value={draftChanges[item.key] ?? item.current}
                              min={item.min ?? undefined}
                              max={item.max ?? undefined}
                              onChange={(event) => handleChangeItem(item.key, Number(event.target.value))}
                              className="w-36 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900"
                            />
                          )}
                        </td>
                        <td className="px-3 py-3">
                          <div className={`rounded-lg border px-3 py-2 text-xs leading-5 ${changed ? 'border-cyan-200 bg-cyan-50 text-cyan-800' : 'border-slate-200 bg-slate-50 text-slate-600'}`}>
                            <div className="font-semibold">{changed ? '待校验变更' : '未变更'}</div>
                            <div>{item.direction === 'CONSERVATIVE_ONLY' ? '仅允许保守方向；策略校验会阻断激进调整。' : '允许任意方向；仍需通过策略校验与审批流程。'}</div>
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </TableShell>

          <div className="space-y-2">
            <div className="text-sm text-slate-700">变更原因</div>
            <textarea
              rows={3}
              className="w-full rounded-lg border border-slate-200 bg-white p-3 text-sm text-slate-900"
              value={draftReason}
              onChange={(event) => setDraftReason(event.target.value)}
            />
          </div>

          <div className="flex flex-col gap-3 sm:flex-row">
            <button
              type="button"
              data-testid="backend-tuning-apply-runtime"
              className="rounded-lg bg-emerald-600 px-5 py-3 text-sm font-semibold text-white transition hover:bg-emerald-700 disabled:opacity-60"
              onClick={handleApplyRuntimeChange}
              disabled={!canManageBackendTuning}
              title={tuningWriteDisabledReason || undefined}
            >
              应用安全运行配置
            </button>
            <button
              type="button"
              data-testid="backend-tuning-submit-draft"
              className="rounded-lg bg-sky-600 px-5 py-3 text-sm font-semibold text-white transition hover:bg-sky-700 disabled:opacity-60"
              onClick={handleCreateDraft}
              disabled={!canManageBackendTuning}
              title={tuningWriteDisabledReason || undefined}
            >
              提交审核草稿
            </button>
          </div>

          {validationResult && (
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
              <div className="mb-3 flex flex-wrap items-center gap-2">
                <span className="text-sm font-semibold text-slate-950">策略校验结果</span>
                <Badge status={validationResult.passed ? 'PASS' : 'BLOCKED'}>{validationResult.passed ? '通过' : '未通过'}</Badge>
                <Badge status={validationResult.level}>{validationResult.level}</Badge>
              </div>
              <div className="grid gap-3 text-sm text-slate-600 md:grid-cols-2">
                {draftResult ? (
                  <div className="rounded-lg border border-slate-200 bg-white px-3 py-2">草稿：{draftResult.draft_id ?? draftResult.draftId} / {draftResult.status}</div>
                ) : null}
                <div className="rounded-lg border border-slate-200 bg-white px-3 py-2">是否通过：{validationResult.passed ? '是' : '否'}</div>
                <div className="rounded-lg border border-slate-200 bg-white px-3 py-2">等级：{validationResult.level}</div>
                {validationResult.warnings?.length > 0 && (
                  <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-amber-800 md:col-span-2">警告：{validationResult.warnings.join(', ')}</div>
                )}
                {(validationResult.blocked_reasons?.length ?? 0) > 0 && (
                  <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-rose-800 md:col-span-2">阻断原因：{(validationResult.blocked_reasons ?? []).join(', ')}</div>
                )}
              </div>
            </div>
          )}
        </div>
      </Card>
    </div>
  )
}

function renderConfigValue(value: unknown) {
  if (value === undefined || value === null || value === '') return '-'
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}
