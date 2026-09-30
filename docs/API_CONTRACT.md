# API 合约文档

## 基础信息
- Base URL: `http://localhost:8000/api`
- Content-Type: `application/json`
- 所有 timestamp 使用 ISO 8601 格式

---

## 1. POST /analysis/runs — 创建分析任务

### 请求
```json
{
  "symbol": "603663",
  "task_type": "持仓复核",
  "run_mode": "STANDARD_MODE",
  "scenario_id": "qiam_discounted",
  "user_constraints": {
    "position_ratio": 0.12,
    "shares": 1000,
    "cost_price": 18.5,
    "max_drawdown": 0.08,
    "allow_add": true,
    "allow_t0": false
  },
  "config_profile_id": "default",
  "quant_engine_mode": "LOW_FREQ_MID_LONG",
  "bottom_research_config": {
    "lookback_range": "2y",
    "horizon_days": 20,
    "cov_window": 20,
    "min_drawdown_pct": 0.12,
    "downside_tolerance_pct": 0.05,
    "recovery_return_pct": 0.08,
    "repair_probability_threshold": 0.60,
    "max_research_position_pct": 0.30,
    "horizon_days_list": [5, 20, 60]
  },
  "research_loop_id": "RLOOP_...",
  "research_iteration_id": "RITER_..."
}
```

`quant_engine_mode`、`bottom_research_config`、`research_loop_id` 和 `research_iteration_id` 为可选字段。`quant_engine_mode` 支持 `HIGH_FREQ_SHORT` 和 `LOW_FREQ_MID_LONG`；未传时由后端按任务类型推断。`bottom_research_config` 是兼容请求名，当前语义为 MFE/MAE Path Research 配置，影响 `STANDARD_MODE` / `DEEP_MODE` 中 `quant_core.mfeMaeResearch` 子输出，不生成交易动作；其研究结论可在 DVG 放行、技术面不看空、证据质量达标且 MAE 跌破风险较低时对 QIAM 做受控一档校准。传入研究字段后，后端会在 run payload 写入 `rdResearch`，并在 run 创建、完成或失败时同步更新对应研究轮次。
Research Lab 当前轮次的“创建关联运行”入口会通过 `/new-task?research_loop_id=...&research_iteration_id=...` 把这两个字段带入新建任务页，前端提交时必须原样传给本接口，确保 run -> iteration 回写链路不断。

### 成功响应 (201)
```json
{
  "run_id": "RUN_20260511_120000_abc12345",
  "status": "CREATED",
  "stream_url": "/api/analysis/runs/RUN_20260511_120000_abc12345/stream"
}
```

## 2. POST /analysis/runs/{run_id}/start — 启动分析

### 响应
```json
{
  "run_id": "RUN_20260511_120000_abc12345",
  "status": "RUNNING"
}
```

---

## 3. GET /analysis/runs — 历史列表

### 响应
```json
[
  {
    "runId": "RUN_20260511_120000_abc12345",
    "stockCode": "603663",
    "stockName": "柯利达",
    "taskType": "持仓复核",
    "runMode": "STANDARD_MODE",
    "status": "COMPLETED",
    "finalAction": "WAIT",
    "createdAt": "2026-05-11T12:00:00",
    "updatedAt": "2026-05-11T12:00:30"
  }
]
```

---

## 4. GET /analysis/runs/{run_id} — 分析详情

### 响应
返回完整 AnalysisRun 对象，包含 agentResults, dagEvents, debateArtifacts, tokenUsage, auditLog 等。

`AnalysisRun.quantCore` 是新的 canonical 量化核心输出，可为 `null`。当 `quant_core` 已执行时，该字段包含 `{ marketTechnical, mfeMaeResearch, bottomResearch, factorSlicing, factorEngine, calculationAuthority, quantEngine, qiam, scenario, coreInterpretation, legacyOutputs, legacyAgentOutputs, warnings, missingData, provenance }`。其中 `mfeMaeResearch` 是当前 active 研究输出，`bottomResearch` 仅作为 legacy alias 回填同一 payload。旧 Agent ID `market_regime`、`technical_kline_analyst`、`market_technical_analyst`、`bottom_research`、`quant_engine`、`qiam` 和 `scenario_engine` 均重定向到 `quant_core`。

`AnalysisRun.guardrailHub` 是新的 canonical 护栏中枢输出，可为 `null` 或缺失以兼容旧历史 run。新 run 必须写入该字段，结构包含 `{ status, finalDecisionCap, killSwitch, dvg, risk, atrade, gateResults, warnings, auditId }`。`guardrail_hub` 同时负责 DVG 数据门禁、风险/熔断、交易微观结构和执行可达性，旧 Agent ID `dvg_gate`、`dvg_evidence_gate`、`risk_firewall`、`trade_micro`、`atrade`、`hallucination_guardrail`、`flash_crash` 和 `portfolio` 均重定向到 `guardrail_hub`。旧公共字段 `AnalysisRun.dvg`、`AnalysisRun.risk`、`AnalysisRun.atrade`、`AnalysisRun.killSwitch` 仍为必填，不删除、不改名，并必须由 `guardrailHub` 镜像回填；实时行情 preflight block 也必须同步写入 `guardrailHub`。

`AnalysisRun.quantCore.coreInterpretation` 是只读确定性解释层，版本为 `quant_core_interpretation_v1`。字段包含 `status`、`overallScore`、`overallBias`、`confidence`、`summary`、`weights`、`dimensions[]`、`conflicts[]`、`riskFlags[]`、`weightAdjusted`、`weightAdjustmentReasons[]` 和 `actionBoundary=READ_ONLY_NO_PERMISSION_CHANGE`。`dimensions[]` 包含 `key`、`label`、`score`、`bias`、`confidence`、`weight`、`evidence`、`warnings`；`conflicts[]` 的 `severity` 可为 `INFO`、`WARN`、`BLOCKING_CONTEXT`，其中 `BLOCKING_CONTEXT` 只代表解释层强冲突，不等于交易阻断。该字段会同步进入 `finalContext.conclusion_derivation_inputs.core_interpretation`，供最终报告引用，但不得改变 QIAM、SignalOps、Execution 或 `finalAction`。

`AnalysisRun.quantCore.coreInterpretation.pathRiskFilter` 是 MFE/MAE 路径风险过滤解释层，版本为 `mfe_mae_path_risk_filter_v1`。字段包含 `status`、`method=daily_proxy_no_future_labels_v1`、`horizonDays=20`、`actionBoundary=READ_ONLY_NO_PERMISSION_CHANGE`、`labelStatus=UNLABELED_NOWCAST_PROXY_ONLY`、`sampleQuality`、`leakagePolicy`、`simulation_only=true`、`is_real_trade=false`、`mfeMaeProxy`、`riskCurve[]`、`downsideRiskScore`、`maxRiskGradient`、`riskPolicy`、`evidence[]`、`warnings[]`、`limitations[]` 和 `provenance`。`mfeMaeProxy` 只能包含 `mfeProxy`、`maeProxy`、`riskRewardProxy` 等代理字段，不能表示已训练条件分位数或确定性价格预测。该过滤器只读取现有 `technicalKline`、`marketTechnical.market`、`qiam` 和 `dvg` payload，不重新拉取 K 线或外部数据；当日线少于 30、缺少收盘价、缺少支撑阻力基础字段或日线不是可验证 LIVE 数据时返回 `INSUFFICIENT_DATA`。`riskPolicy` 只影响解释层展示、`riskFlags[]` 与 `conflicts[]`，不得改变 QIAM、SignalOps、Execution、`finalAction` 或任何实盘/模拟交易权限。

`AnalysisRun.quantCore.coreInterpretation.visualDecisionPanel` 是只读派生展示面板，版本为 `quant_core_visual_decision_panel_v1`。字段包含 `directionProbability`、`pathPayoffProxy`、`riskGradient`、`probabilityOddsMatrix`、`actionBoundary=READ_ONLY_NO_PERMISSION_CHANGE`、`simulation_only=true` 和 `is_real_trade=false`。`directionProbability` 优先读取 `futureTrendProbability.points[]` 的校正上涨/下跌/震荡概率；`pathPayoffProxy` 只暴露 `mfeProxy`、`maeProxy`、`riskRewardProxy`、`expectedPathValueProxy` 等代理值；`riskGradient` 显示 `downsideRiskScore`、`maxRiskGradient` 和 `riskPolicy`；`probabilityOddsMatrix.zone` 可为 `PRIORITY`、`WATCH`、`FILTER` 或 `INSUFFICIENT_DATA`。该面板只为 `/quant-core` 做概率、赔率和路径风险解释，不改变 QIAM、SignalOps、Execution 或 `finalAction`；历史 run 没有该字段时前端必须回退读取 `pathRiskFilter`、`futureTrendProbability` 和 `mfeMaeResearch`。

`AnalysisRun.mfeMaeResearch` 可为 `null`。当 `quant_core.mfeMaeResearch` 已执行时，该字段包含 MFE/MAE Path Research 的 canonical 输出；`AnalysisRun.bottomResearch` 和 `quantCore.bottomResearch` 仅作为 legacy alias 回填同一 payload，避免历史 run 和旧前端崩溃。输出包含 `researchType=MFE_MAE_PATH_RESEARCH`、`actionBoundary=RESEARCH_ONLY_NO_PERMISSION_CHANGE`、`labelStatus`、`sampleQuality`、`leakagePolicy`、`simulation_only=true`、`is_real_trade=false`、`mfeFavorableProbability`、`maeBreachProbability`、`mfeProxy`、`maeProxy`、`riskRewardProxy`、`downsideRiskScore`、`riskPolicy`、`marketProfile`、`mfeMaeFormulaConfig`、`mfeMaePathModel`、`modelDiagnostics`、`positionEnvelope`、`probabilitySeries`、`currentPrediction`、`horizonForecasts`、`trendSynthesis` 和 `qiamAdjustmentPreview`。旧字段 `bottomRepairProbability` 映射到 `mfeFavorableProbability`，`breakdownRiskProbability` 映射到 `maeBreachProbability`，只为兼容显示和历史接口存在。`probabilitySeries` / `horizonProbabilitySeries` 的历史段是由论文标签公式生成的 0/1 标签命中序列，前端可展示为 0/100 的工程可视化；只有最新 `UNLABELED_NOWCAST` 段表示当前日线代理概率，该图不是论文原图，也不是确定性条件分位数预测。若日线 payload 不是 `dataMode=LIVE`，即使包含 rows，也只能返回 supporting-only/`SKIPPED`。

MFE/MAE Path Research 的标签公式为 `mfeLabel=max(high[t+1:t+H])/close[t]-1`、`maeLabel=min(low[t+1:t+H])/close[t]-1`、`maeAbsLabel=abs(min(0, maeLabel))`、`riskRewardLabel=mfeLabel/(maeAbsLabel+epsilon)`。最新交易日永远是 `UNLABELED_NOWCAST`，不进入 Rank IC、coverage 或训练窗口。`modelDiagnostics.mfeMaePathRiskEvaluation` 使用 train-before-test walk-forward 输出 `rankIc`、`rankIcMode=single_symbol_time_series_spearman`、`quantileCoverage`、`folds[]`、`sampleQuality` 和 `leakagePolicy`。`modelDiagnostics.conditionalQuantileEvaluation` 使用 `walk_forward_empirical_conditioned_quantile_v1` 输出 MFE、MAE Abs、RiskReward 的 Q50/Q80/Q90 覆盖率、Rank IC、walk-forward folds 和 `sampleQuality`；该评估只使用历史标签和训练窗内的 entry-day proxy 分桶，`actionBoundary=RESEARCH_ONLY_NO_PERMISSION_CHANGE`，`simulation_only=true`，`is_real_trade=false`。A股通过 `marketProfile.market=CN_A` 启用涨跌停、T+1、100 股手和 limit-board aware MAE 调整；港股通过 `marketProfile.market=HK` 启用无涨跌停尾部风险、流动性缺口权重和未知 board lot 的 review-only 约束；美股/ETF 和日本市场分别输出独立 `marketProfile`、样本迁移状态和缺失外部数据原因。所有字段均为研究证据，不是 BUY/ADD/SELL 指令，不能绕过 DVG、Risk、Execution、SignalOps 或 `finalAction`。

`AnalysisRun.marketTechnical` is optional and read-only. When `quant_core.marketTechnical` has run, it contains `{ market, technicalKline, alignment, confidence, summaryForDownstream, warnings }`. The legacy public fields `AnalysisRun.market`, `AnalysisRun.technicalKline`, and `AnalysisRun.qiam.technicalKlineConstraint` remain compatible and are backfilled from this fused result.

`GET /api/technical-kline/governance` returns `savedGovernance.caseImpact` as review-only Technical Kline governance metadata. `caseImpact` includes the existing overall/current-config case counts and `byConfigHash[]`, plus `representativeCaseSet`, `parameterVersionReview`, and `longWindowRegression`. `representativeCaseSet` reports minimum reviewed cases, symbol diversity, required classifications (`valid`, `misjudge`, `insufficient_data`), missing classifications, remediation next actions, `blocking=false`, and `boundary=REVIEW_ONLY_NO_TRADE_ACTION`. `parameterVersionReview` reports the current config case count, missing current-config classifications, baseline config count, optional current-vs-baseline valid/misjudge/insufficient-data rate deltas, action, and the same no-trade boundary. `longWindowRegression` reports retained reviewed-case coverage across the last 200 local governance cases, current-vs-baseline config case counts, config-version and symbol diversity, classification gaps, remediation, `dataPolicy=REVIEWED_REAL_TUSHARE_KLINE_CASES_ONLY`, `blocking=false`, and `tradeActionPolicy=NO_DIRECT_TRADE_ACTION`. These fields guide parameter governance review only; they must not create BUY/SELL/SIM actions or override QIAM, SignalOps, Execution, or `finalAction`.

DVG Gate 兼容旧字段，同时增加 Quant Engine 模式化门禁元数据；新 run 的 DVG payload 来源是 `guardrailHub.dvg` 镜像：

```json
{
  "dvg": {
    "quantEngineMode": "LOW_FREQ_MID_LONG",
    "activeModule": "dvg_low_frequency_mid_long",
    "criticalMissingData": [],
    "ignoredMissingData": ["Level-2 逐笔成交", "盘口深度"],
    "qiamPermission": "ALLOW",
    "dvgModules": {
      "highFrequencyTrading": {},
      "lowFrequencyMidLong": {}
    }
  }
}
```

---

## 5. GET /analysis/runs/{run_id}/nodes — Agent 节点状态

### 响应
AgentNode 数组，包含每个节点的 status, isSkipped, isBlocked, duration, auditId 等。

---

## 6. GET /analysis/runs/{run_id}/agents — Agent 执行结果

### 响应
AgentResult 数组。

---

## 7. GET /analysis/runs/{run_id}/dag-events — DAG 事件

### 响应
DagEvent 数组。

---

## 8. GET /analysis/runs/{run_id}/debate — Agent 辩论

### 响应
```json
{
  "debateArtifacts": { "turns": [], "summary": {} },
  "tokenUsage": { "rows": [], "totals": {} }
}
```

---

## 9. GET /analysis/runs/{run_id}/nodes/{node_id} — 节点详情

---

## 10. GET /analysis/runs/{run_id}/audit — 审计日志

---

## 10.5 Portfolio snapshots and broker import template metadata

Portfolio snapshots are created through `POST /portfolio/manual` and `POST /portfolio/imports`; imported CSV/TSV/XLSX files keep the existing normalized holding rows and additionally expose broker-template metadata on the import response, snapshot detail, snapshot summary, and import job lookup.

The added fields are advisory metadata and do not change `portfolio_snapshot_id` submission or analysis-run creation:

- `brokerTemplateId`: normalized template identifier such as `eastmoney`, `htsc`, `gtja`, `futu`, `tiger`, `generic_broker`, `generic_table`, `manual_entry`, or `signalops_sim`.
- `brokerTemplateLabel`: human-readable import template label.
- `templateConfidence`: `0.0` to `1.0` parser confidence based on source hints and mapped columns.
- `templateWarnings`: review notes for missing required/review columns or generic alias fallback.

Broker-template detection accepts common broker-export header variants, including spaced, underscored, and symbolic English forms such as `Stock Code`, `Security Code`, `Position`, `Available to Sell`, `Average Cost`, `Market Value`, and `P&L`. Header normalization is advisory parsing evidence only; it does not imply broker account connectivity or trading authority.

Malformed `POST /portfolio/imports` files return HTTP 400 with structured `detail`:

- `message`: concise validation failure.
- `jobId`: failed import job id, also available through `GET /portfolio/imports/{job_id}`.
- `reason`: bounded code such as `NO_VALID_HOLDING_ROWS`, `FILE_TOO_LARGE`, `TOO_MANY_ROWS`, `COLUMN_LIMIT_OR_MISMATCH`, `CELL_TOO_LARGE`, `UNSUPPORTED_ENCODING`, or `LEGACY_XLS_UNSUPPORTED`.
- `acceptedExtensions`: `.csv`, `.tsv`, and `.xlsx`.
- `expectedColumns.required`: symbol and share/quantity aliases that must map before a snapshot can be created.
- `expectedColumns.recommended`: broker review aliases for name, availability, cost, market value, and P&L.
- `observedHeaders`: bounded non-empty source headers from the malformed file.
- `matchedFields`: normalized Portfolio fields that were recognized before validation failed.
- `missingRequiredFields`: required normalized fields that were not recognized, currently `symbol` and/or `shares`.
- `rowPreview`: first malformed rows with row numbers and bounded cell values for UI repair preview.
- `brokerTemplateHint`: best-effort `brokerTemplateId`, label, confidence, and template warnings derived from filename/source-name hints plus matched headers.
- `templateConfidenceNote`: concise explanation of the template confidence, matched fields, missing required fields, and whether a broker-specific source hint matched.
- `repairSuggestions`: bounded generic or broker-specific column repair suggestions for the missing required fields.
- `limits`: byte, row, column, and cell-size caps.

Failed import jobs preserve the same object as `importError` on `GET /portfolio/imports/{job_id}`. A failed import job is diagnostic evidence only and never creates a usable snapshot for New Task.

`/portfolio` renders this metadata beside each snapshot, and `/new-task?portfolio_snapshot_id=...` includes it in the pre-task Portfolio risk prompt. These warnings are review evidence only; Guardrail Hub, QIAM, Execution, and final human-confirmation gates remain authoritative.

---

## 11. SignalOps 自动模拟交易

SignalOps 当前版本以“全自动股票池模拟交易”为主入口。接口只操作沙箱资金、生命周期和 `SIM_*` 模拟动作，不连接真实交易账户。

### GET /signalops/auto-paper/config — 自动模拟交易配置

返回当前全局股票池配置：

```json
{
  "enabled": true,
  "symbol": "600879,002846",
  "stock_name": "航天电子,英联股份",
  "initial_cash": 10000000,
  "signal_ids": {
    "600879": "SIG_...",
    "002846": "SIG_..."
  },
  "realtime_interval_seconds": 30,
  "tick_interval_seconds": 60,
  "use_llm": true,
  "max_llm_calls_per_day": 6,
  "llm_calls_used_today": 0,
  "llm_gate_status": "TRADING_SESSION",
  "last_kline_snapshot_by_symbol": {}
}
```

`compact=true` 可用于只读控制台首屏加载。该模式保留基础配置、资金参数、股票池和胜率统计，省略 `last_tick_result`、K 线缓存、历史复盘队列等大体积调试明细；默认不传时仍返回完整配置，保持兼容。

### GET /signalops/auto-paper/status — 自动模拟交易状态

返回当前自动运行状态、最近 tick / 复盘摘要、审查队列和验证状态。`compact=true` 会保留页面展示所需的状态、队列、决策卡片摘要和股票名称来源，但裁剪完整 K 线快照、LLM trace、重复复盘队列等大体积字段，用于避免 `/signalops` 首屏因本地代理或浏览器传输过大而超时。

状态响应包含 `decision_tree_state`，按 symbol 记录日K决策树 compact 摘要：

```json
{
  "decision_tree_state": {
    "version": 1,
    "symbols": {
      "603663": {
        "status": "ACTIVE",
        "candidate_low": {},
        "active_tree": {
          "tree_id": "SIGTREE_...",
          "start": {"date": "2026-05-20", "low": 9.0},
          "peak": {"date": "2026-05-24", "price": 10.2, "gain_pct": 0.1333},
          "current": {"date": "2026-05-27", "close": 9.4, "ma5": 9.62, "near_end": true},
          "branch_count": 3,
          "branches": []
        },
        "latest_closed_tree": {},
        "last_review": {},
        "last_tuning_audit": {},
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

### PATCH /signalops/auto-paper/config — 更新自动模拟交易配置

请求字段支持股票池代码、股票池总资金、行情/跟进频率、LLM 预算和交易手续费。`initial_cash` 是股票池唯一全局资金；多股票时后端按池内股票数给每个沙箱子仓分配预算，前端汇总不得重复累加子仓初始资金。

手续费字段：
- `commission_rate`：佣金率，默认 `0.0001`，对应 0.01%。
- `commission_min_fee`：最低手续费，默认 `5` 元。
- `commission_min_trade_value`：最低计费金额阈值，默认 `50000` 元；单笔成交金额低于该值时按最低手续费收取，否则按 `成交金额 * commission_rate` 收取。

### POST /signalops/auto-paper/tick — 触发一次自动跟进

```json
{
  "force": false
}
```

返回本次 AI 自动判断、行情快照、模拟订单、沙箱资金和 warnings。交易日交易时段才允许主动 LLM 调用；非交易时段仅允许收盘复盘窗口按预算调用。

AI 自动交易动作继续限定为 `SIM_*` 沙箱动作。除已有 `SIM_BUY`、`SIM_SELL`、`SIM_HOLD`、`SIM_REBALANCE`、`SIM_CLOSE` 外，本地模拟仓还支持：
- `SIM_T_BUY`：持仓回落但未失效时，AI 自行判断是否用部分现金买回做 T。
- `SIM_T_SELL`：持仓快速拉升时，AI 自行判断是否卖出部分模拟仓做 T，保留底仓观察。
- `SIM_SHORT`：无持仓且触发下跌观察条件时，AI 可以建立模拟空头观察仓；持仓数量以负数表示，不连接真实融券或真实交易账户。
- `SIM_COVER`：模拟空头遇到反弹或命令平仓时，AI 回补负数量模拟仓。

每次 tick 会根据行情、可用现金、已有多/空敞口、Research Lab 调参结果和 LLM 预算输出仓位比例、目标金额、board-lot 数量与 `strategyIntent`，而不是要求人工填写每次使用资金比例或持仓数量。自动撮合始终按 100 股整数手和手续费规则计算；`SIM_SELL` / `SIM_CLOSE` / `SIM_T_SELL` 会执行 A 股 T+1 长仓校验，当天买入形成的长仓不可当天卖出。

若日K决策树生命周期已经确认，tick 响应会增加：

- `decision_tree_branch`：本次有效 tick 的 branch，包含动作、价格、MA5、阶段低点、峰值、收益、组合快照、订单摘要、K线/稳定性质量、blockers、`simulation_only=true`、`is_real_trade=false`。
- `decision_card.decision_tree`：当前 active tree 或刚关闭 review 的摘要。
- `order.risk_constraints.decision_tree_branch`：有订单时同步写入同一个 branch，便于订单审计。

skipped interval 和异常 tick 不推进生命周期；日K不足、低点尚未确认时只更新 `decision_tree_state` 的状态/候选低点，不生成 branch。

K线质量门禁会写入 `decision.pre_buy_quality.components.kline_signal_quality` 和 `decision_card.kline_signal_quality`。字段包含 `trend_regime`、`bottom_stage_score`、`volatility_compression`、`volume_price_confirmation`、`multi_timeframe_alignment`、`risk_invalidation`、`final_score`、`grade`、`action_policy`、`kline_strategy` 和 `ladder_buy_policy`。该评分只影响 `SIM_*` 沙箱动作：低评分或 K线不可用会把模拟买入降级为 `SIM_HOLD`，失效条件可触发 `SIM_CLOSE`，不会生成真实交易动作。

稳定性门禁会写入 `decision.pre_buy_quality.components.strategy_stability_quality` 和 `decision_card.strategy_stability_quality`。字段包含 `stability_score`、`regime_state`、`volatility_state`、`drawdown_throttle`、`confidence_floor`、`action_policy`、`meta_label_gate`、`volatility_sizing_policy`、`stability_strategy`、`triple_barrier_summary` 和 `reasons`。该组件只能进一步限仓或把 `SIM_BUY` / `SIM_T_BUY` 降级为 `SIM_HOLD`，不能绕过 K线 `INVALIDATE`、K线数据缺失、A 股 T+1、涨跌停、100 股整数手、手续费或印花税规则。

2026-05-24 gate hardening:
- `READY` K-line payloads with `rows=[]`, empty data, insufficient samples, `FAILED`, or `SKIPPED` without cache are treated as `HOLD` / `BLOCKED`; simulated buy actions are not allowed.
- K-line support/invalidation is evaluated against bars before the current bar, so the current low cannot hide a support break.
- K-line `INVALIDATE` is a hard post-LLM gate. Existing simulated long exposure is converted to `SIM_CLOSE`; otherwise `SIM_BUY` / `SIM_T_BUY` is downgraded to `SIM_HOLD`.
- `_maybe_create_order` defensively rejects gated buys with `kline_quality_buy_blocked`, even if a caller constructs a buy decision directly.
- K-line snapshots are cached in `last_kline_snapshot_by_symbol`; refresh intervals reuse cache, and no-cache intervals return `SKIPPED`, which blocks buys.
- Stability gate blocks direct or forced simulated buys with `strategy_stability_buy_blocked` when meta-label evidence or high-volatility regime fails the conservative rule gate.

### POST /signalops/auto-paper/daily-review — SignalOps x Research Lab 收盘复盘
```json
{
  "force": false,
  "trading_date": "2026-05-20",
  "reviewer": "auto_research_reviewer"
}
```

对当天 AI 模拟仓订单、持仓、浮盈亏、触发因子和失效条件做清洗，写入 SignalOps review、agent simulation case 与 Research Lab iteration/evidence，并生成下一交易日使用的保守调参结果。返回 `loop_id`、`iteration_id`、`case_ids`、`cleaned_records`、`tuning_update` 和更新后的自动模拟仓配置。后台自动 tick 在交易日 15:00 后会尝试执行一次；手动接口可用 `force=true` 重跑。

返回和 `last_research_review` 可包含 `decision_tree_reviews`。每个 review 包含 `review_id`、`tree_id`、symbol、起点、峰值、结束原因、branch 正确/错判/部分正确/跳过统计、最近 branch review、knowledge candidate id（若已创建）以及 simulation-only 标记。compact payload 只保留最近摘要，完整历史留在 `decision_tree_state.symbols[*].closed_trees` 的裁剪版本中。

闭环约束：
- 只处理 `SIM_*` 模拟订单，继续保持 `simulation_only=true` / `is_real_trade=false`。
- Research Lab 案例因子会写入 `factor_adjustments`，下一次 AI 买入触发阈值、失效阈值和仓位比例会读取这些调整。
- K线候选策略会写入 `strategy_experiment.candidate_config.kline_strategy`、`strategy_experiment.candidate_config.ladder_buy_policy` 和 `candidate_evidence_package.kline_evidence_package`。Daily review 仍只生成候选或 `BACKTEST_PENDING`，进入 `READY_FOR_REVIEW` 仍必须依赖专用 Backtest 实验和 benchmark 门禁。
- 稳定性候选策略会写入 `strategy_experiment.candidate_config.stability_strategy`、`strategy_experiment.candidate_config.meta_label_gate`、`strategy_experiment.candidate_config.volatility_sizing_policy` 和 `candidate_evidence_package.stability_evidence_package`。
- SignalOps review queue items include server-generated `parameter_diff_summary` at the queue-item level and under `strategy_experiment.parameter_diff_summary`. The summary uses `policy_id=signalops_candidate_parameter_diff_v1`, bounded `rows`, changed/added/removed/unchanged counts, `source=server_generated`, `simulation_only=true`, and `is_real_trade=false`. It is review evidence only and does not bypass `READY_FOR_REVIEW`, benchmark, evidence-quality, or human-review gates.
- SignalOps review decisions persist the reviewed parameter delta as `parameter_diff_summary`, `parameter_diff_checksum`, `reviewed_parameter_count`, and `reviewed_parameter_changed_count`; `review_decision_summary.parameter_diff_checksum` repeats the checksum for compact audit views. Non-blocked queue items also retain `reviewed_parameter_diff_checksum` and `reviewed_parameter_diff_summary`. These fields are audit evidence only and keep `simulation_only=true` / `is_real_trade=false`.
- SignalOps status includes `review_decision_event_ledger` with `schema=signalops_review_decision_event_ledger_v1`, event count, latest event hash, append-only marker, and simulation/live flags. `GET /signalops/auto-paper/review-decision-events?limit=100` returns a bounded append-only export bundle with `schema=signalops_review_decision_event_export_v1`, `events[]`, `total_event_count`, `returned_event_count`, `latest_event_hash`, `bundle_checksum=sigops-reviewevents-*`, `export_signature_status`, optional `export_signature.schema=signalops_review_decision_event_export_signature_v1`, `algorithm=HMAC-SHA256`, `signature=sigops-reviewevents-hmac-*`, `payload_checksum`, `append_only=true`, `simulation_only=true`, and `is_real_trade=false`. `POST /signalops/auto-paper/review-decision-events/verify` accepts `{ "bundle": <export bundle> }` and returns `schema=signalops_review_decision_event_export_verification_v1`, `status=VALID|INVALID|UNSIGNED|KEY_MISSING`, checksum/signature/key-ref/signed-field validation flags, event count, warnings, and the same simulation/live boundary fields. `POST /signalops/auto-paper/review-decision-events/handoff?limit=100` builds the signed export, verifies it, and writes bundle plus `signalops_review_decision_event_export_handoff_manifest_v1` to `AUTO_PAPER_REVIEW_DECISION_EXPORT_HANDOFF_DIR` only when verification is `VALID`; otherwise it returns `DISABLED`, `BLOCKED`, or `FAILED` without writing a handoff bundle. Configure `AUTO_PAPER_REVIEW_DECISION_EXPORT_SIGNING_KEY` and optional `AUTO_PAPER_REVIEW_DECISION_EXPORT_SIGNING_KEY_REF` to sign and verify exports; when the signing key is absent the bundle remains readable with `export_signature_status=UNSIGNED` but handoff is blocked. Events persist in local `auto_paper_review_decision_events.jsonl` and are audit evidence only.
- Deployment shippers may write `AUTO_PAPER_REVIEW_DECISION_EXPORT_HANDOFF_DIR/shipper_status.json` after signed review-event handoff upload/index/retention checks complete. The expected sidecar schema is `signalops_review_decision_event_export_shipper_status_v1`; supported statuses are `DELIVERED`, `PENDING`, `FAILED`, and `UNKNOWN`. SignalOps status exposes it as `review_decision_event_ledger.handoff_shipper_status`, and successful handoff responses also include a current optional `shipper_status` snapshot. The app redacts token/secret/authorization-like text, compares `last_handoff_id`, `last_bundle_checksum`, and `last_latest_event_hash` to the latest local manifest, and reports `matches_latest_handoff`, `matches_latest_export`, `search_index_ready`, and bounded `issues`. This sidecar is status evidence only; deployment remains responsible for actual external upload, KMS/object-storage custody, provider retention, and centralized search.
- 复盘不直接改实盘交易计划，只影响自动模拟仓的后续判断参数。

### POST /signalops/auto-paper/command — 沙箱控制指令

```json
{
  "symbol": "600879",
  "command": "FORCE_CLOSE_AND_REMOVE",
  "reason": "User forced paper close from SignalOps."
}
```

支持：

- `FORCE_OPEN_BUY`：控制台触发一次模拟开仓观察，只写入并撮合 `SIM_BUY`。
- `FORCE_CLOSE`：强制记录并撮合平仓动作；多头使用 `SIM_CLOSE`，模拟空头使用 `SIM_COVER`，保留股票池跟踪。
- `REMOVE_SYMBOL`：从股票池移除，不主动生成平仓单。
- `FORCE_CLOSE_AND_REMOVE`：先强制模拟平仓，再移除股票池并关闭对应信号。

所有命令均为模拟仓指令，必须保持 `simulation_only=true` / `is_real_trade=false`。

`FORCE_OPEN_BUY` only forces an immediate simulation evaluation. It still fetches or reuses the K-line snapshot, computes `pre_buy_quality`, builds deterministic SignalOps module evidence, respects ladder/stability/Quant Core MFE-MAE path-risk target caps, and returns `BLOCKED` with `kline_quality_buy_blocked`, `strategy_stability_buy_blocked`, or `quant_core_path_risk_buy_blocked` when the simulated buy gates fail. `decision_card` must preserve `quant_core_path_risk`, `quant_core_path_risk_policy`, `quant_core_path_risk_avoids_new_buy`, `future_trend_probability`, and `review_fields` in compact status payloads. The compact `quant_core_path_risk` summary must keep `actionBoundary`、`labelStatus`、`sampleQuality`、`leakagePolicy`、`simulation_only=true`、`is_real_trade=false`, so the UI can show that MFE/MAE is only a read-only risk filter. `AVOID_NEW_BUY` blocks only `SIM_BUY` / `SIM_T_BUY`; it must not resize or block `SIM_SHORT`, `SIM_SELL`, `SIM_CLOSE`, `SIM_T_SELL`, or `SIM_COVER`.

前端 `/signalops` 的 `SignalOps 控制台` 统一承载 `AI 开仓`、`强制平仓` 和 `平仓移除`，股票池列表中的单股操作只负责选入控制台，避免把人工下单入口散落在交易日志或持仓列表中。

### SignalOps 生命周期和沙箱明细

- `GET /signals`：列出生命周期信号，供自动股票池详情和回测读取。
- `GET /signals/{signal_id}`：获取信号详情、生命周期时间线、审计和 review。
- `POST /signals/{signal_id}/transition`：生命周期迁移。`PAPER_TEST` 允许 AI 沙箱探索；`QUALIFIED` 及以上仍受 DVG/QIAM/Execution/人工确认门禁约束。
- `GET /signalops/{signal_id}/paper-portfolio`：读取某只股票的沙箱子仓。默认不存在时返回 `404/PAPER_PORTFOLIO_NOT_FOUND`；前端只读聚合视图可传 `allow_missing=true`，此时不存在返回 `200/null`，避免把“尚未建仓”渲染成连接异常。
- `GET /signalops/{signal_id}/paper-positions`：读取模拟持仓。
- `GET /signalops/{signal_id}/paper-orders`：读取 `SIM_*` 模拟订单日志。

### Backtest SignalOps AUTO_PAPER_V2

`POST /research/backtest/runs`、`POST /research/backtest/signalops-sample` 和 `POST /research/backtest/signalops-experiment` 是 canonical SignalOps Backtest API；旧 `/backtest/*` 路径仅作为 legacy wrapper 保留。传入 `parameters.signal_source="SIGNALOPS"` 时，后端优先读取 `auto_paper_trading_store` 的 cleaned record history 和当前自动模拟生命周期信号；没有可用自动模拟样本时才使用旧生命周期信号兜底。回测仍是只读复盘，不会触发真实交易，必须保持 `simulation_only=true` / `is_real_trade=false`。

传入 `parameters.signal_source="MFE_MAE_PATH_RESEARCH"` 时，后端从 MFE/MAE Path Research 概率序列生成 `WATCH` 型模拟信号，`source_node="mfe_mae_path_research"`，并强制写入 `simulation_only=true`、`is_real_trade=false`。旧值 `BOTTOM_RESEARCH` 仍作为兼容别名接受，但返回报告的 canonical `signal_source` 为 `MFE_MAE_PATH_RESEARCH`。回测指纹包含 MFE/MAE config、模型版本、数据窗口和信号哈希，不包含时间戳或 UI 状态。

`BacktestRequest.parameters` 可选新增：
- `signalops_version`：默认 `AUTO_PAPER_V2`。
- `signalops_source_mode`：`AUTO`（默认）、`AUTO_PAPER` 或 `LIFECYCLE`。

当 `signal_source=SIGNALOPS` 时，后端会补齐当前 SignalOps A 股沙箱规则，不覆盖调用方显式传入值：
- `commission_bps` = `auto-paper.commission_rate * 10000`
- `stamp_tax_bps` = `auto-paper.stamp_duty_rate * 10000`
- `min_commission` = `auto-paper.commission_min_fee`
- `t_plus_one=true`

SignalOps cleaned history 支持回放动作：`SIM_BUY`、`SIM_SELL`、`SIM_CLOSE`、`SIM_HOLD`、`SIM_T_BUY`、`SIM_T_SELL`、`SIM_SHORT`、`SIM_COVER`。`SIM_HOLD` 会进入 signal log 作为同步证据，但不会触发交易。

旧生命周期信号兜底时，signal metadata 的公共来源继续保持 `metadata_json.source="SIGNALOPS"`；内部来源细节写入 `metadata_json.source_detail="SIGNALOPS_LIFECYCLE_FALLBACK"`，避免调用方依赖内部 fallback 标签。

`POST /research/backtest/signalops-experiment` 的候选验证报告会额外包含 `walk_forward_validation.stability_validation_report`、`research_evidence_package.stability_evidence_package`、Wilson 胜率下界、手续费后期望、MAE/MFE、embargo 检查和 multiple-testing penalty 结果。`READY_FOR_REVIEW` 仍要求 benchmark 可用、样本质量非 `LOW` / `SUPPORTING_ONLY`、样本外验证通过，且稳定性验证不能失败。

### Backtest SignalOps 随机验证任务

`POST /research/backtest/signalops-random-validation/jobs` 会创建异步随机验证任务。任务从近十年全 A 股票池随机抽取两支股票和不少于一年的历史窗口，使用当前 SignalOps 自动模拟配置做确定性历史回放，并比较原策略、保守微调候选、买入持有和空仓基准。任务始终是模拟研究能力，返回和写回状态都必须保持 `simulationOnly=true`、`isRealTrade=false`。

请求示例：

```json
{
  "mode": "VALIDATE_AND_FEEDBACK",
  "history_years": 10,
  "min_window_days": 365,
  "max_window_days": 540,
  "min_trading_days": 200,
  "initial_capital": 100000
}
```

任务接口：
- `POST /research/backtest/signalops-random-validation/jobs`
- `GET /research/backtest/signalops-random-validation/jobs/{job_id}`
- `POST /research/backtest/signalops-random-validation/jobs/{job_id}/cancel`

响应核心字段：
- `jobId`、`status`、`progressStep`、`seed`、`mode`
- `sampleWindows`：随机股票、样本区间、交易日数量、分层信息和数据源。
- `dataQuality`：全 A 股票池 hash、数据可信度、样本失败记录、是否满足最少交易日和交易闭环。
- `baselineResults` / `candidateResults`：原策略、候选策略、买入持有和空仓基准摘要。
- `evidenceLevel`：`STRONG` / `MEDIUM` / `WEAK`；弱证据不能触发自动微调。
- `appliedAdjustment`：是否建议/应用保守微调、参数 delta、before/after、rollback token。
- `rejectionReasons`：不写回或不应用微调的原因。

`mode="VALIDATE_ONLY"` 只生成报告和随机验证状态，不应用策略微调。`mode="VALIDATE_AND_FEEDBACK"` 只有在真实行情数据、样本不少于 200 个交易日、候选策略不劣于原策略、候选样本具备完整买卖闭环且证据等级非弱时，才允许写入 `auto_paper_trading_store.random_validation_state` 并执行保守微调。HOLD-only、buy-only、sell-only 或无完整交易闭环的样本只能展示报告，不能触发自动微调。单次阈值调整上限为 `0.05`，仓位比例调整上限为 `0.02`。`MOCK` / `MOCK_FALLBACK` 数据只能作为报告，不允许影响 SignalOps 策略。

`BacktestReport.provenance` 和 `report.researchContract` 会增加只读元信息：
- `signalOpsVersion`
- `signalOpsSourceMode`
- `simulationOnly`
- `isRealTrade`
- `executionRules`
- `signalBoundary`
- `cleanedRecordCount`
- `reviewQueueSyncStatus`

`BacktestReport.researchGradeScore` is a read-only aggregate score for research use. It combines sample count, out-of-sample coverage, benchmark excess return, maximum drawdown, execution constraints, and statistical confidence into `score` (0-100), `band`, `researchUsage`, `canSupportResearchVerdict`, `supportingOnly`, and per-component scores. Backtests below the research-grade threshold remain `supporting_only` evidence and must not be treated as primary strategy-validity proof.

### Research Lab canonical backtest API

`/api/research/backtest/*` is the canonical backtest namespace. The old `/api/backtest/*` routes remain available as deprecated legacy wrappers for scripts, older tests, and saved browser state.

Canonical routes:
- `POST /api/research/backtest/runs`
- `GET /api/research/backtest/runs`
- `GET /api/research/backtest/runs/{run_id}`
- `GET /api/research/backtest/runs/{run_id}/trades`
- `GET /api/research/backtest/runs/{run_id}/signals`
- `DELETE /api/research/backtest/runs/{run_id}`
- `GET /api/research/backtest/summary`
- `POST /api/research/backtest/parameter-scan`
- `POST /api/research/backtest/parameter-scan/jobs`
- `GET /api/research/backtest/parameter-scan/jobs/{job_id}`
- `POST /api/research/backtest/parameter-scan/jobs/{job_id}/cancel`
- `GET /api/research/backtest/parameter-scans`
- `POST /api/research/backtest/signalops-sample`
- `POST /api/research/backtest/signalops-experiment`
- `POST /api/research/backtest/signalops-random-validation/jobs`
- `GET /api/research/backtest/signalops-random-validation/jobs/{job_id}`
- `POST /api/research/backtest/signalops-random-validation/jobs/{job_id}/cancel`

`BacktestRequest` and `SignalOpsBacktestSampleRequest` support `reuse_existing` and `force_new`. Defaults are `reuse_existing=true` and `force_new=false`. A completed run with the same stable fingerprint is reused unless `force_new=true`.

The stable fingerprint is stored in `parameters.backtest_fingerprint` and is based on deterministic inputs: symbol, date window, initial capital, patch/case/scenario, signal source/date, SignalOps source/version, benchmark, cost parameters, experiment package hash, and stable hashes for caller-supplied market/signal inputs. It excludes run IDs, timestamps, warnings, UI-only flags, `reuse_existing`, `force_new`, and transient SignalOps context.

When a run is reused, the returned payload includes `parameters.dedupe_reused=true`. Deleting through the API checks Research Lab references first; if an iteration, metrics payload, or evidence link still references the backtest, the API returns HTTP 409 with `detail.message="已被研究证据引用，不能删除"`.

SignalOps experiment validation must still call `record_backtest_experiment_result` even when baseline/candidate walk-forward runs were reused. Review queue status, `BACKTEST_PENDING`, `READY_FOR_REVIEW`, `review_queue_sync_status`, `simulation_only=true`, and `is_real_trade=false` must not be skipped by dedupe.

`POST /api/research/backtest/runs/{run_id}/verdict-inputs` and `POST /api/research/signalops/signals/{signal_id}/evidence` are Research Lab evidence-bridge endpoints. They return the updated `iteration` plus refreshed `verdict_inputs`, and the response root must also expose `evidence_usage="supporting_only"`, `supporting_only=true`, `simulation_only=true`, `is_real_trade=false`, and `strong_conclusion_allowed=false`. These bridge responses may add Backtest or SignalOps evidence to review inputs, but they do not accept a verdict, promote knowledge, place orders, or create real-trade authority; frontend clients must reject missing or contradictory top-level boundary fields.

`POST /api/research/backtest/parameter-scan` accepts optional `windows: [{start,end,label}]`. The runner keeps the existing bounded `max_combinations` cap for parameter combinations and applies those combinations across at most four normalized windows. Generated runs keep `parameters.parameter_scan.window`, `windowIndex`, `windowCount`, `windows`, `combinationIndex`, `combinationCount`, `trialCount`, `simulation_only=true`, and `is_real_trade=false`.

`POST /api/research/backtest/parameter-scan/jobs` queues the same bounded parameter-scan request behind a local durable JSON job surface. `GET /api/research/backtest/parameter-scan/jobs/{job_id}` returns `jobId`, `status`, `progressStep`, original `request`, completed `scan`, `scanId`, `runIds`, `bestRunId`, `totalCombinations`, `totalTrials`, `windowCount`, `queueMode=LOCAL_DURABLE_JSON`, `durable=true`, `recovered`, `recoveredAt`, `recoveryAttemptCount`, `idempotencyKey`, `attemptCount`, `currentAttemptId`, `lastAttemptStatus`, retained `attempts[]`, local lease diagnostics (`leaseOwner`, `leaseId`, `leaseStatus`, `leaseAcquiredAt`, `leaseExpiresAt`, `leaseReleasedAt`, `leaseSeconds`), dynamic `handoffStatus`, `simulationOnly=true`, and `isRealTrade=false`; each attempt includes `attemptId`, `attemptNumber`, `status`, `progressStep`, `startedAt`, `finishedAt`, `error`, `scanId`, `runIds`, `bestRunId`, `idempotencyKey`, `queueMode`, the same lease diagnostics, `recovered`, `recoveryAttemptCount`, `simulationOnly=true`, and `isRealTrade=false`. `handoffStatus` is computed at read time from `BACKTEST_PARAMETER_SCAN_HANDOFF_DIR/shipper_status.json` and latest local handoff manifests, reports `schema=backtest_parameter_scan_job_handoff_shipper_status_v1`, `status`, `provider`, remote/object/retention/search metadata, `matchesLatestHandoff`, `matchesJob`, `searchIndexReady`, and bounded `issues`, and is not persisted into `backtest_parameter_scan_jobs.json` or handoff bundles. A running local attempt holds `leaseStatus=LEASED`; duplicate local runner claims are rejected while that lease is active; terminal completion/failure/cancel releases it as `RELEASED`. `POST /cancel` marks queued/running/recovering local jobs and the current attempt as `CANCELLED`. On backend restart, persisted `QUEUED` jobs are loaded as `RECOVERING` and rescheduled when the job is read; persisted `RUNNING` / `RECOVERING` jobs first mark the old active attempt and lease as `INTERRUPTED` / `EXPIRED`, then schedule a new recovery attempt with the same `idempotencyKey`. This job surface is for local operator responsiveness and browser-visible orchestration only; it is not an external queue, distributed lease service, exactly-once scheduler, strategy promotion path, or real-trade executor.

`POST /api/research/backtest/parameter-scan/jobs/{job_id}/handoff` creates a deployment-side local handoff bundle only for completed simulation-only parameter-scan jobs. Configure `BACKTEST_PARAMETER_SCAN_HANDOFF_DIR` to enable it. Responses use `schema=backtest_parameter_scan_job_handoff_v1` with `status=DISABLED|BLOCKED|FAILED|HANDED_OFF`, `handoffDestination=LOCAL_DEPLOYMENT_HANDOFF_DIR|NOT_CONFIGURED`, `handoffRequiresCompletedJob=true`, `bundleChecksum=bt-parameter-scan-handoff-*`, `manifest.schema=backtest_parameter_scan_job_handoff_manifest_v1`, `retentionPolicy.custody=deployment_owned_after_handoff`, `appendOnly=true`, `simulationOnly=true`, and `isRealTrade=false`. The written bundle uses `schema=backtest_parameter_scan_job_handoff_bundle_v1` and contains the public job, scan result, attempt/lease/idempotency evidence, run ids, best run id, and retention policy. Handoff is a sanitized app-side input for deployment-owned retention tooling; it is not object storage custody, KMS, a distributed queue, a scheduler, strategy promotion, or real-trade execution.

Deployment shippers may write `BACKTEST_PARAMETER_SCAN_HANDOFF_DIR/shipper_status.json` after upload/index/retention checks complete. The expected sidecar schema is `backtest_parameter_scan_job_handoff_shipper_status_v1`; supported statuses are `DELIVERED`, `PENDING`, `FAILED`, and `UNKNOWN`. The app redacts token/secret/authorization-like text before returning the sidecar through `handoffStatus`, compares `lastHandoffId` / `lastBundleChecksum` / `lastJobId` / `lastScanId` against the latest local manifest for that job, and surfaces mismatches as `issues`. This sidecar is status evidence only; deployment remains responsible for actual external upload, KMS/object-storage custody, provider retention, and centralized search.

`GET /api/research/backtest/parameter-scans` returns recent retained bounded parameter scans by grouping generated Backtest runs with `parameters.parameter_scan.scanId`. Optional query params: `symbol`, `limit` (1-100). Each item includes `scan_id`, `status`, `symbol`, aggregate `start_date` / `end_date`, `ranking_metric`, `parameter_grid`, unique `combinations`, retained `windows`, `window_count`, `run_ids`, `best_run_id`, `best_score`, `summary.totalCombinations`, `summary.totalTrials`, `trial_count`, timestamps, and the simulation boundary fields. This is a read-only scan-history view; it does not create async workers, promote strategy evidence, or change trading behavior.

---

## 12. Research Lab 研究循环

Research Lab 使用一等后端对象管理 RD-Agent 风格研究迭代。当前已实现循环、轮次、独立 evidence/feedback 表、跨项目链接字段、受控分析 run 启动、P5 派生资产动作别名，以及 P7 第一批 RD-Agent trace 导入。

### GET /research/summary — 研究循环汇总

返回 loop、iteration、反馈 verdict 和跨项目链接数量。

### GET /research/loops — 研究循环列表

可选 query：

- `status`：`ACTIVE` / `PAUSED` / `COMPLETED`

### POST /research/loops — 创建研究循环

```json
{
  "title": "Factor drift research",
  "objective": "Validate if factor drift explains recent drawdown",
  "hypothesis": "Volume-price divergence improves defensive timing.",
  "plan": "Run guarded analysis, compress evidence, evaluate against paper results.",
  "action_target": "factor",
  "tags": ["factor", "signalops"],
  "target_modules": ["factor_engine", "signalops"],
  "linked_projects": [
    {
      "project": "external-strategy-lab",
      "module": "factor_drift",
      "path": "modules/factor_drift.py",
      "expected_version": "latest-compatible",
      "sync_status": "PENDING",
      "note": "Created from Research Lab"
    }
  ]
}
```

### GET /research/loops/{loop_id} — 研究循环详情

返回 loop 及其 iterations。

### PATCH /research/loops/{loop_id} — 更新研究循环

可更新 `title`、`objective`、`status`、`action_target`、`owner`、`tags`、`linked_projects`。

### POST /research/loops/{loop_id}/archive — 归档研究循环

将 loop 标记为 `ARCHIVED`，并在当前 iteration 上记录归档 feedback event。

### GET /research/iterations — 研究轮次列表

可选 query：

- `loop_id`：按研究循环过滤。

### GET /research/iterations/{iteration_id} — 研究轮次详情

返回单个 research iteration。

### POST /research/loops/{loop_id}/iterations — 追加研究轮次

```json
{
  "hypothesis": "Slippage cap should be stricter for low-liquidity cases.",
  "plan": "Compare execution node results with SignalOps paper fills.",
  "target_modules": ["execution", "signalops"],
  "linked_run_id": "RUN_...",
  "metrics": {
    "baseline_slippage": 0.012
  }
}
```

### PATCH /research/iterations/{iteration_id} — 更新研究轮次

可更新 hypothesis、plan、target_modules、status、verdict、linked_run_id、linked_backtest_id、linked_case_id、linked_knowledge_item_id、linked_patch_id 和 metrics。

### POST /research/iterations/{iteration_id}/attach-run — 挂接分析运行

```json
{
  "run_id": "RUN_...",
  "reviewer": "human",
  "note": "Attached from Research Lab"
}
```

### POST /research/iterations/{iteration_id}/attach-backtest — 挂接回测结果

```json
{
  "backtest_run_id": "BT_...",
  "reviewer": "human",
  "note": "Attached backtest evidence"
}
```

### POST /research/iterations/{iteration_id}/start-run — 创建受控分析 run

创建普通 `/analysis/runs`，自动携带 `research_loop_id` / `research_iteration_id`，并回写 iteration。

```json
{
  "symbol": "603663",
  "task_type": "research_iteration",
  "run_mode": "STANDARD_MODE",
  "scenario_id": "qiam_discounted",
  "user_constraints": {},
  "config_profile_id": "default",
  "auto_start": false
}
```

### POST /research/iterations/{iteration_id}/mfe-mae/backtest - MFE/MAE retry evidence

Retries the MFE/MAE Path Research closure step for a Research Lab iteration. The endpoint reuses the linked run unless `run_id` is provided, creates/reuses a Backtest run with `signal_source=MFE_MAE_PATH_RESEARCH`, and records evidence through the normal feedback/evidence path. The legacy `/bottom-research/backtest` route remains as an alias for saved clients.

Request:

```json
{
  "run_id": "RUN_...",
  "force_new": false,
  "reviewer": "human"
}
```

Response is the updated `ResearchIteration`. Missing iteration or missing run returns `404`. If the run is present but cannot produce usable MFE/MAE Path Research backtest evidence, the endpoint returns `200` with warning metrics instead of `500`; examples include:

- `run_not_linked_to_research_iteration`
- `mfe_mae_research_status_not_usable:MISSING`
- `mfe_mae_research_status_not_usable:SKIPPED`
- `mfe_mae_research_backtest_window_missing`
- `mfe_mae_research_symbol_missing`
- `mfe_mae_research_backtest_error`

Successful closure records one `MFE_MAE_RESEARCH_RUN` evidence link and one `BACKTEST` evidence link. Repeating the retry for the same run/backtest updates existing `research_evidence_links` instead of duplicating them. MFE/MAE evidence remains supporting-only: metrics preserve `mfe_mae_research_supporting_only=true`, legacy `bottom_research_supporting_only=true`, `simulation_only=true`, and `is_real_trade=false`; it may only provide controlled one-step QIAM calibration evidence and must not upgrade DVG, Risk, Execution, or any BUY/ADD/SELL path.

`POST /research/p2/closed-loop-sample` returns a deterministic sample package for browser/acceptance smoke. The response includes `simulation_only=true` and `is_real_trade=false` at top level, plus portfolio/run/signal/backtest/research/case/knowledge/evaluation/knowledge-version IDs when those artifacts are materialized. The endpoint is a sample generator for Research Lab closure validation, not a production trading route.

Research Lab surfaces this closure state as a UI-level health summary rather than a separate API contract. The summary derives from the existing `ResearchIteration`, `ResearchWorkflowState`, linked run, verdict inputs, and evidence links: linked run id, usable Bottom output, linked backtest id/deep link, evidence count, case/knowledge/evaluation ids, blocking reasons, quality warnings, next action, `maturity_score`, `maturity_level`, `maturity_label`, and `maturity_reasons`.

### POST /research/iterations/{iteration_id}/next — 从反馈创建下一轮

根据显式 hypothesis 或上一轮 `next_hypothesis` 创建下一轮 iteration，并在父 iteration 记录 `NEXT_ITERATION_CREATED`。

### POST /research/iterations/{iteration_id}/feedback — 记录研究反馈

```json
{
  "action": "ACCEPT",
  "verdict": "ACCEPTED",
  "note": "Evidence supports the stricter cap.",
  "linked_run_id": "RUN_...",
  "linked_case_id": "CASE_...",
  "metrics": {
    "improvement_rate": 0.25
  }
}
```

当 `verdict=ACCEPTED` 且 P4 verdict inputs 的 `can_accept_feedback=false` 时，接口返回 409，防止低质量或阻塞证据被静默采纳。人工覆盖必须传入：

```json
{
  "override_blocking_reasons": true,
  "override_reason": "Manual research lead override after offline review."
}
```

feedback 与 evidence 会同时写入 `research_feedback_events` 和 `research_evidence_links` 独立表，并保留 `research_iterations` JSON 字段作为兼容镜像。

### GET /research/iterations/{iteration_id}/verdict-inputs - P4 verdict evidence inputs

Optional query:
- `baseline_run_id`: baseline analysis run for comparison.
- `candidate_run_id`: candidate/current analysis run for comparison.

Returns compact evidence and metrics for the Research Lab verdict engine. The response separates the P4 engine verdict from the existing human feedback verdict so machine suggestions do not overwrite manual review.

```json
{
  "iteration_id": "RITER_...",
  "engine_verdict": "ACCEPT",
  "suggested_feedback_verdict": "ACCEPTED",
  "confidence": 0.88,
  "can_accept_feedback": true,
  "blocking_reasons": [],
  "quality_warnings": [],
  "metrics": {
    "quality_score": 88,
    "quality_level": "HIGH",
    "final_action": "BUY_CANDIDATE",
    "qiam_confidence": 0.82,
    "dvg_status": "PASS"
  },
  "comparison": [
    {
      "key": "final",
      "label": "final action",
      "baseline": "WAIT",
      "current": "BUY_CANDIDATE",
      "warning": "decision changed"
    }
  ],
  "evidence": [
    {
      "source_type": "RUN",
      "source_id": "RUN_...",
      "quality": "HIGH",
      "summary": "COMPLETED final_action=BUY_CANDIDATE"
    }
  ]
}
```

`engine_verdict` values: `ACCEPT`, `REJECT`, `NEEDS_MORE_DATA`, `REGRESSED`, `GUARDRAIL_BLOCKED`.

### POST /research/iterations/{iteration_id}/verdict-inputs/refresh - persist P4 evidence snapshot

Recomputes verdict inputs and records a `VERDICT_INPUTS_REFRESHED` feedback event with compact metrics and evidence links. It does not auto-accept or auto-reject the iteration.

### POST /research/iterations/{iteration_id}/artifacts/materialize - P5 closed-loop artifact materializer

Materializes Research Lab P5 assets from one research iteration. The endpoint is idempotent by default: if the iteration already links a case, knowledge item, error entry, patch, or evaluation, the existing asset is reused unless `force=true`. Requests for the same iteration are serialized through a persisted `research_artifact_materializations` lease so rapid repeated clicks or multiple backend workers do not duplicate derived assets. If another worker is still materializing the same iteration and the lease is not stale, the API returns HTTP 409 with a retryable conflict message.

Thin workflow aliases:

- `POST /research/iterations/{iteration_id}/compress-evidence`
- `POST /research/iterations/{iteration_id}/create-case`
- `POST /research/iterations/{iteration_id}/create-knowledge`
- `POST /research/iterations/{iteration_id}/create-patch`
- `POST /research/iterations/{iteration_id}/evaluate`

These routes reuse existing compression/materializer stores and keep provenance on the research iteration.

### P7 RD-Agent trace import

`POST /api/research/traces/preview`

Normalizes an external RD-Agent trace JSON without writing DB records.

`POST /api/research/traces/import`

Normalizes and imports an external RD-Agent trace as a Research Lab loop and iterations. External conclusions are stored as review-only evidence (`external_review_only=true`) and do not auto-accept feedback.

```json
{
  "source_id": "RD_RUN_001",
  "dry_run": false,
  "trace": {
    "trace_id": "RD_RUN_001",
    "title": "Factor RD loop",
    "objective": "Improve defensive timing",
    "iterations": []
  }
}
```

Read endpoints:

- `GET /research/traces`
- `GET /research/traces/{loop_id}`
- `POST /research/imports/rd-agent-trace` compatibility alias for import

### P6 Guided Hypothesis Drafts

`POST /api/research/loops/{loop_id}/hypotheses/draft`

Generates draft hypotheses only. This endpoint never creates a run and never starts analysis execution. It first runs the deterministic action selector, then optionally asks the configured LLM profile to rewrite or add draft language. If the LLM is unavailable, the response still returns rule-based drafts with `llm_status=SKIPPED` or `FAILED`.

`max_drafts` accepts `1..5`. If `iteration_id` is supplied, it must belong to the target loop; otherwise the API returns HTTP 404 instead of falling back to another iteration. `context_metrics` may be flat or nested under `current_metrics`, `current`, `baseline`, and `comparison`; the selector flattens these fields before choosing the action target.

Request:

```json
{
  "iteration_id": "RITER_...",
  "context_metrics": {
    "quality_score": 45,
    "dvg_status": "LOW",
    "slippage": 0.02
  },
  "use_llm": false,
  "llm_profile_id": "default_llm",
  "max_drafts": 3,
  "reviewer": "human"
}
```

Response:

```json
{
  "draft_id": "RHYP_20260520_...",
  "loop_id": "RLOOP_...",
  "iteration_id": "RITER_...",
  "status": "DRAFT_READY",
  "action_selection": {
    "target": "data_quality_rule",
    "rule_id": "P6_DATA_QUALITY_BOTTLENECK",
    "reason": "DVG, evidence quality, or source coverage is the current bottleneck.",
    "confidence": 0.86,
    "evidence": ["dvg_status=LOW", "quality_score=45"]
  },
  "drafts": [
    {
      "hypothesis": "If missing data sources are gated before analysis...",
      "plan": "Run the same hypothesis with required DVG/data-source coverage checks...",
      "action_target": "data_quality_rule",
      "target_modules": ["data_reliability_engine", "guardrail_hub", "knowledge"],
      "rationale": "DVG, evidence quality, or source coverage is the current bottleneck.",
      "source": "RULE"
    }
  ],
  "prompt_provenance": {
    "prompt_version": "research_hypothesis_p6_v1",
    "rule_id": "P6_DATA_QUALITY_BOTTLENECK"
  },
  "token_usage": {},
  "llm_status": "NOT_REQUESTED",
  "llm_error": "",
  "token_usage_link": "/debate",
  "confirmation_required": true,
  "auto_run_started": false,
  "confirmed_iteration_id": null,
  "created_at": "2026-05-20T00:00:00+00:00"
}
```

Compatibility aliases and follow-up routes:

- `POST /api/research/loops/{loop_id}/hypothesis-drafts`
- `GET /api/research/loops/{loop_id}/hypothesis-drafts`
- `GET /api/research/hypothesis-drafts/{draft_id}`
- `POST /api/research/hypothesis-drafts/{draft_id}/confirm`

Confirming a draft creates a research iteration from the selected draft and records `source_draft_id`, `action_target`, selector provenance, token usage, and `auto_run_started=false` in iteration metrics. Repeated confirm calls are idempotent and return the already confirmed iteration.
前端应优先调用 confirm 接口创建下一轮研究；只把 draft 应用到表单属于手工编辑路径，不能保留完整 `source_draft_id` / selector / token usage provenance。

If another worker or repeated click is already confirming the same draft, the API returns HTTP 409 with a retryable conflict message. Invalid `selected_index` values also return HTTP 409 and do not leave the draft stuck in `CONFIRMING`.

Request:

```json
{
  "reviewer": "human",
  "selected_index": 0,
  "note": "Create the next research iteration from this draft."
}
```

Response is the created or previously confirmed `ResearchIteration`. Confirm does not start an analysis run; run execution remains a separate guarded action.

### Config version rollback governance

`GET /api/config/versions?include_external=true` returns external runtime configuration versions with a read-only `rollback_policy`.

External runtime configuration versions are not directly rollbackable from their redacted snapshots. Their policy includes:

- `supported=false`
- `approval_required=true`
- `secret_safe_required=true`
- `blocked_reason=secret_safe_rollback_required`
- `approval_gate.status=BLOCKED_PENDING_VAULT_VERSION_APPROVAL`
- `approval_gate.scope=runtime_config_secret_restore`
- `approval_gate.secret_vault_version_required=true`
- `approval_gate.restore_source=secret_vault_version_refs`
- `approval_gate.required_secret_refs[]` containing public immutable vault references such as `runtime-secret:v1:...:version:...`

`POST /api/config/external-restore` is the approved restore executor for Agent Runtime external config versions. Required request fields:

```json
{
  "profile_id": "agent_runtime:llm_profile",
  "audit_id": "AUD_CFG_AGENT_RUNTIME_LLM_PROFILE_1_...",
  "reason": "Restore reviewed LLM profile",
  "approval_id": "APPROVAL-123",
  "approved_by": "admin-reviewer",
  "confirm_secret_safe": true
}
```

The endpoint requires admin auth, `confirm_secret_safe=true`, `target_version` or `audit_id`, an approval id, and a reason. It applies only the surface-specific runtime keys for the requested Agent Runtime profile id, preserves current values for redacted fields, and restores secret refs only when the config version contains immutable `runtime-secret:v1:...:version:...` refs that can still be opened from the vault. Versions that only contain mutable current aliases remain blocked.

Supported Agent Runtime profile ids:

- `agent_runtime:runtime_settings`
- `agent_runtime:llm_profile`
- `agent_runtime:market_data_profile`
- `agent_runtime:agent_llm_assignment`
- `agent_runtime:data_sources_config`
- `agent_runtime:market_data_adapter_config`

Unsupported external profile ids return 400. `agent_runtime:data_sources_config` restore is scoped to data-source config and matching secret refs; it synchronizes the restored Tushare token into market-data profile token refs so the runtime remains usable, but it does not restore unrelated profile metadata or LLM profiles.

The API must never return plaintext key/token/secret values in config version history or restore responses. This is approved restore, not unattended automatic rollback.

### Cross-module Research Lab links

Research Lab stores derived asset IDs in two places:

- First-class fields on `ResearchIteration`: `linked_run_id`, `linked_case_id`, `linked_knowledge_item_id`, `linked_patch_id`.
- `metrics.artifact_links`: `case_id`, `knowledge_item_id`, `error_entry_id`, `patch_id`, `evaluation_id`.

Verdict inputs must treat `metrics.artifact_links` as a fallback source when a first-class linked field is missing. Linked knowledge candidates are included as `KNOWLEDGE` evidence; `PENDING_REVIEW` knowledge blocks automatic acceptance until reviewed. This keeps the intended chain intact:

```text
hypothesis draft -> research iteration -> analysis run -> compressed summary
-> verdict inputs -> case/knowledge/error/patch/evaluation -> feedback
```

## 12.4 Plugin Artifact Governance

### POST /plugins/{plugin_id}/artifacts

Admin-gated in strict/production auth. Uploads a plugin package artifact for review-only storage; it must not extract archives, import executable code, register higher-permission plugin runtimes, or enable trade actions.

The backend computes a server-side SHA-256 digest, optionally verifies `expected_checksum`, checks the digest against the local known-bad denylist, rejects unsafe upload file names, and stores the artifact under the configured plugin artifact storage root. Configure the local denylist with `TIANYUAN_PLUGIN_ARTIFACT_BLOCKED_SHA256` or `PLUGIN_ARTIFACT_BLOCKED_SHA256`; values may be comma, semicolon, or whitespace separated 64-hex SHA-256 digests, with optional `sha256:` prefix. Zip files are metadata-scanned before persistence. The scanner rejects path traversal entries, absolute paths, invalid zip uploads, too many entries, and excessive uncompressed size. Code-like files inside a valid zip are recorded as warnings because plugin code execution remains disabled.

External malware-scan evidence can be ingested from a sidecar verdict directory before persistence. Configure `TIANYUAN_PLUGIN_ARTIFACT_EXTERNAL_SCAN_DIR` or `PLUGIN_ARTIFACT_EXTERNAL_SCAN_DIR` with JSON verdict files named `{sha256}.json`, `sha256_{sha256}.json`, or `sha256-{sha256}.json`. Set `TIANYUAN_PLUGIN_ARTIFACT_EXTERNAL_SCAN_REQUIRED=1` or `PLUGIN_ARTIFACT_EXTERNAL_SCAN_REQUIRED=1` to reject uploads unless the sidecar verdict is present and returns `PASSED` or `WARN`. `BLOCKED`, `FAILED`, `ERROR`, `blocked=true`, and `malicious=true` verdicts reject the upload before storage. Sidecar JSON is read as BOM-compatible UTF-8, bounded to 64 KiB, and secret-like text is redacted from returned scanner/provider metadata. If the verdict declares `checksum`, `artifact_checksum`, or `sha256`, it must match the uploaded artifact's server-computed `sha256:` checksum or the upload is rejected before storage.

Supported optional verdict metadata includes `schema`, `scanner` / `provider`, `signature_version`, `engine_version`, `definitions_updated_at`, `provider_status`, `threat_intel_status`, `scan_id` / `vendor_scan_id`, `warnings`, and `threats`. The backend returns these inside `external_scan` together with `artifact_checksum` and `matches_artifact_checksum=true`, and Plugin Registry renders provider status, threat-intel status, signature/engine evidence, and checksum-match status in both the upload result and package artifact state.

The response includes `artifact_id`, `checksum`, `verified`, `storage_path`, `hash_scan_status`, `hash_scan`, `scan_status`, `scan_summary`, `scan_warnings`, `scan`, `external_scan_status`, `external_scan_provider`, `external_scan_required`, `external_scan`, `retention_days`, `retention_expires_at`, and `retention_policy`. The same governance metadata is mirrored into the plugin manifest, lifecycle fields, and `ARTIFACT_UPLOAD` audit payload.

This is local metadata, local known-bad hash governance, and external sidecar verdict ingestion only. Production object storage lifecycle rules, managed vendor scanner deployment, live threat-intel feed synchronization, and higher-permission plugin execution sandboxing remain separate acceptance items.

### POST /plugins/artifacts/cleanup

Admin-gated in strict/production auth. Runs retention cleanup over registered uploaded package artifacts. The request defaults to:

```json
{ "dry_run": true, "reason": "" }
```

Dry-run scans manifests and returns expired artifact candidates without deleting files or writing cleanup audit rows. When `dry_run=false`, the backend only deletes files whose registered `storage_path` resolves inside the configured plugin artifact root and whose `retention_expires_at` or `retention_policy.expires_at` is already expired. Unsafe paths, missing files, and non-file paths are reported in `items[]`; path traversal and absolute paths are skipped rather than deleted.

The response includes `status`, `dry_run`, `cleanup_at`, `storage_root`, `scanned_plugin_count`, `expired_count`, `candidate_count`, `would_delete_count`, `deleted_count`, `missing_count`, `skipped_count`, `error_count`, and per-artifact `items[]`. Actual cleanup writes `ARTIFACT_CLEANUP` plugin audit entries and marks matched manifest artifacts with cleanup status.

This endpoint is local filesystem retention cleanup. Production object-storage lifecycle rules and malware scanning remain separate acceptance items.

## 12.5 Operations Alert Channel

### GET /ops/alerts/status

Returns the production alert outbox status. The endpoint is read-only and reports `channel="local_file_outbox"`, `external_delivery_enabled`, `external_provider`, `external_delivery_status`, `external_delivery_attempt_limit`, `external_delivery_retry_backoff_seconds`, `alert_rule_policy`, `external_aggregation_ready`, `export_endpoint`, `export_schema`, `retention_policy`, `redaction_policy`, `handoff_status`, `outbox_file`, `queue_size`, `counts_by_severity`, and `latest[]`.

By default external delivery is disabled and alerts are only recorded locally. When `PRODUCTION_ALERT_WEBHOOK_URL` is set, dispatch attempts a generic JSON webhook delivery for each new alert while still writing the local outbox. `PRODUCTION_ALERT_WEBHOOK_MAX_ATTEMPTS` can opt into bounded synchronous retries and is clamped to `1..5`; `PRODUCTION_ALERT_WEBHOOK_RETRY_BACKOFF_SECONDS` is clamped to `0..5`. Webhook URLs are not returned by the API.

`alert_rule_policy` uses `schema="production_alert_rule_policy_v1"` and is applied when alert events are created. Without configuration it reports `status="DEFAULT"` with built-in local rules for `critical`, `warning`, and `info` severities. `PRODUCTION_ALERT_RULE_POLICY_FILE` can point to a BOM-compatible JSON sidecar with the same schema and `rules[]` entries containing `id`, `severity`, `metric`, `routing_key`, `escalation_target`, and `dedupe_window_seconds`; invalid or missing sidecars fall back to the built-in local policy and report `INVALID` / `NOT_REPORTED`. `alert_rule_policy.provider_acceptance` is a read-only deployment sidecar status loaded from `PRODUCTION_ALERT_RULE_PROVIDER_ACCEPTANCE_FILE` when configured. That sidecar must use `schema="production_alert_rule_provider_acceptance_v1"` and may report provider acceptance status, provider policy id, accepted/total rule counts, accepted rule ids, last sync time, routing key, message, and issues; the API redacts secret-like text and reports whether the sidecar policy id/rule count/rule ids match the current app-side policy. Each recorded event includes `alert_rule_policy_schema`, `alert_rule_policy_status`, `alert_rule_source`, `alert_rule_provider`, `alert_rule_id`, `alert_routing_key`, `alert_escalation_target`, and `alert_dedupe_window_seconds`. This is app-side routing metadata plus deployment-reported provider acceptance evidence; it still does not deploy vendor alert rules, deliver alerts centrally, or create provider retention by itself.

`handoff_status` uses `schema="production_alert_outbox_export_handoff_status_v1"` and reports whether `PRODUCTION_ALERT_EXPORT_HANDOFF_DIR` is configured, whether the handoff path or parent appears writable, the expected bundle/manifest schema, and whether the directory will be created on handoff. It also includes `inventory` with `schema="production_alert_outbox_export_handoff_inventory_v1"`, bounded manifest scan counts, verified bundle count, missing bundle count, checksum mismatch count, invalid manifest count, latest handoff id/time, latest bundle checksum, and short issue strings. `shipper_status` is a read-only deployment sidecar status loaded from `PRODUCTION_ALERT_EXPORT_HANDOFF_DIR/shipper_status.json` when present. That sidecar must use `schema="production_alert_outbox_export_shipper_status_v1"` and may report `status`, `reported_at`, `source`, `provider`, `remote_destination`, `remote_object_key`, `retention_policy_id`, `retention_status`, `custody_status`, `kms_key_ref`, `search_index`, `search_index_ready`, `last_handoff_id`, `last_bundle_checksum`, and `message`; the API sanitizes secret-like values, supports BOM-compatible JSON, reports whether the sidecar matches the latest local inventory, and surfaces provider-side index/search readiness plus retention/custody evidence as deployment-reported status only. This is a local readiness/integrity/deployment-reported health hint for alert shippers, not proof of external provider ingestion, centralized alert/search ownership, provider retention enforcement, or KMS/object-storage custody.

### POST /ops/alerts/dispatch

Admin-gated in strict/production auth. It snapshots current `/api/metrics.productionHealth.alerts`, redacts secret-like text, de-duplicates by alert fingerprint, optionally delivers new alerts through `PRODUCTION_ALERT_WEBHOOK_URL`, and records new events into `backend/app/storage/production_alerts.jsonl` by default or `PRODUCTION_ALERT_OUTBOX_FILE` when set.

Each event includes `delivery_status` (`recorded`, `delivered`, or `failed`), `external_delivery`, `external_provider`, `delivery_attempted_at`, `delivery_attempt_count`, `delivery_attempt_limit`, alert rule/routing metadata, and redacted `delivery_error` when delivery fails. Webhook delivery failures do not block local outbox persistence.

The response includes `dispatched`, `deduplicated`, `events[]`, and updated `status`. It must not enable real trading, plugin code execution, or external network delivery.

### GET /ops/alerts/export

Returns a bounded export bundle for the local production alert outbox. Query parameters:

- `limit`: optional, `1..1000`, default `100`.

Response fields include `schema="production_alert_outbox_export_v1"`, `channel="local_file_outbox_export"`, `source_channel="local_file_outbox"`, `external_delivery_enabled`, `external_provider`, `external_delivery_status`, `alert_rule_policy`, `external_aggregation_ready=true`, `export_endpoint`, `export_schema`, `outbox_file`, `event_count`, `total_event_count`, `exported_count`, `checksum`, `retention_policy`, `redaction_policy`, and `events[]`.

`checksum` is a SHA-256 digest over the exported `events[]` payload. Exported events are the same sanitized alert records used by `/ops/alerts/status`: secret-like text is redacted, webhook URLs are not returned, and payloads must not include request headers or raw provider credentials. This endpoint is intended for local sidecar ingestion into deployment-managed alert/log aggregation; it does not push alerts to a vendor provider by itself.

### POST /ops/alerts/export/handoff

Admin-gated in strict/production auth. Writes a bounded sanitized production-alert export bundle and companion manifest into the deployment-configured handoff directory. Query parameters match `GET /ops/alerts/export`: `limit`.

Set `PRODUCTION_ALERT_EXPORT_HANDOFF_DIR` to enable the local file handoff. When the variable is not configured, the endpoint returns `schema="production_alert_outbox_export_handoff_v1"`, `status="DISABLED"`, `handoff_destination="NOT_CONFIGURED"`, and does not write bundle or manifest files.

When enabled, the response returns `status="HANDED_OFF"`, `handoff_destination="LOCAL_DEPLOYMENT_HANDOFF_DIR"`, `bundle_checksum`, `bundle_file`, `manifest_file`, and `manifest`. The manifest uses `schema="production_alert_outbox_export_handoff_manifest_v1"` and includes `alert_rule_policy`, `retention_policy.custody="deployment_owned_after_handoff"`, and `requires_sanitized_export=true`. This creates a deployment-side local handoff input for alert/log shippers; it does not add centralized alert delivery, long-term provider retention, or KMS/object-storage custody by itself.

## 12.6 Operations Event Log

### GET /metrics

Returns read-only local runtime and production-health diagnostics. It does not trigger live LLM calls, market-data calls, SignalOps ticks, backtests, or trading actions.

`productionHealth.windows[*].llmCallFailureRate` is sourced from retained run `llmTrace` records and includes:

- `total`: completed plus failed provider-backed LLM calls in the window; skipped/degraded/not-requested calls are counted separately.
- `succeeded`, `failed`, and `skipped`.
- `successRate`: `succeeded / total`, or `null` when no completed/failed LLM calls exist.
- `failureRate`: `failed / total`, or `null` when no completed/failed LLM calls exist.
- `totalTokens`: provider-reported total tokens from counted traces.
- `failureReasons[]`: bounded redacted reason/count pairs.
- `sampleFailures[]`: bounded redacted `{ runId, node, status, reason }` samples.

`productionHealth.windows` includes the primary `24h` window, the `7d` baseline, and the longer `30d` baseline by default. `productionHealth.trend` compares the primary window, normally `24h`, against `baselineWindow`, normally `7d`. `productionHealth.longTrend` compares the same primary window against `baselineWindow="30d"`. Both trend objects include read-only deltas such as `runSuccessRateDelta`, `llmSuccessRateDelta`, `llmFailureRateDelta`, `marketDataFallbackRateDelta`, and `signalOpsTickSuccessRateDelta`. Dashboard uses this to show LLM live-call success/failure trend evidence, and Backend Status renders the same delta fields through `backend-production-health-trend-deltas`, without recalculating from raw runs.

Dashboard and Backend Status consume this same payload for LLM live-call visibility. Secret-like text in failure reasons must stay redacted. The path is observability-only and keeps `externalCalls=false`.

### GET /ops/logs/status

Returns the local structured ops event log status. Query parameters:

- `limit`: optional, `0..100`, default `20`.
- `level`: optional filter for `debug`, `info`, `warning`, `error`, or `critical`.

Response fields include `channel="local_file_jsonl"`, `external_delivery_enabled=false`, `external_aggregation_ready`, `query_endpoint`, `query_schema`, `export_endpoint`, `export_schema`, `log_file`, `event_count`, `counts_by_level`, `counts_by_type`, `retention_policy`, `redaction_policy`, `handoff_status`, and `latest[]`.

`retention_policy` includes:

```json
{
  "mode": "local_bounded_event_count_and_age",
  "max_events": 1000,
  "time_based_retention_enabled": true,
  "max_age_days": 30,
  "prune_on_read_or_write": true
}
```

By default `time_based_retention_enabled=false` and only the bounded event-count cap is active. Set `OPS_LOG_RETENTION_DAYS` or `TIANYUAN_OPS_LOG_RETENTION_DAYS` to enable local JSONL time pruning; invalid, zero, or negative values disable it.

`handoff_status` uses `schema="ops_log_export_handoff_status_v1"` and reports whether `OPS_LOG_EXPORT_HANDOFF_DIR` is configured, whether the handoff path or parent appears writable, the expected bundle/manifest schema, and whether the directory will be created on handoff. It also includes `inventory` with `schema="ops_log_export_handoff_inventory_v1"`, bounded manifest scan counts, verified bundle count, missing bundle count, checksum mismatch count, invalid manifest count, latest handoff id/time, latest bundle checksum, and short issue strings. `shipper_status` is a read-only deployment sidecar status loaded from `OPS_LOG_EXPORT_HANDOFF_DIR/shipper_status.json` when present. That sidecar must use `schema="ops_log_export_shipper_status_v1"` and may report `status`, `reported_at`, `source`, `provider`, `remote_destination`, `remote_object_key`, `retention_policy_id`, `retention_status`, `custody_status`, `kms_key_ref`, `search_index`, `search_index_ready`, `last_handoff_id`, `last_bundle_checksum`, and `message`; the API sanitizes secret-like values, supports BOM-compatible JSON, reports whether the sidecar matches the latest local inventory, and surfaces provider-side index/search readiness plus retention/custody evidence as deployment-reported status only. This is a local readiness/integrity/deployment-reported health hint for log shippers, not proof of external upload, centralized search ownership, provider retention enforcement, or KMS/object-storage custody.

`latest[]` events can include `http_request` and `production_alert_dispatch`. Request events include request id, method, path without query string, status code, duration, and client host. They must not include request headers, authorization values, request bodies, or query strings. The default file is `backend/app/storage/ops_events.jsonl`; deployments can override it with `OPS_LOG_FILE`.

This endpoint is a local observability surface and does not provide centralized search or external log delivery by itself. `external_aggregation_ready=true` means a bounded sanitized export contract is available for a deployment-side sidecar; it does not mean a vendor aggregator is configured.

### GET /ops/logs/query

Returns a bounded read-only query result over the local structured ops event log. Query parameters:

- `limit`: optional, `0..200`, default `20`.
- `level`: optional filter for `debug`, `info`, `warning`, `error`, or `critical`.
- `event_type`: optional exact event-type filter such as `http_request` or `production_alert_dispatch`.
- `source`: optional exact source filter such as `api` or `ops_alerts`.
- `text`: optional case-insensitive search over sanitized event id, time, type, level, source, request id, method, path, status, message, and context.
- `since`: optional ISO timestamp. Invalid values are ignored.

Response fields include `schema="ops_log_query_v1"`, `channel="local_file_jsonl_query"`, `source_channel="local_file_jsonl"`, `external_delivery_enabled=false`, `external_aggregation_ready=true`, `log_file`, `event_count`, `matched_count`, `returned_count`, `limit`, `level_filter`, `event_type_filter`, `source_filter`, `text_filter`, `since`, `retention_policy`, `redaction_policy`, and newest-first `events[]`.

Returned events use the same sanitized event shape as `/ops/logs/status` and `/ops/logs/export`; request paths exclude query strings, and events must not include request headers, authorization values, request bodies, or raw query strings. This is a local structured query helper for operator diagnostics and smoke verification. It is not a deployed centralized log/search service, external index, or provider-retention guarantee.

### GET /ops/logs/export

Returns a bounded export bundle for the local structured ops event log. Query parameters:

- `limit`: optional, `1..1000`, default `100`.
- `level`: optional filter for `debug`, `info`, `warning`, `error`, or `critical`.
- `since`: optional ISO timestamp. Invalid values are ignored.

Response fields include `schema="ops_log_export_v1"`, `channel="local_file_jsonl_export"`, `source_channel="local_file_jsonl"`, `external_delivery_enabled=false`, `external_aggregation_ready=true`, `log_file`, `event_count`, `exported_count`, `level_filter`, `since`, `checksum`, `retention_policy`, `redaction_policy`, and `events[]`.

Exports read cold archive batches, durable pending cold records, and the hot JSONL window. `event_count` counts this combined history. The `level` and inclusive `since` filters apply before taking the last `limit` matching records in persisted history order. The bundle cap is 1000 events, independent of `OPS_LOG_MAX_EVENTS`; it is a bounded window, not a paginated or unlimited export. Historical reads currently load the combined history into memory. A missing or corrupt referenced archive fails the export rather than returning a partial hot-only bundle.

`checksum` is a SHA-256 digest over the exported `events[]` payload. Exported events are the same sanitized records used by `/ops/logs/status`: request path excludes query strings, and events must not include request headers, authorization values, request bodies, or raw query strings. This endpoint is intended for local sidecar ingestion into deployment-managed centralized logging; it does not push logs to an external provider by itself.

### POST /ops/logs/export/handoff

Writes a bounded sanitized ops-log export bundle and companion manifest into the deployment-configured handoff directory. Query parameters match `GET /ops/logs/export`: `limit`, `level`, and `since`.

The handoff uses the same archive-inclusive export, filters, and 1000-event cap. Its manifest counts and checksum describe the saved bundle. Archive read failures occur before handoff files are created.

Set `OPS_LOG_EXPORT_HANDOFF_DIR` to enable the local file handoff. When the variable is not configured, the endpoint returns `schema="ops_log_export_handoff_v1"`, `status="DISABLED"`, `handoff_destination="NOT_CONFIGURED"`, and does not write bundle or manifest files.

When enabled, the response returns `status="HANDED_OFF"`, `handoff_destination="LOCAL_DEPLOYMENT_HANDOFF_DIR"`, `bundle_checksum`, `bundle_file`, `manifest_file`, and `manifest`. The manifest uses `schema="ops_log_export_handoff_manifest_v1"` and includes `retention_policy.custody="deployment_owned_after_handoff"` plus `requires_sanitized_export=true`. The response keeps `external_delivery_enabled=false`: this is a deployment-side local handoff contract, not vendor log shipping, centralized search, or long-term provider retention by itself.

---

## 错误返回格式

```json
{
  "detail": "Run not found"
}
```

HTTP 状态码：400 (参数错误), 404 (未找到), 500 (服务器错误)

## 数据一致性
- audit_id 贯穿所有表
- 前端字段缺失不白屏（使用 optional chaining + fallback）
- Adapter 失败时降级返回，不抛异常
- Mock 数据明确标记 data_mode
## Analysis Job Attempt Diagnostics

`GET /analysis/jobs/attempts` is a read-only operator diagnostic endpoint over the SQLite `analysis_job_attempts` mirror. It does not start, retry, cancel, or mutate jobs.

Query parameters:
- `run_id` optional; when present, attempts are returned in attempt order for that run.
- `status` optional and repeatable, for example `?status=FAILED&status=STALE`.
- `limit` optional, `1..200`, default `100`.
- `offset` optional, `0..10000`, default `0`. Use it with `limit` for bounded retry-history pagination.

Response:
```json
[
  {
    "run_id": "RUN_...",
    "job_id": "JOB_RUN_..._2",
    "attempt": 2,
    "status": "QUEUED",
    "queue_name": "analysis",
    "concurrency_group": "analysis",
    "worker_id": "worker-a",
    "worker_heartbeat_at": "2026-05-31T07:20:00+00:00",
    "lease_status": "ACTIVE",
    "lease_expires_at": "2026-05-31T07:21:00+00:00",
    "lease_seconds": 60,
    "retry_from_node_id": "risk_gate",
    "failed_node_id": "",
    "last_error": "",
    "created_at": "2026-05-31T07:18:00+00:00",
    "updated_at": "2026-05-31T07:20:00+00:00",
    "history": []
  }
]
```

`GET /analysis/jobs` returns the same lease metadata for the current job row. It accepts `limit` (`1..200`, default `100`), `offset` (`0..10000`, default `0`), and repeatable `status` filters such as `?status=QUEUED&status=RUNNING` so operator UIs can page and filter the local diagnostic mirror without loading an unbounded queue history. The lease fields are local SQLite worker ownership metadata: `ACTIVE` / `EXPIRED` describes whether the most recent heartbeat is still within the configured local lease window, `UNCLAIMED` describes queued jobs, and `RELEASED` describes terminal jobs. Worker-owned heartbeat and terminal updates that provide a different `worker_id` are rejected without overwriting the current job row. This is still not a production external queue or distributed lease service; it is a local owner guard for the SQLite/JSON worker path.

`GET /analysis/jobs/summary` returns read-only queue counts for the same local mirror and accepts the same `limit`, `offset`, and repeatable `status` filters. Response fields:

```json
{
  "generated_at": "2026-06-01T11:44:00+00:00",
  "total_count": 42,
  "filtered_count": 7,
  "counts_by_status": {
    "QUEUED": 2,
    "RUNNING": 1,
    "COMPLETED": 36,
    "FAILED": 3
  },
  "statuses": ["QUEUED", "RUNNING"],
  "limit": 12,
  "offset": 0,
  "has_more": false,
  "source": "sqlite",
  "external_queue_status": {
    "schema": "analysis_job_external_queue_status_v1",
    "checked": true,
    "reported": true,
    "status": "READY",
    "provider": "redis",
    "queue_name": "analysis",
    "lease_backend": "redlock",
    "active_workers": 2,
    "pending_jobs": 0,
    "running_jobs": 1,
    "local_queue_mode": "LOCAL_JSON_SQLITE_DIAGNOSTIC"
  }
}
```

`counts_by_status` is calculated across the local mirror, while `filtered_count` and `has_more` honor the requested status filter. If SQLite is temporarily locked, the backend may fall back to JSON state and marks `source` accordingly.

`external_queue_status` is a read-only deployment sidecar status. When `TIANYUAN_ANALYSIS_JOB_EXTERNAL_QUEUE_STATUS_FILE` or `ANALYSIS_JOB_EXTERNAL_QUEUE_STATUS_FILE` points to a JSON file with `schema="analysis_job_external_queue_status_v1"`, the backend reports deployment-owned queue/lease health fields such as `status`, `provider`, `queue_name`, `lease_backend`, `claim_backend`, `claim_status`, `idempotency_scope`, `audit_stream`, `dead_letter_queue`, `dead_letter_count`, `visibility_timeout_seconds`, `lease_renewal_status`, `worker_pool`, worker/job counts, `message`, and `issues`. Missing env returns `NOT_CONFIGURED`; missing file returns `NOT_REPORTED`; invalid JSON/schema returns `INVALID`; secret-like text is redacted. This does not change local JSON/SQLite worker execution, queue claiming, retry creation, or trading behavior, and it is not proof that the app owns an external queue.

If the SQLite mirror is disabled, clients should treat an empty response as diagnostics unavailable, not as proof that no job attempts ever existed. If the SQLite mirror is temporarily locked, the backend falls back to the local JSON job store and returns the current job as a best-effort attempt row with lease/status/history fields. That fallback may not contain the full retry history that `analysis_job_attempts` stores, but it keeps Backend Status from rendering an empty filtered attempt set during transient SQLite lock contention. Backend Status consumes this endpoint to render recent retry/worker/failure history.

## 12.7 Data Reliability Engine adapter events

`GET /api/data-reliability/snapshot` includes two diagnostic arrays:

- `history`: recent persisted `DataHealthCheckDB` rows, including `fallbackUsed`, `upstreamHealthy`, `liveDataUsable`, latency, diagnosis, and check status. The ORM/table names are historical compatibility names; the product module is Data Reliability Engine.
- `events`: recent persisted `DataAdapterEventDB` rows derived from the same explicit adapter or symbol checks. Event types include `ADAPTER_READY`, `ADAPTER_PARTIAL`, `ADAPTER_FAILED`, `SOURCE_READY`, `SOURCE_FALLBACK`, `SOURCE_FAILED`, and `SOURCE_SKIPPED`.

`GET /api/data-reliability/events?limit=50` returns the same event shape as a standalone read-only diagnostic endpoint. `limit` is capped at 200.

`GET /api/data-reliability/snapshot` also includes `externalMonitorStatus`, a read-only deployment sidecar status. When `TIANYUAN_DATA_RELIABILITY_EXTERNAL_MONITOR_STATUS_FILE` or `DATA_RELIABILITY_EXTERNAL_MONITOR_STATUS_FILE` points at a JSON sidecar with `schema=data_reliability_external_monitor_status_v1`, the backend validates the schema, accepts BOM-compatible JSON, bounds the read to 64 KiB, redacts secret-like text, and reports deployment-provided monitoring, retention, incident, and search-index readiness fields. Missing configuration returns `status=NOT_CONFIGURED`; configured but missing files return `status=NOT_REPORTED`; invalid payloads return `status=INVALID`.

```json
{
  "externalMonitorStatus": {
    "schema": "data_reliability_external_monitor_status_v1",
    "checked": true,
    "reported": true,
    "status": "DEGRADED",
    "provider": "provider-monitor",
    "monitorBackend": "prometheus",
    "monitorStatus": "LATENCY_ELEVATED",
    "freshnessStatus": "STALE_SOURCE_WINDOW",
    "retentionPolicyId": "retention-90d",
    "retentionStatus": "ENFORCED",
    "retentionDays": 90,
    "outageCount": 1,
    "degradedSourceCount": 2,
    "staleSourceCount": 3,
    "latencyP95Ms": 1440,
    "searchIndex": "data-reliability-index",
    "searchIndexReady": true,
    "deploymentReported": true,
    "localEventTrail": "DataAdapterEventDB",
    "issues": ["latency_above_slo"]
  }
}
```

```json
[
  {
    "id": 201,
    "symbol": "603663",
    "adapterId": "akshare",
    "provider": "akshare",
    "category": "realtime_quote",
    "eventType": "SOURCE_FALLBACK",
    "status": "PARTIAL",
    "healthy": true,
    "fallbackUsed": true,
    "upstreamHealthy": true,
    "liveDataUsable": false,
    "latencyMs": 177,
    "recordCount": 1,
    "message": "Realtime upstream healthy, but latest live quote fell back to sina.",
    "error": "",
    "diagnosis": "PARTIAL_UPSTREAM",
    "createdAt": "2026-06-01T12:00:00+00:00"
  }
]
```

`DataAdapterEventDB` is a local audit trail for operator review. `externalMonitorStatus` is deployment-reported visibility only; it does not make the app own external provider monitoring, long-term production retention, centralized observability storage, or provider search lifecycle.
