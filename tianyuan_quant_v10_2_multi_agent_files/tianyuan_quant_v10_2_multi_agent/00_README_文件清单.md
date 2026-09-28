# 天元量化 Agent v10.2 多 Agent 文件包

本文件包将 v10.2 拆成可落地的多 Agent 结构，适合放入 Dify、LangGraph、Cherry Studio、自研 API 工作流或任意支持多节点编排的平台。当前项目不再提供 Coze SignalOps 接口。

## 推荐使用顺序

1. `01_ARCHITECTURE_多Agent总体架构.md`：先看整体结构。
2. `02_ORCHESTRATOR_主控编排Agent.md`：工程主控，负责路由、截断、降级。
3. `03_ROUTER_Agent.md`：识别任务类型和运行模式。
4. `04_DATA_FETCH_Agent.md`：只取数据，不做判断。
5. `05_DVG_Evidence_Gate_Agent.md`：合并 Evidence + DVG，做数据门禁。
6. `06_RISK_Firewall_Agent.md`：硬风险防火墙。
7. `07_ATRADE_Agent.md`：A 股交易制度和微结构检查。
8. `08_MARKET_Regime_Agent.md`：市场情绪、题材地位、风格状态。
9. `09_FACTOR_SLICING_Agent.md`：因子切割和污染识别。
10. `10_QIAM_Agent.md`：机构量化适宜性校准，带折扣因子。
11. `11_SCENARIO_ENGINE_Agent.md`：三情景和赔率质量。
12. `12_PORTFOLIO_Agent.md`：组合角色、仓位上限和风险预算。
13. `13_EXECUTION_Agent.md`：执行可达性和动作门禁。
14. `14_ANTI_CONCLUSION_Agent.md`：反结论检查，防止硬风险后语义漂移。
15. `15_SIGNALOPS_Agent.md`：信号生命周期和全自动模拟交易股票池。
16. `16_META_REVIEW_Agent.md`：错误账本和候选补丁。
17. `17_FINAL_WRITER_Agent.md`：最终表达，不重新决策。
18. `18_SHARED_SCHEMAS.md`：共享字段、动作枚举、Kill Switch。
19. `19_WORKFLOW_CONFIG.yml`：可直接参考的工作流配置。
20. `20_TOOL_CONTRACT.md`：工具/API 契约。
21. `21_DEPLOYMENT_GUIDE.md`：实际落地步骤。
22. `22_MASTER_SYSTEM_PROMPT_简版.md`：纯对话或单 Agent 兜底版本。

## 落地原则

- API 工程环境：不要把所有文件一次性塞进一个模型。按节点加载对应 Agent 文件。
- 纯对话环境：使用 `22_MASTER_SYSTEM_PROMPT_简版.md`，默认保守。
- 工具不可用时：所有精确数值、概率、EV、盘口、资金筹码判断全部降级。
- 硬风险触发时：直接进入 `HARD_RISK_FINAL_ONLY`，禁止继续找看多理由。

## 推荐最小可用 MVP

第一阶段只需要 8 个节点：

Router → Data Fetch → DVG → Risk → ATrade → Market → Factor Slicing Lite → Final Writer

第二阶段再加入：

QIAM → Scenario → Portfolio → Execution → SignalOps

第三阶段加入：

Anti-Conclusion → Meta Review → Memory / Simulation / Debate
