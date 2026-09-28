# SignalOps 日K决策树开发指南

更新时间：2026-05-27

## 1. 目标与边界

SignalOps 决策树用于记录 `/signalops` 自动模拟交易在一个日K生命周期内的每次决策分支，并在生命周期结束后复盘正确/错判、沉淀知识、保守微调下一轮模拟策略。

硬边界：

- 只服务 SignalOps 自动模拟交易，不新增真实交易能力。
- 所有动作必须保持 `SIM_*`、`simulation_only=true`、`is_real_trade=false`。
- 决策树不能绕过现有 K线质量门禁、策略稳定性门禁、A股 T+1、涨跌停方向限制、手续费、印花税、100 股整数手、现金和持仓约束。
- 不新增数据库迁移。第一版使用 `backend/app/storage/auto_paper_trading.json` 中的 `decision_tree_state`。
- 前端只展示和复核模拟证据，不提供真实下单入口。

## 2. 生命周期规则

周期固定为日K。

### 2.1 起点候选

阶段低点候选来自日K `rows`：

- 需要至少 3 个交易日连续下跌。
- 连续下跌判断采用收盘价下移，并要求低点重心不抬高。
- 阶段低点取连续下跌窗口内最低 `low`。
- 如果确认前再次出现更低 `low`，候选低点重置。

### 2.2 起点确认

候选低点后必须出现 2 个交易日反弹：

- 两个确认日的 `low` 都不能跌破候选低点。
- 两个确认日的 `close` 都应高于候选低点日 `close`。
- 第二个确认日 `close` 不低于第一个确认日 `close`。
- 确认后创建 active tree，`start.date` 为候选低点日期，`start.low` 为阶段最低价。

### 2.3 分支生成

每次有效 tick 做出决策后生成一个 branch。

有效 tick 指 `_tick_one` 完成 `_decide`，并已形成 `decision_card`。以下情况不生成分支：

- tick interval 未到导致 `SKIPPED`。
- 股票没有日K数据或日K不足以计算 MA5。
- 决策树起点尚未确认。
- tick 异常进入 `_exception_result`，只记录错误摘要，不推进生命周期。

每个 branch 必须保存：

- `branch_id`, `tree_id`, `sequence`, `trade_date`, `created_at`
- `action`, `strategy_intent`, `reason`, `source`
- 决策时 `price`, `ma5`, `stage_low`, `peak`, `current_return_pct`, `peak_return_pct`
- `portfolio_before`, `portfolio_after`
- `order_summary`: `order_id`, `action`, `fill_status`, `error`, `simulated_price`, `simulated_quantity`, `filled_price`, `filled_quantity`, `fees`
- `kline_signal_quality`, `strategy_stability_quality`
- `blockers`
- `decision_snapshot`: 仓位比例、仓位来源、买入阈值、失效阈值、action policy
- `simulation_only=true`, `is_real_trade=false`

### 2.4 最高点维护

active tree 从 `start.date` 起扫描日K：

- `peak.price` 为生命周期内最高 `high`。
- `peak.date` 为最高价日期。
- `peak.gain_pct = (peak.price - start.low) / start.low`。
- `current.latest_gain_pct = (latest.close - start.low) / start.low`。

### 2.5 结束条件

生命周期结束必须同时满足：

- 从 `peak.date` 起连续至少 2 个交易日没有刷新最高价。
- 最新交易日 `close < MA5`。

如果只满足其中一个条件，不关闭生命周期：

- 未刷新高点但未跌破 MA5：继续观察。
- 跌破 MA5 但仍刷新高点：继续观察。

结束原因固定为 `peak_gain_stalled_and_close_below_ma5`。

## 3. 状态结构

`AutoPaperTradingConfig` 和 status JSON 增加：

```json
{
  "decision_tree_state": {
    "version": 1,
    "updated_at": "...",
    "symbols": {
      "603663": {
        "status": "ACTIVE",
        "candidate_low": {},
        "active_tree": {},
        "closed_trees": [],
        "last_review": {},
        "last_tuning_audit": {},
        "last_context": {},
        "simulation_only": true,
        "is_real_trade": false
      }
    },
    "tuning_audit": [],
    "simulation_only": true,
    "is_real_trade": false
  }
}
```

限制：

- `closed_trees` 默认最多保留 8 棵。
- 每棵树 branch 默认最多保留 80 个。
- `tuning_audit` 默认最多保留 20 条。
- compact API 只返回 active tree 摘要、最近 closed tree、最近 review、最近 tuning，不返回无限历史。

## 4. 后端接入点

新增模块：

- `backend/app/core/signalops_decision_tree.py`

该模块应保持纯逻辑、无数据库依赖，暴露：

- `normalize_decision_tree_state(value)`
- `compact_decision_tree_state(value)`
- `update_decision_tree_after_tick(...)`

`backend/app/core/auto_paper_trading.py` 接入点：

1. `get_status()` 返回 `decision_tree_state`。
2. `update_config()` 和 `_load_state()` 规范化 `decision_tree_state`。
3. `_tick_one()` 在 `_decide()` 与 `_build_decision_card()` 后更新决策树。
4. 决策树 branch 写回：
   - `decision["decision_tree_branch"]`
   - `decision["decision_card"]["decision_tree"]`
   - `order["risk_constraints"]["decision_tree_branch"]`
5. 如果生命周期关闭：
   - 写入 `last_research_review.decision_tree_reviews`
   - 写入 `review_queue_state.observations`
   - 创建 pending `KnowledgeItem`
   - 若调参证据充分，自动应用模拟参数并写入 `decision_tree_tuning`

`backend/app/models/auto_paper_trading.py` 增加：

- `AutoPaperTradingConfig.decision_tree_state`
- `AutoPaperTradingStatus.decision_tree_state`
- `AutoPaperTradingTickResult.decision_tree_branch`
- `AutoPaperTradingTickResult.decision_tree_review`
- `AutoPaperTradingDailyReviewResult.decision_tree_reviews`

`backend/app/api/routes_auto_paper_trading.py`：

- `_compact_config()` 不清空 `decision_tree_state`，但要压缩为摘要。
- `_compact_status()` 返回 compact `decision_tree_state`。
- `_compact_tick_result_one()` 保留 `decision_tree_branch` 和 decision card 的 `decision_tree` 摘要。

## 5. 复盘判定

生命周期结束后对每个 branch 生成 review。

每个 branch review 至少包含：

- `branch_id`
- `trade_date`
- `action`
- `decision_correctness`: `CORRECT`, `WRONG`, `PARTIAL`, `SKIPPED`
- `execution_quality`: `OK`, `PARTIAL`, `BLOCKED`, `SKIPPED`
- `data_quality`: `MEDIUM`, `LOW`
- `reason`
- `future_peak_gain_pct`
- `future_drawdown_pct`
- `final_gain_pct`
- `blockers`
- `simulation_only=true`, `is_real_trade=false`

判定原则：

- `SIM_BUY` / `SIM_T_BUY`
  - 后续有效峰值收益达到至少 1.5%：`CORRECT`
  - 未达到有效峰值且生命周期结束收益转负：`WRONG`
  - 方向不清晰：`PARTIAL`
  - 被硬门禁阻断且无订单：`SKIPPED`
- `SIM_HOLD`
  - 后续没有有效上行空间，或当时存在硬门禁：`CORRECT`
  - 无硬门禁但错过有效上行空间：`WRONG`
- `SIM_SELL` / `SIM_CLOSE` / `SIM_T_SELL`
  - 卖出后未再出现有效新高：`CORRECT`
  - 卖出后仍出现有效新高：`WRONG`
  - 边际不清晰：`PARTIAL`
- `SIM_SHORT`
  - 后续出现有效下跌空间：`CORRECT`
  - 后续出现有效反弹空间：`WRONG`
- `SIM_COVER`
  - 回补后没有更多有效下跌，或出现反弹：`CORRECT`
  - 回补后继续有效下跌：`WRONG`
- 数据质量低时优先 `SKIPPED`，避免错误学习。

注意：不要只按盈亏判断。必须拆分：

- `decision_correctness`: 方向和时机。
- `execution_quality`: 是否实际成交、是否被规则阻断、是否部分执行。
- `data_quality`: K线和行情数据是否可靠。

## 6. 自动微调规则

生命周期复盘后可自动微调模拟参数，但必须保守。

允许调整：

- `buy_change_threshold_pct`
- `close_change_threshold_pct`
- `watch_position_ratio`
- `probe_position_ratio`
- `positive_position_ratio`
- `breakout_position_ratio`
- `defensive_position_ratio`
- `existing_position_ratio`
- `strength_follow_position_ratio`

硬上限：

- 单次阈值调整最大 `0.05`。
- 单次仓位比例调整最大 `0.02`。
- 调整后仍必须落在原有配置 clamp 范围内。

禁止自动调参：

- 有效决策节点少于 3 个。
- 数据质量低的节点占主导。
- 样本只有 `SIM_HOLD` 或 blocked 节点。
- 没有方向一致的错判/正确证据。

微调审计必须保存：

- `tuning_id`
- `source_tree_id`
- `review_id`
- `before`
- `after`
- `applied_parameters`
- `reason`
- `branch_evidence`
- `created_at`
- `simulation_only=true`
- `is_real_trade=false`

## 7. 知识沉淀

生命周期结束后创建 pending knowledge candidate：

- `category = "SIGNALOPS_DECISION_TREE"`
- `title` 包含 symbol 和 tree id。
- `thesis` 总结生命周期结束原因、正确/错判分布和调参结论。
- `evidence` 至少包含：
  - tree id
  - symbol
  - start date / low
  - peak date / price / gain
  - end date / close / MA5
  - tuning applied / reason
- `decision_impact` 明确只影响 SignalOps 模拟策略。
- `guardrail_notes` 明确不产生真实交易。
- `tags`: `signalops`, `decision-tree`, `auto-paper`, `simulation-only`

有真实模拟订单的 branch 继续复用 `AgentSimulationCase`。无订单 branch 只作为 tree review evidence。

## 8. 前端展示要求

`frontend/src/types/index.ts` 增加：

- `SignalOpsDecisionTreeState`
- `SignalOpsDecisionTree`
- `SignalOpsDecisionTreeBranch`
- `SignalOpsDecisionTreeReview`
- `SignalOpsDecisionTreeTuning`

`/signalops` 增加决策树区域。

必须展示：

- 当前生命周期：
  - tree id
  - 起点日期和低点
  - 当前最高点和区间收益
  - 最新收盘、MA5、是否临近结束
  - branch 数量
- 分支时间线：
  - 时间、动作、价格、MA5
  - 决策原因
  - blockers
  - 订单状态
- 已结束生命周期：
  - 结束原因
  - 正确、错判、部分正确、跳过数量
  - 自动微调是否应用
  - knowledge candidate id 或 pending 状态

状态必须安全处理：

- 无树：显示“等待阶段低点确认”。
- active tree：显示当前生命周期。
- closed review：显示最近复盘。
- 数据不足：显示日K样本不足，不崩溃。

UI 约束：

- 不使用嵌套卡片。
- metric 文本必须 `min-w-0` 和可换行，避免长 reason 撑宽页面。
- 不新增真实交易按钮。

## 9. 测试计划

新增或更新 `backend/tests/test_auto_paper_trading.py`。

必测：

- 低点未确认时不创建树。
- 连续下跌后反弹 2 个交易日且不破低，创建 active tree。
- 确认前再创新低，候选低点重置。
- 每次有效 tick 只生成一个 branch。
- 未刷新高点但未跌破 MA5，不结束。
- 跌破 MA5 但仍刷新高点，不结束。
- 未刷新高点且跌破 MA5，关闭生命周期并生成 review。
- BUY/HOLD/SELL/SHORT/COVER 正确、错判、部分正确分类。
- 自动微调 obey caps。
- 证据不足不调参。
- `simulation_only=true`、`is_real_trade=false` 全链路保持。

推荐验证命令：

```powershell
npm.cmd run test:backend -- backend\tests\test_auto_paper_trading.py backend\tests\test_signalops_lifecycle_store.py backend\tests\test_signalops.py -q
npm.cmd run typecheck
npm.cmd run lint
npm.cmd run build
```

如果 `pnpm` 可用，再按项目协议运行：

```powershell
pnpm typecheck
pnpm lint
pnpm test
```

浏览器验收：

- 打开 `http://127.0.0.1:5174/signalops`。
- 确认决策树区域可见。
- 无树、active tree、closed review、数据不足状态均不出现错误 overlay。
- 页面无明显横向溢出。
- 控制台无新增前端错误。

## 10. 文档同步清单

实现完成后同步：

- `docs/API_CONTRACT.md`
  - `decision_tree_state`
  - `decision_tree_branch`
  - `decision_tree_reviews`
  - compact payload 字段
- `docs/TESTING_GUIDE.md`
  - focused tests
  - typecheck/lint/build
  - browser smoke
- `docs/SIGNALOPS_RULES.md`
  - 决策树 simulation-only 边界
  - 不绕过既有门禁
- `docs/DEVELOPMENT_GUIDE.md`
  - 增加本指南入口
- `docs/DEVELOPMENT_LOG.md`
  - 实现范围
  - 验证命令
  - 残余风险

## 11. 当前实现状态

截至 2026-05-27：

- `backend/app/core/signalops_decision_tree.py` 已提供日K生命周期、branch、review、tuning、knowledge candidate 的纯逻辑。
- `auto_paper_trading.py` 已在有效 tick 后写入 `decision_tree_state`，并把 branch 同步到 `decision`、`decision_card.decision_tree` 和订单 `risk_constraints`。
- compact API 已返回 `decision_tree_state`、`decision_tree_branch`、`decision_tree_review` 和 `decision_tree_reviews`。
- `/signalops` 已增加只读 `Daily decision tree` 面板，覆盖无树、active tree、closed review、数据不足状态。
- `backend/tests/test_auto_paper_trading.py` 已增加生命周期 focused tests。

后续继续开发时，应优先补浏览器 smoke 和更细的 BUY/SELL/SHORT/COVER 分类样本，而不是改变 simulation-only 边界。
