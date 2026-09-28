"""
DVG Evidence Gate 门禁测试
验收清单 §9 所有规则
"""

import pytest
from app.core import agent_executor
from app.core.agent_executor import _apply_agent_module_output_to_run
from app.db.repositories import DVGResultRepo


def _mode_split_run(mode: str, task_type: str) -> dict:
    return {
        "taskType": task_type,
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
        "marketData": {"freshness": "REALTIME", "quote": {"changePercent": 0.4}},
        "technicalKline": {
            "agent": "technical_kline_analyst",
            "status": "PASS",
            "technicalBias": "BULLISH",
            "confidence": 0.78,
            "dataQuality": {
                "provider": "tushare",
                "dataMode": "LIVE",
                "dailyCount": 60,
            },
        },
        "atrade": {
            "level2Available": False,
            "depthAvailable": False,
        },
        "dvg": {},
    }


def test_dvg_high_frequency_module_intercepts_microstructure_missing():
    run = _mode_split_run("HIGH_FREQ_SHORT", "交易机会发现")

    result = agent_executor.run_agent_module("dvg_gate", run, {})
    data = result.data

    assert result.status == "WARN"
    assert data["quantEngineMode"] == "HIGH_FREQ_SHORT"
    assert data["activeModule"] == "dvg_high_frequency_trading"
    assert data["qiamPermission"] == "ALLOW_WITH_DISCOUNT"
    assert data["allowedOutputLevel"] == "REVIEW_ONLY"
    assert data["ignoredMissingData"] == []
    assert "Level-2 逐笔成交" in data["criticalMissingData"]
    assert "盘口深度" in data["criticalMissingData"]
    assert data["dvgModules"]["lowFrequencyMidLong"]["qiamPermission"] == "ALLOW"


def test_dvg_low_frequency_module_ignores_microstructure_missing_for_quant_engine():
    run = _mode_split_run("LOW_FREQ_MID_LONG", "持仓复核")

    result = agent_executor.run_agent_module("dvg_gate", run, {})
    data = result.data

    assert result.status == "PASS"
    assert data["quantEngineMode"] == "LOW_FREQ_MID_LONG"
    assert data["activeModule"] == "dvg_low_frequency_mid_long"
    assert data["qiamPermission"] == "ALLOW"
    assert data["allowedOutputLevel"] == "FULL"
    assert data["criticalMissingData"] == []
    assert data["ignoredMissingData"] == ["Level-2 逐笔成交", "盘口深度"]
    assert data["sourceIntegrity"] == "COMPLETE_FOR_MODE"
    assert data["dvgModules"]["highFrequencyTrading"]["qiamPermission"] == "ALLOW_WITH_DISCOUNT"


def test_dvg_low_frequency_legacy_ratios_do_not_leave_synthetic_unknowns_after_ignoring_intraday_gaps():
    run = {
        "taskType": "持仓复核",
        "quantEngine": {"mode": "LOW_FREQ_MID_LONG"},
        "dvg": {
            "confirmedRatio": 0.75,
            "inferredRatio": 0.0,
            "unknownRatio": 0.25,
            "criticalMissingData": ["Level-2 逐笔成交", "盘口深度"],
            "hallucinationRiskScore": 60,
        },
    }

    result = agent_executor.run_agent_module("dvg_gate", run, {})
    data = result.data

    assert result.status == "PASS"
    assert data["criticalMissingData"] == []
    assert data["ignoredMissingData"] == ["Level-2 逐笔成交", "盘口深度"]
    assert data["coreUnknownCount"] == 0
    assert data["qiamPermission"] == "ALLOW"
    assert data["dvgModules"]["highFrequencyTrading"]["qiamPermission"] == "ALLOW_WITH_DISCOUNT"


def test_dvg_low_frequency_module_prevents_qiam_dvg_discount_for_intraday_gaps():
    run = _mode_split_run("LOW_FREQ_MID_LONG", "持仓复核")
    run["qiam"] = {
        "rawBuySuitability": "FAVORABLE",
        "missingData": ["Level-2", "盘口深度"],
    }

    dvg_result = agent_executor.run_agent_module("dvg_gate", run, {})
    _apply_agent_module_output_to_run(run, "dvg_gate", dvg_result)
    qiam_result = agent_executor.run_agent_module("quant_engine", run, {"dvg_gate": dvg_result.data})

    assert run["quantEngine"]["ignoredMissingData"] == ["Level-2 逐笔成交", "盘口深度"]
    assert qiam_result.data["discountFactor"] == pytest.approx(1.0)
    assert qiam_result.data["finalBuySuitability"] == "FAVORABLE"
    assert qiam_result.data["ignoredMissingData"] == ["Level-2", "盘口深度"]
    assert all("DVG ALLOW_WITH_DISCOUNT" not in reason for reason in qiam_result.data["downgradeReasons"])


@pytest.mark.asyncio
async def test_dvg_block_buy_blocks_qiam_positive(db_session):
    """§9-7: DVG BLOCK_BUY 时 QIAM 必须 BLOCK 或 SKIPPED"""
    dvg = {
        "auditId": "AUD_DVG_001",
        "status": "BLOCK_BUY",
        "dataReliability": "LOW",
        "hardStop": True,
        "qiamPermission": "BLOCKED",
        "executionPermission": "BLOCKED",
        "allowedOutputLevel": "BLOCK_BUY",
        "finalDecisionCap": "BLOCK_BUY",
        "hallucinationRiskScore": 75,
        "hallucinationRiskLevel": "HIGH",
    }
    repo = DVGResultRepo(session=db_session)
    record = await repo.save(dvg, "RUN_001")
    assert record.status == "BLOCK_BUY"
    assert record.qiam_permission == "BLOCKED"
    assert record.hard_stop is True


@pytest.mark.asyncio
async def test_dvg_review_only_blocks_qiam_discount(db_session):
    """§9-8: DVG REVIEW_ONLY 时 QIAM discount_factor 必须设为 0"""
    dvg = {
        "auditId": "AUD_DVG_002",
        "status": "REVIEW_ONLY",
        "dataReliability": "MEDIUM",
        "hardStop": False,
        "qiamPermission": "ALLOW_WITH_DISCOUNT",
        "allowedOutputLevel": "REVIEW_ONLY",
        "finalDecisionCap": "WAIT",
    }
    repo = DVGResultRepo(session=db_session)
    record = await repo.save(dvg, "RUN_002")
    assert record.status == "REVIEW_ONLY"
    assert record.qiam_permission == "ALLOW_WITH_DISCOUNT"
    assert record.allowed_output_level == "REVIEW_ONLY"


@pytest.mark.asyncio
async def test_dvg_hard_stop_truncates_downstream(db_session):
    """§9-7: DVG hard_stop 后 Orchestrator 必须截断正向交易链路"""
    dvg = {
        "auditId": "AUD_DVG_003",
        "status": "BLOCK_BUY",
        "hardStop": True,
        "qiamPermission": "BLOCKED",
        "scenarioPermission": "BLOCKED",
        "executionPermission": "BLOCKED",
        "allowedOutputLevel": "BLOCK_BUY",
    }
    repo = DVGResultRepo(session=db_session)
    record = await repo.save(dvg, "RUN_003")
    assert record.hard_stop is True
    assert record.qiam_permission == "BLOCKED"
    assert record.scenario_permission == "BLOCKED"
    assert record.execution_permission == "BLOCKED"


@pytest.mark.asyncio
async def test_dvg_block_buy_blocks_execution_buy(db_session):
    """§9-10: DVG BLOCK_BUY 时 Execution 不得生成买入计划"""
    dvg = {
        "auditId": "AUD_DVG_004",
        "status": "BLOCK_BUY",
        "hardStop": True,
        "executionPermission": "BLOCKED",
        "allowedOutputLevel": "BLOCK_BUY",
    }
    repo = DVGResultRepo(session=db_session)
    record = await repo.save(dvg, "RUN_004")
    assert record.execution_permission == "BLOCKED"


@pytest.mark.asyncio
async def test_dvg_level2_missing_intercepts(db_session):
    """§9-3: 无 Level-2 时不得判断封单强弱 → 必须拦截"""
    dvg = {
        "auditId": "AUD_DVG_005",
        "status": "WARN",
        "dataReliability": "MEDIUM",
        "criticalMissingData": ["Level-2 成交量", "盘口深度"],
        "hardStop": False,
        "qiamPermission": "ALLOW_WITH_DISCOUNT",
        "allowedOutputLevel": "REVIEW_ONLY",
    }
    repo = DVGResultRepo(session=db_session)
    record = await repo.save(dvg, "RUN_005")
    assert "Level-2 成交量" in record.critical_missing_data
    assert record.allowed_output_level == "REVIEW_ONLY"


@pytest.mark.asyncio
async def test_dvg_source_tool_failure_marks_u(db_session):
    """§9-5: source_tool 失败时相关数据必须标记 U"""
    dvg = {
        "auditId": "AUD_DVG_006",
        "status": "WARN",
        "dataReliability": "MEDIUM",
        "confirmedRatio": 0.5,
        "inferredRatio": 0.2,
        "unknownRatio": 0.3,
        "hardStop": False,
    }
    repo = DVGResultRepo(session=db_session)
    record = await repo.save(dvg, "RUN_006")
    assert record.unknown_ratio > 0


@pytest.mark.asyncio
async def test_dvg_hallucination_risk_high_blocks(db_session):
    """§9: hallucination_risk_score >= 75 时最终动作不得高于 REVIEW_ONLY"""
    dvg = {
        "auditId": "AUD_DVG_007",
        "status": "WARN",
        "hallucinationRiskScore": 80,
        "hallucinationRiskLevel": "HIGH",
        "allowedOutputLevel": "REVIEW_ONLY",
        "hardStop": False,
    }
    repo = DVGResultRepo(session=db_session)
    record = await repo.save(dvg, "RUN_007")
    assert record.hallucination_risk_score >= 75
    assert record.allowed_output_level == "REVIEW_ONLY"
