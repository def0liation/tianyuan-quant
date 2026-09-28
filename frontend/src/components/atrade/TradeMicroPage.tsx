import { useAnalysisStore } from '../../store/useAnalysisStore'
import { SectionTitle } from '../common/SectionTitle'
import { Badge } from '../common/Badge'
import { Card } from '../common/Card'
import { MetricTile, TableShell } from '../common/Material'
import { Wifi, WifiOff } from 'lucide-react'
import { SourceBadge, SourceNote } from '../common/SourceBadge'
import { portfolioKind } from '../../utils/dataProvenance'

export function TradeMicroPage() {
  const { currentRun } = useAnalysisStore()

  if (!currentRun) return <div className="text-sm text-slate-500">加载中...</div>

  const atrade = currentRun.atrade
  const portfolio = currentRun.portfolio
  const riskSourceKind = portfolioKind(currentRun)
  const hasHoldingCoverage = portfolio.portfolioCoverage === 'HOLDINGS_CONNECTED'
  const displayPortfolioMetric = (value: number) => (
    hasHoldingCoverage ? `${(value * 100).toFixed(1)}%` : '需导入持仓'
  )
  const reachability =
    atrade.executionReachability === 'REACHABLE'
      ? { label: '可达', status: 'PASS', symbol: '✓' }
      : atrade.executionReachability === 'CONDITIONALLY_REACHABLE'
        ? { label: '有条件', status: 'WARN', symbol: '△' }
        : { label: '不可达', status: 'FAIL', symbol: '⚠' }
  const microRows = [
    { label: '可卖底仓', value: atrade.sellableBottomWarehouse ? '可卖' : '不可卖', status: atrade.sellableBottomWarehouse ? 'PASS' : 'FAIL' },
    { label: 'ST/退市风险', value: atrade.stDelistingRisk ? '有风险' : '无', status: atrade.stDelistingRisk ? 'FAIL' : 'PASS' },
    { label: '盘口深度', value: atrade.depthAvailable ? '可用' : '不可用', status: atrade.depthAvailable ? 'PASS' : 'FAIL' },
    { label: '流动性风险', value: atrade.liquidityRisk, status: atrade.liquidityRisk === 'LOW' ? 'PASS' : atrade.liquidityRisk === 'MEDIUM' ? 'WARN' : 'FAIL' },
    { label: '闪崩真空', value: atrade.flashCrashVacuumStatus ? '有风险' : '正常', status: atrade.flashCrashVacuumStatus ? 'FAIL' : 'PASS' },
  ]
  const executionParams = [
    { label: '滑点上限', value: `${(atrade.slippageLimit * 100).toFixed(2)}%`, helper: '单笔执行约束' },
    { label: '参与度', value: `${(atrade.participationLimit * 100).toFixed(0)}%`, helper: '成交量参与上限' },
    { label: '成交', value: reachability.symbol, helper: reachability.label },
  ]
  const portfolioRows = [
    { label: '总仓位', value: `${(portfolio.currentTotalPosition * 100).toFixed(1)}%` },
    { label: '单票仓位', value: `${(portfolio.singleStockPosition * 100).toFixed(1)}%` },
    { label: '单票上限', value: `${(portfolio.singleStockPositionCap * 100).toFixed(1)}%` },
    { label: '回撤约束', value: `${(portfolio.maxDrawdownConstraint * 100).toFixed(1)}%` },
  ]
  const concentrationRows = [
    { label: '主题集中度', value: displayPortfolioMetric(portfolio.themeConcentration), width: hasHoldingCoverage ? portfolio.themeConcentration * 100 : 0 },
    { label: '同质风险因子', value: displayPortfolioMetric(portfolio.sameRiskFactorConcentration), width: hasHoldingCoverage ? portfolio.sameRiskFactorConcentration * 100 : 0 },
  ]

  return (
    <div className="space-y-5">
      <SectionTitle title="交易微观" subtitle="统一审查 A 股 T+1、涨跌停、Level-2 和持仓组合约束。" dataMode={currentRun?.dataMode} />

      <Card title="交易护栏状态轨" action={<SourceBadge kind={riskSourceKind} />} className="!rounded-lg !shadow-none">
        <div className="grid gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
          <div className="rounded-md border border-[#d2e3fc] bg-[#e8f0fe] p-4">
            <div className="text-xs font-semibold uppercase tracking-wide text-[#1967d2]">Execution Boundary</div>
            <div className="mt-2 flex items-center justify-between gap-3">
              <div className="text-2xl font-semibold tracking-tight text-slate-950">{reachability.label}</div>
              <Badge status={reachability.status} className="!rounded-md px-2 py-0.5">{atrade.executionReachability}</Badge>
            </div>
            <div className="mt-3 text-xs leading-5 text-slate-600">
              A 股微结构、持仓组合和风险集中度只收窄执行权限，不生成自动交易指令。
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {[
              { label: 'T+1', value: atrade.t1Status ? '正常' : '异常', status: atrade.t1Status ? 'PASS' : 'FAIL' },
              { label: '涨跌停', value: atrade.priceLimitStatus === 'NORMAL' ? '正常' : '限制', status: atrade.priceLimitStatus === 'NORMAL' ? 'PASS' : 'FAIL' },
              { label: 'Level-2', value: atrade.level2Available ? '可用' : '不可用', icon: atrade.level2Available ? Wifi : WifiOff, status: atrade.level2Available ? 'PASS' : 'FAIL' },
              { label: '持仓覆盖', value: hasHoldingCoverage ? '已接入' : '需导入持仓', status: hasHoldingCoverage ? 'PASS' : 'WARN' },
            ].map((item) => {
              const Icon = item.icon
              return (
                <MetricTile
                  key={item.label}
                  label={item.label}
                  value={item.value}
                  helper={item.status}
                  icon={Icon}
                  tone={item.status === 'PASS' ? 'success' : item.status === 'WARN' ? 'warning' : 'danger'}
                  className="!rounded-md !p-3 !shadow-none"
                />
              )
            })}
          </div>
        </div>
      </Card>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[
          { label: 'T+1', value: atrade.t1Status ? '正常' : '异常', status: atrade.t1Status ? 'PASS' : 'FAIL' },
          { label: '涨跌停', value: atrade.priceLimitStatus === 'NORMAL' ? '正常' : '限制', status: atrade.priceLimitStatus === 'NORMAL' ? 'PASS' : 'FAIL' },
          { label: 'Level-2', value: atrade.level2Available ? '可用' : '不可用', icon: atrade.level2Available ? Wifi : WifiOff, status: atrade.level2Available ? 'PASS' : 'FAIL' },
          { label: '执行可达性', value: reachability.label, status: reachability.status },
        ].map((item) => (
          <MetricTile
            key={item.label}
            label={item.label}
            value={item.value}
            helper={item.status}
            icon={item.icon}
            tone={item.status === 'PASS' ? 'success' : item.status === 'WARN' ? 'warning' : 'danger'}
            className="!rounded-lg !shadow-none"
          />
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="A股微结构" className="!rounded-lg !shadow-none">
          <TableShell className="!rounded-lg !shadow-none">
            <table className="institution-table">
              <thead className="bg-slate-50">
                <tr className="text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                  <th className="px-3 py-2">检查项</th>
                  <th className="px-3 py-2">结果</th>
                  <th className="px-3 py-2">状态</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 bg-white">
                {microRows.map((row) => (
                  <tr key={row.label}>
                    <td className="px-3 py-2 font-medium text-slate-900">{row.label}</td>
                    <td className="px-3 py-2 text-slate-600">{row.value}</td>
                    <td className="px-3 py-2">
                      <Badge status={row.status} className="!rounded-md px-2 py-0.5">{row.status}</Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableShell>
        </Card>

        <Card title="执行参数" className="!rounded-lg !shadow-none">
          <div className="grid grid-cols-3 gap-3 text-sm">
            {executionParams.map((item) => (
              <div key={item.label} className="rounded-md border border-slate-200 bg-slate-50 p-3 text-center">
                <div className="text-xs font-semibold text-slate-500">{item.label}</div>
                <div className="mt-1 text-lg font-semibold text-slate-950">{item.value}</div>
                <div className="mt-1 text-[11px] text-slate-500">{item.helper}</div>
              </div>
            ))}
          </div>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="持仓组合" className="!rounded-lg !shadow-none">
          <div className="grid grid-cols-2 gap-3 text-sm">
            {portfolioRows.map((item) => (
              <div key={item.label} className="rounded-md border border-slate-200 bg-slate-50 p-3">
                <div className="text-xs font-semibold text-slate-500">{item.label}</div>
                <div className="mt-1 text-lg font-semibold text-slate-950">{item.value}</div>
              </div>
            ))}
          </div>

          <div className="mt-4 flex gap-3 text-sm">
            <div className="flex-1">
              <Badge status={portfolio.allowAddPosition ? 'PASS' : 'FAIL'} className="w-full justify-center !rounded-md px-2 py-0.5">
                {portfolio.allowAddPosition ? '允许加仓' : '禁止加仓'}
              </Badge>
            </div>
            <div className="flex-1">
              <Badge status={portfolio.allowHeavyPosition ? 'PASS' : 'FAIL'} className="w-full justify-center !rounded-md px-2 py-0.5">
                {portfolio.allowHeavyPosition ? '允许重仓' : '禁止重仓'}
              </Badge>
            </div>
          </div>
        </Card>

        <Card title="风险集中度" action={<SourceBadge kind={riskSourceKind} />} className="!rounded-lg !shadow-none">
          <div className="space-y-3 text-sm">
            {concentrationRows.map((item, index) => (
              <div key={item.label}>
                <div className="flex items-center justify-between">
                  <span className="text-slate-600">{item.label}</span>
                  <span className="font-semibold text-slate-900">{item.value}</span>
                </div>
                <div className="mt-2 h-2 w-full rounded-full bg-slate-100">
                  <div className={`h-2 rounded-full ${index === 0 ? 'bg-amber-500' : 'bg-rose-500'}`} style={{ width: `${item.width}%` }} />
                </div>
              </div>
            ))}
          </div>

          <div className="mt-4">
            <div className="mb-2 text-xs font-medium text-slate-500">行业敞口</div>
            <div className="space-y-1.5">
              {hasHoldingCoverage && Object.entries(portfolio.industryExposure).map(([ind, exp]) => (
                <div key={ind} className="flex items-center justify-between text-sm">
                  <span className="text-slate-600">{ind}</span>
                  <span className="font-medium text-slate-900">{(exp * 100).toFixed(1)}%</span>
                </div>
              ))}
              {!hasHoldingCoverage && (
                <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
                  未接入真实持仓明细，无法计算行业敞口。
                </div>
              )}
            </div>
          </div>
          <SourceNote kind={riskSourceKind} note="公共行情接口无法知道你的账户组合；行业敞口、主题集中度和同质风险必须来自持仓导入或账户连接。" />
        </Card>
      </div>

      {portfolio.restrictionReasons.length > 0 && (
        <Card title="限制原因" className="!rounded-lg !shadow-none">
          <div className="space-y-1">
            {portfolio.restrictionReasons.map((r, i) => (
              <div key={i} className="flex items-center gap-2 rounded border border-rose-100 bg-rose-50 p-2 text-sm text-rose-800">
                <div className="h-1.5 w-1.5 rounded-full bg-rose-500" />{r}
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  )
}
