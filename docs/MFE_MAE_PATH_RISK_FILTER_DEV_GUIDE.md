# MFE/MAE Path Risk Filter Development Guide

## Development Goal

Integrate the MFE/MAE conditional path-distribution research as a read-only path risk filter inside `quant_core`.
The first implementation must help explain downside path risk, risk acceleration, and position-risk constraints.
It must not present the model as a deterministic upside predictor.
The active research node now uses MFE/MAE Path Research semantics; legacy `bottomResearch` names may exist only as compatibility mirrors for historical runs and old clients.

## Non-Goals

- No live trading enablement.
- No trade permission changes.
- No QIAM suitability mutation.
- No Execution, SignalOps, or finalAction mutation.
- No persisted ML model, real Level-2/order-book dependency, or deterministic price target.
- No database migration.
- No new market-data fetch inside `quant_core`.

## Phase 1 Output Contract

The runtime output is `coreInterpretation.pathRiskFilter`.

Required fields:

- `version = "mfe_mae_path_risk_filter_v1"`
- `status = "READY" | "INSUFFICIENT_DATA"`
- `method = "daily_proxy_no_future_labels_v1"`
- `horizonDays = 20`
- `mfeMaeProxy`
- `riskCurve`
- `downsideRiskScore`
- `maxRiskGradient`
- `riskPolicy`
- `evidence`
- `warnings`
- `limitations`
- `provenance`

Runtime MFE/MAE fields must use proxy naming: `mfeProxy`, `maeProxy`, and `riskRewardProxy`.
Do not name runtime proxy values as `Q90(MFE)`, `Q90(MAE)`, or conditional quantile predictions.
Historical empirical Q50/Q80/Q90 diagnostics may only appear under `modelDiagnostics.conditionalQuantileEvaluation`.

## Active Research Output Contract

The active research payload is `run.mfeMaeResearch` / `quantCore.mfeMaeResearch`.

- `researchType = "MFE_MAE_PATH_RESEARCH"`
- `agent = "mfe_mae_path_research"`
- `mfeFavorableProbability`, `maeBreachProbability`
- `mfeProxy`, `maeProxy`, `riskRewardProxy`
- `mfeMaeFormulaConfig`
- `marketProfile`
- `modelDiagnostics.mfeMaePathRiskEvaluation`
- `modelDiagnostics.conditionalQuantileEvaluation`
- `actionBoundary`, `labelStatus`, `sampleQuality`, `leakagePolicy`
- `simulation_only = true`, `is_real_trade = false`

`bottomResearch`, `BOTTOM_RESEARCH`, and `/bottom-research/*` are legacy aliases only.
Non-`LIVE` daily payloads, including mock/fallback fixtures with rows, must degrade to supporting-only instead of producing a ready research result.

## Data Inputs

Read only existing run payload fields:

- `technicalKline.trend`
- `technicalKline.volumePrice`
- `technicalKline.supportResistance`
- `technicalKline.chipAnalysis`
- `technicalKline.dataQuality`
- `marketTechnical.market`
- `qiam`
- `dvg`

`technicalKline.dataQuality` is used only for `LIVE` / `dailyCount` sufficiency checks.
It must not be used to change permissions, mutate QIAM, or infer a trade action.

Do not re-fetch K-line data or call external data adapters from the path risk filter.
Missing Level-2, real order flow, full chip distribution, or valuation data must be expressed as warnings or limitations.

## Formula And Market Adaptation

Historical labels must use train-before-test windows:

- `mfeLabel = max(high[t+1:t+H]) / close[t] - 1`
- `maeLabel = min(low[t+1:t+H]) / close[t] - 1`
- `maeAbsLabel = abs(min(0, maeLabel))`
- `riskRewardLabel = mfeLabel / (maeAbsLabel + epsilon)`

The latest trade date is always `UNLABELED_NOWCAST` and must not enter Rank IC, quantile coverage, or training windows.

A-share adaptation must account for daily limit boards, T+1 exits, 100-share lots, and board-specific limit widths. Hong Kong adaptation must account for no daily price-limit tail risk, liquidity gaps, and unknown board-lot constraints as review-only limitations. US/ETF and Japan profiles must expose independent thresholds, sample transferability status, and missing external data reasons.

`modelDiagnostics.conditionalQuantileEvaluation` uses `walk_forward_empirical_conditioned_quantile_v1`: every fold trains only on earlier labeled records, creates entry-day proxy buckets inside the training window, and reports MFE/MAE/RiskReward Q50/Q80/Q90 coverage plus Rank IC. It remains research-only with `actionBoundary=RESEARCH_ONLY_NO_PERMISSION_CHANGE`, `simulation_only=true`, and `is_real_trade=false`.

## Read-Only Boundary

The filter must preserve `READ_ONLY_NO_PERMISSION_CHANGE`.
It may add explanatory dimensions, conflicts, risk flags, and UI display content.
It must not mutate:

- `run.qiam.finalBuySuitability`
- `run.execution.allowedActions`
- `run.signalOps`
- `run.finalAction`
- `prior_outputs["qiam"]`
- `prior_outputs["quant_engine"]`

## Acceptance Commands

Run focused checks after implementation:

```powershell
.\.venv\Scripts\python.exe -m py_compile backend\app\modules\quant_core.py backend\app\core\agent_framework.py backend\app\core\mfe_mae_path_risk_research.py backend\app\core\bottom_research.py
npm.cmd run smoke:mfe-mae-quant-core
npm.cmd run test:backend -- backend\tests\test_agent_executor.py -q
npm.cmd run typecheck
npm.cmd run lint
npm.cmd run build
```

Optional baseline gate:

```powershell
npm.cmd run audit:baseline
```

## Completion Reply Rule

Every completed task response must end with:

```text
主人，任务完成了喵
```
