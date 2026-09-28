import { useCallback, useEffect, useMemo, useState } from 'react'
import { SectionTitle } from '../common/SectionTitle'
import { Card } from '../common/Card'
import { Badge } from '../common/Badge'
import { MetricTile, TableShell } from '../common/Material'
import { ConfigVersionItem, getConfigSchema, getConfigVersions, restoreExternalConfig } from '../../api/configClient'
import { ConfigSchemaItem } from '../../types'
import { roleAllows, useOperatorContext } from '../../store/operatorContext'

interface RestoreDialogState {
  version: ConfigVersionItem
  approvalId: string
  reason: string
  confirmSecretSafe: boolean
}

export function ConfigVersionsPage() {
  const [schema, setSchema] = useState<ConfigSchemaItem[]>([])
  const [versions, setVersions] = useState<ConfigVersionItem[]>([])
  const [schemaLoading, setSchemaLoading] = useState(true)
  const [versionsLoading, setVersionsLoading] = useState(true)
  const [schemaError, setSchemaError] = useState<string | null>(null)
  const [versionsError, setVersionsError] = useState<string | null>(null)
  const [restoreStatus, setRestoreStatus] = useState<string | null>(null)
  const [restoringAuditId, setRestoringAuditId] = useState<string | null>(null)
  const [profileFilter, setProfileFilter] = useState('')
  const [actorFilter, setActorFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [restoreDialog, setRestoreDialog] = useState<RestoreDialogState | null>(null)
  const operator = useOperatorContext()
  const canRestoreExternalConfig = roleAllows(operator.role, 'admin')
  const configRestoreDisabledReason = canRestoreExternalConfig
    ? undefined
    : '配置批准恢复需要 admin 权限。'

  const loadSchema = useCallback(async () => {
    setSchemaLoading(true)
    setSchemaError(null)
    try {
      setSchema(await getConfigSchema())
    } catch {
      setSchemaError('配置结构加载失败。')
    } finally {
      setSchemaLoading(false)
    }
  }, [])

  const loadVersions = useCallback(async () => {
    setVersionsLoading(true)
    setVersionsError(null)
    try {
      setVersions(await getConfigVersions(true, {
        profile_id: profileFilter,
        created_by: actorFilter,
        status: statusFilter,
        limit: 1000,
      }))
    } catch {
      setVersionsError('配置版本历史加载失败。')
    } finally {
      setVersionsLoading(false)
    }
  }, [actorFilter, profileFilter, statusFilter])

  useEffect(() => {
    loadSchema()
  }, [loadSchema])

  useEffect(() => {
    loadVersions()
  }, [loadVersions])

  const openRestoreDialog = useCallback((version: ConfigVersionItem) => {
    if (!canRestoreExternalConfig || !version.profile_id) return
    setVersionsError(null)
    setRestoreStatus(null)
    setRestoreDialog({
      version,
      approvalId: '',
      reason: '',
      confirmSecretSafe: false,
    })
  }, [canRestoreExternalConfig])

  const closeRestoreDialog = useCallback(() => {
    if (restoreDialog && restoringAuditId === restoreDialog.version.audit_id) return
    setRestoreDialog(null)
  }, [restoreDialog, restoringAuditId])

  const updateRestoreDialog = useCallback((changes: Partial<Omit<RestoreDialogState, 'version'>>) => {
    setRestoreDialog((current) => current ? { ...current, ...changes } : current)
  }, [])

  const handleExternalRestore = useCallback(async () => {
    const profileId = restoreDialog?.version.profile_id
    if (!profileId) return
    const approvalId = restoreDialog.approvalId.trim()
    const reason = restoreDialog.reason.trim()
    if (!canRestoreExternalConfig || !approvalId || !reason || !restoreDialog.confirmSecretSafe) return
    const version = restoreDialog.version
    setRestoringAuditId(version.audit_id)
    setRestoreStatus(null)
    setVersionsError(null)
    try {
      const result = await restoreExternalConfig({
        profile_id: profileId,
        audit_id: version.audit_id,
        reason,
        approval_id: approvalId,
        approved_by: operator.id,
        confirm_secret_safe: restoreDialog.confirmSecretSafe,
      })
      setRestoreStatus(`已恢复 ${result.profile_id} v${result.target_version}；审计 ${result.restore_audit_id}`)
      setRestoreDialog(null)
      await loadVersions()
    } catch (error) {
      setVersionsError(error instanceof Error ? error.message : '外部配置恢复失败。')
    } finally {
      setRestoringAuditId(null)
    }
  }, [canRestoreExternalConfig, loadVersions, operator.id, restoreDialog])

  const profileOptions = useMemo(
    () => Array.from(new Set(versions.map((item) => item.profile_id || 'default'))).sort(),
    [versions],
  )
  const actorOptions = useMemo(
    () => Array.from(new Set(versions.map((item) => item.created_by || 'system'))).sort(),
    [versions],
  )
  const statusOptions = useMemo(
    () => Array.from(new Set(versions.map((item) => item.status || 'unknown'))).sort(),
    [versions],
  )
  const loading = schemaLoading && versionsLoading && schema.length === 0 && versions.length === 0

  if (loading) {
    return <div>加载中...</div>
  }

  return (
    <div className="space-y-6">
      <SectionTitle title="配置版本" subtitle="查看配置结构和跨工作面的版本治理历史。" />

      <Card title="版本历史与治理" className="!rounded-lg !shadow-none">
        <div className="mb-4 flex flex-wrap items-center gap-3 rounded-md border border-slate-100 bg-slate-50 px-3 py-2 text-xs text-slate-600">
          <span data-testid="config-approved-restore-role">
            角色：{operator.role}；批准恢复：{canRestoreExternalConfig ? 'admin' : '已阻断'}
          </span>
          {!canRestoreExternalConfig ? (
            <span data-testid="config-approved-restore-disabled-reason" className="text-amber-700">
              {configRestoreDisabledReason}
            </span>
          ) : null}
        </div>
        {versionsError ? (
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-md border border-rose-100 bg-rose-50 px-3 py-2 text-sm text-rose-700">
            <span>{versionsError}</span>
            <button type="button" onClick={loadVersions} className="rounded-md border border-rose-200 bg-white px-3 py-1 text-xs font-medium text-rose-700">重试</button>
          </div>
        ) : null}
        {restoreStatus ? (
          <div className="mb-4 rounded-md border border-emerald-100 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
            {restoreStatus}
          </div>
        ) : null}
        <div className="mb-4 grid gap-3 md:grid-cols-3">
          <label className="text-xs font-medium text-slate-600">
            Surface / 工作面
            <select value={profileFilter} onChange={(event) => setProfileFilter(event.target.value)} className="mt-1 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800">
              <option value="">全部工作面</option>
              {profileOptions.map((profile) => <option key={profile} value={profile}>{profile}</option>)}
            </select>
          </label>
          <label className="text-xs font-medium text-slate-600">
            操作者
            <select value={actorFilter} onChange={(event) => setActorFilter(event.target.value)} className="mt-1 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800">
              <option value="">全部操作者</option>
              {actorOptions.map((actor) => <option key={actor} value={actor}>{actor}</option>)}
            </select>
          </label>
          <label className="text-xs font-medium text-slate-600">
            状态
            <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} className="mt-1 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800">
              <option value="">全部状态</option>
              {statusOptions.map((status) => <option key={status} value={status}>{status}</option>)}
            </select>
          </label>
        </div>
        <div className="mb-4 grid gap-3 sm:grid-cols-3">
          <MetricTile className="!rounded-lg !p-3 !shadow-none" label="版本记录" value={versions.length} helper="当前筛选结果" tone="primary" />
          <MetricTile className="!rounded-lg !p-3 !shadow-none" label="需审批" value={versions.filter((version) => version.approval_required).length} helper="approval_required" tone="warning" />
          <MetricTile className="!rounded-lg !p-3 !shadow-none" label="可回滚" value={versions.filter((version) => version.rollback_available).length} helper="rollback_available" tone="success" />
        </div>
        {versionsLoading ? (
          <div className="text-sm text-slate-500">正在加载版本历史...</div>
        ) : versions.length === 0 ? (
          <div className="text-sm text-slate-500">暂无配置版本记录。</div>
        ) : (
          <TableShell className="!rounded-lg !shadow-none">
            <div className="overflow-x-auto">
              <table className="institution-table">
                <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className="px-3 py-2 font-semibold">工作面 / 版本</th>
                    <th className="px-3 py-2 font-semibold">摘要</th>
                    <th className="px-3 py-2 font-semibold">治理状态</th>
                    <th className="px-3 py-2 font-semibold">回滚策略</th>
                    <th className="px-3 py-2 font-semibold">审计</th>
                    <th className="px-3 py-2 font-semibold">操作</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 bg-white">
                  {versions.slice(0, 30).map((version) => (
                    <tr key={`${version.profile_id ?? 'default'}-${version.audit_id}`} className="align-top transition hover:bg-slate-50">
                      <td className="px-3 py-3">
                        <div className="font-semibold text-slate-950">{version.profile_id ?? 'default'} v{version.version}</div>
                        <div className="mt-1 text-xs text-slate-500">{version.created_at}</div>
                        <div className="mt-1 text-xs text-slate-500">创建者：{version.created_by || 'system'}</div>
                      </td>
                      <td className="max-w-md px-3 py-3 text-slate-600">{version.change_summary || '暂无摘要'}</td>
                      <td className="px-3 py-3">
                        <div className="flex flex-wrap gap-1.5">
                          <Badge status={versionStatus(version.status)} className="rounded-md px-2 py-0.5">{version.status}</Badge>
                          <Badge status={version.rollback_available ? 'PASS' : 'WAIT'} className="rounded-md px-2 py-0.5">{version.rollback_available ? '可回滚' : '回滚锁定'}</Badge>
                          {version.approval_required ? <Badge status="WARN" className="rounded-md px-2 py-0.5">需要审批</Badge> : null}
                          {version.snapshot_redacted ? <Badge status="READ_ONLY" className="rounded-md px-2 py-0.5">快照已脱敏</Badge> : null}
                        </div>
                        {version.effective_scope?.length ? (
                          <div className="mt-2 text-xs text-slate-500">范围：{version.effective_scope.join(' / ')}</div>
                        ) : null}
                      </td>
                      <td className="min-w-64 px-3 py-3 text-xs leading-5 text-slate-600">
                        {version.rollback_policy ? (
                          <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
                            <div className="font-semibold text-slate-800">{version.rollback_policy.supported ? '支持直接回滚' : '直接回滚已阻断'}</div>
                            {version.rollback_policy.secret_safe_required ? <div>需要安全密钥恢复</div> : null}
                            {version.rollback_policy.blocked_reason ? <div>{version.rollback_policy.blocked_reason}</div> : null}
                            {version.rollback_policy.approval_gate ? (
                              <div className="mt-2 rounded-md border border-amber-100 bg-amber-50 px-2 py-1.5 text-amber-800">
                                <div className="font-medium">审批门禁：{version.rollback_policy.approval_gate.status || 'NOT_REQUIRED'}</div>
                                <div className="mt-1 flex flex-wrap gap-2">
                                  {version.rollback_policy.approval_gate.scope ? <span>范围：{version.rollback_policy.approval_gate.scope}</span> : null}
                                  {version.rollback_policy.approval_gate.approver_role ? <span>角色：{version.rollback_policy.approval_gate.approver_role}</span> : null}
                                  {version.rollback_policy.approval_gate.secret_vault_version_required ? <span>需要密钥库版本审批</span> : null}
                                  {version.rollback_policy.approval_gate.restore_source ? <span>来源：{version.rollback_policy.approval_gate.restore_source}</span> : null}
                                </div>
                                {version.rollback_policy.approval_gate.required_secret_refs?.length ? (
                                  <div className="mt-1 text-amber-700">密钥引用：{version.rollback_policy.approval_gate.required_secret_refs.length}</div>
                                ) : null}
                              </div>
                            ) : null}
                          </div>
                        ) : '无回滚策略'}
                      </td>
                      <td className="px-3 py-3 font-mono text-xs text-slate-500">{version.audit_id}</td>
                      <td className="px-3 py-3">
                        {version.rollback_policy?.approval_gate?.secret_vault_version_required ? (
                          <button
                            type="button"
                            onClick={() => openRestoreDialog(version)}
                            disabled={!canRestoreExternalConfig || restoringAuditId === version.audit_id}
                            title={!canRestoreExternalConfig ? configRestoreDisabledReason : undefined}
                            data-testid="config-approved-restore-open"
                            className="rounded-md border border-amber-200 bg-white px-2 py-1 text-xs font-medium text-amber-700 disabled:cursor-not-allowed disabled:opacity-50"
                          >
                            {restoringAuditId === version.audit_id ? '恢复中...' : '批准恢复'}
                          </button>
                        ) : (
                          <span className="text-xs text-slate-400">无操作</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </TableShell>
        )}
      </Card>

      <Card title="配置结构与配置项" className="!rounded-lg !shadow-none">
        {schemaError ? (
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-md border border-rose-100 bg-rose-50 px-3 py-2 text-sm text-rose-700">
            <span>{schemaError}</span>
            <button type="button" onClick={loadSchema} className="rounded-md border border-rose-200 bg-white px-3 py-1 text-xs font-medium text-rose-700">重试</button>
          </div>
        ) : null}
        <div className="text-sm text-slate-600">
          {schemaLoading ? (
            <div className="text-sm text-slate-500">正在加载 schema...</div>
          ) : (
            <TableShell className="!rounded-lg !shadow-none">
              <div className="overflow-x-auto">
                <table className="institution-table">
                  <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                    <tr>
                      <th className="px-3 py-2 font-semibold">配置项</th>
                      <th className="px-3 py-2 font-semibold">层级 / 类型</th>
                      <th className="px-3 py-2 font-semibold">默认值</th>
                      <th className="px-3 py-2 font-semibold">当前值</th>
                      <th className="px-3 py-2 font-semibold">方向</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 bg-white">
                    {schema.map((item) => (
                      <tr key={item.key} className="align-top transition hover:bg-slate-50">
                        <td className="max-w-md px-3 py-3">
                          <div className="font-semibold text-slate-950">{item.label}</div>
                          <div className="mt-1 break-all font-mono text-xs text-slate-500">{item.key}</div>
                          <div className="mt-2 text-xs leading-5 text-slate-600">{item.description}</div>
                        </td>
                        <td className="px-3 py-3">
                          <div className="flex flex-wrap gap-1.5">
                            <Badge status={item.layer === 'LOCKED' ? 'BLOCKED' : item.layer === 'SAFE_RUNTIME' ? 'PASS' : item.layer === 'REVIEW_REQUIRED' ? 'WARN' : 'WAIT'} className="rounded-md px-2 py-0.5">{item.layer}</Badge>
                            <span className="rounded-md border border-slate-200 bg-slate-50 px-2 py-0.5 text-xs font-medium text-slate-600">{item.type}</span>
                            {!item.editable ? <Badge status="READ_ONLY" className="rounded-md px-2 py-0.5">只读</Badge> : null}
                          </div>
                        </td>
                        <td className="px-3 py-3 font-mono text-xs text-slate-500">{renderConfigValue(item.default)}</td>
                        <td className="px-3 py-3 font-mono text-xs text-slate-900">
                          <span className={item.current !== item.default ? 'rounded-md bg-cyan-50 px-2 py-1 text-cyan-800' : ''}>
                            {renderConfigValue(item.current)}
                          </span>
                        </td>
                        <td className="px-3 py-3">
                          <div className={`rounded-lg border px-3 py-2 text-xs leading-5 ${item.direction === 'CONSERVATIVE_ONLY' ? 'border-amber-200 bg-amber-50 text-amber-800' : 'border-slate-200 bg-slate-50 text-slate-600'}`}>
                            {item.direction === 'CONSERVATIVE_ONLY' ? '仅保守方向' : '任意方向'}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </TableShell>
          )}
        </div>
      </Card>
      {restoreDialog ? (
        <div
          data-testid="config-approved-restore-modal"
          className="fixed inset-0 z-50 grid place-items-center bg-slate-200/70 px-4 py-6 backdrop-blur-sm"
          role="dialog"
          aria-modal="true"
          aria-labelledby="config-approved-restore-title"
        >
          <div className="w-full max-w-xl rounded-md bg-white p-5 shadow-xl">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 id="config-approved-restore-title" className="text-base font-semibold text-slate-950">批准恢复</h2>
                <div className="mt-1 text-xs text-slate-500">
                  {restoreDialog.version.profile_id} v{restoreDialog.version.version} / {restoreDialog.version.audit_id}
                </div>
              </div>
              <button
                type="button"
                onClick={closeRestoreDialog}
                disabled={restoringAuditId === restoreDialog.version.audit_id}
                className="rounded-md border border-slate-200 px-2 py-1 text-xs font-medium text-slate-600 disabled:cursor-not-allowed disabled:opacity-50"
              >
                关闭
              </button>
            </div>
            <div className="mt-4 grid gap-3">
              <label className="text-xs font-medium text-slate-600">
                审批 ID
                <input
                  data-testid="config-approved-restore-approval-id"
                  value={restoreDialog.approvalId}
                  onChange={(event) => updateRestoreDialog({ approvalId: event.target.value })}
                  className="mt-1 h-9 w-full rounded-md border border-slate-200 px-3 text-sm text-slate-900 outline-none focus:border-amber-400"
                  autoComplete="off"
                />
              </label>
              <label className="text-xs font-medium text-slate-600">
                恢复原因
                <textarea
                  data-testid="config-approved-restore-reason"
                  value={restoreDialog.reason}
                  onChange={(event) => updateRestoreDialog({ reason: event.target.value })}
                  className="mt-1 min-h-20 w-full rounded-md border border-slate-200 px-3 py-2 text-sm text-slate-900 outline-none focus:border-amber-400"
                />
              </label>
              <div className="rounded-md border border-amber-100 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                <div className="font-medium">密钥引用：{restoreDialog.version.rollback_policy?.approval_gate?.required_secret_refs?.length ?? 0}</div>
                {restoreDialog.version.rollback_policy?.approval_gate?.restore_source ? (
                  <div className="mt-1">来源：{restoreDialog.version.rollback_policy.approval_gate.restore_source}</div>
                ) : null}
              </div>
              <label className="flex items-start gap-2 text-xs font-medium text-slate-700">
                <input
                  data-testid="config-approved-restore-confirm-secret-safe"
                  type="checkbox"
                  checked={restoreDialog.confirmSecretSafe}
                  onChange={(event) => updateRestoreDialog({ confirmSecretSafe: event.target.checked })}
                  className="mt-0.5"
                />
                <span>已确认密钥安全审批</span>
              </label>
            </div>
            <div className="mt-5 flex flex-wrap justify-end gap-2">
              {!canRestoreExternalConfig ? (
                <div data-testid="config-approved-restore-modal-disabled-reason" className="w-full text-right text-xs text-amber-700">
                  {configRestoreDisabledReason}
                </div>
              ) : null}
              <button
                type="button"
                onClick={closeRestoreDialog}
                disabled={restoringAuditId === restoreDialog.version.audit_id}
                className="rounded-md border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                取消
              </button>
              <button
                type="button"
                data-testid="config-approved-restore-submit"
                onClick={handleExternalRestore}
                disabled={
                  restoringAuditId === restoreDialog.version.audit_id
                  || !canRestoreExternalConfig
                  || !restoreDialog.approvalId.trim()
                  || !restoreDialog.reason.trim()
                  || !restoreDialog.confirmSecretSafe
                }
                className="rounded-md border border-amber-300 bg-amber-500 px-3 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
              >
                {restoringAuditId === restoreDialog.version.audit_id ? '恢复中...' : '恢复'}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}

function versionStatus(status: string) {
  const normalized = String(status || '').toUpperCase()
  if (['ACTIVE', 'APPLIED', 'CURRENT', 'APPROVED'].includes(normalized)) return 'PASS'
  if (['PENDING', 'PENDING_REVIEW', 'REVIEW', 'DRAFT'].includes(normalized)) return 'WARN'
  if (['REJECTED', 'FAILED', 'BLOCKED'].includes(normalized)) return 'FAIL'
  return 'WAIT'
}

function renderConfigValue(value: unknown) {
  if (value === undefined || value === null || value === '') return '-'
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}
