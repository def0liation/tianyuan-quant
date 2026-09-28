from __future__ import annotations

from typing import Any, Dict

from ..core.bottom_research import build_bottom_research_analysis
from ..core.kline_service import get_kline_payload
from .base_agent import AgentResult, BaseAgent


class BottomResearchAgent(BaseAgent):
    node = "bottom_research"
    name = "MFE/MAE Path Research"
    stage = "analysis"
    rule_engine_only = True

    def process(self, run_context: Dict[str, Any], prior_outputs: Dict[str, Any]) -> AgentResult:
        run_mode = str(run_context.get("runMode") or "STANDARD_MODE").upper()
        if run_mode == "FAST_MODE":
            return AgentResult(
                node=self.node,
                status="SKIPPED",
                allowed_actions=["REVIEW_ONLY"],
                blocked_actions=["BUY", "ADD", "SELL", "AUTO_ORDER", "EXECUTION_BUY"],
                final_decision_cap="NO_DIRECT_TRADE_ACTION",
                confidence="LOW",
                reasons=["MFE/MAE Path Research is enabled only in STANDARD_MODE and DEEP_MODE."],
                data={
                    "agent": "mfe_mae_path_research",
                    "legacyAgent": self.node,
                    "researchType": "MFE_MAE_PATH_RESEARCH",
                    "status": "SKIPPED",
                    "regimeState": "DISABLED_BY_RUN_MODE",
                    "riskPolicy": "WATCH",
                    "mfeFavorableProbability": None,
                    "maeBreachProbability": None,
                    "bottomRepairProbability": None,
                    "breakdownRiskProbability": None,
                    "missingData": ["run_mode_fast"],
                    "warnings": ["mfe_mae_path_research_disabled_in_fast_mode"],
                    "provenance": {
                        "sourceNode": "mfe_mae_path_research",
                        "legacySourceNode": self.node,
                        "simulation_only": True,
                        "is_real_trade": False,
                    },
                },
                skipped_reason="MFE/MAE Path Research does not run in FAST_MODE.",
            )

        symbol = str(run_context.get("stockCode") or run_context.get("symbol") or "")
        config = run_context.get("bottomResearchConfig") or run_context.get("bottom_research_config")
        payload = get_kline_payload(symbol, "daily", "2y")
        analysis = build_bottom_research_analysis(
            symbol,
            payload,
            auxiliary_data=run_context.get("auxiliaryData") if isinstance(run_context.get("auxiliaryData"), dict) else None,
            config=config if isinstance(config, dict) else None,
        )

        status = str(analysis.get("status") or "WARN")
        diagnostics = analysis.get("modelDiagnostics") if isinstance(analysis.get("modelDiagnostics"), dict) else {}
        confidence = "MEDIUM" if diagnostics.get("status") == "READY" else "LOW"
        missing_data = [str(item) for item in analysis.get("missingData") or []]
        warnings = [str(item) for item in analysis.get("warnings") or []]

        return AgentResult(
            node=self.node,
            status=status,
            allowed_actions=["REVIEW_ONLY", "WATCH"],
            blocked_actions=["BUY", "ADD", "SELL", "AUTO_ORDER", "EXECUTION_BUY"],
            hard_stop=False,
            final_decision_cap="NO_DIRECT_TRADE_ACTION",
            confidence=confidence,
            reasons=[
                f"regimeState={analysis.get('regimeState', 'UNKNOWN')}",
                "MFE/MAE Path Research is the active research layer and cannot create execution permission.",
            ],
            missing_data=missing_data,
            warnings=warnings,
            data=analysis,
            audit_id=self._audit(),
            skipped_reason="MFE/MAE Path Research supporting-only: insufficient live K-line/model samples." if status == "SKIPPED" else None,
        )
