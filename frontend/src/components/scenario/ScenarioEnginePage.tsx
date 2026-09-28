import { useAnalysisStore } from '../../store/useAnalysisStore'
import { SectionTitle } from '../common/SectionTitle'
import { Badge } from '../common/Badge'
import { Card } from '../common/Card'
import { MetricTile } from '../common/Material'

type ScenarioBranch = {
  id: 'bullish' | 'base' | 'bearish'
  name: string
  description: string
  probability: string
  color: string
}

type ScenarioEngineView = {
  hasOutput: boolean
  status: string
  calculationMode: string
  dvgPermission: string
  riskRewardQuality: string
  expectedReturnBand: string
  auditId: string
  branches: ScenarioBranch[]
  sensitivities: string[]
  invalidations: string[]
}

const branchStyles: Record<ScenarioBranch['id'], Pick<ScenarioBranch, 'name' | 'color'>> = {
  bullish: { name: '乐观情景', color: 'border-emerald-200 bg-emerald-50' },
  base: { name: '基准情景', color: 'border-slate-200 bg-slate-50' },
  bearish: { name: '悲观情景', color: 'border-rose-200 bg-rose-50' },
}

export function ScenarioEnginePage() {
  const { currentRun } = useAnalysisStore()

  if (!currentRun) return <div className="text-sm text-slate-500">加载中...</div>

  const killSwitch = currentRun.killSwitch
  const moduleData = readScenarioModuleData(currentRun)
  const scenarioView = buildScenarioEngineView(
    currentRun.agentOutputs?.scenario_engine,
    currentRun.dvg?.scenarioPermission,
    moduleData
  )

  return (
    <div className="space-y-6">
      <SectionTitle title="情景引擎" subtitle="牛市、熊市、基准情景与蒙特卡洛模拟。" dataMode={currentRun?.dataMode} />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[
          { label: '运行模式', value: currentRun.runMode, status: 'PASS' as const },
          { label: '最终动作', value: currentRun.finalAction, status: currentRun.finalAction === 'WAIT' ? 'WARN' as const : 'PASS' as const },
          { label: '熔断开关', value: killSwitch?.active ? '已触发' : '未触发', status: killSwitch?.active ? 'WARN' as const : 'PASS' as const },
          { label: '数据模式', value: currentRun.dataMode ?? 'MOCK', status: 'WARN' as const },
        ].map((item) => (
          <MetricTile
            key={item.label}
            label={item.label}
            value={item.value}
            helper={item.status}
            tone={item.status === 'PASS' ? 'success' : 'warning'}
          />
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="情景分支">
          {scenarioView.hasOutput ? (
            <div className="space-y-3">
              {scenarioView.branches.map((scenario) => (
                <div key={scenario.id} className={`rounded-md border ${scenario.color} p-3`}>
                  <div className="mb-1 flex items-center justify-between gap-3">
                    <span className="text-sm font-medium text-slate-900">{scenario.name}</span>
                    <Badge status={scenarioView.status}>{scenario.probability}</Badge>
                  </div>
                  <div className="text-xs leading-5 text-slate-600">{scenario.description}</div>
                </div>
              ))}
            </div>
          ) : (
            <div className="rounded-md border border-dashed border-slate-200 bg-slate-50 p-4 text-sm text-slate-500">
              等待 Scenario Engine 输出
            </div>
          )}
        </Card>

        <Card title="情景参数">
          <div className="space-y-3 text-sm">
            <ParameterRow label="状态" value={<Badge status={scenarioView.status}>{scenarioView.status}</Badge>} />
            <ParameterRow label="计算模式" value={scenarioView.calculationMode} />
            <ParameterRow label="情景权限" value={<Badge status={scenarioView.dvgPermission}>{scenarioView.dvgPermission}</Badge>} />
            <ParameterRow label="赔率质量" value={scenarioView.riskRewardQuality} />
            <ParameterRow label="预期收益区间" value={scenarioView.expectedReturnBand} />
            <ParameterRow label="审计编号" value={scenarioView.auditId} />

            {scenarioView.sensitivities.length > 0 && (
              <div>
                <div className="mb-2 text-xs font-medium text-slate-500">主要敏感因子</div>
                <div className="flex flex-wrap gap-2">
                  {scenarioView.sensitivities.map((item) => (
                    <Badge key={item} status="WARN">{item}</Badge>
                  ))}
                </div>
              </div>
            )}

            {scenarioView.invalidations.length > 0 && (
              <div>
                <div className="mb-2 text-xs font-medium text-slate-500">技术面失效情景</div>
                <div className="flex flex-wrap gap-2">
                  {scenarioView.invalidations.map((item) => (
                    <Badge key={item} status="WARN">{item}</Badge>
                  ))}
                </div>
              </div>
            )}

            <div className="mt-2 text-xs leading-5 text-slate-400">
              情景分析为定性参考框架，不作为交易决策的直接依据。
              蒙特卡洛模拟依赖参数假设，实际分布可能与假设有偏差。
            </div>
          </div>
        </Card>
      </div>

      {killSwitch?.blockedPaths?.length > 0 && (
        <Card title="阻断路径">
          <div className="flex flex-wrap gap-2">
            {killSwitch.blockedPaths.map((p: string, i: number) => (
              <Badge key={i} status="FAIL">{p}</Badge>
            ))}
          </div>
        </Card>
      )}

      {killSwitch?.allowedPaths?.length > 0 && (
        <Card title="允许路径">
          <div className="flex flex-wrap gap-2">
            {killSwitch.allowedPaths.map((p: string, i: number) => (
              <Badge key={i} status="PASS">{p}</Badge>
            ))}
          </div>
        </Card>
      )}
    </div>
  )
}

function ParameterRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <MetricTile label={label} value={value} className="!rounded-md !px-3 !py-2 !shadow-none" />
  )
}

function buildScenarioEngineView(agentOutput: unknown, scenarioPermission?: string, moduleData?: Record<string, unknown>): ScenarioEngineView {
  const output = asRecord(agentOutput)
  const hasOutput = Boolean(output && Object.keys(output).length > 0)
  const data = output ?? {}

  const status = text(data.status) ?? text(data.scenario_status) ?? (hasOutput ? 'PASS' : 'WAIT')
  const calculationMode = text(data.calculation_mode) ?? text(data.calculationMode) ?? text(moduleData?.calculation_mode) ?? 'PENDING'
  const dvgPermission = text(data.dvgPermission) ?? text(data.dvg_permission) ?? text(moduleData?.dvgPermission) ?? scenarioPermission ?? 'UNKNOWN'

  return {
    hasOutput,
    status,
    calculationMode,
    dvgPermission,
    riskRewardQuality: text(data.risk_reward_quality) ?? text(data.riskRewardQuality) ?? 'UNKNOWN',
    expectedReturnBand: text(data.weighted_expected_return_band) ?? text(data.weightedExpectedReturnBand) ?? 'UNKNOWN',
    auditId: text(data.audit_id) ?? text(data.auditId) ?? 'N/A',
    branches: buildScenarioBranches(data),
    sensitivities: textList(data.main_sensitivity ?? data.mainSensitivity),
    invalidations: invalidationLabels(moduleData?.technicalInvalidationScenarios ?? data.technicalInvalidationScenarios),
  }
}

function buildScenarioBranches(data: Record<string, unknown>): ScenarioBranch[] {
  return (['bullish', 'base', 'bearish'] as const).map((id) => {
    const llmKey = id === 'bullish' ? 'bull_case' : id === 'base' ? 'base_case' : 'bear_case'
    const rulePayload = asRecord(data[id])
    const description = text(data[llmKey]) ?? text(rulePayload?.premise) ?? '等待 Scenario Engine 输出'
    const probability = text(rulePayload?.probability) ?? text(data[`${id}_probability`]) ?? '定性'
    return {
      id,
      ...branchStyles[id],
      description,
      probability,
    }
  })
}

function readScenarioModuleData(run: unknown): Record<string, unknown> | undefined {
  const runRecord = asRecord(run)
  const agentModuleResults = asRecord(runRecord?.agentModuleResults)
  const scenarioModuleResult = asRecord(agentModuleResults?.scenario_engine)
  return asRecord(scenarioModuleResult?.data)
}

function invalidationLabels(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value
    .map((item) => {
      const record = asRecord(item)
      return text(record?.code) ?? text(record?.label) ?? text(item)
    })
    .filter((item): item is string => Boolean(item))
}

function textList(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.map((item) => text(item)).filter((item): item is string => Boolean(item))
}

function text(value: unknown): string | undefined {
  if (typeof value === 'string') return value.trim() || undefined
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return undefined
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : undefined
}
