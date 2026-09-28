# 轻量化防御性股票分析：设计规格

- 日期：2026-08-24
- 状态：已完成交互式设计确认；书面规格待用户复核；实现尚未开始
- 目标目录：lightweight-stock-analysis
- 产品定位：A 股与港股的研究型、防御性全市场客观预筛工具
- 顶层公式：Defensive Score 2.0（DS2）
- 实现校准档：LSA-DS2 2.0.0

## 1. 背景与目标

本项目从原有大型研究控制台中拆出“股票数据准备、规则筛选、评分解释、人工复核、结果导出”这一条最短闭环，并在新目录内重新实现。新应用不复制原项目的任务编排、Agent DAG、SignalOps、回测或交易功能，也不在运行时依赖这些旧模块。

产品目标：

1. 按需扫描 A 股和港股全市场，完成客观硬过滤与六个客观维度评分。
2. 自动选出客观分最高的 50 个可复核候选。
3. 由 AI 生成“行业前景”和“护城河”证据草稿，但由用户最终确认。
4. 使用唯一的 DS2 公式形成“客观 Top 50 候选范围内”的可追溯八维总分与排名。
5. 数据不足、来源冲突或人工复核未完成时，明确显示状态，不生成伪造分数或正式排名。
6. 结果仅用于研究，不连接券商、不自动下单、不表达确定性收益承诺。

## 2. 明确不做的范围

首版不包含：

- 原项目的 AnalysisRun、Agent 编排、SignalOps、研究闭环、回测或订单执行。
- Redis、Celery、消息队列、分布式任务、多租户或云端账户系统。
- 盘中实时行情、定时自动扫描、分钟级信号。
- 组合优化、仓位建议、买卖点、价格预测。
- 未经许可的网页抓取、规避访问限制或实时行情再分发。
- 用模拟值、默认 0 分、默认 50 分或旧缓存冒充真实数据。
- 用 S/A/G 等角色标签替代数值评分；角色标签仅供用户人工标注。

## 3. 核心设计原则

### 3.1 单一公式

全项目只允许使用以下总分公式：

    DS2 =
      0.20 × IndustryProspect
    + 0.18 × EarningsStability
    + 0.15 × CashFlow
    + 0.12 × BalanceSheet
    + 0.12 × Valuation
    + 0.08 × ShareholderReturn
    + 0.08 × LowVolatility
    + 0.07 × Moat

八个维度均为 0–100 分，权重合计 100%。配置文件必须包含公式版本与内容哈希；历史公式不得混入同一次扫描。

### 3.2 先过滤，后评分

行业适用性、五年数据完整性、盈利与经营现金流底线、重大造假和关键数据冲突在评分之前处理。被排除或模型不适用的证券不参与 Top 50。

### 3.3 缺失不是中性

任何必需指标缺失时，不补 0、不补 50、不按剩余权重重新归一化。系统将该证券标为 PARTIAL、UNAVAILABLE 或 CONFLICTED，并说明缺失字段与来源。

### 3.4 机器计算与人工判断分离

财务、估值、股东回报和波动率由确定性代码计算；行业前景与护城河由 AI 提供带证据的建议，用户确认后才进入正式 DS2。前端不自行计算分数。

### 3.5 可追溯优先

每个输入必须能追溯到证券、报告期、公告日期、抓取时间、数据源、原始工件和解析器版本。每个输出必须能追溯到规则版本、配置哈希和计算明细。

### 3.6 参考公式与项目校准的边界

参考对话直接固定的内容：

- DS2 八个顶层维度及其 20/18/15/12/12/8/8/7 权重。
- 先做行业与适用性硬过滤。
- 盈利、现金流、资产负债、估值、股东回报、低波动的原始指标方向与部分提示阈值。
- 行业前景与护城河属于主观分析维度。
- S/A/G 没有给出数值边界；总分是研究优先级且存在约 ±2 分解释误差。

本规格新增、并非参考对话逐项给出的项目校准：

- 六个客观维度的子权重、聚合口径、完整分段锚点和样本下限。
- 行业前景与护城河的子项权重及证据量表。
- AI 只建议、用户确认的复核流程，以及缺失不补 0/50、不重新分配权重的安全规则。
- 行业可比组、A/H 实体去重、数据冲突、恢复、缓存和排名平局规则。
- “全市场六维客观预筛，再对 Top 50 计算完整 DS2”的产品漏斗。

这些新增规则统一命名为 LSA-DS2 2.0.0 校准档。批准本书面规格即表示批准该校准档；它不被描述为参考对话的原文公式。校准档改变时必须产生新版本、配置哈希和新扫描，不能改写历史结果。

该漏斗有明确召回边界：未进入 ObjectiveScore Top 50 的证券不会计算 IndustryProspect 与 Moat，因此最终页面只能称为“客观 Top 50 内部 DS2 排名”，不得称为“全市场 DS2 排名”或暗示它不会漏掉主观维度很强的证券。

## 4. 总体架构

采用单机模块化单体：

    React / Vite 单页前端
                 |
              FastAPI
                 |
        扫描编排与领域服务
        |       |       |
      数据层   评分层   证据采集与 AI 适配器
                 |
               SQLite

边界如下：

- 前端：展示状态、发起扫描、复核证据、确认主观分、导出结果。
- API：参数验证、鉴权边界、资源状态与错误协议。
- providers：只负责获取、解析和规范化数据，不计算业务分数。
- domain：纯函数规则、硬过滤、锚点映射、评分与排名。
- services：组合 provider、domain、持久化和审计。
- jobs：由 FastAPI lifespan 启动的同进程 embedded runner，统一认领 preflight、数据快照、客观扫描、证据采集、AI 草稿和克隆任务，负责检查点、取消、恢复和失败处理。
- db：SQLite 表、事务、迁移和仓储。
- evidence service：采集、导入、冻结、验证和关联证据。
- AI adapter：OpenAI-compatible 接口的结构化证据草稿；只读取冻结 EvidenceBundle，不参与检索或客观计算。

首版只允许一个可写后端进程、一个 embedded runner 和一个正在执行的后台任务；其他合法任务可持久化排队。复核类任务优先于尚未开始的新扫描，以免新一轮全市场同步阻塞当前人工复核。部署时必须使用一个 Uvicorn worker；runner 通过带 fencing token 的数据库租约认领任务，不使用 FastAPI BackgroundTasks 作为持久任务队列。

## 5. 目录设计

    lightweight-stock-analysis/
      backend/
        pyproject.toml
        requirements.lock
        alembic.ini
        app/
          main.py
          cli.py
          api/
          domain/
          providers/
          services/
          jobs/
          db/
        tests/
          api/
          domain/
          providers/
          services/
      frontend/
        package.json
        pnpm-lock.yaml
        vite.config.ts
        src/
          api/
          components/
          features/
            scan/
            review/
            ranking/
      config/
        defensive-score-2.0.yaml
        public-source-allowlist.yaml
      data/
      scripts/
        start-dev.ps1
      docs/
        superpowers/
          specs/

data 目录、SQLite 文件、导入原件、缓存、导出文件、本地密钥和视觉探索工件必须被 Git 忽略。

子应用拥有自己的 Python 依赖清单、前端 package.json 与 pnpm-lock.yaml、迁移配置、环境变量示例和启动脚本。禁止 Python 导入父项目 backend.app.*，禁止前端跨目录引用父项目源码；可借鉴旧契约，但必须重新实现为新的、最小且独立的领域接口。父仓库的 package.json、package-lock.json、node_modules、数据库和运行配置不属于本应用依赖。

## 6. 市场与证券主数据

### 6.1 标识模型

系统区分“发行人实体”和“上市证券”：

- entity_id：经济实体，用于合并 A/H 同发行人的实体级数据。
- listing_id：具体上市证券，至少包含市场、交易所和代码。
- A 股 listing_id 示例：CN.SSE.600000。
- 港股 listing_id 示例：HK.HKEX.00700。

证券主数据至少保存：

- entity_id、listing_id、证券简称、法定名称。
- 市场、交易所、币种、上市日期、退市状态。
- 行业分类代码、名称、分类体系版本、有效日期。
- A/H 同发行人映射来源与置信状态。
- 最近交易日、证券状态和数据可用状态。

### 6.2 全市场范围

- A 股：上交所、深交所和北交所当前上市普通 A 股；退市股、优先股、基金、债券和存托凭证不进入首版扫描。
- 港股：港交所主板或 GEM 当前上市的普通股，包括 H 股、红筹股、P 股、香港本地公司和其他合格海外发行人普通股。
- 结构性产品、基金、债券、优先股、权证和其他非普通股证券不进入首版扫描。
- 上市不足五个完整财年的证券保留在主数据中，但在硬过滤阶段排除。

证券池快照必须保存官方或授权主数据中的证券类型、主板/GEM 市场和上市状态；不能仅凭代码或名称猜测普通股身份。

### 6.3 A/H 同发行人

实体级维度共享同一组规范化事实：

- 行业前景
- 盈利稳定性
- 现金流
- 资产负债表
- 护城河

上市证券级维度单独计算：

- 估值
- 股东回报
- 低波动

实体级财务事实以 entity_id 为主体；价格、每股数据、股份类别和市场行为以 listing_id 为主体。评分存储必须显式记录 subject_type 与 subject_id，不能把实体分和上市证券分写入同一不带主体类型的键。

客观 Top 50 之前先为每个实体选择一个代表 listing，防止同一发行人占用两个候选名额。两个上市地都为 READY 时，预筛代表按以下顺序选择：

1. 未舍入 ObjectiveScore 更高者。
2. 未舍入 Valuation 更高者。
3. 当前绝对 PE_TTM 更低者。
4. listing_id 字典序较小者。

六维客观分仍为每个 READY listing 单独保留，“全部上市地客观排名”不影响核心 Top 50 名额。

主观维度按 entity_id 只复核一次并传播到该实体的全部 listing。完成主观复核后，默认最终核心清单的代表 listing 按以下顺序重新选择：

1. 未舍入 DS2 更高者。
2. 未舍入 Valuation 更高者。
3. 未舍入 ShareholderReturn 更高者。
4. listing_id 字典序较小者。

用户可在最终导出时选择“全部上市地”，但不得把同一发行人的两个上市地误计为两个独立实体。

## 7. 数据来源与治理

### 7.1 来源优先级

每个字段按以下顺序尝试：

1. 已授权的正式 API。
2. 用户导入的 CSV/XLSX。
3. public-source-allowlist.yaml 中明确允许的公开网页或公告。
4. 标记缺失。

优先级不是无条件覆盖。若低优先级来源具有更晚公告日期，或高优先级值不能通过质量检查，必须标记候选值冲突，不能自动覆盖；修复后生成新的 data_snapshot。

### 7.2 首版来源策略

- A 股：Tushare 或用户配置的授权数据网关作为主要结构化来源。
- 港股：授权 API 或用户导入作为主要结构化来源。
- 港交所披露页面和发行人公告只作为允许范围内的收盘后事实与证据来源，不假定可用于实时行情再分发。
- 公开网页 provider 必须逐域名、逐路径、逐用途列入 allowlist，并配置速率限制、缓存周期、解析器版本和失败策略。
- 主观复核使用的 EvidenceBundle 只能由已配置 provider、已提交导入或用户提交且通过 allowlist 校验的来源组成。
- 禁止通用搜索结果页爬取、任意 URL 抓取和绕过验证码或访问控制。

正式 provider 开发前应再次核验数据许可、接口权限和字段定义。当前设计参考了 Tushare 的财务指标与现金流量表文档，以及港交所的实时数据服务和上市公司披露检索页面。

### 7.3 数据能力 Gate 0

应用能力状态与扫描结果分开显示：

- NOT_CONFIGURED：没有真实授权来源；只允许查看界面和运行离线 fixture 测试，禁止创建标记为真实的扫描。
- LIVE_PARTIAL：至少一个市场可读，但授权、字段许可或覆盖率未达到全市场门槛；允许带明显警示运行指定市场，禁止宣称 A 股与港股全市场能力已验收。
- LIVE_READY：A 股与港股都通过授权、许可、覆盖率和真实读回检查。

preflight 先从指定 universe_authority 生成不可变 universe_reference_snapshot。A 股基准范围是上交所、深交所和北交所当前普通 A 股；港股基准范围是港交所主板/GEM 当前普通股。基准必须来自交易所、监管机构或单独配置的授权主数据源，保存范围规则与内容哈希；被测 provider 自己的过滤结果不能同时充当唯一分母。

覆盖率逐市场计算：

- SecurityMasterCoverage = 成功匹配的合格 listing 数 / reference snapshot 合格 listing 数；provider 多出的未知证券另报，不进入分母。
- PriceCoverage = market_effective_date 有有效复权与未复权收盘价的 listing 数 / reference snapshot 合格 listing 数。
- ValuationCoverage = 同时有有效正值 PE_TTM、总市值和完全摊薄股数的 listing 数 / TTM 归母净利润为正的 reference listing 数。
- PriceHistoryCoverage = 满足三年 Beta、最大回撤和 36 个月下行捕获最小样本要求的 listing 数 / 上市满三年的 reference listing 数。
- PEHistoryCoverage = 具有至少 36 个月且交易日覆盖率不低于 80% 的 PE_TTM 历史 listing 数 / 当前 PE_TTM 为正且上市满三年的 reference listing 数。
- BenchmarkCoverage = 两个 canonical total-return benchmark 均满足相应三年日/周和 36 个月月度样本要求时为 100%，否则为 0%。
- FinancialCellCoverage = 有效五年字段单元格数 / 预期单元格数。分母为上市满五年的 reference entity × 5 财年 × 必需字段；零值股息、回购或商誉减值只有在来源明确报告“无/零”时才算有效。
- RiskCoverage = 成功返回“命中”或“无命中”的监管查询 entity 数 / reference snapshot entity 数。

五年财务必需字段固定为：归母净利润、经营活动现金流、资本开支、加权 ROE、总资产、总负债、现金及现金等价物、短期有息债务、长期有息债务、EBIT、EBITDA 或可推导 EBITDA 的折旧摊销、利息费用、现金股息、已完成回购、商誉减值和期初归母净资产。

LIVE_READY 的最低门槛：

- SecurityMasterCoverage 不低于 98%。
- PriceCoverage 和 ValuationCoverage 均不低于 95%。
- PriceHistoryCoverage 不低于 90%，PEHistoryCoverage 不低于 85%，BenchmarkCoverage 必须为 100%。
- FinancialCellCoverage 不低于 85%。
- RiskCoverage 不低于 95%。
- 每个 provider 均记录账户权限、允许用途、可再分发边界和最后一次成功 preflight。
- 每个市场完成 10 个非 fixture 真实样本读回，并核对证券、报告期、公告日、价格日期和来源。样本取 SHA-256(reference_snapshot_hash + listing_id) 字典序最小的 10 个合格 listing，因而同一 reference snapshot 可重复。

preflight 报告按市场保存 reference_snapshot_id/hash、字段集合版本、provider_config_hash、credential_id_hash、测量时间、expires_at、各分子/分母、真实样本与报告 SHA-256。有效期为 24 小时；reference、provider 配置、credential_id 或许可声明任一变化时立即失效。

POST /api/data-sources/preflight 运行上述检查并保存报告。data_snapshot 创建时必须绑定未过期 preflight_id 和报告哈希，导出同时记录当时每市场能力状态。该操作需要用户真实凭据和网络授权，不纳入默认离线测试，也不能用 fake provider 提升真实运行时状态。未达到门槛时系统必须报告实际覆盖率和缺口。

纯分类函数允许用 synthetic=true 的黄金报告测试 LIVE_READY 正向分支；返回值标记 TEST_ONLY，持久化层拒绝把 synthetic 报告写成真实 LIVE_READY 或用于真实 data_snapshot。

### 7.4 截止日与防止未来数据

每次扫描必须指定 as_of_date，默认是本地日期。系统为每个市场另存 market_effective_date，即该市场不晚于 as_of_date 的最近完整交易日；不能假定 A 股与港股交易日完全一致。

- 只有 announcement_date 小于等于 as_of_date 的报表或公告可用。
- 若只有报告期但没有公告日期，该记录不能参与正式评分。
- 修订报表按公告日期排序，使用截止日前最新有效版本，并保留被替换版本。
- 行情和估值使用各市场 market_effective_date 的数据。
- 五年财务窗口指截止日前已公告的最近五个完整年度报告，不使用未完成年度推算值。

### 7.5 同源时间序列

同一个评分指标的五年时间序列默认必须来自同一 provider 和同一会计口径。跨源拼接只允许在创建扫描前通过已提交导入形成明确的规范化序列，并记录：

- 每个年份的来源。
- 拼接原因。
- 单位、币种和复权方式。
- 审核人、时间和备注。

data_snapshot 一旦 READY，其 universe、输入 observation、行业分类和 A/H 映射全部冻结。CONFLICTED listing 在引用该 snapshot 的 scan 内不支持就地修正；用户必须修正 provider、导入或映射后创建新 snapshot 与子 scan。这一限制避免已经评分或进入 Top 50 的结果被静默改写。

### 7.6 规范化

canonical 层统一：

- 日期使用 ISO 8601；数据库时间戳使用 UTC。
- 币种保留原币种，同时保存汇率来源与换算日期。
- 财务数值保存原单位与规范化单位。
- 负号、现金流方向、复权、拆股和每股数据口径。
- 归母净利润、经营现金流、资本开支、总负债、总资产、净债务、EBIT、EBITDA、利息费用、股息和回购定义。
- 行业分类体系与版本。

不需要跨币种比较的比率应直接在同币种输入上计算，避免无意义换算。

### 7.7 数据状态

每个 listing 在每个 READY data snapshot 下有且仅有一个数据状态；scan 引用并冻结该状态：

- READY：所有硬过滤与六个客观维度的必需数据完整、有效、无未解决冲突。
- PARTIAL：可展示部分数据，但至少一个必需字段、监管风险检查或统计样本不足。
- UNAVAILABLE：核心来源不可用，无法形成有意义分析。
- CONFLICTED：关键字段存在超过容差的来源冲突，创建该 snapshot 前未解决。

PARTIAL、UNAVAILABLE、CONFLICTED 均不得进入自动 Top 50 或正式排名。

### 7.8 缓存

- 日终数据按 provider、endpoint、参数、交易日和解析器版本生成缓存键。
- 同一交易日内默认复用成功缓存。
- 用户可强制刷新，但旧成功快照在新请求失败时只可标为 STALE 展示，不得作为本次正式评分。
- 原始响应、导入文件和公开公告以内容哈希保存为不可变工件。
- 数据库是可变业务状态的唯一权威；导出文件按需生成，不作为输入源。
- provider 后续更新不会改变 READY data snapshot；强制刷新创建新 snapshot。

### 7.9 冻结数据快照

DATA_SYNC 不是 scan 内部一边抓取一边评分，而是先生成独立、持久化的 data_snapshot：

1. POST /api/data-snapshots 接收有效 preflight_id、as_of_date、markets 和 source_preferences。
2. 后台任务同步证券池与全部候选数据到 snapshot staging。
3. 每个已完成批次保存不可变 artifact 与 observation；未完成批次可以恢复，但不能被 scan 读取。
4. 全部批次结束后运行冲突、覆盖和时间截止检查。
5. 在单事务中写 universe、输入选择、质量状态、内容清单与 SHA-256，并把 snapshot 标记 READY。

data_snapshot 状态为 QUEUED、SYNCING、READY、FAILED、CANCELLED 或 INTERRUPTED。只有 READY snapshot 可创建 scan；FAILED、CANCELLED、INTERRUPTED 或仍在 staging 的内容从不参与评分。

snapshot 至少冻结：

- universe_reference_snapshot_id、entity_id、listing_id、证券类型和成员清单哈希。
- 每个选中 observation_id、artifact_id、parser_version、公告日和选择理由。
- 行业分类、A/H 映射、股份类别转换和 benchmark mapping 版本。
- preflight_id、每市场能力状态、provider_config_hash、报告哈希与有效期。
- market_effective_date、创建/完成时间和完整 manifest hash。

同一交易日、同一参数和同一有效 preflight 可复用 READY snapshot。provider 新数据或配置变化不会改变它；需要修复冲突、刷新数据或改变来源时创建新的 snapshot。

## 8. 扫描生命周期

用户看到的五个阶段保持为：

    DRAFT
      -> DATA_SYNC
      -> OBJECTIVE_SCREENING
      -> REVIEW_PENDING
      -> FINALIZED

DRAFT 仅是前端尚未提交的配置，不写数据库。DATA_SYNC 对应独立 data_snapshot 后台任务；snapshot READY 后，POST /api/scans 才在事务中占用活动 scan 槽并创建 QUEUED scan。

scan 持久化字段：

- status：QUEUED、RUNNING、REVIEW_PENDING、FINALIZED、FAILED、CANCELLED、INTERRUPTED。
- phase：OBJECTIVE_SCREENING 或空。
- snapshot_id：不可变 READY data_snapshot。
- parent_scan_id 与 clone_reason：新扫描的审计关系；不表示继承旧输入。
- cancel_requested_at：用户请求取消的时间。
- rule_snapshot_id 与 engine_build_hash。

通用 background_job 和 job_attempt 另存 job_type、target_type、target_id、status、retryable、attempt_no、checkpoint、heartbeat、lease_expires_at、lease_epoch/fencing_token 和错误。

状态转换：

    QUEUED
      -> RUNNING / OBJECTIVE_SCREENING
      -> REVIEW_PENDING
      -> FINALIZED

    QUEUED 或 RUNNING
      -> FAILED | CANCELLED | INTERRUPTED

    FAILED(retryable) 或 INTERRUPTED
      -> 新 attempt 的 QUEUED

规则：

- 任意时刻最多一个 scan 处于 QUEUED 或 RUNNING；非终止 CLONE_SCAN 先占用同一 scan_activity_slot，防止准备 snapshot 期间另一个 scan 抢占。SQLite 约束是权威。
- POST /api/scans 使用持久化 idempotency_records。相同 operation、scope、key 和 request_hash 返回原资源；相同 key 但不同 request_hash 返回 409 IDEMPOTENCY_KEY_REUSED。
- 若不同 key 请求撞上活动槽，返回 409 SCAN_ALREADY_RUNNING。
- POST /api/scans 必须接收 READY snapshot_id，并验证 snapshot 的 preflight、provider config、市场、截止日和 manifest hash。
- scan 只读取 snapshot 冻结的 universe 与 observation，不发起 provider 网络请求。
- 每个评分批次保存稳定成员清单哈希；score components、feature 使用记录与 checkpoint 在同一事务写入。
- 取消只在安全边界生效，不中断正在写入的单个事务；重复取消返回当前资源。
- cancel 只接受 QUEUED 或 RUNNING。若取消事务先提交，worker 不得再进入 REVIEW_PENDING；若阶段完成事务先提交，cancel 返回 409 SCAN_NOT_RUNNING。
- resume 创建新 job_attempt 并从最近成功评分检查点继续；每个阶段必须幂等。重复 resume 使用幂等键。
- 进程启动时把租约已过期的遗留 RUNNING 扫描转为 INTERRUPTED。
- 进入 REVIEW_PENDING 时冻结 objective_candidates 和核心 Top 50；之后 provider 更新不改变候选集合。
- FINALIZED 后扫描不可修改。
- 修复冲突、刷新数据或 engine/rule 不兼容时，POST /api/scans/{scan_id}/clone 创建 CLONE_SCAN 后台任务。该任务只继承市场、截止日和来源偏好，生成新的 data_snapshot 与子 scan，并保存 parent_scan_id、clone_reason；绝不复制旧冻结输入或旧分数。

故障边界：

- 请求市场没有已配置的证券主数据或主要 provider 时，data_snapshot 创建前返回 422 DATA_SOURCE_NOT_CONFIGURED。
- 市场级 provider 或监管风险服务在 DATA_SYNC 中整体不可用时，snapshot job 进入 retryable FAILED，不生成 READY snapshot。
- 个别证券字段缺失、样本不足、风险查询失败或冲突时，该 listing 在 READY snapshot 中进入 PARTIAL、UNAVAILABLE 或 CONFLICTED。
- 客观 scan 的失败只来自本地快照、规则、引擎、数据库或进程错误，不在恢复时重新抓取上游数据。

## 9. 硬过滤与模型适用性

过滤顺序固定，首个决定性原因作为 primary_reason，其余原因全部保留。

### 9.1 行业排除

以下是 LSA-DS2 2.0.0 的强制排除代码，不是用户可在单次扫描中关闭的偏好：

| Canonical code | 排除范围 |
|---|---|
| BAIJIU | 白酒生产及以白酒为绝对主营的企业 |
| COAL | 煤炭开采、洗选及纯煤炭贸易 |
| STEEL | 普钢、特钢和以钢铁冶炼为主营的企业 |
| MARINE_SHIPPING | 集装箱、干散货、油运等海运承运 |
| REAL_ESTATE_DEVELOPMENT | 房地产开发与运营 |
| REAL_ESTATE_HIGH_DEPENDENCY | 收入或资产对房地产开发链高度依赖的企业 |
| SOLAR_LEGACY_LOW_EFFICIENCY | 经技术参数确认的低端、高成本旧光伏制造环节 |
| COMMODITY_CHEMICAL_PURE_CYCLICAL | 产品高度同质、主要由商品价差驱动的纯周期化工 |
| BREEDING | 畜牧、家禽、水产等养殖业务 |
| STRUCTURAL_DECLINE | 由版本化规则确认的结构性衰退行业 |
| STRONG_CYCLICAL | 由版本化规则确认且未被其他代码覆盖的强周期行业 |

系统使用内部 DS2 Canonical Industry Taxonomy v1。每个 provider 的行业体系必须通过版本化映射表映射到上述代码；映射表保存来源代码、有效期和审核记录。REAL_ESTATE_HIGH_DEPENDENCY、SOLAR_LEGACY_LOW_EFFICIENCY、COMMODITY_CHEMICAL_PURE_CYCLICAL、STRUCTURAL_DECLINE 和 STRONG_CYCLICAL 只能由明确映射或扫描前已审核的实体分类触发，不能运行时用名称模糊匹配。

分类不确定时标记 PARTIAL 和 INDUSTRY_CLASSIFICATION_UNKNOWN，不自动排除或放行。改变上述强制代码或范围必须发布新的校准档版本。

### 9.2 模型不适用

银行、保险和券商标记 MODEL_NOT_APPLICABLE，不视为负面评价，不参与 DS2 排名。它们需要独立模型，首版不实现。

### 9.3 五年经营底线

最近五个完整年度中满足任一条件即排除：

- 归母净利润小于等于 0。
- 经营活动现金流小于等于 0。
- 五年窗口不完整。

### 9.4 重大造假

若截至 as_of_date，监管机构、交易所、法院或发行人正式公告已确认重大财务造假，标记 EXCLUDED_MATERIAL_FRAUD。

传闻、媒体推测或尚未结案的调查不直接触发该排除，但作为风险证据展示。若正式风险检查来源不可用，则标记 PARTIAL 和 RISK_CHECK_UNKNOWN，不进入 Top 50。

“未发现已确认造假”必须来自一次成功完成且覆盖 as_of_date 的配置化监管记录查询；无命中是有效结果，查询未执行或执行失败不是有效结果。

### 9.5 持续重大商誉减值

以下任一条件触发 EXCLUDED_PERSISTENT_GOODWILL_IMPAIRMENT：

- 最近三个完整年度中至少两个年度的商誉减值损失达到各自期初归母净资产的 10%。
- 最近三个完整年度累计商誉减值损失达到第一个年度期初归母净资产的 20%。

商誉减值、期初归母净资产或公告日期缺失时标记 PARTIAL 和 GOODWILL_RISK_UNKNOWN。以上量化门槛属于 LSA-DS2 2.0.0 新增校准，不冒充参考对话给出的原始数值。

### 9.6 关键冲突

下列字段的来源冲突未解决时标记 CONFLICTED：

- 归母净利润。
- 经营活动现金流。
- 资本开支。
- 总资产、总负债、现金及有息债务。
- 股息、已完成回购金额。
- 价格、总回报复权因子、股本或市值。
- 行业分类和 A/H 实体映射。

默认容差为绝对值与相对值组合：金额字段差异超过 max(1 个规范化货币单位，1%)，比率字段差异超过 0.5 个百分点即冲突。字段可在配置中定义更严格容差。

## 10. 通用计算规则

### 10.1 数值精度

- 中间计算使用 IEEE 754 双精度，数据库保存原始输入与未舍入结果。
- API 展示分数保留一位小数。
- 排名使用未舍入分数。
- DS2 展示必须附“合理误差约 ±2 分”，该说明不是统计置信区间。

### 10.2 分段线性锚点

所有客观子分使用配置中的有序锚点做分段线性插值：

1. x 小于最小锚点时取最小锚点对应分数。
2. x 大于最大锚点时取最大锚点对应分数。
3. 锚点之间按直线插值。
4. 最终限制在 0–100。
5. 缺失、非有限值或分母无效时返回 MISSING，不返回数值。

### 10.3 五年统计

- 五年窗口按财年顺序排列。
- 变异系数 CV = population_std(values) / abs(mean(values))。
- 盈利与经营现金流已通过正值硬过滤，因此其均值必须大于 0。
- 五年最大回撤 = max((历史峰值 - 后续低点) / abs(历史峰值))；持续增长时为 0。
- ROE 优先使用规范化加权平均 ROE；无法获得一致口径时不以简单替代值补齐。

### 10.4 行业分位数

- 同市场、同 as_of_date、同二级行业为默认可比组。
- 可比组只包含对应指标有效且会计口径兼容的普通股。
- 最少 10 个样本；不足时回退到一级行业。
- 一级行业仍少于 10 个样本时，该子项为 MISSING。
- 百分位使用确定性秩方法；并列值取平均秩，结果范围 0–1。

## 11. 六个客观维度

### 11.1 盈利稳定性 EarningsStability

    EarningsStability =
      0.35 × NetProfitCVScore
    + 0.25 × EarningsDrawdownScore
    + 0.25 × AverageROEScore
    + 0.15 × MinimumROEScore

| 子项 | 输入 | 锚点 x → 分数 |
|---|---|---|
| NetProfitCVScore | 五年归母净利润 CV | 0.15→100，0.30→75，0.50→40，0.75→0 |
| EarningsDrawdownScore | 五年归母净利润最大回撤 | 0.10→100，0.25→75，0.40→40，0.70→0 |
| AverageROEScore | 五年 ROE 算术平均，百分数 | 0→0，8→40，10→60，15→85，20→100 |
| MinimumROEScore | 五年最低 ROE，百分数 | 0→0，5→30，8→65，12→90，15→100 |

### 11.2 现金流 CashFlow

定义：

- FCF = 经营活动现金流 - 资本开支。
- 资本开支按购建长期资产的现金流出绝对值计量。
- AnnualOCFToNP = 每一年度经营活动现金流 / 同年度归母净利润。
- AverageOCFToNP = 五个 AnnualOCFToNP 的算术平均。
- AggregateFCFToOCF = 五年 FCF 合计 / 五年经营活动现金流合计。

公式：

    CashFlow =
      0.35 × AverageOCFToNPScore
    + 0.25 × PositiveFCFYearsScore
    + 0.20 × OCFCVScore
    + 0.20 × AggregateFCFToOCFScore

| 子项 | 输入 | 锚点 x → 分数 |
|---|---|---|
| AverageOCFToNPScore | 五年年度 OCF / NP 的算术平均 | 0→0，0.50→35，0.80→70，1.00→100，1.50→100 |
| PositiveFCFYearsScore | FCF 大于 0 的年度数 | 0→0，3→50，4→80，5→100 |
| OCFCVScore | 五年 OCF CV | 0.15→100，0.30→75，0.50→40，0.75→0 |
| AggregateFCFToOCFScore | 五年合计 FCF / OCF | 0→0，0.20→40，0.40→70，0.60→100 |

### 11.3 资产负债表 BalanceSheet

使用截止日前最近一个完整年度：

- NetDebt = 短期有息债务 + 长期有息债务 - 现金及现金等价物。
- NetDebtToEBITDA = NetDebt / EBITDA；净现金时按小于等于 0 处理。
- InterestCoverage = EBIT / 利息费用。
- LiabilitiesToAssets = 总负债 / 总资产。

特殊情况：

- EBITDA 小于等于 0 时 NetDebtToEBITDA 子项为 MISSING。
- 利息费用为 0 且 EBIT 大于 0 时 InterestCoverageScore = 100。
- 总资产小于等于 0 时该维度为 MISSING。

公式：

    BalanceSheet =
      0.40 × NetDebtToEBITDAScore
    + 0.40 × InterestCoverageScore
    + 0.20 × IndustryLeverageScore

| 子项 | 输入 | 锚点 x → 分数 |
|---|---|---|
| NetDebtToEBITDAScore | 净债务 / EBITDA | 0→100，2→85，4→30，6→0 |
| InterestCoverageScore | EBIT / 利息费用 | 1→0，3→60，5→85，10→100 |
| IndustryLeverageScore | 负债率行业百分位，越低越好 | 0→100，0.50→60，0.80→25，1→0 |

### 11.4 估值 Valuation

定义：

- CurrentPE = as_of_date 前最近交易日的正值 PE_TTM。
- OwnPEPercentile = CurrentPE 在该上市证券过去五年有效日频 PE_TTM 中的百分位。
- IndustryPEPercentile = CurrentPE 在行业可比组中的百分位。
- ImpliedEntityMarketCapAtListingPrice = 当前 listing 的复权前每股价格 × 按股份类别转换比例折算的实体完全摊薄等价总股数。
- FCFYield = 截止日前最近一个完整财年的实体 FCF / ImpliedEntityMarketCapAtListingPrice。
- IndustryFCFYieldPercentile = FCFYield 在行业可比组中的百分位，越高越好。

历史 PE 至少覆盖 36 个月，且有效交易日覆盖率至少 80%；否则 OwnPEPercentile 为 MISSING。当前 PE 非正或无法计算时，该维度为 MISSING。A/H 双重上市若缺少可靠的股份类别转换比例或完全摊薄等价股数，FCFYield 为 MISSING，不能用单一类别市值直接除实体 FCF。

    Valuation =
      0.50 × OwnPEPercentileScore
    + 0.25 × IndustryPEPercentileScore
    + 0.25 × IndustryFCFYieldPercentileScore

| 子项 | 输入 | 锚点 x → 分数 |
|---|---|---|
| OwnPEPercentileScore | 自身历史 PE 百分位，越低越好 | 0→100，0.20→90，0.50→70，0.70→40，0.90→10，1→0 |
| IndustryPEPercentileScore | 行业 PE 百分位，越低越好 | 0→100，0.20→90，0.50→70，0.70→40，0.90→10，1→0 |
| IndustryFCFYieldPercentileScore | 行业 FCF 收益率百分位 | 0→0，0.30→40，0.50→65，0.80→90，1→100 |

### 11.5 股东回报 ShareholderReturn

定义：

- DividendYears：五个财年中每股现金股息大于 0 的年度数。
- NonCutYears：窗口首年每股股息为正时计 1；此后仅在本年与紧邻上一财年股息都为正，且本年拆股复权每股股息不低于上一财年 90% 时计 1。停派后的恢复年度不计为未削减。
- AggregatePayout = 五年实体现金股息与已完成普通股回购合计 / 五年归母净利润合计。
- TotalShareholderYield = 截止日前十二个月实体现金股息与已完成普通股回购合计 / ImpliedEntityMarketCapAtListingPrice。
- 只计已完成回购金额，不计公告上限；若公告明确限定股份类别则按该类别事实记录，否则按实体总现金回报处理。

    ShareholderReturn =
      0.20 × DividendYearsScore
    + 0.15 × NonCutYearsScore
    + 0.25 × AggregatePayoutScore
    + 0.40 × TotalShareholderYieldScore

| 子项 | 输入 | 锚点 x → 分数 |
|---|---|---|
| DividendYearsScore | 五年派息年度数 | 0→0，3→50，5→100 |
| NonCutYearsScore | 五年未明显削减覆盖数 | 0→0，3→60，5→100 |
| AggregatePayoutScore | 五年股息加回购合计支付率 | 0→0，0.30→80，0.50→100，0.70→90，1.00→50，1.20→0 |
| TotalShareholderYieldScore | 股息加已完成回购收益率，百分数 | 0→0，2.5→60，3→75，5→95，7→100 |

### 11.6 低波动 LowVolatility

市场基准：

- A 股上市证券：canonical benchmark CN_CSI300_TOTAL_RETURN。
- 港股上市证券：canonical benchmark HK_HSI_TOTAL_RETURN。
- provider 配置必须把 canonical benchmark 映射到获得授权的具体代码，并保存映射版本。
- 首版不允许用价格指数或其他“等价”指数静默替代全收益基准；全收益序列不可用时 LowVolatility 为 MISSING。

统计窗口：

- 周采样：以所属市场每个 ISO 周的最后一个官方交易日为采样日，证券与基准都必须在该日有有效复权收盘价；不前向填充。只有相邻 ISO 周都存在配对价格时才计算一组简单收益率 R(t)=P(t)/P(t-1)-1，缺周会中断该对。
- Beta 使用最近三年不少于 130 组周配对收益，公式为 sum((Ri-mean(Ri))×(Rm-mean(Rm))) / sum((Rm-mean(Rm))²)。基准收益方差为 0 时 MISSING；不做无风险利率调整、对数变换或 winsorize。
- MaxDrawdownRatio：证券最近三年有效日频复权收盘价最大回撤 / 同一日期边界内基准最大回撤；基准回撤为 0 时 MISSING。
- 月采样：以所属市场每个自然月最后一个官方交易日为采样日，证券与基准都必须在该日有有效复权收盘价；仅相邻自然月计算简单收益率，不前向填充。
- DownsideCaptureRatio 使用最近 36 个月，至少 30 组月配对收益且至少 8 个基准下跌月；公式为基准下跌月份证券收益率之和 / 基准收益率之和，小于等于 0 视为最佳端。

    LowVolatility =
      0.40 × BetaScore
    + 0.35 × MaxDrawdownRatioScore
    + 0.25 × DownsideCaptureScore

| 子项 | 输入 | 锚点 x → 分数 |
|---|---|---|
| BetaScore | 三年周 Beta | 0.50→100，0.80→85，0.90→70，1.00→50，1.20→20，1.40→0 |
| MaxDrawdownRatioScore | 证券回撤 / 基准回撤 | 0.50→100，0.70→80，1.00→50，1.30→20，1.60→0 |
| DownsideCaptureScore | 下行捕获率 | 0.50→100，0.70→85，1.00→50，1.20→20，1.40→0 |

## 12. 客观总分与 Top 50

六个客观维度权重总和为 73：

    ObjectiveScore =
      (
        18 × EarningsStability
      + 15 × CashFlow
      + 12 × BalanceSheet
      + 12 × Valuation
      +  8 × ShareholderReturn
      +  8 × LowVolatility
      ) / 73

进入自动 Top 50 必须同时满足：

- 硬过滤结果为 ELIGIBLE。
- 数据状态为 READY。
- 六个客观维度均有完整数值。
- 无模拟数据、过期替代数据或未解决冲突。

系统先计算每个 READY listing 的客观分，再按 6.3 的预筛规则为每个 entity 选出一个代表 listing，最后对代表 listing 排序。排序使用未舍入 ObjectiveScore，依次以 EarningsStability、CashFlow、listing_id 作为稳定的平局规则。少于 50 个合格实体时展示全部，并明确合格数量。

进入 REVIEW_PENDING 时，核心 Top 50 的 entity_id、代表 listing_id、未舍入分数、排名和输入快照写入 objective_candidates 并冻结。另行保存的“全部上市地客观排名”只供查看，不改变核心候选。

ObjectiveScore 只用于缩小人工复核范围，不是最终 DS2，也不是买入顺序。系统必须在页面、API 和导出中明确写出：最终 DS2 仅覆盖该客观 Top 50，不能据此声称获得全市场 DS2 前 50。

## 13. 行业前景与护城河复核

### 13.1 证据进入与冻结

evidence service 提供两种入口：

1. 按 entity_id 从配置化、allowlist 内的监管、交易所、发行人和行业来源采集。
2. 由用户提交 allowlist 内 URL，或上传 PDF、HTML、TXT 证据文件，经 validate 后 commit。

每个 evidence_item 至少保存：

- evidence_id、entity_id、主题和支持/反证方向。
- publisher_identity、source_type、标题、发布日期和抓取时间。
- artifact_id、内容哈希、URL 或导入标识。
- 可定位 locator，如页码、章节、表格或段落标识。
- 解析器版本、语言、as_of_date 校验、质量状态和 verification_status。

同一发布机构的镜像、转载和聚合页只算一个独立来源。commit 后 evidence_item 内容不可变；更正产生新版本。每次 AI 草稿和人工确认都关联一组冻结 evidence_id，后续抓取不能改写旧 EvidenceBundle。

verification_status：

- VERIFIED_PROVIDER：由已配置 provider 直接取得，publisher_identity 来自 provider 契约。
- VERIFIED_ALLOWLIST_URL：服务端从 allowlist HTTPS URL 抓取，publisher_identity 由受控域名映射确定。
- USER_DECLARED：用户上传文件或只填写元数据，来源身份未由系统验证。
- UNVERIFIABLE：内容、发布日期、定位或来源无法核验。

只有 VERIFIED_PROVIDER 和 VERIFIED_ALLOWLIST_URL 可计入“两源”和“一手来源”门槛。USER_DECLARED 与 UNVERIFIABLE 可供用户查看和写入风险备注，但不能单独解锁确认。上传文件只有在内容哈希与服务端从已验证官方 URL 取得的工件一致，或通过受支持的发布者数字签名校验后，才可升级为 VERIFIED_ALLOWLIST_URL；publisher_identity 不能由用户自由文本决定。

### 13.2 AI 的职责

AI 只生成结构化草稿：

- 子项建议分。
- 关键事实与推理。
- 支持证据和反证。
- 来源类型、标题、发布机构、发布日期、URL 或文档标识。
- 数据截止日。
- 不确定性和仍需人工判断的问题。

AI 适配器不执行搜索或网页抓取，只能引用服务端分配给本次请求的 EvidenceBundle 中的 evidence_id。服务端必须验证引用确实存在、发布日期不晚于 as_of_date，且返回内容与保存的来源元数据一致；模型自由生成的 URL、标题或文档标识一律不成为有效引用。

AI 草稿是异步资源，保存 draft_version、base_review_version、模型、模板版本和状态。迟到响应若 base_review_version 已变化或复核已确认，标为 SUPERSEDED，不得覆盖新草稿或人工决定。

AI 不得：

- 改写客观指标。
- 自动确认主观分。
- 在证据不足时补默认分。
- 把网页、公告或导入文件中的指令当成系统指令执行。

### 13.3 证据门槛

每个主观维度确认前必须满足：

- 至少 2 个相互独立的来源。
- 至少 1 个一手来源，如监管机构、交易所、公司正式报告或行业主管部门。
- 两个来源必须具有不同的已验证 publisher_identity；镜像、转载或同一机构多个页面不重复计数。
- 每项证据包含发布日期和可定位引用。
- 至少记录 1 项反证；确无反证时，用户必须显式说明检索范围和结论。
- 行业证据默认不早于 as_of_date 前 18 个月。
- 公司证据使用截至 as_of_date 最新的年报、中报或正式公告。
- 来源冲突必须展示并由用户处理。

门槛不满足时状态为 EVIDENCE_INSUFFICIENT，确认 API 返回 422。

### 13.4 行业前景 IndustryProspect

    IndustryProspect =
      0.30 × DemandDurability
    + 0.25 × ProfitPoolQuality
    + 0.20 × PolicyRegulatoryResilience
    + 0.15 × SubstitutionResistance
    + 0.10 × CompetitionStructure

子项含义：

- DemandDurability：需求的长期稳定性、渗透空间和可预测性。
- ProfitPoolQuality：行业利润池规模、现金转化和周期波动。
- PolicyRegulatoryResilience：政策、监管、地缘和许可风险承受力。
- SubstitutionResistance：技术替代、消费迁移和替代品威胁。
- CompetitionStructure：集中度、价格纪律、进入壁垒和供给扩张风险。

### 13.5 护城河 Moat

    Moat =
      0.30 × MarketPosition
    + 0.30 × DurableAdvantage
    + 0.25 × ReturnPersistence
    + 0.15 × PricingPowerRetention

子项含义：

- MarketPosition：份额、渠道、客户覆盖和关键资源位置。
- DurableAdvantage：品牌、网络效应、转换成本、成本或牌照优势。
- ReturnPersistence：毛利率、营业利润率和 ROIC 的跨周期持续性。
- PricingPowerRetention：提价能力、续约、留存和需求韧性。

### 13.6 打分量表与确认

每个子项由 AI 建议 0–100 的整数，证据量表为：

- 0：证据明确负面或优势不存在。
- 25：弱，易受竞争或周期破坏。
- 50：中性，优势与风险大致平衡。
- 75：强，有多项可验证的持续性证据。
- 100：极强，跨周期、一手证据充分且反证有限。

用户可在 0–100 间调整任意整数；偏离 AI 建议超过 10 分时必须填写理由。所有确认、修改、理由和证据版本写入审计日志。

复核状态：

- PROVISIONAL：AI 草稿存在但未确认。
- CONFIRMED：证据门槛满足且用户确认。
- MANUAL_CONFIRMED：AI 不可用，用户按相同证据门槛手工录入并确认。
- SKIPPED：用户明确不纳入最终排名。
- EXCLUDED_BY_REVIEW：发现新的排除事实并记录理由。

只有 IndustryProspect 和 Moat 均为 CONFIRMED 或 MANUAL_CONFIRMED 时，才计算正式 DS2。

## 14. 最终分数、排名与角色标签

- 正式排名只包含通过客观筛选且完成两项主观确认的候选。
- 排名使用未舍入 DS2；平局依次比较 ObjectiveScore、EarningsStability、CashFlow 和 listing_id。
- FINALIZED 前，Top 50 中每个候选必须被标记为 CONFIRMED、MANUAL_CONFIRMED、SKIPPED 或 EXCLUDED_BY_REVIEW。
- 至少有一个候选完成确认才能 FINALIZED。
- 最终结果展示总分、八维分数、资格状态、排名、主要优点、主要风险、数据截止日、来源和规则哈希。
- S/A/G 仅为用户可选的人工角色标签，不预设分数边界，不影响 DS2 和排名。
- DS2 是研究优先级，不是机械买入命令。

## 15. 单页用户体验

采用单页漏斗工作台，分为四个连续阶段：

1. 数据准备。
2. 客观扫描。
3. Top 50 复核。
4. 最终排名。

桌面布局：

    顶部：扫描状态、截止日、来源健康度、开始/取消/恢复
    左侧：四阶段进度与筛选统计
    中部：候选表格、排序、状态、八维雷达入口
    右侧：当前证券证据、AI 建议、反证、人工确认
    底部：错误、审计摘要、CSV/XLSX 导出

关键行为：

- 数据准备页先显示来源权限、缓存日期、导入校验和缺失覆盖。
- Gate 0 状态固定显示 NOT_CONFIGURED、LIVE_PARTIAL 或 LIVE_READY；只有 LIVE_READY 可使用“A 股与港股全市场已就绪”文案。
- 客观扫描显示总数、已处理、排除、PARTIAL、CONFLICTED 和预计剩余批次。
- 候选表默认按 ObjectiveScore 排序，明确标注“全市场客观预筛、非最终分”。
- 复核面板同时展示支持证据与反证；链接可定位到来源。
- 用户可在数据准备/复核区提交 allowlist URL 或证据文件，先校验再冻结；AI 只看到冻结 evidence_id。
- CONFLICTED 项展示候选值和来源，但明确提示“本扫描不可就地修正；修复来源后创建新扫描”。
- 任何人工覆盖都要求原因，保存时使用版本号避免覆盖并发修改。
- AI 失败时保留手工复核入口，不显示虚假成功。
- 最终页可切换“实体核心清单”和“全部上市地”。
- 最终页标题固定为“客观 Top 50 内部 DS2 排名”，不显示“全市场 DS2 排名”。

响应式与可访问性：

- 小屏时左侧折叠为步骤条，右侧变为抽屉，表格变为候选卡片。
- 页面主体不得产生不可控横向溢出；宽表只在自身容器滚动。
- 核心操作可键盘完成，有可见焦点、语义标签和错误摘要。
- 颜色不是唯一状态信号。

## 16. API 设计

所有响应包含 X-Request-ID header；JSON 响应可同时包含 request_id 字段。错误使用稳定的 code、message、details 结构。二进制导出只通过 header 携带 request ID。

### 16.1 健康与来源

- GET /api/health/live
  - 只返回进程存活与版本，不返回数据库路径、provider 细节或配置；是非 loopback 时唯一可匿名访问的接口。
- GET /api/health
  - 返回数据库、worker、配置哈希和活动扫描状态。
- GET /api/data-sources
  - 返回经过脱敏的 provider 名称、能力状态、最近成功日期、缓存状态和覆盖率；永不返回 token、密钥路径或原始敏感错误。
- POST /api/data-sources/preflight
  - 异步运行 Gate 0，返回 202、Location、preflight_id 和 job_id。
- GET /api/data-sources/preflights/{preflight_id}
  - 返回权限、许可声明、覆盖率、真实样本读回和 NOT_CONFIGURED/LIVE_PARTIAL/LIVE_READY。

### 16.2 数据快照

- POST /api/data-snapshots
  - 输入：有效 preflight_id、as_of_date、markets、source_preferences 和 idempotency_key。
  - 验证报告未过期、每个请求市场不是 NOT_CONFIGURED，且 provider_config_hash 一致；返回 202、Location、snapshot_id 和 job_id。
- GET /api/data-snapshots/{snapshot_id}
  - 返回状态、市场日期、计数、质量分布、preflight 报告哈希、provider config 哈希、manifest hash 和错误。

### 16.3 导入

- POST /api/imports/validate
  - 上传 CSV/XLSX，校验文件类型、大小、工作表、列映射、单位、日期、重复项和公式单元格。
  - 只生成临时校验结果，不写 canonical 数据。
- POST /api/imports/commit
  - 提交已通过校验的 validation_id。
  - 保存内容哈希、原始工件、字段映射和导入审计。

### 16.4 证据

- POST /api/evidence/validate
  - 输入一个 allowlist 内 URL，或上传 PDF、HTML、TXT；校验来源、类型、大小、发布日期、定位信息和内容安全。
- POST /api/evidence/commit
  - 提交 validation_id，创建不可变 evidence_item。
- POST /api/scans/{scan_id}/entities/{entity_id}/evidence/collect
  - 从配置化来源异步采集，返回 202、Location、collection_id 和 job_id。
- GET /api/evidence/collections/{collection_id}
  - 返回 PENDING、RUNNING、READY、FAILED、CANCELLED、INTERRUPTED 与新增 evidence_id。
- GET /api/scans/{scan_id}/entities/{entity_id}/evidence
  - 返回可选择的支持证据、反证、独立来源身份和冻结状态。

### 16.5 扫描

- POST /api/scans
  - 输入：READY snapshot_id、idempotency_key。parent_scan_id 和 clone_reason 只允许由受控 CLONE_SCAN job 写入。
  - 成功占用活动槽后返回 202、Location、QUEUED scan 和 job_id。
  - 同一幂等键先按 request_hash 处理；之后才判断其他活动扫描。已有其他活动扫描时返回 409 SCAN_ALREADY_RUNNING。
- GET /api/scans/{scan_id}
  - 返回状态、阶段、计数、检查点、错误与规则哈希。
- POST /api/scans/{scan_id}/cancel
  - 请求现有 OBJECTIVE_SCAN job 在下一个安全边界取消；运行中返回 202 与 job_id，已取消或已终止返回当前资源。
- POST /api/scans/{scan_id}/resume
  - 仅允许 FAILED 或 INTERRUPTED 且错误可恢复的扫描；返回新 attempt 的 202、Location 与 job_id。
- POST /api/scans/{scan_id}/clone
  - 输入新的 preflight_id、as_of_date、source_preferences、clone_reason 和 idempotency_key。
  - 先创建 clone_operation，再返回 CLONE_SCAN job、clone_operation_id 与 job_id；该 job 生成全新 snapshot，再创建带 parent_scan_id 的子 scan。
- GET /api/clone-operations/{clone_operation_id}
  - 返回父 scan、状态、新 snapshot_id、子 scan_id 和脱敏错误；父 scan 永不被 clone job 修改。
- GET /api/scans/{scan_id}/candidates
  - 仅在 REVIEW_PENDING 或 FINALIZED 可读，支持稳定游标、状态、市场和行业过滤；返回冻结客观分与排名。

### 16.6 个股、实体与复核

- GET /api/scans/{scan_id}/stocks/{listing_id}
  - 返回资格决定、输入、六维客观明细、来源和复核状态。
- GET /api/scans/{scan_id}/entities/{entity_id}
  - 返回实体证据、全部 listing 客观分、当前代表 listing、复核决定和 review_version。
- POST /api/scans/{scan_id}/entities/{entity_id}/ai-drafts
  - 从已验证 EvidenceBundle 异步生成草稿；返回 202、Location、draft_id 和 job_id，重复请求使用持久化幂等键。
- GET /api/ai-drafts/{draft_id}
  - 返回 PENDING、RUNNING、READY、FAILED、CANCELLED、INTERRUPTED 或 SUPERSEDED 及 draft_version。
- PUT /api/scans/{scan_id}/entities/{entity_id}/review
  - 输入证据选择、两个主观维度子分、决定、理由和 expected_version。
  - 版本不匹配返回 409 REVIEW_VERSION_CONFLICT。
- POST /api/scans/{scan_id}/finalize
  - 验证全部候选已解决、配置哈希一致且至少一项确认。
  - 第一次成功冻结结果；相同幂等请求返回原资源，竞态中已完成时返回已完成资源。

复核写操作只允许 REVIEW_PENDING；AI draft 的迟到完成不能覆盖 review。CONFLICTED listing 在当前 scan 没有解决接口，修复来源后必须通过 CLONE_SCAN 生成新 snapshot 与子 scan。

### 16.7 导出

- GET /api/scans/{scan_id}/exports/csv
- GET /api/scans/{scan_id}/exports/xlsx

导出只允许 FINALIZED；非正式候选通过页面和 JSON API查看，不提供容易混淆的预览文件。

导出包含：

- 实体与上市证券标识。
- 资格、排除和数据状态。
- ObjectiveScore、DS2、八维分和子项分。
- 证据与来源索引。
- 数据截止日、生成时间、规则版本和配置哈希。
- data_snapshot manifest hash、preflight 报告哈希、测量/过期时间和当时每市场能力状态。
- 人工修改理由与角色标签。

CSV/XLSX 导出先按 schema 区分数值与文本。合法数值以数值类型写出；文本保留原值，但用移除开头 BOM、空格、Tab、CR/LF 和 U+0000–U+001F 后的探测副本判断风险。若探测副本首字符为 =、+、-、@，则输出值前加单引号。CSV 再按 RFC 4180 引号规则编码；XLSX 强制使用字符串单元格类型，绝不写 formula 类型。BOM、空白和控制字符的组合绕过必须有测试。

### 16.8 通用后台任务

- GET /api/jobs/{job_id}
  - 返回 job_type、target、状态、attempt、进度、可恢复性和脱敏错误。
- POST /api/jobs/{job_id}/cancel
  - 对尚未终止的任务设置 cancel_requested_at；重复调用幂等。
- POST /api/jobs/{job_id}/resume
  - 仅允许 retryable FAILED 或 INTERRUPTED；创建新 attempt 并返回 202。

所有返回 202 的操作必须先持久化 background_job，Location 指向可轮询资源。应用重启后 RUNNING job 转 INTERRUPTED；任务不会只存在于进程内存。

job 是执行状态权威，目标资源在同一带 fencing token 的事务中镜像状态。映射固定为：

| job_type | 目标资源 | 成功状态 | 取消/中断状态 |
|---|---|---|---|
| PREFLIGHT | preflight_run | READY | CANCELLED / INTERRUPTED |
| DATA_SNAPSHOT | data_snapshot | READY | CANCELLED / INTERRUPTED |
| OBJECTIVE_SCAN | scan | REVIEW_PENDING | CANCELLED / INTERRUPTED |
| EVIDENCE_COLLECTION | evidence_collection | READY | CANCELLED / INTERRUPTED |
| AI_DRAFT | ai_draft | READY | CANCELLED / INTERRUPTED |
| CLONE_SCAN | clone_operation | READY，且记录新 snapshot/scan | CANCELLED / INTERRUPTED |

FAILED 在 job 与目标上同步，并携带 retryable。CLONE_SCAN 认领前 clone_operation 已存在；失败、取消或中断只更新 operation，绝不修改父 scan。resume 把同一目标与新 attempt 原子转回 QUEUED/PENDING。

## 17. SQLite 数据模型

首版核心表：

- security_entities：发行人实体。
- listings：上市证券与市场属性。
- entity_listing_links：A/H 映射与证据。
- industry_classifications：行业代码、体系、版本和有效期。
- data_sources：provider、许可状态、配置与健康度。
- universe_reference_snapshots：官方或授权基准证券池、范围规则和内容哈希。
- preflight_runs：每市场权限、许可声明、覆盖率、配置哈希、测量与过期时间。
- source_artifacts：不可变原始工件、内容哈希和获取元数据。
- annual_financials：按实体、财年和公告版本保存类型化财务字段。
- daily_market_data：按 listing 与交易日保存价格、复权因子、PE 和市值。
- corporate_actions：按实体、股份类别和日期保存股息、拆股与已完成回购。
- regulatory_checks：按实体、查询源、截止日保存查询覆盖与命中。
- metric_conflicts：保存冲突字段、候选 observation 和容差结果；当前扫描只读，不就地解决。
- imports：导入校验、提交状态和列映射。
- data_snapshots：状态、截止日、市场、preflight、provider 配置和 manifest hash。
- snapshot_universe：冻结的 entity/listing 成员、纳入类型和成员哈希。
- snapshot_input_observations：选中的 observation、artifact、parser、分类、映射版本和选择理由。
- feature_snapshots：按 data_snapshot 预聚合的类型化五年、三年和行业分位输入。
- scans：snapshot_id、parent_scan_id、clone_reason、状态、规则/引擎哈希、计数和错误。
- clone_operations：父 scan、请求参数、状态、新 snapshot_id、子 scan_id、原因和错误。
- scan_checkpoints：客观评分阶段、稳定批次成员哈希和提交时间。
- background_jobs：job_type、target、状态、优先级、进度、取消与可恢复性。
- scan_activity_slot：当前 QUEUED/RUNNING scan 或正在准备子 scan 的 CLONE_SCAN 保留项。
- job_attempts：attempt_no、checkpoint、错误、heartbeat、lease_epoch/fencing_token 和租约。
- job_leases：embedded runner、background job 与活动 scan 的数据库租约和单调 epoch。
- idempotency_records：operation、scope、key、request_hash、resource_id、状态和创建时间；至少与目标资源同寿命。
- eligibility_decisions：全部过滤原因和数据状态。
- score_components：subject_type、subject_id、输入、锚点、子分、维度分和未舍入结果。
- objective_candidates：冻结的实体、代表 listing、客观分、核心 Top 50 标记和排名。
- evidence_items：发布者身份、来源类型、artifact、locator、发布日期和内容哈希。
- evidence_collections：entity、来源集合、状态、新增 evidence 和 background_job。
- evidence_bundles：scan、entity、用途、冻结 evidence_id 集合与哈希。
- ai_drafts：模型、提示模板版本、结构化输出、证据和失败状态。
- review_decisions：人工分数、决定、理由、版本和操作者。
- final_rankings：冻结的最终名次与分数快照。
- rule_snapshots：DS2 配置、scorer/engine 语义版本、构建哈希与内容哈希。
- audit_events：状态变更、人工修改、冲突发现、新扫描修复引用和导出。

数据库规则：

- 启用 foreign_keys。
- 使用 WAL 模式和短事务。
- listing 结果唯一键为 (scan_id, listing_id)；实体复核为 (scan_id, entity_id)；评分为 (scan_id, subject_type, subject_id, dimension)；候选为 (scan_id, entity_id)。
- 唯一约束保证同一检查点和幂等键不能重复提交。
- 所有状态转换在单事务中校验旧状态。
- daily_market_data 至少建立 (listing_id, trade_date) 唯一索引，以及支持日期窗口的覆盖索引；annual_financials 至少建立 (entity_id, fiscal_year, announcement_date, source_id) 索引。
- 数据同步按最后成功交易日和公告日做增量获取；评分只读取 feature_snapshots，不在 10,000 个 listing 的评分循环中重复聚合日频原表。
- 性能报告记录 SQLite 文件大小、冷/热缓存、峰值内存、原始行数和 feature snapshot 行数。
- 数据迁移只生成并测试 migration；不得从开发流程直接执行生产迁移。

## 18. 并发、恢复与错误处理

### 18.1 单扫描与并发

- 数据库中使用活动扫描唯一约束，进程内锁只作为性能优化。
- FastAPI lifespan 启动 embedded runner；runner 按持久优先级从数据库认领 QUEUED background_job，内存队列不作为权威。
- 任一时刻只执行一个 background_job；EVIDENCE_COLLECTION 和 AI_DRAFT 排在尚未开始的 DATA_SNAPSHOT、OBJECTIVE_SCAN 或 CLONE_SCAN 之前。
- 启动时通过 SQLite job_leases 原子获取写实例租约，默认每 10 秒 heartbeat、60 秒过期。
- 发现未过期的第二写实例租约时，整个服务 fail-fast，不允许进入“API 能接单但没有 runner”的状态。
- 每次实例或 job 租约获取/接管都递增 lease_epoch，并向 attempt 发放 fencing_token。
- 每次 checkpoint、目标状态转换和 job 写入都必须在 SQL 条件中 CAS 校验 owner_id、lease_epoch 与 fencing_token；旧进程暂停后恢复时得到 0 行更新，立即以 LEASE_FENCED 停止，不能双写。
- 过期租约只能在事务中被新实例接管；接管前把原 RUNNING job 及其目标资源标记 INTERRUPTED。
- 人工复核使用 optimistic version。
- 最终化在事务内重新检查所有候选状态和规则哈希。

### 18.2 Provider 错误

- 429：遵守 Retry-After；没有该头时使用有上限的指数退避与抖动。
- 5xx 和网络超时：有限重试，耗尽后保存可恢复错误。
- 401/403：不重试，标记权限不可用。
- 解析器结构漂移：标记 PARSER_DRIFT，不用旧值冒充新数据。
- 一家 provider 失败时只按已配置的来源优先级降级；所有降级写入审计。

### 18.3 恢复

- 每批最多 200 个 listing，成功后更新带 fencing token 的检查点。
- DATA_SNAPSHOT 批次把 observation 与 staging checkpoint 在同一数据库事务提交；原始 artifact 可先按内容哈希幂等保存。只有完整任务最终事务能生成 READY manifest。
- OBJECTIVE_SCAN 批次把 score components、feature 使用记录与 scan checkpoint 在同一事务提交，只读取 READY snapshot。
- scan resume 读取冻结 rule snapshot、engine 语义版本和构建哈希；任一不兼容时拒绝原地恢复并要求新建子 scan。
- 阶段内重复处理同一批次必须得到相同结果。
- scan resume 只使用 snapshot 冻结 observation；中断期间 provider 产生的新数据不进入旧 scan。
- data snapshot resume 可以继续未完成批次，但已提交 artifact/observation 不替换；最终 manifest 精确记录每项获取时间。若用户要求统一重抓，取消旧 snapshot 并创建新资源。
- 失败批次不覆盖上一个成功快照。

## 19. 安全与隐私

- 默认只绑定 127.0.0.1，默认关闭 CORS。
- 开发环境由 Vite 把同源 /api 代理到 127.0.0.1:8177；生产构建由 FastAPI 同源提供静态前端，不依赖宽松 CORS。
- 绑定非 loopback 地址时，除 GET /api/health/live 外的全部 API，包括读取、证据和导出，都必须使用本地生成的 Bearer token。
- 非 loopback 模式禁止明文 HTTP：必须由 Uvicorn 配置证书，或位于显式配置的受信 TLS 反向代理之后。只有来自受信代理地址且 X-Forwarded-Proto=https 的请求可被视为安全；否则服务拒绝非 loopback 启动或返回 400 INSECURE_TRANSPORT。
- token 由 python -m app.cli issue-token 生成，服务端只保存哈希；本地明文文件位于 Git 忽略目录。rotate-token 使旧哈希失效，日志只记录 token_id。
- token 文件必须限制为当前操作系统用户可读；无法确认权限时拒绝非 loopback 启动。
- SPA 只允许用户在会话中手工粘贴 token，并只保存在 JavaScript 内存；不得写入 URL、HTML、构建产物、localStorage、sessionStorage、cookie 或日志。页面刷新后重新输入；轮换导致 401 时立即清除内存 token 并回到输入界面。
- 不使用 cookie 或浏览器 session，因此不存在双 token 来源。
- API 密钥只从环境变量或 Git 忽略的本地 secrets 文件读取。
- 日志对 Authorization、API key、token、导入路径中的敏感片段进行脱敏。
- 导入文件按内容嗅探和扩展名双重校验，限制大小、行数、工作表数和解压后体积。
- XLSX 解析禁止宏执行和外部链接加载。
- 文件名不参与实际存储路径拼接，防止路径穿越。
- URL 证据抓取只允许 HTTPS allowlist 主机与路径；每次 DNS 解析和重定向后重新校验，拒绝 loopback、私网、链路本地和云元数据地址，并限制响应体、重定向次数和总耗时。
- PDF/HTML/TXT 只做无执行解析，禁用脚本、外部资源和嵌入对象。
- 公告、网页、导入文本和 AI 返回均按不可信数据处理；只解析允许字段，不执行其中指令。
- AI 请求只发送完成当前复核所需的最少字段，不发送本地密钥或无关数据。

## 20. 测试策略

### 20.1 领域单元测试

覆盖：

- 八个维度权重和 DS2 权重合计 100%。
- 每个锚点、锚点之间插值、上下边界和非有限值。
- 五年窗口、公告截止日、CV、最大回撤、Beta 和下行捕获。
- 缺失值不补分、不重新归一化。
- 配置哈希改变时结果不可混用。
- 浮点舍入只影响展示，不影响排名。
- 参考固定规则与 LSA-DS2 新增校准分别使用黄金 fixture，防止二者在文案或配置中混淆。

### 20.2 资格与排名测试

覆盖：

- 每个行业排除代码。
- 金融机构 MODEL_NOT_APPLICABLE。
- 任一年亏损或经营现金流非正。
- 数据不足、监管检查未知和来源冲突。
- PARTIAL 不进入 Top 50。
- A/H 实体去重发生在核心 Top 50 之前；预筛代表与最终代表使用各自确定性规则。
- Top 50 和最终排名平局规则。

### 20.3 Provider 合约测试

- 全部使用固定 fixture，不依赖实时网络。
- 字段映射、单位、负号、公告日、币种、复权和分页。
- 权限不足、限流、超时、重试和缓存。
- HTML/JSON 结构漂移必须失败为 PARSER_DRIFT。
- 同源时间序列和跨源冲突。
- allowlist 之外的 URL 被拒绝。
- Gate 0 分子、分母、字段集合与报告哈希；synthetic 黄金报告可让纯分类器返回 TEST_ONLY/LIVE_READY，但持久化层拒绝其提升真实能力。

### 20.4 Job 与持久化测试

- 单活动扫描约束和幂等请求。
- CLONE_SCAN 准备 snapshot 期间保留活动槽，取消/失败后正确释放。
- 同一幂等键不同 payload 返回 IDEMPOTENCY_KEY_REUSED。
- 批次事务、取消安全边界、检查点与恢复。
- 重启后 RUNNING 转 INTERRUPTED。
- 恢复时配置哈希不一致。
- 恢复时 engine 语义版本或构建哈希不兼容。
- 中断期间 provider 数据变化时，旧 scan 仍使用冻结输入。
- 分别在 artifact 保存后、批次事务提交前、批次事务提交后和状态推进前模拟进程退出。
- 第二写实例租约失败时整个服务 fail-fast。
- 旧 runner 暂停超过租约、新 runner 接管、旧 runner 恢复时，fencing token 使旧写入失败。
- data_snapshot 未 READY 时 scan 创建被拒绝；READY snapshot 恢复评分不访问网络。
- preflight、snapshot、evidence collection、AI draft 和 clone job 在重启后都有持久状态与恢复路径。
- 每个 job_type 的 job/目标状态原子映射；CLONE_SCAN 中断不修改父 scan。
- 失败不覆盖旧成功数据。
- SQLite 临时数据库的迁移升级与回滚测试。

### 20.5 AI 与复核测试

- 无引用、引用过旧、少于两源、无一手来源、来源冲突和格式错误时阻止确认。
- prompt injection 文本不改变系统动作。
- AI 失败后可手工完成复核。
- AI 迟到响应不会覆盖新 draft 或已确认 review。
- 偏离建议超过 10 分必须填写理由。
- optimistic version 冲突不会覆盖他人修改。
- fake model 只用于自动化测试，不得标记为真实模型验收。

### 20.6 API 测试

- 无效日期、无效市场、非法状态转换和不存在资源。
- 无效 CSV/XLSX、重复提交、超大文件和公式单元格。
- 并发创建扫描、取消与最终化竞态。
- 非 loopback 匿名读取、写入、证据和导出均被拒绝，只有最小 liveness 可匿名访问。
- 日志脱敏和导出公式注入防护。
- CSV/XLSX 对 BOM、前导空白、Tab、CR/LF、控制字符与 = + - @ 组合执行统一转义；负数数值仍保持数值类型。
- CSV/XLSX 导出与数据库快照一致。

### 20.7 前端测试

- Vitest + Testing Library：加载、空态、PARTIAL、CONFLICTED、失败、取消、恢复和版本冲突。
- 使用 synthetic 报告覆盖 NOT_CONFIGURED、LIVE_PARTIAL 和 TEST_ONLY/LIVE_READY UI；测试状态不能进入真实数据库。
- Playwright：数据准备→客观扫描→复核→最终排名完整路径。
- 响应式布局、键盘操作、焦点、错误摘要和表格局部滚动。
- 前端不包含 DS2 计算实现，只渲染 API 明细。

### 20.8 必跑命令

后端命令只在 lightweight-stock-analysis/backend 执行：

    pytest tests/api
    pytest

前端命令只在 lightweight-stock-analysis/frontend 执行；该目录使用自己的 pnpm-lock.yaml，不修改父仓库 npm 文件：

    pnpm lint
    pnpm test
    pnpm typecheck
    pnpm build
    pnpm e2e

pnpm e2e 的 Playwright webServer 配置负责用测试环境启动 FastAPI 和 Vite、分配可用本地端口，并在结束后清理两个进程。

### 20.9 测试隔离、独立性与真实数据门

默认自动化测试必须：

- 设置 LSA_ENV=test，并由测试 fixture 在操作系统临时目录创建唯一 SQLite、缓存、导入、导出和 secrets 目录。
- 禁止外部网络，只允许测试进程之间的 localhost 连接。
- 使用固定 provider fixture 和明确标记的 fake AI；它们不能写入非测试数据库。
- 使用动态端口，结束时验证端口与子进程均已释放。
- 不写父仓库数据库、缓存、package-lock.json、用户导入或已有源码。
- 对本次测试允许写入的路径做前后清单断言，意外工作区写入使测试失败。

独立性验收把 lightweight-stock-analysis 复制到父仓库之外的临时目录，清除父项目 PYTHONPATH、NODE_PATH 和 node_modules 影响后，按自身锁文件安装依赖、创建临时数据库、启动前后端并跑完测试。静态架构测试同时拒绝 Python 导入 backend.app.* 和前端越出子应用目录的源码引用。

真实数据 Gate 0 是单独、需用户凭据和网络授权的验收：

    python -m app.cli preflight --markets CN,HK --as-of YYYY-MM-DD

该命令只验证权限、许可声明、覆盖率和固定真实样本读回，不运行交易、不写父项目数据。未执行或未达到 LIVE_READY 时，交付只能称为离线原型或 LIVE_PARTIAL，不能声称真实 A 股与港股全市场能力已完成。

若父仓库已有与本项目无关的失败，必须单独记录，不得修改或掩盖用户的现有工作区改动。

## 21. 验收标准

功能验收：

1. defensive-score-2.0.yaml 的八维权重精确合计 100%，六个客观权重精确合计 73。
2. 行业与适用性过滤在任何分数计算前执行。
3. 缺失、模拟、过期替代、冲突或主观未确认的数据不产生正式 DS2。
4. 六个客观维度都可追溯到输入、来源、报告期、公告日、锚点和未舍入结果。
5. AI 草稿没有自动确认权限，引用不足时 UI 和 API 都阻止确认。
6. 最终化后结果不可变；新规则只能形成新扫描。
7. A/H 同发行人不会在默认核心清单中重复计数。
8. CSV/XLSX 导出与最终数据库快照一致，并包含规则哈希和来源索引。
9. 任一测试环境的 mock/fake 数据都有显著标识，不能进入真实扫描或真实验收。
10. 所有结果页显示“研究用途，不构成投资建议”。
11. 页面、API 和导出把“全市场客观预筛”与“客观 Top 50 内部 DS2 排名”明确区分。
12. 同一扫描在恢复、provider 更新或应用重启后仍使用相同 universe、输入 observation、规则和 engine 快照。
13. 未通过真实数据 Gate 0 时，系统保持 NOT_CONFIGURED 或 LIVE_PARTIAL，不能显示 LIVE_READY。
14. 子应用复制到父仓库外仍能独立安装、迁移、启动和测试。

性能验收：

- tests/performance/fixtures/manifest.json 固定 schema_version、生成器版本、随机种子 20260824、10,000 个 listing 的状态分布、输入文件 SHA-256 和期望 Top 50 哈希；缺少或哈希不符时基准拒绝运行。
- 在 READY snapshot 与 feature snapshots 已生成且不含网络时间的前提下，运行 python -m app.benchmarks.objective_scan --manifest tests/performance/fixtures/manifest.json --runs 5。
- 冷运行使用新进程和复制到唯一临时路径的 SQLite 执行一次；热运行在同一进程预热一次后执行五次并取中位数。冷运行与热运行中位数都必须在 60 秒内完成硬过滤、客观评分与 Top 50 排序。
- 基准环境为 Windows x64、至少 4 个逻辑核心、8 GB 可用内存和本地 SSD；报告记录实际硬件、Python/Node 版本、SQLite 大小、冷/热耗时、峰值内存、原始行数和 feature 行数。
- 客观扫描运行期间，对 localhost GET /api/health 和 GET /api/scans/{scan_id} 各采样 100 次，p95 响应时间不高于 500 ms。
- Playwright 在同一期间测量 50 次候选过滤或展开操作，输入到下一次绘制的 p95 不高于 200 ms，且无主线程长任务超过 1 秒。

可靠性验收：

- data snapshot 遇到限流或网络中断、任一后台任务遇到进程退出后，可从最近成功检查点恢复；客观 scan 恢复不访问网络。
- 重复创建、恢复、取消和最终化不会产生重复结果。
- 权限失败、解析器漂移和来源冲突均呈现明确错误，而不是静默降级为成功。
- 第二写实例不能接受任务；AI 迟到响应不能覆盖已确认复核。

## 22. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| 港股结构化数据许可或覆盖不足 | 大量港股为 PARTIAL | Gate 0 量化覆盖；授权 API 与规范导入优先；公开披露只做允许用途；不承诺实时 |
| 公开页面结构变化 | provider 解析失败 | allowlist、fixture 合约测试、解析器版本和 PARSER_DRIFT |
| A/H 会计口径、币种和行业分类不同 | 跨市场分数失真 | canonical 层保留原口径；比率优先；分类版本化；冲突后修复来源并创建新扫描 |
| 五年 PE 或总回报历史不足 | 估值或波动率缺失 | 明确最小覆盖；标记 PARTIAL；不重分配权重 |
| AI 主观性和引用幻觉 | 行业/护城河误判 | 最少两源、一手来源、反证、人工确认和全量审计 |
| 锚点未经长期实证校准 | 分数解释偏差 | 规则版本冻结；后续通过独立研究修改新版本，不回写历史扫描 |
| Objective Top 50 漏掉主观维度很强的证券 | 最终结果不是全市场 DS2 前 50 | 产品与导出明确召回边界；如需提高召回只能发布新的漏斗版本 |
| 单进程中断 | 扫描暂停 | 小批次事务、检查点、INTERRUPTED 和幂等恢复 |
| 用户把排名理解为交易建议 | 使用边界误解 | 全程研究声明、不接订单、不输出仓位或确定性收益 |

## 23. 配置冻结与变更规则

defensive-score-2.0.yaml 必须包含：

- 公式版本、八维权重和六维 ObjectiveScore 权重。
- LSA-DS2 校准档版本、scorer/engine 版本和构建哈希。
- 所有子权重与分段锚点。
- 五年与三年统计窗口。
- canonical benchmark CN_CSI300_TOTAL_RETURN、HK_HSI_TOTAL_RETURN 和全收益口径。
- DS2 Canonical Industry Taxonomy v1、强制排除代码、provider 映射版本和模型不适用代码。
- 样本覆盖、行业可比组、冲突容差和证据新鲜度。

扫描创建时把完整配置保存到 rule_snapshots 并计算 SHA-256，同时记录可执行 scorer/engine 的语义版本和构建哈希。实现与测试只能读取该快照，不从散落的代码常量拼装规则。

任何会改变资格、分数或排名的修改都必须：

1. 产生新的语义版本和配置哈希。
2. 新增或更新相应测试。
3. 不修改历史 FINALIZED 扫描。
4. 在变更说明中列出受影响维度与兼容性。

## 24. 官方参考

- Tushare 财务指标接口：https://tushare.pro/document/2?doc_id=79
- Tushare 现金流量表接口：https://tushare.pro/document/2?doc_id=44
- Tushare 数据接口文档：https://tushare.pro/document/1
- 港交所实时数据服务概览：https://www.hkex.com.hk/Services/Market-Data-Services/Real-Time-Data-Services/Overview/Real_time-Datafeeds?sc_lang=en
- 港交所上市公司披露检索：https://www.hkexnews.hk/homelcicontentsearch.html
- 港交所披露检索指南：https://www2.hkexnews.hk/-/media/HKEXnews/Homepage/Listed-Company-Publications/Search-Guide/SimpleSearchGuide_e.pdf

以上链接用于界定首版 provider 的能力与合规边界，不代表应用自动获得任何商业数据权限。实施时仍需按实际账户权限、许可条款和接口版本验证。

## 25. 书面规格复核门

本文件是实现计划的唯一设计输入。用户复核并明确批准本文件后，才进入逐文件实施计划；在此之前不创建业务代码、数据库迁移或依赖清单。

批准时请同时确认以下五项，不拆成隐含假设：

1. 市场范围是 A 股加全部港交所主板/GEM 合格普通股，不只限法律意义 H 股。
2. 参考对话只固定 DS2 顶层权重；本文子权重、锚点和治理规则是新建的 LSA-DS2 2.0.0 校准档。
3. 全市场只自动计算六维 ObjectiveScore；完整 DS2 排名只覆盖 ObjectiveScore Top 50，存在召回限制。
4. 真实能力必须通过带许可、覆盖率和真实读回的 Gate 0；离线 fixture 不能替代。
5. 数据先形成 READY snapshot，扫描只消费冻结快照；所有异步工作由单进程持久 runner 执行。
