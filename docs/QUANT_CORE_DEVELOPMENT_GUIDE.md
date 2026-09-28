# 量化核心开发指南

更新日期：2026-06-08

“量化核心”是市场状态、K 线技术面、MFE/MAE 路径研究、Quant/QIAM 和情景引擎合并后的
canonical Agent。用户可见名称使用“量化核心”，代码 ID 使用 `quant_core`，前端路径使用
`/quant-core`，API 字段使用 `quantCore`。

## 1. 定位和边界

量化核心负责把已有研究和量化判断收敛为一个可审计输出，不新增真实交易能力。

- 只编排和汇总已有逻辑：市场/技术面、MFE/MAE Path Research、因子、计算校验、QIAM、Scenario。
- 不连接真实券商账户，不新增真实下单 API。
- 所有交易相关后续动作仍必须保持 `simulation_only=true`、`is_real_trade=false` 和 `SIM_*` 边界。
- 量化核心不得绕过 DVG、Risk、Trade Micro、Execution、Anti-Conclusion 或 Final Writer。
- Final Writer 只能引用量化核心的已生成证据，不能自行补推新的买卖理由。

## 2. 输入契约

量化核心读取完整 `AnalysisRun` 上下文，关键输入包括：

| 输入 | 来源 | 说明 |
|------|------|------|
| `marketData` / `dataSources` | Data Engine | 行情、K 线、筹码、数据源质量 |
| `dvg` | DVG Gate | 数据可信度、模式化门禁、QIAM permission |
| `risk` | Risk Firewall | 硬风险、合规、流动性陷阱 |
| `atrade` / `tradeMicro` | Trade Micro | A 股微观结构、T+1、涨跌停、持仓可达性 |
| `quantEngine` | Run seed / request | `quantEngineMode` 和参数画像 |
| `bottomResearchConfig` | Request | 兼容请求名；当前语义为 MFE/MAE Path Research 配置，仅影响研究证据 |
| `agentModuleResults` / `agentOutputs` | Legacy runs | 历史回填和兼容读取 |

## 3. 输出契约

Canonical 输出写入 `run.quantCore` / `AnalysisRun.quantCore`：

```json
{
  "agent": "quant_core",
  "status": "PASS|WARN|REVIEW_ONLY|SKIPPED",
  "marketTechnical": {},
  "mfeMaeResearch": {},
  "bottomResearch": {},
  "factorSlicing": {},
  "factorEngine": {},
  "calculationAuthority": {},
  "quantEngine": {},
  "qiam": {},
  "scenario": {},
  "coreInterpretation": {},
  "legacyOutputs": {},
  "legacyAgentOutputs": {},
  "warnings": [],
  "missingData": [],
  "provenance": {}
}
```

兼容回填字段必须继续存在：

- `run.marketTechnical`
- `run.market`
- `run.technicalKline`
- `run.mfeMaeResearch`
- `run.bottomResearch`
- `run.factorSlicing`
- `run.factorEngine`
- `run.calculationAuthority`
- `run.quantEngine`
- `run.qiam`
- legacy `agentModuleResults` / `agentOutputs`

`coreInterpretation.visualDecisionPanel` 是 `/quant-core` 的只读展示层字段，版本为
`quant_core_visual_decision_panel_v1`。它把 `futureTrendProbability`、`pathRiskFilter`
和 `mfeMaeResearch` 派生为四组面板数据：`directionProbability`、`pathPayoffProxy`、
`riskGradient`、`probabilityOddsMatrix`。所有子字段必须保持
`actionBoundary=READ_ONLY_NO_PERMISSION_CHANGE`、`simulation_only=true`、
`is_real_trade=false`；`probabilityOddsMatrix.zone` 只能表达展示分区
`PRIORITY|WATCH|FILTER|INSUFFICIENT_DATA`，不能写回或覆盖 QIAM、SignalOps、
Execution、Scenario 或 `finalAction`。

## 4. 旧 Agent ID 兼容表

| 旧 ID | Canonical owner |
|-------|-----------------|
| `market_regime` | `quant_core` |
| `technical_kline_analyst` | `quant_core` |
| `market_technical_analyst` | `quant_core` |
| `bottom_research` | `quant_core` |
| `factor_slicing` | `quant_core` |
| `factor_engine` | `quant_core` |
| `calculation_authority` | `quant_core` |
| `qiam` | `quant_core` |
| `quant_engine` | `quant_core` |
| `scenario_engine` | `quant_core` |
| `simulation_agent` | `quant_core` |

兼容入口包括运行时配置、重试节点、插件插入锚点、DAG 展示、历史 run 读取和前端旧页面跳转。

## 5. DAG 顺序和运行模式

FAST_MODE：

```text
orchestrator -> data_engine -> dvg_gate -> risk_firewall
-> trade_micro -> quant_core -> final_writer
```

STANDARD_MODE / DEEP_MODE：

```text
orchestrator -> data_engine -> dvg_gate -> risk_firewall
-> trade_micro -> quant_core -> execution
-> anti_conclusion -> signalops -> final_writer
```

FAST 模式下 `scenario` 子输出可被标记为 `SKIPPED`，但 `quantCore` 字段仍必须生成，方便前端和历史详情页稳定读取。

## 6. MFE/MAE Path Research 和 QIAM 规则

- MFE/MAE Path Research 永远是 supporting-only evidence。
- MFE/MAE Path Research 不能直接生成 BUY、ADD、SELL、REDUCE、CHASE 或真实下单动作。
- MFE/MAE Path Research 对 QIAM 最多只允许一档校准。
- 正向一档校准必须同时满足 DVG 放行、技术面不看空、证据质量达标、MAE 跌破风险可控。
- 任何 DVG、Risk、Trade Micro、Execution 冲突都优先于 MFE/MAE 的正向信号。
- Nowcast 只用于可观测性，不参与 Brier、PR-AUC、verdict acceptance 或交易门禁升级。
- 旧 `bottomResearch` 字段和 `/bottom-research` route 只作为兼容入口；当前 UI、Backtest source 和 Research Lab closure 应使用 MFE/MAE 命名。
- `visualDecisionPanel` 只能做概率、MFE/MAE 盈亏空间代理、风险梯度和概率赔率矩阵的展示汇总；缺少后端字段时前端必须回退旧字段并保持可空兼容。

## 7. 前端路由收敛

新页面为 `/quant-core`。以下旧页面只做重定向，不再作为新的产品入口：

- `/market`
- `/technical-kline`
- `/bottom-research`
- `/quant-engine`
- `/scenario`

新增 UI 时优先读取 `currentRun.quantCore`，再兼容读取旧字段。所有可空字段必须处理
`null` / `undefined`，不能假设历史 run 已经包含新 canonical 字段。

## 8. 开发入口

主要后端文件：

- `backend/app/modules/quant_core.py`
- `backend/app/modules/agent_registry.py`
- `backend/app/core/agent_framework.py`
- `backend/app/core/agent_executor.py`
- `backend/app/core/llm_runner.py`
- `backend/app/models/analysis.py`
- `backend/app/api/routes_analysis.py`

主要前端文件：

- `frontend/src/components/quantCore/QuantCorePage.tsx`
- `frontend/src/App.tsx`
- `frontend/src/routeManifest.json`
- `frontend/src/types/index.ts`
- `frontend/src/components/dashboard/DashboardPage.tsx`

主要文档：

- `docs/QUANT_CORE_DEVELOPMENT_GUIDE.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/AGENT_REGISTRY.md`
- `docs/API_CONTRACT.md`
- `docs/DEVELOPMENT_LOG.md`

## 9. 必跑检查

```powershell
npm.cmd run test:backend -- backend\tests\test_agent_runtime.py backend\tests\test_agent_executor.py backend\tests\test_analysis_workflow.py backend\tests\test_bottom_research_agent.py backend\tests\test_technical_kline_agent.py -q
npm.cmd run typecheck
npm.cmd run lint
npm.cmd run build
npm.cmd run smoke:frontend
git diff --check
```

如果只改后端规则，可先加跑：

```powershell
.\.venv\Scripts\python.exe -m py_compile backend\app\modules\quant_core.py backend\app\core\agent_framework.py backend\app\core\agent_executor.py
```

## 10. 开发注意事项

- 不新增数据库迁移，除非未来需求明确要求持久化 schema 变更。
- 不删除旧字段，不破坏历史 run 详情页。
- 不把旧 ID 重新加入活跃 DAG。
- 不把 `/technical-kline` 独立工具 API 和 `/quant-core` 产品页混为一谈；旧技术 K 线 API 可以继续作为工具接口存在。
- 修改 API 输出时同步更新 Pydantic model、TypeScript 类型、页面空值处理和 `docs/API_CONTRACT.md`。
- 修改 QIAM/MFE-MAE Research 影响时必须补充失败路径或 guardrail 覆盖。
