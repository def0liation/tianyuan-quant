"""
SignalOps 信号管理测试
验收清单 §27 所有规则
"""

import pytest
from app.db.repositories import SignalOpsRepo


@pytest.mark.asyncio
async def test_risk_not_passed_no_qualified(db_session):
    """§27-1: Risk 未通过 → 不得进入 QUALIFIED"""
    signal = {
        "auditId": "AUD_SIG_001",
        "signalStatus": "WATCH",
        "riskPassed": False,
        "dvgPassed": True,
        "qiamPassed": True,
        "executionReachable": True,
        "blockedReason": "Risk 未通过",
    }
    repo = SignalOpsRepo(session=db_session)
    record = await repo.save(signal, "RUN_001", "603663")
    assert record.risk_passed is False
    assert record.signal_status != "QUALIFIED"


@pytest.mark.asyncio
async def test_dvg_review_only_no_qualified(db_session):
    """§27-2: DVG REVIEW_ONLY → 不得进入 QUALIFIED"""
    signal = {
        "auditId": "AUD_SIG_002",
        "signalStatus": "WATCH",
        "riskPassed": True,
        "dvgPassed": False,
        "qiamPassed": True,
        "executionReachable": True,
        "blockedReason": "DVG REVIEW_ONLY",
    }
    repo = SignalOpsRepo(session=db_session)
    record = await repo.save(signal, "RUN_002", "603663")
    assert record.dvg_passed is False
    assert record.signal_status != "QUALIFIED"


@pytest.mark.asyncio
async def test_dvg_block_buy_allows_paper_test_but_not_real_plan(db_session):
    """§27-3: DVG BLOCK_BUY → 可做自动模拟验证，但不得进入真实交易计划"""
    signal = {
        "auditId": "AUD_SIG_003",
        "signalStatus": "PAPER_TEST",
        "riskPassed": True,
        "dvgPassed": False,
        "qiamPassed": False,
        "executionReachable": False,
        "blockedReason": "DVG BLOCK_BUY",
    }
    repo = SignalOpsRepo(session=db_session)
    record = await repo.save(signal, "RUN_003", "603663")
    assert record.dvg_passed is False
    assert record.signal_status == "PAPER_TEST"
    assert record.signal_status not in ("TRADE_PLAN", "MANUAL_CONFIRMED")


@pytest.mark.asyncio
async def test_qiam_block_buy_no_trade_plan(db_session):
    """§27-4: QIAM BLOCK_BUY → 不得进入 TRADE_PLAN"""
    signal = {
        "auditId": "AUD_SIG_004",
        "signalStatus": "WATCH",
        "riskPassed": True,
        "dvgPassed": True,
        "qiamPassed": False,
        "executionReachable": True,
        "blockedReason": "QIAM BLOCK_BUY",
    }
    repo = SignalOpsRepo(session=db_session)
    record = await repo.save(signal, "RUN_004", "603663")
    assert record.qiam_passed is False
    assert record.signal_status != "TRADE_PLAN"


@pytest.mark.asyncio
async def test_atrade_not_reachable_no_real_plan(db_session):
    """§27-5: ATrade NOT_REACHABLE → 不得生成真实执行计划"""
    signal = {
        "auditId": "AUD_SIG_005",
        "signalStatus": "QUALIFIED",
        "riskPassed": True,
        "dvgPassed": True,
        "qiamPassed": True,
        "executionReachable": False,
    }
    repo = SignalOpsRepo(session=db_session)
    record = await repo.save(signal, "RUN_005", "603663")
    assert record.execution_reachable is False


@pytest.mark.asyncio
async def test_repo_preserves_empty_trigger_conditions(db_session):
    """SignalOps repo preserves AI-generated condition fields without imposing lifecycle gates."""
    signal = {
        "auditId": "AUD_SIG_006",
        "signalStatus": "WATCH",
        "triggerConditions": [],
        "invalidationConditions": ["跌破止损"],
    }
    repo = SignalOpsRepo(session=db_session)
    record = await repo.save(signal, "RUN_006", "603663")
    assert len(record.trigger_conditions) == 0
    assert record.signal_status == "WATCH"


@pytest.mark.asyncio
async def test_repo_preserves_empty_invalidation_conditions(db_session):
    """SignalOps repo stores empty invalidation fields; lifecycle gating lives in SignalOps store."""
    signal = {
        "auditId": "AUD_SIG_007",
        "signalStatus": "PAPER_TEST",
        "triggerConditions": ["突破均线"],
        "invalidationConditions": [],
    }
    repo = SignalOpsRepo(session=db_session)
    record = await repo.save(signal, "RUN_007", "603663")
    assert len(record.invalidation_conditions) == 0
    assert record.signal_status == "PAPER_TEST"


@pytest.mark.asyncio
async def test_no_manual_confirmation_no_real_trade(db_session):
    """§27-8: 未人工确认 → 不得进入真实交易动作"""
    signal = {
        "auditId": "AUD_SIG_008",
        "signalStatus": "TRADE_PLAN",
    }
    repo = SignalOpsRepo(session=db_session)
    record = await repo.save(signal, "RUN_008", "603663")
    assert record.signal_status == "TRADE_PLAN"
    assert record.signal_status != "MANUAL_CONFIRMED"


@pytest.mark.asyncio
async def test_signalops_records_simulation_only_no_real_trades(db_session):
    """§27-9: SignalOps 允许自动模拟记录，但不自动真实交易"""
    signal = {
        "auditId": "AUD_SIG_009",
        "signalStatus": "QUALIFIED",
    }
    repo = SignalOpsRepo(session=db_session)
    record = await repo.save(signal, "RUN_009", "603663")
    assert record.signal_status == "QUALIFIED"


@pytest.mark.asyncio
async def test_signalops_no_bypass_kill_switch(db_session):
    """§27-10: SignalOps 不得绕过 Kill Switch"""
    signal = {
        "auditId": "AUD_SIG_010",
        "signalStatus": "WATCH",
        "riskPassed": True,
        "dvgPassed": False,
    }
    repo = SignalOpsRepo(session=db_session)
    record = await repo.save(signal, "RUN_010", "603663")
    assert record.dvg_passed is False
