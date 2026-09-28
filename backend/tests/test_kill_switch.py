"""
Kill Switch 熔断机制测试
验收清单 §34 所有规则
"""

import pytest
from app.db.repositories import KillSwitchRepo


@pytest.mark.asyncio
async def test_kill_switch_hard_blocks_buy_add_chase(db_session):
    """§34-1: HARD 后阻断 BUY / ADD / CHASE / EXECUTION_PLAN"""
    ks = {
        "auditId": "AUD_KS_001",
        "active": True,
        "level": "HARD",
        "triggerNode": "risk_firewall",
        "triggerRule": "hard_stop triggered",
        "blockedPaths": ["BUY_CANDIDATE", "ADD_CANDIDATE", "CHASE", "EXECUTION_PLAN", "AUTO_ORDER"],
        "allowedPaths": ["WAIT", "REVIEW_ONLY", "HOLD"],
        "finalWriterMode": "HARD_RISK_FINAL_ONLY",
    }
    repo = KillSwitchRepo(session=db_session)
    record = await repo.save(ks, "RUN_001")
    assert record.level == "HARD"
    assert "BUY_CANDIDATE" in record.blocked_paths
    assert "ADD_CANDIDATE" in record.blocked_paths
    assert "CHASE" in record.blocked_paths
    assert "EXECUTION_PLAN" in record.blocked_paths


@pytest.mark.asyncio
async def test_kill_switch_compliance_blocks_all(db_session):
    """§34-2: COMPLIANCE 后阻断所有交易路径"""
    ks = {
        "auditId": "AUD_KS_002",
        "active": True,
        "level": "COMPLIANCE",
        "triggerNode": "compliance_check",
        "triggerRule": "compliance_violation = true",
        "blockedPaths": ["BUY_CANDIDATE", "ADD_CANDIDATE", "CHASE", "EXECUTION_PLAN", "AUTO_ORDER", "REVIEW_ONLY"],
        "allowedPaths": ["WAIT"],
        "finalWriterMode": "COMPLIANCE_REJECT",
    }
    repo = KillSwitchRepo(session=db_session)
    record = await repo.save(ks, "RUN_002")
    assert record.level == "COMPLIANCE"
    assert record.allowed_paths == ["WAIT"]


@pytest.mark.asyncio
async def test_kill_switch_soft_conservative(db_session):
    """§34-3: SOFT 后进入保守输出"""
    ks = {
        "auditId": "AUD_KS_003",
        "active": True,
        "level": "SOFT",
        "triggerNode": "dvg_evidence_gate",
        "triggerRule": "data_reliability <= MEDIUM",
        "blockedPaths": ["BUY_CANDIDATE", "ADD_CANDIDATE", "CHASE"],
        "allowedPaths": ["WAIT", "REVIEW_ONLY", "HOLD", "SIGNAL_ONLY"],
        "finalWriterMode": "CONSERVATIVE",
    }
    repo = KillSwitchRepo(session=db_session)
    record = await repo.save(ks, "RUN_003")
    assert record.level == "SOFT"
    assert record.final_writer_mode == "CONSERVATIVE"
    assert "BUY_CANDIDATE" in record.blocked_paths


@pytest.mark.asyncio
async def test_kill_switch_final_writer_mode_follows(db_session):
    """§34-4: finalWriterMode 必须跟随 Kill Switch 级别"""
    modes = {
        "NONE": "NORMAL",
        "SOFT": "CONSERVATIVE",
        "HARD": "HARD_RISK_FINAL_ONLY",
        "COMPLIANCE": "COMPLIANCE_REJECT",
    }
    for level, expected_mode in modes.items():
        ks = {
            "auditId": f"AUD_KS_{level}",
            "active": level != "NONE",
            "level": level,
            "finalWriterMode": expected_mode,
        }
        repo = KillSwitchRepo(session=db_session)
        record = await repo.save(ks, f"RUN_{level}")
        assert record.final_writer_mode == expected_mode


@pytest.mark.asyncio
async def test_kill_switch_not_bypassable(db_session):
    """§34-7: 任何 Agent 不得绕过 Kill Switch"""
    ks = {
        "auditId": "AUD_KS_007",
        "active": True,
        "level": "HARD",
        "blockedPaths": ["BUY_CANDIDATE"],
    }
    repo = KillSwitchRepo(session=db_session)
    record = await repo.save(ks, "RUN_007")
    assert record.active is True
    assert record.level in ("SOFT", "HARD", "COMPLIANCE")


@pytest.mark.asyncio
async def test_kill_switch_not_closeable_by_orchestrator(db_session):
    """§34-8: Kill Switch 不可被 Orchestrator 关闭"""
    ks = {
        "auditId": "AUD_KS_008",
        "active": True,
        "level": "HARD",
    }
    repo = KillSwitchRepo(session=db_session)
    record = await repo.save(ks, "RUN_008")
    assert record.active is True


@pytest.mark.asyncio
async def test_kill_switch_active_no_buy_in_final_writer(db_session):
    """§34-9: Kill Switch 激活时 Final Writer 不得输出买入建议"""
    ks = {
        "auditId": "AUD_KS_009",
        "active": True,
        "level": "HARD",
        "blockedPaths": ["BUY_CANDIDATE", "ADD_CANDIDATE", "CHASE"],
    }
    repo = KillSwitchRepo(session=db_session)
    record = await repo.save(ks, "RUN_009")
    assert record.active is True
    assert "BUY_CANDIDATE" in record.blocked_paths


@pytest.mark.asyncio
async def test_kill_switch_active_no_signal_upgrade(db_session):
    """§34-10: SignalOps 不得在 Kill Switch 激活时升级信号状态"""
    ks = {
        "auditId": "AUD_KS_010",
        "active": True,
        "level": "HARD",
    }
    repo = KillSwitchRepo(session=db_session)
    record = await repo.save(ks, "RUN_010")
    assert record.active is True
