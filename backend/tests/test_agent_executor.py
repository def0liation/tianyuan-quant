from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core import agent_executor
from app.core.agent_executor import (
    _apply_agent_module_output_to_run,
    _canonical_quant_core_output,
    _mirror_data_reliability_prior_outputs,
    _mirror_quant_core_prior_outputs,
    _sync_guardrail_hub_prior_outputs,
    _apply_qiam_output,
    _run_quant_engine_submodules,
    execute_run_with_llm,
)
from app.core.agent_framework import (
    apply_quant_core_data,
    apply_agent_framework_to_run,
    normalize_run_artifacts,
    sync_quant_engine_rule_outputs_from_current_inputs,
    sync_qiam_probability_from_agent_module,
    sync_qiam_score_fields_from_agent_module,
)
from app.core.agent_framework import (
    sync_market_regime_from_agent_results,
    sync_market_technical_from_agent_results,
)
from app.core.llm_runner import LLMRunResult
from app.modules.base_agent import AgentResult
from app.modules.execution import ExecutionAgent
import app.modules.quant_core as quant_core_module
from app.modules.quant_core import QuantCoreAgent, build_mfe_mae_path_risk_filter, build_quant_core_interpretation

PATH_RISK_FILTER_FIELDS = {
    "version",
    "status",
    "method",
    "horizonDays",
    "actionBoundary",
    "labelStatus",
    "sampleQuality",
    "leakagePolicy",
    "simulation_only",
    "is_real_trade",
    "mfeMaeProxy",
    "riskCurve",
    "downsideRiskScore",
    "maxRiskGradient",
    "riskPolicy",
    "evidence",
    "warnings",
    "limitations",
    "provenance",
}
PATH_RISK_PROXY_FIELDS = {"mfeProxy", "maeProxy", "riskRewardProxy"}
PATH_RISK_BUCKETS = [2, 5, 8, 10, 15, 20]
PATH_RISK_INPUT_FIELDS = {
    "technicalKline.trend",
    "technicalKline.volumePrice",
    "technicalKline.supportResistance",
    "technicalKline.chipAnalysis",
    "technicalKline.dataQuality",
    "marketTechnical.market",
    "qiam",
    "dvg",
}


def _assert_quant_core_legacy_marker(payload: dict) -> None:
    assert payload["legacyCompatibilityOnly"] is True
    assert payload["canonicalNode"] == "quant_core"
    assert payload["activeNode"] is False


def _assert_guardrail_legacy_marker(payload: dict, node: str) -> None:
    assert payload["node"] == node
    assert payload["legacyCompatibilityOnly"] is True
    assert payload["canonicalNode"] == "guardrail_hub"
    assert payload["activeNode"] is False


def _market_regime_data() -> dict:
    return {
        "marketSentiment": "BEARISH",
        "volatilityIndex": 95,
        "liquidityIndex": 48,
        "institutionalActivity": "MEDIUM",
        "retailSentiment": "PESSIMISTIC",
        "sectorRotation": [],
        "macroIndicators": {"cpi": 1.2, "gdp": 5.0, "policyRate": 3.0},
        "regimeClassification": "高波动",
        "provenance": {
            "macroIndicators": {
                "sourceType": "LIVE",
                "provider": "tushare",
                "note": "来自宏观数据源",
            }
        },
    }


def _technical_kline_data() -> dict:
    return {
        "agent": "technical_kline_analyst",
        "status": "PASS",
        "technicalBias": "BULLISH",
        "confidence": 0.86,
        "dataQuality": {
            "provider": "tushare",
            "dataMode": "LIVE",
            "dailyCount": 76,
            "weeklyCount": 12,
            "monthlyCount": 5,
        },
        "summaryForDownstream": "canonical LIVE Tushare K-line",
        "forbiddenActions": ["BUY", "SELL", "ADD", "REDUCE", "CHASE", "AUTO_ORDER"],
    }


def _path_risk_technical_data(*, high_risk: bool = False, live: bool = True) -> dict:
    data = _technical_kline_data()
    data["dataQuality"] = {
        "provider": "tushare",
        "dataMode": "LIVE" if live else "UNAVAILABLE",
        "dailyCount": 76 if live else 12,
        "weeklyCount": 12,
        "monthlyCount": 5,
    }
    if high_risk:
        data.update({
            "technicalBias": "BULLISH",
            "trend": {"close": 10.0, "ma20": 10.5, "return20d": -0.10, "return60d": -0.18},
            "volumePrice": {"status": "AVAILABLE", "volumeRatio5v20": 2.8},
            "supportResistance": {
                "support20d": 9.96,
                "support60d": 9.65,
                "distanceToSupport20d": 0.004,
                "distanceToResistance20d": 0.018,
            },
            "chipAnalysis": {
                "status": "AVAILABLE",
                "source": "KLINE_VOLUME_PRICE_PROXY",
                "overheadVolumeRatio": 0.72,
                "supportVolumeRatio": 0.02,
                "costZone": {"volumeRatio": 0.04},
            },
        })
    else:
        data.update({
            "technicalBias": "BULLISH",
            "trend": {"close": 10.0, "ma20": 9.6, "return20d": 0.06, "return60d": 0.12},
            "volumePrice": {"status": "AVAILABLE", "volumeRatio5v20": 1.0},
            "supportResistance": {
                "support20d": 8.8,
                "support60d": 8.5,
                "distanceToSupport20d": 0.12,
                "distanceToResistance20d": 0.09,
            },
            "chipAnalysis": {
                "status": "AVAILABLE",
                "source": "KLINE_VOLUME_PRICE_PROXY",
                "overheadVolumeRatio": 0.08,
                "supportVolumeRatio": 0.52,
                "costZone": {"volumeRatio": 0.40},
            },
        })
    return data


def test_mfe_mae_dev_guide_records_contract_and_acceptance_commands():
    guide = Path("docs/MFE_MAE_PATH_RISK_FILTER_DEV_GUIDE.md").read_text(encoding="utf-8")

    assert "read-only path risk filter" in guide
    assert "No live trading enablement" in guide
    assert "coreInterpretation.pathRiskFilter" in guide
    assert "maxRiskGradient" in guide
    assert "technicalKline.dataQuality" in guide
    assert "LIVE" in guide and "dailyCount" in guide
    assert "READ_ONLY_NO_PERMISSION_CHANGE" in guide
    assert "mfeProxy" in guide and "maeProxy" in guide and "riskRewardProxy" in guide
    assert "py_compile" in guide
    assert r"backend\app\core\mfe_mae_path_risk_research.py" in guide
    assert "主人，任务完成了喵" in guide


def test_market_regime_module_output_updates_run_market():
    run = {
        "market": {
            "marketSentiment": "NEUTRAL",
            "volatilityIndex": 0,
            "liquidityIndex": 0,
            "institutionalActivity": "LOW",
            "retailSentiment": "NEUTRAL",
            "sectorRotation": [],
            "macroIndicators": {},
            "provenance": {"sourceType": "PENDING"},
        }
    }

    _apply_agent_module_output_to_run(
        run,
        "market_regime",
        AgentResult(node="market_regime", status="PASS", data=_market_regime_data()),
    )

    assert run["market"]["marketSentiment"] == "BEARISH"
    assert run["market"]["macroIndicators"] == {"cpi": 1.2, "gdp": 5.0, "policyRate": 3.0}
    assert run["market"]["provenance"]["macroIndicators"]["sourceType"] == "LIVE"


def test_market_regime_sync_backfills_completed_run_from_module_results():
    run = {
        "market": {
            "marketSentiment": "NEUTRAL",
            "volatilityIndex": 0,
            "liquidityIndex": 0,
            "institutionalActivity": "LOW",
            "retailSentiment": "NEUTRAL",
            "sectorRotation": [],
            "macroIndicators": {},
            "provenance": {"sourceType": "PENDING"},
        },
        "agentModuleResults": {
            "market_regime": {
                "data": _market_regime_data(),
            }
        },
    }

    changed = sync_market_regime_from_agent_results(run)

    assert changed is True
    assert run["market"]["regimeClassification"] == "高波动"
    assert run["market"]["macroIndicators"]["policyRate"] == 3.0


def test_market_technical_module_output_updates_compatibility_fields():
    run = {
        "market": {"marketSentiment": "NEUTRAL"},
        "technicalKline": {"status": "SKIPPED", "confidence": 0.0},
        "dvg": {"criticalMissingData": []},
    }
    fused_data = {
        "agent": "market_technical_analyst",
        "status": "PASS",
        "market": _market_regime_data(),
        "technicalKline": _technical_kline_data(),
        "alignment": "CONFLICT",
        "confidence": 0.76,
        "summaryForDownstream": "fused summary",
        "warnings": ["market_technical_conflict"],
    }

    _apply_agent_module_output_to_run(
        run,
        "market_technical_analyst",
        AgentResult(node="market_technical_analyst", status="PASS", data=fused_data),
    )

    assert run["marketTechnical"]["alignment"] == "CONFLICT"
    assert run["market"]["marketSentiment"] == "BEARISH"
    assert run["technicalKline"]["technicalBias"] == "BULLISH"
    assert run["technicalKline"]["summaryForDownstream"] == "canonical LIVE Tushare K-line"
    assert run["dvg"]["provenance"]["technicalKline"]["sourceType"] == "LIVE"


def test_market_technical_sync_backfills_completed_run_from_module_results():
    run = {
        "market": {"marketSentiment": "NEUTRAL"},
        "technicalKline": {},
        "agentModuleResults": {
            "market_technical_analyst": {
                "data": {
                    "status": "PASS",
                    "market": _market_regime_data(),
                    "technicalKline": _technical_kline_data(),
                    "alignment": "ALIGNED_BEARISH",
                    "confidence": 0.7,
                    "summaryForDownstream": "fused summary",
                }
            }
        },
    }

    changed = sync_market_technical_from_agent_results(run)

    assert changed is True
    assert run["marketTechnical"]["summaryForDownstream"] == "fused summary"
    assert run["market"]["macroIndicators"]["policyRate"] == 3.0
    assert run["technicalKline"]["confidence"] == 0.86


def test_paper_trading_agent_output_is_forced_to_simulation_boundary():
    run = {
        "paperTrading": {
            "simulation_only": False,
            "is_real_trade": True,
            "action": "BUY",
            "allowed_order_namespace": "LIVE",
            "simulationActions": [{"action": "SELL", "orderNamespace": "LIVE"}],
        }
    }
    data = {
        "status": "ACTIVE",
        "latest_action": "SELL",
        "paper_action": "BUY",
        "simulationOnly": False,
        "isRealTrade": True,
        "order_namespace": "LIVE",
    }

    _apply_agent_module_output_to_run(
        run,
        "paper_trading_agent",
        AgentResult(node="paper_trading_agent", status="ACTIVE", data=data),
    )

    paper = run["paperTrading"]
    assert paper["simulation_only"] is True
    assert paper["is_real_trade"] is False
    assert paper["simulationOnly"] is True
    assert paper["isRealTrade"] is False
    assert paper["allowed_order_namespace"] == "SIM_*"
    assert paper["order_namespace"] == "SIM_*"
    assert paper["action"] == "SIM_HOLD"
    assert paper["paper_action"] == "SIM_HOLD"
    assert paper["latest_action"] == "SIM_HOLD"
    assert paper["simulationActions"][0]["action"] == "SIM_HOLD"
    assert paper["simulationActions"][0]["orderNamespace"] == "SIM_*"
    assert "simulation_only_boundary_restored" in paper["warnings"]
    assert "real_trade_boundary_suppressed" in paper["warnings"]
    assert "non_sim_order_namespace_suppressed" in paper["warnings"]
    assert "non_sim_paper_action_suppressed" in paper["warnings"]


def test_quant_core_llm_output_cannot_override_rule_qiam_prior_outputs():
    module_data = {
        "agent": "quant_core",
        "status": "REVIEW_ONLY",
        "marketTechnical": {"status": "PASS", "technicalKline": {"technicalBias": "BULLISH"}},
        "qiam": {"finalBuySuitability": "BLOCK_BUY"},
        "legacyAgentOutputs": {
            "quant_engine": {"finalBuySuitability": "BLOCK_BUY"},
            "qiam": {"finalBuySuitability": "BLOCK_BUY"},
        },
    }
    spoofed_llm_output = {
        "status": "PASS",
        "marketTechnical": {"status": "PASS", "technicalKline": {"technicalBias": "BULLISH"}},
        "qiam": {"finalBuySuitability": "FAVORABLE"},
        "legacyAgentOutputs": {
            "quant_engine": {"finalBuySuitability": "FAVORABLE"},
            "qiam": {"finalBuySuitability": "FAVORABLE"},
        },
    }

    output = _canonical_quant_core_output(spoofed_llm_output, module_data)
    prior_outputs = {
        "dvg_gate": {"executionPermission": "ALLOW", "dataReliability": "HIGH"},
        "trade_micro": {"executionReachability": "REACHABLE"},
        "portfolio": {"allowAddPosition": True},
    }
    _mirror_quant_core_prior_outputs(prior_outputs, output)

    execution_result = ExecutionAgent().process(
        {
            "dataMode": "LIVE",
            "dvg": {"executionPermission": "ALLOW", "dataReliability": "HIGH"},
            "atrade": {"executionReachability": "REACHABLE"},
            "portfolio": {"allowAddPosition": True},
            "qiam": {"finalBuySuitability": "BLOCK_BUY"},
        },
        prior_outputs,
    )

    assert output is module_data
    assert prior_outputs["qiam"]["finalBuySuitability"] == "BLOCK_BUY"
    assert prior_outputs["quant_engine"]["finalBuySuitability"] == "BLOCK_BUY"
    _assert_quant_core_legacy_marker(prior_outputs["qiam"])
    _assert_quant_core_legacy_marker(prior_outputs["quant_engine"])
    assert execution_result.status == "BLOCK_BUY"
    assert "BUY_CANDIDATE" in execution_result.blocked_actions


def test_quant_core_agent_review_only_status_keeps_low_evidence_without_warnings(monkeypatch):
    def stub_agent(result: AgentResult):
        return lambda: SimpleNamespace(process=lambda run_context, prior_outputs: result)

    monkeypatch.setattr(
        quant_core_module,
        "MarketTechnicalAnalystAgent",
        stub_agent(
            AgentResult(
                node="market_technical_analyst",
                status="PASS",
                data={
                    "status": "PASS",
                    "market": {**_market_regime_data(), "marketSentiment": "BULLISH"},
                    "technicalKline": _technical_kline_data(),
                    "alignment": "ALIGNED_BULLISH",
                    "confidence": 0.78,
                },
            )
        ),
    )
    monkeypatch.setattr(
        quant_core_module,
        "BottomResearchAgent",
        stub_agent(
            AgentResult(
                node="bottom_research",
                status="PASS",
                data={
                    "status": "PASS",
                    "regimeState": "BOTTOM_REPAIR_ZONE",
                    "bottomRepairProbability": 0.62,
                    "breakdownRiskProbability": 0.22,
                    "trendSynthesis": {"primaryTrendBias": "UP"},
                    "modelDiagnostics": {"status": "READY"},
                },
            )
        ),
    )
    monkeypatch.setattr(
        quant_core_module,
        "FactorSlicingAgent",
        stub_agent(
            AgentResult(
                node="factor_slicing",
                status="PASS",
                data={
                    "mode": "AUTO",
                    "factorStability": 0.72,
                    "missingFactorData": [],
                    "factorDataSource": "RULE_DERIVED",
                },
            )
        ),
    )
    monkeypatch.setattr(
        quant_core_module,
        "FactorEngineAgent",
        stub_agent(AgentResult(node="factor_engine", status="PASS", data={"status": "PASS"})),
    )
    monkeypatch.setattr(
        quant_core_module,
        "CalculationAuthorityAgent",
        stub_agent(AgentResult(node="calculation_authority", status="PASS", data={"status": "PASS"})),
    )
    monkeypatch.setattr(
        quant_core_module,
        "QiamAgent",
        stub_agent(
            AgentResult(
                node="qiam",
                status="REVIEW_ONLY",
                data={
                    "finalBuySuitability": "REVIEW_ONLY",
                    "discountFactor": 0.8,
                    "probabilityBandUp": 0.34,
                    "probabilityBandDown": 0.31,
                    "modelConfidenceFinal": 0.55,
                    "missingData": [],
                    "downgradeReasons": [],
                },
            )
        ),
    )
    monkeypatch.setattr(
        quant_core_module,
        "ScenarioEngineAgent",
        stub_agent(AgentResult(node="scenario_engine", status="PASS", data={"status": "PASS", "dvgPermission": "ALLOW"})),
    )

    result = QuantCoreAgent().process({"runMode": "STANDARD_MODE", "quantEngine": {"mode": "HIGH_FREQ_SHORT"}}, {})

    assert result.status == "REVIEW_ONLY"
    assert result.warnings == []
    assert result.missing_data == []
    assert result.data["evidenceStrength"] == "LOW"
    assert result.data["provenance"]["evidenceStrength"] == "LOW"
    assert result.data["simulation_only"] is True
    assert result.data["is_real_trade"] is False
    assert result.data["strongConclusionAllowed"] is False


def test_quant_core_legacy_outputs_are_marked_when_applied():
    run = {}
    data = {
        "agent": "quant_core",
        "status": "REVIEW_ONLY",
        "qiam": {"finalBuySuitability": "NEUTRAL"},
        "legacyOutputs": {
            "quant_engine": {
                "node": "quant_engine",
                "status": "REVIEW_ONLY",
                "data": {"finalBuySuitability": "NEUTRAL"},
            }
        },
        "legacyAgentOutputs": {
            "quant_engine": {"finalBuySuitability": "NEUTRAL"},
        },
    }

    assert apply_quant_core_data(run, data) is True

    _assert_quant_core_legacy_marker(run["quantCore"]["legacyOutputs"]["quant_engine"])
    _assert_quant_core_legacy_marker(run["agentModuleResults"]["quant_engine"])
    _assert_quant_core_legacy_marker(run["quantCore"]["legacyAgentOutputs"]["quant_engine"])
    _assert_quant_core_legacy_marker(run["agentOutputs"]["quant_engine"])
    assert run["qiam"]["finalBuySuitability"] == "NEUTRAL"


def test_data_reliability_prior_outputs_do_not_generate_legacy_data_engine_keys():
    output = {
        "status": "PASS",
        "dataSources": {"summary": {"liveDataUsable": True}},
        "freshness": {"quote": "FRESH"},
    }
    prior_outputs = {}

    _mirror_data_reliability_prior_outputs(prior_outputs, output)

    assert prior_outputs["data_reliability_engine"] is output
    assert prior_outputs["data_reliability_engine_output"] is output
    assert "data_engine" not in prior_outputs
    assert "data_engine_output" not in prior_outputs


def test_guardrail_hub_prior_outputs_mark_legacy_aliases_compatibility_only():
    output = {
        "status": "PASS",
        "dvg": {"status": "PASS", "qiamPermission": "ALLOW"},
        "risk": {"status": "PASS", "hardStop": False},
        "atrade": {"status": "WARN", "executionReachability": "CONDITIONALLY_REACHABLE"},
        "legacyAgentOutputs": {
            "risk_firewall": {"status": "STALE"},
        },
    }
    prior_outputs = {}

    _sync_guardrail_hub_prior_outputs(prior_outputs, output)

    assert prior_outputs["guardrail_hub"] is output
    assert prior_outputs["guardrail_hub_output"] is output
    for legacy_id in ("dvg_gate", "dvg_evidence_gate", "risk_firewall", "trade_micro", "atrade"):
        _assert_guardrail_legacy_marker(prior_outputs[legacy_id], legacy_id)
        assert prior_outputs[f"{legacy_id}_output"] == prior_outputs[legacy_id]
    assert prior_outputs["risk_firewall"]["status"] == "PASS"
    assert prior_outputs["atrade"]["executionReachability"] == "CONDITIONALLY_REACHABLE"
    assert "legacyCompatibilityOnly" not in output["dvg"]
    assert "legacyCompatibilityOnly" not in output["risk"]
    assert "legacyCompatibilityOnly" not in output["atrade"]


@pytest.mark.asyncio
async def test_execute_run_initial_prior_outputs_do_not_seed_legacy_outputs(monkeypatch):
    initial_prior_outputs: dict = {}

    def fake_run_agent_module(agent_id: str, run: dict, prior_outputs: dict) -> AgentResult:
        if agent_id == "orchestrator":
            initial_prior_outputs.update(prior_outputs)
        return AgentResult(node=agent_id, status="PASS", data={"agent": agent_id})

    async def fake_run_agent_llm(agent_id: str, run: dict, prior_outputs: dict) -> LLMRunResult:
        return LLMRunResult(
            status="COMPLETED",
            provider="test",
            model="test-model",
            profile_id="test_profile",
            parsed_json={"status": "PASS", "agent": agent_id},
        )

    monkeypatch.setattr(agent_executor, "run_agent_module", fake_run_agent_module)
    monkeypatch.setattr(agent_executor, "run_agent_llm", fake_run_agent_llm)
    monkeypatch.setattr(
        agent_executor,
        "get_agent_execution_config",
        lambda agent_id: (
            SimpleNamespace(id=agent_id),
            SimpleNamespace(provider="test", model="test-model", id="test_profile", timeout_seconds=1),
        ),
    )
    monkeypatch.setattr(agent_executor, "save_run", lambda run: None)

    run = {
        "runId": "RUN_NO_LEGACY_PRIOR_SEEDS",
        "status": "CREATED",
        "nodes": [
            {"id": "orchestrator", "name": "Orchestrator", "status": "PASS", "isRunning": False, "isSkipped": False, "rawJson": {}},
            {"id": "final_writer", "name": "Final Writer", "status": "PASS", "isRunning": False, "isSkipped": False, "rawJson": {}},
        ],
        "streamEvents": [],
        "auditLog": [],
        "agentOutputs": {},
        "agentModuleResults": {},
        "llmTrace": [],
    }

    await execute_run_with_llm("RUN_NO_LEGACY_PRIOR_SEEDS", {"RUN_NO_LEGACY_PRIOR_SEEDS": run})

    assert "orchestrator_output" in initial_prior_outputs
    assert "data_reliability_engine_output" in initial_prior_outputs
    assert "guardrail_hub_output" in initial_prior_outputs
    for legacy_key in (
        "data_engine_output",
        "dvg_gate_output",
        "risk_firewall_output",
        "trade_micro_output",
        "market_technical_output",
    ):
        assert legacy_key not in initial_prior_outputs


def test_quant_core_interpretation_high_frequency_weights_and_contract():
    run = {
        "taskType": "交易机会发现",
        "quantEngine": {"mode": "HIGH_FREQ_SHORT"},
    }
    market = {**_market_regime_data(), "marketSentiment": "BULLISH"}
    technical = _technical_kline_data()
    interpretation = build_quant_core_interpretation(
        run,
        marketTechnical={
            "market": market,
            "technicalKline": technical,
            "alignment": "ALIGNED_BULLISH",
            "confidence": 0.78,
        },
        bottomResearch={
            "status": "PASS",
            "regimeState": "BOTTOM_REPAIR_ZONE",
            "bottomRepairProbability": 0.68,
            "breakdownRiskProbability": 0.22,
            "trendSynthesis": {"primaryTrendBias": "UP", "mainConclusion": "修复占优"},
            "modelDiagnostics": {"status": "READY"},
        },
        factorSlicing={
            "mode": "AUTO",
            "factorStability": 0.72,
            "missingFactorData": [],
            "factorDataSource": "RULE_DERIVED",
        },
        qiam={
            "finalBuySuitability": "FAVORABLE",
            "discountFactor": 1.0,
            "probabilityBandUp": 0.62,
            "probabilityBandDown": 0.18,
            "modelConfidenceFinal": 0.74,
            "probabilitySource": "RULE_DERIVED",
        },
        scenario={"status": "PASS", "dvgPermission": "ALLOW"},
        quantEngine={"mode": "HIGH_FREQ_SHORT"},
    )

    assert interpretation["version"] == "quant_core_interpretation_v1"
    assert interpretation["actionBoundary"] == "READ_ONLY_NO_PERMISSION_CHANGE"
    assert interpretation["weights"]["qiam"] == pytest.approx(0.30)
    assert interpretation["weights"]["technical"] == pytest.approx(0.30)
    assert interpretation["weightAdjusted"] is False
    assert interpretation["overallScore"] > 60
    future = interpretation["futureTrendProbability"]
    assert future["version"] == "quant_core_future_trend_probability_v1"
    assert future["decisionFeedback"]["actionBoundary"] == "READ_ONLY_NO_REAL_TRADE_PERMISSION_CHANGE"
    assert future["points"][0]["calibrationStatus"] == "INSUFFICIENT_SAMPLE"
    assert 0 <= future["points"][0]["calibratedUpProbability"] <= 1
    assert 0 <= future["points"][0]["calibratedDownProbability"] <= 1
    visual = interpretation["visualDecisionPanel"]
    assert visual["version"] == "quant_core_visual_decision_panel_v1"
    assert visual["actionBoundary"] == "READ_ONLY_NO_PERMISSION_CHANGE"
    assert visual["simulation_only"] is True
    assert visual["is_real_trade"] is False
    assert visual["directionProbability"]["horizonDays"] == future["points"][0]["horizonDays"]
    assert visual["directionProbability"]["upProbability"] == future["points"][0]["calibratedUpProbability"]
    assert visual["directionProbability"]["downProbability"] == future["points"][0]["calibratedDownProbability"]
    assert visual["directionProbability"]["source"] == "FUTURE_TREND_PROBABILITY_CALIBRATED"


def test_quant_core_interpretation_reads_canonical_scenario_fallbacks():
    run = {
        "taskType": "review",
        "quantEngine": {"mode": "HIGH_FREQ_SHORT"},
        "scenario": {"status": "WARN", "dvgPermission": "REVIEW_ONLY"},
        "dvg": {"scenarioPermission": "BLOCKED"},
    }

    interpretation = build_quant_core_interpretation(
        run,
        marketTechnical={
            "market": {**_market_regime_data(), "marketSentiment": "BULLISH"},
            "alignment": "ALIGNED_BULLISH",
            "confidence": 0.7,
        },
        scenario=None,
        quantEngine={"mode": "HIGH_FREQ_SHORT"},
    )

    market_dimension = next(item for item in interpretation["dimensions"] if item["key"] == "marketScenario")
    assert "scenarioPermission=REVIEW_ONLY" in market_dimension["evidence"]

    dvg_fallback = build_quant_core_interpretation(
        {**run, "scenario": None},
        marketTechnical={
            "market": {**_market_regime_data(), "marketSentiment": "BULLISH"},
            "alignment": "ALIGNED_BULLISH",
            "confidence": 0.7,
        },
        scenario=None,
        quantEngine={"mode": "HIGH_FREQ_SHORT"},
    )

    dvg_market_dimension = next(item for item in dvg_fallback["dimensions"] if item["key"] == "marketScenario")
    assert "scenarioPermission=BLOCKED" in dvg_market_dimension["evidence"]


def test_normalize_run_artifacts_suppresses_pre_execution_core_interpretation():
    run = {
        "runId": "RUN_CREATED_SEED",
        "status": "CREATED",
        "taskType": "review",
        "quantEngine": {"mode": "LOW_FREQ_MID_LONG"},
        "marketTechnical": None,
        "mfeMaeResearch": None,
        "bottomResearch": None,
        "factorSlicing": {
            "mode": "AUTO",
            "factorStability": 0,
            "factorDataSource": "PENDING",
            "missingFactorData": ["factor inputs pending"],
        },
        "qiam": {
            "finalBuySuitability": "REVIEW_ONLY",
            "probabilityBandUp": 0.14,
            "probabilityBandDown": 0.41,
            "modelConfidenceFinal": 0.62,
            "missingData": ["qiam inputs pending"],
        },
        "quantCore": {
            "coreInterpretation": {
                "version": "quant_core_interpretation_v1",
                "summary": "stale seed interpretation",
            }
        },
        "agentOutputs": {},
        "agentModuleResults": {},
        "finalContext": {
            "conclusion_derivation_inputs": {
                "core_interpretation": {
                    "version": "quant_core_interpretation_v1",
                    "summary": "stale seed interpretation",
                },
                "quant_core_summary": {
                    "coreInterpretation": {
                        "version": "quant_core_interpretation_v1",
                        "summary": "stale seed interpretation",
                    }
                },
            }
        },
    }

    normalize_run_artifacts(run)

    assert run["quantCore"] is None
    inputs = run["finalContext"]["conclusion_derivation_inputs"]
    assert "core_interpretation" not in inputs
    assert "coreInterpretation" not in inputs["quant_core_summary"]


def test_quant_core_interpretation_includes_ready_mfe_mae_path_risk_filter():
    technical = _path_risk_technical_data()
    interpretation = build_quant_core_interpretation(
        {
            "taskType": "review",
            "technicalKline": technical,
            "market": {**_market_regime_data(), "marketSentiment": "BULLISH", "liquidityIndex": 82, "volatilityIndex": 35},
            "dvg": {"dataReliability": "HIGH"},
            "qiam": {"finalBuySuitability": "FAVORABLE", "probabilityBandUp": 0.58, "probabilityBandDown": 0.12},
            "quantEngine": {"mode": "HIGH_FREQ_SHORT"},
        },
        marketTechnical={
            "market": {**_market_regime_data(), "marketSentiment": "BULLISH", "liquidityIndex": 82, "volatilityIndex": 35},
            "technicalKline": technical,
            "alignment": "ALIGNED_BULLISH",
            "confidence": 0.78,
        },
        qiam={"finalBuySuitability": "FAVORABLE", "probabilityBandUp": 0.58, "probabilityBandDown": 0.12},
        quantEngine={"mode": "HIGH_FREQ_SHORT"},
    )

    path_risk = interpretation["pathRiskFilter"]
    assert set(path_risk) == PATH_RISK_FILTER_FIELDS
    assert path_risk["version"] == "mfe_mae_path_risk_filter_v1"
    assert path_risk["status"] == "READY"
    assert path_risk["method"] == "daily_proxy_no_future_labels_v1"
    assert path_risk["horizonDays"] == 20
    assert path_risk["actionBoundary"] == "READ_ONLY_NO_PERMISSION_CHANGE"
    assert path_risk["labelStatus"] == "UNLABELED_NOWCAST_PROXY_ONLY"
    assert path_risk["sampleQuality"]["dataMode"] == "LIVE"
    assert "no_future_mfe_mae_labels" in path_risk["leakagePolicy"]
    assert path_risk["simulation_only"] is True
    assert path_risk["is_real_trade"] is False
    assert path_risk["riskPolicy"] == "NORMAL"
    assert path_risk["maxRiskGradient"] is not None
    assert [item["drawdownPct"] for item in path_risk["riskCurve"]] == PATH_RISK_BUCKETS
    assert set(path_risk["mfeMaeProxy"]) == PATH_RISK_PROXY_FIELDS
    assert path_risk["provenance"]["actionBoundary"] == "READ_ONLY_NO_PERMISSION_CHANGE"
    assert PATH_RISK_INPUT_FIELDS <= set(path_risk["provenance"]["inputFields"])
    path_dimension = next(item for item in interpretation["dimensions"] if item["key"] == "pathRisk")
    assert path_dimension["label"] == "MFE/MAE路径风险"
    assert path_dimension["weight"] == 0.0
    visual = interpretation["visualDecisionPanel"]
    assert visual["pathPayoffProxy"]["mfeProxy"] == path_risk["mfeMaeProxy"]["mfeProxy"]
    assert visual["pathPayoffProxy"]["maeProxy"] == path_risk["mfeMaeProxy"]["maeProxy"]
    assert visual["pathPayoffProxy"]["riskRewardProxy"] == path_risk["mfeMaeProxy"]["riskRewardProxy"]
    assert visual["riskGradient"]["riskPolicy"] == path_risk["riskPolicy"]
    assert visual["probabilityOddsMatrix"]["zone"] in {"PRIORITY", "WATCH", "FILTER"}
    assert visual["probabilityOddsMatrix"]["zone"] != "INSUFFICIENT_DATA"


def test_mfe_mae_path_risk_filter_marks_insufficient_data_without_qiam_downgrade():
    qiam = {"finalBuySuitability": "FAVORABLE", "probabilityBandUp": 0.58, "probabilityBandDown": 0.12}
    output = build_mfe_mae_path_risk_filter(
        {
            "technicalKline": _path_risk_technical_data(live=False),
            "market": {**_market_regime_data(), "marketSentiment": "BULLISH"},
            "qiam": qiam,
            "dvg": {"dataReliability": "HIGH"},
        },
        qiam=qiam,
    )

    assert set(output) == PATH_RISK_FILTER_FIELDS
    assert output["status"] == "INSUFFICIENT_DATA"
    assert output["actionBoundary"] == "READ_ONLY_NO_PERMISSION_CHANGE"
    assert output["labelStatus"] == "UNLABELED_NOWCAST_PROXY_ONLY"
    assert output["sampleQuality"]["dataMode"] == "UNAVAILABLE"
    assert "technical_kline_live_daily_data_missing" in output["sampleQuality"]["missingInputs"]
    assert "no_future_mfe_mae_labels" in output["leakagePolicy"]
    assert output["simulation_only"] is True
    assert output["is_real_trade"] is False
    assert output["riskPolicy"] == "WATCH"
    assert output["riskCurve"] == []
    assert output["downsideRiskScore"] is None
    assert output["maxRiskGradient"] is None
    assert output["mfeMaeProxy"] == {"mfeProxy": None, "maeProxy": None, "riskRewardProxy": None}
    assert set(output["mfeMaeProxy"]) == PATH_RISK_PROXY_FIELDS
    assert output["provenance"]["actionBoundary"] == "READ_ONLY_NO_PERMISSION_CHANGE"
    assert PATH_RISK_INPUT_FIELDS <= set(output["provenance"]["inputFields"])
    assert qiam["finalBuySuitability"] == "FAVORABLE"
    assert any("daily_count_below_30" in item for item in output["warnings"])

    interpretation = build_quant_core_interpretation(
        {
            "technicalKline": _path_risk_technical_data(live=False),
            "market": {**_market_regime_data(), "marketSentiment": "BULLISH"},
            "qiam": qiam,
            "dvg": {"dataReliability": "HIGH"},
        },
        qiam=qiam,
    )
    visual = interpretation["visualDecisionPanel"]
    assert visual["status"] == "INSUFFICIENT_DATA"
    assert visual["riskGradient"]["status"] == "INSUFFICIENT_DATA"
    assert visual["probabilityOddsMatrix"]["zone"] == "INSUFFICIENT_DATA"
    assert visual["actionBoundary"] == "READ_ONLY_NO_PERMISSION_CHANGE"


def test_high_mfe_mae_path_risk_is_read_only_and_syncs_final_context():
    qiam = {
        "finalBuySuitability": "FAVORABLE",
        "discountFactor": 1.0,
        "probabilityBandUp": 0.45,
        "probabilityBandDown": 0.82,
        "modelConfidenceFinal": 0.74,
        "probabilitySource": "RULE_DERIVED",
    }
    execution = {"allowedActions": ["REVIEW_ONLY"], "forbiddenActions": ["BUY_CANDIDATE"]}
    signal_ops = {"signalStatus": "WATCH", "blockedReason": "manual_watch"}
    run = {
        "runId": "RUN_PATH_RISK_READ_ONLY",
        "stockCode": "000001.SZ",
        "stockName": "Ping An",
        "taskType": "持仓复核",
        "runMode": "STANDARD_MODE",
        "quantEngine": {"mode": "HIGH_FREQ_SHORT"},
        "market": {**_market_regime_data(), "marketSentiment": "BEARISH", "liquidityIndex": 5, "volatilityIndex": 98},
        "marketTechnical": {
            "market": {**_market_regime_data(), "marketSentiment": "BEARISH", "liquidityIndex": 5, "volatilityIndex": 98},
            "technicalKline": _path_risk_technical_data(high_risk=True),
            "alignment": "CONFLICT",
            "confidence": 0.78,
        },
        "technicalKline": _path_risk_technical_data(high_risk=True),
        "bottomResearch": {
            "status": "PASS",
            "regimeState": "BOTTOM_REPAIR_ZONE",
            "bottomRepairProbability": 0.62,
            "breakdownRiskProbability": 0.32,
            "trendSynthesis": {"primaryTrendBias": "UP"},
            "modelDiagnostics": {"status": "READY"},
        },
        "factorSlicing": {
            "mode": "AUTO",
            "factorStability": 0.72,
            "missingFactorData": [],
            "factorDataSource": "RULE_DERIVED",
        },
        "dvg": {"dataReliability": "HIGH", "criticalMissingData": []},
        "qiam": dict(qiam),
        "quantCore": None,
        "execution": dict(execution),
        "signalOps": dict(signal_ops),
        "finalAction": "WAIT",
        "finalContext": {"conclusion_derivation_inputs": {}},
        "nodes": [],
        "agentModuleResults": {},
    }
    prior_outputs = {
        "qiam": {"finalBuySuitability": "STALE_QIAM"},
        "quant_engine": {"finalBuySuitability": "STALE_QUANT_ENGINE"},
    }
    prior_outputs_before_normalize = {key: dict(value) for key, value in prior_outputs.items()}

    normalize_run_artifacts(run)

    path_risk = run["quantCore"]["coreInterpretation"]["pathRiskFilter"]
    visual = run["quantCore"]["coreInterpretation"]["visualDecisionPanel"]
    assert path_risk["riskPolicy"] in {"THROTTLE", "AVOID_NEW_BUY"}
    assert visual["riskGradient"]["riskPolicy"] == path_risk["riskPolicy"]
    assert visual["probabilityOddsMatrix"]["zone"] in {"WATCH", "FILTER"}
    assert any(item["key"] == "path_risk_qiam_divergence" for item in run["quantCore"]["coreInterpretation"]["conflicts"])
    assert "path_risk_gradient_high" in run["quantCore"]["coreInterpretation"]["riskFlags"]
    assert run["qiam"]["finalBuySuitability"] == "FAVORABLE"
    assert run["execution"]["allowedActions"] == execution["allowedActions"]
    assert run["signalOps"] == signal_ops
    assert run["finalAction"] == "WAIT"
    assert prior_outputs == prior_outputs_before_normalize
    mirror_output = {
        **run["quantCore"],
        "qiam": dict(run["qiam"]),
        "legacyAgentOutputs": {
            "qiam": dict(run["qiam"]),
            "quant_engine": dict(run["qiam"]),
        },
    }
    _mirror_quant_core_prior_outputs(prior_outputs, mirror_output)
    for key in ("qiam", "quant_engine"):
        assert prior_outputs[key]["finalBuySuitability"] == "FAVORABLE"
        assert prior_outputs[key]["probabilityBandDown"] == 0.82
        _assert_quant_core_legacy_marker(prior_outputs[key])
        assert "pathRiskFilter" not in prior_outputs[key]
        assert "coreInterpretation" not in prior_outputs[key]
        assert prior_outputs[key] != path_risk
    assert (
        run["finalContext"]["conclusion_derivation_inputs"]["core_interpretation"]["pathRiskFilter"]["version"]
        == "mfe_mae_path_risk_filter_v1"
    )
    assert (
        run["finalContext"]["conclusion_derivation_inputs"]["core_interpretation"]["visualDecisionPanel"]["version"]
        == "quant_core_visual_decision_panel_v1"
    )


def test_quant_core_interpretation_low_frequency_weights_and_ignored_missing_qiam_path():
    interpretation = build_quant_core_interpretation(
        {"taskType": "持仓复核", "quantEngine": {"mode": "LOW_FREQ_MID_LONG"}},
        marketTechnical={
            "market": _market_regime_data(),
            "technicalKline": _technical_kline_data(),
            "alignment": "NEUTRAL_OR_MIXED",
            "confidence": 0.7,
        },
        bottomResearch={
            "status": "PASS",
            "regimeState": "BOTTOM_REPAIR_ZONE",
            "bottomRepairProbability": 0.6,
            "breakdownRiskProbability": 0.25,
            "trendSynthesis": {"primaryTrendBias": "UP"},
            "modelDiagnostics": {"status": "READY"},
        },
        factorSlicing={
            "mode": "AUTO",
            "factorStability": 0.66,
            "missingFactorData": [],
            "factorDataSource": "RULE_DERIVED",
        },
        qiam={
            "finalBuySuitability": "FAVORABLE",
            "discountFactor": 0.95,
            "probabilityBandUp": 0.54,
            "probabilityBandDown": 0.2,
            "modelConfidenceFinal": 0.68,
            "ignoredMissingData": ["Level-2", "盘口深度"],
            "missingData": [],
        },
        scenario={"status": "PASS", "dvgPermission": "ALLOW"},
        quantEngine={"mode": "LOW_FREQ_MID_LONG"},
    )

    assert interpretation["weights"]["mfeMaeResearch"] == pytest.approx(0.30)
    assert interpretation["weights"]["qiam"] == pytest.approx(0.25)
    qiam_dimension = next(item for item in interpretation["dimensions"] if item["key"] == "qiam")
    assert qiam_dimension["score"] > 60
    assert not any("Level-2" in warning for warning in qiam_dimension["warnings"])


def test_quant_core_interpretation_fast_mode_reweights_skipped_bottom_research():
    interpretation = build_quant_core_interpretation(
        {"taskType": "交易机会发现", "runMode": "FAST_MODE", "quantEngine": {"mode": "HIGH_FREQ_SHORT"}},
        marketTechnical={
            "market": {**_market_regime_data(), "marketSentiment": "BULLISH"},
            "technicalKline": _technical_kline_data(),
            "alignment": "ALIGNED_BULLISH",
            "confidence": 0.78,
        },
        bottomResearch={
            "status": "SKIPPED",
            "regimeState": "DISABLED_BY_RUN_MODE",
            "missingData": ["run_mode_fast"],
        },
        factorSlicing={
            "mode": "AUTO",
            "factorStability": 0.7,
            "missingFactorData": [],
            "factorDataSource": "RULE_DERIVED",
        },
        qiam={
            "finalBuySuitability": "NEUTRAL",
            "discountFactor": 0.7,
            "probabilityBandUp": 0.36,
            "probabilityBandDown": 0.28,
            "modelConfidenceFinal": 0.6,
        },
        scenario={"status": "SKIPPED", "dvgPermission": "NOT_RUN_IN_FAST_MODE"},
        quantEngine={"mode": "HIGH_FREQ_SHORT"},
    )

    assert interpretation["weightAdjusted"] is True
    assert interpretation["weights"]["mfeMaeResearch"] == 0
    assert interpretation["weights"]["qiam"] == pytest.approx(0.30 / 0.85, abs=0.0001)
    assert any("MFE/MAE路径研究" in item for item in interpretation["weightAdjustmentReasons"])


def test_quant_core_interpretation_conflicts_do_not_mutate_permissions_or_final_action():
    bearish_technical = {**_technical_kline_data(), "technicalBias": "BEARISH", "confidence": 0.82}
    run = {
        "runId": "RUN_CORE_INTERPRET_CONFLICT",
        "taskType": "持仓复核",
        "quantEngine": {"mode": "LOW_FREQ_MID_LONG"},
        "marketTechnical": {
            "market": _market_regime_data(),
            "technicalKline": bearish_technical,
            "alignment": "CONFLICT",
            "confidence": 0.78,
        },
        "technicalKline": bearish_technical,
        "bottomResearch": {
            "status": "PASS",
            "regimeState": "BREAKDOWN_RISK",
            "bottomRepairProbability": 0.2,
            "breakdownRiskProbability": 0.72,
            "trendSynthesis": {"primaryTrendBias": "DOWN"},
            "modelDiagnostics": {"status": "READY"},
        },
        "factorSlicing": {
            "mode": "AUTO",
            "factorStability": 0.62,
            "missingFactorData": [],
            "factorDataSource": "RULE_DERIVED",
        },
        "qiam": {
            "rawBuySuitability": "FAVORABLE",
            "finalBuySuitability": "FAVORABLE",
            "discountFactor": 1.0,
            "probabilityBandUp": 0.58,
            "probabilityBandDown": 0.22,
            "modelConfidenceFinal": 0.7,
        },
        "quantCore": None,
        "execution": {"allowedActions": ["REVIEW_ONLY"], "forbiddenActions": ["BUY_CANDIDATE"]},
        "signalOps": {"signalStatus": "WATCH"},
        "finalAction": "WAIT",
        "finalContext": {"conclusion_derivation_inputs": {}},
        "nodes": [],
        "agentModuleResults": {},
    }

    normalize_run_artifacts(run)

    interpretation = run["quantCore"]["coreInterpretation"]
    assert {item["key"] for item in interpretation["conflicts"]} >= {
        "qiam_technical_divergence",
            "mfe_mae_risk_qiam_divergence",
    }
    assert any(item["severity"] == "BLOCKING_CONTEXT" for item in interpretation["conflicts"])
    assert run["qiam"]["finalBuySuitability"] == "FAVORABLE"
    assert run["finalAction"] == "WAIT"
    assert run["execution"]["allowedActions"] == ["REVIEW_ONLY"]
    assert run["finalContext"]["conclusion_derivation_inputs"]["core_interpretation"]["version"] == "quant_core_interpretation_v1"


def test_final_context_uses_bottom_research_after_artifact_normalization():
    run = {
        "runId": "RUN_BOTTOM_CONTEXT",
        "stockCode": "000001.SZ",
        "stockName": "Ping An",
        "taskType": "持仓复核",
        "runMode": "STANDARD_MODE",
        "agentModuleResults": {
            "bottom_research": {
                "data": {
                    "status": "PASS",
                    "bottomRepairProbability": 0.72,
                    "breakdownRiskProbability": 0.18,
                    "regimeState": "BOTTOM_REPAIR_ZONE",
                    "horizonForecasts": [{"horizonDays": 20, "trendBias": "UP"}],
                    "trendSynthesis": {"primaryHorizonDays": 20, "primaryTrendBias": "UP"},
                    "qiamAdjustmentPreview": {"direction": "UP", "maxStep": 1},
                }
            }
        },
        "dvg": {"dataReliability": "HIGH", "criticalMissingData": []},
        "qiam": {
            "finalBuySuitability": "NEUTRAL",
            "modelConfidenceFinal": 0.62,
            "probabilityBandUp": 0.4,
            "probabilityBandSideways": 0.35,
            "probabilityBandDown": 0.25,
        },
        "execution": {"executionReachability": "CONDITIONALLY_REACHABLE"},
        "marketData": {"quote": {"price": 10}},
        "market": {},
        "atrade": {},
        "factorSlicing": {},
        "portfolio": {},
    }

    result = apply_agent_framework_to_run(run, {"symbol": "000001.SZ", "task_type": "持仓复核"}, {})
    bottom_inputs = result["finalContext"]["conclusion_derivation_inputs"]["bottom_research"]

    assert result["bottomResearch"]["bottomRepairProbability"] == 0.72
    assert bottom_inputs["bottom_repair_probability"] == 0.72
    assert bottom_inputs["breakdown_risk_probability"] == 0.18
    assert bottom_inputs["trend_synthesis"]["primaryTrendBias"] == "UP"
    assert bottom_inputs["decision_policy"] == "CONTROLLED_ONE_STEP_QIAM_CALIBRATION_NO_TRADE_ACTION"


@pytest.mark.asyncio
async def test_execute_run_skips_non_executable_plugin_observation(monkeypatch):
    module_calls: list[str] = []
    llm_calls: list[str] = []

    def fake_run_agent_module(agent_id: str, run: dict, prior_outputs: dict) -> AgentResult:
        module_calls.append(agent_id)
        return AgentResult(node=agent_id, status="PASS", data={"agent": agent_id})

    async def fake_run_agent_llm(agent_id: str, run: dict, prior_outputs: dict) -> LLMRunResult:
        llm_calls.append(agent_id)
        return LLMRunResult(
            status="COMPLETED",
            provider="test",
            model="test-model",
            profile_id="test_profile",
            parsed_json={"status": "PASS", "agent": agent_id},
        )

    monkeypatch.setattr(agent_executor, "run_agent_module", fake_run_agent_module)
    monkeypatch.setattr(agent_executor, "run_agent_llm", fake_run_agent_llm)
    monkeypatch.setattr(
        agent_executor,
        "get_agent_execution_config",
        lambda agent_id: (
            SimpleNamespace(id=agent_id),
            SimpleNamespace(provider="test", model="test-model", id="test_profile", timeout_seconds=1),
        ),
    )
    monkeypatch.setattr(agent_executor, "save_run", lambda run: None)

    plugin_node_id = "plugin:technical_kline_readonly:technical_kline_analyst"
    run = {
        "runId": "RUN_PLUGIN_SKIP",
        "status": "CREATED",
        "nodes": [
            {"id": "orchestrator", "name": "Orchestrator", "status": "PASS", "isRunning": False, "isSkipped": False, "rawJson": {}},
            {
                "id": plugin_node_id,
                "name": "Readonly plugin",
                "status": "REVIEW_ONLY",
                "isRunning": False,
                "isSkipped": False,
                "auditId": "AUD_PLUGIN",
                "rawJson": {
                    "nodeType": "plugin_observation",
                    "dagRegistration": {"execution_mode": "PLAN_ONLY_NO_EXECUTION"},
                    "permissionSandbox": {"mode": "READ_ONLY_NO_CODE"},
                    "canExecuteCode": False,
                    "directExecution": False,
                },
            },
            {"id": "final_writer", "name": "Final Writer", "status": "PASS", "isRunning": False, "isSkipped": False, "rawJson": {}},
        ],
        "streamEvents": [],
        "auditLog": [],
        "agentOutputs": {},
        "agentModuleResults": {},
        "llmTrace": [],
    }

    await execute_run_with_llm("RUN_PLUGIN_SKIP", {"RUN_PLUGIN_SKIP": run})

    plugin_node = run["nodes"][1]
    assert run["status"] == "COMPLETED"
    assert module_calls == ["orchestrator", "final_writer"]
    assert llm_calls == ["orchestrator", "final_writer"]
    assert plugin_node["status"] == "REVIEW_ONLY"
    assert plugin_node["isSkipped"] is True
    assert plugin_node["rawJson"]["pluginObservation"]["status"] == "RECORDED_NO_EXECUTION"
    assert run["agentOutputs"][plugin_node_id]["status"] == "REVIEW_ONLY"
    assert {trace["nodeId"] for trace in run["llmTrace"]} == {"orchestrator", "final_writer"}
    assert any(event["event_type"] == "NODE_SKIPPED" and event["node_id"] == plugin_node_id for event in run["streamEvents"])


def test_quant_engine_submodules_populate_factor_slicing_before_qiam():
    run = {
        "marketData": {
            "status": "READY",
            "provider": "tushare",
            "quote": {
                "changePercent": 2.4,
                "volume": 32000000,
                "amount": 850000000,
            },
        },
        "auxiliaryData": {
            "fundamentals": {
                "status": "READY",
                "records": [{"roe": 12.5}],
            },
            "moneyflow": {
                "status": "READY",
                "records": [{"net_mf_amount": 12000000}],
            },
        },
        "factorSlicing": {
            "mode": "AUTO",
            "factors": [],
            "factorClusters": [],
            "regimeClassification": "UNKNOWN",
            "factorStability": 0,
            "missingFactorData": ["因子输入尚未完成拉取"],
            "factorDataSource": "PENDING",
        },
        "market": {"regimeClassification": "震荡"},
        "qiam": {},
    }
    prior_outputs = {}

    _run_quant_engine_submodules(run, prior_outputs)

    assert run["factorSlicing"]["factorDataSource"] == "RULE_DERIVED"
    assert len(run["factorSlicing"]["factors"]) >= 3
    assert {factor["name"] for factor in run["factorSlicing"]["factors"]}.issuperset({"Momentum", "Liquidity", "Volatility"})
    assert run["factorSlicing"]["missingFactorData"] == []
    assert run["factorEngine"]["factorCount"] == len(run["factorSlicing"]["factors"])
    assert prior_outputs["factor_slicing"]["factorDataSource"] == "RULE_DERIVED"
    assert "factor_engine" in prior_outputs
    assert "calculation_authority" in prior_outputs


def test_quant_engine_submodules_use_tushare_stk_factor_when_available():
    run = {
        "marketData": {
            "status": "READY",
            "provider": "tushare",
            "quote": {
                "changePercent": 0.8,
                "volume": 12000000,
                "amount": 280000000,
            },
        },
        "auxiliaryData": {
            "special_data": {
                "status": "READY",
                "provider": "tushare",
                "api_name": "stk_factor",
                "record_count": 2,
                "records": [
                    {
                        "trade_date": "20260520",
                        "pct_chg": 2.3,
                        "turnover_rate": 3.2,
                        "boll_upper": 13.0,
                        "boll_mid": 12.0,
                        "boll_lower": 11.2,
                    },
                    {"trade_date": "20260519", "pct_chg": -1.2, "turnover_rate": 1.1},
                ],
            }
        },
        "factorSlicing": {
            "mode": "AUTO",
            "factors": [],
            "factorClusters": [],
            "regimeClassification": "UNKNOWN",
            "factorStability": 0,
            "missingFactorData": ["因子输入尚未完成拉取"],
            "factorDataSource": "PENDING",
        },
        "market": {"regimeClassification": "震荡"},
        "qiam": {},
    }
    prior_outputs = {}

    _run_quant_engine_submodules(run, prior_outputs)

    assert run["factorSlicing"]["factorDataSource"] == "TUSHARE_STK_FACTOR"
    assert run["factorSlicing"]["missingFactorData"] == []
    assert {factor["name"] for factor in run["factorSlicing"]["factors"]} == {"Momentum", "Liquidity", "Volatility"}
    assert run["factorSlicing"]["provenance"]["provider"] == "tushare"
    assert run["factorSlicing"]["provenance"]["tradeDate"] == "20260520"
    assert run["factorEngine"]["engineMode"] == "FULL"
    assert prior_outputs["factor_slicing"]["factorDataSource"] == "TUSHARE_STK_FACTOR"


def test_quant_engine_high_frequency_mode_discounts_level2_and_depth_missing():
    run = {
        "taskType": "交易机会发现",
        "quantEngine": {"mode": "HIGH_FREQ_SHORT"},
        "dvg": {
            "qiamPermission": "ALLOW",
            "dataReliability": "HIGH",
            "activeModule": "dvg_low_frequency_mid_long",
            "dvgModules": {
                "lowFrequencyMidLong": {
                    "moduleId": "dvg_low_frequency_mid_long",
                    "quantEngineMode": "LOW_FREQ_MID_LONG",
                    "qiamPermission": "ALLOW",
                    "allowedOutputLevel": "FULL",
                    "coreUnknownCount": 0,
                    "ignoredMissingData": ["二级行情逐笔成交", "盘口深度", "资金流分解"],
                }
            },
        },
        "qiam": {
            "rawBuySuitability": "FAVORABLE",
            "missingData": ["Level-2", "盘口深度"],
        },
    }

    result = agent_executor.run_agent_module("quant_engine", run, {})
    _apply_agent_module_output_to_run(run, "quant_engine", result)

    assert run["qiam"]["discountFactor"] == pytest.approx(0.42)
    assert run["qiam"]["finalBuySuitability"] == "REVIEW_ONLY"
    assert run["qiam"]["ignoredMissingData"] == []
    assert any("Level-2" in reason for reason in run["qiam"]["downgradeReasons"])
    assert run["quantEngine"]["mode"] == "HIGH_FREQ_SHORT"


def test_quant_engine_low_frequency_mode_ignores_intraday_missing_for_discount():
    run = {
        "taskType": "持仓复核",
        "quantEngine": {"mode": "LOW_FREQ_MID_LONG"},
        "dvg": {"qiamPermission": "ALLOW", "dataReliability": "HIGH"},
        "qiam": {
            "rawBuySuitability": "FAVORABLE",
            "missingData": ["Level-2", "盘口深度", "分时逐笔"],
        },
    }

    result = agent_executor.run_agent_module("quant_engine", run, {})
    _apply_agent_module_output_to_run(run, "quant_engine", result)

    assert run["qiam"]["discountFactor"] == pytest.approx(1.0)
    assert run["qiam"]["finalBuySuitability"] == "FAVORABLE"
    assert run["qiam"]["missingData"] == []
    assert run["qiam"]["ignoredMissingData"] == ["Level-2", "盘口深度", "分时逐笔"]
    assert run["qiam"]["downgradeReasons"] == []
    assert run["quantEngine"]["ignoredMissingData"] == ["Level-2", "盘口深度", "分时逐笔"]


def test_quant_engine_low_frequency_repair_moves_high_frequency_qiam_discounts_to_ignored():
    stale_qiam = {
        "rawBuySuitability": "FAVORABLE",
        "missingData": ["二级行情逐笔成交", "盘口深度", "资金流分解", "模型版本"],
        "discountFactor": 0.063,
        "finalBuySuitability": "REVIEW_ONLY",
        "downgradeReasons": [
            "缺少二级行情: ×0.60",
            "缺少盘口深度: ×0.70",
            "缺少资金流分解: ×0.75",
            "缺少模型版本: ×0.50",
        ],
    }
    run = {
        "taskType": "持仓复核",
        "quantEngine": {"mode": "LOW_FREQ_MID_LONG"},
        "dvg": {
            "qiamPermission": "ALLOW",
            "dataReliability": "HIGH",
            "activeModule": "dvg_low_frequency_mid_long",
            "dvgModules": {
                "lowFrequencyMidLong": {
                    "moduleId": "dvg_low_frequency_mid_long",
                    "quantEngineMode": "LOW_FREQ_MID_LONG",
                    "qiamPermission": "ALLOW",
                    "allowedOutputLevel": "FULL",
                    "coreUnknownCount": 0,
                    "ignoredMissingData": ["二级行情逐笔成交", "盘口深度", "资金流分解"],
                }
            },
        },
        "marketData": {"quote": {"changePercent": 0}},
        "qiam": dict(stale_qiam),
        "quantCore": {
            "quantEngine": {"mode": "LOW_FREQ_MID_LONG"},
            "qiam": dict(stale_qiam),
        },
        "agentModuleResults": {
            "quant_core": {
                "data": {
                    "quantEngine": {"mode": "LOW_FREQ_MID_LONG"},
                    "qiam": dict(stale_qiam),
                    "legacyOutputs": {"quant_engine": {"data": dict(stale_qiam)}},
                    "legacyAgentOutputs": {"quant_engine": dict(stale_qiam)},
                }
            }
        },
    }

    assert sync_quant_engine_rule_outputs_from_current_inputs(run) is True

    assert run["qiam"]["missingData"] == ["模型版本"]
    assert run["qiam"]["ignoredMissingData"] == ["二级行情逐笔成交", "盘口深度", "资金流分解"]
    assert run["qiam"]["downgradeReasons"] == ["缺少模型版本: ×0.50"]
    assert run["qiam"]["discountFactor"] == pytest.approx(0.5)
    assert run["quantCore"]["qiam"]["downgradeReasons"] == ["缺少模型版本: ×0.50"]
    _assert_quant_core_legacy_marker(run["quantCore"]["legacyOutputs"]["quant_engine"])
    _assert_quant_core_legacy_marker(run["quantCore"]["legacyAgentOutputs"]["quant_engine"])
    quant_core_data = run["agentModuleResults"]["quant_core"]["data"]
    _assert_quant_core_legacy_marker(quant_core_data["legacyOutputs"]["quant_engine"])
    _assert_quant_core_legacy_marker(quant_core_data["legacyAgentOutputs"]["quant_engine"])
    assert run["agentModuleResults"]["quant_core"]["data"]["qiam"]["ignoredMissingData"] == [
        "二级行情逐笔成交",
        "盘口深度",
        "资金流分解",
    ]


def test_quant_engine_writeback_coerces_none_quant_engine():
    run = {
        "taskType": "鎸佷粨澶嶆牳",
        "quantEngine": None,
        "dvg": {"qiamPermission": "ALLOW", "dataReliability": "HIGH"},
        "qiam": {
            "rawBuySuitability": "FAVORABLE",
            "missingData": ["Level-2", "鐩樺彛娣卞害", "鍒嗘椂閫愮瑪"],
        },
    }

    run["taskType"] = "\u6301\u4ed3\u590d\u6838"
    run["qiam"]["missingData"] = ["Level-2", "\u76d8\u53e3\u6df1\u5ea6", "\u5206\u65f6\u9010\u7b14"]
    result = agent_executor.run_agent_module("quant_engine", run, {})
    _apply_agent_module_output_to_run(run, "quant_engine", result)

    assert isinstance(run["quantEngine"], dict)
    assert run["quantEngine"]["mode"] == "LOW_FREQ_MID_LONG"
    assert run["quantEngine"]["ignoredMissingData"] == ["Level-2", "\u76d8\u53e3\u6df1\u5ea6", "\u5206\u65f6\u9010\u7b14"]


def test_quant_engine_rule_repair_handles_none_quant_engine():
    run = {
        "runId": "RUN_QE_NONE",
        "taskType": "鎸佷粨澶嶆牳",
        "quantEngine": None,
        "status": "COMPLETED",
        "nodes": [],
        "agentModuleResults": {},
        "dvg": {
            "status": "PASS",
            "qiamPermission": "ALLOW_WITH_DISCOUNT",
            "dataReliability": "MEDIUM",
            "criticalMissingData": ["Level-2", "鐩樺彛娣卞害"],
        },
        "qiam": {
            "rawBuySuitability": "FAVORABLE",
            "missingData": ["Level-2", "鐩樺彛娣卞害"],
        },
    }

    run["taskType"] = "\u6301\u4ed3\u590d\u6838"
    run["dvg"]["criticalMissingData"] = ["Level-2", "\u76d8\u53e3\u6df1\u5ea6"]
    run["qiam"]["missingData"] = ["Level-2", "\u76d8\u53e3\u6df1\u5ea6"]
    assert sync_quant_engine_rule_outputs_from_current_inputs(run) is True
    normalize_run_artifacts(run)

    assert isinstance(run["quantEngine"], dict)
    assert run["quantEngine"]["mode"] == "LOW_FREQ_MID_LONG"
    assert run["quantEngine"]["ignoredMissingData"]
    assert "dvg_gate" in run["agentModuleResults"]
    assert "quant_engine" in run["agentModuleResults"]


def test_quant_engine_replaces_pending_seed_zero_scores_with_rule_defaults():
    run = {
        "taskType": "持仓复核",
        "quantEngine": {"mode": "LOW_FREQ_MID_LONG"},
        "dvg": {"qiamPermission": "ALLOW", "dataReliability": "MEDIUM"},
        "marketData": {"quote": {"changePercent": 0}},
        "qiam": {
            "rawBuySuitability": "NEUTRAL",
            "probabilitySource": "PENDING",
            "expectedPayoffQuality": 0,
            "regimeFit": 0,
            "momentumQuality": 0,
            "volatilityCondition": 0,
            "liquidityAdjustedSignal": 0,
            "modelConfidenceRaw": 0,
            "modelConfidenceFinal": 0,
            "overfitRisk": 0,
            "distributionDrift": 0,
            "decisionEffect": 0,
            "missingData": ["QIAM 输入尚未完成拉取"],
        },
    }

    result = agent_executor.run_agent_module("quant_engine", run, {})

    assert result.data["expectedPayoffQuality"] == 0.65
    assert result.data["regimeFit"] == 0.7
    assert result.data["momentumQuality"] == 0.55
    assert result.data["volatilityCondition"] == 0.6
    assert result.data["liquidityAdjustedSignal"] == 0.58
    assert result.data["modelConfidenceRaw"] == 0.75
    assert result.data["modelConfidenceFinal"] == 0.62
    assert result.data["overfitRisk"] == 0.2
    assert result.data["distributionDrift"] == 0.15
    assert result.data["decisionEffect"] == 0.8
    assert any(item["category"] == "QIAM_INPUT" for item in result.data["remediationItems"])


def test_quant_engine_clears_pending_qiam_seed_when_submodules_completed():
    run = {
        "taskType": "持仓复核",
        "quantEngine": {"mode": "LOW_FREQ_MID_LONG"},
        "dvg": {"qiamPermission": "ALLOW", "dataReliability": "HIGH"},
        "marketData": {"quote": {"changePercent": 0}},
        "technicalKline": {
            "agent": "technical_kline_analyst",
            "status": "WARN",
            "technicalBias": "BULLISH",
            "confidence": 0.86,
            "dataQuality": {
                "provider": "tushare",
                "dataMode": "LIVE",
                "dailyCount": 76,
            },
        },
        "factorSlicing": {
            "factorDataSource": "TUSHARE_STK_FACTOR",
            "missingFactorData": [],
            "factors": [{"name": "Value", "weight": 0.35, "contribution": 0.01, "confidence": 0.72}],
        },
        "factorEngine": {"engineMode": "FULL", "factorCount": 1},
        "calculationAuthority": {
            "hasCalculationTools": False,
            "calculationToolStatus": "UNKNOWN",
            "llmCalculationProhibited": True,
        },
        "qiam": {
            "rawBuySuitability": "FAVORABLE",
            "probabilitySource": "PENDING",
            "missingData": ["QIAM 输入尚未完成拉取"],
        },
    }

    result = agent_executor.run_agent_module("quant_engine", run, {})

    assert result.data["missingData"] == []
    assert result.data["discountFactor"] == pytest.approx(1.0)
    assert result.data["finalBuySuitability"] == "FAVORABLE"
    assert all("QIAM 输入尚未完成" not in reason for reason in result.data["downgradeReasons"])
    assert {item["category"] for item in result.data["remediationItems"]} == set()


def test_quant_engine_replaces_pending_seed_with_real_factor_missing_data():
    run = {
        "taskType": "持仓复核",
        "quantEngine": {"mode": "LOW_FREQ_MID_LONG"},
        "dvg": {"qiamPermission": "ALLOW", "dataReliability": "HIGH"},
        "marketData": {"quote": {"changePercent": 0}},
        "technicalKline": {
            "agent": "technical_kline_analyst",
            "status": "WARN",
            "technicalBias": "BULLISH",
            "confidence": 0.86,
            "dataQuality": {
                "provider": "tushare",
                "dataMode": "LIVE",
                "dailyCount": 76,
            },
        },
        "factorSlicing": {
            "factorDataSource": "TUSHARE_STK_FACTOR",
            "missingFactorData": ["样本外验证"],
            "factors": [{"name": "Value", "weight": 0.35, "contribution": 0.01, "confidence": 0.72}],
        },
        "factorEngine": {"engineMode": "FULL", "factorCount": 1},
        "calculationAuthority": {
            "hasCalculationTools": False,
            "calculationToolStatus": "UNKNOWN",
            "llmCalculationProhibited": True,
        },
        "qiam": {
            "rawBuySuitability": "FAVORABLE",
            "probabilitySource": "PENDING",
            "missingData": ["QIAM 输入尚未完成拉取"],
        },
    }

    result = agent_executor.run_agent_module("quant_engine", run, {})

    assert result.data["missingData"] == ["样本外验证"]
    assert result.data["discountFactor"] == pytest.approx(0.5)
    assert result.data["finalBuySuitability"] == "REVIEW_ONLY"
    assert all("QIAM 输入尚未完成" not in reason for reason in result.data["downgradeReasons"])
    assert any("缺少样本外验证" in reason for reason in result.data["downgradeReasons"])
    assert {item["category"] for item in result.data["remediationItems"]} == {"DATA_GAP"}


def test_quant_engine_prefers_verified_canonical_technical_over_prior_llm_output():
    run = {
        "taskType": "持仓复核",
        "quantEngine": {"mode": "LOW_FREQ_MID_LONG"},
        "dvg": {"qiamPermission": "ALLOW", "dataReliability": "HIGH"},
        "marketData": {"quote": {"changePercent": 0}},
        "technicalKline": {
            "agent": "technical_kline_analyst",
            "status": "PASS",
            "technicalBias": "BULLISH",
            "confidence": 0.86,
            "dataQuality": {
                "provider": "tushare",
                "dataMode": "LIVE",
                "dailyCount": 76,
                "weeklyCount": 12,
                "monthlyCount": 5,
            },
            "summaryForDownstream": "canonical LIVE Tushare K-line",
        },
        "qiam": {
            "rawBuySuitability": "FAVORABLE",
            "missingData": [],
        },
    }
    stale_prior = {
        "technicalBias": "INSUFFICIENT_DATA",
        "confidence": 0.0,
        "dataQuality": {"dailySamples": 0, "sourceStatus": "MISSING"},
        "summaryForDownstream": "stale LLM output",
    }

    result = agent_executor.run_agent_module(
        "quant_engine",
        run,
        {"technical_kline_analyst": stale_prior},
    )

    assert result.data["technicalKlineConstraint"]["confidence"] == 0.86
    assert result.data["technicalKlineConstraint"]["summary"] == "canonical LIVE Tushare K-line"
    assert result.data["technicalKlineConstraint"]["appliedFactor"] == 1.0
    assert all("technicalKline low confidence=0.00" not in reason for reason in result.data["downgradeReasons"])


def _bottom_research_payload(
    *,
    repair: float = 0.82,
    breakdown: float = 0.12,
    evidence_grade: str = "MEDIUM",
    trend_bias: str = "UP",
) -> dict:
    probability_series = [
        {
            "tradeDate": f"2026-04-{index + 1:02d}",
            "horizonDays": 20,
            "predictionUpProbability": 0.62 if index % 3 else 0.48,
            "predictionDownProbability": 0.22 if index % 3 else 0.38,
            "actualUpLabel": 1 if index % 3 else 0,
            "actualDownLabel": 0 if index % 3 else 1,
            "actualForwardReturn": 0.03 if index % 3 else -0.02,
            "actualDirection": "UP" if index % 3 else "DOWN",
            "labelStatus": "LABELED_HISTORICAL",
        }
        for index in range(35)
    ]
    return {
        "status": "PASS",
        "bottomRepairProbability": repair,
        "breakdownRiskProbability": breakdown,
        "regimeState": "BOTTOM_REPAIR_ZONE" if breakdown < 0.5 else "BREAKDOWN_RISK",
        "currentPrediction": {
            "tradeDate": "2026-05-26",
            "bottomRepairProbability": repair,
            "breakdownRiskProbability": breakdown,
            "regimeState": "BOTTOM_REPAIR_ZONE" if breakdown < 0.5 else "BREAKDOWN_RISK",
            "horizonDays": 20,
            "labelStatus": "UNLABELED_NOWCAST",
        },
        "horizonForecasts": [
            {
                "horizonDays": 20,
                "status": "READY",
                "bottomRepairProbability": repair,
                "breakdownRiskProbability": breakdown,
                "trendProbabilities": {"up": repair, "sideways": max(0.0, 1.0 - repair - breakdown), "down": breakdown},
                "trendBias": trend_bias,
                "evidenceGrade": evidence_grade,
            }
        ],
        "probabilitySeries": probability_series,
        "horizonProbabilitySeries": [{"horizonDays": 20, "series": probability_series}],
        "trendSynthesis": {
            "primaryHorizonDays": 20,
            "primaryTrendBias": trend_bias,
            "horizonAlignment": "ALIGNED",
            "evidenceConflict": False,
        },
        "config": {"repair_probability_threshold": 0.60, "horizon_days": 20},
    }


def test_quant_engine_applies_positive_bottom_research_one_step_calibration():
    run = {
        "taskType": "持仓复核",
        "quantEngine": {"mode": "LOW_FREQ_MID_LONG"},
        "dvg": {"qiamPermission": "ALLOW", "dataReliability": "HIGH"},
        "marketData": {"quote": {"changePercent": 0}},
        "technicalKline": {
            "agent": "technical_kline_analyst",
            "status": "PASS",
            "technicalBias": "BULLISH",
            "confidence": 0.86,
            "dataQuality": {"provider": "tushare", "dataMode": "LIVE", "dailyCount": 76},
        },
        "bottomResearch": _bottom_research_payload(),
        "qiam": {"rawBuySuitability": "NEUTRAL", "missingData": []},
    }

    result = agent_executor.run_agent_module("quant_engine", run, {})

    assert result.data["finalBuySuitability"] == "FAVORABLE"
    adjustment = result.data["bottomResearchAdjustment"]
    assert adjustment["applied"] is True
    assert adjustment["direction"] == "UP"
    assert adjustment["beforeFinalBuySuitability"] == "NEUTRAL"
    assert adjustment["afterFinalBuySuitability"] == "FAVORABLE"
    assert adjustment["canCreateTradeAction"] is False


def test_quant_engine_does_not_mark_noop_positive_bottom_adjustment_applied():
    run = {
        "taskType": "持仓复核",
        "quantEngine": {"mode": "LOW_FREQ_MID_LONG"},
        "dvg": {"qiamPermission": "ALLOW", "dataReliability": "HIGH"},
        "marketData": {"quote": {"changePercent": 0}},
        "bottomResearch": _bottom_research_payload(),
        "qiam": {"rawBuySuitability": "FAVORABLE", "missingData": []},
    }

    result = agent_executor.run_agent_module("quant_engine", run, {})

    adjustment = result.data["bottomResearchAdjustment"]
    assert result.data["finalBuySuitability"] == "FAVORABLE"
    assert adjustment["applied"] is False
    assert adjustment["direction"] == "UP"
    assert adjustment["reason"] == "already_at_upper_bound"
    assert adjustment["beforeFinalBuySuitability"] == "FAVORABLE"
    assert adjustment["afterFinalBuySuitability"] == "FAVORABLE"


def test_quant_engine_blocks_positive_bottom_research_when_dvg_is_discounted():
    run = {
        "taskType": "持仓复核",
        "quantEngine": {"mode": "LOW_FREQ_MID_LONG"},
        "dvg": {"qiamPermission": "ALLOW_WITH_DISCOUNT", "dataReliability": "MEDIUM"},
        "marketData": {"quote": {"changePercent": 0}},
        "technicalKline": {
            "agent": "technical_kline_analyst",
            "status": "PASS",
            "technicalBias": "BULLISH",
            "confidence": 0.86,
            "dataQuality": {"provider": "tushare", "dataMode": "LIVE", "dailyCount": 76},
        },
        "bottomResearch": _bottom_research_payload(),
        "qiam": {"rawBuySuitability": "NEUTRAL", "missingData": []},
    }

    result = agent_executor.run_agent_module("quant_engine", run, {})

    assert result.data["finalBuySuitability"] == "NEUTRAL"
    adjustment = result.data["bottomResearchAdjustment"]
    assert adjustment["applied"] is False
    assert adjustment["direction"] == "UP"
    assert "dvg_permission_ALLOW_WITH_DISCOUNT" in adjustment["blockedReasons"]


def test_quant_engine_does_not_mark_noop_negative_bottom_adjustment_applied():
    run = {
        "taskType": "持仓复核",
        "quantEngine": {"mode": "LOW_FREQ_MID_LONG"},
        "dvg": {"qiamPermission": "BLOCKED", "dataReliability": "LOW"},
        "marketData": {"quote": {"changePercent": 0}},
        "bottomResearch": _bottom_research_payload(repair=0.30, breakdown=0.64, trend_bias="DOWN"),
        "qiam": {"rawBuySuitability": "NEUTRAL", "missingData": []},
    }

    result = agent_executor.run_agent_module("quant_engine", run, {})

    adjustment = result.data["bottomResearchAdjustment"]
    assert result.data["finalBuySuitability"] == "BLOCK_BUY"
    assert adjustment["applied"] is False
    assert adjustment["direction"] == "DOWN"
    assert adjustment["reason"] == "already_at_lower_bound"
    assert adjustment["beforeFinalBuySuitability"] == "BLOCK_BUY"
    assert adjustment["afterFinalBuySuitability"] == "BLOCK_BUY"


def test_normalize_run_artifacts_syncs_bottom_before_qiam_repair():
    run = {
        "runId": "RUN_BOTTOM_QIAM_REPAIR",
        "stockCode": "000001.SZ",
        "stockName": "Ping An",
        "taskType": "持仓复核",
        "runMode": "STANDARD_MODE",
        "quantEngine": {"mode": "LOW_FREQ_MID_LONG"},
        "marketData": {"quote": {"changePercent": 0}},
        "dvg": {
            "qiamPermission": "ALLOW",
            "dataReliability": "HIGH",
            "criticalMissingData": [],
            "activeModule": "dvg_low_frequency_mid_long",
            "dvgModules": {},
        },
        "qiam": {
            "rawBuySuitability": "NEUTRAL",
            "finalBuySuitability": "REVIEW_ONLY",
            "missingData": [],
            "downgradeReasons": ["DVG ALLOW_WITH_DISCOUNT: ×0.70"],
        },
        "agentModuleResults": {
            "bottom_research": {
                "data": _bottom_research_payload(),
            },
        },
    }

    normalize_run_artifacts(run)

    assert run["bottomResearch"]["bottomRepairProbability"] == 0.82
    adjustment = run["qiam"]["bottomResearchAdjustment"]
    assert adjustment["observed"] is True
    assert adjustment["applied"] is True
    assert adjustment["direction"] == "UP"
    assert adjustment["beforeFinalBuySuitability"] == "NEUTRAL"
    assert adjustment["afterFinalBuySuitability"] == "FAVORABLE"


def test_quant_engine_applies_negative_bottom_research_on_bearish_conflict():
    run = {
        "taskType": "持仓复核",
        "quantEngine": {"mode": "LOW_FREQ_MID_LONG"},
        "dvg": {"qiamPermission": "ALLOW", "dataReliability": "HIGH"},
        "marketData": {"quote": {"changePercent": 0}},
        "technicalKline": {
            "agent": "technical_kline_analyst",
            "status": "WARN",
            "technicalBias": "BEARISH",
            "confidence": 0.82,
            "dataQuality": {"provider": "tushare", "dataMode": "LIVE", "dailyCount": 76},
        },
        "bottomResearch": _bottom_research_payload(),
        "qiam": {"rawBuySuitability": "FAVORABLE", "missingData": []},
    }

    result = agent_executor.run_agent_module("quant_engine", run, {})

    adjustment = result.data["bottomResearchAdjustment"]
    assert adjustment["applied"] is True
    assert adjustment["direction"] == "DOWN"
    assert adjustment["beforeFinalBuySuitability"] == "NEUTRAL"
    assert adjustment["afterFinalBuySuitability"] == "REVIEW_ONLY"
    assert result.data["finalBuySuitability"] == "REVIEW_ONLY"


def test_quant_engine_applies_negative_bottom_research_on_breakdown_risk():
    run = {
        "taskType": "持仓复核",
        "quantEngine": {"mode": "LOW_FREQ_MID_LONG"},
        "dvg": {"qiamPermission": "ALLOW", "dataReliability": "HIGH"},
        "marketData": {"quote": {"changePercent": 0}},
        "technicalKline": {
            "agent": "technical_kline_analyst",
            "status": "PASS",
            "technicalBias": "NEUTRAL",
            "confidence": 0.72,
            "dataQuality": {"provider": "tushare", "dataMode": "LIVE", "dailyCount": 76},
        },
        "bottomResearch": _bottom_research_payload(repair=0.30, breakdown=0.64, trend_bias="DOWN"),
        "qiam": {"rawBuySuitability": "NEUTRAL", "missingData": []},
    }

    result = agent_executor.run_agent_module("quant_engine", run, {})

    assert result.data["finalBuySuitability"] == "REVIEW_ONLY"
    assert result.data["bottomResearchAdjustment"]["direction"] == "DOWN"
    assert result.data["bottomResearchAdjustment"]["applied"] is True


def test_quant_engine_generates_remediation_items_for_qiam_dvg_and_technical():
    run = {
        "taskType": "持仓复核",
        "quantEngine": {"mode": "LOW_FREQ_MID_LONG"},
        "dvg": {
            "qiamPermission": "ALLOW_WITH_DISCOUNT",
            "dataReliability": "MEDIUM",
            "criticalMissingData": ["资金流分解"],
        },
        "marketData": {"quote": {"changePercent": 0}},
        "qiam": {
            "rawBuySuitability": "NEUTRAL",
            "probabilitySource": "PENDING",
            "missingData": ["QIAM 输入尚未完成拉取"],
        },
    }
    prior_outputs = {
        "technical_kline_analyst": {
            "agent": "technical_kline_analyst",
            "status": "WARN",
            "technicalBias": "BULLISH",
            "confidence": 0.0,
            "dataQuality": {"provider": "tushare", "dataMode": "UNAVAILABLE", "dailyCount": 0},
        }
    }

    result = agent_executor.run_agent_module("quant_engine", run, prior_outputs)
    categories = {item["category"] for item in result.data["remediationItems"]}

    assert {"QIAM_INPUT", "DVG", "TECHNICAL_KLINE"}.issubset(categories)


def test_sync_quant_engine_rule_outputs_repairs_stale_qiam_dvg_and_technical_from_current_inputs():
    run = {
        "taskType": "持仓复核",
        "quantEngine": {"mode": "LOW_FREQ_MID_LONG"},
        "dataSources": {
            "sources": {
                "quote": {
                    "name": "实时行情",
                    "status": "READY",
                    "dataMode": "LIVE",
                    "available": True,
                    "provider": "tushare",
                },
            },
        },
        "marketData": {"freshness": "REALTIME", "quote": {"changePercent": 0}},
        "technicalKline": {
            "agent": "technical_kline_analyst",
            "status": "WARN",
            "technicalBias": "BULLISH",
            "confidence": 0.86,
            "dataQuality": {
                "provider": "tushare",
                "dataMode": "LIVE",
                "dailyCount": 76,
            },
            "summaryForDownstream": "canonical LIVE Tushare K-line",
        },
        "atrade": {
            "level2Available": False,
            "depthAvailable": False,
        },
        "dvg": {
            "qiamPermission": "ALLOW_WITH_DISCOUNT",
            "criticalMissingData": ["技术面 K 线真实数据校验", "Level-2 逐笔成交", "盘口深度"],
            "hallucinationRiskScore": 31,
        },
        "factorSlicing": {
            "factorDataSource": "TUSHARE_STK_FACTOR",
            "missingFactorData": [],
            "factors": [{"name": "Value", "weight": 0.35, "contribution": 0.01, "confidence": 0.72}],
        },
        "factorEngine": {"engineMode": "FULL", "factorCount": 1},
        "calculationAuthority": {
            "hasCalculationTools": False,
            "calculationToolStatus": "UNKNOWN",
            "llmCalculationProhibited": True,
        },
        "qiam": {
            "rawBuySuitability": "FAVORABLE",
            "probabilitySource": "RULE_DERIVED",
            "missingData": ["QIAM 输入尚未完成拉取"],
            "discountFactor": 0.44625,
            "finalBuySuitability": "REVIEW_ONLY",
            "downgradeReasons": [
                "缺少QIAM 输入尚未完成拉取: ×0.85",
                "DVG ALLOW_WITH_DISCOUNT: ×0.70",
                "technicalKline low confidence=0.00: x0.75",
            ],
            "technicalKlineConstraint": {
                "observed": True,
                "bias": "INSUFFICIENT_DATA",
                "confidence": 0.0,
                "appliedFactor": 0.75,
                "downgradeReason": "technicalKline low confidence=0.00: x0.75",
            },
        },
        "agentModuleResults": {
            "dvg_gate": {
                "data": {
                    "qiamPermission": "ALLOW_WITH_DISCOUNT",
                    "criticalMissingData": ["技术面 K 线真实数据校验", "Level-2 逐笔成交", "盘口深度"],
                }
            },
            "quant_engine": {
                "data": {
                    "missingData": ["QIAM 输入尚未完成拉取"],
                    "downgradeReasons": [
                        "缺少QIAM 输入尚未完成拉取: ×0.85",
                        "DVG ALLOW_WITH_DISCOUNT: ×0.70",
                        "technicalKline low confidence=0.00: x0.75",
                    ],
                }
            },
        },
    }

    assert sync_quant_engine_rule_outputs_from_current_inputs(run) is True

    assert run["dvg"]["activeModule"] == "dvg_low_frequency_mid_long"
    assert run["dvg"]["qiamPermission"] == "ALLOW"
    assert run["dvg"]["criticalMissingData"] == []
    assert run["dvg"]["ignoredMissingData"] == ["Level-2 逐笔成交", "盘口深度"]
    assert run["qiam"]["missingData"] == []
    assert run["qiam"]["discountFactor"] == pytest.approx(1.0)
    assert run["qiam"]["finalBuySuitability"] == "FAVORABLE"
    assert run["qiam"]["technicalKlineConstraint"]["confidence"] == 0.86
    assert run["qiam"]["technicalKlineConstraint"]["appliedFactor"] == 1.0
    assert run["qiam"]["downgradeReasons"] == []
    assert run["qiam"]["remediationItems"] == []


def test_qiam_llm_unknown_probability_preserves_rule_derived_bands():
    run = {
        "qiam": {
            "probabilityBandUp": 0.1414,
            "probabilityBandSideways": 0.4231,
            "probabilityBandDown": 0.4355,
            "probabilitySource": "RULE_DERIVED",
        }
    }

    _apply_qiam_output(
        run,
        {
            "probability_band_up": "UNKNOWN",
            "probability_band_sideways": "UNKNOWN",
            "probability_band_down": "UNKNOWN",
            "final_buy_suitability": "REVIEW_ONLY",
        },
    )

    assert run["qiam"]["probabilityBandUp"] == 0.1414
    assert run["qiam"]["probabilityBandSideways"] == 0.4231
    assert run["qiam"]["probabilityBandDown"] == 0.4355
    assert run["qiam"]["probabilitySource"] == "RULE_DERIVED"


def test_qiam_llm_unknown_scores_preserve_rule_derived_fallbacks():
    run = {
        "qiam": {
            "expectedPayoffQuality": 0.65,
            "regimeFit": 0.7,
            "momentumQuality": 0.55,
            "volatilityCondition": 0.6,
            "liquidityAdjustedSignal": 0.58,
            "modelConfidenceRaw": 0.75,
            "modelConfidenceFinal": 0.62,
            "overfitRisk": 0.2,
            "distributionDrift": 0.15,
            "decisionEffect": 0.8,
        }
    }

    _apply_qiam_output(
        run,
        {
            "expected_payoff_quality": "UNKNOWN",
            "regime_fit": "UNKNOWN",
            "momentum_quality": "UNKNOWN",
            "volatility_condition": "UNKNOWN",
            "liquidity_adjusted_signal": "UNKNOWN",
            "model_confidence_raw": "UNKNOWN",
            "model_confidence_final": "LOW",
            "overfit_risk": "UNKNOWN",
            "distribution_drift": "UNKNOWN",
            "decision_effect": "UNKNOWN",
        },
    )

    assert run["qiam"]["expectedPayoffQuality"] == 0.65
    assert run["qiam"]["regimeFit"] == 0.7
    assert run["qiam"]["momentumQuality"] == 0.55
    assert run["qiam"]["volatilityCondition"] == 0.6
    assert run["qiam"]["liquidityAdjustedSignal"] == 0.58
    assert run["qiam"]["modelConfidenceRaw"] == 0.75
    assert run["qiam"]["modelConfidenceFinal"] == 0.25
    assert run["qiam"]["overfitRisk"] == 0.2
    assert run["qiam"]["distributionDrift"] == 0.15
    assert run["qiam"]["decisionEffect"] == 0.8


def test_sync_qiam_probability_repairs_flat_canonical_bands_from_module_result():
    run = {
        "qiam": {
            "probabilityBandUp": 0.3333,
            "probabilityBandSideways": 0.3333,
            "probabilityBandDown": 0.3333,
            "probabilitySource": "RULE_DERIVED",
            "llmOutput": {
                "probability_band_up": "UNKNOWN",
                "probability_band_sideways": "UNKNOWN",
                "probability_band_down": "UNKNOWN",
            },
        },
        "agentModuleResults": {
            "quant_engine": {
                "data": {
                    "probabilityBandUp": 0.1414,
                    "probabilityBandSideways": 0.4515,
                    "probabilityBandDown": 0.4071,
                    "probabilitySource": "RULE_DERIVED",
                }
            }
        },
    }

    assert sync_qiam_probability_from_agent_module(run) is True
    assert run["qiam"]["probabilityBandUp"] == 0.1414
    assert run["qiam"]["probabilityBandSideways"] == 0.4515
    assert run["qiam"]["probabilityBandDown"] == 0.4071
    assert run["qiam"]["probabilityRepairSource"] == "agentModuleResults.quant_engine.data"


def test_sync_qiam_score_fields_repairs_unknown_zeroed_scores_from_module_result():
    run = {
        "qiam": {
            "expectedPayoffQuality": 0,
            "regimeFit": 0,
            "momentumQuality": 0,
            "volatilityCondition": 0,
            "liquidityAdjustedSignal": 0,
            "modelConfidenceRaw": 0,
            "modelConfidenceFinal": 0.25,
            "overfitRisk": 0,
            "distributionDrift": 0,
            "decisionEffect": 0,
            "llmOutput": {
                "expected_payoff_quality": "UNKNOWN",
                "regime_fit": "UNKNOWN",
                "momentum_quality": "UNKNOWN",
                "volatility_condition": "UNKNOWN",
                "liquidity_adjusted_signal": "UNKNOWN",
                "model_confidence_raw": "UNKNOWN",
                "model_confidence_final": "LOW",
                "overfit_risk": "UNKNOWN",
                "distribution_drift": "UNKNOWN",
                "decision_effect": "BLOCK_BUY",
            },
        },
        "agentModuleResults": {
            "quant_engine": {
                "data": {
                    "expectedPayoffQuality": 0.65,
                    "regimeFit": 0.7,
                    "momentumQuality": 0.55,
                    "volatilityCondition": 0.6,
                    "liquidityAdjustedSignal": 0.58,
                    "modelConfidenceRaw": 0.75,
                    "modelConfidenceFinal": 0.62,
                    "overfitRisk": 0.2,
                    "distributionDrift": 0.15,
                    "decisionEffect": 0.8,
                }
            }
        },
    }

    assert sync_qiam_score_fields_from_agent_module(run) is True
    assert run["qiam"]["expectedPayoffQuality"] == 0.65
    assert run["qiam"]["regimeFit"] == 0.7
    assert run["qiam"]["momentumQuality"] == 0.55
    assert run["qiam"]["volatilityCondition"] == 0.6
    assert run["qiam"]["liquidityAdjustedSignal"] == 0.58
    assert run["qiam"]["modelConfidenceRaw"] == 0.75
    assert run["qiam"]["modelConfidenceFinal"] == 0.25
    assert run["qiam"]["overfitRisk"] == 0.2
    assert run["qiam"]["distributionDrift"] == 0.15
    assert run["qiam"]["decisionEffect"] == 0
    assert run["qiam"]["scoreRepairSource"] == "agentModuleResults.quant_engine.data"


def test_sync_qiam_score_fields_repairs_unknown_zeroed_final_confidence():
    run = {
        "qiam": {
            "modelConfidenceFinal": 0,
            "llmOutput": {
                "model_confidence_final": "UNKNOWN",
            },
        },
        "agentModuleResults": {
            "quant_engine": {
                "data": {
                    "modelConfidenceFinal": 0.62,
                }
            }
        },
    }

    assert sync_qiam_score_fields_from_agent_module(run) is True
    assert run["qiam"]["modelConfidenceFinal"] == 0.62
    assert run["qiam"]["scoreRepairSource"] == "agentModuleResults.quant_engine.data"
