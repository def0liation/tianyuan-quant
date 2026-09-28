from __future__ import annotations
from typing import Any, Dict

from .base_agent import BaseAgent, AgentResult


class DataFetchAgent(BaseAgent):
    node = "data_reliability_engine"
    name = "数据可靠性引擎"
    stage = "data"

    def process(self, run_context: Dict[str, Any], prior_outputs: Dict[str, Any]) -> AgentResult:
        market_data = run_context.get("marketData", {})
        data_mode = run_context.get("dataMode", "MOCK")
        symbol = run_context.get("stockCode", "UNKNOWN")
        data_sources_report = run_context.get("dataSources") if isinstance(run_context.get("dataSources"), dict) else {}
        data_sources = data_sources_report.get("sources") or {}
        data_summary = data_sources_report.get("summary") if isinstance(data_sources_report.get("summary"), dict) else {}
        ready_sources = [
            source.get("name") or key
            for key, source in data_sources.items()
            if isinstance(source, dict) and source.get("status") == "READY" and source.get("available")
        ]
        failed_sources = [
            source.get("name") or key
            for key, source in data_sources.items()
            if isinstance(source, dict) and source.get("status") != "READY"
        ]

        reasons = [
            f"已检查标的 {symbol} 的数据源：{', '.join(ready_sources) if ready_sources else '暂无可用真实数据源'}",
            f"数据模式: {data_mode}",
        ]

        missing_data = []
        if market_data.get("status") != "READY":
            missing_data.append("行情数据")
        missing_data.extend(failed_sources)
        missing_data.extend(["Level-2 逐笔成交", "盘口深度"])

        fallback_chain = []
        for key, source in data_sources.items():
            if not isinstance(source, dict):
                continue
            chain = source.get("fallbackChain") or source.get("degradationChain") or []
            if chain:
                fallback_chain.append(
                    {
                        "key": key,
                        "name": source.get("name") or key,
                        "chain": chain,
                        "reason": source.get("degradationReason") or source.get("detail") or source.get("error") or "",
                    }
                )

        data = {
            "marketData": market_data,
            "market": {"status": market_data.get("status", "MOCK"), "provider": market_data.get("provider", "mock")},
            "dataSources": data_sources_report,
            "sources": data_sources,
            "summary": {
                "dataMode": data_mode,
                "overallStatus": data_summary.get("overallStatus") or ("READY" if ready_sources else "MISSING"),
                "availableRatio": data_summary.get("availableRatio", ""),
                "readySourceCount": len(ready_sources),
                "failedSourceCount": len(failed_sources),
            },
            "freshness": {
                key: source.get("freshness")
                for key, source in data_sources.items()
                if isinstance(source, dict) and source.get("freshness")
            },
            "fallbackChain": fallback_chain,
        }

        warnings = [
            "缺少 Level-2 逐笔成交，无法判断封单强弱",
        ]
        if failed_sources:
            warnings.append(f"以下数据源未成功接入：{', '.join(failed_sources)}")

        return AgentResult(
            node=self.node,
            status="PASS" if ready_sources else "WARN",
            confidence="HIGH" if ready_sources else "LOW",
            reasons=reasons,
            missing_data=missing_data,
            warnings=warnings,
            data=data,
            audit_id=self._audit(),
        )
