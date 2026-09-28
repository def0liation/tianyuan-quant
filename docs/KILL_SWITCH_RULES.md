# Kill Switch 规则手册

## 定位
Kill Switch 是系统的**安全熔断机制**。当关键门禁未通过时，自动截断下游正向交易链路。Kill Switch 不可被任何 Agent 绕过。DVG、Risk、Trade Micro 相关触发的 canonical `triggerNode` 为 `guardrail_hub`，旧节点名仅作为历史兼容输入映射。

## 四级机制

| 级别 | 含义 | 阻断范围 |
|------|------|----------|
| `NONE` | 未触发 | 无阻断 |
| `SOFT` | 软阻断 | 进入保守输出模式，限制买入候选但允许观察 |
| `HARD` | 硬阻断 | 阻断 BUY / ADD / CHASE / EXECUTION_PLAN |
| `COMPLIANCE` | 合规阻断 | 阻断所有交易相关路径 |

## 触发条件

| 条件 | 触发级别 |
|------|----------|
| compliance_violation = true | COMPLIANCE |
| risk_hard_reject = true | HARD |
| dvg_status = BLOCK_BUY | HARD |
| dvg_status = REVIEW_ONLY | SOFT |
| atrade_execution = NOT_REACHABLE | HARD |
| qiam_final_buy_suitability = BLOCK_BUY | HARD |
| portfolio_risk_exceeded = true | SOFT |
| execution_go = false | SOFT |
| hallucination_risk_score >= 75 | HARD |
| anti_conclusion_status = BLOCK_OUTPUT | HARD |

## 阻断路径

### SOFT 级别
- blocked_paths: [BUY_CANDIDATE, ADD_CANDIDATE, CHASE]
- allowed_paths: [WAIT, REVIEW_ONLY, HOLD, SIGNAL_ONLY]
- finalWriterMode: CONSERVATIVE

### HARD 级别
- blocked_paths: [BUY_CANDIDATE, ADD_CANDIDATE, CHASE, EXECUTION_PLAN, AUTO_ORDER]
- allowed_paths: [WAIT, REVIEW_ONLY, HOLD]
- finalWriterMode: HARD_RISK_FINAL_ONLY

### COMPLIANCE 级别
- blocked_paths: [全部交易路径]
- allowed_paths: [WAIT]
- finalWriterMode: COMPLIANCE_REJECT

## Kill Switch 输出结构

```json
{
  "active": true,
  "level": "NONE | SOFT | HARD | COMPLIANCE",
  "triggerNode": "guardrail_hub",
  "triggerRule": "data_reliability <= MEDIUM",
  "blockedPaths": [],
  "allowedPaths": [],
  "finalWriterMode": "CONSERVATIVE | HARD_RISK_FINAL_ONLY | COMPLIANCE_REJECT",
  "auditId": "AUD_KS_001"
}
```

## 强制规则

1. HARD 后阻断 BUY / ADD / CHASE / EXECUTION_PLAN
2. COMPLIANCE 后阻断所有交易相关路径
3. SOFT 后进入保守输出
4. finalWriterMode 必须跟随 Kill Switch 级别
5. Kill Switch 触发后，前端必须显示触发节点和规则
6. Kill Switch 触发后，下游正向链路必须被截断
7. `guardrail_hub` 触发 HARD / COMPLIANCE 后必须立即重算 nodes、agentResults、dagEvents、finalContext 和 orchestratorPlan
8. 任何 Agent 不得绕过 Kill Switch
9. Kill Switch 不可被 Orchestrator 关闭
10. Final Writer 不得在 Kill Switch 激活时输出买入建议
11. SignalOps 不得在 Kill Switch 激活时升级信号状态
