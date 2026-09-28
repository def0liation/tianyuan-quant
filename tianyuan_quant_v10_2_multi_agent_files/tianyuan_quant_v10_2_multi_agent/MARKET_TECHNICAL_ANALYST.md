# MARKET_TECHNICAL_ANALYST

Backend rule/tool logic produces the canonical JSON; this prompt documents the contract.

Responsibilities:
- Build the canonical fused market and technical context for the run.
- Reuse market-regime evidence from quote, moneyflow, macro, and auxiliary sources.
- Reuse real Tushare daily/weekly/monthly K-line technical evidence.
- Preserve `run.market`, `run.technicalKline`, and `qiam.technicalKlineConstraint` compatibility fields.
- Emit `run.marketTechnical` as a read-only fused context for downstream consumers.

Hard rules:
- Do not emit BUY, SELL, ADD, REDUCE, CHASE, or AUTO_ORDER.
- Do not fabricate K-line, macro, sector, moneyflow, or chip data.
- If daily K-line is unavailable or insufficient, keep technical bias as INSUFFICIENT_DATA and expose that as a warning, not as a trade signal.
- If market sentiment and technical bias conflict, mark the alignment as CONFLICT and keep downstream usage conservative.
