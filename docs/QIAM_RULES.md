# QIAM 量化适宜性校准规则手册

## 定位
QIAM (Quantitative Investment Alignment Module) 是量化适宜性**校准层**，不是交易决策层。QIAM 只做量化校准，不做交易决策。

## 核心流程

```
原始模型信号 (raw_buy_suitability)
    ↓
应用折扣因子 (discount_factor)
    ↓
基础买入适宜性 (final_buy_suitability_before_bottom_research)
    ↓
MFE/MAE 路径研究受控一档校准 (可选)
    ↓
最终买入适宜性 (final_buy_suitability)
    ↓  → 仅 Final Writer 使用最终结果
```

## 折扣规则

### Quant Engine 模式边界

`runMode` 只表示工作流深度；交易周期由独立的 `quantEngineMode` 决定：

| quantEngineMode | 用途 | 参数重点 | 高频数据缺失处理 |
|-----------------|------|----------|------------------|
| `HIGH_FREQ_SHORT` | 短线 / 高频 | Momentum、Liquidity、Volatility | Level-2、盘口深度、分时、逐笔、资金流分解缺失进入 QIAM 折扣 |
| `LOW_FREQ_MID_LONG` | 中长线 / 低频 | Value、Quality/Fundamental、中期 Momentum、Volatility | 上述高频缺失只记录为 `ignoredMissingData`，不进入 QIAM 折扣 |

旧请求未传 `quant_engine_mode` 时，后端按任务类型推断：交易机会发现默认 `HIGH_FREQ_SHORT`，持仓复核和风险排查默认 `LOW_FREQ_MID_LONG`。

### DVG Gate 模块边界

DVG Gate 仍是一个 DAG 节点，但内部按 `quantEngineMode` 形成两个门禁模块，并在 `dvg.dvgModules` 中保留两个模块的判定快照：

| 模块 | 服务对象 | 高频微观结构缺失处理 | 输出影响 |
|------|----------|----------------------|----------|
| `dvg_high_frequency_trading` | 高频/短线交易机会 | Level-2、盘口深度、分时、逐笔、资金流分解为关键输入，缺失会进入 `criticalMissingData` | 可将 `qiamPermission` 降为 `ALLOW_WITH_DISCOUNT` 或更严格 |
| `dvg_low_frequency_mid_long` | 低频中长期复核 | 上述缺失写入 `ignoredMissingData`，不压低有效 `coreUnknownCount` | 基本面、日/周/月 K 线、来源完整性和数据冲突仍可限制 QIAM |

调用方继续读取兼容字段 `dvg.qiamPermission`、`dvg.allowedOutputLevel`、`dvg.criticalMissingData`；这些字段来自当前 active module。`dvg.rawCriticalMissingData` 保留原始证据缺失，便于审计。

### 数据缺失折扣
| 缺失项 | 折扣因子 | 说明 |
|--------|----------|------|
| 缺少 Level-2 | ×0.60 | 无逐笔成交，微观结构校验不完整 |
| 缺少盘口深度 | ×0.70 | 无法评估流动性冲击成本 |
| 缺少资金流分解 | ×0.75 | 无法判断主力资金动向 |
| 缺少筹码/股东户数/机构验证 | ×0.80 | 无法确认筹码集中度 |
| 缺少模型版本 | ×0.50 | 模型来源不可追溯 |
| 缺少样本外验证 | ×0.50 | 模型泛化能力未知 |
| 缺少 walk-forward 验证 | ×0.70 | 模型时序稳定性未知 |
| 缺少分布漂移检测 | ×0.75 | 数据分布可能已变化 |

### 模型风险折扣
| 风险项 | 折扣因子 |
|--------|----------|
| regime_fit = UNKNOWN | ×0.70 |
| volatility_condition = DANGEROUS | ×0.50 |
| liquidity_adjusted_signal = UNKNOWN | ×0.60 |
| overfit_risk = HIGH | ×0.40 |
| distribution_drift = SEVERE | ×0.30 |

### DVG 权限折扣
| DVG 权限 | 折扣处理 |
|----------|----------|
| ALLOW | 不额外折扣 |
| ALLOW_WITH_DISCOUNT | ×0.70 |
| REVIEW_ONLY | discount_factor = 0 |
| BLOCKED | discount_factor = 0 |

## 综合折扣公式

```
discount_factor = d1 × d2 × d3 × ... × dn
```

其中 d1...dn 为各项缺失对应的折扣因子。

## 降级映射

| 综合折扣因子 | QIAM 结果 |
|-------------|-----------|
| >= 0.85 | 保留原结论 |
| 0.60 ~ 0.85 | FAVORABLE → NEUTRAL |
| 0.40 ~ 0.60 | FAVORABLE → REVIEW_ONLY |
| < 0.40 | 不得正向使用，→ REVIEW_ONLY |
| = 0 | QIAM 禁用，→ REVIEW_ONLY 或 BLOCK_BUY |

## MFE/MAE 路径研究校准边界

MFE/MAE Path Research 可以参与 QIAM 校准，但只允许一档、可审计、受门禁约束的适宜性校准，不生成 BUY/ADD/SELL 指令。旧字段 `bottomResearchAdjustment` 仅作为兼容别名保留；新字段优先读取 `mfeMaePathResearchAdjustment`。

正向校准必须同时满足：
- DVG `qiamPermission=ALLOW`
- 技术面约束不是 `BEARISH`
- MFE/MAE 证据质量为 `MEDIUM` 或 `HIGH`
- `mfeFavorableProbability` 达到阈值且 `maeBreachProbability` 低于 0.35
- 现有折扣因子不低于 0.85

负向校准在 MAE 跌破风险偏高、技术面看空、DVG/风险恶化或多周期证据冲突时触发。无论正向或负向，校准最多移动一档，并必须写入 `mfeMaePathResearchAdjustment`；为兼容历史 run，也可同步镜像到 `bottomResearchAdjustment`。调整 payload 必须包含应用状态、方向、前后适宜性、证据和阻断原因。

## 强制规则

### 数据隔离
1. **raw_buy_suitability 不得直接进入 Final Writer**
2. Final Writer 只能使用 final_buy_suitability
3. raw FAVORABLE 只能作为研究加分项，不得作为交易触发项

### 权限约束
4. DVG REVIEW_ONLY 时，discount_factor = 0
5. DVG BLOCK 时，discount_factor = 0
6. QIAM 不得直接输出 BUY
7. QIAM 不得直接输出 ADD
8. QIAM 不得提高仓位上限
9. QIAM 不得绕过 DVG / Risk / ATrade / Portfolio / Execution

### 模型约束
10. 无计算工具时，不得输出精确概率/EV/仓位/滑点
11. 工具失败时，相关字段必须标记 U
12. 不允许 LLM 口算替代工具

## QIAM 输出结构

```json
{
  "node": "qiam",
  "status": "PASS | WARN | REVIEW_ONLY | BLOCK | SKIPPED",
  "allowed_actions": [],
  "blocked_actions": [],
  "hard_stop": false,
  "confidence": "HIGH | MEDIUM | LOW",
  "reasons": [],
  "missing_data": [],
  "warnings": [],
  "data": {
    "rawBuySuitability": "FAVORABLE | NEUTRAL | UNFAVORABLE",
    "discountFactor": 0.52,
    "finalBuySuitability": "FAVORABLE | NEUTRAL | REVIEW_ONLY",
    "dvgPermission": true,
    "modelConfidenceRaw": 0.75,
    "modelConfidenceFinal": 0.62,
    "overfitRisk": 0.2,
    "distributionDrift": 0.15,
    "downgradeReasons": [],
    "missingData": [],
    "mfeMaePathResearchAdjustment": {
      "observed": true,
      "applied": false,
      "direction": "NONE | UP | DOWN",
      "beforeFinalBuySuitability": "REVIEW_ONLY",
      "afterFinalBuySuitability": "REVIEW_ONLY",
      "maxStep": 1,
      "canCreateTradeAction": false,
      "blockedReasons": []
    },
    "bottomResearchAdjustment": {
      "legacyAliasOf": "mfeMaePathResearchAdjustment"
    }
  }
}
```
