# 部署指南

## 1. 最推荐的落地方式

不要做一个超长 Prompt。

推荐做成工作流：

前端 / 聊天入口
→ Router
→ Orchestrator
→ 多数据工具
→ DVG
→ Risk
→ ATrade
→ Market
→ Factor
→ QIAM
→ Scenario
→ Portfolio
→ Execution
→ Anti-Conclusion
→ SignalOps
→ Final Writer

## 2. MVP 第一阶段

先做保守可用版：

1. Router
2. Data Fetch
3. DVG Evidence Gate
4. Risk Firewall
5. ATrade
6. Market Quick
7. Factor Slicing Lite
8. Final Writer

第一阶段目标：

- 不幻觉
- 不乱给买卖点
- 能判断是否值得继续研究
- 能识别数据缺口
- 能识别明显硬风险

## 3. 第二阶段

加入：

1. QIAM
2. Scenario Engine
3. Portfolio Agent
4. Execution Agent
5. SignalOps

第二阶段目标：

- 让量化模块参与校准，但不主导决策
- 让组合和执行约束真正生效
- 每次候选信号都能复盘

## 4. 第三阶段

加入：

1. Anti-Conclusion Checker
2. Meta Review
3. Memory
4. Simulation
5. Debate

第三阶段目标：

- 发现系统性错误
- 生成候选补丁
- 做压力测试
- 做相似失败案例提醒

## 5. Dify / Cherry Studio / LangGraph 用法

### Coze

当前项目不再提供 Coze SignalOps skill 或 `/api/coze/signalops/*` 接口；SignalOps 只通过本地 API 和前端工作台运行。

### Dify

- 用 Workflow。
- Router 节点输出 task_type。
- 条件分支选择 FAST / STANDARD / DEEP。
- 工具节点放 Data Fetch。
- LLM 节点分别加载对应 Agent 文件。

### Cherry Studio

- 适合先做纯对话版本。
- 可把 `22_MASTER_SYSTEM_PROMPT_简版.md` 当主 Prompt。
- 如果要多 Agent，需要配合外部脚本或 API 编排。

### LangGraph

- 最适合完整落地。
- 每个 Agent 是一个 node。
- State 中保存所有节点 JSON。
- 条件边实现 Kill Switch。
- Final Writer 只读取 final_context。

## 6. 推荐工程目录

```text
tianyuan_quant_v10_2/
  prompts/
    03_ROUTER_Agent.md
    05_DVG_Evidence_Gate_Agent.md
    06_RISK_Firewall_Agent.md
    ...
  tools/
    market_api.py
    dvg_tools.py
    qiam_tools.py
    signalops_store.py
  workflows/
    graph.py
    config.yml
  schemas/
    shared_schemas.py
  logs/
    audit_log.jsonl
    error_ledger.jsonl
```

## 7. 开发优先级

优先级 1：DVG + Risk + ATrade。

原因：先保证不会胡说、不会越权、不会假装能成交。

优先级 2：Final Writer 限权。

原因：很多幻觉不是前面判断错，而是最后表达时语气漂移。

优先级 3：QIAM 折扣。

原因：量化模块容易让模型过度自信，必须工程层打折。

优先级 4：SignalOps。

原因：没有复盘账本，系统无法进化。

## 8. 不建议一开始做的东西

- 完整红蓝辩论
- 大规模回测
- 复杂 Memory
- 自动补丁部署
- 高频盘口模型
- 自动交易

这些都应该放到第三阶段以后。
