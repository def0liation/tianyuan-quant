# Agent Registry

当前 Agent 列表由 `backend/app/core/agent_framework.py` 中的 `AGENT_MANIFEST` 和
`RUN_MODE_NODES` 统一注册。当前活跃 manifest 是 8 个 Agent。

“量化核心”是本次合并后的用户可见名称；代码 canonical ID 为 `quant_core`。
旧的市场状态、K 线技术面、旧研究节点、Quant/QIAM 和情景引擎节点不再作为活跃 DAG
节点运行，统一通过 `CONSOLIDATED_AGENT_REDIRECTS` 重定向到 `quant_core`。
`guardrail_hub` 是 DVG、Risk、Trade Micro 的唯一活跃护栏节点；旧
`dvg_gate`、`risk_firewall`、`trade_micro`、`atrade` 仅作为 alias、历史读取、
修复和 retry 映射保留。

## Run Modes

### FAST_MODE (5)

```text
orchestrator -> data_reliability_engine -> guardrail_hub -> quant_core -> final_writer
```

### STANDARD_MODE (8)

```text
orchestrator -> data_reliability_engine -> guardrail_hub -> quant_core -> execution
-> anti_conclusion -> signalops -> final_writer
```

### DEEP_MODE (8)

```text
orchestrator -> data_reliability_engine -> guardrail_hub -> quant_core -> execution
-> anti_conclusion -> signalops -> final_writer
```

## Quant Engine Modes

`runMode` 只控制 DAG 编排深度；Quant/QIAM 的交易周期仍由 `quantEngineMode`
单独控制，不拆分 DAG。

| Mode | Default task | Behavior |
|------|--------------|----------|
| `HIGH_FREQ_SHORT` | 交易机会发现 | 偏重 Momentum、Liquidity、Volatility；DVG 使用高频交易门禁；Level-2、盘口深度、分时、逐笔、资金流缺失参与门禁和 QIAM 折扣。 |
| `LOW_FREQ_MID_LONG` | 持仓复核、风险排查 | 偏重 Value、Quality/Fundamental、中期 Momentum、Volatility；高频缺失记录为 `ignoredMissingData`，不直接压低 QIAM。 |

## Active Agents

| # | Agent ID | Name | Responsibilities |
|---|----------|------|------------------|
| 1 | `orchestrator` | Orchestrator | Routing, state validation, tool budget, hard stops |
| 2 | `data_reliability_engine` | 数据可靠性引擎 | Market data, source health, adapter availability, freshness, fallback, external monitor evidence, positions, chip data, prior context |
| 3 | `guardrail_hub` | Guardrail Hub | Canonical DVG, risk/firewall, kill switch, trade microstructure, execution reachability; mirrors `dvg/risk/atrade/killSwitch` |
| 4 | `quant_core` | 量化核心 | Fused market state, K-line technical evidence, MFE/MAE Path Research, Quant/QIAM, Scenario Engine, and read-only `coreInterpretation`; writes `run.quantCore`, `run.mfeMaeResearch`, and legacy mirrors |
| 5 | `execution` | Execution | Manual execution review path and forbidden actions |
| 6 | `anti_conclusion` | Anti-Conclusion | Premature conclusion and semantic drift review |
| 7 | `signalops` | SignalOps | Lifecycle, automatic paper stock pool, SIM order log, review, error ledger |
| 8 | `final_writer` | Final Writer | Bounded final output, meta-review, state serialization |

## Consolidated Legacy IDs

| Legacy Agent ID | Active owner |
|-----------------|--------------|
| `router` | `orchestrator` |
| `state_validation` | `orchestrator` |
| `data_fetch` | `data_reliability_engine` |
| `data_engine` | `data_reliability_engine` |
| `chip_kb` | `data_reliability_engine` |
| `memory_agent` | `data_reliability_engine` |
| `dvg_evidence_gate` | `guardrail_hub` |
| `dvg_gate` | `guardrail_hub` |
| `hallucination_guardrail` | `guardrail_hub` |
| `risk_firewall` | `guardrail_hub` |
| `flash_crash` | `guardrail_hub` |
| `atrade` | `guardrail_hub` |
| `trade_micro` | `guardrail_hub` |
| `portfolio` | `guardrail_hub` |
| `sector_rotation` | `quant_core` |
| `market_regime` | `quant_core` |
| `technical_kline_analyst` | `quant_core` |
| `market_technical_analyst` | `quant_core` |
| `bottom_research` | `quant_core` |
| `factor_slicing` | `quant_core` |
| `factor_engine` | `quant_core` |
| `calculation_authority` | `quant_core` |
| `qiam` | `quant_core` |
| `quant_engine` | `quant_core` |
| `scenario_engine` | `quant_core` |
| `simulation_agent` | `quant_core` |
| `paper_trading_agent` | `signalops` |
| `review_agent` | `signalops` |
| `error_ledger` | `signalops` |
| `meta_agent` | `final_writer` |
| `meta_review` | `final_writer` |
| `state_serialization` | `final_writer` |

## Compatibility Rules

- New canonical output is `run.quantCore` / `AnalysisRun.quantCore`.
- `run.quantCore.coreInterpretation` is a deterministic, read-only interpretation layer
  (`actionBoundary=READ_ONLY_NO_PERMISSION_CHANGE`); it can be used by the UI and
  final context, but it must not change QIAM, SignalOps, Execution, or `finalAction`.
- Current research output is `mfeMaeResearch`; `bottomResearch` remains populated as
  a legacy mirror when data exists.
- Legacy public fields remain populated when data exists: `marketTechnical`, `market`,
  `technicalKline`, `bottomResearch`, `factorSlicing`, `factorEngine`,
  `calculationAuthority`, `quantEngine`, `qiam`, and old `agentOutputs`.
- Retry, plugin insertion anchors, runtime redirects, and DAG display should canonicalize
  legacy market/technical/bottom/quant/scenario IDs to `quant_core`.
- Do not re-add the old chain as active DAG nodes unless a future migration explicitly
  changes the canonical owner.
