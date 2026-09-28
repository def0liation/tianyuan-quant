# SignalOps 信号管理规则手册

## 定位
SignalOps 是**信号生命周期与自动模拟交易管理模块**。它可以自动维护股票池、调用行情、生成 AI 触发/失效判断、记录 `SIM_*` 沙箱动作并维护模拟资金状态；它不连接真实交易账户，不生成真实下单指令。

## 信号状态流

```
IDEA
  → WATCH
    → PAPER_TEST
      → QUALIFIED
        → TRADE_PLAN
          → MANUAL_CONFIRMED
            → EXECUTION_REVIEW
              → CLOSED

任何阶段 → PATCH_REQUIRED（需维护）
```

## 状态定义

| 状态 | 含义 | 允许操作 |
|------|------|----------|
| IDEA | 初始概念 | 仅记录 |
| WATCH | 观察中 | 跟踪数据变化 |
| PAPER_TEST | 纸面验证 | 纸面模拟 |
| QUALIFIED | 合格信号 | 可进入交易计划 |
| TRADE_PLAN | 交易计划 | 待人工确认 |
| MANUAL_CONFIRMED | 人工已确认 | 可执行 |
| EXECUTION_REVIEW | 执行后复盘 | 复盘分析 |
| CLOSED | 已关闭 | 归档 |
| PATCH_REQUIRED | 需维护 | 触发 Meta-Agent |

## 升级门禁

信号从低状态升级到高状态必须通过以下检查：
SignalOps 读取 canonical `guardrailHub`，同时继续兼容旧生命周期字段 `riskPassed`、`dvgPassed`、`executionReachable`。旧 run 只有 `dvg/risk/atrade/killSwitch` 时必须先合成等价护栏结果再 upsert SignalOps。

| 升级目标 | 必要条件 |
|----------|----------|
| → WATCH | 基础分析完成 |
| → PAPER_TEST | AI 自动模拟沙箱允许进入，Risk/DVG 仅提示 |
| → QUALIFIED | DVG 通过（非 REVIEW_ONLY），Risk 通过，QIAM 通过 |
| → TRADE_PLAN | DVG 通过（非 BLOCK_BUY），ATrade 可达，Portfolio 允许 |
| → MANUAL_CONFIRMED | 人工确认 |
| → EXECUTION_REVIEW | 执行完成 |

## 门禁规则

1. Risk 未通过 → 不得进入 QUALIFIED
2. DVG REVIEW_ONLY → 不得进入 QUALIFIED
3. DVG BLOCK_BUY → 不阻断 PAPER_TEST 沙箱模拟，但不得进入 QUALIFIED、TRADE_PLAN 或真实交易链路
4. QIAM BLOCK_BUY → 不得进入 TRADE_PLAN
5. Trade Micro / ATrade NOT_REACHABLE → 不得生成真实执行计划
6. trigger_conditions / invalidation_conditions 由 AI 自动跟进生成，不再作为人工硬门槛
7. 未人工确认 → 不得进入真实交易动作
8. SignalOps 允许全自动模拟交易和自动撮合沙箱订单，但不得自动真实交易
9. SignalOps 不得绕过 Kill Switch 或 `guardrail_hub` 的 `finalDecisionCap`

## AI 模拟仓规则

SignalOps 可以管理 AI 模拟仓。模拟仓是沙箱研究环境，不属于真实交易链路，也不代表信号已经具备交易资格。

### 启用条件

- 只要信号未关闭，就允许自动创建或同步模拟仓并记录 `SIM_*` 动作。
- 自动模拟交易按股票池运行，股票池总资金是唯一全局资金；每只股票使用按池内数量分配的沙箱预算，前端资金汇总不得重复累加子仓初始资金。
- 自动模拟交易会自行生成 `triggerConditions` / `invalidationConditions` 并推进到 `PAPER_TEST`；Risk/DVG/QIAM/Execution 未通过只在 `riskConstraints.paper_gate_warnings` 中记录提示。
- 前端不提供人工下单入口；允许用户配置运行开关、股票池总资金、股票代码，并提供强制模拟平仓/移除股票池等沙箱控制指令。
- Kill Switch 激活时不得新增模拟风险敞口，只允许 `SIM_HOLD` 或 `SIM_CLOSE`。
- 模拟结果不得用于绕过 `PAPER_TEST`、`QUALIFIED`、`TRADE_PLAN`、人工确认或真实执行门禁。
- 日K决策树只能记录和复盘自动模拟决策，不能产生真实交易动作，不能替代 K线质量、策略稳定性、A 股 T+1、涨跌停、手续费、印花税、100 股整数手、现金或持仓门禁。

### 日K决策树规则

- 生命周期起点必须来自阶段性低点确认：至少 3 个交易日连续下跌后，连续 2 个交易日反弹且最低价不再跌破该低点。
- 每次有效 tick 最多生成一个 branch；skipped interval、日K不足、低点未确认、异常 tick 不推进生命周期。
- 生命周期结束条件固定为：区间最高收益不再刷新至少 2 个交易日，且最新收盘价跌破 MA5。
- 复盘必须拆分 `decision_correctness`、`execution_quality`、`data_quality`，不得只按盈亏判断。
- 自动微调只允许写入 SignalOps 模拟参数，单次阈值调整不超过 `0.05`，仓位比例调整不超过 `0.02`；证据不足、数据质量不足、HOLD/blocked-only 样本不得自动调参。
- 复盘沉淀到知识库时必须标记 `SIGNALOPS_DECISION_TREE`、`simulation_only=true`、`is_real_trade=false`。

### 允许动作

模拟仓动作必须使用专用枚举：

```json
["SIM_BUY", "SIM_SELL", "SIM_HOLD", "SIM_REBALANCE", "SIM_CLOSE", "SIM_T_BUY", "SIM_T_SELL", "SIM_SHORT", "SIM_COVER"]
```

禁止把模拟动作写成 `BUY`、`SELL`、`ADD`、`REDUCE`，避免和真实交易动作混淆。

### 审计字段

每一条模拟动作必须保存：

- `paperPortfolioId`
- `paperOrderId`
- `signalId`
- `runId`
- `agentId`
- `auditId`
- `action`
- `actionReason`
- `dataSnapshotHash`
- `riskConstraints`
- `invalidationConditions`
- `simulatedFill`
- `simulationOnly: true`
- `isRealTrade: false`

### 知识库标记

模拟仓案例可以进入知识库做知识迭代，但必须显式标记为 Agent 操作案例：

```json
{
  "caseSource": "AGENT_SIMULATION",
  "operatorType": "AGENT",
  "simulationOnly": true,
  "isRealTrade": false,
  "agentId": "signalops | paper_trading_agent",
  "sourceSignalId": "",
  "sourcePaperOrderId": "",
  "auditId": ""
}
```

知识库 UI 必须把这类案例显示为“Agent 模拟操作案例”。它们可以生成知识 patch 候选，但不能直接发布到生产规则，必须经过人工审核和回测/沙箱验证。

## 输出结构

```json
{
  "signalStatus": "IDEA | WATCH | PAPER_TEST | QUALIFIED | TRADE_PLAN | MANUAL_CONFIRMED | EXECUTION_REVIEW | CLOSED | PATCH_REQUIRED",
  "riskPassed": true,
  "dvgPassed": false,
  "qiamPassed": true,
  "executionReachable": true,
  "triggerConditions": [],
  "invalidationConditions": [],
  "reviewFields": [],
  "blockedReason": "",
  "auditId": "AUD_SIG_001"
}
```
