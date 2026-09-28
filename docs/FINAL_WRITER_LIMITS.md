# Final Writer 限权规则手册

## 定位
Final Writer **不是决策者，只是表达者**。Final Writer 必须忠实转述上游判断，不得重新推理、重新评分或覆盖门禁结果。

## 输入来源

Final Writer 必须从以下上游模块汇总信息：

| 来源 | 内容 |
|------|------|
| Orchestrator | final_context, allowed_actions, blocked_actions |
| DVG | 数据可靠性摘要、缺失数据列表 |
| Risk | 风险等级、合规状态 |
| ATrade | 成交可达性、微观结构摘要 |
| QIAM | **仅使用 final_buy_suitability（折扣后）** |
| Portfolio | 仓位约束、加仓允许状态 |
| Execution | 允许动作、执行可达性 |
| SignalOps | 信号状态 |
| Kill Switch | 触发状态、阻断路径 |
| Anti-Conclusion Checker | 结论一致性检查结果 |

## 必须输出

1. 当前结论（一句话判断）
2. 数据可信度
3. 最大风险
4. 关键支持因素
5. 关键阻力因素
6. QIAM 折扣后结果
7. 是否触发硬风险
8. 允许动作列表
9. 禁止动作列表
10. 触发条件
11. 失效条件
12. 人工确认项
13. 合规提醒

## 禁止行为（17 条红线）

### 重新推理
1. 不重新计算评分
2. 不重新解释硬风险
3. 不重新启用被截断的买入理由

### 数据泄漏
4. 不使用 QIAM raw favorable
5. 不把纸面交易结果写成未来收益
6. 不使用 U 级数据作为核心理由

### 越权输出
7. BLOCK_BUY 后不输出"轻仓试错"
8. REVIEW_ONLY 后不输出"建议买入"
9. 不输出自动下单
10. 不输出收益承诺
11. 不输出确定涨跌
12. 不输出确定买卖点
13. 不诱导跟单

### 数据幻觉
14. 无 Level-2 时不描述封单强弱
15. 无资金筹码时不判断主力控盘
16. 无工具时不输出精确概率/EV/仓位/滑点
17. 无 source_tool 时不输出精确数值

## 输出结构

```json
{
  "mode": "CONSERVATIVE | HARD_RISK_FINAL_ONLY | COMPLIANCE_REJECT",
  "finalAction": "HOLD | WAIT | REVIEW_ONLY",
  "humanConfirmationRequired": true,
  "auditId": "AUD_FW_001",
  "sections": [
    {
      "title": "当前结论",
      "content": "...",
      "riskLevel": "LOW | MEDIUM | HIGH",
      "requiresConfirmation": true
    }
  ]
}
```

## 强制规则

1. Final Writer 模式跟随 Kill Switch（SOFT→CONSERVATIVE, HARD→HARD_RISK_FINAL_ONLY, COMPLIANCE→COMPLIANCE_REJECT）
2. 所有真实交易动作必须标记 `humanConfirmationRequired: true`
3. Anti-Conclusion Checker 为 REWRITE_REQUIRED 时 Final Writer 必须重写
4. Anti-Conclusion Checker 为 BLOCK_OUTPUT 时只能输出硬风险/合规拒绝模板
