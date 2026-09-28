# super 产品分析与未来开发规划

> 更新日期：2026-06-04
>
> 定位：本文是 `super` 的产品视角总览，用于沉淀现有产品分析、体验/交互改进方向、工程治理短板和未来开发规划，并记录从本地模拟研究控制台逐步升级到受控生产级实盘自动交易系统的产品路线。本文不替代 `docs/PROJECT_DEVELOPMENT_ASSESSMENT.md`、`docs/QUANT_SYSTEM_IMPROVEMENT_PLAN.md` 或 `docs/NEXT_DEVELOPMENT_PLAN.md`；当具体开发验收、模块事实或最新开发日志与本文冲突时，以当前代码、最新验证日志和上述权威文档为准。

## 0. 参考材料与适用范围

本文基于当前仓库材料交叉整理，主要参考：

- `README.md`
- `frontend/src/routeManifest.json`
- `docs/PROJECT_DEVELOPMENT_ASSESSMENT.md`
- `docs/QUANT_SYSTEM_IMPROVEMENT_PLAN.md`
- `docs/NEXT_DEVELOPMENT_PLAN.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/TESTING_GUIDE.md`

本文只做产品分析、路线规划和治理边界记录。若后续把规划转化为前端、后端、API、schema、测试、迁移或真实券商接入实现，必须按对应模块重新做代码审查和验证。

## 1. 产品定位与不可回退边界

`super` 当前已经从早期多 Agent 演示看板，演进为本地量化研究与模拟交易控制台。产品覆盖分析任务、Agent DAG、行情与持仓输入、SignalOps 模拟股票池、Research Backtest、Research Lab、Case / Knowledge / Evaluation、插件注册、配置治理、审计和启动观测。下一阶段的产品目标是：在不破坏当前模拟安全边界的前提下，逐步建设生产级实盘自动交易所需的合规、风控、审计、券商接入、资金管理、异常处置和长期收益验证能力。

核心定位应保持清晰：

- 帮助用户完成可复核的量化研究、模拟决策、回测验证、研究沉淀和知识回归。
- 把 Agent、规则引擎、行情/持仓输入、SignalOps 和 Research Lab 串成有证据链的本地工作台。
- 让用户能判断数据来源、证据强度、缺失项、权限边界和模拟交易状态。

当前不可回退边界：

- 当前已实现系统仍是研究与模拟环境，不是生产级实盘自动交易系统。
- SignalOps 所有动作必须保持 `SIM_*`、`simulation_only=true`、`is_real_trade=false`。
- 不连接真实券商账户，不新增真实下单 API，不把沙箱动作描述成券商自动下单能力。
- Bottom Research、Backtest、SignalOps 证据默认作为可复核研究输入，不能绕过 Research Lab、Case / Knowledge / Evaluation 和人工审查边界。
- 根目录旧 `src/` 前端已删除，不应恢复为产品入口；活跃前端入口是 `frontend/src`。
- 旧 backlog 不再作为当前计划来源；后续开发优先参考当前代码、`docs/DEVELOPMENT_LOG.md`、`docs/PROJECT_DEVELOPMENT_ASSESSMENT.md`、`docs/QUANT_SYSTEM_IMPROVEMENT_PLAN.md`、`docs/NEXT_DEVELOPMENT_PLAN.md` 和 `docs/DEVELOPMENT_GUIDE.md`。

未来实盘升级边界：

- 实盘能力只能作为独立阶段引入，不能把现有 `SIM_*` 路径直接改名或复用成真实订单路径。
- 任何真实订单能力必须先通过 broker read-only、shadow live、人工确认小额实盘、受限自动执行、生产自动执行的成熟度阶梯。
- “稳定增收”应定义为长期风险调整后正期望和可控回撤目标，不得写成收益承诺；系统必须持续展示收益、回撤、胜率、风险暴露、异常订单、停机和策略失效风险。
- 实盘前必须完成合规确认、券商/交易所接入规则确认、资金和订单风控、kill switch、审计留痕、异常回滚、灾备演练、长期样本外验证和人工授权机制。

外部监管与行业约束提示：

- 美国市场接入规则强调 broker-dealer 需要建立、记录并维护风险管理控制和监管程序，用于限制金融暴露、防止错误订单、限制未授权访问并确保预交易合规。
- FINRA 对算法交易监督关注整体风险评估、开发流程、投产前测试、系统变更后的交易活动复核，以及合规人员与算法开发人员之间的有效沟通。
- 中国证监会《证券市场程序化交易管理规定（试行）》自 2024-10-08 实施，强调程序化交易报告、交易监测、风险防控、技术系统管理和高频交易差异化监管。
- 面向 A 股或跨市场实盘时，产品设计必须把“先报告、后交易”、交易所实时监控、异常交易行为约束、券商客户管理职责和技术系统管理纳入 live-readiness gate。

## 2. 当前产品地图

### 2.1 实盘升级成熟度阶梯

| 等级 | 状态 | 产品目标 | 必备门禁 |
| --- | --- | --- | --- |
| L0 | Simulation only | 保持当前模拟研究、安全回测、证据闭环和知识回归能力 | `simulation_only=true`、`is_real_trade=false`、无真实券商下单 API |
| L1 | Broker read-only | 接入券商只读账户、真实持仓、现金、成交回报和委托查询，不允许下单 | 只读 token、账户隔离、敏感信息脱敏、对账报表、权限审计 |
| L2 | Shadow live | 用真实行情和真实账户状态生成“如果下单会怎样”的影子订单，不发送真实订单 | 影子订单 ledger、真实持仓约束、预交易风控、策略失效检测、人工复核 |
| L3 | Human-confirmed live | 允许小额、低频、人工确认的真实订单，系统只提交经过审批的订单 | 双确认、额度上限、标的白名单、价格保护、kill switch、订单回报对账 |
| L4 | Constrained auto live | 在严格风控和稳定策略范围内允许受限自动执行 | 策略 promotion gate、日内亏损停机、频率限制、幂等订单、实时风控、异常熔断 |
| L5 | Production auto trading | 多策略、多账户、可观测、可审计、可恢复的生产级自动交易系统 | 合规报告、灾备演练、集中监控、长期收益/回撤验收、独立风控和审计 |

L0 到 L5 不能跳级。每一级都必须保留回退路径：发现策略失效、系统异常、数据异常、合规风险、订单回报不一致或收益/回撤超阈值时，应自动降级到更低等级或停止交易。

### 2.2 实盘产品新增能力地图

| 能力区 | 新增页面/模块方向 | 关键问题 |
| --- | --- | --- |
| Live Readiness Center | 实盘就绪中心 | 当前是否满足合规、券商、风控、资金、策略、监控和灾备门禁？ |
| Broker Connection Center | 券商连接中心 | 账户、资金、持仓、委托、成交、费率和接口健康是否可信？ |
| Pre-trade Risk Console | 预交易风控控制台 | 每笔订单是否通过资金、仓位、价格、频率、标的、T+1、涨跌停、黑名单和集中度检查？ |
| Strategy Promotion Board | 策略晋级面板 | 策略是否完成样本外、walk-forward、benchmark、压力测试、shadow live 和人工复核？ |
| Live Order Ledger | 实盘订单账本 | 订单意图、审批、发送、回报、撤单、成交、失败和对账是否完整可追踪？ |
| Incident & Kill Switch | 事故和熔断中心 | 是否能一键停机、自动熔断、保留现场、通知负责人并生成复盘？ |
| Compliance & Audit Pack | 合规审计包 | 程序化交易报告、策略变更、权限操作、订单记录、异常处置和审批证据是否可导出？ |

### 2.3 目标收益定义

“打造可以稳定增收的系统”在产品和工程上应拆成可验证指标，而不是收益承诺：

- 收益目标：长期滚动窗口内风险调整后收益为正，且能解释主要收益来源。
- 风险目标：最大回撤、单日亏损、单票集中度、行业暴露、杠杆、换手和成交滑点在阈值内。
- 稳定性目标：策略在不同市场状态、样本外窗口、真实行情延迟、数据缺失和异常波动下不过度退化。
- 执行目标：订单发送、回报、撤单、成交、失败重试和资金持仓对账稳定。
- 治理目标：任何策略上线、参数变更、风控放宽和异常恢复都有审批、审计和可回滚记录。

产品文案应避免“保证收益”“稳赚”“无风险增收”等表达，改用“目标收益”“风险调整后收益”“可控回撤”“长期正期望验证”和“策略失效自动降级”。

### 2.4 导航分组与页面职责

| 分组 | 主要页面 | 产品职责 | 当前体验重点 |
| --- | --- | --- | --- |
| Workbench | 股市全局、分析总览、新建任务、真实持仓、数据源健康、研究实验室、运行对比、实时运行、Agent DAG、Agent 辩论 / Token | 用户进入研究、创建任务、观察运行、检查数据和 Agent 输出的主要工作区 | 信息密度高，需要继续强化任务路径、证据摘要、状态解释和跨页回跳 |
| Guardrail Chain | 权限矩阵、数据引擎、DVG 门禁、风险防火墙、交易微观、量化核心、执行复核、反结论 | 将数据、证据、风险、技术面、情景和执行复核串成 guardrail 链 | 优势是边界清晰；短板是链路较长，用户需要更强的“当前结论从哪里来”导航 |
| Audit & Config | SignalOps、审计日志、最终输出、后端状态、后端调参、配置版本、插件 Agent、系统设置 | 模拟自动化、输出、审计、运行观测、配置治理和插件治理 | 高风险操作已逐步 role-aware，但跨页面提示、配置恢复影响和生产化 handoff 仍需统一 |

### 2.5 核心用户路径

1. 研究启动路径：`Portfolio -> New Task -> Live Run -> Dashboard / Final Writer / Audit`
   - 目标：用户把真实持仓或样例持仓作为研究上下文，创建分析任务，查看运行过程和最终结论。
   - 当前优势：持仓快照、broker-template 导入、风险预检和 Live Run 串联已具备。
   - 体验风险：路径长，用户需要持续看到当前 run id、portfolio snapshot、数据来源和模拟边界。

2. 证据闭环路径：`SignalOps -> Backtest -> Research Lab -> Case -> Knowledge -> Evaluation`
   - 目标：把模拟信号和回测结果沉淀为 supporting-only 研究证据，再进入知识回归和评估。
   - 当前优势：P2 closed-loop sample、Backtest verdict inputs、SignalOps selected-signal evidence、Knowledge regression 等链路已经具备浏览器 smoke 或静态 guard。
   - 体验风险：证据强度、blocking reasons、下一步动作和是否可发布知识版本仍需要更统一的呈现。

3. 自动模拟路径：`SignalOps status / tick / daily review / review queue / manual sandbox command`
   - 目标：系统自动跟踪、判断、复盘、调参和沉淀证据，用户主要做审查、授权和异常处置。
   - 当前优势：A 股规则、费用、T+1、涨跌停、候选参数复核、审查事件导出和签名 handoff 已成型。
   - 体验风险：自动化能力容易被误解成实盘自动交易，必须持续用 UI 和文档强调 simulation-only。

4. 治理与运维路径：`Backend Status -> Config Versions -> Settings -> Plugins -> Audit Log`
   - 目标：让本地运行状态、配置变更、插件包、告警/日志和审计行为可解释、可回溯。
   - 当前优势：productionHealth、operator role、配置版本、插件 artifact、local handoff 和 strict-auth smoke 已覆盖大量关键面。
   - 体验风险：外部队列、集中日志、厂商告警、object storage、KMS/legal-hold 等仍是部署侧或未来生产化工作。

### 2.6 Public Equity Investing 插件融入分析

Public Equity Investing 插件适合作为 `super` 的公开股票研究增强层，而不是交易执行器。当前第一阶段应只融入研究只读与模拟联动能力：不接真实券商，不新增真实下单 API，不把插件输出包装成最终交易建议，继续保持 `simulation_only=true`、`is_real_trade=false` 和无真实券商下单边界。

当前 Public Equity Investing 尚未配置 saved context 或外部数据源；本文只分析能力融入方式，不声称已接入 FactSet、LSEG、券商、研报、实时财务数据或内部组合模型。任何真实数据源接入都必须在后续阶段单独完成 source readiness、权限、脱敏、审计和数据质量验证。

能力映射：

| Public Equity Investing 能力 | 可融入 `super` 的位置 | 边界 |
| --- | --- | --- |
| `idea-generation` | 股市全局自动选股候选、Research Lab 候选池、SignalOps 模拟观察池 | 只生成 idea candidates / watchlist items，不输出最终买卖建议 |
| `thesis-tracker` | Research Lab 证据账本、Case / Knowledge / Evaluation 的假设、证伪、催化剂和复盘字段 | 采用 append-only 证据和阈值来源标记，不把分析师草拟阈值当成已批准规则 |
| `earnings-deep-dive` / `earnings-preview` | 财报事件证据、估值假设变化、催化剂前后复核、模型假设更新说明 | 仅作为公开信息研究输入；缺失财报、电话会、估计或价格上下文时必须标记证据缺口 |
| `portfolio-risk-management` | Portfolio / New Task 风险预检、Quant Core 风险解释、SignalOps 模拟仓位复核 | 只提供研究层仓位、集中度、对冲或降仓建议，不作为执行指令 |
| `comps-valuation` / `dcf-model-builder` / `scenario-sensitivity-generator` | Quant Core supporting-only 估值、可比公司、DCF、情景敏感性证据 | 不覆盖 DVG、Risk Firewall、Execution 或 SignalOps 的硬边界 |

可融入自身系统的五条主线：

1. 自动选股增强：把股市全局页的自动选股从“板块强弱 + 资金流 + 市场温度”扩展为“候选漏斗 + 投资假设 + 第一否决项 + 下一步研究 workflow”。候选必须标记来源、证据强度、缺失项、估值/催化剂状态和是否可进入 Research Lab。
2. 研究闭环增强：把 thesis、catalyst、earnings、valuation、risk plan 变成 Research Lab 可追踪证据，并进入 Case / Knowledge / Evaluation 的回归和复盘链路。弱证据、缺 benchmark、缺样本外或缺财报来源时继续保持 supporting-only。
3. Quant Core 增强：保留当前规则、行情、技术面、MFE/MAE 和 QIAM 证据为主，Public Equity 只提供 PM judgment、variant view、valuation context、first rejection 和 what would make it investable 等解释层输入。
4. SignalOps 模拟增强：Public Equity 输出只能成为 `review_note`、`dag_observation`、模拟复核理由或候选池解释，不生成 `BUY`、`SELL`、`AUTO_ORDER`，不绕过 A 股规则、DVG、Risk Firewall、Execution 和人工复核。
5. 插件治理增强：沿用当前 `plugin_observation`、`READ_ONLY_NO_CODE`、`NO_DIRECT_TRADE_ACTION`、禁止代码执行、禁止网络/文件访问和禁止交易动作的插件边界。Public Equity 能力即使进入 DAG，也应是只读 observation 节点，而不是可执行 Agent。

阶段路线：

| 阶段 | 目标 | 交付方向 |
| --- | --- | --- |
| P0 文档校准 | 先把插件能力、边界和融入点写清楚 | 维护本文、插件治理说明和无真实交易边界 |
| P1 股市全局自动选股增强 | 让自动选股候选具备研究解释 | 增加候选来源、投资假设、第一否决项、下一步 Research Lab 入口的产品方向 |
| P2 Research Lab 证据模型增强 | 沉淀 thesis / catalyst / earnings / valuation / risk evidence | 扩展研究证据分类、缺失项、证伪条件、复盘和知识回归字段 |
| P3 Backtest + SignalOps 模拟联动 | 候选进入模拟验证和支持性证据桥 | 结合参数扫描、walk-forward、benchmark 和 SignalOps review queue，保持 supporting-only |
| P4 生产化前置 | 只读券商、真实行情或影子盘成熟后再进入 live-readiness gate | Public Equity 输出只能作为 live-readiness 证据之一，不能单独批准实盘 |

明确不做：

- 不把 Public Equity Investing 插件包装成真实交易推荐器。
- 不新增实盘交易按钮、券商订单路由、自动下单 API 或真实订单账本。
- 不让财报、估值、情景或 PM judgment 覆盖硬风控和执行权限。
- 不声称当前系统已经接入外部券商、付费研报、实时估计、实时财务模型或机构级数据源。

## 3. 产品体验分析

### 3.1 已形成的产品优势

- 产品边界清楚：研究、模拟、回测、证据沉淀和治理形成了完整工作台，而不是单页 Agent 演示。
- 证据链意识强：run、SignalOps、Backtest、Research iteration、Case、Knowledge、Evaluation 和 audit 都在向同一条可复核链路收敛。
- 角色边界持续补齐：Portfolio、New Task、Backtest、Research Lab、SignalOps、Config Versions、Settings、Plugins 等高风险入口已经逐步接入 role-aware 禁用和 disabled reason。
- 本地验证基础扎实：`validate:phase1-3`、`validate:premerge`、`smoke:frontend`、`smoke:strict-auth-browser:*` 等检查能覆盖主链路和关键边界。
- 自动化方向正确：SignalOps 的默认方向是系统自动运行，人类负责审查、授权、异常处置和边界复核，不把人工日常触发变成主路径。

### 3.2 主要体验摩擦

| 区域 | 当前摩擦 | 改进方向 |
| --- | --- | --- |
| Dashboard | 信息面广，用户需要快速判断“现在该看什么、下一步该做什么” | 强化决策工作台：当前状态、证据分数、阻塞原因、下一步复核动作、模拟边界始终可见 |
| Portfolio / New Task | 导入、样例、风险预检、任务创建之间存在多步上下文传递 | 固化“当前使用的持仓快照”提示，显示现金、集中度、可卖数量、来源模板和风险约束 |
| Live Run / Agent DAG / Debate | 运行状态、Agent 输出来源、LLM 降级和 token 信息分布在多处 | 建立统一 run context header，跨页保留 run id、状态、数据源、LLM/source classification |
| SignalOps | 控制台能力丰富，容易把模拟动作误读为真实交易动作 | 所有交易语义控件继续显示 `仅模拟`、`真实交易：否`、动作原因、A 股规则和审查状态 |
| Backtest | 参数扫描、实验包、benchmark、walk-forward 和 validation protocol 信息密度高 | 用分层摘要先回答“能否支持研究结论”，再展开 trial/window/hash/限制信息 |
| Research Lab | 子路由和证据桥接多，用户需要理解成熟度、blocking reason 和下一步 | 加强工作流向导、证据强度分层、缺失项、下一步动作、回跳到 Backtest/SignalOps 的上下文 |
| Case / Knowledge / Evaluation | 沉淀和回归治理已复杂化 | 用统一状态解释区分 warn-only、blocking、waiver、regression、observation-only |
| Backend / Config / Plugins | 配置、插件、告警、handoff 的治理概念多 | 统一展示 role、审批、影响面、恢复来源、handoff custody 和部署侧责任 |

### 3.3 可见证据质量

当前产品最大的价值不只是“跑出结论”，而是让结论可复核。后续所有新页面和新流程应尽量回答以下问题：

- 这个结论来自哪个 run、portfolio snapshot、SignalOps signal、Backtest report 或 Research iteration？
- 证据强度是 strong、supporting-only、weak、sample/mock/fallback，还是缺失？
- 是否存在 benchmark、out-of-sample、walk-forward、parameter-scan、case regression 或 knowledge impact？
- 当前动作是否需要 researcher、operator 或 admin？
- 当前动作是否仍然是 `simulation_only=true`、`is_real_trade=false`？
- 下一步应该补数据、补样本、跑评估、发布知识版本、回滚配置，还是只做观察？

## 4. 视觉与交互改进方向

### 4.1 信息架构

- 保持现有三组导航，但为长链任务增加跨页上下文：当前 run、portfolio snapshot、research iteration、backtest run 和 selected signal。
- Research Lab 子路由应继续作为研究闭环中心，不再新增平行的孤立研究页面。
- Guardrail Chain 页面应按“数据 -> 证据 -> 风险 -> 量化核心 -> 执行复核 -> 反结论”呈现因果关系，减少用户在单个模块里迷失。

### 4.2 页面层级

- 页面顶部优先放“当前状态 + 关键边界 + 下一步动作”，再放明细表格和 JSON/trace。
- 对信息密度高的页面使用固定结构：状态摘要、证据来源、阻塞原因、操作区、历史/审计、技术细节。
- 对高风险按钮统一使用 disabled reason、role label、审批状态和 action boundary，不只依赖按钮禁用。

### 4.3 状态、空态与失败态

- 空态必须告诉用户缺什么证据、如何创建样例、是否可以继续观察。
- 失败态要区分数据缺失、权限不足、后端未就绪、LLM 降级、行情 fallback、任务 stale、worker 未运行。
- 对 long-running job 使用进度、lease/attempt、cancel/retry eligibility 和 handoff custody，避免用户把本地 SQLite worker 误认为生产级分布式队列。

### 4.4 复核入口

- SignalOps、Backtest、Research Lab、Knowledge Versions 和 Config Versions 的复核入口应使用一致文案：复核、验证、批准、驳回、回滚、移交、观察。
- 不新增“立即实盘”“自动下单”等暗示真实交易的入口。
- 对模拟动作继续使用 `SIM_*`、沙箱、模拟、review-only、supporting-only 等明确语义。

## 5. 工程与治理分析

### 5.1 当前治理优势

- 权限和审计边界已经成为产品主线，多个页面具备 operator role、admin gate、disabled reason 和 handler-level short-circuit。
- strict-auth browser smoke 已覆盖 Dashboard、Portfolio -> New Task -> Live Run、SignalOps、Backtest、Research Lab、Config Versions、Plugins、Backend Status 等关键路径。
- SignalOps 和 Backtest 的模拟边界有模型、API、前端类型、页面文案和浏览器断言共同守护。
- Config Versions、Plugin artifact、ops log、alert outbox 和 handoff manifest 已经开始形成部署侧交接契约。

### 5.2 真实短板

- 外部 worker/queue、跨主机 lease、分布式并发限制和幂等恢复仍不是产品内已完成能力。
- 长周期真实样本外验证、真实 benchmark 数据源和系统化参数回归仍不足，不能把当前本地 scan 直接解释为策略有效性证明。
- 非 Agent Runtime 外部配置面的安全 restore executor 仍需逐步补齐。
- 集中日志、厂商级告警、object storage、KMS/legal-hold、外部恶意软件扫描和长期 retention 仍是部署侧或未来生产化能力。
- 历史文档多，若不持续压缩和标记权威来源，容易把旧 backlog 或旧架构重新带回当前开发。

### 5.3 开发治理原则

- 新增能力先接入现有模块边界和 canonical route，不新建平行闭环。
- 修改 API schema 时同步前端类型、client guard、调用方和测试。
- 修改 auth/session/cookie/middleware 时检查 token 来源、cookie name、sameSite、secure、domain、path，并补 session 持久化测试。
- 修改高风险写入口时同步前端 role-aware 禁用、后端权限、审计记录和 smoke guard。
- 修改 SignalOps 交易语义时必须保留 `simulation_only=true`、`is_real_trade=false`、`SIM_*`，并覆盖 A 股规则边界。
- 文档更新必须基于当前源码和验证结果，不从已删除旧 backlog 直接复制未复核条目。

## 6. 未来开发规划

### P0：文档和入口校准

目标：降低历史文档和复杂入口对用户的误导。

交付物：

- 明确当前文档权威地图：产品分析、整体评估、量化改进计划、Phase 计划、开发指南、测试指南各自职责。
- 在核心入口继续强调 `frontend/src` 是活跃前端，根目录旧 `src/` 不恢复。
- 为 Dashboard、Research Lab、SignalOps 和 Config Versions 增加或维护“当前边界 / 当前下一步”型文档说明。

验收方式：

- `git diff` 只包含目标文档或明确文档范围。
- `rg` 检查旧 backlog 没有被重新写成当前计划来源。
- 文档持续包含 `simulation_only=true`、`is_real_trade=false` 和无真实券商下单边界。

### P1：产品体验一致性

目标：让用户在任何核心页面都能快速判断当前状态、权限、证据和下一步。

交付物：

- 统一 run context header：run id、portfolio snapshot、workflow status、data source、LLM/source classification、simulation boundary。
- 统一 role-aware action pattern：role label、disabled reason、审批要求、handler guard 和 smoke hook。
- 统一证据摘要组件：source、timestamp、evidence strength、missing items、next action、blocking reasons。
- 对 Dashboard、SignalOps、Backtest、Research Lab 优先做信息层级和状态摘要优化。

验收方式：

- `npm.cmd run typecheck`
- `npm.cmd run lint`
- `npm.cmd run smoke:frontend`
- 涉及浏览器主链路时追加对应 `npm.cmd run smoke:strict-auth-browser:*` 场景。

### P2：研究闭环深度

目标：把当前可见样例闭环升级为更有研究可信度的长期验证工作台。

交付物：

- 强化 Portfolio -> New Task -> Live Run -> Research Lab 的同一套 ID 追踪。
- 扩展 Backtest benchmark、out-of-sample、walk-forward、parameter-scan 和 experiment-package 的长期沉淀。
- 强化 SignalOps tick/review/parameter diff 到 Research verdict inputs 的 supporting-only 证据桥。
- 增强 Case / Knowledge / Evaluation 的 regression、waiver、case-set quality 和 impact analytics。

验收方式：

- `npm.cmd run validate:phase1-3`
- `npm.cmd run validate:module-participation`
- 相关 focused backend tests 和 strict-auth browser research/backtest/signalops 场景。
- 所有桥接证据继续证明 supporting-only，不自动接受结论、不触发真实交易。

### P3：生产化工程能力

目标：把本地工作台的运维、队列、配置和告警交接能力推向可部署但仍受控的工程形态。

交付物：

- 外部 worker/queue 设计与实现：claim、heartbeat、lease、retry、DLQ、幂等、跨进程恢复。
- 配置恢复扩展：非 Agent Runtime surface 的 restore executor、审批影响说明、secret-safe restore。
- 部署侧日志/告警：集中日志、厂商 webhook、长期 retention、sidecar readiness、handoff custody。
- Backend Status 提供更完整的生产 readiness、趋势、失败原因和部署责任分界。

验收方式：

- focused backend tests 覆盖队列、配置恢复、告警和 handoff。
- `npm.cmd run smoke:strict-auth-browser:platform`
- 大范围改动时运行 `npm.cmd run validate:premerge`。

### P4：平台扩展和长期治理

目标：在不破坏 simulation-only 和插件安全边界的前提下，扩展平台能力。

交付物：

- 插件系统生产治理：artifact storage、hash verification、retention lifecycle、外部扫描/威胁情报 handoff、resource quota。
- SQLite + JSON 状态继续收敛，减少双写和历史状态漂移。
- 更系统的跨页面 Playwright E2E：复杂状态矩阵、失败态、权限态、长链回跳和 artifact 下载。
- 长期文档压缩：保持一个清晰权威入口，避免旧计划、旧术语和旧边界复活。

验收方式：

- 插件、数据、配置、审计和浏览器 smoke 分场景验证。
- 每个扩展项必须声明不改变 `simulation_only=true`、`is_real_trade=false`、无真实券商下单 API。
- 新增高风险入口必须同时具备 role-aware UI、后端权限、审计、失败路径测试和文档边界。

### P5：实盘只读与影子盘

目标：开始接近真实交易环境，但仍不发送真实订单。

交付物：

- Broker read-only adapter：只读取账户、现金、持仓、委托、成交、费率和交易日历。
- Broker Connection Center：显示接口健康、权限范围、只读/可写状态、脱敏账户标识和最新对账时间。
- Shadow live engine：根据真实账户状态生成影子订单，记录本该下单的意图、价格、数量、风控检查、预估滑点和未执行原因。
- Live readiness gate：合规报告、券商连接、数据质量、预交易风控、策略验证、监控告警和灾备状态必须全部通过后，才能申请 L3。

验收方式：

- 所有 broker token 默认只读，后端测试证明写权限 token 不会被默认使用。
- shadow order 必须带 `is_real_trade=false`，且没有任何真实下单 API 调用。
- 浏览器 smoke 证明只读账户、影子订单、对账状态和 readiness blockers 可见。
- 影子盘至少经历足够长的市场周期和异常行情窗口，收益、回撤和误触发记录进入 Research Lab / Evaluation。

### P6：人工确认小额实盘

目标：在强门禁下允许人工确认的小额真实订单，用真实成交验证执行链路。

交付物：

- Live Order Approval：每笔订单进入审批队列，显示策略依据、风控结果、预估成本、最大损失、撤单计划和回滚影响。
- Human-confirmed broker execution：只有 admin/operator 双确认、额度内、标的白名单内、风控通过的订单才能发送。
- Real order ledger：订单意图、审批、发送、broker ack、成交、撤单、失败、资金持仓对账全链路记录。
- Kill switch：全局停机、策略停机、账户停机、单标的停机、亏损阈值停机和异常订单自动停机。

验收方式：

- 单元/API 测试覆盖重复订单、网络重试、broker ack 丢失、部分成交、撤单失败、资金不足、交易时段关闭、价格越界、权限不足。
- 浏览器 smoke 覆盖审批、拒绝、发送、回报、熔断、审计导出。
- 所有真实订单默认小额、低频、白名单，并要求人工确认；不得直接进入全自动。
- 每轮真实订单试运行后必须生成 post-trade review，并能回写 Case / Knowledge / Evaluation。

### P7：受限自动实盘与收益治理

目标：只让经过长期验证且风险可控的策略进入受限自动执行。

交付物：

- Strategy promotion gate：策略必须通过样本外、walk-forward、benchmark、shadow live、人工小额实盘、回撤和异常订单验收。
- Auto-live policy：每个策略有资金上限、单日亏损上限、单票/行业集中度、换手率、订单频率、可交易时间、可交易标的和自动降级规则。
- Revenue governance dashboard：展示收益、风险调整收益、最大回撤、胜率、盈亏比、滑点、费用、异常订单、策略失效信号和降级记录。
- Independent risk override：风控层独立于策略层，能拦截或撤销策略订单，并保留审计。

验收方式：

- 自动实盘只允许从 L6 已验证策略晋级，不能从模拟策略直接晋级。
- 任一关键指标越界时自动降级到人工确认或停止交易。
- 生产监控必须覆盖行情延迟、broker 状态、订单延迟、成交回报、资金对账、错误率、收益回撤和异常交易行为。
- 文档和 UI 必须持续声明收益不保证，目标是长期风险调整后正期望和可控回撤。

## 7. 当前推荐优先级

短期优先级：

1. 保持文档权威地图清晰，避免旧 backlog 和旧前端入口回流。
2. 强化 Dashboard、Research Lab、SignalOps、Backtest 的状态摘要和证据解释。
3. 统一高风险操作的 role-aware 提示、disabled reason、审批和审计。

中期优先级：

1. 提升真实样本外、benchmark、长期参数扫描和 Technical Kline 长窗口回归能力。
2. 扩展 Case / Knowledge / Evaluation 对 regression、waiver、impact analytics 的治理可见性。
3. 建立更系统的浏览器 E2E 状态矩阵，覆盖复杂失败态和跨页面回跳。

长期优先级：

1. 外部 worker/queue、集中日志、厂商告警和部署侧 custody。
2. 插件 artifact 的生产级存储、扫描、保留和配额治理。
3. 按 L1-L5 成熟度阶梯推进实盘：先只读和影子盘，再人工确认小额实盘，最后才是受限自动实盘。
4. 在独立设计、独立权限、独立审计、合规确认、长期验证和人工授权前，不允许任何真实券商下单能力进入默认路径。

## 8. 验证与维护方式

本文作为 docs-only 产品规划文档，更新时默认执行：

- `git status --short`
- `git diff -- docs/PRODUCT_ANALYSIS_AND_ROADMAP.md`
- `rg -n "Public Equity Investing|idea-generation|thesis-tracker|portfolio-risk-management|plugin_observation|READ_ONLY_NO_CODE|NO_DIRECT_TRADE_ACTION|simulation_only=true|is_real_trade=false|自动选股|Research Lab|SignalOps|实盘升级|影子盘|人工确认小额实盘|受限自动实盘|无真实券商下单|产品体验|视觉|工程治理|未来开发规划" docs/PRODUCT_ANALYSIS_AND_ROADMAP.md`

如果文档更新同步修改产品 UI、API、schema、权限、测试、迁移或 smoke fixture，应按 `docs/DEVELOPMENT_GUIDE.md` 和 `docs/TESTING_GUIDE.md` 选择对应检查命令，而不能只跑文档级检查。
