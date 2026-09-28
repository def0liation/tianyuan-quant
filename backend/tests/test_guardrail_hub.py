from app.core import agent_executor
from app.core.agent_executor import (
    _apply_agent_module_output_to_run,
    _canonical_retry_node_id,
)
from app.core.agent_framework import normalize_run_artifacts


def _assert_guardrail_legacy_marker(payload: dict, node: str) -> None:
    assert payload["node"] == node
    assert payload["legacyCompatibilityOnly"] is True
    assert payload["canonicalNode"] == "guardrail_hub"
    assert payload["activeNode"] is False


def _base_run(mode: str = "LOW_FREQ_MID_LONG", task_type: str = "持仓复核") -> dict:
    return {
        "runId": "RUN_GUARDRAIL_HUB",
        "stockCode": "000001.SZ",
        "stockName": "Ping An",
        "taskType": task_type,
        "runMode": "STANDARD_MODE",
        "quantEngine": {"mode": mode},
        "dataSources": {
            "sources": {
                "quote": {
                    "name": "实时行情",
                    "status": "READY",
                    "dataMode": "LIVE",
                    "available": True,
                    "provider": "tushare",
                }
            }
        },
        "marketData": {"freshness": "REALTIME", "quote": {"changePercent": 0}},
        "technicalKline": {
            "agent": "technical_kline_analyst",
            "status": "PASS",
            "technicalBias": "NEUTRAL",
            "confidence": 0.82,
            "dataQuality": {"provider": "tushare", "dataMode": "LIVE", "dailyCount": 80},
        },
        "dvg": {},
        "risk": {
            "complianceRedLines": [],
            "f0IndividualHardRisks": [],
            "f1ExtremeChipCollapse": [],
            "f4ThreePartyFundResonanceOutflow": [],
            "l0AbsoluteLiquidityRedLine": [],
            "m0SystemicRisk": [],
            "portfolioRiskOverLimit": [],
            "executionUnreachable": [],
        },
        "atrade": {
            "level2Available": False,
            "depthAvailable": False,
            "executionReachability": "REACHABLE",
            "liquidityRisk": "MEDIUM",
        },
        "userPosition": {"sellableBottomWarehouse": True, "plannedPeriod": 20, "maxAcceptableDrawdown": 0.08},
    }


def test_guardrail_hub_low_frequency_keeps_dvg_qiam_allowed_when_micro_data_missing():
    run = _base_run()

    result = agent_executor.run_agent_module("guardrail_hub", run, {})
    data = result.data

    assert data["dvg"]["quantEngineMode"] == "LOW_FREQ_MID_LONG"
    assert data["dvg"]["qiamPermission"] == "ALLOW"
    assert data["dvg"]["criticalMissingData"] == []
    assert data["dvg"]["ignoredMissingData"] == ["Level-2 逐笔成交", "盘口深度"]
    assert data["atrade"]["executionReachability"] == "CONDITIONALLY_REACHABLE"
    assert data["killSwitch"]["active"] is False
    for legacy_id in ("dvg_gate", "dvg_evidence_gate", "risk_firewall", "trade_micro", "atrade"):
        _assert_guardrail_legacy_marker(data["legacyModuleResults"][legacy_id], legacy_id)
        _assert_guardrail_legacy_marker(data["legacyAgentOutputs"][legacy_id], legacy_id)
    assert result.status in {"WARN", "PASS"}


def test_guardrail_hub_compliance_redline_uses_guardrail_hub_kill_switch():
    run = _base_run()
    run["risk"]["complianceRedLines"] = ["restricted_security"]

    result = agent_executor.run_agent_module("guardrail_hub", run, {})
    data = result.data

    assert result.status == "BLOCK"
    assert result.hard_stop is True
    assert data["killSwitch"]["active"] is True
    assert data["killSwitch"]["level"] == "COMPLIANCE"
    assert data["killSwitch"]["triggerNode"] == "guardrail_hub"
    assert data["finalDecisionCap"] == "REJECT"


def test_guardrail_hub_execution_unreachable_blocks_buy_without_dvg_penalty():
    run = _base_run()
    run["atrade"]["executionReachability"] = "NOT_REACHABLE"

    result = agent_executor.run_agent_module("guardrail_hub", run, {})
    data = result.data

    assert result.status == "BLOCK_BUY"
    assert data["dvg"]["qiamPermission"] == "ALLOW"
    assert data["killSwitch"]["triggerRule"] == "atrade_not_reachable"
    assert "EXECUTION_BUY" in data["killSwitch"]["blockedPaths"]


def test_guardrail_hub_apply_output_mirrors_legacy_public_fields_and_module_results():
    run = _base_run()
    result = agent_executor.run_agent_module("guardrail_hub", run, {})

    _apply_agent_module_output_to_run(run, "guardrail_hub", result)

    assert run["guardrailHub"]["dvg"]["qiamPermission"] == run["dvg"]["qiamPermission"]
    assert run["guardrailHub"]["risk"]["status"] == run["risk"]["status"]
    assert run["guardrailHub"]["atrade"]["executionReachability"] == run["atrade"]["executionReachability"]
    assert run["killSwitch"] == run["guardrailHub"]["killSwitch"]
    assert "dvg_gate" in run["agentModuleResults"]
    assert "risk_firewall" in run["agentModuleResults"]
    assert "trade_micro" in run["agentModuleResults"]
    for legacy_id in ("dvg_gate", "risk_firewall", "trade_micro"):
        legacy_result = run["agentModuleResults"][legacy_id]
        _assert_guardrail_legacy_marker(legacy_result, legacy_id)


def test_guardrail_hub_normalize_marks_legacy_module_results_as_compatibility_only():
    result = agent_executor.run_agent_module("guardrail_hub", _base_run(), {})
    run = {
        **_base_run(),
        "agentModuleResults": {
            "guardrail_hub": result.to_dict(),
        },
    }

    normalize_run_artifacts(run)

    for legacy_id in ("dvg_gate", "dvg_evidence_gate", "risk_firewall", "trade_micro", "atrade"):
        legacy_result = run["agentModuleResults"][legacy_id]
        _assert_guardrail_legacy_marker(legacy_result, legacy_id)


def test_guardrail_hub_agent_results_expose_legacy_compatibility_marker():
    result = agent_executor.run_agent_module("guardrail_hub", _base_run(), {})
    run = {
        **_base_run(),
        "nodes": [
            {
                "id": "dvg_gate",
                "name": "DVG Gate",
                "status": "PASS",
                "isSkipped": False,
                "isBlocked": False,
                "duration": 12,
                "auditId": "AUD_DVG_LEGACY",
                "outputSummary": "legacy DVG alias",
            }
        ],
        "agentModuleResults": {
            "guardrail_hub": result.to_dict(),
        },
    }

    normalize_run_artifacts(run)

    agent_result = next(item for item in run["agentResults"] if item["node"] == "dvg_gate")
    _assert_guardrail_legacy_marker(agent_result, "dvg_gate")


def test_guardrail_hub_runtime_hard_stop_marks_forward_nodes_skipped():
    run = {
        **_base_run(),
        "nodes": [
            {"id": "guardrail_hub", "name": "Guardrail Hub", "status": "PASS", "isSkipped": False, "allowedNextActions": ["quant_core"], "rawJson": {}},
            {"id": "quant_core", "name": "量化核心", "status": "PASS", "isSkipped": False, "allowedNextActions": ["execution"], "rawJson": {}},
            {"id": "execution", "name": "Execution", "status": "PASS", "isSkipped": False, "allowedNextActions": ["final_writer"], "rawJson": {}},
            {"id": "final_writer", "name": "Final Writer", "status": "PASS", "isSkipped": False, "allowedNextActions": [], "rawJson": {}},
        ],
        "agentModuleResults": {
            "guardrail_hub": {
                "data": {
                    "status": "BLOCK_BUY",
                    "finalDecisionCap": "BLOCK_BUY",
                    "killSwitch": {
                        "active": True,
                        "level": "HARD",
                        "triggerNode": "guardrail_hub",
                        "triggerRule": "risk_hard_reject",
                        "blockedPaths": ["BUY_CANDIDATE", "ADD_CANDIDATE", "EXECUTION_BUY"],
                        "allowedPaths": ["WAIT", "REVIEW_ONLY", "HOLD"],
                        "finalWriterMode": "HARD_RISK_FINAL_ONLY",
                        "auditId": "AUD_KS_RISK",
                    },
                    "dvg": {},
                    "risk": {"hardStop": True},
                    "atrade": {},
                }
            }
        },
    }

    normalize_run_artifacts(run)

    by_id = {node["id"]: node for node in run["nodes"]}
    assert by_id["guardrail_hub"]["allowedNextActions"] == ["final_writer"]
    assert by_id["quant_core"]["isSkipped"] is True
    assert by_id["execution"]["isSkipped"] is True
    assert by_id["final_writer"]["isSkipped"] is False
    assert run["orchestratorPlan"]["trigger_node"] == "guardrail_hub"


def test_guardrail_hub_retry_aliases_legacy_nodes():
    assert _canonical_retry_node_id("dvg_gate") == "guardrail_hub"
    assert _canonical_retry_node_id("risk_firewall") == "guardrail_hub"
    assert _canonical_retry_node_id("trade_micro") == "guardrail_hub"
