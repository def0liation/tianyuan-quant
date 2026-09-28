# Shared Schemas 共享结构

## 1. 数据标签

- [C] Confirmed：已确认
- [I] Inferred：推断
- [U] Unknown：未确认

## 2. 最终动作枚举

```json
[
  "REJECT",
  "REVIEW_ONLY",
  "WAIT",
  "HOLD",
  "REDUCE",
  "LIGHT_WATCH",
  "BUY_CANDIDATE",
  "ADD_CANDIDATE",
  "DEFENSIVE",
  "SIGNAL_ONLY",
  "PAPER_TEST_ONLY"
]
```

说明：

- BUY_CANDIDATE 不是买入指令。
- ADD_CANDIDATE 不是加仓指令。
- SIGNAL_ONLY 只进入观察池。
- PAPER_TEST_ONLY 只允许纸面验证。
- 所有真实交易必须人工确认。

## 3. Kill Switch Schema

```json
{
  "kill_switch": {
    "active": false,
    "level": "NONE|SOFT|HARD|COMPLIANCE",
    "trigger_node": "",
    "trigger_rule": "",
    "blocked_paths": [],
    "allowed_paths": [],
    "final_writer_mode": "NORMAL|CONSERVATIVE|HARD_RISK_FINAL_ONLY|COMPLIANCE_REFUSAL",
    "audit_id": ""
  }
}
```

## 4. 统一节点状态

```json
[
  "PASS",
  "WARN",
  "REVIEW_ONLY",
  "BLOCKED",
  "BLOCK_BUY",
  "REJECT",
  "FAILED",
  "UNKNOWN"
]
```

## 5. final_context Schema

```json
{
  "final_context": {
    "final_writer_mode": "NORMAL|CONSERVATIVE|HARD_RISK_FINAL_ONLY|COMPLIANCE_REFUSAL",
    "final_action": "REJECT|REVIEW_ONLY|WAIT|HOLD|REDUCE|LIGHT_WATCH|BUY_CANDIDATE|ADD_CANDIDATE|DEFENSIVE|SIGNAL_ONLY|PAPER_TEST_ONLY",
    "final_decision_cap": "NO_CAP|NO_STRONG_BUY|NO_BUY|REVIEW_ONLY|BLOCK_BUY|REJECT",
    "allowed_actions": [],
    "forbidden_actions": [],
    "data_reliability": "HIGH|MEDIUM|LOW",
    "risk_summary": {},
    "dvg_summary": {},
    "atrade_summary": {},
    "market_summary": {},
    "factor_summary": {},
    "qiam_summary": {},
    "portfolio_summary": {},
    "execution_summary": {},
    "signalops_summary": {},
    "auto_paper_trading_summary": {
      "enabled": false,
      "tracked_symbols": [],
      "stock_pool_cash": 0,
      "available_cash": 0,
      "market_value": 0,
      "total_assets": 0,
      "last_sim_action": "SIM_HOLD|SIM_BUY|SIM_SELL|SIM_REBALANCE|SIM_CLOSE",
      "simulation_only": true,
      "is_real_trade": false
    },
    "missing_data": [],
    "trigger_conditions": [],
    "invalidation_conditions": [],
    "human_confirmation_required": true,
    "audit_id": ""
  }
}
```
