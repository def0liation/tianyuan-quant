import copy
from pathlib import Path

import pytest

from app.api import routes_analysis
from app.core import (
    agent_framework,
    analysis_run_create,
    analysis_run_compare,
    analysis_run_persistence,
    analysis_run_retry,
    analysis_run_start,
)
from app.core.agent_framework import apply_agent_framework_to_run, apply_quant_core_data
from app.mock.scenarios import mock_scenarios
from app.models import analysis as analysis_models
from app.models.analysis import AnalysisRun, CreateAnalysisRequest


def test_retry_legacy_quant_core_node_ids_are_canonicalized():
    run = {"nodes": [{"id": "orchestrator"}, {"id": "quant_core"}, {"id": "execution"}]}

    for node_id in [
        "market_regime",
        "technical_kline_analyst",
        "market_technical_analyst",
        "bottom_research",
        "quant_engine",
        "qiam",
        "scenario_engine",
    ]:
        assert routes_analysis._retry_legacy_node_id(run, node_id) == "quant_core"
        assert analysis_run_retry.retry_legacy_node_id(run, node_id) == "quant_core"


def test_analysis_compare_logic_lives_in_core_service():
    route_source = Path(routes_analysis.__file__).read_text(encoding="utf-8")
    compare_source = Path(analysis_run_compare.__file__).read_text(encoding="utf-8")

    assert "analysis_run_compare.compare_runs" in route_source
    assert "def _diff_impact" not in route_source
    assert "def compare_runs" in compare_source
    assert "fastapi" not in compare_source


def test_analysis_persist_logic_lives_in_core_service():
    route_source = Path(routes_analysis.__file__).read_text(encoding="utf-8")
    persistence_source = Path(analysis_run_persistence.__file__).read_text(encoding="utf-8")

    assert "analysis_run_persistence.persist_run" in route_source
    assert "AgentResultRepository" not in route_source
    assert "SignalOpsRepo" not in route_source
    assert "def persist_run" in persistence_source
    assert "fastapi" not in persistence_source


def test_analysis_retry_logic_lives_in_core_service():
    route_source = Path(routes_analysis.__file__).read_text(encoding="utf-8")
    retry_source = Path(analysis_run_retry.__file__).read_text(encoding="utf-8")

    assert "analysis_run_retry.prepare_retry" in route_source
    assert "def prepare_retry" in retry_source
    assert "NON_EXECUTABLE_PLUGIN_OBSERVATION_REASON" not in route_source
    assert "fastapi" not in retry_source


def test_analysis_start_logic_lives_in_core_service():
    route_source = Path(routes_analysis.__file__).read_text(encoding="utf-8")
    start_source = Path(analysis_run_start.__file__).read_text(encoding="utf-8")

    assert "analysis_run_start.check_start_preflight" in route_source
    assert "analysis_run_start.prepare_start" in route_source
    assert '"RUN_QUEUED"' not in route_source
    assert "def prepare_start" in start_source
    assert "simulation_only" in start_source
    assert "is_real_trade" in start_source
    assert "fastapi" not in start_source


def test_analysis_create_logic_lives_in_core_service():
    route_source = Path(routes_analysis.__file__).read_text(encoding="utf-8")
    create_source = Path(analysis_run_create.__file__).read_text(encoding="utf-8")

    assert "analysis_run_create.build_created_run" in route_source
    assert '"PORTFOLIO_SNAPSHOT_ATTACHED"' not in route_source
    assert "def build_created_run" in create_source
    assert "Portfolio snapshot not found" in create_source
    assert "fastapi" not in create_source


def test_real_run_seed_initializes_pending_guardrail_hub_canonical_owner():
    seed = analysis_run_create.real_run_seed(mock_scenarios["qiam_discounted"])
    guardrail = seed["guardrailHub"]
    paper = seed["paperTrading"]

    assert guardrail["status"] == "PENDING"
    assert guardrail["killSwitch"] == seed["killSwitch"]
    assert guardrail["killSwitch"]["triggerNode"] == ""
    assert guardrail["dvg"]["provenance"]["sourceType"] == "PENDING"
    assert guardrail["risk"] == seed["risk"]
    assert guardrail["atrade"]["executionReachability"] == "CONDITIONALLY_REACHABLE"

    guardrail["dvg"]["status"] = "MUTATED"
    assert seed["dvg"]["status"] == "WARN"
    assert paper["status"] == "PENDING"
    assert paper["observationPeriod"] == 14
    assert paper["entryAssumptions"] == []
    assert paper["invalidationConditions"] == []
    assert paper["simulationActions"] == []
    assert paper["simulatedProfit"] == 0.0
    assert paper["maxDrawdown"] == 0.0
    assert paper["triggeredInvalidation"] is False
    assert paper["writtenToLedger"] is False
    assert paper["triggeredErrorLedger"] is False
    assert paper["simulation_only"] is True
    assert paper["is_real_trade"] is False
    assert paper["simulationOnly"] is True
    assert paper["isRealTrade"] is False
    assert paper["allowed_order_namespace"] == "SIM_*"
    assert paper["latest_action"] == "SIM_HOLD"
    assert seed["portfolio"]["evidenceUsage"] == "supporting_only"
    assert seed["portfolio"]["evidenceStrength"] == "LOW"
    assert seed["portfolio"]["simulationOnly"] is True
    assert seed["portfolio"]["isRealTrade"] is False
    assert seed["portfolio"]["strongConclusionAllowed"] is False
    assert seed["portfolio"]["provenance"]["sourceId"] == "USER_INPUT_ONLY"


def test_mock_paper_trading_scenarios_preserve_simulation_boundary():
    for scenario in mock_scenarios.values():
        paper = scenario.get("paperTrading")
        if not paper:
            continue
        assert paper["simulation_only"] is True
        assert paper["is_real_trade"] is False
        assert paper["allowed_order_namespace"] == "SIM_*"
        assert str(paper["latest_action"]).startswith("SIM_")


def test_analysis_run_model_sanitizes_paper_trading_boundary():
    run = copy.deepcopy(mock_scenarios["qiam_discounted"])
    run["paperTrading"] = {
        **run["paperTrading"],
        "simulation_only": False,
        "simulationOnly": False,
        "is_real_trade": True,
        "isRealTrade": True,
        "allowed_order_namespace": "LIVE",
        "order_namespace": "LIVE",
        "orderNamespace": "LIVE",
        "latest_action": "BUY",
        "paper_action": "BUY",
        "action": "BUY",
        "simulationActions": [
            {
                "action": "BUY",
                "orderNamespace": "LIVE",
                "simulationOnly": False,
                "isRealTrade": True,
            },
            {
                "action": "SIM_SELL",
                "orderNamespace": "SIM_*",
            },
            "legacy-note",
        ],
    }

    response_payload = AnalysisRun(**run).model_dump()
    paper = response_payload["paperTrading"]

    assert paper["simulation_only"] is True
    assert paper["simulationOnly"] is True
    assert paper["is_real_trade"] is False
    assert paper["isRealTrade"] is False
    assert paper["allowed_order_namespace"] == "SIM_*"
    assert paper["order_namespace"] == "SIM_*"
    assert paper["orderNamespace"] == "SIM_*"
    assert paper["latest_action"] == "SIM_HOLD"
    assert paper["paper_action"] == "SIM_HOLD"
    assert paper["action"] == "SIM_HOLD"
    assert paper["simulationActions"][0]["action"] == "SIM_HOLD"
    assert paper["simulationActions"][0]["orderNamespace"] == "SIM_*"
    assert paper["simulationActions"][0]["simulationOnly"] is True
    assert paper["simulationActions"][0]["isRealTrade"] is False
    assert paper["simulationActions"][1]["action"] == "SIM_SELL"
    assert paper["simulationActions"][2] == "legacy-note"


def test_analysis_run_model_sanitizes_portfolio_boundary():
    run = copy.deepcopy(mock_scenarios["qiam_discounted"])
    run["portfolio"] = {
        **run["portfolio"],
        "portfolioCoverage": "HOLDINGS_CONNECTED",
        "snapshotId": "PF_LEGACY_POLLUTED",
        "evidenceUsage": "primary",
        "evidenceStrength": "HIGH",
        "simulationOnly": False,
        "isRealTrade": True,
        "strongConclusionAllowed": True,
        "provenance": {
            "sourceType": "LIVE_BROKER",
            "evidenceUsage": "primary",
            "evidenceStrength": "HIGH",
            "simulationOnly": False,
            "isRealTrade": True,
            "strongConclusionAllowed": True,
        },
    }

    response_payload = AnalysisRun(**run).model_dump()
    portfolio = response_payload["portfolio"]

    assert portfolio["evidenceUsage"] == "supporting_only"
    assert portfolio["evidenceStrength"] == "PENDING"
    assert portfolio["simulationOnly"] is True
    assert portfolio["isRealTrade"] is False
    assert portfolio["strongConclusionAllowed"] is False
    assert portfolio["provenance"]["snapshotId"] == "PF_LEGACY_POLLUTED"
    assert portfolio["provenance"]["evidenceUsage"] == "supporting_only"
    assert portfolio["provenance"]["evidenceStrength"] == "PENDING"
    assert portfolio["provenance"]["simulationOnly"] is True
    assert portfolio["provenance"]["isRealTrade"] is False
    assert portfolio["provenance"]["strongConclusionAllowed"] is False


def test_analysis_run_model_sanitizes_agent_node_boundary():
    run = copy.deepcopy(mock_scenarios["qiam_discounted"])
    run["nodes"] = [
        {
            "id": "guardrail_hub",
            "name": "Guardrail Hub",
            "status": "PASS",
            "isRunning": False,
            "isSkipped": False,
            "isBlocked": False,
            "duration": 120,
            "auditId": "AUD_NODE_POLLUTED",
            "missingData": [],
            "downgradeReasons": [],
            "blockedPaths": [],
            "allowedNextActions": ["quant_core"],
            "evidenceUsage": "primary",
            "evidenceStrength": "HIGH",
            "simulationOnly": False,
            "isRealTrade": True,
            "strongConclusionAllowed": True,
            "rawJson": {
                "nodeType": "agent",
                "allowTradeAction": True,
                "finalDecisionCap": "UPSTREAM_ONLY",
                "evidenceUsage": "primary",
                "evidenceStrength": "HIGH",
                "simulationOnly": False,
                "isRealTrade": True,
                "strongConclusionAllowed": True,
            },
        },
        {
            "id": "plugin:research:observer",
            "name": "Plugin Observer",
            "status": "REVIEW_ONLY",
            "isRunning": False,
            "isSkipped": False,
            "isBlocked": False,
            "duration": 0,
            "auditId": "AUD_PLUGIN_OBSERVER",
            "missingData": [],
            "downgradeReasons": [],
            "blockedPaths": [],
            "allowedNextActions": [],
            "evidenceUsage": "primary",
            "evidenceStrength": "HIGH",
            "simulationOnly": False,
            "isRealTrade": True,
            "strongConclusionAllowed": True,
            "rawJson": {
                "nodeType": "plugin_observation",
                "directExecution": False,
                "canExecuteCode": False,
                "allowTradeAction": True,
            },
        },
    ]

    response_payload = AnalysisRun(**run).model_dump()
    active_node = response_payload["nodes"][0]
    plugin_node = response_payload["nodes"][1]

    assert active_node["evidenceUsage"] == "simulation_only"
    assert active_node["evidenceStrength"] == "MEDIUM"
    assert active_node["simulationOnly"] is True
    assert active_node["isRealTrade"] is False
    assert active_node["strongConclusionAllowed"] is False
    assert active_node["rawJson"]["allowTradeAction"] is False
    assert active_node["rawJson"]["finalDecisionCap"] == "NO_DIRECT_TRADE_ACTION"
    assert active_node["rawJson"]["simulationOnly"] is True
    assert active_node["rawJson"]["isRealTrade"] is False
    assert active_node["rawJson"]["strongConclusionAllowed"] is False

    assert plugin_node["evidenceUsage"] == "simulation_only"
    assert plugin_node["evidenceStrength"] == "LOW"
    assert plugin_node["rawJson"]["evidenceStrength"] == "LOW"
    assert plugin_node["simulationOnly"] is True
    assert plugin_node["isRealTrade"] is False
    assert plugin_node["strongConclusionAllowed"] is False
    assert plugin_node["rawJson"]["allowTradeAction"] is False


@pytest.mark.parametrize("status", ["WARN", "REVIEW_ONLY"])
def test_analysis_run_model_weak_agent_node_status_keeps_low_evidence_strength(status):
    run = copy.deepcopy(mock_scenarios["qiam_discounted"])
    run["nodes"] = [
        {
            "id": "guardrail_hub",
            "name": "Guardrail Hub",
            "status": status,
            "isRunning": False,
            "isSkipped": False,
            "isBlocked": False,
            "duration": 120,
            "auditId": "AUD_NODE_WEAK_STATUS",
            "missingData": [],
            "downgradeReasons": [],
            "blockedPaths": [],
            "allowedNextActions": ["quant_core"],
            "evidenceUsage": "primary",
            "evidenceStrength": "HIGH",
            "simulationOnly": False,
            "isRealTrade": True,
            "strongConclusionAllowed": True,
            "rawJson": {
                "nodeType": "agent",
                "allowTradeAction": True,
                "finalDecisionCap": "UPSTREAM_ONLY",
                "evidenceUsage": "primary",
                "evidenceStrength": "HIGH",
                "simulationOnly": False,
                "isRealTrade": True,
                "strongConclusionAllowed": True,
            },
        }
    ]

    response_payload = AnalysisRun(**run).model_dump()
    node = response_payload["nodes"][0]

    assert node["evidenceUsage"] == "simulation_only"
    assert node["evidenceStrength"] == "LOW"
    assert node["rawJson"]["evidenceStrength"] == "LOW"
    assert node["simulationOnly"] is True
    assert node["isRealTrade"] is False
    assert node["strongConclusionAllowed"] is False


def test_analysis_run_model_sanitizes_quant_core_boundary():
    run = copy.deepcopy(mock_scenarios["qiam_discounted"])
    run["quantCore"] = {
        "agent": "quant_core",
        "status": "PASS",
        "actionBoundary": "LIVE_PERMISSION_CHANGE",
        "evidenceUsage": "primary",
        "evidenceStrength": "HIGH",
        "simulation_only": False,
        "is_real_trade": True,
        "strongConclusionAllowed": True,
        "warnings": [],
        "missingData": [],
        "coreInterpretation": {
            "version": "quant_core_interpretation_v1",
            "status": "PASS",
            "actionBoundary": "LIVE_PERMISSION_CHANGE",
            "simulation_only": False,
            "is_real_trade": True,
            "strongConclusionAllowed": True,
        },
        "provenance": {
            "sourceNode": "quant_core",
            "actionBoundary": "LIVE_PERMISSION_CHANGE",
            "evidenceUsage": "primary",
            "evidenceStrength": "HIGH",
            "simulation_only": False,
            "is_real_trade": True,
            "strongConclusionAllowed": True,
        },
    }

    response_payload = AnalysisRun(**run).model_dump()
    quant_core = response_payload["quantCore"]

    assert quant_core["actionBoundary"] == "READ_ONLY_NO_PERMISSION_CHANGE"
    assert quant_core["evidenceUsage"] == "simulation_only"
    assert quant_core["evidenceStrength"] == "MEDIUM"
    assert quant_core["simulation_only"] is True
    assert quant_core["is_real_trade"] is False
    assert quant_core["strongConclusionAllowed"] is False
    assert quant_core["coreInterpretation"]["actionBoundary"] == "READ_ONLY_NO_PERMISSION_CHANGE"
    assert quant_core["coreInterpretation"]["simulation_only"] is True
    assert quant_core["coreInterpretation"]["is_real_trade"] is False
    assert quant_core["coreInterpretation"]["strongConclusionAllowed"] is False
    assert quant_core["provenance"]["actionBoundary"] == "READ_ONLY_NO_PERMISSION_CHANGE"
    assert quant_core["provenance"]["evidenceUsage"] == "simulation_only"
    assert quant_core["provenance"]["simulation_only"] is True
    assert quant_core["provenance"]["is_real_trade"] is False
    assert quant_core["provenance"]["strongConclusionAllowed"] is False


def test_analysis_run_model_quant_core_without_interpretation_keeps_low_evidence_strength():
    run = copy.deepcopy(mock_scenarios["qiam_discounted"])
    run["quantCore"] = {
        "agent": "quant_core",
        "status": "PASS",
        "actionBoundary": "LIVE_PERMISSION_CHANGE",
        "evidenceUsage": "primary",
        "evidenceStrength": "HIGH",
        "simulation_only": False,
        "is_real_trade": True,
        "strongConclusionAllowed": True,
        "warnings": [],
        "missingData": [],
        "provenance": {
            "sourceNode": "legacy_quant_core",
            "evidenceStrength": "HIGH",
        },
    }

    response_payload = AnalysisRun(**run).model_dump()
    quant_core = response_payload["quantCore"]

    assert quant_core["evidenceUsage"] == "simulation_only"
    assert quant_core["evidenceStrength"] == "LOW"
    assert quant_core["provenance"]["evidenceStrength"] == "LOW"
    assert quant_core["simulation_only"] is True
    assert quant_core["is_real_trade"] is False
    assert quant_core["strongConclusionAllowed"] is False


def test_analysis_run_model_review_gates_research_grade_evidence_aliases():
    assert {"RESEARCH_GRADE", "PRIMARY_EVIDENCE_READY"}.issubset(
        analysis_models.REVIEW_GATE_EVIDENCE_STRENGTH_ALIASES
    )

    for evidence_strength in ("RESEARCH_GRADE", "PRIMARY_EVIDENCE_READY"):
        run = copy.deepcopy(mock_scenarios["qiam_discounted"])
        run["nodes"] = [
            {
                "id": "guardrail_hub",
                "name": "Guardrail Hub",
                "status": "PASS",
                "isRunning": False,
                "isSkipped": False,
                "isBlocked": False,
                "auditId": "AUD_NODE_REVIEW_GATE",
                "missingData": [],
                "downgradeReasons": [],
                "blockedPaths": [],
                "allowedNextActions": ["quant_core"],
                "evidenceStrength": evidence_strength,
                "rawJson": {"nodeType": "agent", "evidenceStrength": evidence_strength},
            }
        ]
        run["quantCore"] = {
            "agent": "quant_core",
            "status": "PASS",
            "warnings": [],
            "missingData": [],
            "evidenceStrength": evidence_strength,
            "coreInterpretation": {
                "version": "quant_core_interpretation_v1",
                "status": "PASS",
            },
        }

        response_payload = AnalysisRun(**run).model_dump()

        assert response_payload["nodes"][0]["evidenceStrength"] == "MEDIUM"
        assert response_payload["nodes"][0]["rawJson"]["evidenceStrength"] == "MEDIUM"
        assert response_payload["quantCore"]["evidenceStrength"] == "MEDIUM"
        assert response_payload["quantCore"]["provenance"]["evidenceStrength"] == "MEDIUM"


def test_apply_quant_core_data_writes_readonly_simulation_boundary():
    run: dict = {}

    changed = apply_quant_core_data(
        run,
        {
            "agent": "quant_core",
            "status": "PASS",
            "actionBoundary": "LIVE_PERMISSION_CHANGE",
            "evidenceUsage": "primary",
            "evidenceStrength": "HIGH",
            "simulation_only": False,
            "is_real_trade": True,
            "strongConclusionAllowed": True,
            "warnings": [],
            "missingData": [],
            "coreInterpretation": {
                "version": "quant_core_interpretation_v1",
                "status": "PASS",
            },
            "legacyOutputs": {"qiam": {"finalBuySuitability": "FAVORABLE"}},
            "legacyAgentOutputs": {"qiam": {"finalBuySuitability": "FAVORABLE"}},
        },
    )

    assert changed is True
    quant_core = run["quantCore"]
    assert quant_core["actionBoundary"] == "READ_ONLY_NO_PERMISSION_CHANGE"
    assert quant_core["evidenceUsage"] == "simulation_only"
    assert quant_core["evidenceStrength"] == "MEDIUM"
    assert quant_core["simulation_only"] is True
    assert quant_core["is_real_trade"] is False
    assert quant_core["strongConclusionAllowed"] is False
    assert quant_core["provenance"]["actionBoundary"] == "READ_ONLY_NO_PERMISSION_CHANGE"
    assert quant_core["provenance"]["simulation_only"] is True
    assert run["agentModuleResults"]["qiam"]["legacyCompatibilityOnly"] is True
    assert run["agentOutputs"]["qiam"]["activeNode"] is False


def test_apply_quant_core_data_without_interpretation_keeps_low_evidence_strength():
    run: dict = {}

    changed = apply_quant_core_data(
        run,
        {
            "agent": "quant_core",
            "status": "PASS",
            "actionBoundary": "LIVE_PERMISSION_CHANGE",
            "evidenceUsage": "primary",
            "evidenceStrength": "HIGH",
            "simulation_only": False,
            "is_real_trade": True,
            "strongConclusionAllowed": True,
            "warnings": [],
            "missingData": [],
        },
    )

    assert changed is True
    quant_core = run["quantCore"]
    assert quant_core["evidenceUsage"] == "simulation_only"
    assert quant_core["evidenceStrength"] == "LOW"
    assert quant_core["provenance"]["evidenceStrength"] == "LOW"
    assert quant_core["simulation_only"] is True
    assert quant_core["is_real_trade"] is False
    assert quant_core["strongConclusionAllowed"] is False


def test_agent_framework_builds_agent_nodes_with_simulation_boundary():
    seed = analysis_run_create.real_run_seed(mock_scenarios["qiam_discounted"])
    seed["marketData"] = {"status": "PENDING", "provider": "test"}

    run = apply_agent_framework_to_run(
        seed,
        {
            "run_mode": "STANDARD_MODE",
            "symbol": "603663.SZ",
            "task_type": "持仓复核",
        },
        {"agents": []},
    )

    assert run["nodes"]
    for node in run["nodes"]:
        assert node["evidenceUsage"] == "simulation_only"
        assert node["evidenceStrength"] in {"LOW", "MEDIUM"}
        assert node["simulationOnly"] is True
        assert node["isRealTrade"] is False
        assert node["strongConclusionAllowed"] is False
        assert node["rawJson"]["evidenceUsage"] == "simulation_only"
        assert node["rawJson"]["evidenceStrength"] == node["evidenceStrength"]
        assert node["rawJson"]["simulationOnly"] is True
        assert node["rawJson"]["isRealTrade"] is False
        assert node["rawJson"]["strongConclusionAllowed"] is False
        assert node["rawJson"]["allowTradeAction"] is False
        assert node["rawJson"]["finalDecisionCap"] == "NO_DIRECT_TRADE_ACTION"


def test_agent_framework_plugin_runtime_nodes_keep_low_evidence_strength():
    seed = analysis_run_create.real_run_seed(mock_scenarios["qiam_discounted"])
    seed["marketData"] = {"status": "PENDING", "provider": "test"}
    runtime_summary = {
        "agents": [],
        "pluginRuntimePlan": {
            "agents": [
                {
                    "eligible": True,
                    "plugin_id": "readonly_research_plugin",
                    "agent_id": "observer",
                    "agent_name": "Read-only Observer",
                    "dag_node_id": "plugin:readonly_research_plugin:observer",
                    "dag_registration": {
                        "node_type": "plugin_observation",
                        "insertion_after": "quant_core",
                    },
                    "risk_gate": {"trade_actions_allowed": False},
                }
            ]
        },
    }

    run = apply_agent_framework_to_run(
        seed,
        {
            "run_mode": "STANDARD_MODE",
            "symbol": "603663.SZ",
            "task_type": "持仓复核",
        },
        runtime_summary,
    )

    plugin_node = next(node for node in run["nodes"] if node["id"] == "plugin:readonly_research_plugin:observer")

    assert plugin_node["evidenceUsage"] == "simulation_only"
    assert plugin_node["evidenceStrength"] == "LOW"
    assert plugin_node["rawJson"]["evidenceStrength"] == "LOW"
    assert plugin_node["rawJson"]["canExecuteCode"] is False
    assert plugin_node["rawJson"]["directExecution"] is False
    assert plugin_node["simulationOnly"] is True
    assert plugin_node["isRealTrade"] is False
    assert plugin_node["strongConclusionAllowed"] is False


@pytest.mark.parametrize("status", ["WARN", "REVIEW_ONLY"])
def test_agent_framework_weak_agent_node_status_keeps_low_evidence_strength(status):
    strength = agent_framework._agent_node_evidence_strength(
        status=status,
        is_skipped=False,
        is_blocked=False,
        missing_data=[],
        downgrade_reasons=[],
    )

    assert strength == "LOW"


def test_qiam_discounted_mock_uses_guardrail_hub_as_active_guardrail_trigger():
    scenario = mock_scenarios["qiam_discounted"]
    guardrail = scenario["guardrailHub"]

    assert scenario["killSwitch"]["triggerNode"] == "guardrail_hub"
    assert guardrail["killSwitch"]["triggerNode"] == "guardrail_hub"
    assert guardrail["dvg"]["allowedOutputLevel"] == "REVIEW_ONLY"
    assert "dvg_evidence_gate" not in {
        scenario["killSwitch"]["triggerNode"],
        guardrail["killSwitch"]["triggerNode"],
    }


@pytest.mark.asyncio
async def test_core_build_created_run_rejects_missing_portfolio_snapshot():
    async def missing_snapshot(_snapshot_id: str):
        return None

    async def fake_hydrate(run_data: dict, _symbol: str):
        return run_data

    request = CreateAnalysisRequest(
        symbol="603663.SZ",
        task_type="持仓复核",
        run_mode="STANDARD_MODE",
        scenario_id="qiam_discounted",
        user_constraints={},
        config_profile_id="default",
        portfolio_snapshot_id="PF_MISSING",
    )

    with pytest.raises(analysis_run_create.AnalysisRunCreateNotFound) as exc_info:
        await analysis_run_create.build_created_run(
            request=request,
            run_id="RUN_CREATE_CORE_MISSING_PF",
            research_loop_id=None,
            scenario_template=mock_scenarios["qiam_discounted"],
            runtime_summary={"agents": []},
            knowledge_context=[],
            get_snapshot=missing_snapshot,
            normalize_symbol=lambda value: value.split(".")[0],
            hydrate_run_with_market_data=fake_hydrate,
            apply_agent_framework_to_run=lambda run_data, _request_data, _runtime: run_data,
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Portfolio snapshot not found"


@pytest.mark.asyncio
async def test_core_build_created_run_preserves_created_simulation_boundary():
    async def unused_snapshot(_snapshot_id: str):
        raise AssertionError("snapshot lookup should not run without portfolio_snapshot_id")

    async def fake_hydrate(run_data: dict, _symbol: str):
        return run_data

    request = CreateAnalysisRequest(
        symbol="603663.SZ",
        task_type="持仓复核",
        run_mode="STANDARD_MODE",
        scenario_id="qiam_discounted",
        user_constraints={},
        config_profile_id="default",
    )

    run = await analysis_run_create.build_created_run(
        request=request,
        run_id="RUN_CREATE_CORE_BOUNDARY",
        research_loop_id=None,
        scenario_template=mock_scenarios["qiam_discounted"],
        runtime_summary={"agents": []},
        knowledge_context=[],
        get_snapshot=unused_snapshot,
        normalize_symbol=lambda value: value.split(".")[0],
        hydrate_run_with_market_data=fake_hydrate,
        apply_agent_framework_to_run=lambda run_data, _request_data, _runtime: run_data,
    )

    assert run["status"] == "CREATED"
    assert run["streamEvents"][-1]["event_type"] == "RUN_CREATED"
    assert run["streamEvents"][-1]["payload"]["simulation_only"] is True
    assert run["streamEvents"][-1]["payload"]["is_real_trade"] is False
    assert run["streamEvents"][-1]["payload"]["allowed_order_namespace"] == "SIM_*"
    assert run["paperTrading"]["status"] == "PENDING"
    assert run["paperTrading"]["simulatedProfit"] == 0.0
    assert run["paperTrading"]["simulation_only"] is True
    assert run["paperTrading"]["is_real_trade"] is False
    assert run["paperTrading"]["allowed_order_namespace"] == "SIM_*"
    assert run["paperTrading"]["latest_action"] == "SIM_HOLD"

    response_payload = AnalysisRun(**run).model_dump()
    assert response_payload["streamEvents"][-1]["event_type"] == "RUN_CREATED"
    assert response_payload["paperTrading"]["status"] == "PENDING"
    assert response_payload["paperTrading"]["simulation_only"] is True


@pytest.mark.asyncio
async def test_core_build_created_run_sanitizes_knowledge_context_boundary():
    async def unused_snapshot(_snapshot_id: str):
        raise AssertionError("snapshot lookup should not run without portfolio_snapshot_id")

    async def fake_hydrate(run_data: dict, _symbol: str):
        return run_data

    request = CreateAnalysisRequest(
        symbol="603663.SZ",
        task_type="持仓复核",
        run_mode="STANDARD_MODE",
        scenario_id="qiam_discounted",
        user_constraints={},
        config_profile_id="default",
    )

    run = await analysis_run_create.build_created_run(
        request=request,
        run_id="RUN_CREATE_CORE_KNOWLEDGE_CONTEXT",
        research_loop_id=None,
        scenario_template=mock_scenarios["qiam_discounted"],
        runtime_summary={"agents": []},
        knowledge_context=[
            {
                "itemId": "KB_LEGACY_CONTEXT_HIGH",
                "version": 3,
                "category": "RUN_REVIEW",
                "title": "Legacy context",
                "thesis": "Legacy state must not pollute a new analysis run.",
                "decisionImpact": "Review only.",
                "tags": ["legacy"],
                "confidence": "HIGH",
                "evidenceUsage": "primary",
                "evidenceStrength": "HIGH",
                "simulationOnly": False,
                "isRealTrade": True,
                "strongConclusionAllowed": True,
            },
            {"not": "a valid context"},
        ],
        get_snapshot=unused_snapshot,
        normalize_symbol=lambda value: value.split(".")[0],
        hydrate_run_with_market_data=fake_hydrate,
        apply_agent_framework_to_run=lambda run_data, _request_data, _runtime: run_data,
    )

    assert run["knowledgeContext"] == [
        {
            "itemId": "KB_LEGACY_CONTEXT_HIGH",
            "version": 3,
            "category": "RUN_REVIEW",
            "title": "Legacy context",
            "thesis": "Legacy state must not pollute a new analysis run.",
            "decisionImpact": "Review only.",
            "tags": ["legacy"],
            "confidence": "MEDIUM",
            "evidenceUsage": "supporting_only",
            "evidenceStrength": "MEDIUM",
            "simulationOnly": True,
            "isRealTrade": False,
            "strongConclusionAllowed": False,
        }
    ]

    response_payload = AnalysisRun(**run).model_dump()
    assert response_payload["knowledgeContext"][0]["evidenceUsage"] == "supporting_only"
    assert response_payload["knowledgeContext"][0]["simulationOnly"] is True
    assert response_payload["knowledgeContext"][0]["isRealTrade"] is False
    assert response_payload["knowledgeContext"][0]["strongConclusionAllowed"] is False


def test_core_prepare_start_worker_queue_preserves_simulation_boundary():
    jobs: list[dict] = []
    run = {"status": "CREATED", "auditLog": [{"eventType": "CREATED"}]}

    def fake_start_job(run_id: str, *, retry_from_node_id: str, operator: str) -> dict:
        job = {
            "run_id": run_id,
            "status": "QUEUED",
            "retry_from_node_id": retry_from_node_id,
            "operator": operator,
        }
        jobs.append(job)
        return job

    result = analysis_run_start.prepare_start(
        run,
        "RUN_START_CORE",
        execution_mode="worker",
        payload={"operator": "tester"},
        start_job=fake_start_job,
    )

    assert result.status == "QUEUED"
    assert result.should_schedule_background_task is False
    assert run["status"] == "QUEUED"
    assert jobs == [
        {
            "run_id": "RUN_START_CORE",
            "status": "QUEUED",
            "retry_from_node_id": "",
            "operator": "tester",
        }
    ]
    assert run["job"] == jobs[0]
    assert run["auditLog"][-1]["eventType"] == "RUN_QUEUED"
    assert run["streamEvents"][-1]["event_type"] == "RUN_QUEUED"
    assert run["streamEvents"][-1]["payload"]["simulation_only"] is True
    assert run["streamEvents"][-1]["payload"]["is_real_trade"] is False


def test_core_prepare_retry_resets_downstream_nodes_and_artifacts():
    run = {
        "status": "FAILED",
        "nodes": [
            {"id": "dvg_gate", "status": "FAILED", "isRunning": True, "duration": 10, "outputSummary": "failed"},
            {"id": "quant_core", "status": "PASS", "duration": 3, "outputSummary": "old"},
            {"id": "final_writer", "status": "FAILED", "duration": 5, "outputSummary": "old"},
        ],
        "agentOutputs": {"dvg_gate": {}, "quant_core": {}, "final_writer": {}},
        "agentModuleResults": {"quant_core": {}, "final_writer": {}},
        "llmTrace": [{"nodeId": "dvg_gate"}, {"nodeId": "final_writer"}, {"nodeId": "portfolio"}],
        "agentResults": [{"node": "dvg_gate"}, {"node": "final_writer"}, {"node": "portfolio"}],
    }

    retry_from = analysis_run_retry.prepare_retry(run, {"reason": "rerun failed branch"})

    assert retry_from == "dvg_gate"
    assert run["status"] == "CREATED"
    assert run["failReason"] == ""
    assert run["failureCategory"] == ""
    assert run["cancelRequested"] is False
    assert run["retry"]["from_node_id"] == "dvg_gate"
    assert run["retry"]["previous_status"] == "FAILED"
    assert run["retry"]["reason"] == "rerun failed branch"
    assert run["nodes"][0]["status"] == "WAIT"
    assert run["nodes"][1]["status"] == "WAIT"
    assert run["nodes"][2]["status"] == "WAIT"
    assert run["agentOutputs"] == {}
    assert run["agentModuleResults"] == {}
    assert run["llmTrace"] == [{"nodeId": "portfolio"}]
    assert run["agentResults"] == [{"node": "portfolio"}]


@pytest.mark.asyncio
async def test_route_persist_run_delegates_to_core_persistence(monkeypatch):
    run_data = {"runId": "RUN_PERSIST_DELEGATE"}
    calls: dict[str, object] = {}

    def fake_save_run(next_run_data: dict) -> None:
        calls["save_run_called_with"] = next_run_data

    async def fake_persist_run(next_run_data: dict, run_id: str, symbol: str, *, save_run, logger) -> None:
        calls["run_data"] = next_run_data
        calls["run_id"] = run_id
        calls["symbol"] = symbol
        calls["save_run"] = save_run
        calls["logger"] = logger

    monkeypatch.setattr(routes_analysis, "save_run", fake_save_run)
    monkeypatch.setattr(routes_analysis.analysis_run_persistence, "persist_run", fake_persist_run)

    await routes_analysis._persist_run(run_data, "RUN_PERSIST_DELEGATE", "603663")

    assert calls == {
        "run_data": run_data,
        "run_id": "RUN_PERSIST_DELEGATE",
        "symbol": "603663",
        "save_run": fake_save_run,
        "logger": routes_analysis.logger,
    }


@pytest.mark.asyncio
async def test_core_persist_run_saves_local_run_before_repo_failure(monkeypatch):
    saved: list[dict] = []
    logged: list[str] = []
    run_data = {"runId": "RUN_PERSIST_CORE", "auditId": "AUD_PERSIST_CORE"}

    class FailingRunRepository:
        async def save(self, next_run_data: dict) -> None:
            raise RuntimeError("db unavailable")

    class FakeLogger:
        def exception(self, message: str, run_id: str) -> None:
            logged.append(f"{message}:{run_id}")

    monkeypatch.setattr(analysis_run_persistence, "RunRepository", FailingRunRepository)

    await analysis_run_persistence.persist_run(
        run_data,
        "RUN_PERSIST_CORE",
        "603663",
        save_run=lambda next_run_data: saved.append(next_run_data.copy()),
        logger=FakeLogger(),
    )

    assert saved == [run_data]
    assert logged == ["Failed to persist run %s:RUN_PERSIST_CORE"]
